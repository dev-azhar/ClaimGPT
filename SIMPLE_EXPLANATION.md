# SIMPLE EXPLANATION - Why Your Diagnosis Data Isn't Showing

## THE PROBLEM (In Simple Terms)

You uploaded an image of a **patient discharge summary** (from a maternity hospital). The image contains:
- Patient name: AMREEN AZHAR SHAIKH ✓ (shown)
- Patient age: 29 ✗ (not shown - N/A)
- Gender: FEMALE ✗ (not shown - N/A)
- Diagnosis: G3PILIAI 39WKS... ✗ (not shown - N/A)
- Medications: 4 medicines ✗ (not shown - N/A)

**Only patient name appears in report. Everything else says "N/A".**

---

## ROOT CAUSE IN PLAIN ENGLISH

Think of the parser like a person reading a form:

### How OCR Works (Converting Image → Text)
```
Person with OCR glasses looks at image:
  "Okay, I see words here..."
  Says each word out loud:
    "Bill... No... 29... Years... 26... Sex... FEMALE... Occupation... HOUSE"
  And remembers position: "29 is at pixel (180, 242), Years is at (210, 242)..."
```

### How Parser Should Extract Fields
```
Person with extraction skill reads each field:
  1. Looks for label "Age:" or "Patient Age"
  2. Grabs value AFTER label: "29"
  3. Stops when seeing next label "Sex:" or "Gender:"
  4. Records: age = "29"
  
  Repeat for each field...
```

### What ACTUALLY Happens (The Bug)
```
Person sees: "Bill No. 29 Years 26 Sex- FEMALE Occupation: HOUSE"
  (all on same line - no clear separation)

Person looks for "Age" pattern → finds "29 Years 26"
Person thinks: "Age must be all the text after I found '29'..."
Person records: age = "Bill No. 29 Years 26 Sex- FEMALE Occupation: HOUSE"  ← WRONG!

Person stops at the END of line, not at the NEXT LABEL (Sex-, Occupation:)
```

**Why?** The multiple fields are on the SAME line in the image, so the parser thinks they're all part of one value.

---

## THREE SPECIFIC ISSUES

### Issue #1: Greedy Field Extraction
**The Problem**: Parser collects too much text after a field label

```
Form line in image:  "Age: 29 Sex: FEMALE Occupation: HOUSE"
                      └── label   └─ value (should stop here)
                           └────────────────────────────── but parser captures all this

Parser Logic:
  "Find 'Age' label" ✓
  "Collect everything after it until end of line" ✓
  "Stop when finding next label?" ✗ MISSING
```

**What's happening in YOUR document**:
```
"Bill No. 29 Years 26 Sex- FEMALE Occupation: HOUSE IPD BiLL WIFE DOA- 09-04-2026"
   └─ Bad OCR    └─ age   ↑
                  Parser captures: "Bill No. 29 Years 26 Sex- FEMALE Occupation: HOUSE..."
                  Should capture:  "29" or "29 Years"
```

**Fix Required**: Add logic to STOP when next label appears
```python
# Current: Keep collecting until end of row
# Fixed: Stop if you see "Sex-", "Occupation:", "DOA-", etc.
```

---

### Issue #2: Missing Field Anchors
**The Problem**: Parser doesn't know to look for certain fields in discharge documents

```python
Parser's anchor list (simplified):
  "patient_name" → look for "Patient Name", "Name"
  "age" → look for "Age"
  "sex" → look for "Sex"
  "admission_date" → look for "Admission Date", "DOA"
  # ... but MISSING:
  "diagnosis" ← Your document HAS this
  "discharge_date" ← Your document HAS this
  "address" ← Your document HAS this
  "medications" ← Your document HAS this
```

**What's in YOUR document**:
```
Line: "DIAGNOSIS- G3PILIAI 39WKS ZDAYS PREGNANCY..."
Parser thinks: "I don't know what to do with this... skip it"
Result: diagnosis field = N/A
```

**Fix Required**: Add missing field anchors
```python
# Add to anchor list:
"diagnosis": ["diagnosis", "final diagnosis"]
"discharge_date": ["discharge date", "dod", "date of discharge"]
"address": ["address", "residence"]
```

---

### Issue #3: Medication Tables Not Recognized
**The Problem**: Parser only looks for EXPENSE tables, not medication tables

```
Your document has:
  TREATMENT ON DISCHARGE:
  Medicine Name    Dose     Days    Instructions
  LYSER D          TAB      14      AFTER MEALS
  MACPOD 0         TAB      -       AFTER MEALS
  METRO ER         TAB      -       AFTER MEALS
  DETTOL           -        10      (missing)

Parser thinks: "This looks like a table..."
              "But does it have keywords like 'Room', 'Charges', 'Pharmacy'?"
              "No... so skip it"
Result: No medications extracted
```

**Why it's different from PDFs**:
- PDF: pdfplumber has already separated fields with newlines, so parser recognizes medication section
- Image: OCR produces continuous text, medication keywords not obvious

**Fix Required**: Create medication extractor
```python
# Detect tables with keywords: "medicine", "drug", "tab", "dose", "days"
# Extract as medication table (not expense table)
```

---

## WHY PDF WORKS BUT IMAGE DOESN'T

### PDF Path (WORKING ✓)
```
1. Upload PDF with extractable text
2. pdfplumber says: "I found this text structure:
   
   Patient Name: AMREEN AZHAR SHAIKH
   Age: 29
   Sex: FEMALE
   Occupation: HOUSE
   Diagnosis: G3PILIAI...
   
   (proper newlines/structure)"
   
3. Parser reads structured text → easy to extract each field
4. Result: All fields extracted correctly
```

### Image Path (BROKEN ✗)
```
1. Upload discharge image
2. EasyOCR says: "I see this text:
   
   AMREEN AZHAR SHAIKH IPD REG NO- 1-28/2026 DOA- 09-04-2026 TIME 08.55 AM
   29 Years Sex- FEMALE Occupation: HOUSE WIFE DOD- 10-04-2026
   Address - BHAIGAON ROAD SHARDA NAGAR
   DIAGNOSIS- G3PILIAI 39WKS...
   
   (all on same lines, no structure)"
   
3. Parser reads poorly-structured text → hard to separate fields
4. Result: Only patient_name works, others are N/A or wrong
```

**Key Difference**: PDFs have explicit document structure. Images are pixel grids, so OCR has to guess where text breaks are.

---

## REAL WORKFLOW

```
                    ┌─────────────────────────────────┐
                    │   YOU UPLOAD IMAGE/PDF          │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │   OCR/EXTRACTION STAGE      │
        ┌───────────┤   • EasyOCR (images)       ├──────────┐
        │           │   • pdfplumber (PDFs)      │          │
        │           └────────────────────────────┘          │
        │                                                     │
        │        Token Stream: {text, x0, y0, x1, y1}       │
        │        "29" at (180,242), "FEMALE" at (350,242)   │
        │                                                     │
        │           ┌─────────────────────────┐              │
        └──────────▶│  PARSER V2 PIPELINE     ├─────────┐   │
                    │                         │         │   │
                    │  1. Detect Regions      │         │   │
                    │  2. Classify Doc Type   │         │   │
                    │  3. Extract Form Fields ◀─────────┼───┘
                    │  4. Extract Tables      │    BUG: Takes entire
                    │  5. Normalize           │    line as one field
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼───────────┐
                    │  CANONICAL JSON       │
                    │  patient_name: AMREEN │
                    │  patient_age: [WRONG] │ ◀── Should be "29"
                    │  diagnosis: N/A       │ ◀── Should have value
                    │  medications: N/A     │ ◀── Should have table
                    └────────────┬───────────┘
                                 │
                    ┌────────────▼──────────────┐
                    │  REPORT RENDERING        │
                    │  Patient: AMREEN         │
                    │  Age: N/A                │ ◀── Shows N/A
                    │  Diagnosis: N/A          │
                    │  Medicines: N/A          │
                    └──────────────────────────┘
```

---

## THE FIX (Simple Version)

### Fix #1: Stop at Next Label
**File**: `services/parser/app/form_extractor.py`

**Before (buggy)**:
```python
# Keep collecting tokens for value until end of row
while i < len(row):
    value_tokens.append(row[i])
    i += 1
```

**After (fixed)**:
```python
# Stop if next token is a label
STOP_LABELS = ["sex", "occupation", "doa", "dod", "address", "diagnosis"]
while i < len(row):
    token_text = row[i].get("text", "").lower()
    if any(label in token_text for label in STOP_LABELS):
        break  # Stop here!
    value_tokens.append(row[i])
    i += 1
```

### Fix #2: Add Missing Anchors
**File**: `services/parser/app/form_extractor.py`

```python
# Add these to the ANCHORS dictionary:
"diagnosis": ["diagnosis", "final diagnosis"],
"discharge_date": ["discharge date", "dod", "date of discharge"],
"address": ["address", "residence"],
```

### Fix #3: Extract Medication Tables
**Create**: `services/parser/app/medication_extractor.py`

```python
def extract_medications(table_region):
    # Look for medication keywords in table header
    # Extract columns: medicine_name, dosage, days, frequency
    # Return list of medication dicts
    ...
```

---

## EXPECTED RESULTS AFTER FIXES

### Before (Current - Broken)
```
Report Preview:
  Patient Information
    Name: AMREEN AZHAR SHAIKH
    Age: N/A
    Gender: N/A
    Diagnosis: N/A
    
  Hospital Expenses
    (No table found)
```

### After (Fixed)
```
Report Preview:
  Patient Information
    Name: AMREEN AZHAR SHAIKH
    Age: 29
    Gender: FEMALE
    Address: BHAIGAON ROAD SHARDA NAGAR
    Diagnosis: G3PILIAI 39WKS 2DAYS PREGNANCY IN LABOUR
    
  Medications Prescribed
    1. LYSER D - 14 DAYS - AFTER MEALS
    2. MACPOD 0 - AFTER MEALS
    3. METRO ER - AFTER MEALS
    4. DETTOL - 10 DAYS
```

---

## KEY TAKEAWAY

The issue is NOT with OCR. The OCR correctly reads the text. The problem is the PARSER cannot handle:

1. **Multiple fields on same line** → needs lookahead logic
2. **New field types in discharge documents** → needs expanded anchor list  
3. **Medication tables** → needs new table type handler

PDFs work because the text is already structured. Images need better parsing logic for unstructured text.

All three fixes are in the **form extraction and table detection** logic, not in the OCR itself.

---

## Debug Files Generated

When you uploaded the image, the system created debug files showing the problem:

```
tmp/parser_debug/normalized_fields.json
  → Shows what was extracted (currently broken)
  
tmp/parser_debug/normalized_expenses.json
  → Should show medications/expenses (currently empty)
  
tmp/parser_debug/layout_model_regions.json
  → Shows regions found (no expense_table found - expected for discharge)
  
tmp/parser_debug/ppstructure_tables.json
  → Shows tables found (empty - medication table not detected)
```

These debug files confirm the three issues above.

---

## Next Steps

1. **Quick Fix (15 minutes)**: Fix multi-label line parsing + add missing anchors → Most fields will appear
2. **Medium Fix (1-2 hours)**: Add medication table extraction → Medications will appear
3. **Better Fix (later)**: Consider LLM-based field extraction for even better accuracy

See `PARSER_FIX_ROADMAP.md` for detailed code changes.
