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

from .icd10_codes import (
    estimate_cost,
    get_cpt_for_icd10,
    is_valid_cpt,
    lookup_cpt,
    lookup_icd10,
    search_cpt_by_text,
    search_icd10_by_text,
)

logger = logging.getLogger("coding.engine")

# ------------------------------------------------------------------
# Data types
# ------------------------------------------------------------------

@dataclass
class Entity:
    entity_text: str
    entity_type: str  # DIAGNOSIS / PROCEDURE / MEDICATION / CHEMICAL
    start_offset: int | None = None
    end_offset: int | None = None
    confidence: float | None = None
    umls_cui: str | None = None  # UMLS Concept Unique Identifier


@dataclass
class Code:
    code: str
    code_system: str  # ICD10 / CPT
    description: str | None = None
    confidence: float | None = None
    is_primary: bool = False
    estimated_cost: float | None = None
    entity_index: int | None = None


@dataclass
class CodingOutput:
    entities: list[Entity] = field(default_factory=list)
    codes: list[Code] = field(default_factory=list)
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
        # Optimization: disable unnecessary components to reduce latency and memory
        _nlp = spacy.load(_SCISPACY_MODEL, exclude=["parser", "tagger", "lemmatizer", "textcat", "senter", "attribute_ruler"])
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
    texts: list[str],
    parsed_fields: list[dict] | None = None,
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

    # Priority 0: Semantic LLM extraction (if enabled)
    semantic_output = _extract_with_semantic_llm(full_text)
    if semantic_output is not None:
        return semantic_output

    # Priority 1: Parsed fields (highest quality human-corrected or parser output)
    if parsed_fields:
        return _extract_from_parsed_fields(parsed_fields, full_text)

    # Priority 2: scispaCy biomedical NER
    nlp = _load_scispacy()
    if nlp is not None:
        return _extract_with_scispacy(nlp, full_text)

    # Priority 3: Regex fallback
    return _extract_with_regex(full_text)


def _extract_with_semantic_llm(full_text: str) -> CodingOutput | None:
    # New architecture hook: implement semantic extraction if needed
    # Currently disabled to default to scispaCy/Regex fallback.
    return None


# ------------------------------------------------------------------
# Parsed-fields-based extraction (highest quality)
# ------------------------------------------------------------------

# Map parser field names to entity types
_FIELD_TO_ENTITY: dict[str, str] = {
    "diagnosis": "DIAGNOSIS",
    "primary_diagnosis": "DIAGNOSIS",
    "secondary_diagnosis": "DIAGNOSIS",
    "icd_code": "DIAGNOSIS",
    "procedure": "PROCEDURE",
    "primary_procedure": "PROCEDURE",
    "cpt_code": "PROCEDURE",
    "medication": "MEDICATION",
}


def _extract_from_parsed_fields(
    parsed_fields: list[dict],
    full_text: str,
) -> CodingOutput:
    """Use parser's structured fields directly as entities, then map to codes."""
    entities: list[Entity] = []
    codes: list[Code] = []
    seen_codes: set[str] = set()

    for pf in parsed_fields:
        fname = pf.get("field_name", "")
        fval = pf.get("field_value", "")
        if not fval or fname not in _FIELD_TO_ENTITY:
            continue

        etype = _FIELD_TO_ENTITY[fname]
        
        # 1. Clean the field value: remove leading numbers, colons, and pipes
        clean_fval = re.sub(r"^(\d+[\:\.]\s*)?\|?\s*", "", fval).replace("|", "").strip()
        
        # Strip "None" or "N/A" prefixes from parser noise (e.g., "None Procedure: X")
        clean_fval = re.sub(r"^(?:none|n/a|null)\s+", "", clean_fval, flags=re.IGNORECASE).strip()
        
        # Override field mapping if text explicitly declares its category type
        if re.search(r"^procedure\s*[:\-]", clean_fval, flags=re.IGNORECASE):
            etype = "PROCEDURE"
        elif re.search(r"^(?:diagnosis|dx|impression)\s*[:\-]", clean_fval, flags=re.IGNORECASE):
            etype = "DIAGNOSIS"
        
        # Strip category prefixes accidentally included in field value (e.g. "Procedure: X")
        clean_fval = re.sub(r"^(?:procedure|diagnosis|dx|impression)\s*[:\-]\s*", "", clean_fval, flags=re.IGNORECASE).strip()

        # 2. Quality Filter: skip if too short or exactly equivalent to a null value
        lower_fval = clean_fval.lower()
        if len(clean_fval) < 4 or lower_fval in ["none", "n/a", "null"]:
            continue
            
        # Blacklist conversational / billing noise phrases
        blacklist = ["medically necessary", "first claim", "% of sum", "payment", "balance", "total", "amount"]
        if any(bad in lower_fval for bad in blacklist):
            continue

        # Simple fallback to find provenance in the text
        start_idx = full_text.find(fval)
        end_idx = start_idx + len(fval) if start_idx != -1 else -1

        entities.append(Entity(
            entity_text=clean_fval,
            entity_type=etype,
            confidence=0.90,
            start_offset=start_idx,
            end_offset=end_idx,
        ))

        if etype == "DIAGNOSIS":
            matches = []
            # 3. Explicit Code Extraction: check the text for a literal code first
            explicit_match = _ICD_CODE_RE.search(clean_fval)
            if explicit_match:
                raw_code = explicit_match.group(1)
                info = lookup_icd10(raw_code)
                matches.append((raw_code, info[1] if info else None))
            
            if not matches:
                matches = search_icd10_by_text(clean_fval, max_results=2)
                
            for code_tuple in matches:
                if code_tuple[0] not in seen_codes:
                    seen_codes.add(code_tuple[0])
                    codes.append(Code(
                        code=code_tuple[0],
                        code_system="ICD10",
                        description=code_tuple[1],
                        confidence=0.95 if explicit_match else 0.90,
                        is_primary=len(codes) == 0,
                        estimated_cost=estimate_cost(code_tuple[0], "ICD10"),
                        entity_index=len(entities) - 1,
                    ))
                    
        elif etype == "PROCEDURE":
            cpt_matches = []
            explicit_match = _CPT_CODE_RE.search(clean_fval)
            if explicit_match:
                raw_code = explicit_match.group(1)
                info = lookup_cpt(raw_code)
                cpt_matches.append((raw_code, info[1] if info else None))
                        
            if not cpt_matches:
                cpt_matches = search_cpt_by_text(clean_fval, max_results=2)
                
            for code_tuple in cpt_matches:
                if code_tuple[0] not in seen_codes:
                    seen_codes.add(code_tuple[0])
                    codes.append(Code(
                        code=code_tuple[0],
                        code_system="CPT",
                        description=code_tuple[1],
                        confidence=0.95 if explicit_match else 0.90,
                        estimated_cost=estimate_cost(code_tuple[0], "CPT"),
                        entity_index=len(entities) - 1,
                    ))

    # Also extract explicit ICD-10/CPT codes from the raw text (fallback)
    _extract_explicit_codes(full_text, codes, seen_codes)

    return CodingOutput(entities=entities, codes=codes, model_used="parsed_fields")


# ------------------------------------------------------------------
# scispaCy-based extraction
# ------------------------------------------------------------------

def _extract_with_scispacy(nlp, full_text: str) -> CodingOutput:
    """Use scispaCy model for medical entity extraction."""
    doc = nlp(full_text)
    entities: list[Entity] = []
    codes: list[Code] = []
    seen_codes: set[str] = set()

    # scispaCy entity labels in bc5cdr: DISEASE, CHEMICAL
    for ent in doc.ents:
        if ent.label_ == "DIAGNOSIS" or ent.label_ == "DISEASE":
            etype = "DIAGNOSIS"
        elif ent.label_ == "CHEMICAL" or ent.label_ == "DRUG":
            etype = "MEDICATION"
        else:
            continue  # ignore others for now

        # Add entity with provenance
        entities.append(Entity(
            entity_text=ent.text,
            entity_type=etype,
            start_offset=ent.start_char,
            end_offset=ent.end_char,
            confidence=0.85,  # Estimated for scispacy
            umls_cui=ent._.kb_ents[0][0] if hasattr(ent._, "kb_ents") and ent._.kb_ents else None,
        ))

        # Look up codes
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
                        entity_index=len(entities) - 1,
                    ))

    # Supplement with regex for PROCEDURE entities (not covered by bc5cdr model)
    regex_out = _extract_with_regex(full_text)
    for ent in regex_out.entities:
        if ent.entity_type == "PROCEDURE":
            # Avoid dupes if possible (simple text check)
            if not any(e.entity_text.lower() == ent.entity_text.lower() for e in entities):
                entities.append(ent)
                # Map procedure to CPT
                cpt_matches = search_cpt_by_text(ent.entity_text, max_results=2)
                for code_tuple in cpt_matches:
                    if code_tuple[0] not in seen_codes:
                        seen_codes.add(code_tuple[0])
                        codes.append(Code(
                            code=code_tuple[0],
                            code_system="CPT",
                            description=code_tuple[1],
                            confidence=0.75,
                            estimated_cost=estimate_cost(code_tuple[0], "CPT"),
                            entity_index=len(entities) - 1,
                        ))

    # Also extract explicit ICD-10/CPT codes from the raw text
    _extract_explicit_codes(full_text, codes, seen_codes)

    return CodingOutput(entities=entities, codes=codes, model_used="scispacy")


# ------------------------------------------------------------------
# Regex-based extraction (fallback)
# ------------------------------------------------------------------

def _extract_with_regex(full_text: str) -> CodingOutput:
    """Fallback extraction using keyword patterns and common codes."""
    entities: list[Entity] = []
    codes: list[Code] = []
    seen_codes: set[str] = set()

    for pat in _DIAGNOSIS_PATTERNS:
        for m in pat.finditer(full_text):
            val = m.group(1).split("\n")[0].strip()
            if len(val) > 3:
                entities.append(Entity(
                    entity_text=val,
                    entity_type="DIAGNOSIS",
                    start_offset=m.start(1),
                    end_offset=m.end(1),
                    confidence=0.65,
                ))
                matches = search_icd10_by_text(val, max_results=1)
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
                            entity_index=len(entities) - 1,
                        ))

    for pat in _PROCEDURE_PATTERNS:
        for m in pat.finditer(full_text):
            val = m.group(1).split("\n")[0].strip()
            if len(val) > 3:
                entities.append(Entity(
                    entity_text=val,
                    entity_type="PROCEDURE",
                    start_offset=m.start(1),
                    end_offset=m.end(1),
                    confidence=0.60,
                ))
                matches = search_cpt_by_text(val, max_results=1)
                for code_tuple in matches:
                    if code_tuple[0] not in seen_codes:
                        seen_codes.add(code_tuple[0])
                        codes.append(Code(
                            code=code_tuple[0],
                            code_system="CPT",
                            description=code_tuple[1],
                            confidence=0.60,
                            estimated_cost=estimate_cost(code_tuple[0], "CPT"),
                            entity_index=len(entities) - 1,
                        ))

    for pat in _MEDICATION_PATTERNS:
        for m in pat.finditer(full_text):
            val = m.group(1).split("\n")[0].strip()
            if len(val) > 3:
                entities.append(Entity(
                    entity_text=val,
                    entity_type="MEDICATION",
                    start_offset=m.start(1),
                    end_offset=m.end(1),
                    confidence=0.60,
                ))

    _extract_explicit_codes(full_text, codes, seen_codes)

    return CodingOutput(entities=entities, codes=codes, model_used="regex")


# ------------------------------------------------------------------
# Shared: extract explicit ICD-10 / CPT codes from text
# ------------------------------------------------------------------

def _extract_explicit_codes(
    text: str,
    codes: list[Code],
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
        # Attempt lookup but don't drop on failure
        # (Allows parser and explicit extraction to capture missing codes)
        seen.add(raw_code)
        info = lookup_cpt(raw_code)
        codes.append(Code(
            code=raw_code,
            code_system="CPT",
            description=info[1] if info else None,
            confidence=0.90 if info else 0.60,
            estimated_cost=estimate_cost(raw_code, "CPT"),
        ))
