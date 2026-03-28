#!/usr/bin/env bash
# =====================================================
# Health check all running ClaimGPT services
# =====================================================

set -euo pipefail

SERVICES=(
    "ingress:8001"
    "ocr:8002"
    "parser:8003"
    "coding:8004"
    "predictor:8005"
    "validator:8006"
    "workflow:8007"
    "submission:8008"
    "chat:8009"
    "search:8010"
)

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "ClaimGPT Service Health Check"
echo "=============================="

for entry in "${SERVICES[@]}"; do
    name="${entry%%:*}"
    port="${entry##*:}"
    url="http://localhost:$port/health"

    printf "%-15s " "$name"

    if response=$(curl -sf --max-time 3 "$url" 2>/dev/null); then
        status=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "?")
        if [[ "$status" == "ok" ]]; then
            echo -e "${GREEN}OK${NC}  ($url)"
        else
            echo -e "${YELLOW}$status${NC}  ($url)"
        fi
    else
        echo -e "${RED}DOWN${NC}  ($url)"
    fi
done
