"""
Ingest ICD-10 PDF(s) and build a FAISS + BM25 index compatible with
services.coding.app.icd10_rag.

Drop one or more PDFs into: services/coding/app/rag_data/input/
Run locally (in the project venv) to parse and build the index.

Usage:
    python -m services.coding.app.scripts.ingest_icd_pdf   # picks all PDFs in input/
    python -m services.coding.app.scripts.ingest_icd_pdf --file icd10_official_2026.pdf

Requirements
- PyPDF2 or pdfminer.six for PDF text extraction
- sentence-transformers, faiss-cpu, rank_bm25 (same deps as icd10_rag.build_index)

The script is intentionally conservative: it looks for ICD-like code tokens at
line starts and aggregates wrapped descriptions until the next code line.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import re
import sys
from typing import List

logger = logging.getLogger("ingest_icd_pdf")
logging.basicConfig(level=logging.INFO)

PDF_INPUT_DIR = pathlib.Path(__file__).parent.parent / "rag_data" / "input"
PDF_INPUT_DIR.mkdir(parents=True, exist_ok=True)

# ICD-ish code pattern: letter + 2 digits, optional dot+digits, optional trailing alphanum
_CODE_RE = re.compile(r"^\s*([A-Z]\d{2}(?:\.\d+)?[A-Z0-9]*)\b", re.IGNORECASE)


def extract_text_from_pdf(path: pathlib.Path) -> str:
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(path))
        pages = []
        for p in reader.pages:
            try:
                pages.append(p.extract_text() or "")
            except Exception:
                pages.append("")
        return "\n".join(pages)
    except Exception:
        # fallback to pdfminer
        try:
            from pdfminer.high_level import extract_text
            return extract_text(str(path))
        except Exception as e:
            logger.error("No PDF extractor available: %s", e)
            raise


def parse_icd_lines(text: str) -> List[dict]:
    entries: List[dict] = []
    lines = [l.rstrip() for l in text.splitlines()]

    cur_code = None
    cur_desc_parts: List[str] = []

    def flush_current():
        nonlocal cur_code, cur_desc_parts
        if cur_code:
            desc = " ".join(p for p in cur_desc_parts if p).strip()
            if desc:
                entries.append({"code": cur_code.upper(), "description": desc})
            cur_code = None
            cur_desc_parts = []

    for line in lines:
        if not line:
            continue
        m = _CODE_RE.match(line)
        if m:
            # new code line
            flush_current()
            cur_code = m.group(1)
            # description is remainder of line after the code token
            rest = line[m.end():].strip(" -:;\t")
            if rest:
                cur_desc_parts = [rest]
            else:
                cur_desc_parts = []
        else:
            # continuation of previous description
            if cur_code:
                cur_desc_parts.append(line.strip())
            else:
                # lines before the first code — ignore
                continue
    flush_current()
    return entries


def build_index_from_entries(entries: List[dict]) -> bool:
    """Create FAISS + BM25 artifacts using the same format as icd10_rag.build_index.

    This function mirrors the final embedding + index write steps from
    services.coding.app.icd10_rag but operates on the parsed PDF entries.
    """
    try:
        import faiss
    except Exception:
        logger.error("faiss is not installed in the environment. Install faiss-cpu.")
        return False

    # Import the icd10_rag helpers for consistency
    try:
        from services.coding.app import icd10_rag
    except Exception as e:
        logger.error("Failed to import icd10_rag module: %s", e)
        return False

    model = icd10_rag._load_model()
    if model is None:
        logger.error("Embedding model unavailable (sentence-transformers missing)")
        return False

    data_dir = pathlib.Path(icd10_rag._DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Normalize entries: ensure code/description
    normalized = []
    for e in entries:
        if not e.get("code") or not e.get("description"):
            continue
        code = e["code"].strip()
        desc = e["description"].strip()
        cat = icd10_rag._code_to_category(code)
        normalized.append({"code": code, "description": desc, "category": cat, "synonyms": []})

    if not normalized:
        logger.error("No ICD entries parsed from PDF(s). Aborting.")
        return False

    texts = [icd10_rag._build_texts_for_code(e["code"], e["description"], e["category"], e.get("synonyms", [])) for e in normalized]

    logger.info("Embedding %d parsed ICD entries...", len(texts))
    vectors = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)

    import numpy as np
    vectors = np.array(vectors, dtype=np.float32)

    idx = faiss.IndexFlatIP(vectors.shape[1])
    idx.add(vectors)

    faiss.write_index(idx, str(icd10_rag._ICD10_INDEX_PATH))
    with open(icd10_rag._ICD10_META_PATH, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)

    # BM25
    try:
        from rank_bm25 import BM25Okapi
    except Exception:
        logger.error("rank_bm25 not installed. Install rank-bm25 to build BM25 index.")
        return False

    tokens = [icd10_rag._tokenize(t) for t in texts]
    bm25 = BM25Okapi(tokens)
    import pickle
    with open(icd10_rag._ICD10_BM25_PATH, "wb") as f:
        pickle.dump(bm25, f, protocol=pickle.HIGHEST_PROTOCOL)

    logger.info("Wrote FAISS index and meta to %s", data_dir)

    # Refresh module globals
    icd10_rag._load_indices()
    return True


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--file", "-f", help="Specific PDF filename in the input directory to ingest")
    p.add_argument("--input-dir", default=str(PDF_INPUT_DIR), help="Input dir with PDFs")
    args = p.parse_args(argv)

    input_dir = pathlib.Path(args.input_dir)
    if not input_dir.exists():
        logger.error("Input dir not found: %s", input_dir)
        return 2

    if args.file:
        files = [input_dir / args.file]
    else:
        files = sorted(input_dir.glob("*.pdf"))

    if not files:
        logger.error("No PDF files found in %s", input_dir)
        return 2

    total_parsed = []
    for f in files:
        logger.info("Extracting text from %s", f)
        try:
            text = extract_text_from_pdf(f)
        except Exception as e:
            logger.exception("Failed to extract PDF text: %s", e)
            continue
        entries = parse_icd_lines(text)
        logger.info("Parsed %d candidate entries from %s", len(entries), f)
        total_parsed.extend(entries)

    if not total_parsed:
        logger.error("No entries parsed from any PDF. Inspect PDF format and extraction results.")
        return 1

    ok = build_index_from_entries(total_parsed)
    if not ok:
        logger.error("Index build failed")
        return 1
    logger.info("Index build succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
