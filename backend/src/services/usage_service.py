"""
Sprint 4 – BLOQUE C: Usage & Limits Enforcement
Tracks usage, checks plan limits, enforces execution mode.
"""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.src.database.models import (
    Subscription, SubscriptionStatusEnum, UsageEvent, MetaConnection, AdAccount,
)


class UsageService:
    def __init__(self, db: Session):
        self.db = db

    def get_subscription(self, org_id: str) -> Subscription:
        """Get the subscription for an org. Raises 403 if none."""
        try:
            org_uuid = UUID(org_id)
        except (ValueError, AttributeError):
            raise HTTPException(403, "Invalid organization")

        sub = self.db.query(Subscription).filter(Subscription.org_id == org_uuid).first()
        if not sub:
            raise HTTPException(403, "No active subscription. Please set up billing.")
        return sub

    def check_limit(self, org_id: str, event_type: str) -> dict:
        """
        Check if the org is within plan limits for an event type.
        Returns {allowed, current, limit, plan}.
        Raises 403 if over limit.
        """
        sub = self.get_subscription(org_id)

        # Read-only check
        self._check_read_only(sub)

        # Get limit for this event type
        limit_map = {
            "decision_create": sub.max_decisions_per_month,
            "creative_generate": sub.max_creatives_per_month,
        }
        limit = limit_map.get(event_type)
        if limit is None:
            return {"allowed": True, "current": 0, "limit": None, "plan": sub.plan.value}

        current = self._get_current_usage(org_id, event_type)

        if current >= limit:
            raise HTTPException(
                403,
                f"Monthly {event_type} limit reached ({current}/{limit}). "
                f"Upgrade your plan to increase limits."
            )

        return {
            "allowed": True,
            "current": current,
            "limit": limit,
            "plan": sub.plan.value,
        }

    def record_usage(self, org_id: str, event_type: str):
        """Increment the usage counter for the current period (upsert)."""
        org_uuid = UUID(org_id)
        period_start = self._current_period_start()

        existing = self.db.query(UsageEvent).filter(
            UsageEvent.org_id == org_uuid,
            UsageEvent.event_type == event_type,
            UsageEvent.period_start == period_start,
        ).first()

        if existing:
            existing.count = existing.count + 1
        else:
            self.db.add(UsageEvent(
                id=uuid4(),
                org_id=org_uuid,
                event_type=event_type,
                count=1,
                period_start=period_start,
                created_at=datetime.now(timezone.utc),
            ))
        self.db.flush()

    def enforce_execution_mode(self, org_id: str, requested_dry_run: bool) -> bool:
        """
        Enforce execution mode based on plan.
        - TRIAL: always returns True (forced dry_run)
        - past_due/canceled: raises 403
        - Others: returns the requested value
        """
        sub = self.get_subscription(org_id)
        self._check_read_only(sub)

        if not sub.allow_live_execution:
            return True  # Force dry_run for TRIAL

        return requested_dry_run

    def check_ad_account_limit(self, org_id: str) -> dict:
        """Check if the org can add more ad accounts."""
        sub = self.get_subscription(org_id)
        org_uuid = UUID(org_id)

        # Count current ad accounts via MetaConnection chain
        connections = self.db.query(MetaConnection.id).filter(
            MetaConnection.org_id == org_uuid
        ).subquery()
        current_count = self.db.query(AdAccount).filter(
            AdAccount.connection_id.in_(connections)
        ).count()

        if current_count >= sub.max_ad_accounts:
            raise HTTPException(
                403,
                f"Ad account limit reached ({current_count}/{sub.max_ad_accounts}). "
                f"Upgrade your plan to add more ad accounts."
            )

        return {
            "allowed": True,
            "current": current_count,
            "limit": sub.max_ad_accounts,
            "plan": sub.plan.value,
        }

    def _check_read_only(self, sub: Subscription):
        """Block write operations for canceled/past_due subscriptions."""
        if sub.status == SubscriptionStatusEnum.CANCELED:
            raise HTTPException(403, "Subscription canceled. Please renew to continue.")
        if sub.status == SubscriptionStatusEnum.PAST_DUE:
            raise HTTPException(402, "Payment past due. Please update billing.")

    def _get_current_usage(self, org_id: str, event_type: str) -> int:
        """Get the current month usage count for an event type."""
        org_uuid = UUID(org_id)
        period_start = self._current_period_start()

        usage = self.db.query(UsageEvent).filter(
            UsageEvent.org_id == org_uuid,
            UsageEvent.event_type == event_type,
            UsageEvent.period_start == period_start,
        ).first()

        return usage.count if usage else 0

    @staticmethod
    def _current_period_start() -> datetime:
        """First day of current month, UTC, midnight."""
        now = datetime.now(timezone.utc)
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
