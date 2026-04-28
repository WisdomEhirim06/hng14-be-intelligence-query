from database import get_connection

def check_distinct_genders():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT gender FROM profiles")
            results = cur.fetchall()
            print(f"Distinct genders: {[r[0] for r in results]}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_distinct_genders()
