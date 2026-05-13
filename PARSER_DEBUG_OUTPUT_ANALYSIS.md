# PARSER DEBUG OUTPUT ANALYSIS - Your Upload

## Raw OCR Text Extracted
```
DISCHARGE SUMMARY
Original Copy

Name- AMREEN AZHAR SHAIKH
IPD REG NO- |-28/2026
DOA- 09-04-2026 TIME 08.55 AM
29 Years
Sex- FEMALE
Occupation: HOUSE
WIFE
DOD- 10-04-2026 TIME 00.00.00

Address - BHAIGAON ROAD SHARDA NAGAR

DIAGNOSIS- G3PILIAI 39WKS ZDAYS PREGNANCY IN LABOUR
FTND C EPISIOTOMY ON 09/04/2026 AT 6 2aRM MALE BABYOF WT 2 8kG

VITALS
P-88 /m, BP-121/83 mmHg, RR-16 /m, Temp-AFEBRILE

TREATMENT ON DISCHARGE:
TAB. LYSER D - 14 DAYS AFTER MEALS
TAB. MACPOD 0 - AFTER MEALS
TAB. METRO ER - AFTER MEALS
DETTOL - 10 - (instruction missing)

Follow Up- Date-16-04-2026 (Thursday)
```

---

## Current Parser Output (BUGGY)

### Extracted Fields
```json
[
  {
    "field_name": "patient_name",
    "field_value": "AMREEN AZHAR SHAIKH",
    "status": "✓ CORRECT"
  },
  {
    "field_name": "patient_age",
    "field_value": "Bill No. 29 Years 26 Sex- FEMALE Occupation: HOUSE IPD BiLL WIFE DOA- 09-04-2026TIME 08.55 AM",
    "status": "✗ WRONG - Captured entire line instead of just '29' or '29 Years'"
  },
  {
    "field_name": "patient_id",
    "field_value": "DOD- 10-04-2026TIME Oo.00.00 Initial",
    "status": "✗ WRONG - Should be IPD REG NO: 1-28/2026, not discharge date"
  },
  {
    "field_name": "insurance_policy_number",
    "field_value": "No_ 1-28/2026 Age. 29 Sex_ FEMALE Adm Date 9/4/2026",
    "status": "✗ WRONG - Correct policy but mixed with other fields"
  }
]
```

### Extracted Tables
```json
[]  // EMPTY - No tables extracted
```

**Why Hospital Expenses Table is Empty**:
- Document type = "discharge_summary" (correct classification)
- Discharge summaries don't have expense tables
- Only found form regions, no table regions detected
- NOTE: Medication table IS present but not extracted (missing functionality)

---

## Expected Parser Output (What Should Happen)

### Extracted Fields - SHOULD BE
```json
[
  {
    "field_name": "patient_name",
    "field_value": "AMREEN AZHAR SHAIKH",
    "source_page": 1,
    "model_version": "discharge-form-v1"
  },
  {
    "field_name": "patient_age",
    "field_value": "29",
    "source_page": 1,
    "model_version": "discharge-form-v1"
  },
  {
    "field_name": "patient_gender",
    "field_value": "FEMALE",
    "source_page": 1,
    "model_version": "discharge-form-v1"
  },
  {
    "field_name": "patient_id",
    "field_value": "1-28/2026",
    "source_page": 1,
    "model_version": "discharge-form-v1"
  },
  {
    "field_name": "admission_date",
    "field_value": "09-04-2026",
    "source_page": 1,
    "model_version": "discharge-form-v1"
  },
  {
    "field_name": "discharge_date",
    "field_value": "10-04-2026",
    "source_page": 1,
    "model_version": "discharge-form-v1"
  },
  {
    "field_name": "diagnosis",
    "field_value": "G3PILIAI 39WKS 2DAYS PREGNANCY IN LABOUR FTND C EPISIOTOMY",
    "source_page": 1,
    "model_version": "discharge-form-v1"
  },
  {
    "field_name": "address",
    "field_value": "BHAIGAON ROAD SHARDA NAGAR",
    "source_page": 1,
    "model_version": "discharge-form-v1"
  },
  {
    "field_name": "occupation",
    "field_value": "HOUSE WIFE",
    "source_page": 1,
    "model_version": "discharge-form-v1"
  }
]
```

### Extracted Medications - SHOULD BE
```json
[
  {
    "medicine_name": "LYSER D",
    "dosage": "TAB",
    "frequency": "AFTER MEALS",
    "days": "14",
    "source_page": 1,
    "table_type": "medication"
  },
  {
    "medicine_name": "MACPOD 0",
    "dosage": "TAB",
    "frequency": "AFTER MEALS",
    "days": "",
    "source_page": 1,
    "table_type": "medication"
  },
  {
    "medicine_name": "METRO ER",
    "dosage": "TAB",
    "frequency": "AFTER MEALS",
    "days": "",
    "source_page": 1,
    "table_type": "medication"
  },
  {
    "medicine_name": "DETTOL",
    "dosage": "SOLUTION",
    "frequency": "",
    "days": "10",
    "source_page": 1,
    "table_type": "medication"
  }
]
```

### Why Expenses Table is Intentionally Empty
✓ **This is CORRECT behavior**
- Document is a discharge summary (clinical document)
- Discharge summaries never have hospital expense tables
- Expense data comes from separate hospital bill documents
- If you upload a bill document, it WILL have expense table extraction

---

## Report Preview Rendering

### Current (Buggy)
```
PATIENT INFORMATION
  Name: AMREEN AZHAR SHAIKH
  Age: N/A
  Gender: N/A
  ID: N/A
  Address: N/A

HOSPITALIZATION DETAILS
  Admission Date: N/A
  Discharge Date: N/A
  Hospital: N/A
  Diagnosis: N/A

HOSPITAL EXPENSES
  (No charges table found)

MEDICATIONS
  (No medications extracted)
```

### Expected (Fixed)
```
PATIENT INFORMATION
  Name: AMREEN AZHAR SHAIKH
  Age: 29 Years
  Gender: FEMALE
  ID: 1-28/2026
  Address: BHAIGAON ROAD SHARDA NAGAR
  Occupation: HOUSE WIFE

HOSPITALIZATION DETAILS
  Admission Date: 09-04-2026
  Discharge Date: 10-04-2026
  Hospital: Aniket Netaralay And Maternity Home, Nanded
  Diagnosis: G3PILIAI 39WKS 2DAYS PREGNANCY IN LABOUR FTND C EPISIOTOMY

MEDICATIONS
  1. LYSER D (TAB) - 14 DAYS - AFTER MEALS
  2. MACPOD 0 (TAB) - AFTER MEALS
  3. METRO ER (TAB) - AFTER MEALS
  4. DETTOL (10) - Apply as needed

FOLLOW-UP
  Date: 16-04-2026 (Thursday)
  Location: Aniket Netaralay And Maternity Home, Nanded
```

---

## Key Differences: Image vs PDF

### When you upload IMAGE (JPG/PNG) of discharge summary
1. **EasyOCR** extracts text + coordinates
2. Multi-label lines confuse the parser
3. Fields are greedy/incomplete
4. Some fields marked as "N/A"
5. Result: PARTIAL DATA (current issue)

### When you upload PDF with extractable text
1. **pdfplumber** reads embedded text
2. Text is pre-structured (better delimiters)
3. Form extractor works better
4. All fields found correctly
5. Result: COMPLETE DATA ✓

### Example of the difference
```
IMAGE OCR Output:
Token 1: {text: "Bill", x0: 108, y0: 242, ...}
Token 2: {text: "No.", x0: 142, y0: 242, ...}
Token 3: {text: "29", x0: 180, y0: 242, ...}
Token 4: {text: "Years", x0: 210, y0: 242, ...}
Token 5: {text: "26", x0: 260, y0: 242, ...}
Token 6: {text: "Sex-", x0: 300, y0: 242, ...}
Token 7: {text: "FEMALE", x0: 350, y0: 242, ...}
Token 8: {text: "Occupation:", x0: 420, y0: 242, ...}
... all on SAME Y-coordinate (242)

PDF pdfplumber Output:
Text with newlines:
"Age: 29\nSex: FEMALE\nOccupation: HOUSE"
... properly delimited
```

The parser sees all tokens on Y=242 as ONE ROW, so when it finds "Age", it collects everything to the right until row end = entire line!

---

## Summary of Issues

| Field | Current | Expected | Problem |
|-------|---------|----------|---------|
| patient_name | ✓ AMREEN AZHAR SHAIKH | ✓ AMREEN AZHAR SHAIKH | None |
| patient_age | ✗ Entire line | ✓ 29 | Greedy extraction |
| patient_gender | ✗ Not extracted | ✓ FEMALE | Missing anchor |
| patient_id | ✗ Discharge date | ✓ 1-28/2026 | Misidentified |
| admission_date | ✗ Not extracted | ✓ 09-04-2026 | Missing anchor |
| discharge_date | ✗ Not extracted | ✓ 10-04-2026 | Missing anchor |
| diagnosis | ✗ Not extracted | ✓ G3PILIAI 39WKS... | Missing anchor |
| address | ✗ Not extracted | ✓ BHAIGAON ROAD... | Missing anchor |
| medications | ✗ Not extracted | ✓ Table of 4 medicines | Not implemented |
| hospital_expenses | ✗ N/A (correct) | ✓ N/A (discharge summary has no expenses) | Correct - no expenses in discharge |

---

## What Needs to Be Fixed

**Priority 1 (HIGH)**: Multi-label line parsing
- Stop anchor value collection when hitting next label
- Split lines like "Age: 29 Sex- FEMALE" into separate fields

**Priority 2 (HIGH)**: Add discharge summary anchors
- diagnosis, discharge_date, address, occupation
- These are missing from current ANCHORS dict

**Priority 3 (MEDIUM)**: Medication table extraction
- Detect medication tables in discharge context
- Extract drug name, dosage, frequency, days
- Display in report as separate section

**Priority 4 (LOW)**: Hospital name extraction
- Fallback to header text: "Aniket Netaralay And Maternity Home, Nanded"
- Could improve with better regex or NER model
