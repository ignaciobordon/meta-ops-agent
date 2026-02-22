"""
Sprint 7 -- BLOQUE 7: OpenTelemetry Setup.
Instruments FastAPI, Celery, SQLAlchemy, httpx.
Skipped in test environments.
"""
from backend.src.config import settings
from src.utils.logging_config import logger


def setup_telemetry(app=None, engine=None):
    """Initialize OpenTelemetry with all instrumentations."""
    if settings.ENVIRONMENT == "test":
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({
            "service.name": "meta-ops-agent",
            "service.version": settings.APP_VERSION,
            "deployment.environment": settings.ENVIRONMENT,
        })

        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)

        # Instrument FastAPI
        if app:
            try:
                from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
                FastAPIInstrumentor.instrument_app(app)
                logger.info("OTEL_INSTRUMENTED | fastapi")
            except ImportError:
                pass

        # Instrument SQLAlchemy
        if engine:
            try:
                from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
                SQLAlchemyInstrumentor().instrument(engine=engine)
                logger.info("OTEL_INSTRUMENTED | sqlalchemy")
            except ImportError:
                pass

        # Instrument Celery
        try:
            from opentelemetry.instrumentation.celery import CeleryInstrumentor
            CeleryInstrumentor().instrument()
            logger.info("OTEL_INSTRUMENTED | celery")
        except ImportError:
            pass

        # Instrument httpx
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
            HTTPXClientInstrumentor().instrument()
            logger.info("OTEL_INSTRUMENTED | httpx")
        except ImportError:
            pass

        logger.info("OTEL_SETUP_COMPLETE | env={}", settings.ENVIRONMENT)

    except ImportError:
        logger.info("OTEL_NOT_AVAILABLE | opentelemetry packages not installed")
    except Exception as e:
        logger.warning("OTEL_SETUP_FAILED | error={}", str(e))
