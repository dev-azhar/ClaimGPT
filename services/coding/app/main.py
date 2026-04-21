from __future__ import annotations

import logging
import uuid
import contextvars

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .config import settings
from .db import SessionLocal, check_db_health, engine
from .engine import _load_scispacy, extract_entities_and_codes
from .models import (
    Claim,
    Document,
    MedicalCode,
    MedicalEntity,
    OcrResult,
    ParsedField,
)
from .schemas import CodingResultOut, MedicalCodeOut, MedicalEntityOut

# ------------------------------------------------------------------ logging
correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="SYSTEM")

class CorrelationIdFilter(logging.Filter):
    def filter(self, record):
        record.correlation_id = correlation_id.get()
        return True

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  [Claim: %(correlation_id)s]  %(name)s  %(message)s",
)

for handler in logging.root.handlers:
    handler.addFilter(CorrelationIdFilter())
logger = logging.getLogger("coding")

app = FastAPI(title="ClaimGPT Medical Coding Service")

# ------------------------------------------------------------------ CORS
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
    init_tracing("coding")
    init_metrics("coding")
    instrument_fastapi(app)
    app.add_middleware(PrometheusMiddleware)
    _metrics_handler = metrics_endpoint()
    if _metrics_handler:
        app.get("/metrics")(_metrics_handler)
except Exception:
    logger.debug("Observability libs not available — skipping")

# ------------------------------------------------------------------ custom domain metrics
try:
    from prometheus_client import Counter, Histogram
    
    CODING_ENTITIES_TOTAL = Counter(
        "coding_entities_extracted_total",
        "Total medical entities extracted",
        ["entity_type", "model_used"]
    )
    CODING_CONFIDENCE = Histogram(
        "coding_entity_confidence",
        "Confidence score distribution of extracted entities",
        ["entity_type"],
        buckets=[0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99]
    )
    CODING_MODEL_USAGE = Counter(
        "coding_model_usage_total",
        "Tracks which NLP model answered the request to monitor drift",
        ["model"]
    )
except ImportError:
    CODING_ENTITIES_TOTAL = None
    CODING_CONFIDENCE = None
    CODING_MODEL_USAGE = None

@app.on_event("startup")
def _startup():
    logger.info("Initializing background models...")
    _load_scispacy()
    
@app.on_event("shutdown")
def _shutdown():
    engine.dispose()


# ------------------------------------------------------------------ deps
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")


# ------------------------------------------------------------------ helpers

def _collect_texts(db: Session, claim_id: uuid.UUID) -> list[str]:
    """Gather OCR raw text for a claim."""
    texts: list[str] = []
    doc_ids = [
        d.id
        for d in db.query(Document).filter(Document.claim_id == claim_id).all()
    ]
    if doc_ids:
        ocr_rows = (
            db.query(OcrResult)
            .filter(OcrResult.document_id.in_(doc_ids))
            .order_by(OcrResult.page_number)
            .all()
        )
        for r in ocr_rows:
            if r.text:
                texts.append(r.text)

    return texts


def _collect_parsed_fields(db: Session, claim_id: uuid.UUID) -> list[dict]:
    """Gather parsed fields for a claim."""
    pf_rows = db.query(ParsedField).filter(ParsedField.claim_id == claim_id).all()
    return [
        {"field_name": pf.field_name, "field_value": pf.field_value}
        for pf in pf_rows
        if pf.field_value
    ]


# ------------------------------------------------------------------ routes

router = APIRouter()


@router.get("/health")
def health():
    db_ok = check_db_health()
    return {"status": "ok" if db_ok else "degraded", "database": "up" if db_ok else "down"}


@router.post("/code-suggest/{claim_id}", response_model=CodingResultOut)
async def run_coding(claim_id: str, db: Session = Depends(get_db)):
    """
    Extract medical entities (NER) and assign ICD-10 / CPT codes
    from OCR + parsed data for a claim. Idempotent — re-running replaces
    previous results.
    """
    correlation_id.set(claim_id)
    cid = _parse_uuid(claim_id)

    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    texts = _collect_texts(db, cid)
    if not texts:
        raise HTTPException(
            status_code=409,
            detail="No OCR/parsed data available — run OCR and parsing first",
        )

    parsed_fields = _collect_parsed_fields(db, cid)
    output = await run_in_threadpool(extract_entities_and_codes, texts, parsed_fields or None)

    if CODING_MODEL_USAGE is not None:
        CODING_MODEL_USAGE.labels(model=output.model_used).inc()

    # Idempotent: wipe old results
    db.query(MedicalCode).filter(MedicalCode.claim_id == cid).delete()
    db.query(MedicalEntity).filter(MedicalEntity.claim_id == cid).delete()

    # Persist entities
    entity_map: dict[int, MedicalEntity] = {}
    for i, ent in enumerate(output.entities):
        if CODING_ENTITIES_TOTAL is not None:
            CODING_ENTITIES_TOTAL.labels(entity_type=ent.entity_type, model_used=output.model_used).inc()
        if CODING_CONFIDENCE is not None and ent.confidence is not None:
            CODING_CONFIDENCE.labels(entity_type=ent.entity_type).observe(ent.confidence)
            
        row = MedicalEntity(
            claim_id=cid,
            entity_text=ent.entity_text,
            entity_type=ent.entity_type,
            start_offset=ent.start_offset,
            end_offset=ent.end_offset,
            confidence=ent.confidence,
        )
        db.add(row)
        db.flush()
        entity_map[i] = row

    # Persist codes
    for code in output.codes:
        entity_id_val = None
        if code.entity_index is not None and code.entity_index in entity_map:
            entity_id_val = entity_map[code.entity_index].id

        db.add(MedicalCode(
            claim_id=cid,
            entity_id=entity_id_val,
            code=code.code,
            code_system=code.code_system,
            description=code.description,
            confidence=code.confidence,
            is_primary=code.is_primary,
            estimated_cost=code.estimated_cost,
        ))

    claim.status = "CODED"
    db.commit()

    logger.info(
        "Coding complete for claim %s — %d entities, %d codes",
        cid, len(output.entities), len(output.codes),
    )

    return _build_result(db, cid, "CODED")


@router.get("/code-suggest/{claim_id}", response_model=CodingResultOut)
def get_coding(claim_id: str, db: Session = Depends(get_db)):
    """Retrieve medical entities and codes for a claim."""
    correlation_id.set(claim_id)
    cid = _parse_uuid(claim_id)

    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    return _build_result(db, cid, claim.status)


def _build_result(db: Session, cid: uuid.UUID, status: str) -> CodingResultOut:
    entities = db.query(MedicalEntity).filter(MedicalEntity.claim_id == cid).all()
    all_codes = db.query(MedicalCode).filter(MedicalCode.claim_id == cid).all()

    return CodingResultOut(
        claim_id=cid,
        status=status,
        entities=[
            MedicalEntityOut(
                id=e.id,
                entity_text=e.entity_text,
                entity_type=e.entity_type,
                start_offset=e.start_offset,
                end_offset=e.end_offset,
                confidence=e.confidence,
                codes=[
                    MedicalCodeOut(
                        id=c.id, code=c.code, code_system=c.code_system,
                        description=c.description, confidence=c.confidence,
                        is_primary=c.is_primary,
                    )
                    for c in e.codes
                ],
                created_at=e.created_at,
            )
            for e in entities
        ],
        icd_codes=[
            MedicalCodeOut(
                id=c.id, code=c.code, code_system=c.code_system,
                description=c.description, confidence=c.confidence,
                is_primary=c.is_primary, estimated_cost=c.estimated_cost,
            )
            for c in all_codes if c.code_system == "ICD10"
        ],
        cpt_codes=[
            MedicalCodeOut(
                id=c.id, code=c.code, code_system=c.code_system,
                description=c.description, confidence=c.confidence,
                is_primary=c.is_primary, estimated_cost=c.estimated_cost,
            )
            for c in all_codes if c.code_system == "CPT"
        ],
    )


# ── Include router (standalone mode) ──
app.include_router(router)
