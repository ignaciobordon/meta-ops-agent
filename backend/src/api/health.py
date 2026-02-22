"""Health check endpoints."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "meta-ops-agent"}


@router.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Meta Ops Agent API",
        "version": "1.0.0",
        "status": "operational",
    }
