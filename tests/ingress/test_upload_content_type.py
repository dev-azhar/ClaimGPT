"""Regression tests for ingress upload content-type resolution.

Bug: Browsers and curl sometimes send non-standard MIME types (``image/jpg``
instead of ``image/jpeg``) or fall back to ``application/octet-stream`` when
they don't recognise an extension. The pre-fix ingress only matched against
the canonical ``allowed_content_types`` set, so .jpg uploads were rejected
with HTTP 415 even though OCR fully supports them.

These tests pin the new ``_resolve_content_type`` behaviour so the regression
can't return.
"""

from __future__ import annotations

from io import BytesIO

from fastapi import UploadFile
from starlette.datastructures import Headers


def _make_upload(filename: str, content_type: str | None) -> UploadFile:
    headers = Headers({"content-type": content_type}) if content_type else Headers({})
    return UploadFile(filename=filename, file=BytesIO(b"x"), headers=headers)


def test_jpg_with_canonical_mime_accepted() -> None:
    from services.ingress.app.main import _resolve_content_type

    ct, ok = _resolve_content_type(_make_upload("scan.jpg", "image/jpeg"))
    assert ok is True
    assert ct == "image/jpeg"


def test_jpg_with_non_standard_mime_normalised() -> None:
    """Windows / older browsers send ``image/jpg`` — must be accepted."""
    from services.ingress.app.main import _resolve_content_type

    ct, ok = _resolve_content_type(_make_upload("scan.jpg", "image/jpg"))
    assert ok is True
    assert ct == "image/jpeg"


def test_jpg_with_octet_stream_falls_back_to_extension() -> None:
    """curl without ``-H 'Content-Type: image/jpeg'`` sends octet-stream."""
    from services.ingress.app.main import _resolve_content_type

    ct, ok = _resolve_content_type(_make_upload("bill.jpg", "application/octet-stream"))
    assert ok is True
    assert ct == "image/jpeg"


def test_jpeg_with_no_content_type_header_falls_back_to_extension() -> None:
    from services.ingress.app.main import _resolve_content_type

    ct, ok = _resolve_content_type(_make_upload("photo.jpeg", None))
    assert ok is True
    assert ct == "image/jpeg"


def test_legacy_x_png_alias_accepted() -> None:
    from services.ingress.app.main import _resolve_content_type

    ct, ok = _resolve_content_type(_make_upload("scan.png", "image/x-png"))
    assert ok is True
    assert ct == "image/png"


def test_pjpeg_alias_accepted() -> None:
    from services.ingress.app.main import _resolve_content_type

    ct, ok = _resolve_content_type(_make_upload("scan.jpg", "image/pjpeg"))
    assert ok is True
    assert ct == "image/jpeg"


def test_heic_extension_accepted_via_fallback() -> None:
    """iPhone uploads with no content type — should still pass."""
    from services.ingress.app.main import _resolve_content_type

    ct, ok = _resolve_content_type(_make_upload("photo.HEIC", "application/octet-stream"))
    assert ok is True
    assert ct == "image/heic"


def test_unknown_extension_rejected() -> None:
    from services.ingress.app.main import _resolve_content_type

    _ct, ok = _resolve_content_type(_make_upload("payload.exe", "application/octet-stream"))
    assert ok is False


def test_canonical_pdf_accepted() -> None:
    from services.ingress.app.main import _resolve_content_type

    ct, ok = _resolve_content_type(_make_upload("bill.pdf", "application/pdf"))
    assert ok is True
    assert ct == "application/pdf"


def test_jfif_extension_accepted() -> None:
    """.jfif is a JPEG variant some Windows tools produce."""
    from services.ingress.app.main import _resolve_content_type

    ct, ok = _resolve_content_type(_make_upload("scan.jfif", "application/octet-stream"))
    assert ok is True
    assert ct == "image/jpeg"
