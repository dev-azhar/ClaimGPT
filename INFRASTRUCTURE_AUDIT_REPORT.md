# ClaimGPT Infrastructure & Deployment Audit Report

**Date:** May 1, 2026  
**Scope:** Complete analysis of Docker orchestration, CI/CD, microservices architecture, and production readiness  
**Status:** ⚠️ **NOT PRODUCTION READY** — Critical networking and configuration issues identified

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Docker & Orchestration Analysis](#docker--orchestration-analysis)
3. [Dockerfile Deep-Dive](#dockerfile-deep-dive)
4. [CI/CD & Automation Analysis](#cicd--automation-analysis)
5. [Architectural Alignment (Proposal vs. Reality)](#architectural-alignment-proposal-vs-reality)
6. [Scalability & Performance Risks](#scalability--performance-risks)
7. [Critical Gaps & Fixes](#critical-gaps--fixes)
8. [Production-Readiness Checklist](#production-readiness-checklist)

---

## Executive Summary

### 🔴 **Critical Issues Found:**

1. **FATAL: Hardcoded `localhost` defaults in service configurations** — Services will NOT communicate inside Docker containers
2. **FATAL: GPU queue configured with concurrency=1** — OCR and Parser tasks bottleneck; cannot scale
3. **FATAL: No resource limits in docker-compose.yml** — Services can consume unlimited CPU/memory
4. **HIGH: Missing environment variable overrides** — Many services don't respect env vars in docker-compose
5. **HIGH: OCR service runs both FastAPI + Celery worker** — Conflicting responsibilities; unclear resource allocation
6. **MEDIUM: No GPU support configured** — Even if hardware available, containers won't access GPU
7. **MEDIUM: MinIO integration incomplete** — No client configuration in services; fallback to local storage unclear
8. **MEDIUM: PostgreSQL volume may be ephemeral** — Data loss risk on container restart
9. **MEDIUM: CI/CD secrets not validated** — GitHub Actions may fail if secrets are missing

### ✅ **What's Working Well:**

- ✅ Microservices are properly separated into individual containers
- ✅ Service networking uses container DNS (gateway, ocr, parser, etc.) — **IF environment variables are set correctly**
- ✅ Celery queue routing is properly configured (gpu_queue vs default)
- ✅ CI/CD pipeline structure is sound (lint, test, build, deploy)
- ✅ Database schema migrations are properly versioned (Alembic)
- ✅ Health checks are defined for infrastructure services (postgres, redis, minio, keycloak)

---

## Docker & Orchestration Analysis

### 1. Service Mapping (docker-compose.yml)

**Current services and their definitions:**

```
┌─ GATEWAY (Port 8000) — API Router
│  └─ depends_on: All application services
│  └─ Provides unified API endpoint
│  └─ Routes requests to individual microservices
│
├─ CELERY WORKERS
│  ├─ worker_gpu (Q: gpu_queue, concurrency=1)
│  │  └─ Runs ocr_task, parser_task
│  │  └─ ⚠️ BOTTLENECK: Only 1 concurrent task!
│  ├─ worker_cpu (Q: default, concurrency=4)
│  │  └─ Runs coding_task, risk_task, validator_task, finalize_claim_task
│  └─ flower (Port 5555) — Celery monitoring UI
│
├─ INFRASTRUCTURE
│  ├─ postgres:16-alpine (Port 5432)
│  │  └─ Volume: pgdata:/var/lib/postgresql/data
│  │  └─ Health check: pg_isready
│  ├─ redis:7-alpine (Port 6379)
│  │  └─ Broker for Celery + Result backend
│  │  └─ Health check: redis-cli ping
│  ├─ minio:latest (Port 9000, 9001)
│  │  └─ Object storage (S3-compatible)
│  │  └─ Volume: miniodata:/data
│  │  └─ ⚠️ NO INTEGRATION IN SERVICES
│  └─ keycloak:24.0 (Port 8080)
│     └─ Auth provider (disabled in compose env)
│
└─ APPLICATION SERVICES
   ├─ ingress (Port 8001) — Document upload
   ├─ ocr (Port 8002) — OCR extraction
   │  └─ ⚠️ Dual responsibility: FastAPI + gpu_queue worker
   ├─ parser (Port 8003) — Field extraction
   ├─ coding (Port 8004) — Medical coding (NER)
   ├─ predictor (Port 8005) — Risk scoring
   ├─ validator (Port 8006) — Rules validation
   ├─ workflow (Port 8007) — Orchestration
   ├─ submission (Port 8008) — Report generation
   ├─ chat (Port 8009) — Chat service
   └─ search (Port 8010) — Vector search
```

### 2. Service Networking

**How services communicate (inside containers):**

```
gateway:8000
 ├─ INGRESS_URL: http://ingress:8000
 ├─ OCR_URL: http://ocr:8000
 ├─ PARSER_URL: http://parser:8000
 ├─ CODING_URL: http://coding:8000
 ├─ PREDICTOR_URL: http://predictor:8000
 ├─ VALIDATOR_URL: http://validator:8000
 ├─ WORKFLOW_URL: http://workflow:8000
 ├─ SUBMISSION_URL: http://submission:8000
 ├─ CHAT_URL: http://chat:8000
 └─ SEARCH_URL: http://search:8000

Celery Task Orchestration:
 ├─ CELERY_BROKER_URL: redis://redis:6379/0 ✓
 ├─ CELERY_RESULT_BACKEND: redis://redis:6379/0 ✓
 └─ Queue routing:
     ├─ ocr_task → gpu_queue → worker_gpu
     ├─ parser_task → gpu_queue → worker_gpu
     └─ coding_task, risk_task, validator_task, finalize_claim_task → default → worker_cpu

Database connections:
 ├─ All services → DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt ✓
 └─ Workers → WORKFLOW_DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt ✓
```

**Network resolution (Docker DNS):**
- ✅ Service names resolve via Docker's embedded DNS (e.g., `postgres:5432`, `redis:6379`)
- ✅ All services are on the same `default` bridge network (implicit in docker-compose)
- ✅ Container-to-container communication works **if environment variables are set correctly**

### 3. **CRITICAL NETWORKING ISSUES** 🔴

#### Issue 3.1: Hardcoded `localhost` in Service Configurations

**Problem:** Services define hardcoded `localhost` defaults that will fail inside containers.

**Affected Services:**

| Service | Config File | Issue |
|---------|------------|-------|
| **workflow** | `services/workflow/app/config.py:10-18` | All service URLs default to `http://localhost:8000/...` |
| **workflow** | `services/workflow/app/config.py:10` | DATABASE_URL defaults to `localhost:5432` |
| **ocr** | `services/ocr/app/config.py:14-15` | REDIS_URL and DATABASE_URL default to `localhost` |
| **ingress** | `services/ingress/app/config.py:14-15` | REDIS_URL and DATABASE_URL default to `localhost` |
| **parser** | `services/parser/app/config.py:14-15` | REDIS_URL and DATABASE_URL default to `localhost` |
| **predictor** | `services/predictor/app/config.py:13-14` | REDIS_URL and DATABASE_URL default to `localhost` |
| **coding** | `services/coding/app/config.py:11` | DATABASE_URL defaults to `localhost:5432` |
| **validator** | `services/validator/app/config.py:10` | DATABASE_URL defaults to `localhost:5432` |
| **search** | `services/search/app/config.py:7-8` | DATABASE_URL defaults to `localhost:5432` |

**Why it breaks:**
```
When a container starts, localhost:5432 points to INSIDE that container's network namespace.
There is NO PostgreSQL service running inside the workflow container.
Connection attempts will fail immediately.
```

**Example failure scenario:**
```python
# services/workflow/app/config.py (line 10)
database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"  # WRONG!

# When workflow container starts:
# It tries to connect to localhost:5432
# There's no postgres process inside the workflow container
# Result: Connection refused
# Fix: Environment variable WORKFLOW_DATABASE_URL should be set in docker-compose.yml
```

**Docker-compose.yml Status:**
```yaml
gateway:
  environment:
    DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt  # ✓ CORRECT
    OCR_URL: http://ocr:8000  # ✓ CORRECT
    # ...

workflow:  # ✓ SETS env vars correctly
  environment:
    DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
    WORKFLOW_INGRESS_URL: http://ingress:8000
    WORKFLOW_OCR_URL: http://ocr:8000
    # ...

ocr:  # ❌ MISSING many env vars!
  environment:
    DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt  # ✓
    OCR_DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt  # ✓
    # But: OCR_REDIS_URL is NOT SET, will default to localhost!

parser:  # ❌ MISSING ALL env vars for Redis/DB!
  environment:
    DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt  # ✓
    PARSER_DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt  # ✓
    # But: PARSER_REDIS_URL is NOT SET, will default to localhost!
```

#### Issue 3.2: Workflow Service Cannot Call Other Services

**Problem:** Workflow orchestrator has hardcoded localhost URLs.

```python
# services/workflow/app/config.py (lines 13-18)
ocr_url: str = "http://localhost:8000/ocr"        # WRONG! Should be http://ocr:8000
parser_url: str = "http://localhost:8000/parser"  # WRONG! Should be http://parser:8000
coding_url: str = "http://localhost:8000/coding"  # WRONG! Should be http://coding:8000
predictor_url: str = "http://localhost:8000/predictor"  # WRONG!
validator_url: str = "http://localhost:8000/validator"  # WRONG!
submission_url: str = "http://localhost:8000/submission"  # WRONG!
```

**Docker-compose provides correct URLs:**
```yaml
workflow:
  environment:
    WORKFLOW_INGRESS_URL: http://ingress:8000  # ✓ CORRECT
    WORKFLOW_OCR_URL: http://ocr:8000  # ✓ CORRECT
    WORKFLOW_PARSER_URL: http://parser:8000  # ✓ CORRECT
    WORKFLOW_CODING_URL: http://coding:8000  # ✓ CORRECT
    # ...
```

**BUT:** Service config expects prefixed env vars (`WORKFLOW_OCR_URL`) but defaults to `ocr_url` (no prefix).  
The Pydantic `model_config = {"env_prefix": "WORKFLOW_"}` means the env var lookup is correct, BUT the **hardcoded defaults are wrong**.

**When Workflow calls OCR from inside container:**
```
Attempt: POST http://localhost:8000/ocr/extract
Where does this go? → Inside workflow container's localhost
Is there an OCR service running there? → NO
Result: Connection refused / timeout
```

---

### 4. Environment Variable Coverage Matrix

**Services and environment variable configuration in docker-compose.yml:**

| Service | Config Supports Env Vars? | Docker-Compose Sets Vars? | Notes |
|---------|--------------------------|---------------------------|-------|
| gateway | N/A (reads from child services) | ✓ Full coverage | Routes requests only |
| ingress | ✓ (INGRESS_*) | ⚠️ Partial (missing INGRESS_REDIS_URL) | Uses `redis_url` fallback to localhost |
| ocr | ✓ (OCR_*) | ⚠️ Partial (missing OCR_REDIS_URL) | Uses `redis_url` fallback to localhost |
| parser | ✓ (PARSER_*) | ❌ NONE! | Defaults all to localhost |
| coding | ✓ (no prefix, direct DATABASE_URL) | ⚠️ Partial (sets DATABASE_URL) | Missing REDIS_URL |
| predictor | ✓ (no prefix) | ⚠️ Partial | Missing REDIS_URL |
| validator | ✓ (no prefix) | ❌ NONE! | Defaults all to localhost |
| workflow | ✓ (WORKFLOW_*) | ✓ Full coverage | Correctly configured |
| submission | ✓ (no prefix) | ⚠️ Partial | Missing REDIS_URL (if needed) |
| chat | ✓ (no prefix) | ⚠️ Partial | Missing REDIS_URL |
| search | ✓ (no prefix) | ⚠️ Partial | Missing REDIS_URL |

### 5. Volume Mounting Configuration

| Volume | Mount Path | Purpose | Persistence | Status |
|--------|------------|---------|-------------|--------|
| `pgdata` | `/var/lib/postgresql/data` | Database persistence | ✓ Host-mounted | ✓ Correct |
| `miniodata` | `/data` | MinIO object storage | ✓ Host-mounted | ✓ Correct |
| `shared-storage` | `/app/services/ingress/storage/raw` | Shared document storage | ✓ Host-mounted | ✓ Correct (but local only) |

**Status:** ✅ Volumes are properly configured for local Docker Compose; will persist on host.

---

## Dockerfile Deep-Dive

### 1. Dockerfile.gateway

**Location:** `infra/docker/Dockerfile.gateway`

```dockerfile
FROM python:3.11-slim
WORKDIR /app

# Install build tools and CMake
RUN apt-get update && \
    apt-get install -y build-essential cmake && \
    rm -rf /var/lib/apt/lists/*

# Install requirements
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy application code
COPY . /app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Analysis:**
- ✅ Base image: `python:3.11-slim` (lightweight, appropriate for API)
- ✅ System dependencies: build-essential, cmake (needed for llama-cpp-python compilation)
- ✅ Pip optimization: `--upgrade pip` before installing
- ⚠️ **Issue:** Installs entire `requirements.txt` (all services' dependencies)
  - This is wasteful; gateway only needs routing logic
  - Result: Slow builds, large image, unnecessary dependencies
- ⚠️ **Issue:** No health check defined (should have HEALTHCHECK)
- ✅ Entrypoint: Correct for FastAPI/Uvicorn

**Estimated image size:** ~1.5 GB (due to torch, transformers, xgboost, lightgbm, paddleocr)

---

### 2. Dockerfile.ocr

**Location:** `infra/docker/Dockerfile.ocr`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install Tesseract, OpenCV dependencies, and build tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        libtesseract-dev \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY services/ocr/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared libs
COPY libs/ /app/libs/

# Copy all services for Celery import resolution
COPY services/ /app/services/

# Copy service code
COPY services/ocr/app/ /app/app/

# Copy entrypoint script
COPY services/ocr/start-ocr.sh /app/start-ocr.sh
RUN chmod +x /app/start-ocr.sh

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

**System Dependencies Analysis:**

| Package | Purpose | Status |
|---------|---------|--------|
| `tesseract-ocr` | Tesseract OCR engine | ✓ Installed |
| `tesseract-ocr-eng` | English language pack for Tesseract | ✓ Installed |
| `libtesseract-dev` | Tesseract development headers | ✓ Installed |
| `libgl1` | OpenGL runtime (needed for opencv-python-headless) | ✓ Installed |
| `libglib2.0-0` | GLIB runtime (needed for OpenCV/GUI libs) | ✓ Installed |
| `curl` | Health check utility | ✓ Installed |
| ❌ `poppler-utils` | PDF rendering (pdfplumber indirect dep) | **MISSING!** |
| ❌ `libsm6` | X11/display libs | **MISSING!** (may be needed for OpenCV) |
| ❌ `libxrender1` | X11 rendering | **MISSING!** (may be needed for OpenCV) |

**Issues:**

1. ⚠️ **Missing Poppler:** `pdfplumber` requires `pdfplumber` Python package, which MAY require `poppler-utils` on Linux.
   - Current: Not explicitly installed; may fail on PDF extraction
   - Fix: Add `apt-get install -y poppler-utils`

2. ⚠️ **OpenCV display libraries:** `libsm6`, `libxrender1`, `libxext6` may be needed
   - Current: Only `libgl1` and `libglib2.0-0` installed
   - Fix: Add these for full OpenCV compatibility

3. ✓ **Tesseract:** Correctly installed with English language pack
   - Pytesseract will find `/usr/bin/tesseract` correctly

4. ✅ **PaddleOCR:** Installed via pip; should work with current system libs

5. ⚠️ **Dual Responsibility:** OCR container runs BOTH:
   - FastAPI server (`uvicorn app.main:app --workers=2`)
   - Celery GPU worker (`start-ocr.sh` runs both in background)
   - This means:
     - If Celery worker crashes, FastAPI might keep running
     - If FastAPI crashes, Celery worker might keep running
     - Resource allocation is unclear (2 uvicorn workers + 1 celery = 3 Python processes)

**Entrypoint Script (`start-ocr.sh`):**

```bash
#!/bin/bash
set -e

# Start FastAPI app in background
uvicorn app.main:app --host 0.0.0.0 --port 8000 &

# Start Celery worker for gpu_queue
celery -A libs.shared.celery_app worker -Q gpu_queue --concurrency=1 --loglevel=info &

wait
```

**Issues:**
- Both processes run in background with `&`
- `wait` waits for all background processes
- If one crashes, the other continues (unclear failure mode)
- No process supervisor (should use `supervisord` or separate containers)

**Healthcheck:**
- ✅ HTTP GET to `/health` (if implemented)
- ✅ 15s interval, 5s timeout, 10s start delay
- ⚠️ Only checks FastAPI; doesn't check Celery worker status

---

### 3. Dockerfile.service (Generic Template)

**Location:** `infra/docker/Dockerfile.service`

```dockerfile
FROM python:3.11-slim AS base

ARG SERVICE_NAME
ENV SERVICE_NAME=${SERVICE_NAME}

WORKDIR /app
ENV PYTHONPATH=/app:/app/libs:/app/services

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        build-essential \
        cmake \
    && rm -rf /var/lib/apt/lists/*

# Increase pip timeout for large installs
ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=10

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy shared libs
COPY libs/ /app/libs/

# Copy all services for Celery autodiscovery
COPY services/ /app/services/

# Copy service code
COPY services/${SERVICE_NAME}/app/ /app/app/

# Create storage directory
RUN mkdir -p /app/storage/raw

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

**Analysis:**

| Aspect | Status | Notes |
|--------|--------|-------|
| **Base image** | ✓ `python:3.11-slim` | Lightweight, appropriate |
| **ARG SERVICE_NAME** | ✓ Parameterized | Allows reuse for different services |
| **PYTHONPATH** | ✓ Set correctly | Enables imports of libs and services |
| **System deps** | ⚠️ Minimal | Only `curl`, `build-essential`, `cmake`; missing service-specific deps |
| **Pip timeout** | ✓ 300s | Appropriate for large packages like torch, transformers |
| **pip --no-cache-dir** | ✓ | Reduces image size |
| **Copy order** | ⚠️ Suboptimal | Copies entire `requirements.txt` (all services) instead of service-specific |
| **Celery autodiscovery** | ✓ | Copies all services for import resolution |
| **Storage dir** | ✓ | `/app/storage/raw` created for ingress volume mount |
| **Healthcheck** | ✓ | Properly defined |

**Issues:**

1. ⚠️ **Installs all requirements:** Every service builds with full `requirements.txt`
   - Result: 1.5 GB image for each service
   - Should use: service-specific `requirements.txt`
   - Impact: Slow builds, large registry footprint

2. ⚠️ **Missing service-specific system deps:**
   - `parser` might need additional OCR dependencies if LayoutLMv3 fallback uses image processing
   - `coding` might need additional NLP dependencies
   - Currently assumes all services need only `curl`, `build-essential`, `cmake`

3. ✅ **Imports are correct:**
   - `COPY services/ /app/services/` ensures Celery can import all tasks
   - `PYTHONPATH` set correctly for imports

---

## CI/CD & Automation Analysis

### 1. Workflow Structure

**Location:** `.github/workflows/ci.yml`

**Jobs:**

```
ci.yml
├─ quality (lint/type check)
│  ├─ Runs on: ubuntu-latest
│  ├─ continue-on-error: true (informational only, doesn't block PRs)
│  ├─ Steps:
│  │  ├─ Checkout code
│  │  ├─ Setup Python 3.11
│  │  ├─ Install requirements-dev.txt + all service requirements
│  │  ├─ Lint with ruff (services/ libs/)
│  │  └─ Type check with mypy (services/ libs/ --ignore-missing-imports)
│  └─ Status: ⚠️ Soft gate (failures don't block)
│
├─ test (depends: quality)
│  ├─ Runs on: ubuntu-latest
│  ├─ Services: postgres:16-alpine on port 5432
│  ├─ Steps:
│  │  ├─ Checkout code
│  │  ├─ Setup Python 3.11
│  │  ├─ Install all requirements
│  │  ├─ Install psql client
│  │  ├─ Apply schema (claimgpt_schema.sql)
│  │  ├─ Run pytest (tests/ -v --tb=short)
│  │  └─ Upload test results artifact
│  └─ Status: ✓ Required gate (must pass)
│
├─ build (depends: test, if: main branch)
│  ├─ Runs on: ubuntu-latest with buildx
│  ├─ Matrix: ingress, ocr, parser, coding, predictor, validator, workflow, submission, chat, search
│  ├─ Authentication: Login to GHCR with GITHUB_TOKEN
│  ├─ For each service:
│  │  ├─ Determine Dockerfile (Dockerfile.ocr or Dockerfile.service)
│  │  ├─ Build and push to ghcr.io/${repo}/${service}:latest and :${sha}
│  │  └─ Cache via GitHub Actions Cache
│  └─ Status: ✓ Main branch only
│
└─ deploy (depends: build, if: main branch)
   ├─ Runs on: ubuntu-latest
   ├─ Environment: production
   ├─ Steps:
   │  └─ Placeholder: "Trigger ArgoCD sync for ClaimGPT"
   └─ Status: ⚠️ INCOMPLETE — No actual deployment
```

### 2. Test Infrastructure

**Database:**
- ✓ PostgreSQL 16-alpine spun up as GitHub Actions service
- ✓ Health check: `pg_isready -U claimgpt`
- ✓ Schema applied: `infra/db/claimgpt_schema.sql`

**Database URL:**
```yaml
DATABASE_URL: postgresql://claimgpt:claimgpt@localhost:5432/claimgpt
```
**Note:** Uses `localhost` because tests run ON the GitHub runner (not in containers).

**Test execution:**
```bash
python -m pytest tests/ -v --tb=short --junitxml=test-results.xml
```

**Issues:**
1. ⚠️ **No environment isolation:** Tests run against shared PostgreSQL
   - If test 1 modifies DB state, test 2 may fail (test pollution)
   - Should use transactions or database fixtures to isolate tests
2. ⚠️ **No Celery testing:** Tests don't verify async task execution
   - No Redis service configured in CI
   - No Celery task tests
3. ⚠️ **No OCR testing:** OCR tests may skip if Tesseract/PaddleOCR unavailable
   - CI doesn't install system dependencies for OCR
   - Tests might be skipped silently

### 3. Build & Push

**Registry:** `ghcr.io` (GitHub Container Registry)

**For each service:**
```
ghcr.io/owner/repo/ocr:latest
ghcr.io/owner/repo/ocr:${git_sha}
```

**Authentication:**
```yaml
with:
  registry: ghcr.io
  username: ${{ github.actor }}
  password: ${{ secrets.GITHUB_TOKEN }}
```

**Status:**
- ✓ Uses GitHub-provided token (no additional secrets needed)
- ✓ Matrix strategy (10 services × N commits = parallelized)
- ✓ Caching via GitHub Actions Cache (type=gha)
- ⚠️ **Issue:** `Dockerfile.ocr` is hardcoded for `ocr` service only
  - All other services use generic `Dockerfile.service`
  - Could be more explicit (add explicit if/else for other special cases)

### 4. Deployment (ArgoCD)

**Status:** ⚠️ **NOT IMPLEMENTED**

```yaml
deploy:
  steps:
    - name: Trigger ArgoCD sync
      run: |
        echo "🚀 Triggering ArgoCD sync for ClaimGPT..."
        # Replace with: argocd app sync claimgpt --grpc-web
        echo "Deploy step placeholder — configure ArgoCD webhook or CLI"
```

**Missing:**
- ❌ No ArgoCD webhook configured
- ❌ No ArgoCD CLI authentication
- ❌ No Kubernetes manifests versioning
- ❌ No helm charts or kustomize overlays
- ❌ No rollback strategy

---

## Architectural Alignment (Proposal vs. Reality)

### 1. Microservices Separation

**Proposal claim:** "Separate Ingress, OCR, and Parser services as independent containers"

**Reality check:**

| Service | Deployed as Container? | Has Independent Health Check? | Separate Queue? | Status |
|---------|------------------------|--------------------------------|-----------------|--------|
| Ingress | ✓ Yes (`ingress:8001`) | ✓ Yes (healthcheck defined) | ✓ Default queue | ✓ Proper |
| OCR | ✓ Yes (`ocr:8002`) | ✓ Yes (healthcheck defined) | ❌ Shared gpu_queue | ⚠️ Problematic |
| Parser | ✓ Yes (`parser:8003`) | ✓ Yes (healthcheck defined) | ❌ Shared gpu_queue | ⚠️ Problematic |
| Coding | ✓ Yes (`coding:8004`) | ✓ Yes (healthcheck defined) | ✓ Default queue | ✓ Proper |
| Predictor | ✓ Yes (`predictor:8005`) | ✓ Yes (healthcheck defined) | ✓ Default queue | ✓ Proper |
| Validator | ✓ Yes (`validator:8006`) | ✓ Yes (healthcheck defined) | ✓ Default queue | ✓ Proper |
| Workflow | ✓ Yes (`workflow:8007`) | ✓ Yes (healthcheck defined) | ❌ No queue (orchestrator) | ✓ Proper |
| Submission | ✓ Yes (`submission:8008`) | ✓ Yes (healthcheck defined) | ✓ Default queue | ✓ Proper |

**Conclusion:** ✅ Microservices ARE properly separated into independent containers.

### 2. OCR Service Dual Responsibility

**Problem:** OCR container runs BOTH FastAPI server AND gpu_queue worker.

```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

But `start-ocr.sh` also starts:
```bash
celery -A libs.shared.celery_app worker -Q gpu_queue --concurrency=1 --loglevel=info
```

**Issues:**
1. ⚠️ Resource contention: 2 Uvicorn workers + 1 Celery worker = 3 Python processes sharing container resources
2. ⚠️ Failure mode unclear: If Celery worker crashes, FastAPI continues (silent failure)
3. ⚠️ Not actually microservices: OCR is doing TWO JOBS
   - Should separate: `ocr-service` (FastAPI only) + `ocr-worker` (Celery worker only)

---

### 3. Storage Implementation

**Claim:** "MinIO correctly integrated as object store"

**Reality:**

**What exists:**
- ✓ MinIO service defined in docker-compose (port 9000, 9001)
- ✓ MinIO volume mounted: `miniodata:/data`
- ✓ MinIO credentials in .env.example: `MINIO_ROOT_USER=claimgpt`, `MINIO_ROOT_PASSWORD=claimgpt123`
- ✓ MINIO_ENDPOINT in .env.example: `http://minio:9000`

**What's missing:**
- ❌ **No S3 client configuration in any service**
- ❌ **No boto3/minio Python package in requirements.txt**
- ❌ **No file upload integration:**
  - `services/ingress/app/config.py` references `INGRESS_STORAGE_ROOT: /app/services/ingress/storage/raw`
  - This is a LOCAL filesystem path, not MinIO
- ❌ **No OCR file reading integration:**
  - OCR service reads from `shared-storage` volume mount (local filesystem)
  - Not from MinIO

**Current file flow:**
```
Upload (Ingress)
  └─ Stored: /app/services/ingress/storage/raw/ (local, in shared-storage volume)
  
OCR retrieval
  └─ Reads: /app/services/ingress/storage/raw/ (same local mount)
  
Parse retrieval
  └─ Database: OcrResult.text (not from MinIO)
```

**Conclusion:** ❌ MinIO is **NOT integrated**. It's running as a service but unused.
- All files currently go to local shared volumes
- MinIO is a dangling service (waste of resources)
- To implement: Would need boto3 client, upload handlers, OCR file retrieval changes

---

## Scalability & Performance Risks

### 1. GPU Queue Bottleneck

**Current configuration:**
```yaml
worker_gpu:
  command: celery -A libs.shared.celery_app worker -Q gpu_queue --concurrency=1
```

**Problem:** Only 1 task can run at a time on the GPU worker.

**Load scenario:**
```
Time 0:  ocr_task_1 arrives → Accepted by worker_gpu → Running
Time 1:  ocr_task_2 arrives → Queued (waiting)
Time 2:  ocr_task_3 arrives → Queued (waiting)
...
Time 100: ocr_task_1 completes
Time 101: ocr_task_2 starts

If each ocr_task takes 30 seconds:
100 concurrent uploads = 100 tasks in queue
100 tasks × 30 seconds = 50 MINUTES before all are processed!
```

**Impact on 1,000 concurrent users:**
- Queue depth: 1,000 tasks
- Time to process all: 1,000 × 30s = 8 hours+
- User experience: 8-hour waiting time
- System state: Redis memory grows indefinitely holding pending tasks

**Solution:** Increase `concurrency` value (if GPU can handle it).

### 2. No Resource Limits in docker-compose.yml

**Current:** No `deploy.resources` section defined

```yaml
# Current (MISSING):
worker_gpu:
  # NO resource limits!
  # Container can consume 100% CPU, all available memory
  
# Should have:
deploy:
  resources:
    requests:
      cpus: '2'
      memory: 8GB
    limits:
      cpus: '4'
      memory: 16GB
```

**Risk:** One runaway process (e.g., infinite loop in parser) crashes the entire host.

### 3. GPU Support Not Configured

**Current:** No GPU device configuration

```yaml
# Current (MISSING GPU):
worker_gpu:
  # No 'devices' or 'runtime' configuration
  # Even if NVIDIA GPU available, container won't access it

# Should have (for NVIDIA GPU):
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1  # or "all"
          capabilities: [gpu]

# Or use legacy Docker Compose syntax:
# runtime: nvidia  (deprecated)
```

**Issue:** If you have NVIDIA GPU, it won't be used. OCR/Parser run on CPU instead.

### 4. PostgreSQL Volume Persistence

**Configuration:**
```yaml
postgres:
  volumes:
    - pgdata:/var/lib/postgresql/data
```

**Persistence status:** ✓ **Data IS persisted** (Docker named volume `pgdata` is host-mounted by default in Docker Desktop)

**Risks:**
1. On production server: Needs explicit `volumes.pgdata.driver_opts.o=bind` or external volume driver
2. On Docker Desktop: Volume is stored in Docker VM, survives container restart but not full VM deletion
3. **Backup strategy:** ⚠️ **NOT DEFINED**
   - No automated backups
   - No backup verification tests
   - Single point of failure

---

## Critical Gaps & Fixes

### 🔴 CRITICAL FIXES REQUIRED (Blocking Production)

#### Fix 1: Set Missing Environment Variables in docker-compose.yml

**Current state:** Multiple services don't set required environment variables.

**File:** `infra/docker/docker-compose.yml`

**Changes needed:**

```yaml
# OCR service — ADD MISSING REDIS_URL
ocr:
  environment:
    DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
    OCR_DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
    OCR_REDIS_URL: redis://redis:6379/0  # ← ADD THIS LINE
    OCR_ENABLE_PADDLE_OCR: ${OCR_ENABLE_PADDLE_OCR:-true}
    OCR_ENABLE_PADDLE_VL: ${OCR_ENABLE_PADDLE_VL:-true}
    OCR_ENABLE_SECONDARY_OCR_ON_PDF: ${OCR_ENABLE_SECONDARY_OCR_ON_PDF:-true}
    REDIS_URL: redis://redis:6379/0  # ← ADD THIS LINE
    PYTHONPATH: /app

# Parser service — SET ALL MISSING VARS
parser:
  environment:
    DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
    PARSER_DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
    PARSER_REDIS_URL: redis://redis:6379/0  # ← ADD THIS LINE
    REDIS_URL: redis://redis:6379/0  # ← ADD THIS LINE

# Coding service — ADD MISSING REDIS_URL
coding:
  environment:
    DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
    REDIS_URL: redis://redis:6379/0  # ← ADD THIS LINE

# Predictor service — ADD MISSING REDIS_URL
predictor:
  environment:
    DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
    REDIS_URL: redis://redis:6379/0  # ← ADD THIS LINE

# Validator service — SET ALL MISSING VARS
validator:
  environment:
    DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
    REDIS_URL: redis://redis:6379/0  # ← ADD THIS LINE

# Chat service — ADD MISSING REDIS_URL
chat:
  environment:
    DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
    REDIS_URL: redis://redis:6379/0  # ← ADD THIS LINE

# Search service — ADD MISSING REDIS_URL
search:
  environment:
    DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
    REDIS_URL: redis://redis:6379/0  # ← ADD THIS LINE
```

---

#### Fix 2: Correct Hardcoded Localhost URLs in Service Configs

**Problem:** `services/workflow/app/config.py` has hardcoded localhost URLs that override env vars when not set.

**File:** `services/workflow/app/config.py` (lines 10-18)

**Current code:**
```python
database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"

# Downstream service URLs (unified gateway)
ocr_url: str = "http://localhost:8000/ocr"
parser_url: str = "http://localhost:8000/parser"
coding_url: str = "http://localhost:8000/coding"
predictor_url: str = "http://localhost:8000/predictor"
validator_url: str = "http://localhost:8000/validator"
submission_url: str = "http://localhost:8000/submission"
```

**Fixed code:**
```python
database_url: str = "postgresql://claimgpt:claimgpt@postgres:5432/claimgpt"  # Container DNS

# Downstream service URLs — use container DNS names
ocr_url: str = "http://ocr:8000"
parser_url: str = "http://parser:8000"
coding_url: str = "http://coding:8000"
predictor_url: str = "http://predictor:8000"
validator_url: str = "http://validator:8000"
submission_url: str = "http://submission:8000"
```

---

#### Fix 3: Fix Service Config Default Values

All service configs still use `localhost` defaults. These need to change:

**Services affected:**
- `services/ocr/app/config.py:14-15`
- `services/ingress/app/config.py:14-15`
- `services/parser/app/config.py:14-15`
- `services/predictor/app/config.py:13-14`
- `services/coding/app/config.py:11`
- `services/validator/app/config.py:10`
- `services/search/app/config.py:7`
- `libs/shared/config.py:5-8`

**Pattern:** All should use container DNS names, not localhost.

**Example: `services/ocr/app/config.py`**

**Current:**
```python
redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
database_url: str = os.environ.get("DATABASE_URL", "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt")
```

**Fixed:**
```python
redis_url: str = os.environ.get("REDIS_URL", "redis://redis:6379/0")  # Container DNS
database_url: str = os.environ.get("DATABASE_URL", "postgresql://claimgpt:claimgpt@postgres:5432/claimgpt")  # Container DNS
```

---

#### Fix 4: Scale GPU Queue

**File:** `infra/docker/docker-compose.yml` (worker_gpu)

**Current:**
```yaml
worker_gpu:
  command: celery -A libs.shared.celery_app worker -Q gpu_queue --concurrency=1
```

**Fixed (for multi-GPU or high-capacity GPU):**
```yaml
worker_gpu:
  command: celery -A libs.shared.celery_app worker -Q gpu_queue --concurrency=4
  # Or if using multiple GPU workers:
  # Scale up the number of worker_gpu replicas instead of increasing concurrency
```

**Or (better approach: separate workers for each GPU):**
```yaml
worker_gpu_0:
  build:
    context: ../../
    dockerfile: infra/docker/Dockerfile.service
    args:
      SERVICE_NAME: workflow
  command: celery -A libs.shared.celery_app worker -Q gpu_queue --concurrency=1 --hostname=gpu0@%h
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            device_ids: ['0']  # GPU 0
            capabilities: [gpu]

worker_gpu_1:
  build:
    context: ../../
    dockerfile: infra/docker/Dockerfile.service
    args:
      SERVICE_NAME: workflow
  command: celery -A libs.shared.celery_app worker -Q gpu_queue --concurrency=1 --hostname=gpu1@%h
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            device_ids: ['1']  # GPU 1
            capabilities: [gpu]
```

---

### ⚠️ HIGH-PRIORITY FIXES (Should fix before production)

#### Fix 5: Add Resource Limits to All Services

**File:** `infra/docker/docker-compose.yml`

**Add to each service:**

```yaml
worker_gpu:
  deploy:
    resources:
      requests:
        cpus: '2'
        memory: 8GB
      limits:
        cpus: '4'
        memory: 16GB

ocr:
  deploy:
    resources:
      requests:
        cpus: '2'
        memory: 4GB
      limits:
        cpus: '4'
        memory: 8GB

parser:
  deploy:
    resources:
      requests:
        cpus: '1'
        memory: 2GB
      limits:
        cpus: '2'
        memory: 4GB

# ... and all other services similarly
```

---

#### Fix 6: Add System Dependencies to OCR Dockerfile

**File:** `infra/docker/Dockerfile.ocr`

**Current:**
```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        libtesseract-dev \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*
```

**Fixed:**
```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        libtesseract-dev \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxrender1 \
        libxext6 \
        poppler-utils \
        curl \
    && rm -rf /var/lib/apt/lists/*
```

---

#### Fix 7: Add GPU Support to docker-compose.yml

**File:** `infra/docker/docker-compose.yml`

**Add to worker_gpu:**

```yaml
worker_gpu:
  build: ...
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1  # or "all" for all GPUs
            capabilities: [gpu]
```

---

#### Fix 8: Separate OCR Concerns

**Problem:** OCR container runs both FastAPI server and Celery worker.

**Solution:** Split into two containers:

```yaml
ocr:
  # FastAPI only
  build:
    context: ../../
    dockerfile: infra/docker/Dockerfile.ocr
  command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
  environment: ...
  ports:
    - "8002:8000"

ocr-worker:
  # GPU worker only
  build:
    context: ../../
    dockerfile: infra/docker/Dockerfile.service
    args:
      SERVICE_NAME: workflow
  command: celery -A libs.shared.celery_app worker -Q gpu_queue --concurrency=1 --hostname=ocr@%h
  environment: ...
  depends_on:
    - postgres
    - redis
```

---

### 📋 MEDIUM-PRIORITY FIXES (Recommended)

#### Fix 9: Implement MinIO Integration

**Current:** MinIO runs but is unused.

**Action:**
1. Add boto3 to requirements.txt
2. Create MinIO client in libs/shared/storage.py
3. Implement file upload to MinIO in ingress service
4. Update OCR service to read from MinIO
5. Remove local storage fallback (or keep as secondary backup)

---

#### Fix 10: Separate Docker Builds by Service

**Current:** Every service Dockerfile copies entire `requirements.txt`

**Fix:** Use service-specific requirements.txt

```dockerfile
# Current (Dockerfile.service)
COPY requirements.txt /app/requirements.txt  # Copies ALL services' deps

# Fixed
ARG SERVICE_NAME
COPY services/${SERVICE_NAME}/requirements.txt /app/requirements.txt  # Service-specific
```

**Impact:** Reduce image size from ~1.5GB to ~300-400MB per service.

---

#### Fix 11: Implement Full CI/CD Deployment

**Current:** Deploy job is a placeholder.

**Fix:** 
1. Set up ArgoCD webhook in GitHub
2. Create Kubernetes manifests (or use Helm)
3. Implement deployment verification
4. Add rollback strategy

---

#### Fix 12: Database Backup Strategy

**Add to Makefile:**

```makefile
backup:  ## Backup PostgreSQL database
	@mkdir -p backups
	$(COMPOSE) exec -T postgres pg_dump -U claimgpt claimgpt > backups/claimgpt-$(shell date +%Y%m%d-%H%M%S).sql
	@echo "✅ Backup created"

restore: ## Restore PostgreSQL database: make restore FILE=backups/claimgpt-20260501-120000.sql
	@if [ -z "$(FILE)" ]; then echo "Usage: make restore FILE=<backup_file>"; exit 1; fi
	@echo "⚠️  This will overwrite the current database!"
	@read -p "Continue? (y/n) " -n 1 -r; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		$(COMPOSE) exec -T postgres psql -U claimgpt claimgpt < $(FILE); \
		echo "✅ Restore complete"; \
	fi
```

---

## Production-Readiness Checklist

| Category | Item | Status | Priority | Effort | Notes |
|----------|------|--------|----------|--------|-------|
| **Networking** | Services use container DNS instead of localhost | ❌ | 🔴 CRITICAL | 1h | Affects all inter-service communication |
| **Networking** | All environment variables set in docker-compose | ⚠️ Partial | 🔴 CRITICAL | 1h | Missing REDIS_URL in multiple services |
| **GPU** | GPU support configured for worker_gpu | ❌ | 🔴 CRITICAL | 2h | NVIDIA device reservation needed |
| **GPU** | GPU queue concurrency increased to reasonable value | ❌ | 🔴 CRITICAL | 1h | Currently only 1, limits throughput |
| **Resources** | Resource limits defined for all services | ❌ | ⚠️ HIGH | 2h | Prevents runaway process crashes |
| **System Deps** | OCR container has all required system libraries | ⚠️ Partial | ⚠️ HIGH | 30m | Missing poppler-utils, libsm6 |
| **Separation** | OCR container FastAPI separated from Celery worker | ❌ | ⚠️ HIGH | 4h | Currently dual-purpose |
| **Storage** | MinIO integration implemented | ❌ | ⚠️ HIGH | 8h | Currently unused dangling service |
| **Backup** | Database backup automation configured | ❌ | ⚠️ HIGH | 2h | No backup strategy defined |
| **Monitoring** | Prometheus/Grafana metrics scraping configured | ❌ | 📋 MEDIUM | 4h | Can add later |
| **Logging** | Centralized logging (ELK/Loki) configured | ❌ | 📋 MEDIUM | 8h | Can add later |
| **CI/CD** | Deployment automation fully implemented | ❌ | 📋 MEDIUM | 6h | ArgoCD placeholder only |
| **Testing** | Celery task tests included in CI | ❌ | 📋 MEDIUM | 4h | No Redis in CI environment |
| **Testing** | OCR system dependencies available in CI | ❌ | 📋 MEDIUM | 2h | Tesseract not installed in CI |
| **Documentation** | Infrastructure architecture documented | ❌ | 📋 MEDIUM | 2h | Only code-level docs exist |
| **Load Testing** | 1,000 concurrent user simulation done | ❌ | 📋 MEDIUM | 16h | No load test results available |

---

## Summary of Changes Required for Production Readiness

### Phase 1: Critical Fixes (Before any production deployment)
**Effort: ~6 hours**

1. ✅ Fix service config defaults (localhost → container DNS)
2. ✅ Add missing environment variables to docker-compose.yml
3. ✅ Enable GPU support for worker_gpu
4. ✅ Increase gpu_queue concurrency
5. ✅ Add resource limits to all services

### Phase 2: High-Priority Improvements (Before sustained load)
**Effort: ~12 hours**

1. ✅ Add missing system dependencies to OCR Dockerfile
2. ✅ Separate OCR service into FastAPI + Worker containers
3. ✅ Implement MinIO file storage integration
4. ✅ Set up database backup automation
5. ✅ Add database transaction isolation for tests

### Phase 3: Production Operations (For long-term reliability)
**Effort: ~20 hours**

1. ✅ Implement full CI/CD deployment pipeline (ArgoCD)
2. ✅ Set up centralized monitoring (Prometheus/Grafana)
3. ✅ Set up centralized logging (ELK/Loki)
4. ✅ Implement load testing (1,000 concurrent users)
5. ✅ Create operational runbooks (alerts, incident response)

---

**Report generated:** 2026-05-01  
**Status:** Ready for review and implementation
