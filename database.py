import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Read schema.sql
            schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
            with open(schema_path, "r") as f:
                cur.execute(f.read())
            
            # Check for country_name column (migration)
            cur.execute("""
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='profiles' AND column_name='country_name'
            """)
            if not cur.fetchone():
                print("Migrating: Adding 'country_name' column to profiles table...")
                cur.execute("ALTER TABLE profiles ADD COLUMN country_name VARCHAR(255)")
            
            # Ensure 'name' column has a UNIQUE constraint for ON CONFLICT
            cur.execute("""
                SELECT 1 FROM information_schema.table_constraints 
                WHERE table_name='profiles' AND constraint_type='UNIQUE' 
                AND constraint_name='profiles_name_key'
            """)
            if not cur.fetchone():
                 print("Migrating: Adding UNIQUE constraint to 'name' column...")
                 try:
                     cur.execute("ALTER TABLE profiles ADD CONSTRAINT profiles_name_key UNIQUE (name)")
                 except Exception as e:
                     print(f"Warning: Could not add UNIQUE constraint (maybe duplicates exist?): {e}")
            
            conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    print("Database initialized successfully.")
