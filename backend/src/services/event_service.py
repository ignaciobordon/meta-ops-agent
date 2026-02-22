"""Sprint 8 — Product Event service: tracking and funnel analytics."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.src.database.models import ProductEvent

FUNNEL_EVENTS = [
    "onboarding_started",
    "meta_connected",
    "account_selected",
    "template_chosen",
    "onboarding_completed",
    "first_sync_complete",
    "first_alert_seen",
    "first_decision_created",
    "first_analytics_viewed",
]


def track(
    db: Session,
    org_id: UUID,
    user_id: Optional[UUID],
    event_name: str,
    properties: Optional[dict] = None,
) -> ProductEvent:
    """Track a product event."""
    event = ProductEvent(
        org_id=org_id,
        user_id=user_id,
        event_name=event_name,
        properties_json=properties or {},
    )
    db.add(event)
    db.flush()
    return event


def get_funnel(db: Session, org_id: Optional[UUID] = None) -> dict:
    """Get onboarding funnel stats. If org_id is None, return global stats."""
    result = {}
    for event_name in FUNNEL_EVENTS:
        query = db.query(func.count(func.distinct(ProductEvent.org_id))).filter(
            ProductEvent.event_name == event_name,
        )
        if org_id:
            query = query.filter(ProductEvent.org_id == org_id)
        count = query.scalar() or 0
        result[event_name] = count

    return result


def get_events(
    db: Session,
    org_id: UUID,
    event_name: Optional[str] = None,
    limit: int = 50,
) -> List[dict]:
    """Get recent product events for an org."""
    query = db.query(ProductEvent).filter(ProductEvent.org_id == org_id)
    if event_name:
        query = query.filter(ProductEvent.event_name == event_name)

    events = query.order_by(ProductEvent.created_at.desc()).limit(limit).all()
    return [
        {
            "id": str(e.id),
            "event_name": e.event_name,
            "properties": e.properties_json or {},
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]
