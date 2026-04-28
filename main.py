from fastapi import FastAPI, Query, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
import datetime
from database import get_connection
from parser import parse_query
from auth import (
    create_access_token, create_refresh_token, get_current_user, 
    check_admin, exchange_github_code, refresh_access_token, logout_user,
    Token
)
from fastapi.responses import RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import time
import os
import uuid
import csv
import io
from fastapi.responses import StreamingResponse

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Insighta Labs Intelligence Query Engine")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Custom Middleware for Logging and Versioning
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
async def github_login(request: Request):
    client_id = os.getenv("GITHUB_CLIENT_ID")
    redirect_uri = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8000/auth/github/callback")
    scope = "user:email"
    # For PKCE challenge, web can also use it or just standard flow.
    # The TRD says CLI flow uses PKCE. 
    # For now, let's provide a simple redirect.
    return RedirectResponse(
        f"https://github.com/login/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}&scope={scope}"
    )

@app.post("/auth/github/exchange")
async def github_exchange(request: Request):
    # For CLI: takes code and code_verifier
    body = await request.json()
    code = body.get("code")
    code_verifier = body.get("code_verifier")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")
    
    user = await exchange_github_code(code, code_verifier)
    access_token = create_access_token(data={"sub": user["id"]})
    refresh_token = create_refresh_token(user["id"])
    
    return {
        "status": "success",
        "access_token": access_token,
        "refresh_token": refresh_token
    }

@app.get("/auth/github/callback")
async def github_callback(code: str, state: Optional[str] = None):
    # This handles both Web and CLI if CLI uses this callback.
    # But TRD says CLI sends code+verifier to backend.
    user = await exchange_github_code(code)
    access_token = create_access_token(data={"sub": user["id"]})
    refresh_token = create_refresh_token(user["id"])
    
    return {
        "status": "success",
        "access_token": access_token,
        "refresh_token": refresh_token
    }

@app.post("/auth/refresh", response_model=Token)
@limiter.limit("10/minute")
async def refresh_token_rotation(request: Request):
    body = await request.json()
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Missing refresh token")
    
    return await refresh_access_token(refresh_token)

@app.post("/auth/logout")
async def logout(request: Request):
    body = await request.json()
    refresh_token = body.get("refresh_token")
    if refresh_token:
        await logout_user(refresh_token)
    return {"status": "success", "message": "Logged out"}

@app.get("/api/profiles")
async def get_profiles(
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
    limit: int = Query(10, ge=1, le=50)
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
            
            # Links
            path = "/api/profiles"
            self_link = f"{path}?page={page}&limit={limit}"
            next_link = f"{path}?page={page+1}&limit={limit}" if page < total_pages else None
            prev_link = f"{path}?page={page-1}&limit={limit}" if page > 1 else None

            return {
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

@app.post("/api/profiles")
@limiter.limit("60/minute")
async def create_profile(
    request: Request,
    body: dict,
    user = Depends(check_admin)
):
    name = body.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    
    try:
        from seed import fetch_profile_data, save_profile
        data = fetch_profile_data(name)
        profile = save_profile(data)
        return {
            "status": "success",
            "data": format_profile(profile)
        }
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/profiles/export")
@limiter.limit("60/minute")
async def export_profiles(
    request: Request,
    format: str = Query(..., pattern="^csv$"),
    gender: Optional[str] = None,
    country_id: Optional[str] = None,
    sort_by: str = Query("created_at"),
    order: str = Query("desc"),
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

@app.get("/health")
def health_check():
    return {"status": "ok"}
