"""
Sprint 3 – BLOQUE 3: Multi-Tenant Utilities
Shared helpers for org-scoped data access.
"""
from typing import List
from uuid import UUID

from sqlalchemy.orm import Session

from backend.src.database.models import AdAccount, MetaConnection


def get_org_ad_account_ids(org_id: str, db: Session) -> List[UUID]:
    """
    Get all ad_account IDs belonging to an organization.
    Traverses: Organization → MetaConnection → AdAccount.
    """
    try:
        org_uuid = UUID(org_id)
    except (ValueError, AttributeError):
        return []

    connections = db.query(MetaConnection.id).filter(
        MetaConnection.org_id == org_uuid
    ).subquery()

    accounts = db.query(AdAccount.id).filter(
        AdAccount.connection_id.in_(connections)
    ).all()

    return [a.id for a in accounts]
