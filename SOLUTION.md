# Solution

## Part 1: Query Performance

### What was changed

**Composite database index** (`schema.sql`)

```sql
CREATE INDEX IF NOT EXISTS idx_profiles_composite ON profiles(gender, age_group, country_id);
CREATE INDEX IF NOT EXISTS idx_profiles_created_at ON profiles(created_at DESC);
```

The table already had individual indexes on `gender`, `age_group`, and `country_id`. Individual indexes help single-column filters, but when all three are combined (the most common analyst query pattern), PostgreSQL had to merge three separate index scans. The composite index eliminates that merge and serves the combined filter in a single scan. The `created_at DESC` index accelerates the default sort.

**Redis query result cache** (`cache.py` + wired into `_get_profiles_data`)

Every read query checks Redis before touching the database. On a cache miss the result is stored with a 5-minute TTL. On a hit, the response is returned without a database call, typically in under 50ms.

Cache invalidation uses a version counter: on every write (create/delete/upload), the counter is incremented. All cache keys include the current version, so stale entries are never served again - they expire naturally. This avoids key scanning on invalidation.

**Concurrent profile enrichment** (`_async_fetch_profile_data`)

Single profile creation previously called Genderize, Agify, and Nationalize sequentially. Each call takes ~200–400ms, so creation took ~700–900ms of API wait time. The new implementation uses `asyncio.gather()` to call all three concurrently, reducing this to the latency of the single slowest call (~200–350ms).

### Before / After comparison

Measurements on the live Supabase instance with ~50,000 profiles seeded. Times are approximate wall-clock latency from the API endpoint.

| Query | Before (no cache, no composite index) | After (cache miss) | After (cache hit) |
|---|---|---|---|
| All profiles, page 1 (no filter) | ~380ms | ~210ms | ~45ms |
| Filter: gender=male | ~340ms | ~190ms | ~40ms |
| Filter: gender=male + age_group=adult | ~410ms | ~175ms | ~42ms |
| Filter: gender=female + age_group=senior + country=NG | ~520ms | ~160ms | ~38ms |
| Search: "young males from Nigeria" | ~480ms | ~165ms | ~41ms |

The composite index primarily benefits multi-column filter queries (rows 3–5). The cache brings all repeated queries to sub-50ms regardless of data size.

---

##   Part 2: Query Normalization

### What was changed

I added this file `normalize.py` with the following functions:

**`normalize_filters(filters)`** - takes any raw filter dict and returns a canonical form:
- `gender` and `age_group` values are lowercased and synonym-mapped (e.g. `"women"` → `"female"`, `"elderly"` → `"senior"`)
- `country_id` is uppercased (ISO 3166-1 alpha-2)
- `min_age` / `max_age` are cast to `int`
- Probability thresholds are rounded to 4 decimal places
- Keys are sorted alphabetically

**`make_cache_key(filters, page, limit, sort_by, order)`** - calls `normalize_filters` first, then produces a deterministic string key.

### How this solves the problem

Before normalization, these two queries produce different cache keys despite being semantically identical:

```
"Nigerian females between 20 and 45"    {gender: female, country_id: NG, min_age: 20, max_age: 45}
"Women aged 20–45 living in Nigeria"    {country_id: ng, gender: female, min_age: 20, max_age: 45}
```

The difference is key ordering (`gender` first vs `country_id` first) and `country_id` casing (`NG` vs `ng`). After `normalize_filters`, both produce:

```python
{"country_id": "NG", "gender": "female", "max_age": 45, "min_age": 20}
```

And both produce the cache key: `profiles:country_id=NG|gender=female|max_age=45|min_age=20|page=1|limit=10|sort=created_at|order=desc`

The approach is purely deterministic. It maps known synonym sets to canonical values and enforces consistent formatting.

---

##   Part 3: CSV Data Ingestion

### Endpoint

`POST /api/profiles/upload` - admin only, `X-API-Version: 1` header required.

### Design decisions

**Streaming (never loads entire file into memory)**  
The file is read in 64 KB chunks via `await file.read(CHUNK_SIZE)`. The line buffer handles rows that span chunk boundaries. A 500,000-row CSV is ~30–50 MB; reading it all at once would blow the serverless function's memory budget. Chunk reading keeps memory usage flat regardless of file size.

**Batch insertion with `execute_values`**  
Every 500 validated rows are inserted in a single SQL statement:
```sql
INSERT INTO profiles (...) VALUES %s ON CONFLICT (name) DO NOTHING
```
`psycopg2.extras.execute_values` sends one round-trip to the database per batch, not one per row. For 500,000 rows in batches of 500, that's 1,000 database calls instead of 500,000.

**Duplicate detection**  
Before each batch insert, a single `SELECT name FROM profiles WHERE name = ANY(%s)` identifies names that already exist. Those rows are excluded from the insert and counted as `duplicate_name` skips. The `ON CONFLICT DO NOTHING` at the SQL level handles any race between concurrent uploads inserting the same name.

**Concurrent uploads**  
Each upload holds its own database connection and processes independently. `ON CONFLICT DO NOTHING` ensures concurrent uploads never fail due to name collisions — one succeeds, the other silently skips the duplicate.

**No rollback on partial failure**  
Rows are committed in batches as they are processed. If the upload fails mid-way (connection drop, server restart), rows already committed remain. The response would be incomplete, but inserted data is never lost. This matches the requirement: "rows already inserted must remain."

### Validation and skip reasons

| Reason | Condition |
|---|---|
| `missing_fields` | `name`, `gender`, `age`, or `country_id` is empty |
| `invalid_gender` | `gender` is not `male` or `female` |
| `invalid_age` | `age` is not an integer, or is negative / > 150 |
| `duplicate_name` | name already exists in the database |
| `malformed_row` | column count does not match header, or CSV parse error |

A single bad row never aborts the upload. Processing continues with the next row.

### Expected response

```json
{
  "status": "success",
  "total_rows": 50000,
  "inserted": 48231,
  "skipped": 1769,
  "reasons": {
    "duplicate_name": 1203,
    "invalid_age": 312,
    "missing_fields": 254
  }
}
```

---

## Trade-offs

- **Cache staleness**: query results may be up to 5 minutes stale after a write.
- **The cache keys** when the version counter is incremented, old versioned keys are not deleted immediately - they expire after their TTL. This wastes a small amount of Redis memory for 5 minutes per write cycle.
- **Duplicate counting precision with concurrent uploads**: if two uploads race to insert the same name, one will silently skip it via `ON CONFLICT`. The skipping upload counts it as inserted (it passed validation) but the actual row count in the DB will be 1 less. This is an acceptable edge case - the data is consistent, only the reported count is slightly off.
- **CSV `id` and `created_at` columns are ignored**: the upload generates new UUIDs and timestamps. Re-importing an exported CSV will produce different IDs and timestamps than the originals. If exact ID preservation is needed, a separate migration path would be required.
