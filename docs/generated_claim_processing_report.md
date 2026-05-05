PHASE 1: DOCUMENT UPLOAD (Ingress Service)
File: main.py

When you upload documents to /claims/{claim_id}/documents:

File Storage & Hashing

Files stored in MinIO object storage
SHA-256 hash computed for idempotency (duplicate upload detection)
Creates Document DB record with:
file_name, file_type, minio_path, content_hash
Identity Gate Validation (_apply_identity_gate())

Extracts patient name & DOB from first 5 pages
Compares against previous documents (anchor matching)
Creates DocValidation record to track patient consistency
Can exclude documents if patient mismatch
Workflow Enqueue (_enqueue_pipeline())

Creates WorkflowState record with status=RUNNING
Enqueues Celery chain:
ocr_task → parser_task → coding_task → risk_task → validator_task → finalize_task


PHASE 2: OCR (Text Extraction)
File: engine.py

Function: extract_text(file_path) - Multi-format text extraction

File Type Routing:
PDF Documents: _extract_from_pdf()

Step 1: Extract embedded text via pdfplumber
Step 2: Extract structured tables using pdfplumber.extract_tables()
Step 3: If no text found, render page to image and run OCR
Images (JPG, PNG, TIFF): _extract_from_image()

Preprocessing pipeline:

Grayscale conversion
Denoise (fastNlMeansDenoising)
CLAHE contrast enhancement
Adaptive thresholding
Morphological close (fill text gaps)
Deskew (detect + correct rotation)
Multi-engine OCR (cascading):

Try EasyOCR (if enabled)
Fall back to PaddleOCR (default)
Fall back to Tesseract
Result Format:
List[Tuple[page_number, text, confidence]]


Storage:
For each page, creates OcrResult record:

document_id, page_number, text, confidence
Output after OCR Phase:

Raw text stored per page
Ready for parsing
PHASE 3: PARSING (Smart Field Extraction)
File: engine.py
Main Function: parse_document() (2600+ lines)

Step 1: Gather OCR Pages
_gather_ocr_pages(db, claim_id)

Reads all OcrResult records for the claim
Filters excluded documents
Returns unified list of OCR text pages
Step 2: Classify Document Type
_classify_page_document_type(page) → DocumentType

Classification Logic:

Strong keywords: "discharge summary" → DISCHARGE_SUMMARY
Billing cues: "expense category", "bill summary", "total amount" → HOSPITAL_BILL
Keyword scoring: Count matches against known document patterns
Table density: Dense numeric tables bias toward HOSPITAL_BILL/LAB_REPORT
Result: DISCHARGE_SUMMARY | HOSPITAL_BILL | PHARMACY_INVOICE | LAB_REPORT | UNKNOWN
Why this matters: Field extraction is routed by document type. HOSPITAL_BILL documents get expense field extraction, DISCHARGE_SUMMARY documents get CPT code validation, etc.

Step 3: EXPENSE TABLE EXTRACTION ⭐ (Dynamic Field Retrieval)
Function: _extract_expense_table(text, page_num, tables, known_cpt_codes)
Returns: (list[FieldResult], list[BillingLineItem])

This is where dynamic fields are extracted. Four cascaded passes:

PASS 1: Structural Tables (Most Accurate)
if tables:  # From pdfplumber/layout detection
  for tbl in tables:
    header = get_column_names()  # e.g., ["Description", "Amount"]
    for row in rows:
      label = row[description_col]  # e.g., "Room Charges"
      amount_str = row[amount_col]  # e.g., "21,000"
      
      # CATEGORIZATION - maps description to field name
      category = _categorise_expense(label)
      # e.g., "Room Charges" → "room_charges"
      # "HDU Charges" → "icu_charges"
      # "Surgeon Fees" → "surgeon_fees"

PASS 2a: Pipe-delimited (if no structural tables)

| Room Charges | Rs. 21,000 |
| Pharmacy | 5,000 |


PASS 2b: Standard Regex (multi-space separated)

Room Charges ......... 21,000
Pharmacy ............ 5,000

PASS 2c: Numbered Lines

1  HDU Charges  18,000
2  Pharmacy   5,000

PASS 2d: PaddleOCR Parallel (labels on one line, amounts on next)

Room | Board | Investigation
21000 15000 8000


Categorization Function: _categorise_expense(description_text)

Uses regex patterns to map description to canonical category
Examples:
"Room & Board" → "room_charges"
"Surgery/Procedure" → "surgery_charges"
"Medicines & Consumables" → "pharmacy_charges"
"Lab Tests" → "investigation_charges"
Output: FieldResult objects with:

field_name: "room_charges", "surgery_charges", etc.
field_value: "21000.00"
model_version: "expense-table-geo-v1"
source_page: page number
document_id: UUID of source document
Step 4: Extract All Other Fields via Regex Patterns
40+ Regex Patterns stored as _PATTERNS list:

Demographics (extracted in order of specificity):
("patient_name", _PAT_PATIENT_NAME)        # Regex: "Patient Name : [value]"
("date_of_birth", _PAT_DOB)                 # Regex: "DOB: 01-01-1990"
("age", _PAT_AGE)                           # Regex: "Age: 35 years"
("gender", _PAT_GENDER)                     # Regex: "Gender: Male"


Insurance:
("policy_number", _PAT_POLICY)              # "Policy No: POL123456"
("member_id", _PAT_MEMBER_ID)               # "Member ID: MEM789"
("insurer", _PAT_INSURER)                   # "Insurer: ABC Insurance"


Clinical:
("diagnosis", _PAT_DIAGNOSIS)               # "Diagnosis: Pneumonia"
("icd_code", _PAT_ICD_CODE)                 # Pattern: J18.9 (ICD-10)
("procedure", _PAT_PROCEDURE)               # "Procedure: CABG"
("cpt_code", _PAT_CPT_CODE)                 # Pattern: 99213 (5 digits)


Financial (these are the dynamic ones):
("total_amount", _PAT_TOTAL_AMOUNT)         # "Total Amount: 100,000"
("room_charges", _PAT_ROOM_CHARGE)          # "Room Charges: 21,000"
("consultation_charges", _PAT_CONSULTATION) # "Consultation: 5,000"
("pharmacy_charges", _PAT_PHARMACY)         # "Pharmacy: 8,000"
("investigation_charges", _PAT_INVESTIGATION)
("laboratory_charges", _PAT_LABORATORY)
("radiology_charges", _PAT_RADIOLOGY)
("surgery_charges", _PAT_SURGERY_CHARGE)
("surgeon_fees", _PAT_SURGEON_FEE)
("anaesthesia_charges", _PAT_ANAESTHESIA)
("ot_charges", _PAT_OT_CHARGE)              # Operation Theatre
("consumables", _PAT_CONSUMABLES)
("nursing_charges", _PAT_NURSING)
("icu_charges", _PAT_ICU_CHARGE)
("ambulance_charges", _PAT_AMBULANCE)
("misc_charges", _PAT_MISC_CHARGE)


Step 5: Field Validation
Function: _is_valid_field_value(field_name, value, line_context, doc_type)

Money fields: Must be numeric, validates surrounding context (contains "rs", "amount", etc.)
CPT codes: Must be 5 digits, found in discharge summary with procedure context
ICD codes: Format validation [A-TV-Z]\d{2}(.\d{1,4})?
Doctor names: Not signatures or blank lines
Document-type specific: CPT extraction only from DISCHARGE_SUMMARY docs
Step 6: Enrich with Document Information
Function: _enrich_fields_with_doc_info(output, ocr_pages, doc_type_map)

For each extracted field, add:

source_page: Which page was it found on?
document_id: Which document file?
doc_type: Is it from HOSPITAL_BILL or DISCHARGE_SUMMARY?
Step 7: Persist to Database
Function: _persist_fields(db, claim_id, output)

For each field, create ParsedField record:
Step 5: Field Validation
Function: _is_valid_field_value(field_name, value, line_context, doc_type)

Money fields: Must be numeric, validates surrounding context (contains "rs", "amount", etc.)
CPT codes: Must be 5 digits, found in discharge summary with procedure context
ICD codes: Format validation [A-TV-Z]\d{2}(.\d{1,4})?
Doctor names: Not signatures or blank lines
Document-type specific: CPT extraction only from DISCHARGE_SUMMARY docs
Step 6: Enrich with Document Information
Function: _enrich_fields_with_doc_info(output, ocr_pages, doc_type_map)

For each extracted field, add:

source_page: Which page was it found on?
document_id: Which document file?
doc_type: Is it from HOSPITAL_BILL or DISCHARGE_SUMMARY?
Step 7: Persist to Database
Function: _persist_fields(db, claim_id, output)

For each field, create ParsedField record:
ParsedField(
  claim_id = claim_id,
  document_id = source_document_uuid,
  field_name = "room_charges",
  field_value = "21000.00",
  source_page = 3,
  doc_type = "HOSPITAL_BILL",
  model_version = "expense-table-geo-v1",  # Track extraction method
  created_at = now()
)


Key Point: Each field knows:

What it is (field_name)
Where it came from (document_id, source_page)
What type of document (doc_type)
How it was extracted (model_version)
PHASE 4: SUBMISSION (Report Generation)
File: main.py

Endpoint: GET /claims/{claim_id}/submission
Function: _gather_claim_data_full(db, claim)

Step 1: Read All Parsed Fields
pf_rows = db.query(ParsedField).filter(ParsedField.claim_id == claim_id).all()


Step 2: Build Field Map with Smart Prioritization
Function: _build_parsed_field_map(pf_rows)

For money fields specifically, prioritize by extraction method:
PRIORITY_ORDER = [
  "expense-table-v4",      # Best - from structured tables
  "expense-table-geo-v1",  # Good - from geometric analysis
  "expense-table-v2",      # Good - from text patterns
  "heuristic-v2",          # Fallback - from regex
]


Logic for consolidating multiple values:

If multiple pages have room_charges:
If all from expense-table: SUM them (they're partial totals)
If from heuristic: PICK the MAX (to avoid double-counting)
Result: Single best value per field

Step 3: Build Dynamic Expense Breakdown
Function: Iterates pf_rows looking for expense fields:
_EXPENSE_FIELDS = {
  "room_charges": "Room Charges",
  "consultation_charges": "Consultation Charges",
  "pharmacy_charges": "Pharmacy & Medicines",
  "investigation_charges": "Diagnostics & Investigations",
  "surgery_charges": "Surgery Charges",
  "surgeon_fees": "Surgeon & Professional Fees",
  "anaesthesia_charges": "Anaesthesia Charges",
  "ot_charges": "Operation Theatre Charges",
  "consumables": "Medical & Surgical Consumables",
  "nursing_charges": "Nursing & Support Services",
  "icu_charges": "ICU Charges",
  "ambulance_charges": "Ambulance Charges",
  "isolation_charges": "Isolation Ward Charges",
  "transplant_charges": "Stem Cell / Transplant Charges",
  "chemotherapy_charges": "Chemotherapy & Conditioning",
  "blood_charges": "Blood Products & Bank",
  "physiotherapy_charges": "Physiotherapy Charges",
  "other_charges": "Other Charges",
}

expenses = []
for r in pf_rows:
  if r.field_name in _EXPENSE_FIELDS:
    expenses.append({
      "category": _EXPENSE_FIELDS[r.field_name],  # Display label
      "amount": float(r.field_value),
      "source_field": r.field_name,
      "model_version": r.model_version,  # Track provenance
      "document_id": r.document_id,
      "source_page": r.source_page,
    })


This is entirely DYNAMIC:

Not hardcoded in reports
Built fresh from parsed fields
Preserves source information
Display labels mapped from field names
Step 4: Generate PDF Reports
TPA Format: generate_tpa_pdf(claim_data)
IRDA Format: generate_irda_pdf(claim_data) or generate_irda_pdf_modern()

Both formats include:

Patient demographics
Hospital details
Admission/discharge dates
Diagnosis & procedures
Itemized Expense Breakdown (dynamically built from expenses list)
Total amount
Medical codes
KEY TAKEAWAYS
❌ NOT Hardcoded:
Actual expense values (come from documents)
Which documents contain which fields (varies per upload)
Specific amounts or calculations (dynamic per claim)
✅ Hardcoded:
Field names (room_charges, consultation_charges, etc.) - 40+ patterns
Regex patterns for extraction
Display labels for report output
Categorization logic (description → field name)
Dynamic Field Retrieval Process:
Parse: Extract text from documents via OCR
Classify: Determine document type
Table Detection: Identify expense tables in bills
Categorize: Map table descriptions to field names
Validate: Ensure extracted values match context
Store: Save with source tracking (document_id, page, model_version)
Prioritize: When consolidating, prefer table-based over heuristic
Report: Build report by reading from database
Model Version Tracking:
expense-table-geo-v1 - From spatial table analysis
heuristic-v2 - From regex patterns
ollama-structured-v1 - From LLM extraction
This lets you trace exactly how each field was extracted and trust expense fields more if they came from tables.








commands to update db after any changes in models code:
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "add new column"
.\.venv\Scripts\python.exe -m alembic upgrade head






















Answer: Yes — new/unknown expense lines are still extracted, stored, and shown in reports.

Short explanation

- The parser does not require a description to exactly match a hardcoded expense field name to consider it an expense.
- Expense rows extracted from tables or recognized text are categorized where possible by `_categorise_expense()`; if not classifiable to a known canonical key, they are preserved as itemized rows (or mapped to `other_charges`/generic categories).
- The parser persists extracted rows (structured JSON when available, or parsed field rows) as `ParsedField` rows with `model_version` indicating the extraction method (e.g. `expense-table-geo-v1`, `expense-table-v2`, `heuristic-v2`).
- The Submission/report generator (`services/submission/app/main.py`) builds the report dynamically from stored `ParsedField` rows and will include these new/unknown expenses in the expense breakdown displayed in generated PDFs.

What happens for a completely new expense label (step-by-step)

1. OCR extracts page text and/or structured table rows and writes `OcrResult` rows (per page).
2. Parser runs `_extract_expense_table(...)` which tries multiple cascaded passes:
   - structural table pass (uses detected `tables`),
   - pipe-delimited pass,
   - regex multi-space pass,
   - numbered-line and parallel-line passes.

   If any pass finds a row it extracts a (description, inferred_category, amount) tuple. Known CPT amounts are filtered out.

3. Categorization: `_categorise_expense(description)` attempts to map the description to canonical field names (e.g. `room_charges`, `pharmacy_charges`). If it cannot reliably map, the parser will still keep the original description and amount as a line item (and may attribute it to a generic `other_charges` or store the full structured JSON for the line under a `ParsedField` with `model_version` starting with `expense-table`).

4. Storage: Parser persists extracted rows as `ParsedField` records (or structured JSON values under `ParsedField.field_value` when extraction produced JSON). Each `ParsedField` includes:
   - `claim_id`, `document_id`, `field_name` (canonical or generic), `field_value` (amount or JSON), `source_page`, `model_version`.

5. Report assembly: Submission service reads all `ParsedField` rows for the claim; it builds an `expenses` list using `_EXPENSE_FIELDS` mapping for display labels, but it also preserves rows whose `field_name` or `model_version` indicate a structured expense row. Thus new categories appear in the report either under a derived display label or as "Other Charges" with the original description and amount intact.

Files & functions to review in the codebase

- OCR extraction: `services/ocr/app/engine.py` — `extract_text()`, `_extract_from_pdf()`, `_extract_from_image()`
- Parser orchestration: `services/parser/app/engine.py` — key functions:
  - `_gather_ocr_pages()` — collects `OcrResult` rows
  - `_build_page_objects()` / `_classify_page_document_type()` — builds page objects and doc types
  - `_extract_expense_table(text, page_num, tables, known_cpt_codes)` — expense table extraction (structural and fallbacks)
  - `_categorise_expense()` — maps descriptions to canonical categories
  - `_extract_with_heuristic()` — heuristic field extraction using regexes
  - `_enrich_fields_with_doc_info()` / `_persist_fields()` — attach document/page info and persist `ParsedField` rows
- Submission/report building: `services/submission/app/main.py` — `_gather_claim_data_full()`, `_build_parsed_field_map()`, and expense assembly logic that reads `ParsedField` rows and creates the `expenses` list for PDFs

What you will see in reports for new expense items

- If the parser extracted a structured line (table row) it will be visible in the report as an itemized line with its description, inferred category (or fallback to "Other Charges"), amount, and provenance (`document_id`/`source_page`).
- If only a heuristic regex matched and no canonical category was found, the value may still be shown as an expense under a generic label, but you can trace it back via `ParsedField.model_version` and `ParsedField.document_id`.

Quick pointers to validate on a claim in the running system

1. Upload a test PDF with a new expense label.
2. After processing, inspect the DB tables:
   - `ocr_results` (text extracted)
   - `parsed_fields` (new rows should include the extracted expense)
3. Open the submission preview endpoint to view the dynamic expense breakdown (or generate TPA/IRDA PDF via the submission endpoints).

Report file saved

- File path: docs/generated_claim_processing_report.md

Next steps (if you want):
- I can add a sample unit test claiming a PDF snippet and verifying that a novel expense line ends up in `ParsedField` and the submission expenses list.
- Or I can trace a specific claim/document in your DB and show the exact `ParsedField` rows for that claim.

What I did now

- Added a TODO tracking entry and wrote the detailed report to `docs/generated_claim_processing_report.md`.

Would you like me to add the unit test or inspect a specific claim's parsed rows?