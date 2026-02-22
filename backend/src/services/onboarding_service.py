"""Sprint 8 — Onboarding service: step progression, validation, completion."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.src.database.models import OnboardingState, OnboardingStatusEnum


# Step order for validation
STEP_ORDER = [
    OnboardingStatusEnum.PENDING,
    OnboardingStatusEnum.CONNECT_META,
    OnboardingStatusEnum.SELECT_ACCOUNT,
    OnboardingStatusEnum.CHOOSE_TEMPLATE,
    OnboardingStatusEnum.CONFIGURE,
    OnboardingStatusEnum.SYNCING,
    OnboardingStatusEnum.COMPLETED,
]

STEP_INDEX = {s: i for i, s in enumerate(STEP_ORDER)}


def get_or_create_state(db: Session, org_id: UUID, user_id: Optional[UUID] = None) -> OnboardingState:
    """Get existing onboarding state or create a new one."""
    state = db.query(OnboardingState).filter(OnboardingState.org_id == org_id).first()
    if state:
        return state

    state = OnboardingState(
        org_id=org_id,
        user_id=user_id,
        current_step=OnboardingStatusEnum.PENDING,
    )
    db.add(state)
    db.flush()
    return state


def get_progress(db: Session, org_id: UUID) -> dict:
    """Return current onboarding progress as a dict."""
    state = db.query(OnboardingState).filter(OnboardingState.org_id == org_id).first()
    if not state:
        return {
            "current_step": "pending",
            "meta_connected": False,
            "account_selected": False,
            "template_chosen": False,
            "completed": False,
        }
    return {
        "current_step": state.current_step.value if hasattr(state.current_step, 'value') else str(state.current_step),
        "meta_connected": state.meta_connected or False,
        "account_selected": state.account_selected or False,
        "template_chosen": state.template_chosen or False,
        "selected_template_id": str(state.selected_template_id) if state.selected_template_id else None,
        "completed": state.completed_at is not None,
    }


def is_complete(db: Session, org_id: UUID) -> bool:
    """Check if onboarding is complete for the org."""
    state = db.query(OnboardingState).filter(OnboardingState.org_id == org_id).first()
    if not state:
        return False
    return state.completed_at is not None


def advance_step(
    db: Session,
    org_id: UUID,
    step: str,
    data: Optional[dict] = None,
    user_id: Optional[UUID] = None,
) -> OnboardingState:
    """Advance onboarding to the specified step. Validates prerequisites."""
    state = get_or_create_state(db, org_id, user_id)

    try:
        target_step = OnboardingStatusEnum(step)
    except ValueError:
        raise ValueError(f"Invalid step: {step}")

    current_idx = STEP_INDEX.get(state.current_step, 0)
    target_idx = STEP_INDEX.get(target_step, 0)

    # Allow same step (idempotent) or next step only
    if target_idx > current_idx + 1:
        raise ValueError(f"Cannot skip to {step} from {state.current_step.value}")

    # Update flags based on step
    if target_step == OnboardingStatusEnum.CONNECT_META:
        state.meta_connected = True
    elif target_step == OnboardingStatusEnum.SELECT_ACCOUNT:
        if not state.meta_connected:
            raise ValueError("Must connect Meta first")
        state.account_selected = True
    elif target_step == OnboardingStatusEnum.CHOOSE_TEMPLATE:
        if not state.account_selected:
            raise ValueError("Must select an account first")
        state.template_chosen = True
        if data and data.get("template_id"):
            state.selected_template_id = UUID(data["template_id"])
    elif target_step == OnboardingStatusEnum.COMPLETED:
        state.completed_at = datetime.utcnow()

    state.current_step = target_step
    state.updated_at = datetime.utcnow()
    db.flush()
    return state


def complete_onboarding(db: Session, org_id: UUID) -> OnboardingState:
    """Mark onboarding as complete."""
    state = db.query(OnboardingState).filter(OnboardingState.org_id == org_id).first()
    if not state:
        raise ValueError("No onboarding state found")

    state.current_step = OnboardingStatusEnum.COMPLETED
    state.completed_at = datetime.utcnow()
    state.updated_at = datetime.utcnow()
    db.flush()
    return state
