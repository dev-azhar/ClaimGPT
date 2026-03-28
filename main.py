"""
ClaimGPT — API Gateway / Root Entrypoint

Includes all 10 microservice routers under a single FastAPI app so
every endpoint appears in one unified OpenAPI / Swagger UI at /docs.
Each service is also runnable standalone via uvicorn.
"""

import os
import sys
import importlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ── Ensure service packages are importable ──
ROOT = Path(__file__).resolve().parent
for svc_dir in sorted((ROOT / "services").iterdir()):
    if svc_dir.is_dir() and (svc_dir / "app").is_dir():
        sys.path.insert(0, str(svc_dir))

app = FastAPI(
    title="ClaimGPT",
    description="AI-powered medical claims processing platform",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")[0], "*"],
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
