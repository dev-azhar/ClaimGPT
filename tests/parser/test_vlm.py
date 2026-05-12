"""Tests for the VLM extractor (PR #45).

Validates that:
* When ``vlm_extraction_enabled`` is False the extractor short-circuits to None.
* When enabled, it base64-encodes the images, posts to the configured URL,
  and parses the Ollama-style envelope into ``StructuredClaimExtraction``.
* Network errors are swallowed and yield None (caller falls back).
"""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from services.parser.app import vlm
from services.parser.app.config import settings


def _make_image() -> Image.Image:
    return Image.new("RGB", (32, 32), color=(255, 255, 255))


def _ollama_envelope(payload: dict[str, Any]) -> bytes:
    return json.dumps({"model": "qwen2-vl:7b", "response": json.dumps(payload), "done": True}).encode("utf-8")


def test_vlm_disabled_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vlm_extraction_enabled", False)
    assert vlm.extract_with_vlm([_make_image()]) is None


def test_vlm_no_images_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vlm_extraction_enabled", True)
    assert vlm.extract_with_vlm([]) is None


def test_vlm_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vlm_extraction_enabled", True)
    monkeypatch.setattr(settings, "vlm_url", "http://localhost:11434/api/generate")
    monkeypatch.setattr(settings, "vlm_model", "qwen2-vl:7b")

    payload = {
        "patient_name": "Jane Doe",
        "member_id": "MID-123",
        "policy_number": "POL-456",
        "age": 42,
        "hospital_name": "City Hospital",
        "admission_date": "2025-01-10",
        "discharge_date": "2025-01-15",
        "primary_diagnosis": "Acute appendicitis",
        "secondary_diagnosis": None,
        "procedures": ["Appendectomy"],
        "treating_doctor": "Dr. Smith",
        "claimed_total": 24500.50,
        "bill_line_items": [
            {"description": "Room charges", "category": "ROOM", "quantity": 5, "unit_price": 2000, "amount": 10000},
        ],
        "notes": None,
        "confidence": "HIGH",
    }

    fake_resp = MagicMock()
    fake_resp.read.return_value = _ollama_envelope(payload)
    fake_resp.__enter__ = lambda self: self
    fake_resp.__exit__ = lambda self, *a: False

    with patch.object(vlm.urlrequest, "urlopen", return_value=fake_resp) as mocked:
        result = vlm.extract_with_vlm([_make_image()])

    assert result is not None
    assert result.patient_name == "Jane Doe"
    assert result.member_id == "MID-123"
    assert result.claimed_total == 24500.50
    assert result.procedures == ["Appendectomy"]
    assert mocked.call_count == 1


def test_vlm_network_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vlm_extraction_enabled", True)
    from urllib.error import URLError

    with patch.object(vlm.urlrequest, "urlopen", side_effect=URLError("connection refused")):
        result = vlm.extract_with_vlm([_make_image()])

    assert result is None


def test_vlm_invalid_json_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vlm_extraction_enabled", True)

    fake_resp = MagicMock()
    fake_resp.read.return_value = b"not json at all"
    fake_resp.__enter__ = lambda self: self
    fake_resp.__exit__ = lambda self, *a: False

    with patch.object(vlm.urlrequest, "urlopen", return_value=fake_resp):
        result = vlm.extract_with_vlm([_make_image()])

    assert result is None


def test_vlm_image_encoding_roundtrip() -> None:
    """Sanity: _img_to_b64 produces decodable base64 PNG."""
    import base64

    b64 = vlm._img_to_b64(_make_image())
    raw = base64.b64decode(b64)
    img = Image.open(io.BytesIO(raw))
    assert img.size == (32, 32)
    assert img.format == "PNG"
