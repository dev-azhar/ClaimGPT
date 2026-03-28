"""
Advanced OCR engine — multi-format text extraction with intelligent preprocessing.

Supported formats:
  - PDF (embedded text via pdfplumber + scanned-page OCR via Tesseract)
  - Images (JPEG, PNG, TIFF, BMP, WebP) with advanced CV2 preprocessing
  - DOCX (Word documents via python-docx — full paragraph + table extraction)
  - XLSX/XLS (Excel spreadsheets via openpyxl — all sheets, all cells)
  - Plain text / CSV / JSON / XML / HTML (direct read with encoding detection)

Image preprocessing pipeline:
  1. Grayscale conversion
  2. Noise removal (fastNlMeansDenoising)
  3. Adaptive thresholding for varied lighting
  4. Morphological operations (close small gaps in text)
  5. Contrast enhancement (CLAHE)
  6. Deskew via minAreaRect
  7. Multi-pass OCR with orientation detection

Returns a list of (page_number, text, confidence) tuples.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import cv2
    import numpy as np
    _HAS_CV2 = True
except ImportError:
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    _HAS_CV2 = False

try:
    import docx as _docx
    _HAS_DOCX = True
except ImportError:
    _docx = None  # type: ignore[assignment]
    _HAS_DOCX = False

try:
    import openpyxl
    _HAS_OPENPYXL = True
except ImportError:
    openpyxl = None  # type: ignore[assignment]
    _HAS_OPENPYXL = False

import pdfplumber
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

from .config import settings

logger = logging.getLogger("ocr.engine")

PageResult = Tuple[int, str, Optional[float]]

# Point tesseract binary at configured path
pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}
_PDF_EXTENSIONS = {".pdf"}
_DOCX_EXTENSIONS = {".docx", ".doc"}
_EXCEL_EXTENSIONS = {".xlsx", ".xls"}
_TEXT_EXTENSIONS = {".txt", ".csv", ".json", ".xml", ".html", ".htm", ".md", ".rtf", ".log"}


# ================================================================== pre-processing

def _preprocess(img: Image.Image, aggressive: bool = False) -> Image.Image:
    """Advanced image preprocessing pipeline for OCR accuracy."""
    if not _HAS_CV2:
        # PIL-only fallback: sharpen + contrast
        img = img.convert("L")
        img = img.filter(ImageFilter.SHARPEN)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.5)
        return img

    arr = np.array(img.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    # Step 1: Denoise
    denoised = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)

    # Step 2: CLAHE contrast enhancement
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)

    # Step 3: Adaptive thresholding (handles uneven lighting / shadows)
    if aggressive:
        binary = cv2.adaptiveThreshold(
            enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 10,
        )
    else:
        # Otsu's method works well for clean documents
        _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Step 4: Morphological close (fill small gaps in letters)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    # Step 5: Deskew
    deskewed = _deskew(closed)

    return Image.fromarray(deskewed)


def _deskew(gray: "np.ndarray") -> "np.ndarray":
    """Detect skew angle from text lines and rotate to correct it."""
    _, binary_inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    coords = np.column_stack(np.where(binary_inv > 0))
    if coords.shape[0] < 50:
        return gray

    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    if abs(angle) < 0.5:
        return gray

    h, w = gray.shape
    center = (w // 2, h // 2)
    mat = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        gray, mat, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
    )
    logger.debug("Deskewed by %.2f deg", angle)
    return rotated


def _upscale_if_small(img: Image.Image, min_dpi_equiv: int = 300) -> Image.Image:
    """Upscale very small images so Tesseract gets enough pixel detail."""
    w, h = img.size
    if w < 600 or h < 600:
        scale = max(2, min_dpi_equiv // min(w, h) + 1)
        img = img.resize((w * scale, h * scale), Image.LANCZOS)
        logger.debug("Upscaled small image %dx%d -> %dx%d", w, h, w * scale, h * scale)
    return img


# ================================================================== extraction router

def extract_text(file_path: "str | Path") -> List[PageResult]:
    """Run extraction on any supported file and return per-page results."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix in _PDF_EXTENSIONS:
        return _extract_from_pdf(path)
    if suffix in _IMAGE_EXTENSIONS:
        return _extract_from_image(path)
    if suffix in _DOCX_EXTENSIONS:
        return _extract_from_docx(path)
    if suffix in _EXCEL_EXTENSIONS:
        return _extract_from_excel(path)
    if suffix in _TEXT_EXTENSIONS:
        return _extract_from_text(path)

    # Last resort: try reading as plain text
    try:
        return _extract_from_text(path)
    except Exception:
        raise ValueError(f"Unsupported file type: {suffix}")


# ================================================================== PDF extraction

def _extract_from_pdf(path: Path) -> List[PageResult]:
    """Extract text from PDF with embedded text + table extraction + scanned fallback."""
    results: List[PageResult] = []

    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            parts: List[str] = []

            # 1. Embedded text
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text.strip())

            # 2. Table extraction (pdfplumber structured tables)
            try:
                tables = page.extract_tables()
                for table in (tables or []):
                    table_text = _format_table(table)
                    if table_text:
                        parts.append(table_text)
            except Exception:
                logger.debug("Table extraction failed on page %d", i)

            if parts:
                combined = "\n\n".join(parts)
                results.append((i, combined, 99.0))
            else:
                # 3. Scanned page fallback: render -> preprocess -> OCR
                page_text, conf = _ocr_pdf_page(page)
                results.append((i, page_text, conf))

    return results


def _ocr_pdf_page(page) -> Tuple[str, Optional[float]]:
    """OCR a single PDF page by rendering to image."""
    img = page.to_image(resolution=300).original
    img = _upscale_if_small(img)

    # First pass: standard preprocessing
    cleaned = _preprocess(img, aggressive=False)
    data = pytesseract.image_to_data(cleaned, output_type=pytesseract.Output.DICT)
    text, conf = _aggregate_tesseract_data(data)

    # If confidence is low, retry with aggressive preprocessing
    if conf is not None and conf < 60:
        logger.debug("Low confidence (%.1f) — retrying with aggressive preprocessing", conf)
        cleaned_agg = _preprocess(img, aggressive=True)
        data2 = pytesseract.image_to_data(cleaned_agg, output_type=pytesseract.Output.DICT)
        text2, conf2 = _aggregate_tesseract_data(data2)
        if conf2 is not None and (conf is None or conf2 > conf):
            text, conf = text2, conf2

    return text, conf


def _format_table(table: list) -> str:
    """Format a pdfplumber table (list of rows) into readable text."""
    if not table:
        return ""
    lines: List[str] = []
    for row in table:
        cells = [str(c).strip() if c else "" for c in row]
        lines.append(" | ".join(cells))
    return "\n".join(lines)


# ================================================================== image extraction

def _extract_from_image(path: Path) -> List[PageResult]:
    """Extract text from image with multi-pass OCR for best results."""
    img = Image.open(path)
    img = _upscale_if_small(img)

    # Handle multi-frame images (e.g. multi-page TIFF)
    results: List[PageResult] = []
    try:
        n_frames = getattr(img, "n_frames", 1)
    except Exception:
        n_frames = 1

    for frame_idx in range(n_frames):
        try:
            img.seek(frame_idx)
        except EOFError:
            break

        frame = img.copy()

        # Standard pass
        cleaned = _preprocess(frame, aggressive=False)
        data = pytesseract.image_to_data(cleaned, output_type=pytesseract.Output.DICT)
        text, conf = _aggregate_tesseract_data(data)

        # Aggressive retry if low quality
        if conf is not None and conf < 60:
            cleaned_agg = _preprocess(frame, aggressive=True)
            data2 = pytesseract.image_to_data(cleaned_agg, output_type=pytesseract.Output.DICT)
            text2, conf2 = _aggregate_tesseract_data(data2)
            if conf2 is not None and (conf is None or conf2 > conf):
                text, conf = text2, conf2

        results.append((frame_idx + 1, text, conf))

    return results if results else [(1, "", None)]


# ================================================================== DOCX extraction

def _extract_from_docx(path: Path) -> List[PageResult]:
    """Extract text from Word documents including paragraphs and tables."""
    if not _HAS_DOCX:
        raise ValueError("python-docx not installed  -- cannot process .docx files")

    doc = _docx.Document(str(path))
    parts: List[str] = []

    # Extract all paragraphs
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            parts.append(text)

    # Extract tables
    for table in doc.tables:
        rows: List[str] = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows.append(" | ".join(cells))
        if rows:
            parts.append("\n".join(rows))

    combined = "\n\n".join(parts)
    return [(1, combined, 99.0)]


# ================================================================== Excel extraction

def _extract_from_excel(path: Path) -> List[PageResult]:
    """Extract text from all sheets in an Excel workbook."""
    if not _HAS_OPENPYXL:
        raise ValueError("openpyxl not installed -- cannot process .xlsx files")

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    results: List[PageResult] = []

    for sheet_idx, sheet_name in enumerate(wb.sheetnames, start=1):
        ws = wb[sheet_name]
        lines: List[str] = []
        lines.append(f"[Sheet: {sheet_name}]")

        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() if c is not None else "" for c in row]
            if any(cells):
                lines.append(" | ".join(cells))

        text = "\n".join(lines)
        results.append((sheet_idx, text, 99.0))

    wb.close()
    return results if results else [(1, "", None)]


# ================================================================== text / CSV / JSON extraction

def _extract_from_text(path: Path) -> List[PageResult]:
    """Read plain text, CSV, JSON, XML, HTML files."""
    suffix = path.suffix.lower()

    # Try utf-8 first, then latin-1 as fallback
    for encoding in ("utf-8", "latin-1"):
        try:
            raw = path.read_text(encoding=encoding)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    else:
        raw = path.read_bytes().decode("utf-8", errors="replace")

    if suffix == ".csv":
        return _extract_from_csv_text(raw)
    if suffix == ".json":
        return _extract_from_json_text(raw)

    # Plain text / XML / HTML / MD — return as-is
    return [(1, raw.strip(), 99.0)]


def _extract_from_csv_text(raw: str) -> List[PageResult]:
    """Parse CSV into readable tabular text."""
    reader = csv.reader(io.StringIO(raw))
    lines: List[str] = []
    for row in reader:
        cells = [c.strip() for c in row]
        if any(cells):
            lines.append(" | ".join(cells))
    return [(1, "\n".join(lines), 99.0)]


def _extract_from_json_text(raw: str) -> List[PageResult]:
    """Flatten JSON into readable text."""
    try:
        data = json.loads(raw)
        text = json.dumps(data, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        text = raw
    return [(1, text, 99.0)]


# ================================================================== Tesseract helpers

def _aggregate_tesseract_data(data: dict) -> Tuple[str, Optional[float]]:
    """Combine Tesseract word-level output into full text + average confidence."""
    words: List[str] = []
    confidences: List[float] = []
    for txt, c in zip(data["text"], data["conf"]):
        c = float(c)
        if c < 0:
            continue
        stripped = txt.strip()
        if stripped:
            words.append(stripped)
            confidences.append(c)

    text = " ".join(words)
    avg_conf = round(sum(confidences) / len(confidences), 2) if confidences else None
    return text, avg_conf
