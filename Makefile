# =====================================================
# ClaimGPT — Top-Level Makefile
# =====================================================

.PHONY: help install dev infra up down build test lint health seed clean

COMPOSE := docker compose -f infra/docker/docker-compose.yml
SERVICES := ingress ocr parser coding predictor validator workflow submission chat search

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

up: ## Start ALL services via Docker Compose
	$(COMPOSE) up -d --build
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

# -------------------------------------------------- Cleanup
clean: ## Remove all containers, volumes, and build artifacts
	$(COMPOSE) down -v --remove-orphans
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "🧹 Clean complete"
