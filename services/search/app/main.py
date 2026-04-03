from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, check_db_health, engine
from .models import Claim, Document, OcrResult, ParsedField
from .schemas import IndexRequest, SearchHit, SearchResultOut, VectorSearchRequest
from .vector import get_index_stats, index_claim, index_claims_batch, search_similar

# ------------------------------------------------------------------ logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("search")

app = FastAPI(title="ClaimGPT Search & Indexing Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------ observability
try:
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from libs.observability.metrics import PrometheusMiddleware, init_metrics, metrics_endpoint
    from libs.observability.tracing import init_tracing, instrument_fastapi
    init_tracing("search")
    init_metrics("search")
    instrument_fastapi(app)
    app.add_middleware(PrometheusMiddleware)
    _metrics_handler = metrics_endpoint()
    if _metrics_handler:
        app.get("/metrics")(_metrics_handler)
except Exception:
    logger.debug("Observability libs not available — skipping")


@app.on_event("shutdown")
def _shutdown():
    engine.dispose()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ------------------------------------------------------------------ routes

router = APIRouter()


@router.get("/health")
def health():
    db_ok = check_db_health()
    return {"status": "ok" if db_ok else "degraded", "database": "up" if db_ok else "down"}


@router.get("/", response_model=SearchResultOut)
def search_claims(
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Full-text search across claims, parsed fields, and OCR results.
    Uses Postgres ILIKE as a baseline — swap in OpenSearch for production.
    """
    pattern = f"%{q}%"

    # Search parsed fields
    pf_hits = (
        db.query(ParsedField.claim_id)
        .filter(ParsedField.field_value.ilike(pattern))
        .distinct()
        .limit(limit)
        .all()
    )
    hit_claim_ids = {row[0] for row in pf_hits}

    # Search OCR text
    ocr_hits = (
        db.query(OcrResult.document_id)
        .filter(OcrResult.text.ilike(pattern))
        .distinct()
        .limit(limit)
        .all()
    )
    for row in ocr_hits:
        doc = db.query(Document).filter(Document.id == row[0]).first()
        if doc:
            hit_claim_ids.add(doc.claim_id)

    # Search claim metadata
    meta_hits = (
        db.query(Claim.id)
        .filter(
            or_(
                Claim.policy_id.ilike(pattern),
                Claim.patient_id.ilike(pattern),
                cast(Claim.id, String).ilike(pattern),
            )
        )
        .limit(limit)
        .all()
    )
    for row in meta_hits:
        hit_claim_ids.add(row[0])

    # Build results
    results = []
    for cid in list(hit_claim_ids)[:limit]:
        claim = db.query(Claim).filter(Claim.id == cid).first()
        if not claim:
            continue

        # Gather highlight snippets
        highlights = []
        pfs = (
            db.query(ParsedField)
            .filter(ParsedField.claim_id == cid, ParsedField.field_value.ilike(pattern))
            .limit(3)
            .all()
        )
        for pf in pfs:
            highlights.append(f"{pf.field_name}: {pf.field_value}")

        results.append(SearchHit(
            claim_id=cid,
            score=1.0,  # placeholder — real scoring with OpenSearch
            highlights=highlights,
            status=claim.status,
            policy_id=claim.policy_id,
            created_at=claim.created_at,
        ))

    return SearchResultOut(query=q, total=len(results), results=results)


@router.post("/vector-search", response_model=SearchResultOut)
def vector_search(body: VectorSearchRequest, db: Session = Depends(get_db)):
    """
    Semantic / vector search using sentence-transformers + FAISS.
    Falls back to text search if vector search is unavailable.
    """
    similar = search_similar(body.text, top_k=body.top_k)

    if not similar:
        # Fallback to text search if FAISS is empty or unavailable
        return search_claims(q=body.text, limit=body.top_k, db=db)

    results = []
    for claim_id_str, score in similar:
        try:
            cid = uuid.UUID(claim_id_str)
        except ValueError:
            continue

        claim = db.query(Claim).filter(Claim.id == cid).first()
        if not claim:
            continue

        # Gather highlight snippets from parsed fields
        highlights = []
        pfs = (
            db.query(ParsedField)
            .filter(ParsedField.claim_id == cid)
            .limit(3)
            .all()
        )
        for pf in pfs:
            highlights.append(f"{pf.field_name}: {pf.field_value}")

        results.append(SearchHit(
            claim_id=cid,
            score=round(score, 4),
            highlights=highlights,
            status=claim.status,
            policy_id=claim.policy_id,
            created_at=claim.created_at,
        ))

    return SearchResultOut(query=body.text, total=len(results), results=results)


@router.post("/index/{claim_id}")
def index_single_claim(claim_id: str, db: Session = Depends(get_db)):
    """Index (or re-index) a single claim for vector search."""
    cid = uuid.UUID(claim_id)

    text = _gather_claim_text(db, cid)
    if not text.strip():
        raise HTTPException(status_code=404, detail="No text content found for claim")

    ok = index_claim(str(cid), text)
    if not ok:
        raise HTTPException(status_code=503, detail="Vector search engine unavailable")

    return {"indexed": True, "claim_id": str(cid), "text_length": len(text)}


@router.post("/index/batch")
def index_batch(body: IndexRequest, db: Session = Depends(get_db)):
    """Batch-index multiple claims for vector search."""
    items = []
    for cid in body.claim_ids:
        text = _gather_claim_text(db, cid)
        if text.strip():
            items.append((str(cid), text))

    if not items:
        return {"indexed": 0}

    count = index_claims_batch(items)
    return {"indexed": count}


@router.get("/index/stats")
def index_stats():
    """Return FAISS index statistics."""
    return get_index_stats()


def _gather_claim_text(db: Session, claim_id: uuid.UUID) -> str:
    """Concatenate all text content for a claim (OCR + parsed fields)."""
    parts = []

    # Parsed fields
    pfs = db.query(ParsedField).filter(ParsedField.claim_id == claim_id).all()
    for pf in pfs:
        if pf.field_value:
            parts.append(f"{pf.field_name}: {pf.field_value}")

    # OCR text
    docs = db.query(Document).filter(Document.claim_id == claim_id).all()
    for doc in docs:
        ocr_rows = (
            db.query(OcrResult)
            .filter(OcrResult.document_id == doc.id)
            .order_by(OcrResult.page_number)
            .all()
        )
        for row in ocr_rows:
            if row.text:
                parts.append(row.text)

    return "\n".join(parts)


# ── Include router (standalone mode) ──
app.include_router(router)
