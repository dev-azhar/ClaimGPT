#!/usr/bin/env bash
# =====================================================
# Run a single service locally (outside Docker)
# =====================================================
# Usage:
#   ./infra/scripts/run-service.sh ingress
#   ./infra/scripts/run-service.sh ocr --port 8002
# =====================================================

set -euo pipefail

SERVICE="${1:?Usage: $0 <service_name> [--port PORT]}"
PORT="${3:-8000}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_DIR="$ROOT_DIR/services/$SERVICE"

if [[ ! -d "$SERVICE_DIR" ]]; then
    echo "Error: Service '$SERVICE' not found at $SERVICE_DIR"
    exit 1
fi

# Set default env vars
export "${SERVICE^^}_DATABASE_URL=${DATABASE_URL:-postgresql://claimgpt:claimgpt@postgres:5432/claimgpt}"

echo "[claimgpt] Starting $SERVICE on port $PORT..."
cd "$SERVICE_DIR"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
