"""Vision-Language Model (VLM) extractor for the parser service.

Why this exists
---------------
Tesseract / PaddleOCR + a text-only LLM struggle with:

* Handwritten claim forms.
* Stamped / signed forms with overlapping text.
* Tables that don't align cleanly when rendered to plain text.
* Photographs of bills taken at angles or with poor lighting.

A vision-language model (VLM) reads the page **image** directly and produces
structured fields. We talk to a local Ollama-compatible endpoint that exposes
multimodal models like ``qwen2-vl`` (https://github.com/ollama/ollama/blob/main/docs/api.md).

How it slots in
---------------
Wired into ``parse_document`` ahead of ``_extract_with_structured_llm``. If
the VLM returns a usable extraction we use it (it's the most accurate path);
otherwise we fall through to the existing structured LLM and heuristic chain.

Activation
----------
``settings.vlm_extraction_enabled`` (default off — the model needs to be
pulled into Ollama first via ``ollama pull qwen2-vl:7b``).

Public API
----------
- ``extract_with_vlm(images: list[PIL.Image]) -> StructuredClaimExtraction | None``
"""

from __future__ import annotations

import base64
import io
import json
import logging
from typing import Any, List
from urllib import error as urlerror, request as urlrequest

from PIL import Image
from pydantic import ValidationError

from .config import settings
from .engine import StructuredClaimExtraction

logger = logging.getLogger("parser.vlm")

_VLM_PROMPT = (
    "You are a medical-claims parser. Look at the attached page image(s) and "
    "extract the structured claim information. Return ONLY a JSON object that "
    "matches this schema (no prose, no markdown):\n"
    '{"patient_name": str|null, "member_id": str|null, "policy_number": str|null,'
    ' "age": int|null, "hospital_name": str|null, "admission_date": str|null,'
    ' "discharge_date": str|null, "primary_diagnosis": str|null,'
    ' "secondary_diagnosis": str|null, "procedures": [str], "treating_doctor": str|null,'
    ' "claimed_total": number|null,'
    ' "bill_line_items": [{"description": str, "category": str|null,'
    ' "quantity": number|null, "unit_price": number|null, "amount": number|null}],'
    ' "notes": str|null, "confidence": "HIGH"|"MEDIUM"|"LOW"}\n'
    "Rules: dates must be ISO YYYY-MM-DD; amounts numeric (no currency symbols, "
    "no commas); empty / unknown fields must be null; never invent values."
)

_MAX_IMAGES = 8  # cap to keep the request small + avoid context overflow
_LOG_UNAVAILABLE_ONCE = False


def _img_to_b64(img: Image.Image) -> str:
    """Encode PIL image as base64 PNG (Ollama vision API expects raw base64)."""
    buf = io.BytesIO()
    rgb = img.convert("RGB")
    rgb.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _post_vlm(images_b64: List[str]) -> str | None:
    """POST to Ollama-compatible /api/generate. Returns the raw model text or None."""
    global _LOG_UNAVAILABLE_ONCE

    payload = {
        "model": settings.vlm_model,
        "prompt": _VLM_PROMPT,
        "images": images_b64,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }

    req = urlrequest.Request(
        settings.vlm_url or settings.llm_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlrequest.urlopen(req, timeout=settings.vlm_timeout_seconds) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        _LOG_UNAVAILABLE_ONCE = False
    except urlerror.URLError as exc:
        if not _LOG_UNAVAILABLE_ONCE:
            logger.warning(
                "VLM endpoint unavailable at %s (%s); skipping VLM step",
                settings.vlm_url or settings.llm_url, exc,
            )
            _LOG_UNAVAILABLE_ONCE = True
        return None
    except Exception:
        logger.exception("VLM call failed")
        return None

    try:
        envelope = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("VLM returned non-JSON envelope")
        return None

    raw = envelope.get("response")
    if not isinstance(raw, str) or not raw.strip():
        logger.warning("VLM envelope missing 'response' field")
        return None
    return raw


def extract_with_vlm(images: List[Image.Image]) -> StructuredClaimExtraction | None:
    """Run a multimodal model over page images and return a structured extraction.

    Returns ``None`` when the feature is disabled, the endpoint is unreachable,
    or the response can't be parsed into ``StructuredClaimExtraction``. Callers
    must fall back to the existing extraction chain.
    """
    if not getattr(settings, "vlm_extraction_enabled", False):
        return None
    if not images:
        return None

    bounded = images[:_MAX_IMAGES]
    logger.info(
        "VLM extraction: model=%s images=%d (capped from %d)",
        settings.vlm_model, len(bounded), len(images),
    )

    try:
        b64_imgs = [_img_to_b64(img) for img in bounded]
    except Exception:
        logger.exception("Failed to encode page images for VLM")
        return None

    raw = _post_vlm(b64_imgs)
    if not raw:
        return None

    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("VLM returned non-JSON response payload")
        return None

    try:
        return StructuredClaimExtraction.model_validate(data)
    except ValidationError as exc:
        logger.warning("VLM payload did not match StructuredClaimExtraction schema: %s", exc)
        return None
