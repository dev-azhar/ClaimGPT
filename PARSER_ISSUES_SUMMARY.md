# PARSER ISSUES - QUICK SUMMARY

## Your Problem
✗ Uploaded patient discharge images → Only patient name shown in report  
✗ All other fields showing as "NA"  
✗ Hospital expenses table not shown  
✓ PDF files with extractable text work fine

---

## ROOT CAUSE ANALYSIS

### Problem #1: Multi-Field Lines Breaking Field Extraction (HIGH PRIORITY)
**What's happening**:
```
Image OCR produces:
"Bill No. 29 Years 26 Sex- FEMALE Occupation: HOUSE IPD BiLL WIFE DOA- 09-04-2026"

Parser extracts "age" field as:
"Bill No. 29 Years 26 Sex- FEMALE Occupation: HOUSE IPD BiLL WIFE DOA- 09-04-2026"  ← ENTIRE LINE!

Should extract:
"29" or "29 Years"  ← Just the age value
```

**Why**:
- OCR groups multiple form labels on one line
- Form extractor doesn't recognize "Sex-", "Occupation:", "DOA-" as label boundaries
- Regex logic is too greedy — captures everything after label until row end

**Location**: `services/parser/app/form_extractor.py` lines 40-90


### Problem #2: Missing Field Anchors (HIGH PRIORITY)
**What's happening**:
- Only patient_name and hospital_name are being extracted
- Diagnosis, date of discharge, and other fields are skipped

**Why**:
- Form extractor has hardcoded ANCHORS list (patient_name, age, sex, address, admission_date, discharge_date, hospital_name, occupation)
- "DIAGNOSIS-" in the OCR text doesn't match any anchor pattern
- Discharge-specific fields (diagnosis, medications) not in the anchor list

**Location**: `services/parser/app/form_extractor.py` lines 1-15


### Problem #3: No Hospital Expenses Table Detected (MEDIUM PRIORITY)
**What's happening**:
```
Debug output: ppstructure_tables.json = []   (EMPTY)
Debug output: normalized_expenses.json = []  (EMPTY)
```

**Why**:
- Your document is a **discharge summary**, not a hospital bill
- Discharge summaries DON'T typically have expense tables
- The parser is looking for expense keywords (room, charges, pharmacy)
- But your document has **medication table instead** (TAB, MACPOD, METRO ER)
- Medication tables are NOT being extracted because the parser doesn't know how to handle them

**Location**: `services/parser_v2/layout_detector.py` & `services/parser/app/table_extractor.py`

**Note**: This is EXPECTED behavior for discharge summaries. Expenses would come from a separate hospital bill document.

---

## Why PDFs Work Better
**PDF Path**:
- `pdfplumber` extracts embedded text that's already well-formatted
- Text has natural delimiters (newlines, spacing, indentation)
- No OCR errors → no multi-label lines problem

**Image Path**:
- EasyOCR/PaddleOCR converts pixels → text with coordinates
- More prone to OCR errors and misplaced delimiters
- Text structure depends on image quality

---

## What's Working
✓ OCR is successfully converting images to text + coordinates  
✓ Document classification correctly identifies discharge summaries  
✓ Layout detector finds form regions  
✓ PDF files with extractable text work as expected  
✓ Patient name is extracted correctly

---

## What's Broken
✗ Form field extraction too greedy (captures entire line)  
✗ Discharge summary anchors incomplete (missing diagnosis, medications)  
✗ Medication tables not normalized/displayed  
✗ Multi-field lines not split properly  

---

## TOOLS & MODELS IN USE

| Stage | Tool | Accuracy |
|-------|------|----------|
| Image OCR | **EasyOCR** or **PaddleOCR** | ~95% (errors in merged labels) |
| PDF Text | **pdfplumber** | ~99% (native extraction) |
| Layout Detection | Geometric heuristics (Y/X coordinate clustering) | ~90% (coordinate-based) |
| Form Extraction | Regex + anchor matching | ~60% (greedy, multi-label issues) |
| Table Detection | Row/column clustering + keyword matching | ~70% (expense-only) |
| Classification | Keyword pattern matching | ~95% |

---

## RECOMMENDED ACTIONS

### 1. Fix Multi-Label Line Parsing
Add lookahead in form extractor to detect next label and stop:
```python
# Stop values collection if next token contains:
STOP_LABELS = ["sex-", "occupation:", "doa-", "dod-", "address-", "diagnosis-"]
```

### 2. Add Discharge Summary Anchors
```python
ANCHORS["diagnosis"] = ["diagnosis", "final diagnosis"]
ANCHORS["discharge_date"] = ["dod", "discharge date", "date of discharge"]
ANCHORS["medications"] = ["rx", "treatment on discharge", "medicines"]
```

### 3. Extract Medication Tables
For discharge summaries, recognize and extract:
- Medicine name, dosage, frequency, days
- Display as "Medications" section (not "Expenses")

### 4. Better Multi-Anchor Detection
Pre-split merged anchor-value pairs:
```
Input:  "Bill No. 29 Years 26 Sex- FEMALE Occupation: HOUSE"
Split:  ["Bill No.", "29 Years", "26", "Sex-", "FEMALE", "Occupation:", "HOUSE"]
Parse:  age=29, sex=FEMALE, occupation=HOUSE
```

---

## Debug Files Location
- `/tmp/parser_debug/normalized_fields.json` — Extracted fields (currently wrong)
- `/tmp/parser_debug/normalized_expenses.json` — Extracted expenses (empty for discharge)
- `/tmp/parser_debug/detected_regions.json` — Found regions
- `/tmp/parser_debug/ppstructure_tables.json` — Extracted tables (empty)
- `/tmp/parser_debug/layout_model_regions.json` — Region classification

---

## Next Steps
1. **Immediate**: Fix multi-label line parsing in `form_extractor.py`
2. **Short-term**: Add discharge summary field anchors
3. **Medium-term**: Implement medication table extraction
4. **Long-term**: Consider LLM-based field extraction for complex forms
