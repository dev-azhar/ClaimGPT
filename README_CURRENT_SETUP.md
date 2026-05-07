# ClaimGPT Current Setup Guide

This guide covers the commands teammates should run after pulling the latest `main` branch.

---

## 1. Pull the Latest Code

```powershell
git checkout main
git pull origin main
```

---

## 2. Create or Refresh the Python 3.11 Virtual Environment

Use Python 3.11 for the backend and workers.

```powershell
deactivate
rmdir /s /q .venv
py -3.11 -m venv .venv
& .\.venv\Scripts\Activate.ps1
```

If `py -3.11` is not available, install Python 3.11 first and make sure it is on PATH.

---

## 3. Install Python Dependencies

```powershell
pip install -r requirements.txt
```

If Paddle OCR packages are missing:

```powershell
pip install paddlepaddle paddleocr
```

---

## 4. Start Infrastructure

Start Postgres, Redis, and MinIO:

```powershell
make dev
```

If your team uses Docker Compose directly instead of `make dev`, this is the equivalent command:

```powershell
docker compose -f infra/docker/docker-compose.yml up -d postgres redis minio
```

---

## 5. Apply Database Migrations

Run the migration after pulling any change that touches the schema or workflow-state logic:

```powershell
& .\.venv\Scripts\python.exe -m alembic upgrade head
```

If a teammate is on a fresh database and the schema file is required in your environment, they can also apply:

```powershell
psql -U claimgpt -d claimgpt -h localhost -f infra/db/claimgpt_schema.sql
```

---

## 6. Start Backend Services

Set the Python path first for Celery:

```powershell
$env:PYTHONPATH = "."
```

Start the workers in separate terminals:

```powershell
celery -A libs.shared.celery_app worker --loglevel=info -Q default --pool=threads --concurrency=4 --hostname=cpu@%h
```

```powershell
celery -A libs.shared.celery_app worker --loglevel=info -Q gpu_queue --pool=threads --concurrency=1 --hostname=gpu@%h
```

Start the backend API:

```powershell
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

If a teammate runs the services individually instead of the unified gateway, the equivalent API commands are:

```powershell
uvicorn services.ingress.app.main:app --reload --port 8000
uvicorn services.ocr.app.main:app --reload --port 8002
uvicorn services.parser.app.main:app --reload --port 8003
uvicorn services.coding.app.main:app --reload --port 8004
uvicorn services.predictor.app.main:app --reload --port 8005
uvicorn services.validator.app.main:app --reload --port 8006
uvicorn services.workflow.app.main:app --reload --port 8007
```

---

## Performance testing / Batch upload (QA guide)

Follow these steps to run repeatable performance tests and batch uploads. Keep the same virtualenv and repositories open in each terminal.

1) Activate the project venv in every terminal you will use and set `PYTHONPATH`:

```powershell
& .\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "."
```

2) Install dependencies (includes PaddleOCR). If Paddle installs fail on Windows, follow the Paddle official Windows instructions for the correct wheel.

```powershell
pip install -r requirements.txt
# if Paddle related packages are missing or fail, try:
# pip install paddlepaddle paddleocr
```

3) Start infrastructure (Postgres, Redis, MinIO) and Flower (monitoring) before ingesting batches:

```powershell
make dev
# Start Flower in a separate terminal (opens web UI at port 5555)
celery -A libs.shared.celery_app flower --port=5555
```

4) Start the backend API (in its own terminal):

```powershell
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

5) Start initial Celery workers (open each in a separate terminal). Start one `default` worker and one `gpu_queue` worker first:

```powershell
# default worker (parsing, coding, etc.)
celery -A libs.shared.celery_app worker --loglevel=info -Q default --pool=threads --concurrency=4 --hostname=cpu@%h

# OCR worker (listening on gpu_queue). On machines without NVIDIA GPUs this still runs on CPU.
celery -A libs.shared.celery_app worker --loglevel=info -Q gpu_queue --pool=threads --concurrency=1 --hostname=gpu@%h
```

6) Run a small pilot upload first (one folder with a few images) to collect baseline numbers. Example uploader command:

```powershell
python tmp/bulk_upload_claims.py --api http://localhost:8000 --input-dir "C:\Users\Admin\Downloads\Imageclaims\one_folder" --concurrency 2
```

7) Scale test plan (recommended order):
- Baseline: 1 worker (OCR) + concurrency 2, small folder (3 images).
- Scale workers: start 2–4 OCR workers (each as a separate process, `--concurrency=1`) and re-run the same small folder to measure speedup.
- Client sweep: keep workers constant and vary uploader `--concurrency` (2, 4, 8) to find saturation point.
- Full batch: run the real batch (for example your 20 folders × 3 images) and record total time.

Example to start multiple OCR workers (open one terminal per command):

```powershell
celery -A libs.shared.celery_app worker --loglevel=info -Q gpu_queue --pool=threads --concurrency=1 --hostname=gpu1@%h
celery -A libs.shared.celery_app worker --loglevel=info -Q gpu_queue --pool=threads --concurrency=1 --hostname=gpu2@%h
celery -A libs.shared.celery_app worker --loglevel=info -Q gpu_queue --pool=threads --concurrency=1 --hostname=gpu3@%h
```

8) What to measure and where to look:
- Use Flower (http://localhost:5555) to see per-task timings and host column (which worker processed each task).
- Look at the `finalize_claim` task output for `total_processing_seconds` and `results` (the uploader reports this on completion).
- Record per-claim median and 95th percentile latencies across runs.

9) Quick tips to reduce latency on CPU-only machines:
- Reduce client concurrency when running locally (e.g., `--concurrency 2`), then increase worker count instead of one worker handling many threads.
- If you control the code: consider lowering PDF render DPI (e.g., 150) and disable heavy preprocessing for speed runs (we can add config flags for these).

If the team needs help running these steps, pick an option and I will provide exact command sequences or a small benchmark script to collect metrics automatically.

## 7. Start the Frontend

```powershell
cd ui/web
npm install
npm run dev
```

---

## 8. Access the App

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs
- Flower: http://localhost:5555

---

## 9. Common Post-Pull Checklist

- Recreate the venv if Python version changed.
- Run `pip install -r requirements.txt` again if dependencies changed.
- Run `& .\.venv\Scripts\python.exe -m alembic upgrade head` after schema changes.
- Run `npm install` in `ui/web` if frontend packages changed.
- Set `PYTHONPATH` before starting Celery workers on Windows.
