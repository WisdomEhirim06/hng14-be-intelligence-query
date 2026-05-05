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

COUNTRY_NAMES = {
    "AF": "Afghanistan", "AL": "Albania", "DZ": "Algeria", "AR": "Argentina",
    "AU": "Australia", "AT": "Austria", "BD": "Bangladesh", "BE": "Belgium",
    "BR": "Brazil", "BG": "Bulgaria", "CA": "Canada", "CL": "Chile",
    "CN": "China", "CO": "Colombia", "HR": "Croatia", "CZ": "Czech Republic",
    "DK": "Denmark", "EG": "Egypt", "ET": "Ethiopia", "FI": "Finland",
    "FR": "France", "DE": "Germany", "GH": "Ghana", "GR": "Greece",
    "HU": "Hungary", "IN": "India", "ID": "Indonesia", "IR": "Iran",
    "IQ": "Iraq", "IE": "Ireland", "IL": "Israel", "IT": "Italy",
    "JP": "Japan", "JO": "Jordan", "KE": "Kenya", "KR": "South Korea",
    "KW": "Kuwait", "LB": "Lebanon", "LY": "Libya", "MY": "Malaysia",
    "MX": "Mexico", "MA": "Morocco", "MM": "Myanmar", "NP": "Nepal",
    "NL": "Netherlands", "NZ": "New Zealand", "NG": "Nigeria", "NO": "Norway",
    "PK": "Pakistan", "PE": "Peru", "PH": "Philippines", "PL": "Poland",
    "PT": "Portugal", "QA": "Qatar", "RO": "Romania", "RU": "Russia",
    "SA": "Saudi Arabia", "SN": "Senegal", "ZA": "South Africa", "ES": "Spain",
    "LK": "Sri Lanka", "SD": "Sudan", "SE": "Sweden", "CH": "Switzerland",
    "SY": "Syria", "TZ": "Tanzania", "TH": "Thailand", "TN": "Tunisia",
    "TR": "Turkey", "UG": "Uganda", "UA": "Ukraine", "AE": "United Arab Emirates",
    "GB": "United Kingdom", "US": "United States", "UY": "Uruguay",
    "UZ": "Uzbekistan", "VE": "Venezuela", "VN": "Vietnam", "YE": "Yemen",
    "ZM": "Zambia", "ZW": "Zimbabwe",
}


def fetch_profile_data(name: str):
    """Calls external APIs to gather information about a name."""
    import httpx

    GENDERIZE_URL = f"https://api.genderize.io?name={name}"
    AGIFY_URL = f"https://api.agify.io?name={name}"
    NATIONALIZE_URL = f"https://api.nationalize.io?name={name}"

    results = {}

    with httpx.Client() as client:
        resp = client.get(GENDERIZE_URL)
        if resp.status_code == 200:
            d = resp.json()
            results["gender"] = d.get("gender")
            results["gender_probability"] = d.get("probability")

        resp = client.get(AGIFY_URL)
        if resp.status_code == 200:
            d = resp.json()
            results["age"] = d.get("age")
            if results.get("age"):
                if results["age"] < 13:
                    results["age_group"] = "child"
                elif results["age"] < 20:
                    results["age_group"] = "teenager"
                elif results["age"] < 65:
                    results["age_group"] = "adult"
                else:
                    results["age_group"] = "senior"

        resp = client.get(NATIONALIZE_URL)
        if resp.status_code == 200:
            d = resp.json()
            countries = d.get("country", [])
            if countries:
                country_id = countries[0].get("country_id")
                results["country_id"] = country_id
                results["country_probability"] = countries[0].get("probability")
                results["country_name"] = COUNTRY_NAMES.get(country_id, country_id)

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
