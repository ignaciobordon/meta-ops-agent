"""
Sprint 4 – BLOQUE B: Billing API
Stripe checkout, customer portal, webhook, and subscription status.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.src.database.session import get_db
from backend.src.middleware.auth import get_current_user
from backend.src.services.stripe_service import StripeService

router = APIRouter(tags=["Billing"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class CheckoutRequest(BaseModel):
    plan: str = "pro"
    success_url: str = "http://localhost:5173/settings?tab=billing&status=success"
    cancel_url: str = "http://localhost:5173/settings?tab=billing&status=cancel"


class PortalRequest(BaseModel):
    return_url: str = "http://localhost:5173/settings?tab=billing"


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/checkout")
def create_checkout(
    body: CheckoutRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a Stripe Checkout session. Returns redirect URL."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization associated with user")

    try:
        service = StripeService(db)
        url = service.create_checkout_session(
            org_id=org_id,
            plan=body.plan,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
        return {"checkout_url": url}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/portal")
def create_portal(
    body: PortalRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a Stripe Customer Portal session. Returns redirect URL."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization associated with user")

    try:
        service = StripeService(db)
        url = service.create_portal_session(org_id=org_id, return_url=body.return_url)
        return {"portal_url": url}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Stripe webhook endpoint. No auth required — verified via signature.
    Must receive raw body for signature verification.
    """
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        service = StripeService(db)
        result = service.handle_webhook(payload, sig_header)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/status")
def get_billing_status(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current subscription status, plan, usage, and limits."""
    org_id = user.get("org_id", "")
    if not org_id:
        raise HTTPException(400, "No organization associated with user")

    service = StripeService(db)
    return service.get_subscription_status(org_id)
