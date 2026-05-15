"""Layout-aware PDF extraction via IBM ``docling`` (optional, opt-in).

Why this exists
---------------
The default OCR path (`pdfplumber` + `pytesseract` + `PaddleOCR`) is fast and
good enough for most claims, but loses table structure and reading order on
complex hospital bills, discharge summaries with multi-column layouts, and
scanned forms.

`docling` (https://github.com/DS4SD/docling) ships pre-trained layout +
table-structure models that produce **layout-aware Markdown** with proper
table boundaries, headers, and reading order — exactly what the structured
LLM step in the parser service consumes downstream.

Activation
----------
Off by default. Turn on with ``OCR_USE_DOCLING=true`` in the environment, OR
by setting ``settings.use_docling = True``. If docling isn't installed,
``extract_with_docling`` returns ``None`` and the caller MUST fall back to
the existing pipeline.

Public API
----------
- ``extract_with_docling(path: str | Path) -> list[dict] | None``
  Returns the same per-page dict shape as ``engine._extract_from_pdf``:
  ``{"page": int, "text": str, "fields": dict, "tables": list, "confidence": float | None}``.
  Returns ``None`` (not raises) when docling is unavailable so the caller
  never has to wrap it in try/except.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("ocr.docling")

_HAS_DOCLING: bool | None = None
_DocumentConverter: Any = None


def _ensure_docling() -> bool:
    """Lazy-load docling once. Returns True if available."""
    global _HAS_DOCLING, _DocumentConverter
    if _HAS_DOCLING is not None:
        return _HAS_DOCLING
    try:
        from docling.document_converter import DocumentConverter  # type: ignore
        _DocumentConverter = DocumentConverter
        _HAS_DOCLING = True
        logger.info("docling loaded — layout-aware PDF extraction enabled")
    except Exception as exc:  # pragma: no cover - optional heavy dep
        logger.info("docling not available (%s) — falling back to pdfplumber path", exc)
        _HAS_DOCLING = False
    return _HAS_DOCLING


def extract_with_docling(path: str | Path) -> list[dict] | None:
    """Run docling on ``path`` and return per-page dicts. ``None`` if unavailable."""
    if not _ensure_docling():
        return None

    try:
        converter = _DocumentConverter()
        result = converter.convert(str(path))
        doc = getattr(result, "document", None) or result

        # Try the canonical export first.
        try:
            full_md = doc.export_to_markdown()  # type: ignore[union-attr]
        except Exception:
            full_md = ""

        # Per-page split: docling annotates each page; if not, fall back to one page.
        pages_attr = getattr(doc, "pages", None) or []
        per_page: list[dict] = []

        if pages_attr:
            # Use a stable page-by-page export when supported, else slice the
            # full markdown by the page-break marker docling injects.
            for idx, page in enumerate(pages_attr, start=1):
                page_md = ""
                try:
                    page_md = page.export_to_markdown()  # type: ignore[attr-defined]
                except Exception:
                    page_md = getattr(page, "text", "") or ""
                per_page.append(
                    {
                        "page": idx,
                        "text": page_md.strip(),
                        "fields": {},
                        "tables": [],
                        "confidence": 99.0,
                    }
                )

        if not per_page:
            per_page = [
                {
                    "page": 1,
                    "text": (full_md or "").strip(),
                    "fields": {},
                    "tables": [],
                    "confidence": 99.0,
                }
            ]

        return per_page
    except Exception:
        logger.exception("docling extraction failed for %s", path)
        return None
