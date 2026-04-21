#!/bin/bash
set -e

# Start FastAPI app in background
uvicorn app.main:app --host 0.0.0.0 --port 8000 &

# Start Celery worker for gpu_queue
celery -A libs.shared.celery_app worker -Q gpu_queue --concurrency=1 --loglevel=info &

wait