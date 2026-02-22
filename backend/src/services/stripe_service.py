"""
Sprint 4 – BLOQUE B: Stripe Billing Service
Handles checkout sessions, customer portal, webhooks, and subscription status.
"""
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from backend.src.config import settings
from backend.src.database.models import (
    Organization, Subscription, SubscriptionStatusEnum, PlanEnum, PLAN_LIMITS, UsageEvent,
)
from src.utils.logging_config import logger

try:
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
except ImportError:
    stripe = None  # Tests can mock this


class StripeService:
    def __init__(self, db: Session):
        self.db = db

    def create_checkout_session(self, org_id: str, plan: str, success_url: str, cancel_url: str) -> str:
        """Create a Stripe Checkout session and return the URL."""
        if not stripe or not settings.STRIPE_SECRET_KEY:
            raise ValueError("Stripe is not configured")

        org_uuid = UUID(org_id)
        sub = self.db.query(Subscription).filter(Subscription.org_id == org_uuid).first()

        # Get or create Stripe customer
        customer_id = sub.stripe_customer_id if sub else None
        if not customer_id:
            org = self.db.query(Organization).filter(Organization.id == org_uuid).first()
            if not org:
                raise ValueError("Organization not found")
            customer = stripe.Customer.create(
                name=org.name,
                metadata={"org_id": org_id, "org_slug": org.slug},
            )
            customer_id = customer.id
            if sub:
                sub.stripe_customer_id = customer_id
                self.db.commit()

        # Resolve price ID
        price_id = settings.STRIPE_PRO_PRICE_ID
        if not price_id:
            raise ValueError("STRIPE_PRO_PRICE_ID not configured")

        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"org_id": org_id, "plan": plan},
        )
        return session.url

    def create_portal_session(self, org_id: str, return_url: str) -> str:
        """Create a Stripe Customer Portal session and return the URL."""
        if not stripe or not settings.STRIPE_SECRET_KEY:
            raise ValueError("Stripe is not configured")

        org_uuid = UUID(org_id)
        sub = self.db.query(Subscription).filter(Subscription.org_id == org_uuid).first()
        if not sub or not sub.stripe_customer_id:
            raise ValueError("No Stripe customer found. Please complete checkout first.")

        session = stripe.billing_portal.Session.create(
            customer=sub.stripe_customer_id,
            return_url=return_url,
        )
        return session.url

    def handle_webhook(self, payload: bytes, sig_header: str) -> dict:
        """Process Stripe webhook event. Returns {status, event_type}."""
        if not stripe:
            raise ValueError("Stripe is not configured")

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET,
            )
        except stripe.error.SignatureVerificationError:
            raise ValueError("Invalid webhook signature")

        event_type = event["type"]
        data = event["data"]["object"]

        if event_type == "checkout.session.completed":
            self._handle_checkout_completed(data)
        elif event_type == "customer.subscription.updated":
            self._handle_subscription_updated(data)
        elif event_type == "customer.subscription.deleted":
            self._handle_subscription_deleted(data)
        elif event_type == "invoice.payment_failed":
            self._handle_invoice_failed(data)
        else:
            logger.info(f"STRIPE_WEBHOOK | Ignored event: {event_type}")

        return {"status": "ok", "event_type": event_type}

    def _handle_checkout_completed(self, session_data: dict):
        """Handle checkout.session.completed — activate subscription."""
        org_id = session_data.get("metadata", {}).get("org_id")
        plan_str = session_data.get("metadata", {}).get("plan", "pro")
        customer_id = session_data.get("customer")
        subscription_id = session_data.get("subscription")

        if not org_id:
            logger.warning("STRIPE_WEBHOOK | checkout.session.completed missing org_id metadata")
            return

        try:
            org_uuid = UUID(org_id)
        except (ValueError, AttributeError):
            logger.warning(f"STRIPE_WEBHOOK | Invalid org_id: {org_id}")
            return

        plan = PlanEnum(plan_str) if plan_str in [p.value for p in PlanEnum] else PlanEnum.PRO
        limits = PLAN_LIMITS[plan]

        # Look up org + subscription with UUID objects (SQLite compat)
        org = self.db.query(Organization).get(org_uuid)
        if not org:
            logger.warning(f"STRIPE_WEBHOOK | Organization not found: {org_id}")
            return
        sub = self.db.query(Subscription).filter(
            Subscription.org_id == org_uuid
        ).first()
        now = datetime.now(timezone.utc)

        if sub:
            sub.plan = plan
            sub.status = SubscriptionStatusEnum.ACTIVE
            sub.stripe_customer_id = customer_id
            sub.stripe_subscription_id = subscription_id
            sub.max_ad_accounts = limits["max_ad_accounts"]
            sub.max_decisions_per_month = limits["max_decisions_per_month"]
            sub.max_creatives_per_month = limits["max_creatives_per_month"]
            sub.allow_live_execution = limits["allow_live_execution"]
            sub.updated_at = now
        else:
            sub = Subscription(
                id=uuid4(),
                org_id=org_uuid,
                plan=plan,
                status=SubscriptionStatusEnum.ACTIVE,
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
                max_ad_accounts=limits["max_ad_accounts"],
                max_decisions_per_month=limits["max_decisions_per_month"],
                max_creatives_per_month=limits["max_creatives_per_month"],
                allow_live_execution=limits["allow_live_execution"],
                created_at=now,
            )
            self.db.add(sub)

        self.db.commit()
        logger.info(f"STRIPE_WEBHOOK | Checkout completed for org={org_id} plan={plan.value}")

    def _handle_subscription_updated(self, sub_data: dict):
        """Handle customer.subscription.updated — sync status + limits."""
        stripe_sub_id = sub_data.get("id")
        sub = self.db.query(Subscription).filter(
            Subscription.stripe_subscription_id == stripe_sub_id
        ).first()
        if not sub:
            logger.warning(f"STRIPE_WEBHOOK | subscription.updated — sub not found: {stripe_sub_id}")
            return

        status_map = {
            "trialing": SubscriptionStatusEnum.TRIALING,
            "active": SubscriptionStatusEnum.ACTIVE,
            "past_due": SubscriptionStatusEnum.PAST_DUE,
            "canceled": SubscriptionStatusEnum.CANCELED,
            "incomplete": SubscriptionStatusEnum.INCOMPLETE,
        }
        new_status = status_map.get(sub_data.get("status"), sub.status)
        sub.status = new_status
        sub.current_period_start = datetime.fromtimestamp(
            sub_data.get("current_period_start", 0), tz=timezone.utc
        ) if sub_data.get("current_period_start") else None
        sub.current_period_end = datetime.fromtimestamp(
            sub_data.get("current_period_end", 0), tz=timezone.utc
        ) if sub_data.get("current_period_end") else None
        sub.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        logger.info(f"STRIPE_WEBHOOK | Subscription updated: {stripe_sub_id} → {new_status.value}")

    def _handle_subscription_deleted(self, sub_data: dict):
        """Handle customer.subscription.deleted — mark canceled."""
        stripe_sub_id = sub_data.get("id")
        sub = self.db.query(Subscription).filter(
            Subscription.stripe_subscription_id == stripe_sub_id
        ).first()
        if not sub:
            return

        sub.status = SubscriptionStatusEnum.CANCELED
        sub.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        logger.info(f"STRIPE_WEBHOOK | Subscription deleted (canceled): {stripe_sub_id}")

    def _handle_invoice_failed(self, invoice_data: dict):
        """Handle invoice.payment_failed — mark past_due."""
        customer_id = invoice_data.get("customer")
        sub = self.db.query(Subscription).filter(
            Subscription.stripe_customer_id == customer_id
        ).first()
        if not sub:
            return

        sub.status = SubscriptionStatusEnum.PAST_DUE
        sub.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        logger.info(f"STRIPE_WEBHOOK | Invoice failed for customer={customer_id}")

    def get_subscription_status(self, org_id: str) -> dict:
        """Get current subscription status, plan, usage, and limits."""
        org_uuid = UUID(org_id)
        sub = self.db.query(Subscription).filter(Subscription.org_id == org_uuid).first()

        if not sub:
            return {
                "plan": None,
                "status": None,
                "limits": {},
                "usage": {},
                "trial_ends_at": None,
            }

        # Get current month usage
        now = datetime.now(timezone.utc)
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        usage_events = self.db.query(UsageEvent).filter(
            UsageEvent.org_id == org_uuid,
            UsageEvent.period_start == period_start,
        ).all()

        usage = {}
        for ue in usage_events:
            usage[ue.event_type] = ue.count

        return {
            "plan": sub.plan.value,
            "status": sub.status.value,
            "limits": {
                "max_ad_accounts": sub.max_ad_accounts,
                "max_decisions_per_month": sub.max_decisions_per_month,
                "max_creatives_per_month": sub.max_creatives_per_month,
                "allow_live_execution": sub.allow_live_execution,
            },
            "usage": {
                "decisions_this_month": usage.get("decision_create", 0),
                "creatives_this_month": usage.get("creative_generate", 0),
            },
            "trial_ends_at": sub.trial_ends_at.isoformat() if sub.trial_ends_at else None,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        }
