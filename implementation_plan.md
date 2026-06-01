# Production-Scale Architecture for ClaimGPT
## Goal: Support Lakhs of Concurrent Users with Celery + Redis

This plan upgrades the current dev setup (inline pipeline, single gateway, no scalability) to a production-ready architecture capable of handling 100,000+ concurrent users with Celery workers, Redis, horizontal scaling, and proper monitoring.

---

## Current State vs Target State

| Concern | Current (Dev) | Production Target |
|---|---|---|
| Pipeline execution | Inline thread in gateway | Celery workers (CPU + GPU queues) |
| Gateway replicas | 1 | N replicas behind Nginx |
| Workers | Defined but bypassed | Active, horizontally scalable |
| Redis | Locking only | Broker + Cache + Rate Limiter |
| Database | Single Postgres | Postgres + PgBouncer connection pool |
| File storage | Shared volume (local) | MinIO (S3-compatible, already in compose) |
| OMP deadlock | Fixed via inline mode | Fixed properly via `spawn` pool |
| Monitoring | Flower (basic) | Flower + Prometheus + Grafana |
| Load balancer | None | Nginx with upstream pool |

---

## Root Cause of the Celery Deadlock (Must Fix First)

The workers crash/deadlock because:
1. Celery defaults to `prefork` (fork-based) multiprocessing
2. OpenMP (used by PaddleOCR, scikit-learn, etc.) initializes thread pools before fork
3. After fork, thread state is invalid → **deadlock**

**Fix:** Use `--pool=solo` (single-threaded, no fork) for the GPU worker, or `--pool=gevent`/`--pool=threads` for CPU workers. Alternatively, use `PYTHONPATH` isolation and `multiprocessing.set_start_method('spawn')`.

---

## Proposed Changes

### Component 1: Celery Worker — Fix OMP Deadlock

#### [MODIFY] [celery_app.py](file:///C:/Project/ClaimGPT/libs/shared/celery_app.py)
- Set `OMP_NUM_THREADS=1` (already done ✅)
- Add `worker_pool = "solo"` for GPU worker config via task route
- Add `task_always_eager = False` to ensure tasks never run inline

#### [MODIFY] [docker-compose.yml](file:///C:/Project/ClaimGPT/infra/docker/docker-compose.yml)
Change worker commands:
```yaml
# worker_gpu — use solo pool (single process, no fork, safest for GPU/OpenMP)
command: celery -A libs.shared.celery_app worker -Q gpu_queue --pool=solo --concurrency=1 --loglevel=info --hostname=gpu@%h

# worker_cpu — use threads pool (avoids fork-based OMP issues, still concurrent)
command: celery -A libs.shared.celery_app worker -Q default --pool=threads --concurrency=8 --loglevel=info --hostname=cpu@%h
```

Also:
- Remove `CLAIMGPT_INLINE_PIPELINE: "true"` from gateway → set to `"false"` or `"auto"`
- Add `CELERY_WORKER_HIJACK_ROOT_LOGGER: "false"` to all workers
- Add `CELERY_TASK_ALWAYS_EAGER: "false"` to gateway

---

### Component 2: Nginx Load Balancer

#### [NEW] `infra/docker/nginx.conf`
Full upstream config for:
- Gateway: round-robin across replicas
- Rate limiting (10 req/s per IP burst 50)
- Request buffering for file uploads
- Gzip compression
- Health check endpoint passthrough

#### [MODIFY] [docker-compose.yml](file:///C:/Project/ClaimGPT/infra/docker/docker-compose.yml)
Add nginx service:
```yaml
nginx:
  image: nginx:1.27-alpine
  ports:
    - "80:80"
    - "443:443"
  volumes:
    - ./nginx.conf:/etc/nginx/nginx.conf:ro
  depends_on:
    - gateway
```

Change gateway ports from `"8000:8000"` to internal only (remove host port binding).

---

### Component 3: Redis — Full Production Config

#### [NEW] `infra/docker/redis.conf`
```
maxmemory 2gb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
appendonly yes
tcp-keepalive 60
```

#### [MODIFY] [docker-compose.yml](file:///C:/Project/ClaimGPT/infra/docker/docker-compose.yml)
```yaml
redis:
  image: redis:7-alpine
  command: redis-server /usr/local/etc/redis/redis.conf
  volumes:
    - ./redis.conf:/usr/local/etc/redis/redis.conf:ro
    - redisdata:/data
  deploy:
    resources:
      limits:
        cpus: '2'
        memory: 2G
```

Redis roles in production:
| DB index | Purpose |
|---|---|
| `redis://redis:6379/0` | Celery broker |
| `redis://redis:6379/1` | Celery result backend |
| `redis://redis:6379/2` | Application cache (coding RAG, etc.) |
| `redis://redis:6379/3` | Rate limiting counters |
| `redis://redis:6379/4` | Distributed locks (idempotency) |

---

### Component 4: PgBouncer — Database Connection Pooling

At 100K users, direct Postgres connections will be exhausted (~100 max by default).

#### [NEW] `infra/docker/pgbouncer.ini`
```ini
[databases]
claimgpt = host=postgres port=5432 dbname=claimgpt

[pgbouncer]
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 20
server_lifetime = 300
```

#### [MODIFY] [docker-compose.yml](file:///C:/Project/ClaimGPT/infra/docker/docker-compose.yml)
Add pgbouncer service. All services' `DATABASE_URL` point to `postgresql://claimgpt:claimgpt@pgbouncer:5432/claimgpt` instead of postgres directly.

---

### Component 5: Gateway Horizontal Scaling

#### [MODIFY] [docker-compose.yml](file:///C:/Project/ClaimGPT/infra/docker/docker-compose.yml)
```yaml
gateway:
  deploy:
    replicas: 3      # Scale based on load
    resources:
      limits:
        cpus: '2'
        memory: 4G
```

Remove `CLAIMGPT_INLINE_PIPELINE: "true"` → set `"false"` (use Celery).

---

### Component 6: Prometheus + Grafana Monitoring

#### [NEW] `infra/docker/prometheus.yml`
Scrape targets:
- `gateway:8000/metrics`
- `flower:5555/api/metrics` (Celery task stats)
- `redis-exporter:9121/metrics`
- `postgres-exporter:9187/metrics`

#### [MODIFY] [docker-compose.yml](file:///C:/Project/ClaimGPT/infra/docker/docker-compose.yml)
Add:
- `prometheus` service
- `grafana` service (port 3000)
- `redis-exporter` (oliver006/redis_exporter)
- `postgres-exporter` (prometheuscommunity/postgres-exporter)

---

### Component 7: Celery Rate Limiting & Priority Queues

#### [MODIFY] [celery_app.py](file:///C:/Project/ClaimGPT/libs/shared/celery_app.py)
Add:
- Task rate limits: `ocr_task` rate = `"10/m"` per worker (prevent GPU overload)
- Priority queues: `priority` (urgent claims), `default`, `gpu_queue`, `dead_letter`
- Result expiry: 24 hours (not keep results forever)

```python
celery_app.conf.update(
    result_expires=86400,        # 24h TTL on results
    task_compression='gzip',    # Compress large payloads
    worker_max_tasks_per_child=50,  # Recycle workers to prevent memory leaks
    worker_max_memory_per_child=2000000,  # Kill worker at 2GB RSS
)
```

---

### Component 8: Health Checks & Graceful Shutdown

#### [NEW] `infra/docker/healthcheck.sh`
Unified healthcheck script for all services.

#### [MODIFY] [docker-compose.yml](file:///C:/Project/ClaimGPT/infra/docker/docker-compose.yml)
Add proper healthchecks to all services:
- gateway: `GET /health`
- workers: `celery -A libs.shared.celery_app inspect ping`

---

## Implementation Order

1. **Fix Celery deadlock** — change pool mode in docker-compose.yml, disable inline mode
2. **Test Celery works** — upload a claim, verify tasks appear in Flower
3. **Add PgBouncer** — update DATABASE_URL in all services
4. **Add Redis production config** — persistence, memory limits, separate DB indices
5. **Add Nginx** — load balancer + rate limiting
6. **Add Prometheus + Grafana** — monitoring dashboards
7. **Add gateway replicas** — scale gateway to 3+

---

## Open Questions

> [!IMPORTANT]
> **Deployment target**: Is this for Docker Compose (single server) or Kubernetes (cloud)? 
> For lakhs of users, Kubernetes with HPA (auto-scaling) is strongly recommended over Docker Compose.

> [!IMPORTANT]
> **GPU availability**: The `worker_gpu` uses `--pool=solo --concurrency=1`. If you have multiple GPUs, do you want one worker per GPU? Please clarify GPU count.

> [!WARNING]
> **MinIO vs S3**: MinIO is already in the compose file but claim files are stored in a local shared volume. For production, all file I/O should go through MinIO. Do you want the ingress/OCR service updated to use MinIO?

> [!NOTE]
> **Keycloak auth**: Is Keycloak being used for auth in production, or is it just configured for dev? It should be production-hardened (start-dev → start, external DB, etc.).

---

## Verification Plan

### After Step 1 (Celery fix)
- Run `docker compose up -d`
- Upload a claim via UI
- Open Flower at `http://localhost:5555`
- Verify tasks appear: `ocr_task` → `parser_task` → `coding_task` → `risk_task` → `validator_task`
- Verify claim status reaches `COMPLETED`

### After Step 4 (PgBouncer)
- Run `docker compose exec pgbouncer psql -U claimgpt -h localhost pgbouncer -c "SHOW POOLS;"`
- Confirm connections are pooled

### After Step 5 (Nginx)
- Hit `http://localhost/` → proxied to gateway
- Run `ab -n 1000 -c 100 http://localhost/health` → check rate limiting kicks in

### After Step 6 (Monitoring)
- Open Grafana at `http://localhost:3000`
- Verify Celery task throughput, Redis memory, Postgres query time dashboards
