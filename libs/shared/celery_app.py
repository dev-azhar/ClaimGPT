import sys
import os

# Force unbuffered output for real-time logging in Celery workers
os.environ['PYTHONUNBUFFERED'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['VECLIB_MAXIMUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

# Ensure the project root is in sys.path regardless of how the worker is started
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

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
ocr_exchange = Exchange("ocr_queue", type="direct", durable=True)
parser_exchange = Exchange("parser_queue", type="direct", durable=True)
dead_letter_exchange = Exchange("dead_letter", type="direct", durable=True)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_persistent=True,
    worker_send_task_events=True,
    imports=("services.shared_tasks",),
    task_routes={
        "services.shared_tasks.ocr_task": {"queue": "ocr_queue"},
        "services.shared_tasks.parser_task": {"queue": "parser_queue"},
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
            "ocr_queue",
            ocr_exchange,
            routing_key="ocr_queue",
            queue_arguments={
                "x-dead-letter-exchange": "dead_letter",
                "x-dead-letter-routing-key": "dead_letter",
            },
            durable=True,
        ),
        Queue(
            "parser_queue",
            parser_exchange,
            routing_key="parser_queue",
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
    worker_prefetch_multiplier=1,
    task_create_missing_queues=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_publish_retry=True,
)

celery_app.autodiscover_tasks(["services"])

# ================================================================== logging level hooks
from celery import signals

@signals.after_setup_logger.connect
@signals.after_setup_task_logger.connect
def setup_custom_logging_levels(logger, *args, **kwargs):
    import logging
    # Set logging level for all custom loggers to propagate INFO logs properly
    loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
    for l in loggers:
        if l.name.startswith(("parser", "ocr", "coding")):
            l.setLevel(logging.INFO)
            l.propagate = True
    # Also explicitly define the main ones in case they aren't loaded in manager yet
    for name in ["parser-debug", "parser.engine", "parser.vlm", "parser.layout_analyzer", 
                 "coding.rag", "coding.engine", 
                 "ocr", "ocr.engine", "ocr.docling", "ocr.scan_analyzer", "ocr.doc_validator"]:
        l = logging.getLogger(name)
        l.setLevel(logging.INFO)
        l.propagate = True

# ================================================================== worker startup hooks
# Pre-warm OCR engines when worker process initializes
from celery import signals

@signals.worker_process_init.connect
@signals.worker_ready.connect
def prewarm_worker_engines(sender=None, **kwargs):
    """Called when Celery worker process initializes or worker is ready.
    Selectively pre-warms only the engines required by this worker's queue
    to minimize RAM bloat and speed up startup time.
    """
    import sys
    args_str = " ".join(sys.argv)
    
    # Detect worker role from command line queues
    is_ocr = "ocr_queue" in args_str
    is_parser = "parser_queue" in args_str
    # Only pre-warm coding if 'default' queue or no specific queue is declared (meaning it targets default tasks)
    is_coding = "default" in args_str or not any(q in args_str for q in ["ocr_queue", "parser_queue"])

    print(f"[CELERY SIGNAL] Worker startup. Role: OCR={is_ocr}, Parser={is_parser}, Coding={is_coding}")
    print("[CELERY SIGNAL] Selectively pre-warming engines based on worker role...")

    if is_ocr:
        try:
            from services.ocr.app.engine import prewarm_ocr_engines
            prewarm_ocr_engines()
            print("[CELERY SIGNAL] Successfully pre-warmed OCR engines")
        except Exception as e:
            print(f"[CELERY SIGNAL] Warning: Failed to prewarm OCR engines: {e}")
            import traceback
            traceback.print_exc()

    if is_coding:
        try:
            print("[CELERY SIGNAL] Attempting to pre-warm RAG coding models...")
            from services.coding.app.icd10_rag import preload_rag_models
            preload_rag_models()
            print("[CELERY SIGNAL] Successfully pre-warmed RAG coding models")
        except ImportError as e:
            print(f"[CELERY SIGNAL] RAG coding prewarm skipped (dependencies like '{e.name}' not installed)")
        except Exception as e:
            print(f"[CELERY SIGNAL] Warning: Failed to prewarm RAG coding models: {e}")
            import traceback
            traceback.print_exc()

    if is_parser:
        try:
            print("[CELERY SIGNAL] Attempting to pre-warm Parser layout models...")
            from services.parser.app.layout_analyzer import init_pp_structure
            init_pp_structure()
            print("[CELERY SIGNAL] Successfully pre-warmed Parser layout models")
        except ImportError as e:
            print(f"[CELERY SIGNAL] Parser layout prewarm skipped (dependencies like '{e.name}' not installed)")
        except Exception as e:
            print(f"[CELERY SIGNAL] Warning: Failed to prewarm Parser layout models: {e}")
            import traceback
            traceback.print_exc()

# Alias for celery -A libs.shared.celery_app worker ...
app = celery_app
claim_app = celery_app
