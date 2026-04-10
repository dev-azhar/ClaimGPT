#!/usr/bin/env bash
# =====================================================
# ClaimGPT — Local Development Bootstrap
# =====================================================
# Starts infrastructure (Postgres, Redis, MinIO), applies DB schema,
# and optionally starts all services.
#
# Usage:
#   ./infra/scripts/dev-setup.sh          # infra only
#   ./infra/scripts/dev-setup.sh --all    # infra + services
# =====================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[claimgpt]${NC} $*"; }
warn() { echo -e "${YELLOW}[claimgpt]${NC} $*"; }

# -------------------------------------------------- Step 1: Start infra
log "Starting Postgres, Redis, MinIO..."
docker compose -f "$COMPOSE_FILE" up -d postgres redis minio

log "Waiting for Postgres to be ready..."
until docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U claimgpt 2>/dev/null; do
    sleep 1
done
log "Postgres is ready."

# -------------------------------------------------- Step 2: Apply schema
log "Applying database schema..."
docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -U claimgpt -d claimgpt -f /docker-entrypoint-initdb.d/01-schema.sql 2>/dev/null || \
    warn "Schema may already exist (safe to ignore duplicate errors)"

# -------------------------------------------------- Step 3: Create MinIO bucket
log "Creating MinIO bucket 'claimgpt'..."
docker compose -f "$COMPOSE_FILE" exec -T minio \
    mc alias set local http://localhost:9000 claimgpt claimgpt123 2>/dev/null || true
docker compose -f "$COMPOSE_FILE" exec -T minio \
    mc mb local/claimgpt --ignore-existing 2>/dev/null || true

# -------------------------------------------------- Step 4: Optionally start services
if [[ "${1:-}" == "--all" ]]; then
    log "Building and starting all services..."
    docker compose -f "$COMPOSE_FILE" up -d --build
    log "All services started. Ports:"
    echo "  Ingress:    http://localhost:8001"
    echo "  OCR:        http://localhost:8002"
    echo "  Parser:     http://localhost:8003"
    echo "  Coding:     http://localhost:8004"
    echo "  Predictor:  http://localhost:8005"
    echo "  Validator:  http://localhost:8006"
    echo "  Workflow:   http://localhost:8007"
    echo "  Submission: http://localhost:8008"
    echo "  Chat:       http://localhost:8009"
    echo "  Search:     http://localhost:8010"
else
    log "Infrastructure ready. Start services individually or use --all."
fi

echo ""
log "Postgres:  localhost:5432  (claimgpt/claimgpt)"
log "Redis:     localhost:6379"
log "MinIO:     localhost:9000  (console: localhost:9001)"
echo ""
log "Done!"
