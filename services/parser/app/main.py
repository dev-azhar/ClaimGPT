


from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, check_db_health, engine
from libs.shared.db import get_db_session
from .lightweight_ner import extract_ner_entities
from .engine import FieldResult, ParseOutput, parse_document
from .field_resolver import Candidate, resolve as resolve_fields
from .models import Claim, Document, DocValidation, OcrResult, ParsedField, ParseJob
from .schemas import (
    ParsedFieldOut,
    ParseJobOut,
    ParseJobStatusOut,
    ParseResultOut,
)

# ── audit helper ──
try:
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "..", ".."))
    from libs.utils.audit import AuditLogger
except Exception:
    AuditLogger = None  # type: ignore

def _audit(db, action, claim_id=None, metadata=None):
    try:
        if AuditLogger:
            AuditLogger(db, "parser").log(action, claim_id=claim_id, metadata=metadata)
    except Exception:
        pass

# ------------------------------------------------------------------ logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("parser-debug")

app = FastAPI(title="ClaimGPT Parser Service")

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
    init_tracing("parser")
    init_metrics("parser")
    instrument_fastapi(app)
    app.add_middleware(PrometheusMiddleware)
    _metrics_handler = metrics_endpoint()
    if _metrics_handler:
        app.get("/metrics")(_metrics_handler)
except Exception:
    logger.debug("Observability libs not available — skipping")


# ------------------------------------------------------------------ lifecycle
@app.on_event("shutdown")
def _shutdown():
    engine.dispose()
    logger.info("DB engine disposed")


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

def _gather_ocr_pages(db: Session, claim_id: uuid.UUID) -> list[dict[str, Any]]:
    """Collect OCR text grouped by page for a claim's documents."""
    excluded_doc_ids = {
        r.document_id
        for r in db.query(DocValidation).filter(
            DocValidation.claim_id == claim_id,
            DocValidation.doc_type == "IDENTITY_GATE",
        ).all()
        if (r.validation_metadata or {}).get("excluded_from_pipeline")
    }

    documents = (
        db.query(Document)
        .filter(Document.claim_id == claim_id)
        .order_by(Document.uploaded_at)
        .all()
    )
    documents = [d for d in documents if d.id not in excluded_doc_ids]
    pages: list[dict[str, Any]] = []
    for doc in documents:
        # Fetch OcrResult by joining through Document, not by ocr_job_id
        rows = (
            db.query(OcrResult)
            .join(Document, OcrResult.document_id == Document.id)
            .filter(OcrResult.document_id == doc.id)
            .order_by(OcrResult.page_number)
            .all()
        )
        for r in rows:
            pages.append({
                "page_number": r.page_number,
                "text": r.text or "",
                "raw_text": r.text or "",
                "markdown": r.text or "",
                "tokens": r.tokens or [],
                "document_id": str(doc.id),
                "file_name": doc.file_name,
            })
    return pages


def _get_document_type_map(db: Session, claim_id: uuid.UUID) -> dict[str, str]:
    """Get mapping of document_id (string) to doc_type from DocValidation table."""
    doc_type_map = {}
    validations = db.query(DocValidation).filter(
        DocValidation.claim_id == claim_id
    ).all()
    for validation in validations:
        doc_type_map[str(validation.document_id)] = validation.doc_type or "UNKNOWN"
    return doc_type_map


def _enrich_fields_with_doc_info(
    output: ParseOutput,
    ocr_pages: list[dict[str, Any]],
    doc_type_map: dict[str, str],
) -> None:
    """
    Enrich parsed fields with document_id and doc_type information.
    Maps source_page to document_id from OCR pages, then looks up doc_type.
    """
    # Create a mapping of page_number -> document_id from OCR pages
    page_to_doc_map = {}
    for page in ocr_pages:
        page_num = page.get("page_number")
        doc_id = page.get("document_id")
        if page_num is not None and doc_id:
            page_to_doc_map[page_num] = doc_id
    
    # Enrich each field with document_id and doc_type
    for field in output.fields:
        # Get document_id from source_page mapping
        if field.source_page is not None and field.source_page in page_to_doc_map:
            field.document_id = page_to_doc_map[field.source_page]
        
        # Get doc_type from the mapping
        if field.document_id:
            field.doc_type = doc_type_map.get(field.document_id, "UNKNOWN")


def _merge_lightweight_entities(
    current: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(current)
    for key in ("patient_name", "hospital_name", "doctor_name", "diagnosis"):
        if not merged.get(key) and candidate.get(key):
            merged[key] = candidate.get(key)

    medicines = list(merged.get("medicines") or [])
    for medicine in candidate.get("medicines") or []:
        if medicine not in medicines:
            medicines.append(medicine)
    merged["medicines"] = medicines
    return merged


def _apply_lightweight_entities(
    output: ParseOutput,
    entities: dict[str, Any],
    source_page: int | None = None,
) -> None:
    existing = {field.field_name for field in output.fields}
    field_map = {
        "patient_name": entities.get("patient_name"),
        "hospital_name": entities.get("hospital_name"),
        "doctor_name": entities.get("doctor_name"),
        "diagnosis": entities.get("diagnosis"),
    }

    for field_name, value in field_map.items():
        if not value or field_name in existing:
            continue
        output.fields.append(FieldResult(
            field_name=field_name,
            field_value=str(value).strip(),
            source_page=source_page,
            model_version="lightweight-ner-v1",
        ))

    medicines = entities.get("medicines") or []
    if medicines and "medicines" not in existing:
        output.fields.append(FieldResult(
            field_name="medicines",
            field_value=", ".join(str(m).strip() for m in medicines if str(m).strip()),
            source_page=source_page,
            model_version="lightweight-ner-v1",
        ))

def _default_confidence_for_model(model_version: str | None, field_name: str) -> Tuple[float, str]:
    mv = (model_version or "").lower()
    # Priority: anchor/form > structured parser > layout parser > ner > regex
    if "-form-" in mv or mv.endswith("form-v1"):
        return 0.95, "form_extractor"
    if "pp-structure" in mv or mv.endswith("pp-structure-v1") or "pp-structure" in mv:
        return 0.85, "layout_parser"
    if mv.startswith("lightweight-ner"):
        return 0.60, "lightweight-ner"
    if "expense-table" in mv or "table" in mv:
        return 0.9, "table_extractor"
    # default
    return 0.5, mv or "unknown"


def _persist_fields(
    db: Session,
    claim_id: uuid.UUID,
    output: ParseOutput,
) -> None:
    """Delete old parsed fields for claim and insert new ones."""
    db.query(ParsedField).filter(ParsedField.claim_id == claim_id).delete()

    for f in output.fields:
        db.add(ParsedField(
            claim_id=claim_id,
            document_id=f.document_id,
            field_name=f.field_name,
            field_value=f.field_value,
            bounding_box=f.bounding_box,
            source_page=f.source_page,
            doc_type=f.doc_type,
            model_version=f.model_version,
        ))
    db.commit()


def _render_table_markdown(header: List[Any] | None, rows: List[List[Any]]) -> str:
    if not rows:
        return ""
    col_count = max(len(header or []), *(len(r) for r in rows))
    safe_header = [str(c).strip() for c in (header or [])]
    while len(safe_header) < col_count:
        safe_header.append(f"col_{len(safe_header) + 1}")

    lines = [
        "| " + " | ".join(safe_header) + " |",
        "| " + " | ".join(["---"] * col_count) + " |",
    ]
    for row in rows:
        padded = [str(c).strip() for c in row] + [""] * (col_count - len(row))
        lines.append("| " + " | ".join(padded[:col_count]) + " |")
    return "\n".join(lines)


def _build_table_views(output: ParseOutput) -> List[Dict[str, Any]]:
    views: List[Dict[str, Any]] = []

    for idx, table in enumerate(output.tables or [], start=1):
        rows = table.get("rows") or []
        header = table.get("header")
        views.append({
            "source": "parser_output",
            "table_index": idx,
            "source_page": table.get("source_page"),
            "row_count": table.get("row_count", len(rows)),
            "header": header,
            "rows": rows,
            "markdown": _render_table_markdown(header, rows),
        })

    for p in output.page_objects or []:
        page_num = p.get("page_number")
        doc_id = p.get("document_id")
        for idx, table in enumerate(p.get("detected_tables") or [], start=1):
            rows = table.get("rows") or []
            header = table.get("header")
            views.append({
                "source": "page_detected",
                "document_id": doc_id,
                "source_page": page_num,
                "table_index": idx,
                "row_count": table.get("row_count", len(rows)),
                "header": header,
                "rows": rows,
                "markdown": _render_table_markdown(header, rows),
            })

    return views


from .schema_normalizer import build_canonical_schema


def _build_canonical_claim(output: ParseOutput) -> dict[str, Any]:
    """Convert parser output fields and tables into a canonical claim payload."""
    form_data: dict[str, str] = {}
    for f in output.fields:
        if f.field_value is not None and f.field_name not in form_data:
            form_data[f.field_name] = f.field_value

    # Pass table objects directly (with type information) to schema_normalizer
    table_data: list[dict[str, Any]] = output.tables or []

    entities = {
        "patient_name": form_data.get("patient_name"),
        "hospital_name": form_data.get("hospital_name"),
        "doctor_name": form_data.get("doctor_name"),
        "diagnosis": form_data.get("diagnosis"),
        "medicines": [
            value.strip()
            for key, value in form_data.items()
            if key == "medicines" and value
        ],
    }
    if not entities["medicines"]:
        entities["medicines"] = []

    return build_canonical_schema(form_data, table_data, entities=entities)


def _build_renderer_input(
    output: ParseOutput,
    ocr_pages: List[Dict[str, Any]],
    layout: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "claim_id": str(ocr_pages[0].get("document_id")) if ocr_pages else None,
        "model_version": output.model_version,
        "used_fallback": output.used_fallback,
        "fields": [
            {
                "field_name": f.field_name,
                "field_value": f.field_value,
                "bounding_box": f.bounding_box,
                "source_page": f.source_page,
                "document_id": f.document_id,
                "doc_type": f.doc_type,
                "model_version": f.model_version,
            }
            for f in output.fields
        ],
        "tables": output.tables,
        "sections": output.sections,
        "layout": layout,
        "ocr_pages": [
            {
                "page_number": p.get("page_number"),
                "document_id": p.get("document_id"),
                "text": p.get("text"),
                "tokens": p.get("tokens", []),
            }
            for p in ocr_pages
        ],
        "canonical_claim": _build_canonical_claim(output),
    }


def _write_parse_debug_dump(
    job: ParseJob,
    ocr_pages: List[Dict[str, Any]],
    output: ParseOutput,
    layout: dict[str, Any] | None = None,
) -> None:
    """Temporarily dump OCR + parsed data for manual inspection/debugging."""
    if not settings.debug_dump_enabled:
        return

    dump_dir = Path(settings.debug_dump_dir)
    if not dump_dir.is_absolute():
        dump_dir = Path.cwd() / dump_dir
    dump_dir.mkdir(parents=True, exist_ok=True)
    table_views = _build_table_views(output)
    canonical_claim = _build_canonical_claim(output)
    renderer_input = _build_renderer_input(output, ocr_pages, layout=layout)

    payload = {
        "claim_id": str(job.claim_id),
        "job_id": str(job.id),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "model_version": output.model_version,
        "used_fallback": output.used_fallback,
        "ocr_pages": ocr_pages,
        "page_objects": output.page_objects,
        "results": output.document_boundaries,
        "fields": [
            {
                "field_name": f.field_name,
                "field_value": f.field_value,
                "bounding_box": f.bounding_box,
                "source_page": f.source_page,
                "document_id": f.document_id,
                "doc_type": f.doc_type,
                "model_version": f.model_version,
            }
            for f in output.fields
        ],
        "tables": output.tables,
        "table_views": table_views,
        "sections": output.sections,
        "layout": layout,
        "canonical_claim": canonical_claim,
        "renderer_input": renderer_input,
    }

    file_name = f"{job.claim_id}_{job.id}.json"
    file_path = dump_dir / file_name
    file_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    file_path.with_name(f"{job.claim_id}_{job.id}_real_tokens.json").write_text(
        json.dumps([t for page in ocr_pages for t in page.get("tokens", [])], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    file_path.with_name(f"{job.claim_id}_{job.id}_layout_sections.json").write_text(
        json.dumps(layout if layout is not None else output.sections, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    file_path.with_name(f"{job.claim_id}_{job.id}_canonical_claim.json").write_text(
        json.dumps(canonical_claim, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    file_path.with_name(f"{job.claim_id}_{job.id}_renderer_input.json").write_text(
        json.dumps(renderer_input, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    audit_payload = {
        "claim_id": str(job.claim_id),
        "job_id": str(job.id),
        "model_version": output.model_version,
        "used_fallback": output.used_fallback,
        "field_count": len(output.fields),
        "table_count": len(output.tables),
        "section_count": len(output.sections),
        "line_item_count": sum(len(table.get("rows", [])) for table in output.tables or []),
        "canonical_claim_summary": {
            "patient_name": canonical_claim["patient"].get("name"),
            "policy_number": canonical_claim["patient"].get("policy_number"),
            "hospital_name": canonical_claim["hospitalization"].get("hospital_name"),
            "total_amount": canonical_claim["claims"].get("total_amount"),
        },
    }
    file_path.with_name(f"{job.claim_id}_{job.id}_final_render_audit.json").write_text(
        json.dumps(audit_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Parser debug dump written: %s", file_path)


# ------------------------------------------------------------------ background worker

def _run_parse_job(job_id: uuid.UUID) -> None:
    """Background worker that parses all documents for a claim."""
    import time
    job_start = time.time()
    
    logger.info(f"[PARSER] _run_parse_job called for job_id={job_id}")
    with get_db_session() as db:
        try:
            job = db.query(ParseJob).filter(ParseJob.id == job_id).first()
            if not job:
                logger.error("ParseJob %s not found — aborting", job_id)
                return
            logger.info(f"[PARSER] Job found: {job}")

            job.status = "PROCESSING"
            db.commit()

            claim = db.query(Claim).filter(Claim.id == job.claim_id).first()
            if claim:
                claim.status = "PARSING"
                db.commit()

            # Set set_hash for this ParseJob
            hashes = [d.content_hash for d in db.query(Document).filter(Document.claim_id == job.claim_id).all() if d.content_hash]
            hashes.sort()
            joined = ",".join(hashes)
            set_hash = hashlib.sha256(joined.encode("utf-8")).hexdigest()
            job.set_hash = set_hash
            db.commit()

            # Gather OCR pages by document_id for all documents in claim
            ocr_pages = []
            documents = db.query(Document).filter(Document.claim_id == job.claim_id).all()
            for doc in documents:
                rows = (
                    db.query(OcrResult)
                    .filter(OcrResult.document_id == doc.id)
                    .order_by(OcrResult.page_number)
                    .all()
                )
                for r in rows:
                    # CRITICAL: Include real tokens with geometry (x0, y0, x1, y1)
                    # This bypasses flattened line coordinate inference
                    tokens = r.tokens or []
                    
                    ocr_pages.append({
                        "page_number": r.page_number,
                        "text": r.text or "",
                        "tokens": tokens,  # Real token geometry (x0, y0, x1, y1)
                        "document_id": str(doc.id),
                        "file_name": doc.file_name,
                    })
            logger.info(f"[PARSER] Found {len(ocr_pages)} OCR pages for claim {job.claim_id}")
            if not ocr_pages:
                job.status = "FAILED"
                job.error_message = "No OCR results available — run OCR first"
                job.completed_at = datetime.now(UTC)
                if claim:
                    claim.status = "PARSE_FAILED"
                db.commit()
                logger.warning(f"[PARSER] No OCR pages found for claim {job.claim_id}, job {job_id} failed.")
                return

            job.total_documents = len(
                {p["document_id"] for p in ocr_pages}
            )
            db.commit()

            doc_type_map = _get_document_type_map(db, job.claim_id)

            try:
                from .layout_analyzer_lightweight import analyze_layout_lightweight
                import time

                combined_output = ParseOutput()
                combined_candidates: list[Candidate] = []
                combined_ocr_pages: list[dict[str, Any]] = []
                combined_layout_sections: list[dict[str, Any]] = []
                combined_entities: dict[str, Any] = {"medicines": []}

                for doc in documents:
                    rows = (
                        db.query(OcrResult)
                        .filter(OcrResult.document_id == doc.id)
                        .order_by(OcrResult.page_number)
                        .all()
                    )

                    doc_pages: list[dict[str, Any]] = []
                    doc_tokens: list[dict[str, Any]] = []
                    for r in rows:
                        token_list: list[dict[str, Any]] = []
                        for token in (r.tokens or []):
                            token_copy = dict(token)
                            if token_copy.get("page") is None:
                                token_copy["page"] = r.page_number
                            token_copy["document_id"] = str(doc.id)
                            token_list.append(token_copy)
                            doc_tokens.append(token_copy)

                        doc_pages.append({
                            "page_number": r.page_number,
                            "text": r.text or "",
                            "tokens": token_list,
                            "document_id": str(doc.id),
                            "file_name": doc.file_name,
                        })

                    if not doc_pages:
                        logger.warning("No OCR pages found for document %s", doc.id)
                        continue

                    start_layout = time.time()
                    layout = analyze_layout_lightweight(doc_tokens, page_images=None, debug_dump_dir=None)
                    logger.warning(f"[PERF] Lightweight layout analysis for %s: %.3fs", doc.file_name, time.time() - start_layout)

                    start_parse = time.time()
                    output = parse_document(doc_pages, layout=layout, images=None)
                    logger.warning(f"[PERF] Parse extraction for %s: %.3fs", doc.file_name, time.time() - start_parse)

                    section_tokens: dict[str, list[dict[str, Any]]] = {}
                    for section in layout.get("sections", []) or []:
                        section_type = str(section.get("type", "")).lower()
                        section_tokens.setdefault(section_type, []).extend(section.get("tokens", []) or [])

                    doc_entities = extract_ner_entities(
                        patient_tokens=section_tokens.get("patient_info"),
                        hospital_tokens=(section_tokens.get("hospitalization_info") or []) + (section_tokens.get("hospital_info") or []),
                        diagnosis_tokens=section_tokens.get("diagnosis"),
                        all_tokens=doc_tokens,
                    )
                    _apply_lightweight_entities(output, doc_entities, source_page=doc_pages[0].get("page_number"))

                    _enrich_fields_with_doc_info(output, doc_pages, doc_type_map)

                    # Convert parser field results into resolver candidates
                    for f in output.fields:
                        conf, extractor = _default_confidence_for_model(f.model_version, f.field_name)
                        combined_candidates.append(Candidate(
                            field_name=f.field_name,
                            field_value=f.field_value,
                            confidence=conf,
                            extractor_name=extractor,
                            bounding_box=f.bounding_box,
                            source_page=f.source_page,
                            model_version=f.model_version,
                            document_id=f.document_id,
                            doc_type=f.doc_type,
                        ))
                    combined_output.tables.extend(output.tables)
                    combined_output.sections.extend(output.sections)
                    combined_output.page_objects.extend(output.page_objects)
                    combined_ocr_pages.extend(doc_pages)
                    combined_layout_sections.extend(layout.get("sections", []))
                    combined_entities = _merge_lightweight_entities(
                        combined_entities,
                        doc_entities,
                    )

                    # Add NER entity candidates (lower default confidence)
                    ner_map = {
                        "patient_name": doc_entities.get("patient_name"),
                        "hospital_name": doc_entities.get("hospital_name"),
                        "doctor_name": doc_entities.get("doctor_name"),
                        "diagnosis": doc_entities.get("diagnosis"),
                    }
                    for k, v in ner_map.items():
                        if v:
                            conf, extractor = _default_confidence_for_model("lightweight-ner-v1", k)
                            combined_candidates.append(Candidate(
                                field_name=k,
                                field_value=str(v).strip(),
                                confidence=conf,
                                extractor_name=extractor,
                                bounding_box=None,
                                source_page=doc_pages[0].get("page_number") if doc_pages else None,
                                model_version="lightweight-ner-v1",
                                document_id=str(doc.id),
                                doc_type=doc_type_map.get(str(doc.id)),
                            ))

                if not combined_candidates and not combined_output.tables:
                    raise ValueError("Parser produced no structured output")

                # Resolve field candidates into final chosen fields with provenance
                resolved_list, provenance_map = resolve_fields(combined_candidates)

                # Convert resolved entries into FieldResult objects
                final_field_results: list[FieldResult] = []
                for r in resolved_list:
                    final_field_results.append(FieldResult(
                        field_name=r.get("field_name"),
                        field_value=r.get("field_value"),
                        bounding_box=r.get("bounding_box"),
                        source_page=r.get("source_page"),
                        model_version=r.get("model_version"),
                        document_id=r.get("document_id"),
                        doc_type=r.get("doc_type"),
                        confidence=r.get("confidence"),
                        extractor_name=r.get("extractor"),
                        provenance=provenance_map.get(r.get("field_name")),
                    ))

                combined_output.fields = final_field_results

                job_end = time.time()
                total_job_time = job_end - job_start if 'job_start' in locals() else 0
                logger.warning(f"[PERF] Total job time: {total_job_time:.2f}s")

                output = combined_output
                canonical_claim = _build_canonical_claim(output)
                canonical_claim["medical_entities"] = {
                    "patient_name": combined_entities.get("patient_name"),
                    "hospital_name": combined_entities.get("hospital_name"),
                    "doctor_name": combined_entities.get("doctor_name"),
                    "diagnosis": combined_entities.get("diagnosis"),
                    "medicines": combined_entities.get("medicines") or [],
                }
                # Attach field resolution provenance into canonical payload
                canonical_claim["_field_resolution"] = provenance_map

                if claim:
                    claim.canonical_json = canonical_claim
                    claim.status = "PARSED"

                # Write debug artifacts if enabled. Do this before persisting fields
                # so the debug dump contains the combined OCR pages, layout and output.
                try:
                    _write_parse_debug_dump(job, combined_ocr_pages, output, layout={"sections": combined_layout_sections})
                except Exception:
                    logger.exception("Failed to write parse debug dump")

                _persist_fields(db, job.claim_id, output)

                job.status = "COMPLETED"
                job.model_version = output.model_version
                job.used_fallback = output.used_fallback
                job.processed_documents = job.total_documents
                job.completed_at = datetime.now(UTC)
                db.commit()
            except Exception:
                logger.exception("Parse engine failed for job %s", job_id)
                job.status = "FAILED"
                job.error_message = "Parse engine error"
                job.completed_at = datetime.now(UTC)
                if claim:
                    claim.status = "PARSE_FAILED"

                db.commit()
                return

        except Exception as e:
            db.rollback()
            logger.exception(f"Unexpected error in parse job {job_id}: {e}")
            try:
                job = db.query(ParseJob).filter(ParseJob.id == job_id).first()
                if job:
                    job.status = "FAILED"
                    job.error_message = "Internal error"
                    job.completed_at = datetime.now(UTC)
                    db.commit()
            except Exception:
                pass


# ------------------------------------------------------------------ routes

router = APIRouter()


@router.get("/health")
def health():
    db_ok = check_db_health()
    status = "ok" if db_ok else "degraded"
    return {"status": status, "database": "up" if db_ok else "down"}


@router.post("/parse/{claim_id}", response_model=ParseJobOut, status_code=202)
def start_parse(
    claim_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Trigger document parsing for a claim. Reads OCR results from the DB,
    runs the lightweight coordinate-native parser, and persists structured fields.
    Returns a job_id for polling.
    """
    cid = _parse_uuid(claim_id)

    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Ensure OCR has been run
    excluded_doc_ids = {
        r.document_id
        for r in db.query(DocValidation).filter(
            DocValidation.claim_id == cid,
            DocValidation.doc_type == "IDENTITY_GATE",
        ).all()
        if (r.validation_metadata or {}).get("excluded_from_pipeline")
    }

    doc_ids = [
        d.id for d in db.query(Document).filter(Document.claim_id == cid).all()
        if d.id not in excluded_doc_ids
    ]
    if not doc_ids:
        raise HTTPException(status_code=409, detail="No documents passed identity gate for parsing")

    ocr_count = (
        db.query(OcrResult)
        .filter(OcrResult.document_id.in_(doc_ids))
        .count()
    )
    if ocr_count == 0:
        raise HTTPException(
            status_code=409,
            detail="OCR has not been completed for this claim — run OCR first",
        )

    job = ParseJob(
        claim_id=cid,
        status="QUEUED",
        total_documents=len(doc_ids),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_run_parse_job, job.id)

    return ParseJobOut(
        job_id=job.id,
        claim_id=job.claim_id,
        status=job.status,
        total_documents=job.total_documents,
        processed_documents=0,
        created_at=job.created_at,
    )


@router.get("/parse/{claim_id}", response_model=ParseResultOut)
def get_parsed(claim_id: str, db: Session = Depends(get_db)):
    """
    Retrieve the latest parsed fields for a claim.
    """
    cid = _parse_uuid(claim_id)

    claim = db.query(Claim).filter(Claim.id == cid).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    rows = (
        db.query(ParsedField)
        .filter(ParsedField.claim_id == cid)
        .order_by(ParsedField.source_page, ParsedField.field_name)
        .all()
    )

    # Determine status from latest parse job
    latest_job = (
        db.query(ParseJob)
        .filter(ParseJob.claim_id == cid)
        .order_by(ParseJob.created_at.desc())
        .first()
    )
    status = latest_job.status if latest_job else ("PARSED" if rows else "NOT_STARTED")
    model_version = latest_job.model_version if latest_job else None
    used_fallback = latest_job.used_fallback if latest_job else False

    fields = [
        ParsedFieldOut(
            id=r.id,
            field_name=r.field_name,
            field_value=r.field_value,
            bounding_box=r.bounding_box,
            source_page=r.source_page,
            model_version=r.model_version,
            created_at=r.created_at,
        )
        for r in rows
    ]

    return ParseResultOut(
        claim_id=cid,
        status=status,
        model_version=model_version,
        used_fallback=used_fallback,
        fields=fields,
    )


@router.get("/parse/job/{job_id}", response_model=ParseJobStatusOut)
def get_parse_job_status(job_id: str, db: Session = Depends(get_db)):
    """Poll a parse job for its status and results."""
    jid = _parse_uuid(job_id)

    job = db.query(ParseJob).filter(ParseJob.id == jid).first()
    if not job:
        raise HTTPException(status_code=404, detail="Parse job not found")

    fields: list[ParsedFieldOut] = []
    if job.status in ("COMPLETED", "FAILED"):
        rows = (
            db.query(ParsedField)
            .filter(ParsedField.claim_id == job.claim_id)
            .order_by(ParsedField.source_page, ParsedField.field_name)
            .all()
        )
        fields = [
            ParsedFieldOut(
                id=r.id,
                field_name=r.field_name,
                field_value=r.field_value,
                bounding_box=r.bounding_box,
                source_page=r.source_page,
                model_version=r.model_version,
                created_at=r.created_at,
            )
            for r in rows
        ]

    return ParseJobStatusOut(
        job_id=job.id,
        claim_id=job.claim_id,
        status=job.status,
        total_documents=job.total_documents,
        processed_documents=job.processed_documents,
        model_version=job.model_version,
        used_fallback=job.used_fallback,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
        fields=fields,
    )


# ── Include router (standalone mode) ──
app.include_router(router)
