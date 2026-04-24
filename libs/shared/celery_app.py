import sys
import os
# Ensure the project root is in sys.path regardless of how the worker is started
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)


import os

from celery import Celery
from kombu import Exchange, Queue

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
backend_url = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

celery_app = Celery(
    "claim_app",
    broker=broker_url,
    backend=backend_url,
)

default_exchange = Exchange("default", type="direct", durable=True)
gpu_exchange = Exchange("gpu_queue", type="direct", durable=True)
dead_letter_exchange = Exchange("dead_letter", type="direct", durable=True)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_persistent=True,
    imports=("services.shared_tasks",),
    task_routes={
        "services.shared_tasks.ocr_task": {"queue": "gpu_queue"},
        "services.shared_tasks.parser_task": {"queue": "gpu_queue"},
        "services.shared_tasks.coding_task": {"queue": "default"},
        "services.shared_tasks.risk_task": {"queue": "default"},
        "services.shared_tasks.validator_task": {"queue": "default"},
        "services.shared_tasks.finalize_claim_task": {"queue": "default"},
        # Add any new tasks here and assign to the correct queue
    },
    task_queues=(
        Queue(
            "default",
            default_exchange,
            routing_key="default",
            queue_arguments={
                "x-dead-letter-exchange": "dead_letter",
                "x-dead-letter-routing-key": "dead_letter",
            },
            durable=True,
        ),
        Queue(
            "gpu_queue",
            gpu_exchange,
            routing_key="gpu_queue",
            queue_arguments={
                "x-dead-letter-exchange": "dead_letter",
                "x-dead-letter-routing-key": "dead_letter",
            },
            durable=True,
        ),
        Queue(
            "dead_letter",
            dead_letter_exchange,
            routing_key="dead_letter",
            durable=True,
        ),
    ),
    task_default_queue="default",
    task_default_exchange="default",
    task_default_routing_key="default",
    task_create_missing_queues=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_publish_retry=True,
)

celery_app.autodiscover_tasks(["services"])

# Alias for celery -A libs.shared.celery_app worker ...
app = celery_app
claim_app = celery_app
