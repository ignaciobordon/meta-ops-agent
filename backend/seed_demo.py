"""
Seed demo data for development.
Creates sample organization, user, and Meta connection.
"""
from uuid import uuid4

from src.database.models import (
    AdAccount,
    MetaConnection,
    Organization,
    RoleEnum,
    User,
    UserOrgRole,
    ConnectionStatus,
)
from src.database.session import get_db_context, init_db
from backend.src.middleware.auth import hash_password


def seed_demo_data():
    """Create demo data for testing the UI."""
    print("Initializing database...")
    init_db()

    with get_db_context() as db:
        print("Seeding demo data...")

        # Check if demo org exists
        existing_org = db.query(Organization).filter(Organization.slug == "demo-workspace").first()
        if existing_org:
            print("Demo data already exists. Skipping seed.")
            return

        # Create demo organization
        org = Organization(
            name="Demo Workspace",
            slug="demo-workspace",
            operator_armed=False,
        )
        db.add(org)
        db.flush()

        # Create demo user with proper password hash
        user = User(
            email="demo@example.com",
            name="Demo User",
            password_hash=hash_password("demo123"),
        )
        db.add(user)
        db.flush()

        # Assign ADMIN role (not DIRECTOR which doesn't exist)
        user_role = UserOrgRole(
            user_id=user.id,
            org_id=org.id,
            role=RoleEnum.ADMIN,
        )
        db.add(user_role)

        # Create demo Meta connection
        connection = MetaConnection(
            org_id=org.id,
            access_token_encrypted="demo_token_placeholder",
            scopes=["ads_read"],
            status=ConnectionStatus.ACTIVE,
        )
        db.add(connection)
        db.flush()

        # Create demo ad account
        ad_account = AdAccount(
            connection_id=connection.id,
            meta_ad_account_id="act_123456789",
            name="Demo Ad Account",
            currency="USD",
        )
        db.add(ad_account)

        db.commit()

        print("[OK] Demo data seeded successfully!")
        print(f"  - Organization: {org.name} (ID: {org.id})")
        print(f"  - User: {user.email} / demo123 (ID: {user.id}, Role: admin)")
        print(f"  - Ad Account: {ad_account.name} (ID: {ad_account.id})")
        print("\nYou can now start the backend and frontend.")


if __name__ == "__main__":
    seed_demo_data()
