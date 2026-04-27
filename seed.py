import json
import os
import uuid6
import sys
from database import get_connection, init_db
from datetime import datetime, timezone
from psycopg2.extras import execute_values, RealDictCursor
import httpx

def seed_data():
    # Initialize DB (which now includes column migrations)
    print("Initializing database and checking schema...", flush=True)
    init_db()
    
    # Directly refer to the file in the project directory
    seed_file = os.path.join(os.path.dirname(__file__), "seed_profiles.json")
    
    if not os.path.exists(seed_file):
        print(f"Error: {seed_file} not found in the project directory.", flush=True)
        return

    print(f"Reading data from {seed_file}...", flush=True)
    with open(seed_file, "r") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}", flush=True)
            return

    profiles = data.get("profiles", [])
    total_profiles = len(profiles)
    print(f"Found {total_profiles} profiles to seed.", flush=True)

    print("Connecting to database...", flush=True)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Prepare data for bulk insert
            values = []
            created_at = datetime.now(timezone.utc)
            
            print("Preparing batch for seeding...", flush=True)
            for i, p in enumerate(profiles):
                values.append((
                    str(uuid6.uuid7()),
                    p.get("name"),
                    p.get("gender"),
                    p.get("gender_probability"),
                    p.get("age"),
                    p.get("age_group"),
                    p.get("country_id"),
                    p.get("country_name"),
                    p.get("country_probability"),
                    created_at
                ))
                if (i + 1) % 500 == 0:
                    print(f"  Processed {i + 1}/{total_profiles}...", flush=True)
            
            print(f"Executing bulk insert of {len(values)} records to Supabase...", flush=True)
            # Use execute_values for efficient bulk insertion
            execute_values(cur, """
                INSERT INTO profiles (
                    id, name, gender, gender_probability, age, age_group, 
                    country_id, country_name, country_probability, created_at
                ) VALUES %s
                ON CONFLICT (name) DO NOTHING
            """, values)
            
            print("Committing changes...", flush=True)
            conn.commit()
            print("Seeding completed successfully.", flush=True)
    except Exception as e:
        print(f"Error during seeding: {e}", flush=True)
        conn.rollback()
    finally:
        conn.close()

def fetch_profile_data(name: str):
    """
    Calls external APIs to gather information about a name.
    """
    import httpx
    import time
    
    # Standard external APIs
    GENDERIZE_URL = f"https://api.genderize.io?name={name}"
    AGIFY_URL = f"https://api.agify.io?name={name}"
    NATIONALize_URL = f"https://api.nationalize.io?name={name}"
    
    results = {}
    
    with httpx.Client() as client:
        # Gender
        resp = client.get(GENDERIZE_URL)
        if resp.status_code == 200:
            d = resp.json()
            results["gender"] = d.get("gender")
            results["gender_probability"] = d.get("probability")
            
        # Age
        resp = client.get(AGIFY_URL)
        if resp.status_code == 200:
            d = resp.json()
            results["age"] = d.get("age")
            if results["age"]:
                if results["age"] < 13: results["age_group"] = "child"
                elif results["age"] < 20: results["age_group"] = "teenager"
                elif results["age"] < 65: results["age_group"] = "adult"
                else: results["age_group"] = "senior"
        
        # Nationality
        resp = client.get(NATIONALize_URL)
        if resp.status_code == 200:
            d = resp.json()
            countries = d.get("country", [])
            if countries:
                results["country_id"] = countries[0].get("country_id")
                results["country_probability"] = countries[0].get("probability")
                # We could look up country_name here, or leave it for later
                results["country_name"] = results["country_id"] # Placeholder
    
    results["name"] = name
    return results

def save_profile(data: dict):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            profile_id = str(uuid6.uuid7())
            cur.execute("""
                INSERT INTO profiles (
                    id, name, gender, gender_probability, age, age_group,
                    country_id, country_name, country_probability
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (
                profile_id, data.get("name"), data.get("gender"), data.get("gender_probability"),
                data.get("age"), data.get("age_group"), data.get("country_id"),
                data.get("country_name"), data.get("country_probability")
            ))
            profile = cur.fetchone()
            conn.commit()
            return profile
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--seed":
        seed_data()
    else:
        print("Usage: python seed.py --seed")
