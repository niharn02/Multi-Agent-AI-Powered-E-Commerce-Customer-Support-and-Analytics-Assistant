
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    return psycopg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "ecomassist_v2"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD"),
    )


if __name__ == "__main__":
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), version();")
                database_name, postgres_version = cur.fetchone()

                print(f"Connected to database: {database_name}")
                print(f"PostgreSQL version: {postgres_version}")

    except psycopg.OperationalError as exc:
        print(f"Database connection failed: {exc}")
