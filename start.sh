#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Activate venv if it exists (local dev), otherwise assume global install (Docker)
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
  source "$SCRIPT_DIR/venv/bin/activate"
fi

echo "Running database migrations..."
alembic upgrade head

echo "Starting uvicorn..."
exec uvicorn app:app --host 0.0.0.0 --port 8000
