# OCR & Parser Workflow - Detailed Analysis

## 1. OVERALL WORKFLOW ARCHITECTURE

```
IMAGE/PDF UPLOAD
    ↓
[OCR SERVICE] - Extract text + token coordinates
    ↓
Token Stream: {text, x0, y0, x1, y1, page, document_id}
    ↓
[PARSER V2 PIPELINE] - Geometric-first parsing
    ├─ Layout Detection (Region Classification)
    ├─ Form Field Extraction
    ├─ Table Detection & Reconstruction
    └─ Normalization
    ↓
Canonical JSON Output
    ↓
[REPORT RENDERING] - Display extracted data
```

---

## 2. OCR PROCESSING FLOW (Image Path)

### 2.1 Entry Point
- **File**: `services/parser/app/main.py`
- **Endpoint**: Background job `_run_parse_job()` triggered when documents are uploaded

### 2.2 OCR Extraction
**Current Pipeline**:
1. For **PDF files**: Uses `pdfplumber` to extract embedded text (WORKS WELL ✓)
2. For **Image files**: Uses **EasyOCR** (if installed) or **PaddleOCR**
   - Produces token coordinates: `{text, x0, y0, x1, y1}`
   - Stores in `OcrResult` table with page-by-page text

**OCR Models Available**:
- **EasyOCR**: Preferred for images (faster, more accurate)
- **PaddleOCR**: Fallback (slower, needs v3.x for latest API)
- **Tesseract**: Last resort (older fallback)

### 2.3 Token Geometry
Each OCR token has precise bounding box coordinates:
```json
{
  "text": "AMREEN",
  "x0": 210.0,
  "y0": 216.0,
  "x1": 464.0,
  "y1": 246.0,
  "page": 1,
  "document_id": "doc-uuid"
}
```

**Key Insight**: These coordinates are CRITICAL for geometric layout detection. They bypass line-inference and provide actual pixel positions.

---

## 3. PARSER V2 PIPELINE (Geometry-First)

**File**: `services/parser_v2/pipeline.py`

### 3.1 Phase 1: Region Detection
```python
parse_v2(all_tokens, page_images=..., document_paths=...)
```

**Steps**:
1. **Detect Regions** → Classify areas as:
   - `patient_form` (demographics)
   - `expense_table` (hospital bills)
   - `diagnosis` (clinical findings)
   - `header/footer` (non-essential)

2. **Reconstruct Tables** → Build cell grid from token coordinates
   - Clusters tokens into rows (Y-proximity, tolerance=8px)
   - Organizes rows into columns (X-proximity, tolerance=28px)
   - Creates table cells with text content

3. **Extract Form Fields** → Anchor-based extraction from form regions
   - Looks for known labels: "Patient Name:", "Date of Admission:", etc.
   - Collects text to the RIGHT of the label (same row)
   - STOPS when hitting next label

4. **Normalize Data** → Standardize field names & expense categories
   - Maps raw fields → canonical schema
   - Validates field values (dates, amounts, etc.)

### 3.2 Hybrid Fallback Strategy
If model-assisted detection fails:
- Falls back to **geometric heuristics** (coordinate-based clustering)
- Recursive re-scan with tighter tolerance (12px) if no tables found
- Nested table detection within form regions

---

## 4. FORM FIELD EXTRACTION DETAILS

**File**: `services/parser/app/form_extractor.py`

### 4.1 Anchor-Based Extraction
```python
ANCHORS = {
    "patient_name": ["patient name", "name", "insured name"],
    "age": ["age", "age/sex"],
    "sex": ["sex", "gender"],
    "admission_date": ["admission date", "doa", "admitted on"],
    # ... more anchors
}
```

### 4.2 Extraction Algorithm
1. **Row Clustering**: Group tokens by Y-coordinate (tolerance 6px)
2. **Left-to-Right Scan**: Process each row from left to right
3. **Anchor Matching**: Match 1-3 consecutive tokens against ANCHORS
4. **Value Collection**: Grab tokens AFTER anchor until:
   - Next label found
   - Large horizontal gap (>50-100px)
   - End of row
5. **Concatenation**: Join value tokens with spaces

### 4.3 ISSUE #1: Multi-Label Lines
**Problem**: OCR puts multiple labels on ONE line

Example from your discharge summary:
```
Line: "Bill No. 29 Years 26 Sex- FEMALE Occupation: HOUSE IPD BiLL WIFE DOA- 09-04-2026"
```

The extractor sees:
- Anchor: "Age" or "Years" → value starts collecting
- **BUG**: Captures EVERYTHING after until row end: `"Bill No. 29 Years 26 Sex- FEMALE Occupation: HOUSE IPD BiLL WIFE DOA- 09-04-2026"`
- **Missing**: No stop-logic for "Sex-" or "Occupation:" labels

**Current Behavior in Your Data**:
```json
{
  "field_name": "patient_age",
  "field_value": "Bill No. 29 Years 26 Sex- FEMALE Occupation: HOUSE IPD BiLL WIFE DOA- 09-04-2026TIME 08.55 AM"
}
```

---

## 5. TABLE DETECTION & EXTRACTION

**Files**:
- `services/parser_v2/layout_detector.py` - Region finding
- `services/parser_v2/table_reconstructor.py` - Cell grid building
- `services/parser/app/table_extractor.py` - Content extraction

### 5.1 Table Detection Strategy
1. **Y-Clustering**: Find rows where tokens cluster vertically
2. **Pattern Matching**: Look for:
   - "Room", "Charges", "Consultation", "Pharmacy" (expense keywords)
   - Numeric amounts (Rs.XXX or digit patterns)
   - Multiple columns (>= 3)
3. **Validate**: Must have >=2 header-like rows

### 5.2 Table Reconstruction
```python
detect_regions(tokens, gap_threshold=8.0)
  ↓
cluster_rows_by_y(tokens)     # Group by Y (8px tolerance)
  ↓
_cluster_columns_by_x(tokens)  # Group by X (28px tolerance)
  ↓
_build_table_cells(...)        # Assign tokens to cells
  ↓
Table: { header, rows: [[cell1, cell2], ...] }
```

### 5.3 ISSUE #2: No Expense Table Detected
**Problem**: Your discharge summary has **NO hospital expense table**

Debug Output:
```json
ppstructure_tables.json: []                    // EMPTY - no tables found
normalized_expenses.json: []                   // EMPTY - no normalized expenses
layout_model_regions.json: [                   // Only found forms & footer
  { "type": "patient_form", "bbox": [...] },
  { "type": "footer", "bbox": [...] }
]
```

**Why?**
- Discharge summaries typically DON'T have expense tables
- Your document has **medication tables** instead (TAB, MACPOD, METRO ER, DETTOL)
- Parser only looks for EXPENSE keywords, not medication keywords in discharge context

---

## 6. DOCUMENT CLASSIFICATION

**File**: `services/parser/app/document_classifier.py`

```python
def classify_document(ocr_pages, layout):
    if "discharge summary" in text:
        return "discharge_summary"    # Routes to discharge_parser.py
    if "hospital bill" in text:
        return "hospital_bill"         # Routes to bill_parser.py
    if "prescription" in text:
        return "prescription"          # Routes to prescription_parser.py
    if "lab report" in text:
        return "lab_report"            # Routes to lab_parser.py
```

**For Your Case**: Correctly classified as `discharge_summary` ✓

**But**: Different parsers have different field & table expectations
- Discharge: Diagnosis, medications, vitals, patient info
- Hospital Bill: Expenses, room charges, procedures, amount due

---

## 7. WHY PDF WITH PDFPLUMBER WORKS BETTER

### 7.1 PDF Path (Text-Extractable PDFs)
1. **pdfplumber** extracts embedded text (already structured)
2. Text has better semantic delimiters (newlines, indentation)
3. Field extraction regex matches more reliably
4. Table rows are pre-delimited in PDF structure

### 7.2 Image Path (Current Issue)
1. **EasyOCR/PaddleOCR** convert pixels → text + coordinates
2. OCR makes mistakes:
   - Misreads characters (e.g., "O" as "0", "l" as "1")
   - Misplaces delimiters (missing colons, dashes)
   - Groups tokens in unexpected ways
3. Multi-label lines are harder to parse coordinately
4. Confidence scores may not reflect actual accuracy

**Example from Your Upload**:
```
OCR saw:     "Bill No. 29 Years 26 Sex- FEMALE Occupation: HOUSE"
Should be:   "Age: 29 Years, Sex: FEMALE, Occupation: House"
```

---

## 8. DETAILED ISSUES IN YOUR CASE

### ISSUE #1: Multi-Field Lines Not Properly Split
**Location**: Discharge form header region

**Current Extraction**:
```
Line 1: "Bill No. 29 Years 26 Sex- FEMALE Occupation: HOUSE IPD BiLL WIFE DOA- 09-04-2026"
  ├─ Age extracted as: "Bill No. 29 Years 26 Sex- FEMALE Occupation: HOUSE IPD BiLL WIFE DOA- 09-04-2026" ✗
  ├─ Should be: "29" or "29 Years" ✓
  └─ Stop at next label: "Sex-" or "Occupation:"

Line 2: "DOD- 10-04-2026TIME Oo.00.00 Initial"
  ├─ Patient ID extracted as: "DOD- 10-04-2026TIME Oo.00.00 Initial" ✗
  ├─ Should be: None found (or parse discharge date) ✓
  └─ Problem: "DOD" = Date of Discharge, not Patient ID
```

**Root Cause**: Form extractor tries to split merged labels but:
- Regex `r"^([A-Za-z\s]+)([:\-])(.+)$"` only works on single token
- Multi-token labels like "Bill No." confuse the splitter
- Stop-logic doesn't recognize "Sex-", "Occupation:", "DOD-" as labels

### ISSUE #2: Hospital Expenses Table Not Detected
**Location**: Should be in bill section (but this is discharge summary)

**Current Extraction**:
```
normalized_expenses.json: []           // Empty - no expense items
ppstructure_tables.json: []            // No table structure found
```

**Why**:
1. Document is **discharge summary**, not hospital bill
2. No expense table structure present (would be in separate bill document)
3. Medication table (TAB, MACPOD, METRO ER) NOT extracted as expense table

**Note**: Medication tables ARE present but parser doesn't normalize them as "expenses"

### ISSUE #3: Diagnosis Field Not Captured
**Location**: Should capture full diagnosis text

**Observed**: Only patient_name shown in report

**OCR Text Available**:
```
"DIAGNOSIS- G3PILIAI 39WKS ZDAYS PREGNANCY IN LABOUR
FTND C EPISIOTOMY ON 09/04/2026 AT 6 2aRM MALE BABYOF WT 2 8kG"
```

**Why It's Missing**:
- Form extractor only looks for specific ANCHORS
- "DIAGNOSIS-" not in anchor list (needs "diagnosis" in lowercase without dash)
- Diagnosis is parsed as region, not extracted as field

---

## 9. TOOLS & MODELS BEING USED

| Component | Tool/Model | Status |
|-----------|-----------|--------|
| Image OCR | EasyOCR or PaddleOCR | ✓ Working |
| PDF Text | pdfplumber | ✓ Working |
| Layout Detection | Geometric heuristics (coordinate-based) | ⚠️ Limited for discharge docs |
| Form Extraction | Regex + anchor matching | ⚠️ Greedy (captures too much) |
| Table Detection | Y/X clustering + pattern matching | ⚠️ Expense-focused |
| Document Classification | Keyword matching | ✓ Working |
| Normalization | Schema validation | ⚠️ Only handles detected fields |

---

## 10. CRITERIA FOR FIELD/TABLE EXTRACTION

### 10.1 Form Field Criteria
- Must match anchor label (case-insensitive, partial match OK)
- Value collected to RIGHT on same row only
- Stops at next label or large gap (>50-100px)
- Requires at least 1 token after label

### 10.2 Table Row Criteria (Expenses)
- Must have 3+ columns (via X-clustering)
- At least one row with expense keyword (room, charges, pharmacy, etc.)
- At least one numeric cell (amount)
- Skip header rows (non-numeric text only)

### 10.3 Medication Table Criteria (If Implemented)
- Keywords: "tab", "cap", "inj", "medicine", "dosage", "frequency"
- Multiple columns aligned
- Non-numeric first column (medicine name)

---

## SUMMARY: ROOT CAUSES

| Issue | Root Cause | Fix Priority |
|-------|-----------|--------------|
| Only patient_name shown | Form extractor is greedy; other fields not extracted | HIGH |
| Other fields = "NA" | Anchors don't match OCR text exactly; multi-label lines confuse parser | HIGH |
| Hospital expenses table missing | Document is discharge summary, not bill; no expense table present | MEDIUM |
| PDF files work better | pdfplumber text is pre-structured; OCR has more errors | N/A (expected) |

---

## RECOMMENDED FIXES

### Fix #1: Improve Multi-Label Line Handling
**Location**: `services/parser/app/form_extractor.py`

```python
# Current: Captures entire line after label
# Better: Detect next label and stop before it
# Add check for common discharge form labels:
# "Sex-", "Occupation:", "DOA-", "DOD-", "Address-", "Diagnosis-"
```

### Fix #2: Add Discharge Summary Field Anchors
**Location**: `services/parser/app/form_extractor.py` → ANCHORS dict

```python
ANCHORS = {
    "diagnosis": ["diagnosis", "final diagnosis", "icd"],
    "discharge_date": ["discharge date", "dod", "date of discharge"],
    "medication_list": ["treatment on discharge", "rx", "medicine prescribed"],
    # ... add more diagnosis-specific fields
}
```

### Fix #3: Extract Medication Tables from Discharge Summaries
**Location**: `services/parser_v2/layout_detector.py`

```python
# Detect medication tables in discharge summaries
# Look for: TAB, CAP, INJ keywords + dosage patterns
# Extract as separate normalized entity (not expenses)
```

### Fix #4: Improve Table Detection for Non-Expense Tables
**Location**: `services/parser/app/table_extractor.py`

```python
# Currently: Only looks for expense keywords
# Better: Classify table type (medication, vitals, lab, diagnosis, expense)
# Route to category-specific extractor
```

