# Parser & OCR Technical Overview

This document summarizes the end-to-end OCR + parser pipeline, the code locations that implement each stage, and the concrete tools/models used in this repository. It is intentionally concise so you can present it to a manager while still containing the essential implementation details.

---

## High-level flow (steps)

1. Ingest (upload)
   - What: Accept uploaded PDF/image and persist raw file.
   - Where: submission/ingest handlers in `services/submission/app` (upload endpoints and job enqueueing).
   - Notes: Raw file retained for replay and debug dumps (`tmp/parser_debug`).

2. Text extraction (two paths)
   - Decision: try PDF text-layer extraction first; if missing/low-quality -> rasterize + OCR.
   - Tools used (from this repo):
     - `pdfplumber` for PDF text & table extraction (preferred when PDF has a text layer).
    - `easyocr` for image OCR (preferred for scanned images; lazy-initialized in `services/ocr/app/engine.py`).
     - `pdf2image` / `pdftoppm` to rasterize PDF pages when OCR is required.
     - `pytesseract` (Tesseract) as OCR fallback.
     - `paddlepaddle` + `paddleocr` (document parser / VL models) as an alternative OCR / document parser.
     - Image libraries: `Pillow`, `opencv-python-headless`.
   - Where in code:
     - PDF/text first-path and fallback logic: `services/parser/app/main.py`.
     - OCR engine normalization & token helpers: `services/ocr/app/engine.py` (see `_tokens_from_tesseract_data()` and `_tokens_from_paddle_result()`).

3. Token model & grouping into lines
   - What: produce unified token objects: `{text, x0,y0,x1,y1,page,confidence,source}`.
   - Where: `services/ocr/app/engine.py` normalizes engine outputs to this token model.
   - Method: tokens are grouped by `page` and clustered into lines by y-coordinate and sorted by x.

4. Layout / region detection
   - What: split page into meaningful regions (header, patient block, tables, footers) using geometry heuristics.
   - Where: layout helpers in `services/parser/app` (`layout_analyzer.py`, `form_extractor.py`) and orchestration in `services/parser_v2/pipeline.py`.
   - Key heuristics: vertical gaps, token-proximity clustering, column-alignment detection. Table-like regions flagged when numeric density and repeated column structure exist.

5. Table reconstruction
   - What: detect rows/columns within a table region; extract cells and recognize amount-like columns.
   - Where: table reconstruction modules under `services/parser_v2/` (table reconstructor functions called from `pipeline.py`).
   - Methods: vertical projection/clustering for rows; x-center clustering for columns; numeric-density heuristics to identify amount columns.

6. Local PHI extraction (purely local — NO LLM)
   - Goal: deterministically extract sensitive fields (patient name, hospital, doctor, diagnosis, gender, age, admission/discharge dates) without sending PHI to any external model.
   - Where: `services/parser/app/robust_field_extractor.py`.
   - Methods implemented:
     - Reconstruct line-oriented text via `_tokens_to_text()` and run label-anchored regex patterns.
     - `PATTERNS` per field (ordered precision-first); label-on-line or label+value-on-next-line forms.
     - Cleaning helpers: `_clean_person_name()`, `_normalize_date()`, `_normalize_gender()`.
     - Reject-term lists and trimming logic to avoid header fragments (e.g., "INFORMATION", "Date") matching as names.
   - Why local: avoids PHI leakage and satisfies compliance/legal constraints.

7. Semantic (LLM-assisted) table processing — restricted & guarded
   - Purpose: apply semantic models only to candidate expense-style tables to map columns to `(description, category, amount, date)`.
   - Where: `services/parser_v2/semantic_extractor.py` and orchestration in `services/parser_v2/pipeline.py`.
   - Tools / models referenced in config:
     - Configurable semantic backends: `openrouter`, `qwen2-vl`, `layoutlmv3`, `florence-2`, `donut`, `ollama` (see `services/parser/app/config.py`).
     - VLM code model used/configured: `paddleocr-vl-1.5-doc-parser` (config option `vlm_code_model_version`).
     - Local LLM endpoint settings: `llm_url` and `llm_model` (e.g. Ollama-compatible).
   - Safeguards:
     - Only call semantic extractor on tables that meet expense heuristics (numeric density, column pattern).
     - Apply `NON_EXPENSE_KEYWORDS` blacklist to semantic outputs (e.g., "Claim Amount Requested", "ICD-10", "Sum Insured") to drop metadata rows.
     - Post-call dedupe and aggregate-row removal (pipeline-level AGGREGATE_KEYWORDS).

8. Schema normalization & canonicalization
   - What: normalize raw fields and table rows into a canonical claim schema (dates normalized to ISO, amounts to numeric cents, field-name mapping).
   - Where: `services/parser_v2/schema_normalizer.py` and final assembly in `services/parser_v2/pipeline.py`.
   - Tasks: mapping form keys → canonical keys, stripping currency formatting, parsing dates, filtering blacklisted descriptions, merging fuzzy duplicates.

9. Persistence & renderer input
   - Canonical JSON: built by the pipeline and saved to the Claim record as `claim.canonical_json` (used by preview & PDF renderer).
   - Where: persistence and preview endpoints in `services/submission/app/main.py`.
   - UI save flows:
     - UI edits write `ParsedField` rows; on save endpoints the server now deletes existing expense-like `ParsedField` rows, inserts updated ones, and rebuilds `claim.canonical_json` from `ParsedField` rows to ensure preview/PDF reflect edits.
     - UI file: `ui/web/src/app/page.tsx` ensures `loadPreview()` is called after saves to refresh the preview.

10. Debug artifacts & testing
    - Regression test for local extractor: `tests/test_robust_extractor.py`.
    - Replayable debug dumps: `tmp/parser_debug/*` contain `renderer_input.json`, `canonical_claim.json`, and intermediate artifacts for failing claims.

---

## Concrete tools & packages used (found in `requirements.txt` / repo)
- PDF & image processing
  - `pdfplumber` — preferred for PDFs with an embedded text layer and for table extraction.
  - `pdf2image` — to rasterize PDF pages when OCR is needed.
  - `Pillow`, `opencv-python-headless` — image ops and pre-processing.

- OCR engines
  - `pytesseract` (Tesseract) — fallback OCR engine; normalized into tokens by `_tokens_from_tesseract_data()` in `services/ocr/app/engine.py`.
  - `paddlepaddle` + `paddleocr` — alternative OCR/document parsing (structured outputs, VL models); normalized via `_tokens_from_paddle_result()`.
  - `easyocr` — preferred for general image OCR in this project when enabled; the repo supports lazy initialization (`_ensure_easyocr_reader()`) in `services/ocr/app/engine.py` and environment flags (`OCR_EASYOCR_ENABLED`).

- Token normalization
  - `services/ocr/app/engine.py` provides helpers to convert engine outputs into repository's token format: `{text, x0,y0,x1,y1,page,confidence,source}`.

- Semantic / ML models (configurable/backends)
  - Layout/vision models: `microsoft/layoutlmv3-base` may be used when configured (`layoutlm_model` in config).
  - Paddle OCR VLM code model: `paddleocr-vl-1.5-doc-parser` (configured as `vlm_code_model_version`).
  - Config supports routing to external semantic backends (OpenRouter, Qwen2-VL, Florence, Donut, Ollama). These are optional/configurable via `services/parser/app/config.py`.

- Other
  - `fpdf2` — PDF generation for renderer.
  - `llama-cpp-python` and other LLM libs may be present to support local model hosting (configurable).

---

## Quick edit map (where to change behavior)
- Tighten PHI regex / name cleaning: edit `services/parser/app/robust_field_extractor.py` (`PATTERNS`, `_clean_person_name()`, reject lists).
- Change PDF vs OCR decision or add engine: edit `services/parser/app/main.py` (text-extraction routing) and `services/ocr/app/engine.py` normalization.
- Adjust table detection thresholds: edit table reconstructor modules under `services/parser_v2/` and `pipeline.py` thresholds.
- Add or change expense blacklists: edit `services/parser_v2/schema_normalizer.py` and `services/parser_v2/semantic_extractor.py` (`NON_EXPENSE_KEYWORDS` and `AGGREGATE_KEYWORDS`).
- Alter persistence/save behavior: edit `services/submission/app/main.py` (endpoints that rebuild `claim.canonical_json`).
- UI refresh after save: edit `ui/web/src/app/page.tsx` (call `loadPreview()` after successful save).

---

## Verification checklist (quick)
- Run `pytest tests/test_robust_extractor.py` — ensures local extractor regex suite passes.
- Reparse specific debug claims: use the parse entrypoint that writes `tmp/parser_debug/*` and validate `canonical_claim.json` and `normalized_expenses`.
- After UI saves edits, call preview endpoint and verify `claim.canonical_json` includes the updates.
- Inspect server logs on `/claims/{id}/expenses` save for deleted/created counts (added for debugging).

---

## Suggested next deliverables (I can produce)
- A slightly longer `docs/parser_technical_deepdive.md` with exact regex literals and key function signatures pulled directly from the code.
- A short slide deck summarizing risks (PHI leakage), safeguards (local-only extractor), and required environment (Tesseract, Paddle, Poppler for `pdf2image`).

---

Document generated on: May 14, 2026

