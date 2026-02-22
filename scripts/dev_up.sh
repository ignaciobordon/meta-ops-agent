#!/usr/bin/env bash
# Sprint 12 — BLOQUE A: One-command dev environment boot.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PID_FILE="$SCRIPT_DIR/.dev_pids"

echo "=== META-OPS-AGENT: Starting dev environment ==="
echo ""

# Clean up stale PID file
rm -f "$PID_FILE"

# 1. Check Redis
REDIS_OK=false
if redis-cli ping >/dev/null 2>&1; then
    echo "[OK] Redis: running"
    REDIS_OK=true
else
    echo "[WARN] Redis not running."
    if command -v redis-server &>/dev/null; then
        echo "       Attempting to start redis-server..."
        redis-server --daemonize yes 2>/dev/null || true
        sleep 1
        if redis-cli ping >/dev/null 2>&1; then
            echo "       Redis started successfully."
            REDIS_OK=true
        fi
    fi
    if [ "$REDIS_OK" = false ]; then
        echo "       Jobs will run via sync fallback (no Celery)."
    fi
fi

# 2. Python env check
echo ""
cd "$PROJECT_ROOT"
python scripts/env_check.py || echo "[WARN] Some env checks failed. Continuing..."
echo ""

# 3. Start backend (uvicorn)
echo "[START] Backend (uvicorn) on :8000..."
cd "$PROJECT_ROOT"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
echo $! >> "$PID_FILE"

# 4. Start frontend (vite)
echo "[START] Frontend (vite) on :5173..."
cd "$PROJECT_ROOT/frontend"
npm run dev &
echo $! >> "$PID_FILE"
cd "$PROJECT_ROOT"

# 5. Start Celery workers (if Redis is available)
if [ "$REDIS_OK" = true ]; then
    echo "[START] Celery worker: default queue..."
    celery -A backend.src.infra.celery_app worker --queues=default --concurrency=2 --loglevel=info &
    echo $! >> "$PID_FILE"

    echo "[START] Celery worker: io queue..."
    celery -A backend.src.infra.celery_app worker --queues=io --concurrency=2 --loglevel=info &
    echo $! >> "$PID_FILE"

    echo "[START] Celery worker: llm queue..."
    celery -A backend.src.infra.celery_app worker --queues=llm --concurrency=1 --loglevel=info &
    echo $! >> "$PID_FILE"
else
    echo "[INFO] Skipping Celery workers (Redis not available)."
    echo "       Jobs will run via sync fallback in the API process."
fi

echo ""
echo "=== All services started ==="
echo "   Backend:  http://localhost:8000"
echo "   Frontend: http://localhost:5173"
echo "   API docs: http://localhost:8000/docs"
echo ""
echo "   To stop:  bash scripts/dev_down.sh"
