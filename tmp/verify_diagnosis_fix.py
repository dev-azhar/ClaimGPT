"""
Live verification for the diagnosis-narrative ICD bug.

Reproduces the screenshot scenario: the parser hands a single
``diagnosis`` field whose value is the entire 800-char admission note.
Before the fix this returned D65 (DIC) at 90% confidence with the whole
narrative as the rendered description. After the fix the description
should be a short clean phrase and the codes should map to obstetric
delivery (O80 / Z37.x / O75.x) rather than coagulation disorders.

Run:
    PYTHONPATH=. python tmp/verify_diagnosis_fix.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

# Force the deterministic fallback in this verification script so it runs
# without a live Ollama instance. The same code path is used in
# production whenever the LLM is unreachable, so this is a meaningful
# floor on quality.
os.environ.setdefault("CODING_LLM_DIAGNOSIS_ENABLED", "true")

from services.coding.app.diagnosis_extractor import (  # noqa: E402
    extract_diagnosis_keywords,
    needs_extraction,
)
from services.coding.app.engine import _extract_from_parsed_fields  # noqa: E402


NARRATIVE = (
    "G3P1L1A1 39WKS ZDAYS PREGNANCY IN LABOUR FTND C EPISIOTOMY ON 09/04/2026 "
    "AT 6 2aRM MALE BABYOF WT 2.8KG. Vitals: BP-121/83 mmHg P-88/m RR-16/m "
    "Temp afebrile. General examination fair. Systemic exam clear. "
    "Obstetric history: previous full term normal delivery 2018, abortion "
    "2020, current pregnancy uneventful, regular ANC, all investigations "
    "within normal limits. HBsAg-NR HIV-NR VDRL-NR. Plan: continue "
    "monitoring, antibiotic cover, suture care, discharge after 48 hours."
)


def main() -> int:
    print("=" * 70)
    print("Input length:", len(NARRATIVE), "chars")
    print("Needs extraction:", needs_extraction(NARRATIVE))
    print("-" * 70)

    keywords = extract_diagnosis_keywords(NARRATIVE)
    print("Extracted keywords:")
    for k in keywords:
        print(f"  - {k}")
    print("-" * 70)

    out = _extract_from_parsed_fields(
        parsed_fields=[
            {"field_name": "diagnosis", "field_value": NARRATIVE}
        ],
        full_text=NARRATIVE,
    )
    print("Returned codes:")
    bad = []
    for c in out.codes:
        print(
            f"  {c.code:<10} system={c.code_system} primary={c.is_primary} "
            f"conf={c.confidence:.2f} desc={c.description!r}"
        )
        if c.code == "D65":
            bad.append("D65 (DIC) is back — fix regressed")
        if c.description and len(c.description) > 200:
            bad.append(
                f"description for {c.code} is {len(c.description)} chars — "
                f"narrative leaked into description again"
            )

    print("-" * 70)
    if bad:
        for b in bad:
            print("FAIL:", b)
        return 1
    print("OK — no D65, no long-narrative descriptions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
