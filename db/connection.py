"""Shared DB connection for patient persistence layer."""
import os
import psycopg2
import psycopg2.extras

def get_db_conn():
    url = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")
    return psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
