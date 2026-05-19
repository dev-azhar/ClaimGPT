"""Tests for ICD preview ordering and truncation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "submission"))
for _k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]

from app.main import _sort_icd_codes


class _Code:
    def __init__(self, code, confidence, estimated_cost, is_primary=False):
        self.code_system = "ICD10"
        self.code = code
        self.confidence = confidence
        self.estimated_cost = estimated_cost
        self.is_primary = is_primary


def test_sort_icd_codes_prioritizes_primary_then_confidence_and_limits_applied_by_caller():
    codes = [
        _Code("A90", 0.72, 100),
        _Code("A91", 0.91, 200, True),
        _Code("R50.9", 0.50, 50),
        _Code("B34.9", 0.88, 75),
    ]

    ordered = _sort_icd_codes(codes)

    assert [c.code for c in ordered] == ["A91", "B34.9", "A90", "R50.9"]
    assert ordered[:3][0].is_primary is True
