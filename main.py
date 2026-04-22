"""
ClaimGPT — API Gateway / Root Entrypoint

Includes all 10 microservice routers under a single FastAPI app so
every endpoint appears in one unified OpenAPI / Swagger UI at /docs.
Each service is also runnable standalone via uvicorn.
"""

import os
import sys
import importlib
import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager 


# ── Ensure service packages are importable ──
ROOT = Path(__file__).resolve().parent
for svc_dir in sorted((ROOT / "services").iterdir()):
    if svc_dir.is_dir() and (svc_dir / "app").is_dir():
        sys.path.insert(0, str(svc_dir))

# Global reference 
graph = None
@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.chat.app.workflow.graph import create_workflow_graph
    from langfuse.langchain import CallbackHandler
    from langgraph.checkpoint.postgres.aio import  AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool
    from services.chat.app.config import load_langfuse_env, settings as s
    load_langfuse_env()
    global graph

     # Pool must stay open for entire app lifetime
    async with AsyncConnectionPool(
        conninfo=s.database_url,
        max_size=20,
        kwargs={"autocommit": True},
    ) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()  # creates tables once, idempotent

        graph_builder = create_workflow_graph()
        graph = graph_builder.compile(checkpointer=checkpointer)

        app.state.ClaimAgent = graph
        app.state.langfuse_handler = CallbackHandler()

        yield  # app runs here, pool stays alive
    # pool closes here on shutdown

app = FastAPI(
    title="ClaimGPT",
    description="AI-powered medical claims processing platform",
    lifespan=lifespan,
    version="0.1.0",
)

logger = logging.getLogger("gateway")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Frontend polls this endpoint frequently; keep logs readable.
    quiet_poll = (
        request.method == "GET"
        and (
            request.url.path == "/ingress/claims"
            or request.url.path.startswith("/ocr/job/")
            or request.url.path.startswith("/submission/claims/") and request.url.path.endswith("/preview")
        )
    )
    started = time.perf_counter()
    if not quiet_poll:
        logger.info("%s %s -> start", request.method, request.url.path)
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if not quiet_poll:
        logger.info("%s %s -> %s (%.1fms)", request.method, request.url.path, response.status_code, elapsed_ms)
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ORIGINS", "*").split(",")[0], "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Service registry: (prefix, module path, router attribute, tag) ──
SERVICES = [
    ("/ingress",    "services.ingress.app.main",    "router", "Ingress"),
    ("/ocr",        "services.ocr.app.main",        "router", "OCR"),
    ("/parser",     "services.parser.app.main",     "router", "Parser"),
    ("/coding",     "services.coding.app.main",     "router", "Coding"),
    ("/predictor",  "services.predictor.app.main",  "router", "Predictor"),
    ("/validator",  "services.validator.app.main",   "router", "Validator"),
    ("/workflow",   "services.workflow.app.main",    "router", "Workflow"),
    ("/submission", "services.submission.app.main",  "router", "Submission"),
    ("/chat",       "services.chat.app.main",       "router", "Chat"),
    ("/search",     "services.search.app.main",     "router", "Search"),
]


@app.get("/", tags=["Gateway"])
def root():
    return {
        "service": "ClaimGPT API Gateway",
        "version": "0.1.0",
        "services": [s[0] for s in SERVICES],
        "docs": "/docs",
    }


@app.get("/health", tags=["Gateway"])
def health():
    return {"status": "ok"}


# ── Include each service router (graceful — skip if deps missing) ──
for prefix, module_path, attr, tag in SERVICES:
    try:
        mod = importlib.import_module(module_path)
        svc_router = getattr(mod, attr)
        app.include_router(svc_router, prefix=prefix, tags=[tag])
    except Exception as exc:  # noqa: BLE001
        print(f"⚠ Skipping {prefix}: {exc}")
