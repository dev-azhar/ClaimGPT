# ClaimGPT Setup Guide (ocr_parser_update branch)

This guide will help you set up and run the ClaimGPT application on your local system using the ocr_parser_update branch.

---

## 1. Pull the Latest Code

```
git checkout ocr_parser_update
git pull origin ocr_parser_update
```

---

## 2. Create and Activate Virtual Environment

```
# Create venv (if not present)
python -m venv .venv

# Activate venv (Windows)
.\.venv\Scripts\activate
# (On Mac/Linux: source .venv/bin/activate)
```

---

## 3. Install Python Dependencies

```
pip install -r requirements.txt
```

---

## 4. Start Infrastructure (Postgres, Redis, MinIO)

```
docker compose -f infra/docker/docker-compose.yml up -d postgres redis minio
```

---

## 5. Apply Database Schema

If this is your first time or if the schema has changed:

```
psql -U claimgpt -d claimgpt -h localhost -f infra/db/claimgpt_schema.sql
```
- (Adjust username, db name, and host if needed.)
- If you use a GUI (like DBeaver), you can run the SQL file there.

---

## 6. Start Backend Services

Open a new terminal for each service:

### Celery Workers (Queue Separation)

- **GPU Worker (OCR, Parser, Coding):**
  ```
  celery -A libs.shared.celery_app worker --loglevel=info -Q gpu_queue --pool=threads --concurrency=1 --hostname=gpu@%h
  ```
- **CPU Worker (Risk, Validator):**
  ```
  celery -A libs.shared.celery_app worker --loglevel=info -Q default --pool=threads --concurrency=4 --hostname=cpu@%h
  ```

### API Services (examples)
  ```
  uvicorn main:app --reload --host 0.0.0.0 --port 8000
  uvicorn services.ingress.app.main:app --reload --port 8000
  uvicorn services.ocr.app.main:app --reload --port 8002
  uvicorn services.parser.app.main:app --reload --port 8003
  uvicorn services.coding.app.main:app --reload --port 8004
  uvicorn services.predictor.app.main:app --reload --port 8005
  uvicorn services.validator.app.main:app --reload --port 8006
  uvicorn services.workflow.app.main:app --reload --port 8007
  ```

### Flower (Celery Monitoring)
  ```
  celery -A libs.shared.celery_app flower --port=5555
  # Open http://localhost:5555 to monitor workers and tasks
  ```

---

## 7. Start Frontend (if needed)

```
cd ui/web
npm install
npm run dev
```

---

## 8. Access the Application

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs (and other ports as above)
- Flower dashboard: http://localhost:5555

---

## 9. Troubleshooting
- If you see database errors, make sure you applied the schema (step 5).
- If a port is in use, change the port number in the command.
- For any missing dependencies, re-run `pip install -r requirements.txt` or `npm install`.

---

## 10. Deactivate Virtual Environment (when done)

```
deactivate
```

---

**For any issues, check the logs in your terminal or ask the team for help!**
