# --- Celery monitoring ---
flower:
	.venv/Scripts/flower --app=libs.shared.celery_app --port=5555
# =====================================================
# ClaimGPT — Top-Level Makefile
# =====================================================

.PHONY: help install dev infra up down build test lint health seed clean gateway worker worker-bg worker-stop sync verify-deps hooks

COMPOSE := docker compose -f infra/docker/docker-compose.yml
SERVICES := ingress ocr parser coding predictor validator workflow submission chat search
OCR_VL ?= false
OCR_SECONDARY_PDF_OCR ?= false

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# -------------------------------------------------- Local Dev
install: ## Install Python dependencies (all services)
	@for svc in $(SERVICES); do \
		echo "📦 Installing $$svc..."; \
		pip install -r services/$$svc/requirements.txt -q; \
	done
	pip install -r requirements-dev.txt -q
	@echo "✅ All dependencies installed"

dev: ## Start infra (Postgres, Redis, MinIO) for local dev
	$(COMPOSE) up -d postgres redis minio
	@echo "⏳ Waiting for Postgres..."
	@until $(COMPOSE) exec -T postgres pg_isready -U claimgpt 2>/dev/null; do sleep 1; done
	@echo "✅ Infrastructure ready"

# -------------------------------------------------- Docker
infra: dev ## Alias for 'dev'

up: ## Start ALL services via Docker Compose (override: make up OCR_VL=true OCR_SECONDARY_PDF_OCR=true)
	@OCR_ENABLE_PADDLE_VL=$(OCR_VL) OCR_ENABLE_SECONDARY_OCR_ON_PDF=$(OCR_SECONDARY_PDF_OCR) $(COMPOSE) up -d --build
	@echo "✅ All services started"

down: ## Stop all Docker Compose services
	$(COMPOSE) down
	@echo "🛑 All services stopped"

build: ## Build all Docker images (no start)
	$(COMPOSE) build

# -------------------------------------------------- Quality
test: ## Run all tests with pytest
	python -m pytest tests/ -v --tb=short

test-svc: ## Run tests for one service: make test-svc SVC=ingress
	python -m pytest tests/$(SVC)/ -v --tb=short

lint: ## Lint all Python code with ruff
	python -m ruff check services/ libs/ tests/

fmt: ## Format all Python code with ruff
	python -m ruff format services/ libs/ tests/

typecheck: ## Run mypy type checking
	python -m mypy services/ libs/ --ignore-missing-imports

# -------------------------------------------------- Dependencies
sync: ## Align local .venv exactly to requirements.txt (fixes post-pull drift)
	@if [ ! -x ".venv/bin/python" ]; then \
		echo "❌ .venv not found — create it first: python -m venv .venv"; exit 1; \
	fi
	.venv/bin/python -m pip install -r requirements.txt --upgrade
	.venv/bin/python infra/scripts/verify_deps.py

verify-deps: ## Check installed pinned versions match requirements.txt
	@if [ -x ".venv/bin/python" ]; then \
		.venv/bin/python infra/scripts/verify_deps.py; \
	else \
		python infra/scripts/verify_deps.py; \
	fi

verify-deps-cross: ## Check per-service requirements.txt files agree with root
	@if [ -x ".venv/bin/python" ]; then \
		.venv/bin/python infra/scripts/verify_deps.py --cross-check; \
	else \
		python infra/scripts/verify_deps.py --cross-check; \
	fi

verify-deps-all: ## Run both installed and cross-file dependency checks
	@if [ -x ".venv/bin/python" ]; then \
		.venv/bin/python infra/scripts/verify_deps.py --all; \
	else \
		python infra/scripts/verify_deps.py --all; \
	fi

hooks: ## Install repo git hooks (pre-push dep check)
	git config core.hooksPath .githooks
	@echo "✅ Git hooks enabled (pre-push runs verify-deps)"

# -------------------------------------------------- Operations
health: ## Health-check all running services
	@bash infra/scripts/healthcheck.sh

seed: ## Seed database with sample data
	@bash infra/scripts/seed-data.sh

schema: ## Apply database schema to running Postgres
	$(COMPOSE) exec -T postgres psql -U claimgpt -d claimgpt \
		-f /docker-entrypoint-initdb.d/01-schema.sql

run: ## Run a single service locally: make run SVC=ingress PORT=8001
	@bash infra/scripts/run-service.sh $(SVC) --port $(or $(PORT),8000)

gateway: ## Run unified gateway (defaults: OCR_VL=false OCR_SECONDARY_PDF_OCR=false)
	@if [ ! -x ".venv/bin/python" ]; then \
		echo "Create .venv first: python -m venv .venv"; \
		exit 1; \
	fi
	@if ! .venv/bin/python -m pip show uvicorn >/dev/null 2>&1; then \
		echo "Installing Python dependencies into .venv (one-time)..."; \
		.venv/bin/python -m pip install -r requirements.txt; \
	fi
	@echo "Starting gateway with OCR VL=$(OCR_VL), secondary_pdf_ocr=$(OCR_SECONDARY_PDF_OCR)"
	@PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True OCR_ENABLE_PADDLE_OCR=true OCR_ENABLE_PADDLE_VL=$(OCR_VL) OCR_ENABLE_SECONDARY_OCR_ON_PDF=$(OCR_SECONDARY_PDF_OCR) PREDICTOR_MODEL_DIR=/tmp/claimgpt-models .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --no-access-log --timeout-graceful-shutdown 10

worker: ## Start a Celery worker that consumes both `default` and `gpu_queue` (foreground)
	@if [ ! -x ".venv/bin/python" ]; then \
		echo "Create .venv first: python -m venv .venv"; \
		exit 1; \
	fi
	@echo "Starting Celery worker (queues: default,gpu_queue)..."
	@PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True OCR_ENABLE_PADDLE_OCR=true PREDICTOR_MODEL_DIR=/tmp/claimgpt-models \
		.venv/bin/python -m celery -A libs.shared.celery_app worker \
			--loglevel=info \
			-Q default,gpu_queue \
			--pool=threads \
			--concurrency=4 \
			--hostname=local@%h

worker-bg: ## Start the worker in the background (logs -> logs/celery_worker.log)
	@mkdir -p logs
	@if pgrep -f 'celery -A libs.shared.celery_app worker' >/dev/null; then \
		echo "Celery worker already running."; \
	else \
		nohup env PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True OCR_ENABLE_PADDLE_OCR=true PREDICTOR_MODEL_DIR=/tmp/claimgpt-models \
			.venv/bin/python -m celery -A libs.shared.celery_app worker \
				--loglevel=info \
				-Q default,gpu_queue \
				--pool=threads \
				--concurrency=4 \
				--hostname=local@%h \
				> logs/celery_worker.log 2>&1 & \
		echo "Worker started in background. Tail logs: tail -f logs/celery_worker.log"; \
	fi

worker-stop: ## Stop background Celery worker(s)
	@pkill -f 'celery -A libs.shared.celery_app worker' && echo "Worker stopped." || echo "No worker process found."

# -------------------------------------------------- Cleanup
clean: ## Remove all containers, volumes, and build artifacts
	$(COMPOSE) down -v --remove-orphans
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "🧹 Clean complete"
