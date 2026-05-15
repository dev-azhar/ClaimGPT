"""
LLM-assisted narrative consistency check.

The local LLM is asked to compare the structured claim payload
against any free-text narrative (chief complaint, discharge summary
snippet, etc.) and return a JSON verdict. The result is folded into
the hybrid fraud score with a small weight.

This layer is OFF by default (FRAUD_LLM_ENABLED=false) because it
adds latency and depends on a local model being available.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("fraud.llm")


_NARRATIVE_KEYS = (
    "chief_complaint",
    "clinical_diagnosis",
    "discharge_summary",
    "history_of_present_illness",
    "treatment_summary",
    "doctor_notes",
    "operative_notes",
)


def _gather_narrative(field_map: dict[str, Any]) -> str:
    parts: list[str] = []
    for k in _NARRATIVE_KEYS:
        v = field_map.get(k)
        if v:
            parts.append(f"{k}: {v}")
    return "\n".join(parts).strip()


def assess_narrative(
    field_map: dict[str, Any],
    codes: list[dict[str, Any]],
) -> tuple[float, list[dict[str, Any]]]:
    """
    Returns (llm_score in [0,1], list of indicators).
    Score 0 = consistent / no fraud signal; 1 = strongly suspicious.
    Returns (0.0, []) if narrative is missing or LLM unavailable.
    """
    narrative = _gather_narrative(field_map)
    if not narrative:
        return 0.0, []

    try:
        from libs.shared.local_llm import generate_semantic_json
    except Exception:
        logger.debug("local_llm not available — skipping LLM narrative check")
        return 0.0, []

    primary_dx = field_map.get("primary_diagnosis") or field_map.get("diagnosis") or ""
    icd_codes = ", ".join(c["code"] for c in codes if c.get("code_system") == "ICD10") or "—"
    cpt_codes = ", ".join(c["code"] for c in codes if c.get("code_system") == "CPT") or "—"

    prompt = (
        "Assess the following medical claim for narrative inconsistency that may "
        "indicate fraud. Compare the free-text narrative to the structured "
        "diagnosis and procedure codes. Look for: contradictions, copy-paste "
        "language, generic boilerplate, dates that don't match, treatments not "
        "supported by the diagnosis.\n\n"
        f"Primary diagnosis: {primary_dx}\n"
        f"ICD-10 codes: {icd_codes}\n"
        f"CPT codes: {cpt_codes}\n"
        f"Narrative:\n{narrative}\n\n"
        "Return JSON only."
    )
    schema = {
        "suspicion_score": "float in [0,1]",
        "reasons": ["short string", "..."],
        "verdict": "CONSISTENT | MINOR_INCONSISTENCY | LIKELY_INCONSISTENT",
    }

    try:
        result = generate_semantic_json(prompt, schema=schema, max_tokens=300, temperature=0.0)
    except Exception:
        logger.exception("LLM narrative assessment failed")
        return 0.0, []

    if not result:
        return 0.0, []

    raw_score = result.get("suspicion_score")
    try:
        score = max(0.0, min(1.0, float(raw_score)))
    except (TypeError, ValueError):
        score = 0.0

    reasons = result.get("reasons") or []
    indicators: list[dict[str, Any]] = []
    if score >= 0.4 and reasons:
        indicators.append({
            "code": "L-NAR-01",
            "name": "LLM narrative inconsistency",
            "layer": "llm",
            "severity": "HIGH" if score >= 0.7 else "WARN",
            "weight": score,
            "message": "; ".join(str(r) for r in reasons[:3]),
            "evidence": {"verdict": result.get("verdict")},
        })

    return round(score, 4), indicators
