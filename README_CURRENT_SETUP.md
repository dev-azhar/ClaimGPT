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
