"""One-time migration: set conversion_model='offline' for all existing organizations.

Run with:
    python -m scripts.set_offline_conversion_model

This is safe to run multiple times — it only sets the value if not already present.
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.src.database.session import SessionLocal
from backend.src.database.models import Organization
from sqlalchemy.orm.attributes import flag_modified


def main():
    db = SessionLocal()
    try:
        orgs = db.query(Organization).all()
        updated = 0
        for org in orgs:
            settings = dict(org.settings or {})
            if settings.get("conversion_model") is None:
                settings["conversion_model"] = "offline"
                org.settings = settings
                flag_modified(org, "settings")
                updated += 1
                print(f"  Set conversion_model=offline for org '{org.name}' ({org.id})")

        if updated:
            db.commit()
            print(f"\nDone. Updated {updated} organization(s).")
        else:
            print("All organizations already have conversion_model set. Nothing to do.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
