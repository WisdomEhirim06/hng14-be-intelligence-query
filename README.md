# Insighta Labs - Intelligence Query Engine

This is the Stage 2 backend task for HNG (Backend Wizards). It implements advanced filtering, sorting, pagination, and a rule-based natural language query (NLQ) engine for demographic data.

## Natural Language Query (NLQ) Approach

### Logic and Keyword Mapping
The parsing logic is **rule-based** and uses regular expressions (Regex) combined with keyword dictionaries to map plain English queries to structured filters.

| Category | Keywords / Logic | Mapping |
|----------|-----------------|---------|
| **Gender** | `male`, `female`, `man`, `woman`, `boy`, `girl` | `gender` filter |
| **Age Group** | `child`, `teenager`, `adult`, `senior` | `age_group` filter |
| **"Young"** | `young` | `min_age=16` AND `max_age=24` |
| **Age Range** | `above X`, `older than X`, `below X`, `younger than X` | `min_age` or `max_age` |
| **Nationality** | `from [country name]` | `country_id` (ISO code) |

**How it works:**
1. The input string is converted to lowercase.
2. A series of regex patterns search for specific keywords for gender, age groups, and "young" status.
3. Age comparisons are extracted using numeric capture groups following comparison keywords (e.g., "above 30" -> `min_age=30`).
4. Country names following "from" are matched against a predefined mapping of common countries to ISO 3166-1 alpha-2 codes.
5. All identified filters are combined and passed to the standard query executor.

### Supported Keywords
- **Genders**: male/males, female/females, man/men, woman/women, boy/boys, girl/girls.
- **Age Groups**: child, teenager/teens, adult, senior.
- **Modifiers**: young (16-24), above/older, below/younger.
- **Countries**: Supports major countries (Nigeria, Kenya, Angola, Ghana, etc.).

## Limitations
- **Compound Logic**: The parser handles simple combinations but does not support complex nested "and/or" logic (e.g., "males from Nigeria OR females from Kenya").
- **Exclusion**: Negative filters (e.g., "not from Nigeria") are not currently supported.
- **Fuzzy Matching**: Country matching is literal and bound to a predefined dictionary; unknown country names will not be parsed.
- **Contextual Ambiguity**: If a query contains conflicting terms (e.g., "child senior"), the parser picks the first matched group or yields unexpected results.

## Endpoints

### 1. Get All Profiles
`GET /api/profiles`
Supports filtering (`gender`, `age_group`, `country_id`, `min_age`, `max_age`, `min_gender_probability`, `min_country_probability`), sorting (`age`, `created_at`, `gender_probability`), and pagination (`page`, `limit`).

### 2. Natural Language Query
`GET /api/profiles/search?q=young males from nigeria`
Parses the query `q` and executes the corresponding filters.

## Tech Stack
- **FastAPI** — High-performance web framework.
- **Psycopg2** — Direct PostgreSQL interaction for Supabase compatibility.
- **Vercel** — Serverless deployment runtime.
- **UUID v7** — Next-gen sortable unique identifiers.
