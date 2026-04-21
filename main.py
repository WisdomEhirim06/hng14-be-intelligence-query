from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
import datetime
from database import get_connection
from parser import parse_query

app = FastAPI(title="Insighta Labs Intelligence Query Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

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

            return {
                "status": "success",
                "page": page,
                "limit": limit,
                "total": total,
                "data": [format_profile(row) for row in rows]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'conn' in locals():
            conn.close()

@app.get("/api/profiles/search")
async def search_profiles(
    q: str = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50)
):
    if not q:
        raise HTTPException(status_code=400, detail="Missing or empty parameter")
    
    filters = parse_query(q)
    if not filters:
        return JSONResponse(
            status_code=200, # Requirement says success response or error response?
            # Wait, "Queries that can't be interpreted return: { 'status': 'error', 'message': 'Unable to interpret query' }"
            content={"status": "error", "message": "Unable to interpret query"}
        )

    # Use the internal data fetcher
    return _get_profiles_data(
        gender=filters.get("gender"),
        age_group=filters.get("age_group"),
        country_id=filters.get("country_id"),
        min_age=filters.get("min_age"),
        max_age=filters.get("max_age"),
        page=page,
        limit=limit
    )

@app.get("/health")
def health_check():
    return {"status": "ok"}
