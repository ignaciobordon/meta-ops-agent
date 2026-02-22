"""
Sprint 4 – BLOQUE C: Plan Gate Middleware
Dependencies that enforce subscription status on write operations.
"""
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from backend.src.database.models import Subscription, SubscriptionStatusEnum
from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user


def require_active_subscription(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Subscription:
    """Dependency that blocks write operations for inactive subscriptions."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(403, "No organization associated with user")

    try:
        org_uuid = UUID(org_id)
    except (ValueError, AttributeError):
        raise HTTPException(403, "Invalid organization")

    sub = db.query(Subscription).filter(Subscription.org_id == org_uuid).first()
    if not sub:
        raise HTTPException(403, "No active subscription. Please set up billing.")

    if sub.status == SubscriptionStatusEnum.CANCELED:
        raise HTTPException(403, "Subscription canceled. Please renew to continue.")
    if sub.status == SubscriptionStatusEnum.PAST_DUE:
        raise HTTPException(402, "Payment past due. Please update billing.")

    return sub
