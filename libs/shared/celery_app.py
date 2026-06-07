import sys
import os
import multiprocessing

# Force 'spawn' start method for Celery prefork workers to prevent OpenMP/PaddleOCR deadlocks
try:
    if multiprocessing.get_start_method(allow_none=True) != 'spawn':
        multiprocessing.set_start_method('spawn', force=True)
except (RuntimeError, ValueError):
    pass

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

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(root_dir, ".env"))
except ImportError:
    pass

from celery import Celery
from kombu import Exchange, Queue

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
backend_url = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

broker_transport_options = {}
result_backend_transport_options = {}

if broker_url and broker_url.startswith("sentinel://"):
    sentinels = []
    master_name = os.getenv("CELERY_SENTINEL_MASTER_NAME", "mymaster")
    # Parse sentinel URL format: sentinel://host1:port1;host2:port2/db
    url_without_scheme = broker_url[len("sentinel://"):]
    if "/" in url_without_scheme:
        hosts_part, _ = url_without_scheme.split("/", 1)
    else:
        hosts_part = url_without_scheme
        
    for host_port in hosts_part.split(";"):
        if ":" in host_port:
            host, port = host_port.split(":")
            sentinels.append((host, int(port)))
        else:
            sentinels.append((host_port, 26379))
            
    broker_transport_options = {
        'master_name': master_name,
        'sentinels': sentinels
    }
    result_backend_transport_options = {
        'master_name': master_name,
        'sentinels': sentinels
    }

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
    broker_transport_options=broker_transport_options,
    result_backend_transport_options=result_backend_transport_options,
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
    worker_max_tasks_per_child=50,
    worker_max_memory_per_child=2000000, # 2GB limit per process (in KB)
    worker_proc_alive_timeout=120.0,
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
# Pre-warm OCR engines when parent worker imports the module (before fork)
import sys
import os

def run_prewarm():
    args_str = " ".join(sys.argv)
    
    # Detect worker role from command line queues
    is_ocr = "ocr_queue" in args_str
    is_parser = "parser_queue" in args_str
    is_coding = "default" in args_str or not any(q in args_str for q in ["ocr_queue", "parser_queue"])

    print(f"[CELERY PREWARM] Loading models in parent process (pre-fork). Role: OCR={is_ocr}, Parser={is_parser}, Coding={is_coding}")

    if is_ocr and os.environ.get("DISABLE_OCR_PREWARM") != "1":
        try:
            from services.ocr.app.engine import prewarm_ocr_engines
            prewarm_ocr_engines()
            print("[CELERY PREWARM] Parent successfully pre-warmed OCR engines")
        except Exception as e:
            print(f"[CELERY PREWARM] Warning: Parent failed to prewarm OCR engines: {e}")

    if is_coding and os.environ.get("DISABLE_CODING_PREWARM") != "1":
        try:
            from services.coding.app.icd10_rag import preload_rag_models
            preload_rag_models()
            print("[CELERY PREWARM] Parent successfully pre-warmed RAG coding models")
        except Exception as e:
            print(f"[CELERY PREWARM] Warning: Parent failed to prewarm RAG coding models: {e}")

    if is_parser and os.environ.get("DISABLE_PARSER_PREWARM") != "1":
        try:
            from services.parser.app.layout_analyzer import init_pp_structure
            init_pp_structure()
            print("[CELERY PREWARM] Parent successfully pre-warmed Parser layout models")
        except Exception as e:
            print(f"[CELERY PREWARM] Warning: Parent failed to prewarm Parser layout models: {e}")

# Run in the main parent worker process at import time before forks occur
if any("celery" in arg for arg in sys.argv) and "worker" in sys.argv:
    run_prewarm()

# Alias for celery -A libs.shared.celery_app worker ...
app = celery_app
claim_app = celery_app

# Start a lightweight background thread for container liveness/health checking
def _start_celery_heartbeat_thread():
    if os.environ.get("CELERY_WORKER") == "true":
        import threading
        import time
        
        # Avoid starting multiple threads
        if hasattr(_start_celery_heartbeat_thread, "_started"):
            return
        _start_celery_heartbeat_thread._started = True
        
        def _celery_heartbeat_loop():
            path = "/tmp/celery_worker_heartbeat"
            # Fast update at start
            try:
                with open(path, "w") as f:
                    f.write(str(time.time()))
            except Exception:
                pass
            while True:
                time.sleep(10)
                try:
                    with open(path, "w") as f:
                        f.write(str(time.time()))
                except Exception:
                    pass
                    
        t = threading.Thread(target=_celery_heartbeat_loop, daemon=True)
        t.start()

# Start on import (for single-process/eager modes)
_start_celery_heartbeat_thread()

# Also register on worker_ready and worker_process_init to ensure it runs inside Celery worker processes
@signals.worker_ready.connect
@signals.worker_process_init.connect
def _on_worker_ready_start_heartbeat(sender=None, **kwargs):
    _start_celery_heartbeat_thread()


