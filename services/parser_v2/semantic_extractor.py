from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from services.parser.app.config import settings

from .models import DocumentStructure, Region, TableRegion
from .schema_normalizer import normalize_fields, normalize_tables
from .semantic_backends import SemanticBackendRegistry, SemanticRequest
from .semantic_models import SemanticDocumentOutput, SemanticFieldOutput, SemanticRegionOutput, SemanticTableOutput, SemanticTableRowOutput

logger = logging.getLogger("parser-debug")


SEMANTIC_EXPENSE_TABLE_KINDS = {"expenses", "expense", "expense_table", "bill_table"}
SEMANTIC_MEDICAL_TABLE_KINDS = {"medications", "lab_results", "vitals", "diagnoses"}

_NON_EXPENSE_ROW_PREFIXES = (
    "total",
    "grand total",
    "subtotal",
    "net payable",
    "total claimed",
    "amount claimed",
    "claim amount",
    "claim requested",
    "requested amount",
    "procedure code",
    "diagnosis code",
    "code",
)

_NON_EXPENSE_ROW_KEYWORDS = {
    "claim",
    "claims",
    "policy",
    "payer",
    "premium",
    "deductible",
    "risk factor",
    "member id",
    "policy number",
    "insurance",
    "sum insured",
    "previous claims",
    "claim vs sum insured",
    "amount exceeding policy",
    "icd-10",
    "snomed",
    "diagnosis count",
    "ward type",
    "admission type",
    "policy status",
    "patient name",
    "age/gender",
    "admission date",
    "discharge date",
    "consultant",
    "uhid",
    "hospital",
    "diagnosis",
    "code",
    "claim(s)",
}


def _join_region_text(tokens: Iterable[Any]) -> str:
    parts = []
    for token in tokens:
        text = getattr(token, "text", None) if not isinstance(token, dict) else token.get("text")
        if text and str(text).strip():
            parts.append(str(text).strip())
    return " ".join(parts).strip()


def _token_payloads(tokens: Iterable[Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for token in tokens:
        if isinstance(token, dict):
            payloads.append({
                "text": token.get("text", ""),
                "x0": float(token.get("x0", 0.0)),
                "y0": float(token.get("y0", 0.0)),
                "x1": float(token.get("x1", 0.0)),
                "y1": float(token.get("y1", 0.0)),
                "page": int(token.get("page", 1)),
                "document_id": token.get("document_id"),
                "claim_id": token.get("claim_id"),
            })
        else:
            payloads.append({
                "text": getattr(token, "text", ""),
                "x0": float(getattr(token, "x0", 0.0)),
                "y0": float(getattr(token, "y0", 0.0)),
                "x1": float(getattr(token, "x1", 0.0)),
                "y1": float(getattr(token, "y1", 0.0)),
                "page": int(getattr(token, "page", 1)),
                "document_id": getattr(token, "document_id", None),
                "claim_id": getattr(token, "claim_id", None),
            })
    return payloads


def _crop_region_image(page_image: Image.Image | None, bbox: list[float] | None) -> Image.Image | None:
    if page_image is None or not bbox or len(bbox) != 4:
        return None

    left, top, right, bottom = bbox
    left = max(0, int(left) - 8)
    top = max(0, int(top) - 8)
    right = min(page_image.width, int(right) + 8)
    bottom = min(page_image.height, int(bottom) + 8)
    if right <= left or bottom <= top:
        return None
    return page_image.crop((left, top, right, bottom))


def _row_cells_payload(table: TableRegion) -> list[list[dict[str, Any]]]:
    payload: list[list[dict[str, Any]]] = []
    for row in table.rows:
        row_payload = []
        for cell in row.cells:
            row_payload.append({
                "text": cell.text,
                "bbox": cell.bbox,
                "tokens": [token.model_dump() if hasattr(token, "model_dump") else token for token in (cell.tokens or [])],
                "column_id": cell.column_id,
                "row_id": cell.row_id,
                "cell_id": cell.cell_id,
                "token_count": cell.token_count,
            })
        payload.append(row_payload)
    return payload


def _table_text_payload(table: TableRegion) -> str:
    parts: list[str] = []
    for row in table.rows:
        for cell in row.cells:
            text = (cell.text or "").strip()
            if text:
                parts.append(text)
    return " ".join(parts).strip()


def _table_tokens_payload(table: TableRegion) -> list[dict[str, Any]]:
    tokens: list[dict[str, Any]] = []
    for row in table.rows:
        for cell in row.cells:
            for token in cell.tokens or []:
                if hasattr(token, "model_dump"):
                    tokens.append(token.model_dump())
                elif isinstance(token, dict):
                    tokens.append(token)
    return tokens


def _table_to_semantic_rows(table: SemanticTableOutput) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in table.rows:
        row_data = dict(row.cells or {})
        row_data["row_index"] = row.row_index
        row_data["confidence"] = row.confidence
        rows.append(row_data)
    return rows


def _table_to_expenses(table: SemanticTableOutput, source_page: int | None) -> list[dict[str, Any]]:
    """Convert LLM-extracted expense table to standardized expense items.
    
    The LLM now returns pre-standardized expense rows with:
    - category: Expense category (ICU, Room, Surgery, Pharmacy, etc.)
    - description: Full description of the expense
    - amount: Numeric amount (already calculated and deduplicated by LLM)
    
    This function just validates and formats the data for the report.
    """
    expenses: list[dict[str, Any]] = []
    
    # Skip non-expense tables
    if table.table_kind not in SEMANTIC_EXPENSE_TABLE_KINDS:
        return expenses
    
    # Track seen expenses to avoid duplicates without collapsing distinct line items
    # that happen to share the same category or amount.
    seen_expense_keys = set()
    
    for row in table.rows:
        cells = row.cells or {}
        
        # Extract standardized fields from LLM
        category = str(cells.get("category") or table.table_kind or "Miscellaneous").strip()
        description = str(cells.get("description") or cells.get("desc") or cells.get("item") or "").strip()
        amount = cells.get("amount")
        normalized_description = description.lower().strip()
        normalized_category = category.lower().strip()

        # Structural guardrail: reject rows that are clearly metadata, labels,
        # or summary rows even if the model marked them as expenses.
        if not description or any(
            normalized_description.startswith(prefix) or prefix in normalized_description
            for prefix in _NON_EXPENSE_ROW_PREFIXES
        ):
            logger.debug(f"[EXPENSE_FILTER] Skipping summary/label row: {category} - {description}")
            continue

        if any(keyword in normalized_category or keyword in normalized_description for keyword in _NON_EXPENSE_ROW_KEYWORDS):
            logger.debug(f"[EXPENSE_FILTER] Skipping non-expense row: {category} - {description}")
            continue
        
        if not amount or not description:
            continue
        
        amount_text = str(amount).strip()
        
        # Parse amount - LLM should already provide clean numeric values
        # But handle cases where there might still be currency symbols
        try:
            # Remove common currency symbols and commas
            cleaned = amount_text.replace("Rs.", "").replace("₹", "").replace(",", "").strip()
            amount_numeric = float(cleaned)
        except (ValueError, AttributeError):
            continue
        
        if amount_numeric <= 0:
            continue
        
        # Deduplicate on description + amount so we keep separate services
        # even if the semantic model assigns the same category to both.
        expense_key = (category.lower(), description.lower(), amount_numeric)
        if expense_key in seen_expense_keys:
            logger.debug(f"[EXPENSE_DEDUP] Skipping duplicate: {description} - Rs. {amount_numeric}")
            continue
        seen_expense_keys.add(expense_key)
        
        # Standardized expense format for report
        expenses.append({
            "description": description,
            "amount": str(amount_numeric),  # Keep as string for JSON consistency
            "category": category,
            "page": source_page,
            "source_region_id": table.source_region_id,
            "source_region_type": table.source_region_type,
            "model_name": table.model_name,
            "confidence": row.confidence or table.confidence,
        })
        
        logger.info(f"[EXPENSE] {category}: {description} - Rs. {amount_numeric}")
    
    return expenses


def _is_expense_like_table_payload(table: TableRegion) -> bool:
    rows = list(getattr(table, "rows", []) or [])
    if len(rows) < 2:
        return False

    def _looks_numeric(text: str) -> bool:
        s = str(text or "").strip().lower()
        if not s:
            return False
        s = s.replace("₹", "").replace("rs.", "").replace("rs", "").replace("inr", "")
        s = s.replace(",", "").replace(" ", "")
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", s))

    header_text = " ".join((cell.text or "") for cell in rows[0].cells).lower()
    has_expense_header = any(
        kw in header_text
        for kw in ["description", "particular", "item", "qty", "rate", "gross", "payable", "amount", "np", "charges"]
    )

    data_rows = rows[1:] if len(rows) > 1 else rows
    if not data_rows:
        return False

    amount_like_rows = 0
    for row in data_rows:
        cells = [c for c in row.cells if str(c.text or "").strip()]
        if not cells:
            continue
        tail = cells[-3:] if len(cells) >= 3 else cells
        numeric_tail = sum(1 for cell in tail if _looks_numeric(cell.text))
        if numeric_tail >= 2:
            amount_like_rows += 1

    tail_ratio = amount_like_rows / max(1, len(data_rows))
    return has_expense_header and tail_ratio >= 0.4


def _fallback_semantic_expense_table(table: TableRegion, source_region_type: str, model_name: str) -> SemanticTableOutput | None:
    # Bridge path when backend returns empty/invalid output for a table that is
    # clearly expense-like: convert normalized table rows to semantic row schema.
    fallback_rows = normalize_tables([table]) or []
    if not fallback_rows:
        return None

    semantic_rows: list[SemanticTableRowOutput] = []
    for idx, row in enumerate(fallback_rows):
        description = str(row.get("field_name") or row.get("description") or "").strip()
        amount = row.get("payable_amount") or row.get("amount")
        if not description or amount in {None, ""}:
            continue
        semantic_rows.append(
            SemanticTableRowOutput(
                row_index=idx,
                cells={
                    "category": str(row.get("category") or "Miscellaneous").strip(),
                    "description": description,
                    "amount": str(amount).strip(),
                },
                confidence=0.55,
            )
        )

    if not semantic_rows:
        return None

    return SemanticTableOutput(
        table_kind="expenses",
        confidence=0.55,
        source_region_id=table.region_id,
        source_region_type=source_region_type,
        source_tokens=_table_tokens_payload(table),
        headers=["category", "description", "amount"],
        rows=semantic_rows,
        model_name=model_name,
        metadata={"source": "expense_fallback_bridge"},
    )


def _is_patient_form_table(table: TableRegion) -> bool:
    """Detect if a table is actually a patient information form, not an expense/medical data table.
    
    Patient forms typically have:
    - Rows with label:value pairs (Patient:, Age/Sex:, DOA:, DOD:, etc.)
    - First column contains form labels, second column contains values
    - First cell often contains keywords like "Patient", "DOB", "Gender", "Address", "Policy", etc.
    """
    if not table.rows or len(table.rows) < 2:
        return False
    
    # Sample first few cells to check for form-like patterns
    PATIENT_FORM_KEYWORDS = {
        "patient",
        "date of birth",
        "dob",
        "gender",
        "sex",
        "age",
        "address",
        "phone",
        "email",
        "admission",
        "discharge",
        "doa",
        "dod",
        "ward",
        "los",
        "consultant",
        "doctor",
        "hospital",
        "insurance",
        "policy",
        "member id",
        "uhid",
        "ip no",
    }
    
    form_keyword_count = 0
    for row in table.rows[:5]:  # Check first 5 rows
        for cell in row.cells:
            text = (cell.text or "").strip().lower()
            if text in PATIENT_FORM_KEYWORDS:
                form_keyword_count += 1
    
    # If 3+ form keywords found in first 5 rows, it's likely a patient form
    if form_keyword_count >= 3:
        logger.debug(f"[TABLE_FILTER] Skipping patient form table (region_id={table.region_id}): found {form_keyword_count} form keywords")
        return True
    
    return False


def extract_semantics(
    doc: DocumentStructure,
    page_images: dict[int, Image.Image] | None = None,
    debug_dir: str | None = None,
    claim_id: str | None = None,
) -> SemanticDocumentOutput:
    """Run region-first semantic extraction over isolated regions and reconstructed tables."""
    registry = SemanticBackendRegistry()
    backend = registry.choose()

    output = SemanticDocumentOutput(model_name=getattr(backend, "name", None))
    region_outputs: list[SemanticRegionOutput] = []
    semantic_fields: list[SemanticFieldOutput] = []
    classified_tables: list[SemanticTableOutput] = []
    model_predictions: list[dict[str, Any]] = []
    semantic_field_mapping: dict[str, Any] = {}
    semantic_table_mapping: dict[str, Any] = {}
    expenses: list[dict[str, Any]] = []

    region_by_id = {region.region_id: region for region in doc.regions}

    def _analyze_region(region: Region, table: TableRegion | None = None) -> None:
        if backend is None:
            model_predictions.append({
                "region_id": region.region_id,
                "page": region.page,
                "region_type": region.region_type,
                "model_name": None,
                "available": False,
                "reason": "No semantic backend available",
            })
            return

        # Privacy boundary: only expense-style table regions are sent to the LLM.
        # All other fields are extracted locally so patient / hospital / diagnosis
        # text never leaves the backend.
        if table is None:
            return

        page_image = page_images.get(region.page) if page_images else None
        crop = _crop_region_image(page_image, region.bbox)
        region_text = _table_text_payload(table)
        region_tokens = _table_tokens_payload(table)
        table_kind_hint = str(getattr(table, "table_kind", "") or "").lower()
        request_region_type = (
            "expense_table"
            if table_kind_hint in SEMANTIC_EXPENSE_TABLE_KINDS or _is_expense_like_table_payload(table)
            else region.region_type
        )
        request = SemanticRequest(
            region_id=region.region_id,
            region_type=request_region_type,
            page=region.page,
            document_id=region.document_id,
            claim_id=region.claim_id or claim_id,
            text=region_text,
            tokens=region_tokens,
            table_cells=_row_cells_payload(table),
            image=crop,
            bbox=region.bbox,
        )

        prediction = backend.analyze(request)
        model_predictions.append({
            "region_id": region.region_id,
            "page": region.page,
            "region_type": region.region_type,
            "model_name": getattr(backend, "name", None),
            "available": True,
            "prediction": prediction,
        })

        if not prediction:
            if table and (table_kind_hint in SEMANTIC_EXPENSE_TABLE_KINDS or _is_expense_like_table_payload(table)):
                fallback_table = _fallback_semantic_expense_table(table, source_region_type=request_region_type, model_name="heuristic-expense-bridge")
                if fallback_table is not None:
                    fallback_region = SemanticRegionOutput(
                        region_id=region.region_id,
                        region_type=request_region_type,
                        semantic_type=request_region_type,
                        confidence=0.55,
                        source_page=region.page,
                        document_id=region.document_id,
                        claim_id=region.claim_id or claim_id,
                        source_tokens=[],
                        fields=[],
                        tables=[fallback_table],
                        model_name="heuristic-expense-bridge",
                        notes="semantic backend returned empty output; used expense fallback bridge",
                        metadata={"source": "expense_fallback_bridge"},
                    )
                    region_outputs.append(fallback_region)
                    classified_tables.append(fallback_table)
            return

        try:
            region_output = SemanticRegionOutput.model_validate(prediction)
        except Exception:
            region_output = SemanticRegionOutput(
                region_id=str(prediction.get("region_id") or region.region_id),
                region_type=str(prediction.get("region_type") or region.region_type),
                semantic_type=str(prediction.get("semantic_type") or prediction.get("region_type") or region.region_type),
                confidence=float(prediction.get("confidence") or 0.0),
                source_page=region.page,
                document_id=region.document_id,
                claim_id=region.claim_id or claim_id,
                source_tokens=[SemanticFieldOutput.model_validate(tok) for tok in []],
                model_name=prediction.get("model_name") or getattr(backend, "name", None),
                notes=prediction.get("notes"),
                metadata=prediction,
            )
            for field_item in prediction.get("fields", []) or []:
                try:
                    region_output.fields.append(SemanticFieldOutput.model_validate(field_item))
                except Exception:
                    continue
            for table_item in prediction.get("tables", []) or []:
                try:
                    region_output.tables.append(SemanticTableOutput.model_validate(table_item))
                except Exception:
                    continue

        region_outputs.append(region_output)
        if table and not region_output.tables and (table_kind_hint in SEMANTIC_EXPENSE_TABLE_KINDS or _is_expense_like_table_payload(table)):
            fallback_table = _fallback_semantic_expense_table(table, source_region_type=request_region_type, model_name="heuristic-expense-bridge")
            if fallback_table is not None:
                region_output.tables.append(fallback_table)
                region_output.notes = (region_output.notes or "") + " | added expense fallback bridge table"
        semantic_fields.extend(region_output.fields)
        classified_tables.extend(region_output.tables)

    # Process reconstructed tables first so semantic interpretation sees structure.
    for table in doc.tables:
        # Skip patient form tables — they should not be sent to LLM for semantic analysis
        # (to protect PHI and avoid misclassification as expense tables)
        if _is_patient_form_table(table):
            logger.info(f"[TABLE_FILTER] Skipping patient form table (region_id={table.region_id})")
            continue

        # Coerce generic/misclassified tables that look like billing tables so
        # LLM gets the correct expense-table context and schema.
        table_kind = str(getattr(table, "table_kind", "") or "").lower()
        if table_kind not in SEMANTIC_EXPENSE_TABLE_KINDS and _is_expense_like_table_payload(table):
            table.table_kind = "expenses"
            if table.region_id in region_by_id:
                region_by_id[table.region_id].region_type = "expense_table"
            logger.info("[SEMANTIC_COERCE] Promoted table region_id=%s to expenses for LLM", table.region_id)
        
        region = region_by_id.get(table.region_id)
        if not region:
            region = Region(
                region_id=table.region_id,
                region_type="table",
                bbox=table.bbox,
                tokens=[],
                page=table.page,
                confidence=table.confidence,
                model_name=table.model_name,
            )
        _analyze_region(region, table=table)

    # Then process remaining non-table regions.
    for region in doc.regions:
        if region.region_type in {"table", "expense_table"}:
            continue
        _analyze_region(region)

    # Semantic tables should create canonical expenses, medications, labs, and diagnosis tables.
    semantic_expenses: list[dict[str, Any]] = []
    semantic_medications: list[dict[str, Any]] = []
    semantic_labs: list[dict[str, Any]] = []
    semantic_diagnoses: list[dict[str, Any]] = []

    for table in classified_tables:
        semantic_table_mapping.setdefault(table.table_kind, []).append(table.model_dump())
        source_page = None
        if table.source_region_id and table.source_region_id in region_by_id:
            source_page = region_by_id[table.source_region_id].page

        if table.table_kind in SEMANTIC_EXPENSE_TABLE_KINDS:
            semantic_expenses.extend(_table_to_expenses(table, source_page))
        elif table.table_kind == "medications":
            semantic_medications.extend(_table_to_semantic_rows(table))
        elif table.table_kind == "lab_results":
            semantic_labs.extend(_table_to_semantic_rows(table))
        elif table.table_kind == "diagnoses":
            semantic_diagnoses.extend(_table_to_semantic_rows(table))

    # Build a compact field map with best-confidence values.
    for field in semantic_fields:
        current = semantic_field_mapping.get(field.canonical_field)
        candidate = field.model_dump()
        if not current or float(candidate.get("confidence") or 0.0) > float(current.get("confidence") or 0.0):
            semantic_field_mapping[field.canonical_field] = candidate

    output.model_predictions = model_predictions
    output.semantic_regions = region_outputs
    output.semantic_fields = semantic_fields
    output.classified_tables = classified_tables
    output.semantic_field_mapping = semantic_field_mapping
    output.semantic_table_mapping = semantic_table_mapping

    if debug_dir and settings.semantic_debug_enabled:
        dump_dir = Path(debug_dir)
        dump_dir.mkdir(parents=True, exist_ok=True)
        (dump_dir / "semantic_region_outputs.json").write_text(
            json.dumps([region.model_dump() for region in region_outputs], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (dump_dir / "model_predictions.json").write_text(
            json.dumps(model_predictions, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (dump_dir / "classified_tables.json").write_text(
            json.dumps([table.model_dump() for table in classified_tables], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (dump_dir / "semantic_field_mapping.json").write_text(
            json.dumps(semantic_field_mapping, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # If semantic extraction failed or no backend was available, fall back to the
    # existing normalized outputs to keep the runtime usable. The semantic outputs
    # remain the primary path.
    if not semantic_fields:
        output.semantic_fields = []
    if not classified_tables and not semantic_expenses:
        output.errors.append("No semantic backend output produced; fallback required")

    # Attach fallback-derived outputs for callers that want a complete payload.
    output.classified_tables = classified_tables
    if semantic_expenses:
        expenses = semantic_expenses
        output.semantic_table_mapping.setdefault("expenses", [])

    # Expose the extracted line items and summary rows in a model-friendly way.
    if semantic_medications:
        output.semantic_table_mapping.setdefault("medications", semantic_medications)
    if semantic_labs:
        output.semantic_table_mapping.setdefault("lab_results", semantic_labs)
    if semantic_diagnoses:
        output.semantic_table_mapping.setdefault("diagnoses", semantic_diagnoses)

    # Record extracted expenses in the output metadata for pipeline consumers.
    output.semantic_table_mapping.setdefault("expense_line_items", expenses)

    return output
