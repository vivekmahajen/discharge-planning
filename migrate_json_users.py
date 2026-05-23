"""One-shot script to migrate data/users.json into the multi-tenant PostgreSQL schema.

Usage:
    POSTGRES_URL=postgresql://... python migrate_json_users.py

Creates the 'Original Users' organization (id = DEFAULT_ORG_ID) if it does not
exist, then inserts every user from users.json preserving their existing
password hash and salt so existing passwords continue to work.
"""
import json
import os
import sys
from pathlib import Path

DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_ORG_NAME = "Original Users"
DEFAULT_ORG_SLUG = "original-users"

USERS_FILE = Path(__file__).parent / "data" / "users.json"


def main() -> None:
    db_url = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: Set POSTGRES_URL or DATABASE_URL", file=sys.stderr)
        sys.exit(1)

    if not USERS_FILE.exists():
        print(f"No users file at {USERS_FILE} — nothing to migrate.")
        return

    users = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    if not users:
        print("users.json is empty — nothing to migrate.")
        return

    import psycopg2
    conn = psycopg2.connect(db_url)
    try:
        with conn:
            with conn.cursor() as cur:
                # Ensure default org exists
                cur.execute(
                    """
                    INSERT INTO organizations (id, name, slug, plan)
                    VALUES (%s, %s, %s, 'standard')
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (DEFAULT_ORG_ID, DEFAULT_ORG_NAME, DEFAULT_ORG_SLUG),
                )

                migrated = skipped = 0
                for email, record in users.items():
                    salt = record.get("salt", "")
                    pw_hash = record.get("hash", "")
                    if not salt or not pw_hash:
                        print(f"  SKIP {email}: missing salt or hash")
                        skipped += 1
                        continue

                    cur.execute(
                        """
                        INSERT INTO users (organization_id, email, salt, hash, role)
                        VALUES (%s, %s, %s, %s, 'clinician')
                        ON CONFLICT (organization_id, email) DO NOTHING
                        """,
                        (DEFAULT_ORG_ID, email, salt, pw_hash),
                    )
                    migrated += 1
                    print(f"  OK {email}")

        print(f"\nDone: {migrated} migrated, {skipped} skipped.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
