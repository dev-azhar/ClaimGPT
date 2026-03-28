"""
Advanced document parsing engine — deep structured extraction for medical claims.

Strategy:
  1. **LayoutLMv3** (microsoft/layoutlmv3-base) for structured field extraction
     using token classification on document images + OCR text.
  2. **Advanced heuristic** fallback with 40+ regex patterns covering:
     - Patient demographics (name, DOB, gender, age, address, phone, email)
     - Insurance details (policy, member ID, group, insurer, TPA)
     - Clinical data (diagnosis, ICD-10, procedures, CPT, medications, allergies)
     - Billing (line items, totals, dates of service, room charges)
     - Provider/facility info (hospital, doctor, registration/discharge dates)
     - Discharge summary sections (chief complaint, history, findings, plan)
  3. **Smart table parsing** with header detection and column alignment.
  4. **Amount normalization** (INR/USD, commas, decimals).
  5. **Section detection** for discharge summaries and medical reports.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from .config import settings

logger = logging.getLogger("parser.engine")

# ------------------------------------------------------------------
# Lazy-loaded model singleton
# ------------------------------------------------------------------
_model = None
_processor = None
_tokenizer = None
_model_version: Optional[str] = None
_model_load_attempted = False


def _load_model() -> bool:
    """Attempt to load LayoutLMv3 model + processor.  Returns True on success."""
    global _model, _processor, _tokenizer, _model_version, _model_load_attempted
    if _model_load_attempted:
        return _model is not None
    _model_load_attempted = True

    try:
        import torch  # noqa: F401
        from transformers import (
            LayoutLMv3ForTokenClassification,
            LayoutLMv3Processor,
            LayoutLMv3TokenizerFast,
        )

        model_id = settings.layoutlm_model
        logger.info("Loading LayoutLMv3 model: %s", model_id)

        _tokenizer = LayoutLMv3TokenizerFast.from_pretrained(model_id)
        _processor = LayoutLMv3Processor.from_pretrained(
            model_id, apply_ocr=False, tokenizer=_tokenizer,
        )
        _model = LayoutLMv3ForTokenClassification.from_pretrained(model_id)
        _model.eval()
        _model_version = model_id

        n_labels = _model.config.num_labels
        logger.info(
            "LayoutLMv3 loaded — %d token-classification labels, device=cpu",
            n_labels,
        )
        return True

    except ImportError:
        logger.warning(
            "transformers / torch not installed — will use heuristic fallback"
        )
        return False
    except Exception:
        logger.warning(
            "Could not load LayoutLMv3 model '%s' — will use heuristic fallback",
            settings.layoutlm_model,
            exc_info=True,
        )
        return False


# ------------------------------------------------------------------
# Data types
# ------------------------------------------------------------------

@dataclass
class FieldResult:
    field_name: str
    field_value: Optional[str] = None
    bounding_box: Optional[Dict[str, Any]] = None
    source_page: Optional[int] = None
    model_version: Optional[str] = None


@dataclass
class ParseOutput:
    fields: List[FieldResult] = field(default_factory=list)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    sections: List[Dict[str, Any]] = field(default_factory=list)
    model_version: Optional[str] = None
    used_fallback: bool = False


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def parse_document(
    ocr_pages: List[Dict[str, Any]],
    images: Optional[List[Image.Image]] = None,
) -> ParseOutput:
    """
    Parse structured fields from OCR text (and optionally page images).

    Parameters
    ----------
    ocr_pages : list of dicts with keys ``page_number``, ``text``
    images    : optional list of PIL Images (one per page) for LayoutLM

    Returns
    -------
    ParseOutput with extracted fields, tables, sections, model version, fallback flag.
    """
    if images and _load_model():
        try:
            return _extract_with_model(ocr_pages, images)
        except Exception:
            logger.exception("Model inference failed — falling back to heuristic")

    if settings.use_heuristic_fallback:
        return _extract_with_heuristic(ocr_pages)

    return ParseOutput(used_fallback=True)


# ------------------------------------------------------------------
# Model-based extraction (LayoutLMv3)
# ------------------------------------------------------------------

def _extract_with_model(
    ocr_pages: List[Dict[str, Any]],
    images: List[Image.Image],
) -> ParseOutput:
    import torch

    all_fields: List[FieldResult] = []

    for page_info, img in zip(ocr_pages, images):
        page_num = page_info.get("page_number", 1)
        text = page_info.get("text", "")
        words = text.split()
        if not words:
            continue

        word_boxes = page_info.get("word_boxes")
        if word_boxes and len(word_boxes) == len(words):
            boxes = word_boxes
        else:
            n = len(words)
            boxes = [
                [0, int(1000 * i / n), 1000, int(1000 * (i + 1) / n)]
                for i in range(n)
            ]

        encoding = _processor(
            img,
            words,
            boxes=boxes,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )

        with torch.no_grad():
            outputs = _model(**encoding)

        predictions = outputs.logits.argmax(-1).squeeze().tolist()
        if isinstance(predictions, int):
            predictions = [predictions]

        id2label = _model.config.id2label
        for word, pred in zip(words, predictions):
            label = id2label.get(pred, "O")
            if label != "O":
                all_fields.append(
                    FieldResult(
                        field_name=label,
                        field_value=word,
                        source_page=page_num,
                        model_version=_model_version,
                    )
                )

    return ParseOutput(
        fields=all_fields,
        model_version=_model_version,
        used_fallback=False,
    )


# ------------------------------------------------------------------
# Advanced heuristic extraction
# ------------------------------------------------------------------

# ---- Patient demographics ----
_PAT_PATIENT_NAME = re.compile(
    r"(?:patient\s*(?:'s\s*)?name|name\s*of\s*(?:the\s*)?patient|pt\s*name)\s*[:\-]?\s*(.+)", re.I
)
_PAT_DOB = re.compile(
    r"(?:date\s*of\s*birth|dob|d\.o\.b|birth\s*date)\s*[:\-]?\s*([\d/\-\.]+(?:\s*\w+\s*\d{4})?)", re.I
)
_PAT_AGE = re.compile(
    r"(?:age|patient\s*age)\s*[/:\-]?\s*(?:gender\s*[/:\-]?\s*)?(\d{1,3})\s*(?:years?|yrs?|y)?", re.I
)
_PAT_GENDER = re.compile(
    r"(?:gender|sex|age\s*/\s*gender)\s*[:\-]?\s*(?:\d{1,3}\s*[/\-]\s*)?(male|female|m|f|other|transgender)", re.I
)
_PAT_ADDRESS = re.compile(
    r"(?:address|patient\s*address|residential\s*address)\s*[:\-]?\s*(.+)", re.I
)
_PAT_PHONE = re.compile(
    r"(?:phone|mobile|contact\s*(?:no|number)|tel)\s*[:\-]?\s*([\d\+\-\(\)\s]{7,15})", re.I
)
_PAT_EMAIL = re.compile(
    r"(?:email|e-mail)\s*[:\-]?\s*([\w\.\-]+@[\w\.\-]+\.\w+)", re.I
)
_PAT_PATIENT_ID = re.compile(
    r"(?:patient\s*id|patient\s*no|uhid|mr\s*no|mrd\s*no|ipd\s*no)\s*[:\-]?\s*([\w\-/]+)", re.I
)
_PAT_SECONDARY_DIAG = re.compile(
    r"(?:secondary\s*diagnosis|additional\s*diagnosis|co-?morbid(?:ity|ities)?)\s*[:\-]?\s*(.+)", re.I
)

# ---- Insurance / policy ----
_PAT_POLICY = re.compile(
    r"(?:policy\s*(?:no|number|#|id)|insurance\s*(?:no|number|id)|health\s*id)\s*[:\-]?\s*([\w\-/]+)", re.I
)
_PAT_CLAIM_NO = re.compile(
    r"(?:claim\s*(?:no|number|#|id|ref)|reference\s*(?:no|number))\s*[:\-]?\s*([\w\-/]+)", re.I
)
_PAT_MEMBER_ID = re.compile(
    r"(?:member\s*(?:id|no|number|#)|uhid|mr\s*(?:no|number)|mrd\s*(?:no|number)|ipd\s*(?:no|number))\s*[:\-]?\s*([\w\-/]+)", re.I
)
_PAT_GROUP = re.compile(
    r"(?:group\s*(?:no|number|#|id)|corp(?:orate)?\s*(?:id|no))\s*[:\-]?\s*([\w\-/]+)", re.I
)
_PAT_INSURER = re.compile(
    r"(?:insurer|insurance\s*(?:company|carrier|provider)|payer|tpa|third\s*party)\s*[:\-]?\s*(.+)", re.I
)

# ---- Clinical / diagnosis ----
_PAT_DIAGNOSIS = re.compile(
    r"^(?:(?:primary|secondary|principal|final|provisional|admitting|discharge)\s+)?diagnosis\s*[:\-]\s*(.+)", re.I | re.M
)
_PAT_ICD_CODE = re.compile(r"\b([A-TV-Z]\d{2}(?:\.\d{1,4})?)\b")
_PAT_PROCEDURE = re.compile(
    r"(?:procedure\s*performed|procedure(?:s)?|surgical?\s*procedure|operation\s*performed|cpt)\s*[:\-]?\s*(.+)", re.I
)
_PAT_CPT_CODE = re.compile(r"\b(\d{5})\b")
_PAT_MEDICATION = re.compile(
    r"^(?:medication(?:s)?|medicine(?:s)?|drug(?:s)?|prescription|rx)\s*[:\-]\s*(.+)", re.I | re.M
)
_PAT_ALLERGY = re.compile(
    r"(?:allerg(?:y|ies)|known\s*allerg(?:y|ies)|drug\s*allerg(?:y|ies))\s*[:\-]?\s*(.+)", re.I
)
_PAT_CHIEF_COMPLAINT = re.compile(
    r"(?:chief\s*complaint|presenting\s*complaint|reason\s*for\s*(?:admission|visit)|c/c)\s*[:\-]?\s*(.+)", re.I
)
_PAT_HISTORY = re.compile(
    r"(?:history\s*of\s*present\s*illness|hpi|brief\s*history|clinical\s*history)\s*[:\-]?\s*(.+)", re.I
)

# ---- Financial / billing ----
_PAT_TOTAL_AMOUNT = re.compile(
    r"(?:total\s*(?:amount|charge|cost|billed|bill|payable|hospital\s*expenses|claimed\s*amount)|grand\s*total|net\s*(?:amount|payable)|amount\s*(?:payable|claimed))\s*[:\-]?\s*(?:(?:rs|inr|usd|\$|₹)\.?\s*)?\w?([\d,]+\.?\d*)", re.I
)
_PAT_ROOM_CHARGE = re.compile(
    r"(?:room\s*(?:charges?|rent|rate)|bed\s*charges?|room\s*&?\s*board)\s*(?:\([^)]*\))?\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_CONSULTATION = re.compile(
    r"(?:consultation\s*(?:charges?|fees?)|doctor(?:'s)?\s*(?:fees?|charges?)|physician\s*(?:fees?|charges?))\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_PHARMACY = re.compile(
    r"(?:pharmacy|pharma\s*(?:charges?|cost)|medicines?\s*(?:&\s*(?:consumables?|surgical)|charges?|cost)|drug\s*(?:charges?|cost))\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_INVESTIGATION = re.compile(
    r"(?:investigations?|lab(?:oratory)?\s*(?:charges?|cost)|diagnostics?\s*(?:&\s*investigations?|charges?|cost)?|pathology|radiology)\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_SURGERY_CHARGE = re.compile(
    r"(?:surgery\s*(?:charges?|cost|fees?)|surgical?\s*(?:charges?|fees?))\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_SURGEON_FEE = re.compile(
    r"(?:surgeon(?:'s)?\s*(?:&\s*professional\s*)?(?:fees?|charges?)|surgeon\s*fees?|professional\s*fees?)\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_ANAESTHESIA = re.compile(
    r"(?:an(?:ae|e)sthes(?:ia|ist)\s*(?:charges?|fees?)|an(?:ae|e)sthesia)\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_OT_CHARGE = re.compile(
    r"(?:ot\s*charges?|operation\s*theat(?:re|er)\s*(?:charges?)?|theatre\s*charges?)\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_CONSUMABLES = re.compile(
    r"(?:(?:medical\s*(?:&\s*)?)?(?:surgical\s*)?consumables?|implants?\s*(?:&\s*consumables?)?|disposables?)\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_NURSING = re.compile(
    r"(?:nursing\s*(?:&\s*(?:support|hospital)\s*(?:services?|charges?)|charges?|fees?)|nurse\s*charges?)\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_ICU_CHARGE = re.compile(
    r"(?:icu\s*(?:charges?|rent|cost)|intensive\s*care\s*(?:charges?|cost))\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_AMBULANCE = re.compile(
    r"(?:ambulance\s*(?:charges?|cost|fees?))\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)
_PAT_MISC_CHARGE = re.compile(
    r"(?:miscellaneous|misc\.?\s*charges?|other\s*(?:charges?|expenses?)|sundry)\s*[:\-]?\s*(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", re.I
)

# ---- Provider / facility ----
_PAT_HOSPITAL = re.compile(
    r"(?:hospital|facility|clinic|medical\s*(?:centre|center)|nursing\s*home)\s*name\s*[:\-]\s*(.+)", re.I
)
_PAT_DOCTOR = re.compile(
    r"(?:(?:treating|attending|consulting)\s*(?:doctor|physician)|dr\.?\s*name|doctor\s*(?:name)?|physician)\s*[:\-]?\s*(.+)", re.I
)
_PAT_REG_NO = re.compile(
    r"(?:registration\s*(?:no|number)|reg\.?\s*(?:no|number|#))\s*[:\-]?\s*([\w\-/]+)", re.I
)

# ---- Dates ----
_PAT_ADMISSION_DATE = re.compile(
    r"(?:date\s*of\s*admission|admission\s*date|admitted\s*on|doa)\s*[:\-]?\s*(\d{1,2}[\-/\.]\w{3,9}[\-/\.]\d{2,4}|\d{1,2}[\-/\.]\d{1,2}[\-/\.]\d{2,4}|\w+\s+\d{1,2},?\s*\d{4})", re.I
)
_PAT_DISCHARGE_DATE = re.compile(
    r"(?:date\s*of\s*discharge|discharge\s*date|discharged\s*on|dod)\s*[:\-]?\s*(\d{1,2}[\-/\.]\w{3,9}[\-/\.]\d{2,4}|\d{1,2}[\-/\.]\d{1,2}[\-/\.]\d{2,4}|\w+\s+\d{1,2},?\s*\d{4})", re.I
)
_PAT_SERVICE_DATE = re.compile(
    r"(?:date\s*of\s*service|service\s*date|dos|bill\s*date|invoice\s*date)\s*[:\-]?\s*(\d{1,2}[\-/\.]\w{3,9}[\-/\.]\d{2,4}|\d{1,2}[\-/\.]\d{1,2}[\-/\.]\d{2,4}|\w+\s+\d{1,2},?\s*\d{4})", re.I
)

# ---- Vitals ----
_PAT_BLOOD_PRESSURE = re.compile(
    r"(?:blood\s*pressure|bp|b\.p)\s*[:\-]?\s*(\d{2,3}\s*/\s*\d{2,3})", re.I
)
_PAT_PULSE = re.compile(
    r"(?:pulse|heart\s*rate|hr)\s*[:\-]?\s*(\d{2,3})\s*(?:/min|bpm)?", re.I
)
_PAT_TEMPERATURE = re.compile(
    r"(?:temperature|temp)\s*[:\-]?\s*(\d{2,3}\.?\d*)\s*(?:°?[FCfc]|deg)?", re.I
)
_PAT_SPO2 = re.compile(
    r"(?:spo2|sp02|oxygen\s*saturation|o2\s*sat)\s*[:\-]?\s*(\d{2,3})%?", re.I
)

# Consolidated pattern list for iteration
_PATTERNS: List[tuple[str, "re.Pattern[str]"]] = [
    # Demographics
    ("patient_name", _PAT_PATIENT_NAME),
    ("date_of_birth", _PAT_DOB),
    ("age", _PAT_AGE),
    ("gender", _PAT_GENDER),
    ("address", _PAT_ADDRESS),
    ("phone", _PAT_PHONE),
    ("email", _PAT_EMAIL),
    ("patient_id", _PAT_PATIENT_ID),
    ("secondary_diagnosis", _PAT_SECONDARY_DIAG),
    # Insurance
    ("policy_number", _PAT_POLICY),
    ("claim_number", _PAT_CLAIM_NO),
    ("member_id", _PAT_MEMBER_ID),
    ("group_number", _PAT_GROUP),
    ("insurer", _PAT_INSURER),
    # Clinical
    ("diagnosis", _PAT_DIAGNOSIS),
    ("icd_code", _PAT_ICD_CODE),
    ("procedure", _PAT_PROCEDURE),
    ("cpt_code", _PAT_CPT_CODE),
    ("medication", _PAT_MEDICATION),
    ("allergy", _PAT_ALLERGY),
    ("chief_complaint", _PAT_CHIEF_COMPLAINT),
    ("history_of_present_illness", _PAT_HISTORY),
    # Financial (order matters: more specific patterns first)
    ("total_amount", _PAT_TOTAL_AMOUNT),
    ("surgeon_fees", _PAT_SURGEON_FEE),
    ("anaesthesia_charges", _PAT_ANAESTHESIA),
    ("ot_charges", _PAT_OT_CHARGE),
    ("surgery_charges", _PAT_SURGERY_CHARGE),
    ("consumables", _PAT_CONSUMABLES),
    ("room_charges", _PAT_ROOM_CHARGE),
    ("consultation_charges", _PAT_CONSULTATION),
    ("pharmacy_charges", _PAT_PHARMACY),
    ("investigation_charges", _PAT_INVESTIGATION),
    ("nursing_charges", _PAT_NURSING),
    ("icu_charges", _PAT_ICU_CHARGE),
    ("ambulance_charges", _PAT_AMBULANCE),
    ("misc_charges", _PAT_MISC_CHARGE),
    # Provider
    ("hospital_name", _PAT_HOSPITAL),
    ("doctor_name", _PAT_DOCTOR),
    ("registration_number", _PAT_REG_NO),
    # Dates
    ("admission_date", _PAT_ADMISSION_DATE),
    ("discharge_date", _PAT_DISCHARGE_DATE),
    ("service_date", _PAT_SERVICE_DATE),
    # Vitals
    ("blood_pressure", _PAT_BLOOD_PRESSURE),
    ("pulse", _PAT_PULSE),
    ("temperature", _PAT_TEMPERATURE),
    ("spo2", _PAT_SPO2),
]


# ---- Section detection for discharge summaries ----
_SECTION_PATTERNS: List[tuple[str, "re.Pattern[str]"]] = [
    ("chief_complaint", re.compile(r"^(?:chief\s*complaint|presenting\s*complaint|c/c|reason\s*for\s*(?:admission|visit))\s*[:\-]?", re.I | re.M)),
    ("history_of_present_illness", re.compile(r"^(?:history\s*of\s*present\s*illness|hpi|brief\s*history|clinical\s*history)\s*[:\-]?", re.I | re.M)),
    ("past_medical_history", re.compile(r"^(?:past\s*(?:medical\s*)?history|pmh|past\s*illness)\s*[:\-]?", re.I | re.M)),
    ("examination_findings", re.compile(r"^(?:(?:on\s*)?examination|physical\s*examination|clinical\s*findings|general\s*examination|systemic\s*examination)\s*[:\-]?", re.I | re.M)),
    ("investigations", re.compile(r"^(?:investigations?|lab(?:oratory)?\s*(?:results?|findings?)|diagnostic\s*(?:results?|findings?))\s*[:\-]?", re.I | re.M)),
    ("diagnosis_section", re.compile(r"^(?:(?:final|principal|primary|provisional)\s*)?diagnosis\s*[:\-]?", re.I | re.M)),
    ("treatment_given", re.compile(r"^(?:treatment\s*(?:given|provided|administered)|course\s*(?:in\s*(?:hospital|ward))|management)\s*[:\-]?", re.I | re.M)),
    ("procedure_section", re.compile(r"^(?:procedure(?:s)?\s*(?:performed|done)?|surgical?\s*(?:procedure|note)|operation\s*(?:performed|note))\s*[:\-]?", re.I | re.M)),
    ("medications_at_discharge", re.compile(r"^(?:(?:medication|medicine|drug)(?:s)?\s*(?:at|on)\s*discharge|discharge\s*(?:medication|medicine)(?:s)?|rx)\s*[:\-]?", re.I | re.M)),
    ("follow_up", re.compile(r"^(?:follow\s*[-\s]?up|advice\s*(?:on|at)\s*discharge|discharge\s*advice|instructions)\s*[:\-]?", re.I | re.M)),
    ("condition_at_discharge", re.compile(r"^(?:condition\s*(?:at|on)\s*discharge|discharge\s*(?:condition|status))\s*[:\-]?", re.I | re.M)),
]


def _normalize_amount(raw: str) -> str:
    """Normalize currency amounts: remove commas, ensure decimal format."""
    cleaned = raw.replace(",", "").strip()
    # Ensure it looks like a number
    try:
        val = float(cleaned)
        return f"{val:.2f}"
    except ValueError:
        return cleaned


def _extract_with_heuristic(ocr_pages: List[Dict[str, Any]]) -> ParseOutput:
    """Advanced regex-based field extraction from OCR text."""
    fields: List[FieldResult] = []
    tables: List[Dict[str, Any]] = []
    sections: List[Dict[str, Any]] = []
    seen_fields: Dict[str, set] = {}  # deduplicate identical extractions

    amount_fields = {
        "total_amount", "room_charges", "consultation_charges",
        "pharmacy_charges", "investigation_charges", "surgery_charges",
        "surgeon_fees", "anaesthesia_charges", "ot_charges",
        "consumables", "nursing_charges", "icu_charges",
        "ambulance_charges", "misc_charges",
    }

    for page_info in ocr_pages:
        page_num = page_info.get("page_number", 1)
        text = page_info.get("text", "")
        if not text:
            continue

        # --- Field extraction ---
        for field_name, pattern in _PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(1).strip() if match.lastindex else match.group(0).strip()
                if not value:
                    continue

                # Normalize amounts
                if field_name in amount_fields:
                    value = _normalize_amount(value)

                # Deduplicate: skip if same field+value already seen
                key = f"{field_name}:{value.lower()}"
                if field_name not in seen_fields:
                    seen_fields[field_name] = set()
                if key in seen_fields[field_name]:
                    continue
                seen_fields[field_name].add(key)

                fields.append(
                    FieldResult(
                        field_name=field_name,
                        field_value=value,
                        source_page=page_num,
                        model_version="heuristic-v2",
                    )
                )

        # --- Table detection (improved) ---
        page_tables = _detect_tables(text, page_num)
        tables.extend(page_tables)

        # --- Section detection ---
        page_sections = _detect_sections(text, page_num)
        sections.extend(page_sections)

        # --- Expense table extraction ---
        expense_fields = _extract_expense_table(text, page_num)
        for ef in expense_fields:
            key = f"{ef.field_name}:{ef.field_value}"
            if ef.field_name not in seen_fields:
                seen_fields[ef.field_name] = set()
            if key not in seen_fields[ef.field_name]:
                seen_fields[ef.field_name].add(key)
                fields.append(ef)

    return ParseOutput(
        fields=fields,
        tables=tables,
        sections=sections,
        model_version="heuristic-v2",
        used_fallback=True,
    )


def _detect_tables(text: str, page_num: int) -> List[Dict[str, Any]]:
    """Detect and parse table-like structures with header detection."""
    lines = text.splitlines()
    table_rows: List[List[str]] = []
    header: Optional[List[str]] = None
    tables: List[Dict[str, Any]] = []

    for line in lines:
        # Split on pipe separators (from pdfplumber tables) or multi-space/tab
        if "|" in line:
            cells = [c.strip() for c in line.split("|") if c.strip()]
        else:
            cells = re.split(r"\t|  {2,}", line.strip())
            cells = [c.strip() for c in cells if c.strip()]

        if len(cells) >= 3:
            # Check if this looks like a header row (all non-numeric, short)
            if not table_rows and all(
                not re.match(r"^[\d,.\-$₹]+$", c) for c in cells
            ):
                header = cells
            table_rows.append(cells)
        else:
            # Break in table — flush if we have rows
            if len(table_rows) >= 2:
                tables.append({
                    "source_page": page_num,
                    "header": header,
                    "rows": table_rows,
                    "row_count": len(table_rows),
                })
            table_rows = []
            header = None

    # Flush remaining
    if len(table_rows) >= 2:
        tables.append({
            "source_page": page_num,
            "header": header,
            "rows": table_rows,
            "row_count": len(table_rows),
        })

    return tables


def _detect_sections(text: str, page_num: int) -> List[Dict[str, Any]]:
    """Detect medical document sections (discharge summary, reports)."""
    sections: List[Dict[str, Any]] = []
    matches: List[tuple[int, str, str]] = []

    for section_name, pattern in _SECTION_PATTERNS:
        for m in pattern.finditer(text):
            matches.append((m.start(), section_name, m.group()))

    if not matches:
        return sections

    # Sort by position in text
    matches.sort(key=lambda x: x[0])

    # Extract content between sections
    for i, (pos, name, header) in enumerate(matches):
        start = pos + len(header)
        end = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()

        # Trim content to reasonable length (first 2000 chars)
        if len(content) > 2000:
            content = content[:2000] + "..."

        if content:
            sections.append({
                "section_name": name,
                "content": content,
                "source_page": page_num,
            })

    return sections


# ------------------------------------------------------------------
# Expense table extraction — smart billing line-item parser
# ------------------------------------------------------------------

_EXPENSE_SECTION_HEADER = re.compile(
    r"(?:(?:hospitali[sz]ation|hospital|medical|surgery|claimed)\s*(?:&\s*(?:surgery|treatment))?\s*)?(?:expense|billing|charges?|cost)\s*(?:summary|details?|breakdown|statement)?",
    re.I,
)

# Matches a line like: "Some Description   35,000" or "Room Rent (5 Days)  10,000"
# Also handles tab-separated and single-space when amount is clearly at end of line
_EXPENSE_LINE = re.compile(
    r"^(.+?)(?:\s{2,}|\t+)\s*(?:(?:rs|inr|\$|₹)\.?\s*)?(\d[\d,]*\.?\d*)\s*$", re.M
)

# Normalised expense categories for deduplication
_EXPENSE_CATEGORY_MAP: Dict[str, str] = {
    "surgeon": "surgeon_fees",
    "professional": "surgeon_fees",
    "anaesthesia": "anaesthesia_charges",
    "anesthesia": "anaesthesia_charges",
    "anaesthetist": "anaesthesia_charges",
    "operation theatre": "ot_charges",
    "ot charges": "ot_charges",
    "ot charge": "ot_charges",
    "theatre": "ot_charges",
    "consumable": "consumables",
    "surgical consumable": "consumables",
    "implant": "consumables",
    "disposable": "consumables",
    "diagnostic": "investigation_charges",
    "investigation": "investigation_charges",
    "pathology": "investigation_charges",
    "radiology": "investigation_charges",
    "lab": "investigation_charges",
    "room": "room_charges",
    "bed": "room_charges",
    "room rent": "room_charges",
    "nursing": "nursing_charges",
    "nurse": "nursing_charges",
    "hospital services": "nursing_charges",
    "pharmacy": "pharmacy_charges",
    "medicine": "pharmacy_charges",
    "drug": "pharmacy_charges",
    "consultation": "consultation_charges",
    "doctor": "consultation_charges",
    "physician": "consultation_charges",
    "icu": "icu_charges",
    "intensive care": "icu_charges",
    "ambulance": "ambulance_charges",
    "miscellaneous": "misc_charges",
    "sundry": "misc_charges",
    "other": "misc_charges",
}


def _categorise_expense(label: str) -> str:
    """Map a free-text expense label to a normalised category."""
    low = label.lower().strip()
    for keyword, category in _EXPENSE_CATEGORY_MAP.items():
        if keyword in low:
            return category
    return "other_charges"


def _extract_expense_table(text: str, page_num: int) -> List[FieldResult]:
    """
    Detect billing / expense sections and parse individual line items.

    Works on the common Indian hospital format:
        Expense Category       Amount (INR)
        Room Charges           10,000
        Surgeon Fees           35,000
        ...
        Total                  96,000
    """
    results: List[FieldResult] = []
    seen: Dict[str, str] = {}

    header_match = _EXPENSE_SECTION_HEADER.search(text)
    if not header_match:
        return results

    section_text = text[header_match.start():]

    for m in _EXPENSE_LINE.finditer(section_text):
        label = m.group(1).strip()
        raw_amount = m.group(2).strip()

        # Skip header rows
        if re.search(r"(?:amount|inr|usd|head|category|description|particular)", label, re.I):
            continue
        # Skip total rows
        if re.search(r"^(?:total|grand\s*total|net\s*(?:amount|payable)|sub\s*total)", label, re.I):
            continue

        amount = _normalize_amount(raw_amount)
        try:
            if float(amount) <= 0:
                continue
        except ValueError:
            continue

        category = _categorise_expense(label)

        # Deduplicate — keep the highest value per category
        if category in seen:
            try:
                if float(amount) <= float(seen[category]):
                    continue
            except ValueError:
                continue
        seen[category] = amount

        results.append(FieldResult(
            field_name=category,
            field_value=amount,
            source_page=page_num,
            model_version="expense-table-v1",
        ))

    return results
