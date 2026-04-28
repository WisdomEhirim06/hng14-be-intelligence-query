import os
import datetime
from typing import Optional
from jose import JWTError, jwt
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer, HTTPBearer
import httpx
from database import get_connection
import uuid6
from pydantic import BaseModel

from dotenv import load_dotenv

# Configuration from environment
load_dotenv()
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_MINUTES = 60

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_REDIRECT_URI = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8000/auth/github/callback")

oauth2_scheme = HTTPBearer()

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(user_id: str):
    token = str(uuid6.uuid7())
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES)
    
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO refresh_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)",
                (user_id, token, expire)
            )
            conn.commit()
    finally:
        conn.close()
    
    return token

def verify_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

async def get_current_user(token = Depends(oauth2_scheme)):
    payload = verify_token(token.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    
    conn = get_connection()
    try:
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cur.fetchone()
            if not user:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
            if not user["is_active"]:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
            return user
    finally:
        conn.close()

def check_admin(user = Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user

async def exchange_github_code(code: str, code_verifier: Optional[str] = None, redirect_uri: Optional[str] = None):
    async with httpx.AsyncClient() as client:
        # Step 1: Exchange code for GitHub access token
        payload = {
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": redirect_uri or GITHUB_REDIRECT_URI
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier
            
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data=payload
        )
        data = resp.json()
        if "error" in data:
            raise HTTPException(status_code=400, detail=data.get("error_description", "OAuth error"))
        
        github_token = data["access_token"]
        
        # Step 2: Get user info
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {github_token}"}
        )
        user_data = user_resp.json()
        
        # Step 3: Create or update user in DB
        return await sync_user_to_db(user_data)

async def sync_user_to_db(github_user: dict):
    conn = get_connection()
    try:
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            github_id = str(github_user["id"])
            username = github_user["login"]
            email = github_user.get("email")
            avatar_url = github_user.get("avatar_url")
            
            # Check if user exists
            cur.execute("SELECT * FROM users WHERE github_id = %s", (github_id,))
            user = cur.fetchone()
            
            now = datetime.datetime.now(datetime.timezone.utc)
            
            if user:
                user_id = user["id"]
                cur.execute(
                    "UPDATE users SET last_login_at = %s, username = %s, email = %s, avatar_url = %s WHERE id = %s RETURNING *",
                    (now, username, email, avatar_url, user_id)
                )
            else:
                user_id = str(uuid6.uuid7())
                # First user is admin (optional logic, but let's default to analyst as per TRD)
                # Check if any users exist
                cur.execute("SELECT COUNT(*) as count FROM users")
                is_first = cur.fetchone()["count"] == 0
                role = "admin" if is_first else "analyst"
                
                cur.execute(
                    "INSERT INTO users (id, github_id, username, email, avatar_url, role, last_login_at) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
                    (user_id, github_id, username, email, avatar_url, role, now)
                )
            
            user = cur.fetchone()
            conn.commit()
            return user
    finally:
        conn.close()

async def refresh_access_token(refresh_token: str):
    conn = get_connection()
    try:
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Check if token exists and is not expired
            now = datetime.datetime.now(datetime.timezone.utc)
            cur.execute(
                "SELECT * FROM refresh_tokens WHERE token = %s AND expires_at > %s",
                (refresh_token, now)
            )
            rt = cur.fetchone()
            if not rt:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
            
            user_id = str(rt["user_id"])
            
            # Invalidate old token
            cur.execute("DELETE FROM refresh_tokens WHERE token = %s", (refresh_token,))
            
            # Issue new pair
            new_access_token = create_access_token(data={"sub": user_id})
            new_refresh_token = create_refresh_token(user_id)
            
            conn.commit()
            return {
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
                "token_type": "bearer"
            }
    finally:
        conn.close()

async def logout_user(refresh_token: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM refresh_tokens WHERE token = %s", (refresh_token,))
            conn.commit()
    finally:
        conn.close()
