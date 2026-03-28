"""
Medical NER + ICD-10/CPT coding engine.

Strategy (ordered by priority):
  1. **scispaCy** biomedical NER (en_ner_bc5cdr_md) for entity extraction —
     identifies diseases, chemicals/drugs, and procedures.
  2. **BioGPT** (microsoft/biogpt) for entity-to-code suggestion when UMLS
     linker is unavailable.
  3. **Regex fallback** when ML models have not been downloaded yet.

Code assignment uses a 350+ entry ICD-10-CM / 120-entry CPT local database
with optional UMLS entity linking for broader coverage.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .icd10_codes import ICD10_CM, CPT_CODES, lookup_icd10, lookup_cpt, search_icd10_by_text, search_cpt_by_text, estimate_cost, get_cpt_for_icd10, is_valid_cpt

logger = logging.getLogger("coding.engine")

# ------------------------------------------------------------------
# Data types
# ------------------------------------------------------------------

@dataclass
class Entity:
    entity_text: str
    entity_type: str  # DIAGNOSIS / PROCEDURE / MEDICATION / CHEMICAL
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    confidence: Optional[float] = None
    umls_cui: Optional[str] = None  # UMLS Concept Unique Identifier


@dataclass
class Code:
    code: str
    code_system: str  # ICD10 / CPT
    description: Optional[str] = None
    confidence: Optional[float] = None
    is_primary: bool = False
    estimated_cost: Optional[float] = None


@dataclass
class CodingOutput:
    entities: List[Entity] = field(default_factory=list)
    codes: List[Code] = field(default_factory=list)
    model_used: str = "regex"  # scispacy | biogpt | regex


# ------------------------------------------------------------------
# Lazy-loaded scispaCy pipeline
# ------------------------------------------------------------------
_nlp = None
_nlp_load_attempted = False
_SCISPACY_MODEL = "en_ner_bc5cdr_md"  # diseases + chemicals


def _load_scispacy():
    """Load scispaCy biomedical NER model. Returns the spaCy nlp object or None."""
    global _nlp, _nlp_load_attempted
    if _nlp_load_attempted:
        return _nlp
    _nlp_load_attempted = True

    try:
        import spacy
        _nlp = spacy.load(_SCISPACY_MODEL)
        logger.info("scispaCy model '%s' loaded successfully", _SCISPACY_MODEL)

        # UMLS linker requires ~500 MB of data on first use.
        # Only enable it if explicitly requested via config.
        try:
            from .config import settings as coding_settings
            if coding_settings.use_umls_linker:
                from scispacy.linking import EntityLinker  # noqa: F401
                if "scispacy_linker" not in _nlp.pipe_names:
                    _nlp.add_pipe(
                        "scispacy_linker",
                        config={
                            "resolve_abbreviations": True,
                            "linker_name": "umls",
                            "threshold": 0.80,
                        },
                    )
                    logger.info("UMLS entity linker attached to scispaCy pipeline")
        except Exception:
            logger.info("UMLS linker not available — using NER without entity linking")

        return _nlp
    except Exception:
        logger.warning(
            "scispaCy model '%s' not available — will try BioGPT or regex fallback",
            _SCISPACY_MODEL,
            exc_info=True,
        )
        return None


# ------------------------------------------------------------------
# Lazy-loaded BioGPT pipeline
# ------------------------------------------------------------------
_biogpt_pipeline = None
_biogpt_load_attempted = False


def _load_biogpt():
    """Load BioGPT for medical text-to-code suggestion."""
    global _biogpt_pipeline, _biogpt_load_attempted
    if _biogpt_load_attempted:
        return _biogpt_pipeline
    _biogpt_load_attempted = True

    try:
        from transformers import pipeline as hf_pipeline
        _biogpt_pipeline = hf_pipeline(
            "text-generation",
            model="microsoft/biogpt",
            max_new_tokens=64,
            device=-1,  # CPU
        )
        logger.info("BioGPT model loaded successfully")
        return _biogpt_pipeline
    except Exception:
        logger.warning(
            "BioGPT model not available — will use regex fallback",
            exc_info=True,
        )
        return None


# ------------------------------------------------------------------
# Regex fallback patterns (kept for environments without ML deps)
# ------------------------------------------------------------------
_DIAGNOSIS_PATTERNS = [
    re.compile(r"(?:diagnosis|dx|impression)\s*[:\-]?\s*(.+)", re.I),
]
_PROCEDURE_PATTERNS = [
    re.compile(r"(?:procedure|operation|surgery|intervention)\s*[:\-]?\s*(.+)", re.I),
]
_MEDICATION_PATTERNS = [
    re.compile(r"(?:medication|medicine|drug|prescription|rx)\s*[:\-]?\s*(.+)", re.I),
]
_ICD_CODE_RE = re.compile(r"\b([A-TV-Z]\d{2}(?:\.\d{1,4})?)\b")
_CPT_CODE_RE = re.compile(r"\b(\d{5})\b")


# ------------------------------------------------------------------
# Main extraction entry-point
# ------------------------------------------------------------------

def extract_entities_and_codes(
    texts: List[str],
    parsed_fields: Optional[List[dict]] = None,
) -> CodingOutput:
    """
    Run NER + code extraction over a list of text blocks.

    Parameters
    ----------
    texts : list of raw text strings (typically one per OCR page)
    parsed_fields : optional list of dicts with 'field_name' and 'field_value'
                    from the parser (higher quality than raw NER).

    Returns
    -------
    CodingOutput with entities, codes, and the model name used.
    """
    full_text = "\n".join(texts)

    # If we have parsed fields, use them directly as high-quality entities
    # and supplement with regex on raw OCR text for anything missed.
    if parsed_fields:
        return _extract_from_parsed_fields(parsed_fields, full_text)

    # --- Try scispaCy first ---
    nlp = _load_scispacy()
    if nlp is not None:
        return _extract_with_scispacy(nlp, full_text)

    # --- Regex fallback (skip BioGPT — not designed for NER) ---
    return _extract_with_regex(full_text)


# ------------------------------------------------------------------
# Parsed-fields-based extraction (highest quality)
# ------------------------------------------------------------------

# Map parser field names to entity types
_FIELD_TO_ENTITY: dict[str, str] = {
    "diagnosis": "DIAGNOSIS",
    "secondary_diagnosis": "DIAGNOSIS",
    "procedure": "PROCEDURE",
    "medication": "MEDICATION",
}


def _extract_from_parsed_fields(
    parsed_fields: List[dict],
    full_text: str,
) -> CodingOutput:
    """Use parser's structured fields directly as entities, then map to codes."""
    entities: List[Entity] = []
    codes: List[Code] = []
    seen_codes: set[str] = set()

    for pf in parsed_fields:
        fname = pf.get("field_name", "")
        fval = pf.get("field_value", "")
        if not fval or fname not in _FIELD_TO_ENTITY:
            continue

        etype = _FIELD_TO_ENTITY[fname]
        entities.append(Entity(
            entity_text=fval,
            entity_type=etype,
            confidence=0.90,
        ))

        if etype == "DIAGNOSIS":
            matches = search_icd10_by_text(fval, max_results=2)
            for code_tuple in matches:
                if code_tuple[0] not in seen_codes:
                    seen_codes.add(code_tuple[0])
                    codes.append(Code(
                        code=code_tuple[0],
                        code_system="ICD10",
                        description=code_tuple[1],
                        confidence=0.90,
                        is_primary=len(codes) == 0,
                        estimated_cost=estimate_cost(code_tuple[0], "ICD10"),
                    ))
        elif etype == "PROCEDURE":
            cpt_matches = search_cpt_by_text(fval, max_results=2)
            for code_tuple in cpt_matches:
                if code_tuple[0] not in seen_codes:
                    seen_codes.add(code_tuple[0])
                    codes.append(Code(
                        code=code_tuple[0],
                        code_system="CPT",
                        description=code_tuple[1],
                        confidence=0.90,
                        estimated_cost=estimate_cost(code_tuple[0], "CPT"),
                    ))

    # Also extract explicit ICD-10/CPT codes from the raw text
    _extract_explicit_codes(full_text, codes, seen_codes)

    # Cross-reference: suggest CPT codes based on found ICD-10 diagnoses
    _cross_reference_icd_to_cpt(codes, seen_codes)

    return CodingOutput(
        entities=entities,
        codes=codes,
        model_used="parsed_fields",
    )


# ------------------------------------------------------------------
# scispaCy extraction
# ------------------------------------------------------------------

_ENTITY_TYPE_MAP = {
    "DISEASE": "DIAGNOSIS",
    "CHEMICAL": "MEDICATION",
}


def _extract_with_scispacy(nlp, full_text: str) -> CodingOutput:
    """Use scispaCy biomedical NER to extract entities, then map to codes.

    The en_ner_bc5cdr_md model detects DISEASE and CHEMICAL entities.
    We supplement with regex patterns for PROCEDURE entities which the
    model doesn't cover.
    """
    doc = nlp(full_text)
    entities: List[Entity] = []
    codes: List[Code] = []
    seen_codes: set[str] = set()

    for ent in doc.ents:
        # Map scispaCy labels to our taxonomy
        etype = _ENTITY_TYPE_MAP.get(ent.label_, ent.label_)

        umls_cui = None
        confidence = 0.85
        # If UMLS linker is available, grab the top concept
        if hasattr(ent, "_") and hasattr(ent._, "kb_ents") and ent._.kb_ents:
            umls_cui = ent._.kb_ents[0][0]  # (CUI, score)
            confidence = round(ent._.kb_ents[0][1], 3)

        entities.append(Entity(
            entity_text=ent.text,
            entity_type=etype,
            start_offset=ent.start_char,
            end_offset=ent.end_char,
            confidence=confidence,
            umls_cui=umls_cui,
        ))

        # Try to match entity text to ICD-10 codes via keyword search
        if etype == "DIAGNOSIS":
            matches = search_icd10_by_text(ent.text, max_results=2)
            for code_tuple in matches:
                if code_tuple[0] not in seen_codes:
                    seen_codes.add(code_tuple[0])
                    codes.append(Code(
                        code=code_tuple[0],
                        code_system="ICD10",
                        description=code_tuple[1],
                        confidence=0.85,
                        is_primary=len(codes) == 0,
                        estimated_cost=estimate_cost(code_tuple[0], "ICD10"),
                    ))

    # Supplement with regex for PROCEDURE entities (not covered by bc5cdr model)
    for pat in _PROCEDURE_PATTERNS:
        for m in pat.finditer(full_text):
            value = m.group(1).strip()
            if value:
                entities.append(Entity(
                    entity_text=value,
                    entity_type="PROCEDURE",
                    start_offset=m.start(1),
                    end_offset=m.end(1),
                    confidence=0.75,
                ))
                # Map procedures to CPT codes
                cpt_matches = search_cpt_by_text(value, max_results=2)
                for code_tuple in cpt_matches:
                    if code_tuple[0] not in seen_codes:
                        seen_codes.add(code_tuple[0])
                        codes.append(Code(
                            code=code_tuple[0],
                            code_system="CPT",
                            description=code_tuple[1],
                            confidence=0.75,
                            estimated_cost=estimate_cost(code_tuple[0], "CPT"),
                        ))

    # Also extract explicit ICD-10/CPT codes from the raw text
    _extract_explicit_codes(full_text, codes, seen_codes)

    # Cross-reference: suggest CPT codes based on found ICD-10 diagnoses
    _cross_reference_icd_to_cpt(codes, seen_codes)

    return CodingOutput(entities=entities, codes=codes, model_used="scispacy")


# ------------------------------------------------------------------
# BioGPT extraction
# ------------------------------------------------------------------

def _extract_with_biogpt(biogpt, full_text: str) -> CodingOutput:
    """
    Use BioGPT to identify medical entities from text, then map to codes.
    BioGPT is prompted to list diagnoses, procedures, and medications.
    """
    entities: List[Entity] = []
    codes: List[Code] = []
    seen_codes: set[str] = set()

    # Truncate to model context window
    snippet = full_text[:1024]

    for task, etype in [
        ("diagnoses", "DIAGNOSIS"),
        ("procedures", "PROCEDURE"),
        ("medications", "MEDICATION"),
    ]:
        prompt = f"Extract the {task} from this medical document: {snippet}\n{task.title()}:"
        try:
            result = biogpt(prompt)
            generated = result[0]["generated_text"]
            # Parse the part after our prompt
            answer = generated[len(prompt):].strip()
            # Split on commas/newlines for individual entities
            for item in re.split(r"[,\n;]+", answer):
                item = item.strip().rstrip(".")
                if 3 < len(item) < 120:
                    entities.append(Entity(
                        entity_text=item,
                        entity_type=etype,
                        confidence=0.70,
                    ))
                    if etype == "DIAGNOSIS":
                        matches = search_icd10_by_text(item, max_results=1)
                        for code_tuple in matches:
                            if code_tuple[0] not in seen_codes:
                                seen_codes.add(code_tuple[0])
                                codes.append(Code(
                                    code=code_tuple[0],
                                    code_system="ICD10",
                                    description=code_tuple[1],
                                    confidence=0.70,
                                    is_primary=len(codes) == 0,
                                    estimated_cost=estimate_cost(code_tuple[0], "ICD10"),
                                ))
        except Exception:
            logger.warning("BioGPT extraction failed for %s", task, exc_info=True)

    # Also extract explicit ICD-10/CPT codes from the raw text
    _extract_explicit_codes(full_text, codes, seen_codes)

    # Cross-reference: suggest CPT codes based on found ICD-10 diagnoses
    _cross_reference_icd_to_cpt(codes, seen_codes)

    return CodingOutput(entities=entities, codes=codes, model_used="biogpt")


# ------------------------------------------------------------------
# Regex fallback extraction
# ------------------------------------------------------------------

def _extract_with_regex(full_text: str) -> CodingOutput:
    """Regex-based NER + code lookup (no ML dependencies)."""
    entities: List[Entity] = []
    codes: List[Code] = []
    seen_codes: set[str] = set()

    for pat in _DIAGNOSIS_PATTERNS:
        for m in pat.finditer(full_text):
            value = m.group(1).strip()
            if value:
                entities.append(Entity(
                    entity_text=value,
                    entity_type="DIAGNOSIS",
                    start_offset=m.start(1),
                    end_offset=m.end(1),
                    confidence=0.65,
                ))
                matches = search_icd10_by_text(value, max_results=2)
                for code_tuple in matches:
                    if code_tuple[0] not in seen_codes:
                        seen_codes.add(code_tuple[0])
                        codes.append(Code(
                            code=code_tuple[0],
                            code_system="ICD10",
                            description=code_tuple[1],
                            confidence=0.65,
                            is_primary=len(codes) == 0,
                            estimated_cost=estimate_cost(code_tuple[0], "ICD10"),
                        ))

    for pat in _PROCEDURE_PATTERNS:
        for m in pat.finditer(full_text):
            value = m.group(1).strip()
            if value:
                entities.append(Entity(
                    entity_text=value,
                    entity_type="PROCEDURE",
                    start_offset=m.start(1),
                    end_offset=m.end(1),
                    confidence=0.60,
                ))
                cpt_matches = search_cpt_by_text(value, max_results=2)
                for code_tuple in cpt_matches:
                    if code_tuple[0] not in seen_codes:
                        seen_codes.add(code_tuple[0])
                        codes.append(Code(
                            code=code_tuple[0],
                            code_system="CPT",
                            description=code_tuple[1],
                            confidence=0.60,
                            estimated_cost=estimate_cost(code_tuple[0], "CPT"),
                        ))

    for pat in _MEDICATION_PATTERNS:
        for m in pat.finditer(full_text):
            value = m.group(1).strip()
            if value:
                entities.append(Entity(
                    entity_text=value,
                    entity_type="MEDICATION",
                    start_offset=m.start(1),
                    end_offset=m.end(1),
                    confidence=0.60,
                ))

    _extract_explicit_codes(full_text, codes, seen_codes)

    # Cross-reference: suggest CPT codes based on found ICD-10 diagnoses
    _cross_reference_icd_to_cpt(codes, seen_codes)

    return CodingOutput(entities=entities, codes=codes, model_used="regex")


# ------------------------------------------------------------------
# Shared: extract explicit ICD-10 / CPT codes from text
# ------------------------------------------------------------------

def _extract_explicit_codes(
    text: str,
    codes: List[Code],
    seen: set[str],
) -> None:
    """Find ICD-10 and CPT codes written explicitly in the text."""
    for m in _ICD_CODE_RE.finditer(text):
        raw_code = m.group(1)
        if raw_code in seen:
            continue
        seen.add(raw_code)
        info = lookup_icd10(raw_code)
        codes.append(Code(
            code=raw_code,
            code_system="ICD10",
            description=info[1] if info else None,
            confidence=0.95 if info else 0.60,
            is_primary=len(codes) == 0,
            estimated_cost=estimate_cost(raw_code, "ICD10"),
        ))

    for m in _CPT_CODE_RE.finditer(text):
        raw_code = m.group(1)
        if raw_code in seen:
            continue
        # Only accept 5-digit codes that are known valid CPT codes
        if not is_valid_cpt(raw_code):
            continue
        seen.add(raw_code)
        info = lookup_cpt(raw_code)
        codes.append(Code(
            code=raw_code,
            code_system="CPT",
            description=info[1] if info else None,
            confidence=0.90 if info else 0.60,
            estimated_cost=estimate_cost(raw_code, "CPT"),
        ))


def _cross_reference_icd_to_cpt(
    codes: List[Code],
    seen: set[str],
) -> None:
    """For each ICD-10 code found, suggest related CPT procedure codes."""
    icd_codes = [c.code for c in codes if c.code_system == "ICD10"]
    for icd_code in icd_codes:
        cpt_matches = get_cpt_for_icd10(icd_code, max_results=3)
        for code_tuple in cpt_matches:
            if code_tuple[0] not in seen:
                seen.add(code_tuple[0])
                codes.append(Code(
                    code=code_tuple[0],
                    code_system="CPT",
                    description=code_tuple[1],
                    confidence=0.80,
                    estimated_cost=estimate_cost(code_tuple[0], "CPT"),
                ))
