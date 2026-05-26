# OpenRouter Parse Analysis & Issue Diagnosis

**Date**: 2026-05-13  
**Claim ID**: `08c8c462-25ee-4b71-ae59-863d5876157c`  
**Job ID**: `4361bf84-640d-4d05-9358-44cd0670a7dc`

---

## ✅ What's Working

### 1. OpenRouter Backend Integration
```
HTTP Requests: 26 POST to https://openrouter.ai/api/v1/chat/completions
All responses: HTTP 200 OK
Parse time: 105.82s
Model: openai/gpt-4o-mini
```

### 2. Semantic Extraction (26 Regions Analyzed)
- **DIAGNOSIS** (4 regions): ✓ Extracted
- **EXPENSE_TABLE** (3 regions): ✓ Extracted  
- **HOSPITALIZATION_INFO** (4 regions): ✓ Extracted
- **INSURANCE_INFO** (2 regions): ✓ Extracted
- **PATIENT_INFO** (3 regions): ✓ Extracted
- **OTHER** (10 regions): Extracted

### 3. Field Extraction (19 Fields)
```
✓ patient_name              = Suresh Reddy
✓ hospital_name             = Yashoda Hospitals
✓ treating_doctor           = Dr. Ramesh Kumar (DM Cardiology)
✓ primary_diagnosis         = Acute Myocardial Infarction (Heart Attack)
✓ admission_date            = 01-03-2026
✓ discharge_date            = 12-03-2026
✓ total_days                = 11 Days
✓ icu_days                  = 5 days
✓ ward_type                 = ICU + Private
✓ registration_number       = YASH-HYD-1998-0018, MCI-78901
(+ 10 more diagnosis and secondary fields)
```

### 4. Expense Extraction (Correct Amounts)
```
From semantic extraction (CORRECT):
[1] ICU Charges         → amount: 75000 (5 days × 15,000)
[2] Room Charges       → amount: 6,000
[3] Surgery Charges    → amount: 120,000
... (12 total items)
```

---

## ❌ What's Broken

### 1. **Report Shows Nothing for Extracted Fields**
Final report missing:
- ❌ Treating doctor
- ❌ Primary diagnosis
- ❌ Age / Gender
- ❌ Secondary diagnoses

### 2. **Renderer Input Has Empty Fields**
File: `renderer_input.json`
```
Keys: ['claim_id', 'model_version', 'used_fallback', 'fields', 'tables', 'sections', 'layout', 'ocr_pages', 'canonical_claim']

✗ treating_doctor: MISSING
✗ diagnosis: MISSING  
✗ fields section: EMPTY
✗ expenses: NOT AT TOP LEVEL
```

### 3. **Data Flow Broken**
```
Semantic Extraction ✓
      ↓
Normalized Fields ✓
      ↓
Canonical Claim ✓
      ↓
??? LOST HERE ???
      ↓
Renderer Input ✗ (empty)
      ↓
Final Report ✗ (blank)
```

---

## 🔍 Root Cause

**File**: `services/parser/app/main.py`  
**Function**: `_build_renderer_input()` (lines 340-360)

The function only includes:
- `output.fields` (ParseOutput from parser)
- `output.tables` (ParseOutput from parser)

But `ParseOutput.fields` is NOT populated with semantic-extracted data!

### Data Is Locked In:
- ✓ `normalized_fields.json` (debug artifact) - HAS the data
- ✓ `canonical_claim.json` (debug artifact) - HAS the data
- ✗ `ParseOutput.fields` - EMPTY
- ✗ `renderer_input.json` - EMPTY (because it reads from ParseOutput)

---

## 📋 Fix Strategy

### Option A: Make ParseOutput.fields Include Semantic Data
- **Where**: `services/parser_v2/pipeline.py` after `parse_document()` 
- **Action**: Merge normalized_fields into ParseOutput.fields before returning
- **Pros**: Clean, structured
- **Cons**: Requires changes to parse_v2 output

### Option B: Make Renderer Read from Canonical Claim
- **Where**: `services/submission/app/main.py` in `_gather_claim_data_full()`
- **Action**: Instead of reading empty `output.fields`, extract from `canonical_claim.fields` 
- **Pros**: No parser changes needed
- **Cons**: Renderer needs to understand canonical_claim schema

### Option C: Fix Both
- **parse_v2**: Output semantic fields in ParseOutput.fields
- **renderer**: As fallback, read from canonical_claim if output.fields empty

---

## 📊 Debug Artifacts Available

All files in `tmp/parser_debug/08c8c462-25ee-4b71-ae59-863d5876157c_4361bf84-640d-4d05-9358-44cd0670a7dc_*`:

| File | Content | Status |
|------|---------|--------|
| `...json` | Full parse job output | ✓ Complete |
| `canonical_claim.json` | Canonical schema with all fields | ✓ Data present |
| `renderer_input.json` | What goes to report generator | ✗ Empty fields |
| `semantic_region_outputs.json` | OpenRouter extraction | ✓ 26 regions analyzed |
| `normalized_fields.json` | 19 extracted fields | ✓ All there |
| `normalized_expenses.json` | 12 expense items | ✓ Correct amounts |

---

## 📝 Next Steps

**Immediate** (get report working):
1. Fix ParseOutput.fields population in parse_v2
2. Verify renderer_input includes doctor, diagnosis, age/gender
3. Test end-to-end report generation

**Follow-up** (validate):
1. Run another claim parse
2. Verify all fields appear in final report
3. Check expense amounts are correct (not truncated)

**Long-term**:
1. Add semantic extraction metrics to logs
2. Track field confidence scores
3. Implement fallback prioritization (semantic > heuristic)

---

## Command to Reproduce

```bash
# Check current debug artifacts
ls -la tmp/parser_debug/08c8c462-25ee-4b71-ae59-863d5876157c_4361bf84-640d-4d05-9358-44cd0670a7dc_*

# View extracted fields
python -c "import json; data=json.load(open('tmp/parser_debug/normalized_fields.json')); print('Fields:', len(data)); [print(f[\"canonical_field\"]) for f in data[:5]]"

# Compare with renderer input
python -c "import json; data=json.load(open('tmp/parser_debug/08c8c462-25ee-4b71-ae59-863d5876157c_4361bf84-640d-4d05-9358-44cd0670a7dc_renderer_input.json')); print('Renderer fields:', len(data.get('fields', []))); print('Has treating_doctor:', 'treating_doctor' in str(data))"
```
