"""
Sprint 7 -- BLOQUE 1: Celery Application.
Three queues: default, io, llm.
"""
from kombu import Queue

from backend.src.config import settings

broker_url = settings.CELERY_BROKER_URL or settings.REDIS_URL
result_backend = settings.CELERY_RESULT_BACKEND or settings.REDIS_URL

# Lazy import to avoid issues when celery is not installed (e.g., in tests)
try:
    from celery import Celery

    celery_app = Celery(
        "meta_ops_worker",
        broker=broker_url,
        backend=result_backend,
    )

    celery_app.conf.update(
        task_default_queue="default",
        task_queues=[
            Queue("default", routing_key="default"),
            Queue("io", routing_key="io"),
            Queue("llm", routing_key="llm"),
            Queue("ci_io", routing_key="ci_io"),
            Queue("ci_cpu", routing_key="ci_cpu"),
        ],
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_track_started=True,
        task_reject_on_worker_lost=True,
        broker_connection_retry_on_startup=True,
        # Global time limits (overridden per-task via annotations)
        task_soft_time_limit=120,   # 2 min soft (raises SoftTimeLimitExceeded)
        task_time_limit=180,        # 3 min hard kill
        # Per-task time limits: LLM tasks get longer budgets
        task_annotations={
            "backend.src.jobs.tasks.creatives_generate": {
                "soft_time_limit": 300,  # 5 min soft
                "time_limit": 360,       # 6 min hard
            },
        },
    )

    # Auto-discover tasks
    celery_app.autodiscover_tasks(["backend.src.jobs"])

    # Worker startup logging
    from celery.signals import worker_ready

    @worker_ready.connect
    def _log_worker_ready(sender=None, **kwargs):
        import logging
        log = logging.getLogger("meta_ops_worker")
        log.info(
            "WORKER_READY | default_provider=%s | fallback_provider=%s | "
            "anthropic_key=%s | openai_key=%s | redis=%s",
            settings.LLM_DEFAULT_PROVIDER,
            settings.LLM_FALLBACK_PROVIDER,
            "present" if settings.ANTHROPIC_API_KEY else "MISSING",
            "present" if settings.OPENAI_API_KEY else "MISSING",
            broker_url[:30] + "..." if len(broker_url) > 30 else broker_url,
        )

except ImportError:
    celery_app = None
