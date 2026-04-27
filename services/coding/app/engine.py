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

## Local LLM import removed
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

# Prefixes that strongly suggest a 5-digit number is NOT a CPT code
_CPT_REJECT_PREFIXES = [
    "authorization number", "auth no", "approval no", "claim no", "ref no",
    "member id", "policy no", "reg no", "registration", "sl no", "page",
    "phone", "pin", "zip", "contact", "mobile", "aadhaar", "receipt",
    "mrn", "ip number", "ip no", "mci", "dr no", "doctor reg"
]

# Keywords that strongly suggest a 5-digit number IS a CPT code
_CPT_TRIGGER_KEYWORDS = ["cpt", "code", "proc", "procedure", "surgical", "operation"]


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
    
    # Track primary assignment by field priority
    primary_diag_code: str | None = None
    primary_proc_code: str | None = None

    # Check if the parser provided explicit icd_code fields.
    # If so, those are authoritative — do NOT use fuzzy text matching on
    # diagnosis description fields to generate new codes (it hallucinates).
    has_explicit_icd_fields = any(
        pf.get("field_name") == "icd_code" and pf.get("field_value")
        for pf in parsed_fields
    )

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
        min_len = 3 if fname in ("icd_code", "cpt_code") else 4
        if len(clean_fval) < min_len or lower_fval in ["none", "n/a", "null"]:
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
            explicit_match = _ICD_CODE_RE.search(clean_fval)
            if explicit_match:
                raw_code = explicit_match.group(1)
                info = lookup_icd10(raw_code)
                matches.append((raw_code, info[1] if info else None))
            
            # Only do fuzzy text-to-code matching if:
            #  1. No explicit ICD code was found in this field's text, AND
            #  2. The parser did NOT provide authoritative icd_code fields
            # This prevents hallucinating codes like Z51.11 from "Chemotherapy"
            if not matches and not has_explicit_icd_fields:
                matches = search_icd10_by_text(clean_fval, max_results=2)
                
            for code_tuple in matches:
                if code_tuple[0] not in seen_codes:
                    seen_codes.add(code_tuple[0])
                    
                    # 1. Try to get description from the field value first
                    orig_text = re.sub(r"(?i)\b(?:icd-10|icd10)?\s*[:\-]?\s*" + re.escape(code_tuple[0]) + r"\b", "", clean_fval).strip()
                    orig_text = re.sub(r"[\:\|\-]\s*$", "", orig_text).strip()
                    
                    # 2. Fallback to nearby OCR context in the full document if field text is weak
                    final_desc = None
                    if len(orig_text) > 4:
                        final_desc = orig_text
                    else:
                        final_desc = _find_description_in_context(full_text, code_tuple[0], "ICD10")
                    
                    # 3. Final fallback to DB description
                    if not final_desc:
                        final_desc = code_tuple[1]

                    is_primary = False
                    if not primary_diag_code:
                        is_primary = True
                        primary_diag_code = code_tuple[0]
                    # Also prioritize if from the 'primary_diagnosis' field specifically
                    elif fname == "primary_diagnosis":
                        # Mark this as primary and downgrade previous one
                        for c in codes:
                            if c.code_system == "ICD10":
                                c.is_primary = False
                        is_primary = True
                        primary_diag_code = code_tuple[0]

                    codes.append(Code(
                        code=code_tuple[0],
                        code_system="ICD10",
                        description=final_desc,
                        confidence=0.95 if explicit_match else 0.90,
                        is_primary=is_primary,
                        estimated_cost=estimate_cost(code_tuple[0], "ICD10"),
                        entity_index=len(entities) - 1,
                    ))
                    
        elif etype == "PROCEDURE":
            cpt_matches = []
            explicit_match = _CPT_CODE_RE.search(clean_fval)
            if explicit_match:
                raw_code = explicit_match.group(1)
                # Apply CPT guardrails even to parsed fields if they look like random IDs
                prefix_window = clean_fval[:explicit_match.start()].lower()
                if not any(bad in prefix_window for bad in _CPT_REJECT_PREFIXES):
                    info = lookup_cpt(raw_code)
                    cpt_matches.append((raw_code, info[1] if info else None))
                        
            if not cpt_matches:
                cpt_matches = search_cpt_by_text(clean_fval, max_results=2)
                
            for code_tuple in cpt_matches:
                if code_tuple[0] not in seen_codes:
                    seen_codes.add(code_tuple[0])

                    # 1. Try to get description from the field value
                    orig_text = re.sub(r"(?i)\b(?:cpt)?\s*[:\-]?\s*" + re.escape(code_tuple[0]) + r"\b", "", clean_fval).strip()
                    orig_text = re.sub(r"[\:\|\-]\s*$", "", orig_text).strip()
                    
                    # 2. Fallback to nearby OCR context
                    final_desc = None
                    if len(orig_text) > 4:
                        final_desc = orig_text
                    else:
                        final_desc = _find_description_in_context(full_text, code_tuple[0], "CPT")

                    # 3. Final fallback to DB
                    if not final_desc:
                        final_desc = code_tuple[1]

                    is_primary = False
                    if not primary_proc_code:
                        is_primary = True
                        primary_proc_code = code_tuple[0]
                    elif fname == "primary_procedure":
                        for c in codes:
                            if c.code_system == "CPT":
                                c.is_primary = False
                        is_primary = True
                        primary_proc_code = code_tuple[0]

                    codes.append(Code(
                        code=code_tuple[0],
                        code_system="CPT",
                        description=final_desc,
                        confidence=0.95 if explicit_match else 0.90,
                        is_primary=is_primary,
                        estimated_cost=estimate_cost(code_tuple[0], "CPT"),
                        entity_index=len(entities) - 1,
                    ))

    # When parsed fields are available, they are the authoritative source for
    # ICD codes. Do NOT add new ICD codes from raw text scanning — this causes
    # hallucinated codes (e.g., Z51.11, N18.9) to be injected from surrounding
    # clinical text that merely *mentions* codes without being diagnoses.
    # Only enrich descriptions of already-found codes, and allow new CPT codes
    # from explicit mentions (they are less prone to hallucination due to the
    # stricter guardrails in _extract_explicit_codes).
    _enrich_descriptions_only(full_text, codes, seen_codes)

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
                        description=ent.text if len(ent.text) > 3 else code_tuple[1],
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
                            description=ent.entity_text if len(ent.entity_text) > 3 else code_tuple[1],
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
                            description=val if len(val) > 3 else code_tuple[1],
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
                            description=val if len(val) > 3 else code_tuple[1],
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

def _get_description_for_match(text: str, start: int, end: int, code_type: str) -> str | None:
    """Gets context for a known match location without rescanning the text."""
    # Look back first (most common for clinical labels)
    context_before = _extract_nearby_context(text, start, code_type)
    if len(context_before) > 8:
        return context_before
        
    # Look forward (less common but occurs in tables/lists)
    # e.g. "92941 - Emergency Angioplasty"
    after_text = text[end:end + 80]
    line_after = after_text.split("\n")[0].strip()
    # Clean separators
    line_after = re.sub(r"^[\s\:\-\|]+", "", line_after).strip()
    # Stop if we hit another code-like pattern or structural delimiter
    line_after = re.split(r"[\n\|\t]", line_after)[0].strip()
    if len(line_after) > 8:
        return line_after
    return None

def _find_description_in_context(text: str, code: str, code_type: str) -> str | None:
    """
    Scans the full OCR text for a specific code and returns the most descriptive
    nearby context. Prioritizes text immediately preceding the code.
    """
    # Escaping and boundary check
    pattern = re.compile(rf"\b{re.escape(code)}\b")
    best_candidate = None
    
    for m in pattern.finditer(text):
        candidate = _get_description_for_match(text, m.start(), m.end(), code_type)
        if candidate and len(candidate) > 8:
            return candidate
        if candidate and not best_candidate:
            best_candidate = candidate
                
    return best_candidate


def _extract_nearby_context(text: str, match_start: int, code_type: str) -> str:
    """Extracts the phrase immediately preceding an explicitly found code."""
    # Look back up to 80 chars for context
    context = text[max(0, match_start - 80):match_start]
    
    # Strip the label right before the code
    if code_type == "ICD10":
        context = re.sub(r"(?i)\b(?:icd-?10)\s*[:-]?\s*$", "", context).strip()
    elif code_type == "CPT":
        context = re.sub(r"(?i)\b(?:cpt\s*(?:code)?)\s*[:-]?\s*$", "", context).strip()
        
    # Isolate to the current line/field by splitting on common structural delimiters
    parts = re.split(r"[\n\|\t]", context)
    
    if not parts:
        return ""
        
    # Start with the last part (immediate context)
    final_context = parts[-1].strip()
    # Remove leading category noise like "Procedure 1:" or "Diagnosis:"
    final_context = re.sub(r"^(?:diagnosis|dx|impression|procedure|proc)\s*\d*\s*[:-]?\s*", "", final_context, flags=re.IGNORECASE).strip()
    # Also strip stray list artifacts
    final_context = re.sub(r"^\d+[\.\)]\s*", "", final_context).strip()
    
    # If the resulting immediate context is too short (e.g., just "sessions" which overflowed from previous line)
    # AND there is a previous part we can get, grab it and combine.
    if len(final_context) < 15 and len(parts) >= 2:
        prev_part = parts[-2].strip()
        # Clean the previous part same way
        prev_part = re.sub(r"^(?:diagnosis|dx|impression|procedure|proc)\s*\d*\s*[:-]?\s*", "", prev_part, flags=re.IGNORECASE).strip()
        prev_part = re.sub(r"^\d+[\.\)]\s*", "", prev_part).strip()
        
        if prev_part:
            # Combine them. Use a space separated join instead of keeping newlines.
            if final_context:
                 final_context = f"{prev_part} {final_context}"
            else:
                 final_context = prev_part

    return final_context

def _enrich_descriptions_only(
    text: str,
    codes: list[Code],
    seen: set[str],
) -> None:
    """
    Enrich descriptions for codes already extracted by parsed fields.
    
    Unlike _extract_explicit_codes, this function NEVER adds new ICD-10 codes.
    It only improves the description text of codes already in the ``codes`` list
    by scanning the OCR text for richer context near the code occurrence.
    
    CPT codes are still allowed to be added because their extraction has
    stricter guardrails (_CPT_REJECT_PREFIXES, trigger keywords, digit-boundary
    checks) that prevent false positives.
    """
    # 1. Enrich existing ICD descriptions
    for code_obj in codes:
        if code_obj.code_system != "ICD10":
            continue
        if code_obj.description and len(code_obj.description) > 15:
            continue  # already has a good description
        better_desc = _find_description_in_context(text, code_obj.code, "ICD10")
        if better_desc and len(better_desc) > len(code_obj.description or ""):
            code_obj.description = better_desc

    # 2. Still allow CPT codes from explicit text (stricter guardrails apply)
    for m in _CPT_CODE_RE.finditer(text):
        raw_code = m.group(1)
        if raw_code in seen:
            continue

        prefix_window = text[max(0, m.start() - 40):m.start()].lower()
        if any(bad in prefix_window for bad in _CPT_REJECT_PREFIXES):
            continue

        info = lookup_cpt(raw_code)
        if not info and not any(trigger in prefix_window for trigger in _CPT_TRIGGER_KEYWORDS):
            continue

        if (m.start() > 0 and text[m.start() - 1].isdigit()) or (m.end() < len(text) and text[m.end()].isdigit()):
            continue

        seen.add(raw_code)
        desc = _get_description_for_match(text, m.start(), m.end(), "CPT")
        if not desc and info:
            desc = info[1]

        codes.append(Code(
            code=raw_code,
            code_system="CPT",
            description=desc,
            confidence=0.90 if info else 0.60,
            is_primary=not any(c.code_system == "CPT" for c in codes),
            estimated_cost=estimate_cost(raw_code, "CPT"),
        ))


def _extract_explicit_codes(
    text: str,
    codes: list[Code],
    seen: set[str],
) -> None:
    """Find ICD-10 and CPT codes written explicitly in the text."""
    # 1. ICD-10 Extraction
    for m in _ICD_CODE_RE.finditer(text):
        raw_code = m.group(1)
        if raw_code in seen:
            continue
        seen.add(raw_code)
        info = lookup_icd10(raw_code)
        
        # Use localized match to avoid rescanning text (Low Latency)
        desc = _get_description_for_match(text, m.start(), m.end(), "ICD10")
        if not desc and info:
            desc = info[1]

        codes.append(Code(
            code=raw_code,
            code_system="ICD10",
            description=desc,
            confidence=0.95 if info else 0.60,
            is_primary=not any(c.code_system == "ICD10" for c in codes),
            estimated_cost=estimate_cost(raw_code, "ICD10"),
        ))

    # 2. CPT Extraction
    for m in _CPT_CODE_RE.finditer(text):
        raw_code = m.group(1)
        if raw_code in seen:
            continue
            
        # apply guardrails
        prefix_window = text[max(0, m.start() - 40):m.start()].lower()
        if any(bad in prefix_window for bad in _CPT_REJECT_PREFIXES):
            continue

        info = lookup_cpt(raw_code)
        if not info and not any(trigger in prefix_window for trigger in _CPT_TRIGGER_KEYWORDS):
            continue
        
        if (m.start() > 0 and text[m.start() - 1].isdigit()) or (m.end() < len(text) and text[m.end()].isdigit()):
            continue

        seen.add(raw_code)
        
        # Use localized match to avoid rescanning text (Low Latency)
        desc = _get_description_for_match(text, m.start(), m.end(), "CPT")
        if not desc and info:
            desc = info[1]

        codes.append(Code(
            code=raw_code,
            code_system="CPT",
            description=desc,
            confidence=0.90 if info else 0.60,
            is_primary=not any(c.code_system == "CPT" for c in codes),
            estimated_cost=estimate_cost(raw_code, "CPT"),
        ))
