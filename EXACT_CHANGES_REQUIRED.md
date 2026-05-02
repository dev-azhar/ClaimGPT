# PRODUCTION-READY FIXES: Exact Line Changes Required

This file provides the exact changes needed for each file. Copy-paste ready.

---

## CRITICAL FIX #1: docker-compose.yml — Add Missing Environment Variables

**File:** `infra/docker/docker-compose.yml`

### Change 1.1: OCR Service

**Find (around line 170):**
```yaml
  ocr:
    build:
      context: ../../
      dockerfile: infra/docker/Dockerfile.ocr
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      OCR_DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      OCR_ENABLE_PADDLE_OCR: ${OCR_ENABLE_PADDLE_OCR:-true}
      OCR_ENABLE_PADDLE_VL: ${OCR_ENABLE_PADDLE_VL:-true}
      OCR_ENABLE_SECONDARY_OCR_ON_PDF: ${OCR_ENABLE_SECONDARY_OCR_ON_PDF:-true}
      REDIS_URL: redis://redis:6379/0
      PYTHONPATH: /app
```

**Replace with:**
```yaml
  ocr:
    build:
      context: ../../
      dockerfile: infra/docker/Dockerfile.ocr
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      OCR_DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      OCR_ENABLE_PADDLE_OCR: ${OCR_ENABLE_PADDLE_OCR:-true}
      OCR_ENABLE_PADDLE_VL: ${OCR_ENABLE_PADDLE_VL:-true}
      OCR_ENABLE_SECONDARY_OCR_ON_PDF: ${OCR_ENABLE_SECONDARY_OCR_ON_PDF:-true}
      OCR_REDIS_URL: redis://redis:6379/0  # ← ADDED
      REDIS_URL: redis://redis:6379/0
      PYTHONPATH: /app
```

### Change 1.2: Parser Service

**Find (around line 195):**
```yaml
  parser:
    build:
      context: ../../
      dockerfile: infra/docker/Dockerfile.service
      args:
        SERVICE_NAME: parser
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      PARSER_DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
    ports:
      - "8003:8000"
```

**Replace with:**
```yaml
  parser:
    build:
      context: ../../
      dockerfile: infra/docker/Dockerfile.service
      args:
        SERVICE_NAME: parser
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      PARSER_DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      PARSER_REDIS_URL: redis://redis:6379/0  # ← ADDED
      REDIS_URL: redis://redis:6379/0  # ← ADDED
    ports:
      - "8003:8000"
```

### Change 1.3: Coding Service

**Find (around line 207):**
```yaml
  coding:
    build:
      context: ../../
      dockerfile: infra/docker/Dockerfile.service
      args:
        SERVICE_NAME: coding
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      REDIS_URL: redis://redis:6379/0
    ports:
```

**Already correct** (REDIS_URL already set). ✓

### Change 1.4: Predictor Service

**Find (around line 221):**
```yaml
  predictor:
    build:
      context: ../../
      dockerfile: infra/docker/Dockerfile.service
      args:
        SERVICE_NAME: predictor
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      REDIS_URL: redis://redis:6379/0
    ports:
```

**Already correct** (REDIS_URL already set). ✓

### Change 1.5: Validator Service

**Find (around line 235):**
```yaml
  validator:
    build:
      context: ../../
      dockerfile: infra/docker/Dockerfile.service
      args:
        SERVICE_NAME: validator
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      REDIS_URL: redis://redis:6379/0
    ports:
```

**Already correct** (REDIS_URL already set). ✓

### Change 1.6: Ingress Service

**Find (around line 155):**
```yaml
  ingress:
    build:
      context: ../../
      dockerfile: infra/docker/Dockerfile.service
      args:
        SERVICE_NAME: ingress
    environment:
      INGRESS_DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      INGRESS_STORAGE_ROOT: /app/services/ingress/storage/raw
      REDIS_URL: redis://redis:6379/0
    ports:
```

**Already correct** (REDIS_URL already set). ✓

### Change 1.7: Chat Service

**Find (around line 275):**
```yaml
  chat:
    build:
      context: ../../
      dockerfile: infra/docker/Dockerfile.service
      args:
        SERVICE_NAME: chat
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      REDIS_URL: redis://redis:6379/0
    ports:
```

**Already correct** (REDIS_URL already set). ✓

### Change 1.8: Search Service

**Find (around line 291):**
```yaml
  search:
    build:
      context: ../../
      dockerfile: infra/docker/Dockerfile.service
      args:
        SERVICE_NAME: search
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      REDIS_URL: redis://redis:6379/0
    ports:
```

**Already correct** (REDIS_URL already set). ✓

---

## CRITICAL FIX #2: services/workflow/app/config.py — Fix Hardcoded localhost URLs

**File:** `services/workflow/app/config.py`

**Find (lines 10-18):**
```python
class Settings(BaseSettings):
    database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"

    # Downstream service URLs (unified gateway)
    ocr_url: str = "http://localhost:8000/ocr"
    parser_url: str = "http://localhost:8000/parser"
    coding_url: str = "http://localhost:8000/coding"
    predictor_url: str = "http://localhost:8000/predictor"
    validator_url: str = "http://localhost:8000/validator"
    submission_url: str = "http://localhost:8000/submission"
```

**Replace with:**
```python
class Settings(BaseSettings):
    database_url: str = "postgresql://claimgpt:claimgpt@postgres:5432/claimgpt"

    # Downstream service URLs (unified gateway) — use container DNS names
    ocr_url: str = "http://ocr:8000"
    parser_url: str = "http://parser:8000"
    coding_url: str = "http://coding:8000"
    predictor_url: str = "http://predictor:8000"
    validator_url: str = "http://validator:8000"
    submission_url: str = "http://submission:8000"
```

---

## HIGH-PRIORITY FIX #3: Dockerfile.ocr — Add Missing System Dependencies

**File:** `infra/docker/Dockerfile.ocr`

**Find (lines 11-19):**
```dockerfile
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
```

**Replace with:**
```dockerfile
# Install Tesseract, OpenCV dependencies, and build tools
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

## HIGH-PRIORITY FIX #4: docker-compose.yml — GPU Support Configuration

**File:** `infra/docker/docker-compose.yml`

**Find (around line 32-37):**
```yaml
  worker_gpu:
    build:
      context: ../../
      dockerfile: infra/docker/Dockerfile.service
      args:
        SERVICE_NAME: workflow
    command: celery -A libs.shared.celery_app worker -Q gpu_queue --concurrency=1 --loglevel=info
```

**Replace with:**
```yaml
  worker_gpu:
    build:
      context: ../../
      dockerfile: infra/docker/Dockerfile.service
      args:
        SERVICE_NAME: workflow
    command: celery -A libs.shared.celery_app worker -Q gpu_queue --concurrency=2 --loglevel=info --hostname=gpu@%h
```

**Then add after the `depends_on` section:**
```yaml
    deploy:
      resources:
        requests:
          cpus: '2'
          memory: 4G
        limits:
          cpus: '4'
          memory: 8G
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

---

## HIGH-PRIORITY FIX #5: docker-compose.yml — Add Resource Limits to All Services

**Add to EACH service** (example: worker_cpu)

**Find:**
```yaml
  worker_cpu:
    build:
      ...
    command: celery -A libs.shared.celery_app worker -Q default --concurrency=4 --loglevel=info
    environment:
      ...
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
```

**Add before/after the service definition (before next service):**
```yaml
    deploy:
      resources:
        requests:
          cpus: '2'
          memory: 2G
        limits:
          cpus: '4'
          memory: 4G
```

**Apply to all services:**

| Service | Insert Location | CPU Req | CPU Limit | Mem Req | Mem Limit |
|---------|-----------------|---------|-----------|---------|-----------|
| gateway | After depends_on | 1 | 2 | 512M | 1G |
| worker_gpu | After depends_on | 2 | 4 | 4G | 8G |
| worker_cpu | After depends_on | 2 | 4 | 2G | 4G |
| flower | After depends_on | 0.5 | 1 | 256M | 512M |
| postgres | After healthcheck | 1 | 2 | 512M | 1G |
| redis | After healthcheck | 0.5 | 1 | 256M | 512M |
| minio | After healthcheck | 0.5 | 1 | 256M | 512M |
| keycloak | After healthcheck | 0.5 | 1 | 256M | 512M |
| ingress | After volumes | 0.5 | 1 | 256M | 512M |
| ocr | After volumes | 1 | 2 | 2G | 4G |
| parser | After depends_on | 1 | 2 | 1G | 2G |
| coding | After depends_on | 0.5 | 1 | 512M | 1G |
| predictor | After depends_on | 0.5 | 1 | 512M | 1G |
| validator | After depends_on | 0.5 | 1 | 256M | 512M |
| workflow | After depends_on | 0.5 | 1 | 256M | 512M |
| submission | After depends_on | 0.5 | 1 | 256M | 512M |
| chat | After depends_on | 0.5 | 1 | 256M | 512M |
| search | After depends_on | 0.5 | 1 | 256M | 512M |

---

## Summary: Quick Copy-Paste Fixes

### For docker-compose.yml:

```bash
# 1. Add REDIS_URL to ocr service (around line 180)
sed -i 's/      REDIS_URL: redis:\/\/redis:6379\/0/      OCR_REDIS_URL: redis:\/\/redis:6379\/0\n      REDIS_URL: redis:\/\/redis:6379\/0/' infra/docker/docker-compose.yml

# 2. Add REDIS_URL to parser service (around line 200)
# Manual edit required — search for "parser:" and add lines

# 3. Increase gpu_queue concurrency and add GPU support
# Manual edit required — search for "gpu_queue" and replace
```

### For service config files:

```bash
# Fix all localhost references in workflow config
sed -i 's/localhost/postgres/g' services/workflow/app/config.py
sed -i 's/http:\/\/localhost:8000\//http:\/\//g' services/workflow/app/config.py
sed -i 's/ocr\//ocr:8000\//g' services/workflow/app/config.py

# Similar pattern for other services
sed -i 's/localhost/redis/g' services/ocr/app/config.py
sed -i 's/localhost/postgres/g' services/ocr/app/config.py
```

---

## Validation Commands

After applying all fixes:

```bash
# 1. Verify docker-compose.yml syntax
docker-compose -f infra/docker/docker-compose.yml config > /dev/null && echo "✓ YAML valid"

# 2. Check all REDIS_URL references
grep -n "REDIS_URL" infra/docker/docker-compose.yml | wc -l
# Should show 11 (one per service that uses Redis)

# 3. Check all localhost references (should be only in defaults/comments)
grep -n "localhost" services/workflow/app/config.py
# Should be ZERO lines

# 4. Verify Dockerfile changes
grep -c "poppler-utils" infra/docker/Dockerfile.ocr && echo "✓ System deps added"

# 5. Test YAML parsing
python3 -c "import yaml; yaml.safe_load(open('infra/docker/docker-compose.yml'))" && echo "✓ Valid YAML"
```

---

## Rollback (If Something Breaks)

```bash
# Restore from git
git checkout infra/docker/docker-compose.yml
git checkout services/workflow/app/config.py
git checkout infra/docker/Dockerfile.ocr

# Or restore from backup
cp infra/docker/docker-compose.yml.backup infra/docker/docker-compose.yml
```
