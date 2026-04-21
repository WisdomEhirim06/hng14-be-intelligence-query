import json
import os
import uuid6
import sys
from database import get_connection, init_db
from datetime import datetime, timezone
from psycopg2.extras import execute_values

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

if __name__ == "__main__":
    seed_data()
