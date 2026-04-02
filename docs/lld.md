# ClaimGPT — Low-Level Design (LLD)

## Table of Contents

1. [Ingress Service](#1-ingress-service)
2. [OCR Service](#2-ocr-service)
3. [Parser Service](#3-parser-service)
4. [Coding Service](#4-coding-service)
5. [Predictor Service](#5-predictor-service)
6. [Validator Service](#6-validator-service)
7. [Workflow Service](#7-workflow-service)
8. [Submission Service](#8-submission-service)
9. [Chat Service](#9-chat-service)
10. [Search Service](#10-search-service)
11. [Shared Libraries](#11-shared-libraries)
12. [Database Schema](#12-database-schema)

---

## 1. Ingress Service

**Route Prefix:** `/ingress` · **Port:** 8001

### Purpose

Handles multi-file claim uploads, document storage, and claim lifecycle management.

### Files

| File          | Responsibility                          |
| ------------- | --------------------------------------- |
| `main.py`     | FastAPI router, endpoints, background tasks |
| `config.py`   | Settings (max upload 50 MB, 19 MIME types) |
| `models.py`   | `Claim`, `Document` SQLAlchemy models   |
| `schemas.py`  | `ClaimOut`, `DocumentOut`, `ClaimListOut`|
| `db.py`       | Session factory, engine setup           |

### Configuration

```
INGRESS_DATABASE_URL        = postgresql://...
INGRESS_MAX_UPLOAD_BYTES    = 52428800  (50 MB)
INGRESS_STORAGE_ROOT        = ./storage/raw
INGRESS_WORKFLOW_URL        = http://localhost:8000/workflow
```

**Allowed content types (19):** PDF, JPEG, PNG, TIFF, BMP, WebP, GIF, DOCX, DOC, XLSX, XLS, CSV, TXT, JSON, XML, HTML, RTF, ODT, ODS

### Database Models

```
Claim
├── id: UUID (PK, auto-generated)
├── policy_id: Text (nullable)
├── patient_id: Text (nullable)
├── status: Text (default="UPLOADED")
├── source: Text (default="PATIENT")
├── created_at: DateTime (server_default=now())
├── updated_at: DateTime (auto-updated)
└── documents: List[Document]  (one-to-many)

Document
├── id: UUID (PK)
├── claim_id: UUID (FK → claims.id)
├── file_name: Text
├── file_type: Text (MIME type)
├── minio_path: Text (actual disk path)
└── uploaded_at: DateTime (server_default=now())
```

### Endpoints

| Method   | Path                            | Status | Description                     |
| -------- | ------------------------------- | ------ | ------------------------------- |
| `GET`    | `/health`                       | 200    | DB connectivity check           |
| `POST`   | `/claims`                       | 201    | Upload claim with files         |
| `POST`   | `/claims/{id}/documents`        | 201    | Add documents to existing claim |
| `GET`    | `/claims`                       | 200    | List claims (paginated)         |
| `GET`    | `/claims/{id}`                  | 200    | Get claim detail                |
| `GET`    | `/claims/{id}/file`             | 200    | Download original file          |
| `GET`    | `/claims/{id}/audit`            | 200    | Audit trail                     |
| `DELETE` | `/claims/{id}`                  | 204    | Delete claim                    |
| `DELETE` | `/claims/{id}/documents/{did}`  | 204    | Remove single document          |

### POST `/claims` Flow

```
Request: files[]: List[UploadFile], policy_id: str?, patient_id: str?
    ↓
1. Validate each file:
   - Check content type against 19 allowed MIME types
   - Check size ≤ 50 MB
   - Sanitize filename via _safe_filename() (prevents path traversal)
    ↓
2. Create Claim row (status=UPLOADED)
    ↓
3. For each file:
   - Write to storage/{claim_id}_{idx}_{filename}
   - Create Document row (file_name, file_type, minio_path)
   - Rollback: delete file on DB insert failure
    ↓
4. Commit transaction
    ↓
5. Background: _trigger_workflow(claim_id)
   - POST {workflow_url}/start/{claim_id} (fire-and-forget)
    ↓
6. Audit: log "CLAIM_UPLOADED" event
    ↓
Response: ClaimOut (id, policy_id, patient_id, status, documents[])
```

### Key Functions

- `_safe_filename(raw: str) → str` — Strip path components, prevent directory traversal
- `_trigger_workflow(claim_id)` — Async HTTP POST, errors logged but not re-raised

---

## 2. OCR Service

**Route Prefix:** `/ocr` · **Port:** 8002

### Purpose

Extracts text from uploaded documents (PDF, images, Office files) and detects medical scan reports.

### Files

| File                | Responsibility                               |
| ------------------- | -------------------------------------------- |
| `main.py`           | Router, async job management                 |
| `engine.py`         | Multi-format text extraction pipeline        |
| `scan_analyzer.py`  | Medical scan detection & analysis            |
| `config.py`         | Settings (tesseract path)                    |
| `models.py`         | `OcrResult`, `OcrJob`, `ScanAnalysis`        |
| `schemas.py`        | Job/result response models                   |
| `db.py`             | Session factory                              |

### Configuration

```
OCR_DATABASE_URL   = postgresql://...
OCR_TESSERACT_CMD  = tesseract  (binary path override)
```

### Database Models

```
OcrResult
├── id: UUID (PK)
├── document_id: UUID (FK → documents.id)
├── page_number: Integer
├── text: Text
├── confidence: Float
└── created_at: DateTime

OcrJob
├── id: UUID (PK)
├── claim_id: UUID (FK → claims.id)
├── status: Text (QUEUED | PROCESSING | COMPLETED | FAILED)
├── total_documents: Integer
├── processed_documents: Integer
├── error_message: Text (nullable)
├── created_at: DateTime
└── completed_at: DateTime (nullable)

ScanAnalysis
├── id: UUID (PK)
├── document_id: UUID (FK)
├── claim_id: UUID (FK)
├── scan_type: Text (MRI | CT | X_RAY | ULTRASOUND | PET | MAMMOGRAPHY | ANGIOGRAPHY)
├── body_part: Text
├── modality: Text
├── findings: JSONB [{ finding, severity, confidence }]
├── impression: Text
├── recommendation: Text
├── confidence: Float
├── metadata: JSONB
└── created_at: DateTime
```

### Endpoints

| Method | Path             | Status | Description                 |
| ------ | ---------------- | ------ | --------------------------- |
| `GET`  | `/health`        | 200    | DB check                    |
| `POST` | `/{claim_id}`    | 202    | Start async OCR job         |
| `GET`  | `/job/{job_id}`  | 200    | Poll job status + results   |
| `GET`  | `/claim/{claim_id}` | 200 | Get OCR results for claim   |

### OCR Engine Pipeline

```
extract_text(file_path) → List[(page_number, text, confidence)]
    ↓
Route by file extension:
├── PDF → _extract_pdf()
│   ├── pdfplumber: extract embedded text per page
│   ├── If text is empty/short → Tesseract OCR on page image
│   └── Returns: [(page, text, confidence)]
├── Images (JPEG/PNG/TIFF/BMP/WebP) → _extract_image()
│   ├── Preprocessing pipeline:
│   │   1. Grayscale conversion
│   │   2. Noise removal (fastNlMeansDenoising)
│   │   3. Adaptive thresholding
│   │   4. Morphological close (fill gaps)
│   │   5. CLAHE contrast enhancement
│   │   6. Deskew via minAreaRect
│   ├── Multi-pass Tesseract with orientation detection
│   └── Returns: [(1, text, confidence)]
├── DOCX → python-docx (paragraphs + tables)
├── XLSX/XLS → openpyxl (all sheets, all cells)
└── TXT/CSV/JSON/XML/HTML → direct read
```

### Scan Analyzer

```
is_scan_document(filename, text) → bool
    ↓ if true
analyze_scan(filename, text, filepath) → ScanAnalysisResult
    ├── Detect scan_type via keyword patterns (MRI, CT, X-Ray, etc.)
    ├── Detect body_part (Brain, Spine, Chest, Abdomen, etc.)
    ├── Extract findings with severity (normal | mild | moderate | severe | critical)
    ├── Extract impression & recommendation
    └── Returns: ScanAnalysisResult(scan_type, body_part, findings[], impression, ...)
```

### Async Job Flow

```
POST /{claim_id} → 202 Accepted
    ↓
1. Create OcrJob (status=QUEUED)
2. Background: _run_ocr_job(job_id)
   ├── Set status=PROCESSING, claim.status=OCR_PROCESSING
   ├── For each document:
   │   ├── engine.extract_text(file_path)
   │   ├── Insert OcrResult rows (per page)
   │   ├── scan_analyzer.analyze_scan() → ScanAnalysis row if scan detected
   │   └── Increment processed_documents
   ├── Set status=COMPLETED, claim.status=OCR_DONE
   └── On error: status=FAILED, claim.status=OCR_FAILED
    ↓
GET /job/{job_id} → Poll until status=COMPLETED/FAILED
```

---

## 3. Parser Service

**Route Prefix:** `/parser` · **Port:** 8003

### Purpose

Extracts 20+ structured fields from OCR text using ML (LayoutLMv3) with regex fallback.

### Files

| File        | Responsibility                                |
| ----------- | --------------------------------------------- |
| `main.py`   | Router, async job management                  |
| `engine.py` | LayoutLMv3 + 40 regex patterns                |
| `config.py` | Settings (model name, fallback toggle)        |
| `models.py` | `ParsedField`, `ParseJob`                     |
| `schemas.py`| Job/result response models                    |
| `db.py`     | Session factory                               |

### Configuration

```
PARSER_DATABASE_URL           = postgresql://...
PARSER_LAYOUTLM_MODEL        = microsoft/layoutlmv3-base
PARSER_USE_HEURISTIC_FALLBACK = true
```

### Database Models

```
ParsedField
├── id: UUID (PK)
├── claim_id: UUID (FK → claims.id)
├── field_name: Text
├── field_value: Text
├── bounding_box: JSONB (nullable)
├── source_page: Integer (nullable)
├── model_version: Text (nullable)
└── created_at: DateTime

ParseJob
├── id: UUID (PK)
├── claim_id: UUID (FK)
├── status: Text (QUEUED | PROCESSING | COMPLETED | FAILED)
├── total_documents, processed_documents: Integer
├── model_version: Text
├── used_fallback: Boolean
├── error_message: Text (nullable)
├── created_at, completed_at: DateTime
```

### Engine Strategy (Priority Order)

```
parse_document(ocr_pages, images?) → ParseOutput
    ↓
1. LayoutLMv3 (microsoft/layoutlmv3-base)
   - Token classification on document images + OCR text
   - Requires: transformers, torch, PIL images
   - Returns: field_name → field_value with bounding_box
    ↓ fallback if unavailable
2. Heuristic Engine (40+ regex patterns)
   - Patient: name, DOB, gender, age, address, phone, email
   - Insurance: policy, member_id, group, insurer, TPA
   - Clinical: diagnosis, ICD-10, procedures, CPT, medications, allergies
   - Billing: line items, totals, dates, room charges
   - Provider: hospital, doctor, registration/discharge dates
   - Sections: chief complaint, history, findings, plan
    ↓ fallback
3. Regex-only (minimal extraction)
```

### Output Structure

```
ParseOutput
├── fields: List[FieldResult]
│   ├── field_name: str
│   ├── field_value: str?
│   ├── bounding_box: Dict?
│   ├── source_page: int?
│   └── model_version: str?
├── tables: List[Dict]
├── sections: List[Dict]
├── model_version: str?
└── used_fallback: bool
```

### Endpoints

| Method | Path                   | Status | Description              |
| ------ | ---------------------- | ------ | ------------------------ |
| `GET`  | `/health`              | 200    | DB check                 |
| `POST` | `/parse/{claim_id}`    | 202    | Start async parse job    |
| `GET`  | `/parse/job/{job_id}`  | 200    | Poll job status + fields |
| `GET`  | `/parse/{claim_id}`    | 200    | Get parsed fields        |

---

## 4. Coding Service

**Route Prefix:** `/coding` · **Port:** 8004

### Purpose

Named Entity Recognition (NER) for medical entities + ICD-10 / CPT code assignment with cost estimates.

### Files

| File              | Responsibility                            |
| ----------------- | ----------------------------------------- |
| `main.py`         | Router, sync endpoints                    |
| `engine.py`       | scispaCy NER + BioGPT + regex fallback    |
| `icd10_codes.py`  | 500+ ICD-10-CM + 180+ CPT code database   |
| `config.py`       | Settings (UMLS, scispaCy model)           |
| `models.py`       | `MedicalEntity`, `MedicalCode`            |
| `schemas.py`      | Result response models                    |
| `db.py`           | Session factory                           |

### Configuration

```
CODING_DATABASE_URL    = postgresql://...
CODING_USE_UMLS_LINKER = false  (UMLS ~500MB on first load)
CODING_SCISPACY_MODEL  = en_ner_bc5cdr_md
```

### Database Models

```
MedicalEntity
├── id: UUID (PK)
├── claim_id: UUID (FK)
├── entity_text: Text
├── entity_type: Text (DIAGNOSIS | PROCEDURE | MEDICATION | CHEMICAL)
├── start_offset, end_offset: Integer
├── confidence: Float
├── created_at: DateTime
└── codes: List[MedicalCode]  (one-to-many)

MedicalCode
├── id: UUID (PK)
├── claim_id: UUID (FK)
├── entity_id: UUID (FK → medical_entities.id, nullable)
├── code: Text (e.g., "J18.9", "99213")
├── code_system: Text (ICD10 | CPT)
├── description: Text
├── confidence: Float
├── is_primary: Boolean
├── estimated_cost: Float (nullable)
└── created_at: DateTime
```

### Engine Strategy

```
extract_entities_and_codes(text, parsed_fields) → CodingOutput
    ↓
1. scispaCy (en_ner_bc5cdr_md)
   - Biomedical NER: diseases, chemicals/drugs
   - Entities: DIAGNOSIS, PROCEDURE, MEDICATION, CHEMICAL
    ↓ fallback
2. BioGPT (microsoft/biogpt)
   - Entity-to-code suggestion
    ↓ fallback
3. Regex patterns
    ↓
Code Assignment:
├── ICD-10 lookup: search_icd10_by_text(entity_text) → best match
├── CPT lookup: get_cpt_for_icd10(icd_code) → related procedures
├── Cost estimation: estimate_cost(code) → float
└── Primary designation: highest confidence ICD-10 → is_primary=true
```

### ICD-10/CPT Database (`icd10_codes.py`)

| Function                     | Returns                              |
| ---------------------------- | ------------------------------------ |
| `lookup_icd10(code)`         | (code, description, category)        |
| `lookup_cpt(code)`           | (code, description, category)        |
| `search_icd10_by_text(query)`| List of matching ICD-10 codes        |
| `search_cpt_by_text(query)`  | List of matching CPT codes           |
| `estimate_cost(code)`        | Estimated cost in INR                |
| `get_cpt_for_icd10(icd)`    | Related CPT procedures               |
| `is_valid_cpt(code)`        | Boolean validation                   |

### Endpoints

| Method | Path                          | Status | Description              |
| ------ | ----------------------------- | ------ | ------------------------ |
| `GET`  | `/health`                     | 200    | DB check                 |
| `POST` | `/code-suggest/{claim_id}`    | 200    | Run NER + code assignment (sync, idempotent) |
| `GET`  | `/code-suggest/{claim_id}`    | 200    | Get assigned codes       |

---

## 5. Predictor Service

**Route Prefix:** `/predictor` · **Port:** 8005

### Purpose

ML-powered rejection risk scoring with explainable feature importance.

### Files

| File        | Responsibility                              |
| ----------- | ------------------------------------------- |
| `main.py`   | Router, sync endpoints                      |
| `engine.py` | XGBoost + LightGBM + heuristic fallback     |
| `config.py` | Settings (model paths, version)             |
| `models.py` | `Feature`, `Prediction`                     |
| `schemas.py`| Result response models                      |
| `db.py`     | Session factory                             |

### Configuration

```
PREDICTOR_DATABASE_URL  = postgresql://...
PREDICTOR_MODEL_NAME    = ClaimGPT Rejection Scorer
PREDICTOR_MODEL_VERSION = 0.1.0
PREDICTOR_MODEL_DIR     = ./models
PREDICTOR_MAX_AGE_DAYS  = 30
```

### Database Models

```
Feature
├── claim_id: UUID (PK, FK → claims.id)
├── feature_vector: JSONB
└── generated_at: DateTime

Prediction
├── id: UUID (PK)
├── claim_id: UUID (FK)
├── rejection_score: Float (0.0–1.0)
├── top_reasons: JSONB [{ feature, importance, value }]
├── model_name: Text
├── model_version: Text
└── created_at: DateTime
```

### Feature Vector (13 Features)

| # | Feature               | Type    | Description                              |
|---|---------------------- |---------|------------------------------------------|
| 1 | `has_patient_name`    | Binary  | patient_name field present               |
| 2 | `has_policy_number`   | Binary  | policy_number field present              |
| 3 | `has_diagnosis`       | Binary  | diagnosis field present                  |
| 4 | `has_service_date`    | Binary  | service_date field present               |
| 5 | `has_total_amount`    | Binary  | total_amount field present               |
| 6 | `has_provider`        | Binary  | provider_name field present              |
| 7 | `num_parsed_fields`   | Integer | Total count of parsed fields             |
| 8 | `num_entities`        | Integer | Total NER entities extracted             |
| 9 | `num_icd_codes`       | Integer | ICD-10 codes assigned                    |
|10 | `num_cpt_codes`       | Integer | CPT codes assigned                       |
|11 | `has_primary_icd`     | Binary  | Primary ICD-10 code designated           |
|12 | `num_diagnosis_types` | Integer | Distinct diagnosis entity types          |
|13 | `total_amount_log`    | Float   | Log-transformed total amount             |

### Engine Strategy

```
predict(feature_vector) → PredictionResult
    ↓
1. XGBoost (models/xgb_rejection.json)
   - If not found: auto-train on 2000 synthetic samples
   - Feature importance via gain-based ranking
    ↓ optional ensemble
2. LightGBM (models/lgbm_rejection.txt)
   - Secondary scorer, averaged with XGBoost
    ↓ fallback
3. Heuristic rules
   - Missing key fields → high score
   - No codes → moderate score
   - Complete + low amount → low score
```

### Endpoints

| Method | Path                      | Status | Description                  |
| ------ | ------------------------- | ------ | ---------------------------- |
| `GET`  | `/health`                 | 200    | DB check                     |
| `POST` | `/predict/{claim_id}`     | 200    | Score rejection risk (sync)  |
| `GET`  | `/predict/{claim_id}`     | 200    | Get latest prediction        |
| `GET`  | `/features/{claim_id}`    | 200    | Get/compute feature vector   |

---

## 6. Validator Service

**Route Prefix:** `/validator` · **Port:** 8006

### Purpose

Deterministic rule engine with 10 validation rules (R001–R010).

### Files

| File        | Responsibility                     |
| ----------- | ---------------------------------- |
| `main.py`   | Router, sync endpoints             |
| `rules.py`  | Rule definitions and executor      |
| `config.py` | Settings                           |
| `models.py` | `Validation`                       |
| `schemas.py`| Result response models             |
| `db.py`     | Session factory                    |

### Database Models

```
Validation
├── id: UUID (PK)
├── claim_id: UUID (FK)
├── rule_id: Text (R001–R010)
├── rule_name: Text
├── severity: Text (INFO | WARN | ERROR)
├── message: Text
├── passed: Boolean
└── evaluated_at: DateTime
```

### Rule Registry

| Rule | Name                     | Severity | Condition                                           |
| ---- | ------------------------ | -------- | --------------------------------------------------- |
| R001 | Patient name present     | ERROR    | Field: patient_name, member_name, insured_name      |
| R002 | Policy number present    | ERROR    | Field: policy_number, policy_id, insurance_id       |
| R003 | Diagnosis present        | ERROR    | Field: diagnosis, primary_diagnosis, chief_complaint|
| R004 | ICD-10 code present      | ERROR    | At least one ICD10 code assigned                    |
| R005 | Date of service present  | ERROR    | Field: service_date, admission_date, treatment_date |
| R006 | Total amount present     | WARN     | Field: total_amount, billed_amount, grand_total     |
| R007 | Provider name present    | WARN     | Field: provider_name, doctor_name, hospital_name    |
| R008 | Rejection score check    | WARN     | rejection_score < 0.5                               |
| R009 | CPT code present         | WARN     | At least one CPT code                               |
| R010 | Primary ICD designated   | WARN     | is_primary ICD-10 code exists                       |

### Validation Flow

```
POST /validate/{claim_id}
    ↓
1. Gather context:
   - parsed_fields (all field_name → field_value)
   - medical_codes (ICD-10 + CPT)
   - latest prediction (rejection_score)
    ↓
2. run_rules(context) → List[RuleResult]
   - Execute R001–R010 sequentially
   - Each returns: rule_id, passed, severity, message
    ↓
3. Persist: wipe old validations, insert new rows (idempotent)
    ↓
4. Claim status:
   - ERROR count > 0 → VALIDATION_FAILED
   - Otherwise → VALIDATED
    ↓
Response: { claim_id, status, total_rules: 10, passed, failed, warnings, results[] }
```

---

## 7. Workflow Service

**Route Prefix:** `/workflow` · **Port:** 8007

### Purpose

Orchestrates the full pipeline: OCR → Parse → Code → Predict → Validate.

### Files

| File          | Responsibility                          |
| ------------- | --------------------------------------- |
| `main.py`     | Router, background job execution        |
| `pipeline.py` | Step definitions, retry logic, polling  |
| `config.py`   | Service URLs, retry/timeout settings    |
| `models.py`   | `WorkflowJob`                           |
| `schemas.py`  | Job response models                     |
| `db.py`       | Session factory                         |

### Configuration

```
WORKFLOW_DATABASE_URL      = postgresql://...
WORKFLOW_OCR_URL           = http://localhost:8000/ocr
WORKFLOW_PARSER_URL        = http://localhost:8000/parser
WORKFLOW_CODING_URL        = http://localhost:8000/coding
WORKFLOW_PREDICTOR_URL     = http://localhost:8000/predictor
WORKFLOW_VALIDATOR_URL     = http://localhost:8000/validator
WORKFLOW_MAX_RETRIES       = 3
WORKFLOW_RETRY_BACKOFF     = 1.0  (exponential 2x)
WORKFLOW_ASYNC_POLL_MAX    = 180  (seconds)
WORKFLOW_ASYNC_POLL_INTERVAL = 2  (seconds)
WORKFLOW_TIMEOUT           = 120  (seconds)
```

### Database Models

```
WorkflowJob
├── id: UUID (PK)
├── claim_id: UUID (FK)
├── job_type: Text (FULL_PIPELINE | PARTIAL)
├── status: Text (QUEUED | RUNNING | COMPLETED | FAILED)
├── current_step: Text (nullable)
├── error_message: Text (nullable)
├── retries: Integer (default=0)
├── started_at: DateTime
└── completed_at: DateTime (nullable)
```

### Pipeline Steps

```
PIPELINE_STEPS = [
  Step 1: OCR       → POST /ocr/{claim_id}                 (async, poll job)
  Step 2: Parse     → POST /parser/parse/{claim_id}         (async, poll job)
  Step 3: Code      → POST /coding/code-suggest/{claim_id}  (sync)
  Step 4: Predict   → POST /predictor/predict/{claim_id}    (sync)
  Step 5: Validate  → POST /validator/validate/{claim_id}   (sync)
]
```

### Execution Flow

```
POST /start/{claim_id} → 202
    ↓
1. Create WorkflowJob (QUEUED)
2. Background: _execute_workflow(job_id)
   ├── Set status=RUNNING, claim.status=PROCESSING
   ├── For each step:
   │   ├── Set current_step
   │   ├── HTTP call to service
   │   ├── If async (202): poll job endpoint until COMPLETED/FAILED
   │   │   └── Max 180s, interval 2s
   │   ├── If sync: check response status
   │   ├── On failure: retry up to 3x (exponential backoff)
   │   └── On final failure: mark step FAILED, stop pipeline
   ├── All steps done: status=COMPLETED, claim.status=COMPLETED
   └── On error: status=FAILED, claim.status=WORKFLOW_FAILED
    ↓
GET /{job_id} → Poll until COMPLETED/FAILED
```

### Endpoints

| Method | Path                | Status | Description              |
| ------ | ------------------- | ------ | ------------------------ |
| `GET`  | `/health`           | 200    | DB check                 |
| `POST` | `/start/{claim_id}` | 202    | Start full pipeline      |
| `GET`  | `/{job_id}`         | 200    | Poll job status          |

---

## 8. Submission Service

**Route Prefix:** `/submission` · **Port:** 8008

### Purpose

TPA PDF generation, reimbursement intelligence, and payer submission via FHIR R4 / X12 837P.

### Files

| File           | Responsibility                              |
| -------------- | ------------------------------------------- |
| `main.py`      | Router, endpoints                           |
| `adapters.py`  | Payer-specific format adapters              |
| `tpa_pdf.py`   | PDF report generation                       |
| `config.py`    | Settings (default payer)                    |
| `models.py`    | `Submission`, `TpaProvider`                 |
| `schemas.py`   | Request/response models                     |
| `db.py`        | Session factory                             |

### Configuration

```
SUBMISSION_DATABASE_URL  = postgresql://...
SUBMISSION_DEFAULT_PAYER = icici_lombard
```

### Database Models

```
Submission
├── id: UUID (PK)
├── claim_id: UUID (FK)
├── payer: Text
├── request_payload: JSONB
├── response_payload: JSONB
├── status: Text
└── submitted_at: DateTime

TpaProvider (pre-populated: 25 rows)
├── id: UUID (PK)
├── code: Text (UNIQUE, e.g., "icici_lombard")
├── name: Text
├── logo: Text
├── provider_type: Text (Private | PSU | TPA)
├── email, phone, website, address: Text
├── is_active: Boolean
└── created_at: DateTime
```

### TPA PDF Sections

```
generate_tpa_pdf(claim_data) → bytes (PDF)
  1. Patient Demographics
  2. Insurance Details
  3. Medical Codes (ICD-10 + CPT with cost estimates)
  4. OCR Text Extract (first 2000 + last 2000 chars)
  5. Parsed Fields Summary
  6. Predictions (rejection score + top reasons)
  7. Validations (rule results table)
  8. Scan Analyses (MRI/CT findings if present)
  9. Reimbursement Brain Insights
  10. Expense Breakdown (8 categories)
```

### Reimbursement Brain

```
_generate_brain_insights(claim_data) → Dict
  ├── Document classification (admission, discharge, bills, etc.)
  ├── Cross-document field consistency check
  ├── Readiness checklist (75%+ completeness scoring)
  ├── Total estimated cost aggregation
  └── Risk assessment summary
```

### Adapters

| Adapter      | Format       | Use Case           |
| ------------ | ------------ | ------------------ |
| FHIR R4      | JSON Bundle  | US payers          |
| X12 837P     | EDI segments | US clearinghouses  |
| TPA Native   | JSON payload | Indian TPAs        |

### Endpoints

| Method | Path                               | Status | Description                    |
| ------ | ---------------------------------- | ------ | ------------------------------ |
| `GET`  | `/health`                          | 200    | DB check                       |
| `POST` | `/submit/{claim_id}`               | 200    | Submit to payer                |
| `GET`  | `/claims/{id}/preview`             | 200    | Full claim preview (JSON)      |
| `GET`  | `/claims/{id}/tpa-pdf`             | 200    | Generate TPA PDF (binary)      |
| `POST` | `/claims/{id}/code-feedback`       | 200    | Accept/reject code feedback    |

---

## 9. Chat Service

**Route Prefix:** `/chat` · **Port:** 8009

### Purpose

LLM-powered conversational interface with RAG-based claim context and PHI scrubbing.

### Files

| File        | Responsibility                           |
| ----------- | ---------------------------------------- |
| `main.py`   | Router, streaming endpoints              |
| `llm.py`    | Multi-provider LLM integration           |
| `config.py` | Settings (provider, model, PHI toggle)   |
| `models.py` | `ChatMessage`                            |
| `schemas.py`| Request/response models                  |
| `db.py`     | Session factory                          |

### Configuration

```
CHAT_DATABASE_URL          = postgresql://...
CHAT_LLM_PROVIDER          = ollama
CHAT_LLM_MODEL             = llama3.2
CHAT_OLLAMA_URL             = http://localhost:11434
CHAT_MAX_CONTEXT_TOKENS    = 8192
CHAT_MAX_RESPONSE_TOKENS   = 1024
CHAT_PHI_SCRUBBING_ENABLED = true
```

### Database Models

```
ChatMessage
├── id: UUID (PK)
├── claim_id: UUID (FK, nullable)
├── role: Text (USER | SYSTEM | ASSISTANT)
├── message: Text
└── created_at: DateTime
```

### LLM Providers

| Provider    | Model Examples              | Protocol      |
| ----------- | --------------------------- | ------------- |
| Ollama      | llama3.2, codellama         | HTTP (local)  |
| OpenAI      | gpt-4, gpt-3.5-turbo       | REST API      |
| Anthropic   | claude-3-opus, claude-3-sonnet | REST API   |
| Cohere      | command-r-plus              | REST API      |
| Together    | Llama-3-70b                 | REST API      |
| Replicate   | Various open models         | REST API      |

### Chat Flow

```
POST /chat → ChatResponse
    ↓
1. PHI Scrubbing
   - If enabled: scrub_phi(message) redacts SSN, phone, email, MRN, DOB
    ↓
2. Context Assembly
   - If claim_id provided:
     ├── Fetch parsed_fields for claim
     ├── Fetch medical_codes
     ├── Fetch predictions
     ├── _search_ocr_for_query(claim_id, message)
     │   ├── Extract keywords from question
     │   ├── Score OCR pages by relevance
     │   ├── Always include first page
     │   └── Return up to 12000 tokens
     └── Build system prompt with claim context
    ↓
3. LLM Call
   - call_llm(provider, model, messages, temperature=0.7)
   - Or stream_llm() for SSE streaming
    ↓
4. Response Processing
   - Generate field_actions (add/modify/delete suggestions)
   - Generate follow-up suggestions via get_suggestions()
   - Persist ChatMessage rows (USER + ASSISTANT)
    ↓
Response: { session_id, role, message, suggestions[], field_actions[] }
```

### Endpoints

| Method | Path                          | Status | Description                   |
| ------ | ----------------------------- | ------ | ----------------------------- |
| `GET`  | `/health`                     | 200    | DB check                      |
| `POST` | `/{session_id}/message`       | 200    | Send chat message             |
| `POST` | `/{session_id}/stream`        | 200    | Stream response (SSE)         |
| `GET`  | `/{session_id}/history`       | 200    | Get chat history              |
| `GET`  | `/providers`                  | 200    | List available LLM providers  |
| `POST` | `/field-action`               | 204    | Apply field edits             |

---

## 10. Search Service

**Route Prefix:** `/search` · **Port:** 8010

### Purpose

Full-text search via PostgreSQL + semantic vector search via FAISS.

### Files

| File        | Responsibility                         |
| ----------- | -------------------------------------- |
| `main.py`   | Router, endpoints                      |
| `vector.py` | FAISS index, embedding, similarity     |
| `config.py` | Settings (model, index path)           |
| `models.py` | Reuses ingress/ocr/parser models       |
| `schemas.py`| Search result models                   |
| `db.py`     | Session factory                        |

### Configuration

```
SEARCH_DATABASE_URL     = postgresql://...
SEARCH_EMBEDDING_MODEL  = sentence-transformers/all-MiniLM-L6-v2
SEARCH_FAISS_INDEX_PATH = ./search_index
```

### Vector Search Engine

```
index_claim(claim_id)
  ├── Gather OCR text + parsed field values
  ├── Encode via SentenceTransformer (all-MiniLM-L6-v2)
  ├── Add to FAISS index (IVF or Flat)
  └── Map vector ID → claim_id

search_similar(query, top_k=20)
  ├── Encode query → vector
  ├── FAISS search → top_k nearest neighbors
  └── Return [(claim_id, score, highlights)]
```

### Endpoints

| Method | Path              | Status | Description                      |
| ------ | ----------------- | ------ | -------------------------------- |
| `GET`  | `/health`         | 200    | DB check                         |
| `GET`  | `/`               | 200    | Full-text search (`?q=...`)      |
| `POST` | `/vector-search`  | 200    | Semantic vector search           |
| `POST` | `/index/{claim_id}` | 202  | Index single claim               |
| `POST` | `/index-batch`    | 202    | Batch index multiple claims      |
| `GET`  | `/index/stats`    | 200    | FAISS index statistics           |

### Full-Text Search

```
GET /?q=diabetes&limit=20
    ↓
PostgreSQL ILIKE search across:
  - parsed_fields.field_value
  - ocr_results.text
  - claims.policy_id, patient_id, id
    ↓
Response: { results: [{ claim_id, score, highlights[], status, policy_id }], limit, offset }
```

---

## 11. Shared Libraries

### Auth (`libs/auth/`)

```
TokenPayload
├── sub: str (user ID)
├── email, preferred_username: str
├── realm_access, resource_access: Dict (Keycloak)
├── exp, iat, iss: int/str (JWT standard)
├── roles → property: List[str]
└── has_role(role) → bool

Functions:
├── get_current_user(creds) → Optional[TokenPayload]
├── require_role(*roles) → Depends() factory
├── _decode_token(token) → TokenPayload
│   ├── RS256 via JWKS endpoint (production)
│   └── HS256 via JWT_SECRET (dev fallback)
└── _fetch_jwks() → cached OIDC public keys

UserRole(Enum): ADMIN, REVIEWER, SUBMITTER, VIEWER, SERVICE
AuthMiddleware: ASGI middleware for global JWT validation
```

### Observability (`libs/observability/`)

```
Metrics:
├── init_metrics(service_name)
├── PrometheusMiddleware (ASGI)
│   ├── http_request_duration_seconds (Histogram)
│   ├── http_requests_total (Counter)
│   └── http_request_errors_total (Counter, 5xx)
└── metrics_endpoint() → /metrics handler

Tracing:
├── init_tracing(service_name)
├── instrument_fastapi(app)
└── instrument_sqlalchemy(engine)
Config: OTEL_ENABLED, OTEL_EXPORTER_OTLP_ENDPOINT (default: localhost:4317)
```

### Schemas (`libs/schemas/`)

```
ClaimStatus (23 states):
  UPLOADED → OCR_PROCESSING → OCR_DONE → PARSING → PARSED →
  CODING → CODED → PREDICTING → PREDICTED → VALIDATING →
  VALIDATED / VALIDATION_FAILED → SUBMITTING → SUBMITTED →
  APPROVED / REJECTED / PROCESSING / COMPLETED / WORKFLOW_FAILED /
  OCR_FAILED / PARSE_FAILED

Event Types:
  ClaimIngestedEvent, OcrCompletedEvent, ParseCompletedEvent,
  CodingCompletedEvent, PredictCompletedEvent,
  ValidationCompletedEvent, SubmissionCompletedEvent
```

### Utils (`libs/utils/`)

```
PHI Scrubber (scrub_phi):
  SSN        → [SSN_REDACTED]
  Phone      → [PHONE_REDACTED]
  Email      → [EMAIL_REDACTED]
  MRN        → [MRN_REDACTED]
  DOB        → [DOB_REDACTED]
  Policy     → [POLICY_REDACTED]

Audit Logger:
  log(action, claim_id, actor, metadata) → audit_logs row
```

---

## 12. Database Schema

Full schema: [`infra/db/claimgpt_schema.sql`](../infra/db/claimgpt_schema.sql)

### Entity Relationship Diagram

```
claims (1) ──────< documents (N)
  │                    │
  │                    ├──< ocr_results (N)
  │                    └──< scan_analyses (N)
  │
  ├──< ocr_jobs (N)
  ├──< parse_jobs (N)
  ├──< parsed_fields (N)
  ├──< medical_entities (N) ──< medical_codes (N)
  ├──< medical_codes (N)     (also direct FK)
  ├──  features (1:1)
  ├──< predictions (N)
  ├──< validations (N)
  ├──< workflow_jobs (N)
  ├──< submissions (N)
  ├──< chat_messages (N)
  └──< audit_logs (N)

tpa_providers (standalone, 25 pre-populated)
```

### Indexes

| Table             | Index                            | Columns       |
| ----------------- | -------------------------------- | ------------- |
| documents         | idx_documents_claim_id           | claim_id      |
| ocr_results       | idx_ocr_document_id              | document_id   |
| ocr_jobs          | idx_ocr_jobs_claim_id            | claim_id      |
| parsed_fields     | idx_parsed_claim_id              | claim_id      |
| parse_jobs        | idx_parse_jobs_claim_id          | claim_id      |
| medical_entities  | idx_medical_entities_claim_id    | claim_id      |
| medical_codes     | idx_medical_codes_claim_id       | claim_id      |
| predictions       | idx_predictions_claim_id         | claim_id      |
| validations       | idx_validations_claim_id         | claim_id      |
| workflow_jobs     | idx_workflow_claim_id            | claim_id      |
| submissions       | idx_submissions_claim_id         | claim_id      |
| chat_messages     | idx_chat_claim_id                | claim_id      |
| audit_logs        | idx_audit_claim_id               | claim_id      |
| scan_analyses     | idx_scan_analyses_claim_id       | claim_id      |
| scan_analyses     | idx_scan_analyses_document_id    | document_id   |
| tpa_providers     | idx_tpa_providers_code           | code          |
