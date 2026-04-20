
import os
from celery import Celery

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
backend_url = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

celery_app = Celery(
    "claim_app",
    broker=broker_url,
    backend=backend_url,
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_persistent=True,
    imports=("services.shared_tasks",),
    task_routes={
        "services.shared_tasks.ocr_task": {"queue": "gpu_queue"},
        "services.shared_tasks.parser_task": {"queue": "gpu_queue"},
        "services.shared_tasks.coding_task": {"queue": "gpu_queue"},
        "services.shared_tasks.risk_task": {"queue": "default"},
        "services.shared_tasks.validator_task": {"queue": "default"},
        # Add any new tasks here and assign to the correct queue
    },
    task_create_missing_queues=True,
)

celery_app.autodiscover_tasks(["services"])

# Alias for celery -A libs.shared.celery_app worker ...
app = celery_app
claim_app = celery_app
