# ClaimGPT Concurrency Optimization Guide

## Overview

This guide explains the optimizations made to handle 30+ concurrent claim uploads without FastAPI getting stuck. The changes focus on database connection pooling and Celery worker configuration.

## Changes Made

### 1. Database Connection Pool Optimization

**Files Updated:**
- `libs/shared/db_config.py` (new)
- All service `*/app/db.py` files

**Changes:**
- Increased connection pool size from 5 to 20
- Increased max_overflow from 10 to 40
- This allows up to 60 concurrent connections per service

**Why This Matters:**
- Each concurrent task needs a DB connection
- With 30+ concurrent claims, each spawning 6 tasks (OCR, Parser, Coding, Risk, Validator, Finalize), you need many connections
- Insufficient pool causes connection starvation and task queueing

### 2. Added asyncpg Driver

**File Updated:**
- `requirements.txt`

**New Dependencies:**
- `asyncpg==0.30.0` - Async PostgreSQL driver (faster than psycopg2)
- `greenlet==3.0.3` - Required for SQLAlchemy async support

**Note:** We're keeping `psycopg2-binary` as well since existing code uses it synchronously.

### 3. Async DB Session Support

**File Created:**
- `libs/shared/async_db.py`

**Provides:**
- Async engine creation with asyncpg
- Async session context managers
- Ready for future async task upgrades

## Running Workers for 30+ Concurrent Claims

### Recommended Worker Configuration

```bash
# Default CPU tasks queue (parser, coding, risk, validator, finalize)
python -m celery -A libs.shared.celery_app worker \
  --loglevel=info \
  -Q default \
  --pool=threads \
  --concurrency=8 \
  --time-limit=1200 \
  --soft-time-limit=1000 \
  --hostname=cpu@%h

# OCR tasks (GPU queue - separate as needed)
python -m celery -A libs.shared.celery_app worker \
  --loglevel=info \
  -Q gpu_queue \
  --pool=threads \
  --concurrency=2 \
  --time-limit=1200 \
  --soft-time-limit=900 \
  --hostname=ocr@%h
```

### Configuration Explanation

| Parameter | Value | Reason |
|-----------|-------|--------|
| `--pool=threads` | threads | Allow concurrent task execution |
| `--concurrency` | 8 (CPU), 2 (OCR) | Scale based on available CPU cores and resources |
| `--time-limit` | 1200s (20min) | Hard limit to prevent zombie tasks |
| `--soft-time-limit` | 1000s (16m40s) | Soft limit for graceful shutdown |

### Scaling Guidelines

- **Small deployment (10-20 concurrent):** 4 CPU workers, 1 OCR worker
- **Medium deployment (30-50 concurrent):** 8 CPU workers, 2-3 OCR workers
- **Large deployment (50+):** 12+ CPU workers, 4+ OCR workers

## Database Configuration for PostgreSQL

### Recommended PostgreSQL Settings

Ensure your PostgreSQL server can handle connection pool sizes:

```sql
-- Increase max connections (default is 100)
ALTER SYSTEM SET max_connections = 500;

-- Increase connection limit for the database
ALTER DATABASE claimgpt CONNECTION LIMIT 400;

-- Reload configuration
SELECT pg_reload_conf();
```

### Connection Pool Math

- 11 services × 60 connections (pool + overflow) = 660 max connections needed
- Add safety margin: recommend 400-500 available for application
- Set PostgreSQL `max_connections` to 600+

## Monitoring & Debugging

### Check Worker Health

```bash
# List active workers
celery -A libs.shared.celery_app inspect active

# Check worker stats
celery -A libs.shared.celery_app inspect stats

# View registered tasks
celery -A libs.shared.celery_app inspect registered
```

### Check DB Connection Usage

```sql
-- View active connections
SELECT datname, count(*) FROM pg_stat_activity GROUP BY datname;

-- View connection details
SELECT usename, application_name, state, query_start, query 
FROM pg_stat_activity 
WHERE datname = 'claimgpt';
```

### Check FastAPI/Ingress Health

```bash
curl http://localhost:8000/health
curl http://localhost:8000/claims  # Returns claim list

# Monitor logs for connection issues
# If you see "QueuePool timeout", increase pool_size in db_config
```

## Performance Tips

### 1. Database Indexing

Ensure these tables have proper indexes:

```sql
-- Verify these indexes exist:
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);
CREATE INDEX IF NOT EXISTS idx_claims_created_at ON claims(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_claim_id ON documents(claim_id);
CREATE INDEX IF NOT EXISTS idx_ocr_job_claim_id ON ocr_jobs(claim_id);
CREATE INDEX IF NOT EXISTS idx_parse_job_claim_id ON parse_jobs(claim_id);
CREATE INDEX IF NOT EXISTS idx_workflow_state_claim_id ON workflow_state(claim_id);
```

### 2. Redis Configuration

Ensure Redis is also scaled appropriately:

```bash
# Check Redis memory usage
redis-cli INFO memory

# Increase maxmemory if needed
redis-cli CONFIG SET maxmemory 1gb
redis-cli CONFIG REWRITE
```

### 3. FastAPI Settings

Ensure FastAPI gateway has good settings:

```python
# In main.py, the connection pool in lifespan is already optimized:
_pool = AsyncConnectionPool(
    conninfo=s.database_url,
    max_size=20,  # Already set
)
```

## Troubleshooting

### Symptom: "FastAPI Gets Stuck"

**Causes & Solutions:**

1. **Database connection pool exhausted**
   - Solution: Increase `pool_size` in db_config (already done to 20)
   - Solution: Increase PostgreSQL `max_connections`

2. **Too few Celery workers**
   - Solution: Increase `--concurrency` or add more worker instances

3. **Slow database queries**
   - Solution: Add indexes (see above)
   - Solution: Monitor slow query log and optimize queries

4. **Memory pressure**
   - Solution: Monitor worker memory usage
   - Solution: Reduce `--concurrency` if memory is limited

### Symptom: "QueuePool timeout waiting for connection"

This means the connection pool is exhausted:

```python
# Increase in db_config.py:
pool_size=30  # Increase further if needed
max_overflow=60
```

Then restart all services.

## Future Improvements

1. **Convert tasks to gevent pool** for better async/await support
2. **Implement connection pooling at application level** for shared pool
3. **Add metrics collection** for monitoring connection pool usage
4. **Implement async versions of task functions** for I/O-bound operations

## Verification Steps

1. Update requirements:
```bash
pip install -r requirements.txt
```

2. Restart all services:
```bash
# Restart FastAPI gateway
pkill -f "uvicorn main:app"
# Wait for processes to terminate
sleep 2
# Restart services
```

3. Test with 30 concurrent uploads:
```bash
python tmp/bulk_upload_claims.py --input-dir <path> --concurrency 30
```

4. Monitor logs and database connections:
```bash
# In separate terminals:
tail -f logs/claim_uploads.txt
redis-cli MONITOR
psql -U claimgpt -d claimgpt -c "SELECT count(*) FROM pg_stat_activity;"
```

## Support

For issues:
1. Check worker logs: `celery -A libs.shared.celery_app worker --loglevel=debug`
2. Check database logs: `SELECT * FROM pg_log;`
3. Check Redis logs: `redis-cli`
4. Verify configuration: `python -c "from libs.shared.db_config import create_optimized_engine; print('OK')"`
