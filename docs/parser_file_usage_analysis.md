# Parser Service File Usage Analysis

Analysis Date: May 14, 2026

This document maps all files in `services/parser/` and `services/parser_v2/` and identifies which are actively used in the current parsing pipeline.

---

## Executive Summary

- **Parser v2 (parser_v2/)**: All 13 files are actively used in the main pipeline.
- **Parser (parser/app/)**: 
  - **Core actively used**: 20 files (main, config, db, models, engine, forms, schema, NER, field resolver, **bill_parser, discharge_parser, lab_parser, prescription_parser, form_extractor, robust_field_extractor, lightweight_ner, schema_normalizer, table_extractor**)
  - **Obsolete layout engines**: 4 files (layout_analyzer, layout_analyzer_lightweight, layout_engine, zoning_engine) - **not used** in current pipeline

---

## Detailed File-by-File Analysis

### `services/parser_v2/` Directory (13 files)

**Status: ALL ACTIVE** ✓

| File | Purpose | Used By | Status |
|------|---------|---------|--------|
| `pipeline.py` | Main orchestrator (parse entry point) | Imported by `parser/app/main.py` as `parse_v2` | ✓ ACTIVE |
| `models.py` | Token, Region, DocumentStructure, TableRegion models | All other parser_v2 files | ✓ ACTIVE |
| `layout_detector.py` | Detect regions (header, body, tables) via geometry | `pipeline.py` | ✓ ACTIVE |
| `region_classifier.py` | Classify regions by type (table, form, body) | `layout_detector.py` | ✓ ACTIVE |
| `geometry_utils.py` | Bbox, line grouping, token clustering helpers | `layout_detector.py`, `table_reconstructor.py`, `form_extractor.py` | ✓ ACTIVE |
| `table_reconstructor.py` | Reconstruct table rows/columns from token clusters | `pipeline.py` | ✓ ACTIVE |
| `form_extractor.py` | Extract form fields from regions | `pipeline.py` | ✓ ACTIVE |
| `schema_normalizer.py` | Normalize fields/tables to canonical schema; blacklist filtering | `pipeline.py`, `semantic_extractor.py` | ✓ ACTIVE |
| `semantic_extractor.py` | Call semantic backends for expense table interpretation | `pipeline.py` | ✓ ACTIVE |
| `semantic_backends.py` | Registry of semantic backends (OpenRouter, Qwen, LayoutLMv3, etc) | `semantic_extractor.py` | ✓ ACTIVE |
| `semantic_models.py` | Pydantic models for semantic backend outputs | `semantic_backends.py` | ✓ ACTIVE |
| `debug_overlay.py` | Generate visual debug overlays of detected regions/tables | `pipeline.py` | ✓ ACTIVE |
| `document_processor.py` | Document-level orchestration (model-assisted region detection) | `pipeline.py` (fallback path) | ✓ ACTIVE |

---

### `services/parser/app/` Directory (23 files)

#### ACTIVE / CORE (Imported and Used) ✓

| File | Purpose | Used By | Status |
|------|---------|---------|--------|
| `main.py` | FastAPI entry point, claim upload, parse job endpoints | API consumers | ✓ ACTIVE |
| `config.py` | Settings (model paths, LLM endpoints, feature flags) | `main.py`, `db.py`, entire codebase | ✓ ACTIVE |
| `db.py` | Database setup, session management, health checks | `main.py` | ✓ ACTIVE |
| `models.py` | SQLAlchemy models (Claim, Document, ParseJob, ParsedField, etc) | `main.py`, database layer | ✓ ACTIVE |
| `schemas.py` | Pydantic schemas (ParseJobOut, ParseResultOut, etc) | `main.py` (API responses) | ✓ ACTIVE |
| `engine.py` | Parse orchestration (calls document classifier, specific parsers) | `main.py` (parse_document call) | ✓ ACTIVE |
| `field_resolver.py` | Field reconciliation logic (merge, choose best field value) | `main.py` (field resolution endpoints) | ✓ ACTIVE |
| `form_extractor.py` | Extract form-like fields from regions | `engine.py`, `bill_parser.py`, `discharge_parser.py`, `lab_parser.py`, `prescription_parser.py`, `parser_v2/pipeline.py` | ✓ ACTIVE |
| `robust_field_extractor.py` | Regex-based PHI extraction (patient, hospital, diagnosis, etc) | `parser_v2/pipeline.py` (local extraction) | ✓ ACTIVE |
| `lightweight_ner.py` | Named entity extraction (lightweight alternative to scispacy) | `main.py` (extract_ner_entities call) | ✓ ACTIVE |
| `schema_normalizer.py` | Normalize field/table values to canonical types | `main.py` (build_canonical_schema call) | ✓ ACTIVE |
| `table_extractor.py` | Extract rows/columns from table regions | `bill_parser.py`, `discharge_parser.py`, `lab_parser.py`, `prescription_parser.py` | ✓ ACTIVE |
| `bill_parser.py` | Extracts fields/tables from bill documents | `engine.py` | ✓ ACTIVE |
| `discharge_parser.py` | Extracts fields/tables from discharge summary | `engine.py` | ✓ ACTIVE |
| `lab_parser.py` | Extracts fields/tables from lab reports | `engine.py` | ✓ ACTIVE |
| `prescription_parser.py` | Extracts fields/tables from prescriptions | `engine.py` | ✓ ACTIVE |
| `document_classifier.py` | Classify document type (bill, discharge, lab, prescription, etc) | `engine.py` | ✓ ACTIVE |


#### OBSOLETE / NOT USED ✗

| File | Purpose | Used By | Status | Notes |
|------|---------|---------|--------|-------|
| `layout_analyzer.py` | Old geometric layout detection | **NONE** | ✗ UNUSED | Replaced by `parser_v2/layout_detector.py` |
| `layout_analyzer_lightweight.py` | Lightweight layout analyzer variant | **NONE** | ✗ UNUSED | Replaced by parser_v2 |
| `layout_engine.py` | Older layout processing engine | **NONE** | ✗ UNUSED | Obsolete; replaced by parser_v2 |
| `zoning_engine.py` | Page zoning logic (old approach) | **NONE** | ✗ UNUSED | Replaced by parser_v2/layout_detector.py |

---

## Pipeline Flow (Which Services Are Called)

### Main Parsing Path: `parser/app/main.py` → `parser/app/engine.py` → `parser_v2/pipeline.py`

1. **Ingest** (main.py):
   - Receives file upload
   - Extracts OCR tokens (via OCR service in `services/ocr/app/engine.py`)
   - Enqueues parse job

2. **Route** (engine.py):
   - Calls `document_classifier.classify_document(...)` to detect doc type
   - Conditionally calls type-specific parser (bill_parser, discharge_parser, etc) **OR**
   - Skips to parser_v2 if configured

3. **Parse V2** (parser_v2/pipeline.py) — **PRIMARY ACTIVE PATH**:
   - Detects regions → tables → local fields (robust_field_extractor.py)
   - Reconstructs tables, classifies regions
   - Normalizes schema, calls semantic backends for expense tables
   - Builds canonical_claim JSON

4. **Persist** (main.py / submission service):
   - Saves ParsedField rows
   - Rebuilds canonical_json for rendering

---

## Recommendations

### Files to Remove (Unused/Obsolete)

**Safe to delete immediately** (no active imports, replaced by parser_v2):
- `services/parser/app/layout_analyzer.py` ✗
- `services/parser/app/layout_analyzer_lightweight.py` ✗
- `services/parser/app/layout_engine.py` ✗
- `services/parser/app/zoning_engine.py` ✗

All 20 other files in `services/parser/app/` are actively used and should be retained.

---

## Current Architecture (What's Actually Running)

The **current active pipeline** uses:

```
File Upload
    ↓
parser/app/main.py (FastAPI entry)
    ↓
parser/app/engine.py (parse_document)
    ↓
parser_v2/pipeline.py (parse_v2) ← PRIMARY
    ├→ layout_detector.py (detect regions)
    ├→ region_classifier.py (classify region types)
    ├→ table_reconstructor.py (reconstruct tables)
    ├→ form_extractor.py (extract form fields)
    ├→ robust_field_extractor.py (local PHI extraction)
    ├→ schema_normalizer.py (normalize to canonical)
    ├→ semantic_extractor.py (expense table interpretation)
    │   ├→ semantic_backends.py (route to LLM)
    │   └→ semantic_models.py (parse semantic output)
    ├→ debug_overlay.py (debug artifacts)
    └→ document_processor.py (model-assisted path)
    ↓
services/submission/app/main.py (persist + render)
```

---

## Files Actually in Use (Summary for Manager)

**Parser V2**: All 13 files active in the production pipeline.

**Parser V1**: Core files (main, engine, config, db, models, schemas, field_resolver, form_extractor, robust_field_extractor, lightweight_ner) are active. Document-specific parsers (bill, discharge, lab, prescription) are conditionally used if document classification is enabled. Layout engines (layout_analyzer*, layout_engine, zoning_engine) are **obsolete** and should be removed.

---

Generated: May 14, 2026
