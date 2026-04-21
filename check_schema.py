import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def check_columns():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'profiles';
            """)
            columns = cur.fetchall()
            print("Columns in 'profiles' table:")
            for col in columns:
                print(f"- {col[0]}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_columns()
