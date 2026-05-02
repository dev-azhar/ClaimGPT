# IMPLEMENTATION GUIDE: Production-Ready ClaimGPT Infrastructure

**Timeline:** ~8 hours for Phase 1 + Phase 2 critical fixes  
**Risk Level:** Moderate (requires container rebuild and database connection testing)  
**Rollback:** Version control all changes; docker-compose down && docker-compose up with old version

---

## Phase 1: Critical Fixes (Do These First — 2-3 Hours)

These fixes are **BLOCKING** for production. Without them, inter-service communication WILL fail inside containers.

### Step 1: Fix docker-compose.yml Environment Variables

**File:** `infra/docker/docker-compose.yml`

**Apply these changes:**

```diff
# FIX 1: Add missing REDIS_URL to OCR service
  ocr:
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      OCR_DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
+     OCR_REDIS_URL: redis://redis:6379/0
+     REDIS_URL: redis://redis:6379/0
      OCR_ENABLE_PADDLE_OCR: ${OCR_ENABLE_PADDLE_OCR:-true}
```

**FIX 2: Add missing variables to PARSER service**
```diff
  parser:
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      PARSER_DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
+     PARSER_REDIS_URL: redis://redis:6379/0
+     REDIS_URL: redis://redis:6379/0
```

**FIX 3: Add missing REDIS_URL to all remaining services**
```diff
  coding:
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
+     REDIS_URL: redis://redis:6379/0

  predictor:
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
+     REDIS_URL: redis://redis:6379/0

  validator:
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
+     REDIS_URL: redis://redis:6379/0

  chat:
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
+     REDIS_URL: redis://redis:6379/0

  search:
    environment:
      DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
+     REDIS_URL: redis://redis:6379/0

  ingress:
    environment:
      INGRESS_DATABASE_URL: postgresql://claimgpt:claimgpt@postgres:5432/claimgpt
      INGRESS_STORAGE_ROOT: /app/services/ingress/storage/raw
+     INGRESS_REDIS_URL: redis://redis:6379/0
+     REDIS_URL: redis://redis:6379/0
```

**Verification command:**
```bash
# After applying changes, verify all services start without connection errors
docker-compose -f infra/docker/docker-compose.yml up -d
docker-compose logs postgres
docker-compose logs redis
docker-compose logs ocr | head -20  # Should show no connection refused errors
docker-compose logs parser | head -20
```

---

### Step 2: Fix Service Configuration Defaults

**File:** `services/workflow/app/config.py` (lines 10-18)

**Current (BROKEN):**
```python
database_url: str = "postgresql://claimgpt:claimgpt@localhost:5432/claimgpt"
ocr_url: str = "http://localhost:8000/ocr"
parser_url: str = "http://localhost:8000/parser"
# ...
```

**Fixed (CORRECT):**
```python
database_url: str = "postgresql://claimgpt:claimgpt@postgres:5432/claimgpt"
ocr_url: str = "http://ocr:8000"
parser_url: str = "http://parser:8000"
# ...
```

**Apply to all service config files:**

| File | Changes | Priority |
|------|---------|----------|
| `services/ocr/app/config.py:14-15` | localhost → redis, postgres | HIGH |
| `services/ingress/app/config.py:14-15` | localhost → redis, postgres | HIGH |
| `services/parser/app/config.py:14-15` | localhost → redis, postgres | HIGH |
| `services/predictor/app/config.py:13-14` | localhost → redis, postgres | HIGH |
| `services/coding/app/config.py:11` | localhost → postgres | HIGH |
| `services/validator/app/config.py:10` | localhost → postgres | HIGH |
| `services/search/app/config.py:7` | localhost → postgres | HIGH |
| `libs/shared/config.py:5-8` | localhost → postgres | HIGH |

**Testing:**
```bash
# Start containers
docker-compose -f infra/docker/docker-compose.yml up -d

# Check each service's logs for connection errors
docker-compose logs workflow | grep -i "error\|refused\|connect" || echo "✓ Workflow OK"
docker-compose logs ocr | grep -i "error\|refused\|connect" || echo "✓ OCR OK"
docker-compose logs parser | grep -i "error\|refused\|connect" || echo "✓ Parser OK"
```

---

### Step 3: Add GPU Support Configuration

**File:** `infra/docker/docker-compose.yml` (worker_gpu service)

**Current (NO GPU):**
```yaml
worker_gpu:
  command: celery -A libs.shared.celery_app worker -Q gpu_queue --concurrency=1
```

**Fixed (WITH GPU support):**
```yaml
worker_gpu:
  command: celery -A libs.shared.celery_app worker -Q gpu_queue --concurrency=2 --hostname=gpu@%h
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

**Prerequisites:**
1. NVIDIA GPU installed on host
2. NVIDIA Container Toolkit installed: https://github.com/NVIDIA/nvidia-container-toolkit
3. Docker daemon configured to use nvidia runtime

**Verification:**
```bash
# Check if NVIDIA runtime is available
docker run --rm --gpus all nvidia/cuda:12.0.0-runtime-ubuntu22.04 nvidia-smi

# If above works, test with worker_gpu
docker-compose -f infra/docker/docker-compose.yml up -d worker_gpu
docker-compose logs worker_gpu | grep -i "gpu\|device" || echo "Check GPU driver"
```

---

### Step 4: Increase GPU Queue Concurrency

**File:** `infra/docker/docker-compose.yml` (worker_gpu service)

**Current:**
```yaml
--concurrency=1
```

**Fixed (depends on GPU capability):**

For single GPU (compute capability 7.0+):
```yaml
--concurrency=2  # 2 concurrent OCR/Parser tasks
```

For multi-GPU or high-capacity GPU (compute capability 8.0+):
```yaml
--concurrency=4  # 4 concurrent tasks
```

**To determine GPU capability:**
```bash
nvidia-smi --query-gpu=compute_cap --format=csv,noheader
# Output: 8.0 = A100, H100 (can handle 4+)
#         7.5 = V100, T4 (can handle 2-3)
#         7.0 = RTX2080, P100 (can handle 2)
```

---

### Step 5: Add Resource Limits

**File:** `infra/docker/docker-compose.yml`

**Add to EVERY service** (example for worker_gpu, then repeat for all):

```yaml
worker_gpu:
  deploy:
    resources:
      requests:  # Minimum guaranteed resources
        cpus: '2'
        memory: 4G
      limits:    # Maximum allowed resources
        cpus: '4'
        memory: 8G
```

**Recommended limits by service:**

| Service | CPU Request | CPU Limit | Memory Request | Memory Limit | Notes |
|---------|-------------|-----------|----------------|--------------|-------|
| gateway | 1 | 2 | 512M | 1G | API router |
| worker_gpu | 2 | 4 | 4G | 8G | GPU-intensive |
| worker_cpu | 2 | 4 | 2G | 4G | CPU-intensive |
| flower | 0.5 | 1 | 256M | 512M | Monitoring |
| postgres | 1 | 2 | 512M | 1G | Database |
| redis | 0.5 | 1 | 256M | 512M | Cache/broker |
| ocr | 1 | 2 | 2G | 4G | OCR processing |
| parser | 1 | 2 | 1G | 2G | Parsing |
| coding | 0.5 | 1 | 512M | 1G | Medical NER |
| predictor | 0.5 | 1 | 512M | 1G | Risk scoring |
| validator | 0.5 | 1 | 256M | 512M | Rules validation |
| ingress | 0.5 | 1 | 256M | 512M | Upload handler |
| workflow | 0.5 | 1 | 256M | 512M | Orchestrator |
| submission | 0.5 | 1 | 256M | 512M | Report builder |
| chat | 0.5 | 1 | 256M | 512M | Chat service |
| search | 0.5 | 1 | 256M | 512M | Vector search |

**Application:**
```bash
# Use docker-compose.yml.fixed as reference
# It has complete resource limits for all services
cp infra/docker/docker-compose.yml infra/docker/docker-compose.yml.backup
# Apply limits manually or use .fixed as template
```

---

## Phase 2: High-Priority System Fixes (3-4 Hours)

### Step 6: Add Missing System Dependencies to OCR Dockerfile

**File:** `infra/docker/Dockerfile.ocr`

**Current (MISSING DEPS):**
```dockerfile
RUN apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libtesseract-dev \
    libgl1 \
    libglib2.0-0 \
    curl \
```

**Fixed (COMPLETE):**
```dockerfile
RUN apt-get install -y --no-install-recommends \
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
```

**Rebuild and test:**
```bash
# Rebuild OCR image with new dependencies
docker-compose -f infra/docker/docker-compose.yml build ocr

# Test OCR with PDF
docker-compose -f infra/docker/docker-compose.yml up -d ocr postgres
docker-compose exec ocr python -c "import pdfplumber; print('✓ pdfplumber OK')"
docker-compose exec ocr tesseract --version
docker-compose exec ocr python -c "from paddleocr import PaddleOCR; print('✓ PaddleOCR OK')"
```

---

### Step 7: Fix OCR Container Dual Responsibility (OPTIONAL but Recommended)

**Current problem:** OCR container runs both FastAPI and Celery worker.

**Solution:** Split into two services. This is more complex, so skip for now and come back in Phase 3 if needed.

**For now (quick fix):** Increase OCR container resource limits to account for dual responsibility:

```yaml
ocr:
  deploy:
    resources:
      requests:
        cpus: '2'
        memory: 4G
      limits:
        cpus: '4'
        memory: 8G
```

---

### Step 8: Enable MinIO Integration (OPTIONAL)

**Current:** MinIO runs but is unused.

**Quick fix:** Don't disable it; leave running as placeholder for future file storage migration.

**For later:** Create separate task in Phase 3 to implement MinIO integration.

---

## Phase 3: Production Operations (4+ Hours, Lower Priority)

These are recommended but not blocking. Do after Phase 1 & 2 are stable.

### Step 9: Database Backup Automation

**Add to Makefile:**

```makefile
backup:  ## Backup PostgreSQL database
	@mkdir -p backups
	@echo "🔄 Backing up database..."
	@$(COMPOSE) exec -T postgres pg_dump -U claimgpt claimgpt > backups/claimgpt-$(shell date +\%Y\%m\%d-\%H\%M\%S).sql
	@echo "✅ Backup saved to backups/"

restore:  ## Restore PostgreSQL database: make restore FILE=backups/claimgpt-*.sql
	@if [ -z "$(FILE)" ]; then echo "❌ Usage: make restore FILE=<backup_file>"; exit 1; fi
	@echo "⚠️  This will overwrite the current database!"
	@read -p "Type 'yes' to confirm: " CONFIRM; \
	if [ "$$CONFIRM" = "yes" ]; then \
		$(COMPOSE) exec -T postgres psql -U claimgpt claimgpt < $(FILE); \
		echo "✅ Database restored"; \
	else \
		echo "❌ Restore cancelled"; \
	fi
```

**Usage:**
```bash
make backup                    # Creates backups/claimgpt-20260501-143000.sql
make restore FILE=backups/claimgpt-20260501-143000.sql
```

---

### Step 10: Separate OCR Service (Advanced)

**Only do this if OCR bottleneck persists after increasing concurrency.**

Split OCR into two containers:

```yaml
# FastAPI server only
ocr:
  build:
    context: ../../
    dockerfile: infra/docker/Dockerfile.ocr
  command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
  # ... rest of config

# GPU worker only
ocr-worker:
  build:
    context: ../../
    dockerfile: infra/docker/Dockerfile.service
    args:
      SERVICE_NAME: workflow
  command: celery -A libs.shared.celery_app worker -Q gpu_queue --concurrency=2 --hostname=ocr@%h
  # ... resources and depends_on
```

---

## Testing Checklist

### Test 1: Container Startup (10 min)

```bash
# Start all services
docker-compose -f infra/docker/docker-compose.yml up -d

# Check all containers are running
docker-compose ps
# Expected: All services in "Up" state

# Check logs for errors
docker-compose logs | grep -i "error\|fail\|refused" || echo "✓ No errors"
```

### Test 2: Database Connectivity (5 min)

```bash
# Test from each service
docker-compose exec ocr psql -h postgres -U claimgpt -d claimgpt -c "SELECT 1" || echo "✗ OCR→DB failed"
docker-compose exec parser psql -h postgres -U claimgpt -d claimgpt -c "SELECT 1" || echo "✗ Parser→DB failed"
docker-compose exec workflow psql -h postgres -U claimgpt -d claimgpt -c "SELECT 1" || echo "✗ Workflow→DB failed"
```

### Test 3: Inter-Service Connectivity (5 min)

```bash
# Test from workflow to other services
docker-compose exec workflow curl http://ocr:8000/health
docker-compose exec workflow curl http://parser:8000/health
docker-compose exec workflow curl http://coding:8000/health

# Expected: HTTP 200 or service-specific response
```

### Test 4: Redis Connectivity (5 min)

```bash
# Test from each service that uses Redis
docker-compose exec ocr redis-cli -h redis ping  # Should reply "PONG"
docker-compose exec parser redis-cli -h redis ping
docker-compose exec ingress redis-cli -h redis ping
```

### Test 5: Celery Task Submission (10 min)

```bash
# Check if Celery queues are working
docker-compose exec worker_gpu celery -A libs.shared.celery_app inspect active
docker-compose exec worker_cpu celery -A libs.shared.celery_app inspect active

# Monitor Flower (Celery monitoring UI)
# Open browser: http://localhost:5555
# Should show worker_gpu and worker_cpu as active
```

### Test 6: Upload and Process Document (15 min)

```bash
# Test complete workflow with a sample PDF
curl -X POST http://localhost:8001/api/upload \
  -F "file=@sample.pdf" \
  -F "claim_id=test-123"

# Monitor processing
docker-compose logs -f workflow
docker-compose logs -f ocr
docker-compose logs -f parser

# Check result in Flower UI: http://localhost:5555
```

---

## Rollback Plan

If anything breaks:

```bash
# Stop all services
docker-compose down

# Restore previous docker-compose.yml
git checkout infra/docker/docker-compose.yml

# Restore service configs
git checkout services/*/app/config.py
git checkout libs/shared/config.py

# Start with old configuration
docker-compose up -d

# Verify
docker-compose logs | head -50
```

---

## Summary of Changes

| Phase | File | Changes | Effort | Impact |
|-------|------|---------|--------|--------|
| 1 | docker-compose.yml | Add REDIS_URL to all services | 30min | HIGH (fixes inter-service comms) |
| 1 | service configs (6 files) | Replace localhost with container DNS | 30min | HIGH (fixes service URLs) |
| 1 | docker-compose.yml (worker_gpu) | Add GPU support, increase concurrency | 30min | HIGH (enables GPU) |
| 1 | docker-compose.yml (all services) | Add resource limits | 30min | HIGH (prevents runaway processes) |
| 2 | Dockerfile.ocr | Add missing system dependencies | 15min | MEDIUM (prevents fallback failures) |
| 2 | docker-compose.yml (ocr) | Increase resource limits | 10min | MEDIUM (for dual responsibility) |
| 3 | Makefile | Add backup/restore commands | 20min | MEDIUM (backup strategy) |
| 3 | docker-compose.yml | Add ocr-worker service | 1hr | OPTIONAL (only if bottleneck persists) |

**Total effort Phase 1+2:** ~3 hours  
**Total effort Phase 3:** ~2 hours (optional)  
**Total effort all phases:** ~5 hours

---

## Production Deployment Checklist

- [ ] Phase 1 fixes applied and tested
- [ ] GPU support confirmed working (if hardware available)
- [ ] All services can communicate internally
- [ ] Database backups automated
- [ ] Resource limits set for all services
- [ ] OCR Dockerfile system dependencies installed
- [ ] CI/CD pipeline produces working Docker images
- [ ] Load test passed (10+ concurrent uploads)
- [ ] Monitoring configured (Flower at minimum)
- [ ] Documentation updated
- [ ] Team trained on new infrastructure
