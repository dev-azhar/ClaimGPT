from celery import Celery

claim_app = Celery(
    "claim_app",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
)

claim_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_persistent=True,
    imports=("services.shared_tasks",),
)

claim_app.autodiscover_tasks(["services"])

# Alias for celery -A libs.shared.celery_app worker ...
app = claim_app
