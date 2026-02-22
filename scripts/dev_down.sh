#!/usr/bin/env bash
# Sprint 12 — BLOQUE A: Stop all dev services.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.dev_pids"

echo "=== META-OPS-AGENT: Stopping dev environment ==="

if [ -f "$PID_FILE" ]; then
    while read -r pid; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "  Killing PID $pid..."
            kill "$pid" 2>/dev/null || true
        fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
    echo "  PID file cleaned up."
else
    echo "  No PID file found."
fi

# Fallback: kill by port
for port in 8000 5173; do
    pid=$(lsof -ti :"$port" 2>/dev/null || true)
    if [ -n "$pid" ]; then
        echo "  Killing process on port $port (PID $pid)..."
        kill "$pid" 2>/dev/null || true
    fi
done

echo "=== All services stopped ==="
