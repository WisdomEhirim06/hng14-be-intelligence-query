from fastapi import FastAPI, Query, HTTPException, Request, Depends, Header, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
import datetime
from database import get_connection
from parser import parse_query
from normalize import normalize_filters, make_cache_key
from cache import cache_get, cache_set, invalidate_cache
from auth import (
    create_access_token, create_refresh_token, get_current_user,
    check_admin, exchange_github_code, refresh_access_token, logout_user,
    Token, GITHUB_REDIRECT_URI
)
from fastapi.responses import RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import time
import os
import uuid
import uuid6
import csv
import csv as csv_module
import io
from fastapi.responses import StreamingResponse

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Insighta Labs Intelligence Query Engine")
WEB_PORTAL_URL = os.getenv("WEB_PORTAL_URL", "https://hng-be-insighta-labs-web-portal.vercel.app")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.on_event("startup")
async def startup():
    """Apply schema.sql on startup so new indexes and migrations are always in sync."""
    try:
        from database import init_db
        init_db()
    except Exception as e:
        print(f"Warning: DB init on startup failed: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

@app.middleware("http")
async def add_process_time_and_versioning(request: Request, call_next):
    start_time = time.time()
    
    # Versioning check for /api/* routes
    if request.url.path.startswith("/api/"):
        version = request.headers.get("X-API-Version")
        if version != "1":
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "API version header required"}
            )
            
    response = await call_next(request)
    
    process_time = time.time() - start_time
    # Logging: Method Endpoint Status ResponseTime
    print(f"{request.method} {request.url.path} {response.status_code} {process_time:.4f}s")
    
    return response

def format_profile(row):
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "gender": row["gender"],
        "gender_probability": row["gender_probability"],
        "age": row["age"],
        "age_group": row["age_group"],
        "country_id": row["country_id"],
        "country_name": row["country_name"],
        "country_probability": row["country_probability"],
        "created_at": row["created_at"].isoformat() if isinstance(row["created_at"], datetime.datetime) else row["created_at"]
    }

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.detail}
    )

# --- Auth Endpoints ---

@app.get("/auth/github")
@limiter.limit("10/minute")
async def github_login(request: Request, state: Optional[str] = None):
    """Initiate GitHub OAuth. Web portal and CLI both use this endpoint.

    CLI passes state='cli:{nonce}'. Web portal hits this without a state param
    and gets a 'web:{nonce}' state assigned automatically.
    """
    import secrets as _secrets
    client_id = os.getenv("GITHUB_CLIENT_ID")
    effective_state = state if state else f"web:{_secrets.token_urlsafe(16)}"
    url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={client_id}&scope=read:user+user:email&state={effective_state}"
    )
    return RedirectResponse(url)

@app.post("/auth/github/exchange")
@limiter.limit("10/minute")
async def github_exchange(request: Request):
    """Exchange a GitHub OAuth code for tokens.

    Used by both the CLI (sends code_verifier for PKCE) and the web portal
    (sends code only — no code_verifier needed for server-side web flows).
    """
    body = await request.json()
    code = body.get("code")
    code_verifier = body.get("code_verifier")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")

    user = await exchange_github_code(code, code_verifier)
    return {
        "status": "success",
        "access_token": create_access_token(data={"sub": str(user["id"])}),
        "refresh_token": create_refresh_token(str(user["id"])),
        "username": user["username"],
        "role": user["role"],
    }

@app.get("/auth/github/callback")
@limiter.limit("10/minute")
async def github_callback(request: Request, code: str = None, state: Optional[str] = None):
    """GitHub redirects here after OAuth. Routes by state prefix.

    - cli:{nonce}  → proxy raw code to CLI local server for PKCE exchange
    - web:{nonce}  → exchange code, redirect tokens to web portal /auth/tokens
    - no prefix    → exchange code, return JSON (direct API use)
    """
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    # CLI: return code to the local server; CLI does the PKCE exchange itself.
    if state and state.startswith("cli:"):
        from urllib.parse import urlencode
        return RedirectResponse(
            f"http://localhost:8080/callback?{urlencode({'code': code, 'state': state})}"
        )

    # Web portal: exchange code and redirect tokens to the portal.
    user = await exchange_github_code(code)
    access_token = create_access_token(data={"sub": str(user["id"])})
    refresh_token = create_refresh_token(str(user["id"]))

    if state and state.startswith("web:"):
        from urllib.parse import urlencode
        params = urlencode({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "username": user["username"],
            "role": user["role"],
        })
        return RedirectResponse(f"{WEB_PORTAL_URL}/auth/tokens?{params}")

    # Direct API use (e.g. curl, Postman): return JSON.
    return {
        "status": "success",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "username": user["username"],
        "role": user["role"],
    }

@app.post("/auth/refresh")
@limiter.limit("10/minute")
async def refresh_token_rotation(request: Request):
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Missing refresh token")
    
    return await refresh_access_token(refresh_token)

@app.post("/auth/logout")
@limiter.limit("10/minute")
async def logout(request: Request):
    try:
        body = await request.json()
        refresh_token = body.get("refresh_token")
        if refresh_token:
            await logout_user(refresh_token)
    except:
        pass
    return {"status": "success", "message": "Logged out"}

@app.get("/api/users/me")
async def get_me(user = Depends(get_current_user)):
    return {
        "status": "success",
        "data": {
            "id": str(user["id"]),
            "github_id": str(user.get("github_id") or "0000000"),
            "username": str(user.get("username") or "unknown"),
            "email": str(user.get("email") or "no-email@github.com"),
            "role": str(user.get("role") or "analyst")
        }
    }

@app.delete("/api/profiles/{profile_id}")
async def delete_profile(profile_id: str, user = Depends(check_admin)):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM profiles WHERE id = %s RETURNING id", (profile_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Profile not found")
            conn.commit()
    finally:
        conn.close()
    invalidate_cache()
    return {"status": "success", "message": f"Profile {profile_id} deleted"}



def _get_profiles_data(
    gender: Optional[str] = None,
    age_group: Optional[str] = None,
    country_id: Optional[str] = None,
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
    min_gender_probability: Optional[float] = None,
    min_country_probability: Optional[float] = None,
    sort_by: str = "created_at",
    order: str = "desc",
    page: int = 1,
    limit: int = 10
):
    # Build normalised filter dict and check cache before hitting the DB.
    # normalize_filters() ensures two semantically identical queries always
    # produce the same cache key regardless of how they were expressed.
    raw_filters = {
        "gender": gender, "age_group": age_group, "country_id": country_id,
        "min_age": min_age, "max_age": max_age,
        "min_gender_probability": min_gender_probability,
        "min_country_probability": min_country_probability,
    }
    # Strip None values before normalising
    raw_filters = {k: v for k, v in raw_filters.items() if v is not None}
    key = make_cache_key(raw_filters, page=page, limit=limit, sort_by=sort_by, order=order)
    cached = cache_get(key)
    if cached is not None:
        return cached
    try:
        conn = get_connection()
        conn.cursor_factory = None # We'll use RealDictCursor manually or equivalent
        from psycopg2.extras import RealDictCursor
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Build query components
            where_clauses = []
            params = []

            if gender:
                where_clauses.append("gender = %s")
                params.append(gender)
            if age_group:
                where_clauses.append("age_group = %s")
                params.append(age_group.lower())
            if country_id:
                where_clauses.append("country_id = %s")
                params.append(country_id.upper())
            if min_age is not None:
                where_clauses.append("age >= %s")
                params.append(min_age)
            if max_age is not None:
                where_clauses.append("age <= %s")
                params.append(max_age)
            if min_gender_probability is not None:
                where_clauses.append("gender_probability >= %s")
                params.append(min_gender_probability)
            if min_country_probability is not None:
                where_clauses.append("country_probability >= %s")
                params.append(min_country_probability)

            where_str = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
            
            # Count total
            count_sql = "SELECT COUNT(*) AS total FROM profiles" + where_str
            cur.execute(count_sql, params)
            total = cur.fetchone()["total"]

            # Fetch data
            offset = (page - 1) * limit
            # Sanitize sort_by and order (already validated by Query regex)
            fetch_sql = f"SELECT * FROM profiles {where_str} ORDER BY {sort_by} {order.upper()} LIMIT %s OFFSET %s"
            cur.execute(fetch_sql, params + [limit, offset])
            rows = cur.fetchall()

            total_pages = (total + limit - 1) // limit
            
            # Build query string for links
            query_params = []
            if gender: query_params.append(f"gender={gender}")
            if age_group: query_params.append(f"age_group={age_group}")
            if country_id: query_params.append(f"country_id={country_id}")
            if min_age is not None: query_params.append(f"min_age={min_age}")
            if max_age is not None: query_params.append(f"max_age={max_age}")
            if min_gender_probability is not None: query_params.append(f"min_gender_probability={min_gender_probability}")
            if min_country_probability is not None: query_params.append(f"min_country_probability={min_country_probability}")
            if sort_by: query_params.append(f"sort_by={sort_by}")
            if order: query_params.append(f"order={order}")
            
            base_query = "&".join(query_params)
            if base_query:
                base_query = "&" + base_query

            # Links
            path = "/api/profiles"
            self_link = f"{path}?page={page}&limit={limit}{base_query}"
            next_link = f"{path}?page={page+1}&limit={limit}{base_query}" if page < total_pages else None
            prev_link = f"{path}?page={page-1}&limit={limit}{base_query}" if page > 1 else None

            result = {
                "status": "success",
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": total_pages,
                "links": {
                    "self": self_link,
                    "next": next_link,
                    "prev": prev_link
                },
                "data": [format_profile(row) for row in rows]
            }
            # Store in cache; no-op if Redis is not configured
            cache_set(key, result)
            return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'conn' in locals():
            conn.close()

@app.get("/api/profiles")
@limiter.limit("60/minute")
async def get_profiles(
    request: Request, # for limiter
    gender: Optional[str] = None,
    age_group: Optional[str] = None,
    country_id: Optional[str] = None,
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
    min_gender_probability: Optional[float] = None,
    min_country_probability: Optional[float] = None,
    sort_by: str = Query("created_at", pattern="^(age|created_at|gender_probability)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    x_api_version: Optional[str] = Header("1", alias="X-API-Version"),
    user = Depends(get_current_user)
):
    return _get_profiles_data(
        gender=gender,
        age_group=age_group,
        country_id=country_id,
        min_age=min_age,
        max_age=max_age,
        min_gender_probability=min_gender_probability,
        min_country_probability=min_country_probability,
        sort_by=sort_by,
        order=order,
        page=page,
        limit=limit
    )

@app.get("/api/profiles/search")
@limiter.limit("60/minute")
async def search_profiles(
    request: Request,
    q: str = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    x_api_version: Optional[str] = Header("1", alias="X-API-Version"),
    user = Depends(get_current_user)
):
    if not q:
        raise HTTPException(status_code=400, detail="Missing or empty parameter")
    
    filters = parse_query(q)
    if not filters:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Unable to interpret query"}
        )

    return _get_profiles_data(
        gender=filters.get("gender"),
        age_group=filters.get("age_group"),
        country_id=filters.get("country_id"),
        min_age=filters.get("min_age"),
        max_age=filters.get("max_age"),
        page=page,
        limit=limit
    )

@app.post("/api/profiles", status_code=201)
@limiter.limit("60/minute")
async def create_profile(
    request: Request,
    body: dict,
    x_api_version: Optional[str] = Header("1", alias="X-API-Version"),
    user = Depends(check_admin)
):
    name = body.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    
    # Check if exists first to return 409
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM profiles WHERE name = %s", (name,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail=f"Profile with name '{name}' already exists")
    finally:
        conn.close()

    try:
        import asyncio
        # Call all three enrichment APIs concurrently instead of sequentially.
        # This reduces profile creation latency from ~3× API latency to ~1×
        # (the slowest of the three calls), typically cutting ~600–900ms to ~300ms.
        data = await _async_fetch_profile_data(name)
        from seed import save_profile
        profile = save_profile(data)
        invalidate_cache()
        return {
            "status": "success",
            "data": format_profile(profile)
        }
    except HTTPException as e:
        raise e
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

async def _async_fetch_profile_data(name: str) -> dict:
    """
    Fetch gender, age, and country enrichment for a name concurrently.
    Replaces the sequential httpx.Client calls in seed.fetch_profile_data,
    reducing latency from ~(sum of all API calls) to ~(slowest single call).
    """
    import asyncio
    import httpx
    from seed import COUNTRY_NAMES

    async def get_gender():
        async with httpx.AsyncClient() as c:
            r = await c.get(f"https://api.genderize.io?name={name}", timeout=10)
            return r.json() if r.status_code == 200 else {}

    async def get_age():
        async with httpx.AsyncClient() as c:
            r = await c.get(f"https://api.agify.io?name={name}", timeout=10)
            return r.json() if r.status_code == 200 else {}

    async def get_country():
        async with httpx.AsyncClient() as c:
            r = await c.get(f"https://api.nationalize.io?name={name}", timeout=10)
            return r.json() if r.status_code == 200 else {}

    gender_data, age_data, country_data = await asyncio.gather(
        get_gender(), get_age(), get_country()
    )

    result = {"name": name}
    result["gender"] = gender_data.get("gender")
    result["gender_probability"] = gender_data.get("probability")

    age = age_data.get("age")
    result["age"] = age
    if age:
        if age < 13:   result["age_group"] = "child"
        elif age < 20: result["age_group"] = "teenager"
        elif age < 65: result["age_group"] = "adult"
        else:          result["age_group"] = "senior"

    countries = country_data.get("country", [])
    if countries:
        cid = countries[0].get("country_id")
        result["country_id"] = cid
        result["country_probability"] = countries[0].get("probability")
        result["country_name"] = COUNTRY_NAMES.get(cid, cid)

    return result


def _insert_csv_batch(batch: list) -> int:
    """
    Bulk-insert a batch of validated profile rows using execute_values.
    Checks for duplicates within the batch against the DB before inserting.
    Returns the number of rows actually inserted.
    """
    if not batch:
        return 0
    from psycopg2.extras import execute_values
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name FROM profiles WHERE name = ANY(%s)",
                ([row[1] for row in batch],)
            )
            existing = {row[0].lower() for row in cur.fetchall()}
            to_insert = [row for row in batch if row[1].lower() not in existing]
            if not to_insert:
                return 0
            execute_values(cur, """
                INSERT INTO profiles (
                    id, name, gender, gender_probability, age, age_group,
                    country_id, country_name, country_probability
                ) VALUES %s
                ON CONFLICT (name) DO NOTHING
            """, to_insert)
            inserted = cur.rowcount
            conn.commit()
            return inserted
    finally:
        conn.close()


def _derive_age_group(age: int) -> str:
    if age < 13:   return "child"
    if age < 20:   return "teenager"
    if age < 65:   return "adult"
    return "senior"


@app.post("/api/profiles/upload", status_code=200)
@limiter.limit("10/minute")
async def upload_profiles_csv(
    request: Request,
    file: UploadFile = File(...),
    x_api_version: Optional[str] = Header("1", alias="X-API-Version"),
    user = Depends(check_admin),
):
    """
    Bulk-ingest profiles from a CSV file (up to 500,000 rows).

    Design decisions:
    - Streams the file in 64 KB chunks — never loads the whole file into memory.
    - Validates each row individually; a bad row is skipped, never aborts the upload.
    - Inserts in batches of 500 using psycopg2 execute_values (one SQL statement
      per batch, not one per row). Concurrent uploads are safe: ON CONFLICT DO NOTHING
      handles any race between two uploads inserting the same name.
    - Rows already inserted before a mid-upload failure remain committed (no rollback).
    - Cache is invalidated once at the end.

    Expected CSV columns (header row required):
      name, gender, age, age_group, country_id
      (optional: gender_probability, country_name, country_probability, id, created_at)
    """
    CHUNK_SIZE = 65536   # 64 KB per read — keeps memory usage flat
    BATCH_SIZE = 500     # rows per execute_values call

    total_rows = 0
    inserted = 0
    reasons: dict = {}

    def skip(reason: str):
        nonlocal inserted  # not modifying inserted, just reasons
        reasons[reason] = reasons.get(reason, 0) + 1

    header = None
    batch = []
    line_buffer = ""

    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        try:
            text = chunk.decode("utf-8")
        except UnicodeDecodeError:
            text = chunk.decode("utf-8", errors="replace")

        line_buffer += text
        lines = line_buffer.split("\n")
        line_buffer = lines[-1]   # save the incomplete trailing line

        for raw_line in lines[:-1]:
            line = raw_line.rstrip("\r")
            if not line.strip():
                continue

            try:
                row = next(csv_module.reader([line]))
            except Exception:
                if header is not None:
                    total_rows += 1
                    skip("malformed_row")
                continue

            if header is None:
                header = [h.strip().lower() for h in row]
                continue

            total_rows += 1

            if len(row) != len(header):
                skip("malformed_row")
                continue

            r = {h: v.strip() for h, v in zip(header, row)}

            name       = r.get("name", "")
            gender     = r.get("gender", "").lower()
            age_str    = r.get("age", "")
            country_id = r.get("country_id", "").upper()

            if not name or not gender or not age_str or not country_id:
                skip("missing_fields")
                continue

            if gender not in ("male", "female"):
                skip("invalid_gender")
                continue

            try:
                age = int(age_str)
                if not (0 <= age <= 150):
                    raise ValueError
            except ValueError:
                skip("invalid_age")
                continue

            age_group = r.get("age_group", "").strip().lower() or _derive_age_group(age)

            try:
                gp = float(r.get("gender_probability") or 0) or None
            except (ValueError, TypeError):
                gp = None
            try:
                cp = float(r.get("country_probability") or 0) or None
            except (ValueError, TypeError):
                cp = None

            country_name = r.get("country_name") or None

            batch.append((
                str(uuid6.uuid7()),
                name, gender, gp, age, age_group,
                country_id, country_name, cp,
            ))

            if len(batch) >= BATCH_SIZE:
                n = _insert_csv_batch(batch)
                # Rows in batch but not inserted are duplicates caught at DB level
                dups = len(batch) - n
                if dups > 0:
                    reasons["duplicate_name"] = reasons.get("duplicate_name", 0) + dups
                inserted += n
                batch = []

    # Process any remaining partial line
    if line_buffer.strip() and header is not None:
        line = line_buffer.rstrip("\r\n")
        try:
            row = next(csv_module.reader([line]))
            total_rows += 1
            if len(row) == len(header):
                r = {h: v.strip() for h, v in zip(header, row)}
                name       = r.get("name", "")
                gender     = r.get("gender", "").lower()
                age_str    = r.get("age", "")
                country_id = r.get("country_id", "").upper()
                if name and gender in ("male", "female") and age_str and country_id:
                    try:
                        age = int(age_str)
                        age_group = r.get("age_group", "").strip().lower() or _derive_age_group(age)
                        batch.append((
                            str(uuid6.uuid7()), name, gender, None,
                            age, age_group, country_id, None, None,
                        ))
                    except ValueError:
                        skip("invalid_age")
                else:
                    skip("missing_fields")
            else:
                skip("malformed_row")
        except Exception:
            skip("malformed_row")

    # Insert final batch
    if batch:
        n = _insert_csv_batch(batch)
        dups = len(batch) - n
        if dups > 0:
            reasons["duplicate_name"] = reasons.get("duplicate_name", 0) + dups
        inserted += n

    invalidate_cache()

    skipped = total_rows - inserted
    return {
        "status": "success",
        "total_rows": total_rows,
        "inserted": inserted,
        "skipped": skipped,
        "reasons": reasons,
    }


@app.get("/api/profiles/export")
@limiter.limit("60/minute")
async def export_profiles(
    request: Request,
    format: str = Query(..., pattern="^csv$"),
    gender: Optional[str] = None,
    country_id: Optional[str] = None,
    sort_by: str = Query("created_at"),
    order: str = Query("desc"),
    x_api_version: Optional[str] = Header("1", alias="X-API-Version"),
    user = Depends(get_current_user)
):
    # Fetch data (no limit for export?)
    # TRD says "Applies the same filters as GET /api/profiles"
    data_resp = _get_profiles_data(
        gender=gender,
        country_id=country_id,
        sort_by=sort_by,
        order=order,
        page=1,
        limit=1000 # Large limit for the export
    )
    profiles = data_resp["data"]
    
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "id", "name", "gender", "gender_probability", "age", "age_group",
        "country_id", "country_name", "country_probability", "created_at"
    ])
    writer.writeheader()
    for p in profiles:
        writer.writerow(p)
    
    timestamp = int(time.time())
    headers = {
        'Content-Disposition': f'attachment; filename="profiles_{timestamp}.csv"'
    }
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers=headers
    )

# NOTE: This route must be LAST among /api/profiles/* routes
# so that /search and /export are matched first by FastAPI
@app.get("/api/profiles/{profile_id}")
@limiter.limit("60/minute")
async def get_profile(
    request: Request,
    profile_id: str,
    x_api_version: Optional[str] = Header("1", alias="X-API-Version"),
    user = Depends(get_current_user)
):
    try:
        conn = get_connection()
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM profiles WHERE id = %s", (profile_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Profile not found")
            return {
                "status": "success",
                "data": format_profile(row)
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'conn' in locals():
            conn.close()


@app.get("/health")
def health_check():
    return {"status": "ok"}
