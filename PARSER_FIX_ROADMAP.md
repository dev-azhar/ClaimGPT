# PARSER FIX ROADMAP

## Overview
You uploaded a **discharge summary image** containing patient diagnosis data. Only patient_name shows; all other fields (age, gender, diagnosis, medications) are N/A or incorrectly extracted. This is due to **three main issues** in the parser.

---

## ISSUE #1: Multi-Label Lines Breaking Field Extraction 🔴

### Location
`services/parser/app/form_extractor.py` lines 40-90

### Problem Example
```
OCR Input Line (all tokens on Y=242):
  Token: "Bill" (x: 108-142)
  Token: "No." (x: 142-180)
  Token: "29" (x: 180-210)
  Token: "Years" (x: 210-260)
  Token: "26" (x: 260-300)
  Token: "Sex-" (x: 300-350)
  Token: "FEMALE" (x: 350-420)
  Token: "Occupation:" (x: 420-500)
  Token: "HOUSE" (x: 500-550)

Parser matches anchor "age" → Should collect: "29" or "29 Years"
Current behavior: Captures EVERYTHING after label to row end = "Bill No. 29 Years 26 Sex- FEMALE Occupation: HOUSE"

Why? No lookahead to detect next label as boundary
```

### Current Code (Lines 75-90)
```python
while i < len(row):
    # Stop if there's a large horizontal gap (e.g. > 50px)
    if value_tokens:
        gap = row[i]["x0"] - value_tokens[-1]["x1"]
        if gap > 50:
            break
    # ... but NO check for next label like "Sex-", "Occupation:"
```

### Required Fix
```python
# Add before collecting values:
STOP_LABELS_DISCHARGE = ["sex", "occupation", "doa", "dod", "address", "diagnosis"]

while i < len(row):
    # NEW: Check if current token starts a new label
    token_text = row[i].get("text", "").lower().rstrip(":-")
    if any(sl in token_text for sl in STOP_LABELS_DISCHARGE):
        break  # Stop collecting values - next label found
    
    # ... rest of logic
```

### Impact
- Will correctly extract: age="29", gender="FEMALE", occupation="HOUSE WIFE"
- Prevents N/A values for merged-line fields

---

## ISSUE #2: Missing Discharge Summary Field Anchors 🔴

### Location
`services/parser/app/form_extractor.py` lines 1-15

### Current ANCHORS Dict
```python
ANCHORS = {
    "patient_name": ["patient name", "name", "insured name"],
    "age": ["age", "age/sex"],
    "sex": ["sex", "gender"],
    "address": ["address", "residence"],
    "admission_date": ["admission date", "doa"],
    "discharge_date": ["discharge date", "dod"],  # ← Only "dod" pattern
    "hospital_name": ["hospital name"],
    "occupation": ["occupation"],
}
```

### Problem Fields Not Extracted
```
Document has:
  - "DIAGNOSIS-" (NOT matched)
  - "DOD-" as "Date of Discharge" (should be mapped, but confused)
  - "Address -" (dash not colon format)
  - Treatment/medications section (no anchor)
```

### Required Fix
```python
ANCHORS = {
    # ... existing anchors ...
    "diagnosis": ["diagnosis", "final diagnosis", "diagnose", "clinical diagnosis"],
    "discharge_date": ["discharge date", "dod", "date of discharge", "discharged on"],
    "address": ["address", "residence", "address -"],  # Add dash variant
    "occupation": ["occupation", "profession", "job"],
    "hospital_name": ["hospital", "nursing home", "maternity home", "clinic"],
}
```

### Additional: Fix DOD Anchor
Current issue: "DOD-" is being misinterpreted as patient_id instead of discharge_date

```python
# In form_extractor.py, before collecting DOD value:
if matched_key == "discharge_date" and token_text.upper() == "DOD":
    # Check if this is actually discharge_date, not being mislabeled
    # by looking at format: DOD-DDMMYYYY
    pass  # Will be handled correctly once anchor matching is fixed
```

### Impact
- Will extract: diagnosis="G3PILIAI 39WKS 2DAYS PREGNANCY IN LABOUR"
- Will extract: discharge_date="10-04-2026"
- Will extract: address="BHAIGAON ROAD SHARDA NAGAR"

---

## ISSUE #3: Medication Tables Not Extracted 🟡

### Location
`services/parser/app/table_extractor.py` + New: `services/parser/app/medication_extractor.py`

### Current Limitation
Table extractor only looks for **expense keywords**:
```python
MEDICAL_KEYWORDS = ["room", "pharmacy", "consultation", "nursing", 
                   "laboratory", "consumables", "procedure", "charges"]
```

### Medication Table Present But Not Extracted
```
TREATMENT ON DISCHARGE:
Rx
Type    Drug Name        Dose    Days    Instruction
TAB.    LYSER D          14      AFTER MEALS
TAB.    MACPOD 0         -       AFTER MEALS
TAB.    METRO ER         -       AFTER MEALS
DETTOL  10               -       (missing)
```

### Required Fix: Create Medication Extractor
**New File**: `services/parser/app/medication_extractor.py`

```python
def extract_medication_table(table_region: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract medication table from discharge summary."""
    medications = []
    
    # Detect medication table by keywords in header
    header_text = " ".join(t.get("text", "").lower() for t in table_region.get("header", []))
    if not any(kw in header_text for kw in ["drug", "medicine", "tab", "type", "dose"]):
        return []
    
    for row in table_region.get("rows", []):
        tokens = sorted(row.get("tokens", []), key=lambda t: t["x0"])
        
        # Skip header rows
        row_text = " ".join(t.get("text", "") for t in tokens).lower()
        if any(kw in row_text for kw in ["type", "drug name", "dosage", "days"]):
            continue
        
        # Extract columns based on X-position
        cols = _cluster_columns_by_x(tokens)
        medicine_name = cols[0] if len(cols) > 0 else ""
        dosage = cols[1] if len(cols) > 1 else ""
        frequency = cols[3] if len(cols) > 3 else ""
        days = cols[2] if len(cols) > 2 else ""
        
        if medicine_name:
            medications.append({
                "medicine_name": medicine_name.strip(),
                "dosage": dosage.strip(),
                "days": days.strip(),
                "frequency": frequency.strip(),
                "table_type": "medication"
            })
    
    return medications
```

### Integration Point
In `services/parser_v2/pipeline.py` line ~80:

```python
# After table extraction:
for table in doc.tables:
    category = infer_table_category(table)  # medication, expense, lab, etc.
    
    if category == "medication":
        medications = extract_medication_table(table)
        # Store separately or in normalized format
    elif category == "expense":
        expenses = extract_expense_table(table)
```

### Impact
- Medications table will be extracted and displayed in report
- Report will show: "Medications: LYSER D (14 days), MACPOD 0, METRO ER, DETTOL"

---

## IMPLEMENTATION PRIORITY & EFFORT

| Issue | Priority | Effort | Files | Expected Result |
|-------|----------|--------|-------|-----------------|
| Multi-label line fix | HIGH | 15 min | form_extractor.py | age, gender, occupation extracted correctly |
| Add discharge anchors | HIGH | 10 min | form_extractor.py | diagnosis, discharge_date, address extracted |
| Medication extraction | MEDIUM | 1-2 hrs | New: medication_extractor.py + pipeline.py | Medications table displayed in report |

---

## Testing After Fix

### Test Case #1: Your Discharge Image
```
Input: Patient discharge summary (JPG image)
Expected Output:
  ✓ patient_name: AMREEN AZHAR SHAIKH
  ✓ patient_age: 29
  ✓ patient_gender: FEMALE
  ✓ admission_date: 09-04-2026
  ✓ discharge_date: 10-04-2026
  ✓ diagnosis: G3PILIAI 39WKS 2DAYS PREGNANCY IN LABOUR
  ✓ medications: [4 items]
  ✓ Report: All fields populated
```

### Test Case #2: Hospital Bill (Expense Table)
```
Input: Hospital bill (JPG/PDF)
Expected Output:
  ✓ patient details: extracted
  ✓ expense_table: [room charges, pharmacy, procedures, etc.]
  ✓ total_amount: calculated
```

### Test Case #3: Lab Report
```
Input: Lab investigation report
Expected Output:
  ✓ patient details: extracted
  ✓ lab_table: [test name, result, normal range, etc.]
```

---

## Debug Commands

### Run Parser Only (Skip OCR)
```python
# Use existing debug output
import json
with open("tmp/parser_debug/detected_regions.json") as f:
    regions = json.load(f)
print(f"Regions found: {len(regions)}")
```

### Check Current Extraction
```python
import json
with open("tmp/parser_debug/normalized_fields.json") as f:
    fields = json.load(f)
for f in fields:
    print(f"{f['field']} = {f['value'][:50]}...")
```

### Monitor After Fix
```python
# After implementing fixes:
# 1. Should show age/gender/diagnosis in normalized_fields.json
# 2. Should show medications in normalized_expenses.json or new section
# 3. Report preview should show all fields (not N/A)
```

---

## Files to Modify

```
services/parser/app/form_extractor.py
  ├─ Line 10-15: Add missing ANCHORS for discharge
  ├─ Line 75-90: Fix multi-label line logic
  └─ Line 40-50: Add STOP_LABELS check

services/parser_v2/pipeline.py
  ├─ Line 75-85: Integrate medication extractor
  └─ Add medication_table detection

NEW FILE: services/parser/app/medication_extractor.py
  ├─ extract_medication_table() function
  ├─ _cluster_columns_by_x() helper
  └─ Normalize medication rows
```

---

## Why This Matters

| Before Fix | After Fix |
|-----------|-----------|
| Report shows only patient_name | Report shows patient_name, age, gender, diagnosis, discharge date, address, occupation |
| All demographic fields = N/A | All fields populated correctly |
| Medications not shown | Medications table displayed with dosage & frequency |
| Image uploads fail; PDF works | Image uploads work same as PDF |

This is why PDFs work but images don't: PDFs have pre-structured text, images need better parsing logic.

---

## Questions?

See detailed analysis in:
- `PARSER_OCR_WORKFLOW_ANALYSIS.md` - Full workflow explanation
- `PARSER_ISSUES_SUMMARY.md` - Quick reference
- `PARSER_DEBUG_OUTPUT_ANALYSIS.md` - Side-by-side comparison of buggy vs expected output
