# Multi-stage Dockerfile for Meta Ops Agent
# Supports: FastAPI backend, Celery workers

FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create logs and exports directories
RUN mkdir -p /app/logs /app/exports

# Create non-root user for security
RUN addgroup --system appuser && adduser --system --ingroup appuser appuser
RUN chown -R appuser:appuser /app
USER appuser

# ── API server ───────────────────────────────────────────────────────────────
FROM base AS api

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health/live || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

# ── Celery worker ────────────────────────────────────────────────────────────
FROM base AS worker

# Queue and concurrency set via docker-compose environment/command
CMD ["celery", "-A", "backend.src.infra.celery_app:celery_app", "worker", "--loglevel=info"]
