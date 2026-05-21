# Claim 348ab724 - Parser Expense Extraction Analysis

## Executive Summary

**Status:** Root cause identified - Semantic LLM is extracting expense data with **DATA CORRUPTION**

**Problem:** Expenses shown in report don't match the actual invoice
- Parser extracted: 26 fragmented items (Rs. 105,642)
- Expected: 25 complete items with dates (Rs. 99,142)
- **Missing:** Date information, proper service descriptions, non-payable flags

---

## Problem Details

### What User Provided (Actual Invoice Data)
```
25 line items with dates (DD-MM-YYYY format):
11-04-2025 Private Charges 5,839
11-04-2025 Nursing Charges 636 NP: Rs.63
11-04-2025 Duty Doctor Fees 1,283
...
12-04-2025 LSCS Delivery Package 43,598 NP: Rs.1,743
12-04-2025 Operation Theatre Charges 9,637
12-04-2025 Spinal Anaesthesia Charges 5,236
13-04-2025 Neonatal Observation Charges 2,902
...
12-04-2025 Surgical Consumables & Disposables 3,049 NP: Rs.2,286
TOTAL: Rs. 99,142
```

### What Parser Extracted (Debug Output)
```
26 fragmented items WITHOUT dates:
- Coagulation (Rs. 48,637) <- corrupted from "Coagulation Profile"
- Private Nursing Duty (Rs. 12,743) <- split across rows
- Blood (Rs. 10,426) <- truncated
- LSCS Operation (Rs. 736) <- corrupted
- Theatre Fees (Rs. 912) <- fragmented  
- Spinal (Rs. 750) <- truncated
- Anaesthesia Fees (Rs. 204) <- split
- ACID 5MG [IV] (Rs. 205) <- corrupted from "TAB FOLIC ACID 5MG"
...
TOTAL: Rs. 105,642 (doesn't match!)
```

---

## Root Cause Analysis

### Issue 1: Missing Date Information
- **Expected:** Each expense line has date (11-04-2025, 12-04-2025, etc.)
- **Actual:** Parser removes dates entirely
- **Symptom:** No temporal grouping in report

### Issue 2: Description Data Corruption
The LLM is splitting multi-word service names across separate extraction results:

| Expected Description | Parser Output | Issue |
|---|---|---|
| TAB FOLIC ACID 5MG | ACID 5MG [IV] | "FOLIC" and "5MG [IV]" split |
| LSCS Delivery Package | LSCS Operation | Lost "Delivery Package" |
| Operation Theatre Charges | Theatre Fees | Lost "Operation" + "Charges" |
| Spinal Anaesthesia Charges | Spinal, Anaesthesia Fees | Split into 2 items |
| Private Charges | Private Nursing Duty | Merged with Nursing |
| Surgical Consumables & Disposables | Surgical | Lost 30% of text |

### Issue 3: Amount Aggregation Errors
- Expected total: Rs. 99,142
- Parser total: Rs. 105,642
- **Difference:** Rs. 6,500 (6.5% error - likely from split/duplicated items)

### Issue 4: Missing Metadata
- Non-payable annotations: "NP: Rs.63", "NP: Rs.1,743", "NP: Rs.2,286"
- Service type grouping (Private Charges, Nursing Charges, Duty Doctor Fees, etc.)
- Special packages (LSCS Delivery, Operation Theatre, Spinal Anaesthesia, Neonatal Observation)

---

## Technical Diagnosis

### Data Flow Breakdown

1. **Region Detection:** ✓ Working
   - Parser correctly identifies expense_table region
   - Extracts 210 tokens from the table

2. **Token to Text:** ✓ Working
   - Raw tokens properly converted to text
   - Text shown as numbered list (1., 2., 3., etc.)

3. **Semantic LLM Extraction:** ✗ **BROKEN**
   - LLM receives expense table text
   - Returns structured rows with description, amount, category
   - **BUG:** Descriptions are fragmented/corrupted
   - **BUG:** Dates not included in extraction
   - **BUG:** Service type suffixes discarded

4. **Schema Normalization:** ✓ Passes through as-is
   - Takes LLM output (corrupted data)
   - Normalizes to standardized format
   - No corruption fixes applied

5. **Report Rendering:** Displays corrupted data
   - IRDA renderer shows aggregated expense heads (room_charges, etc.)
   - Falls back to generic descriptions when no aggregated heads found
   - Shows the 26 corrupted items instead of 25 correct items

### Code Location

**File:** `services/parser_v2/semantic_extractor.py`
- **Function:** `_table_to_expenses()` (line 175)
- **Issue:** Takes whatever LLM returns; no validation/restoration of lost data
- **Prompt:** Likely not requesting date + full description preservation

**File:** `services/parser_v2/semantic_backends.py`
- **Where:** LLM is called to extract table structure
- **Issue:** Prompt doesn't enforce:
  - Date extraction from cells
  - Full description field names
  - Metadata (NP flags, special service types)

---

## Solution Options

### Option A: Improve LLM Prompt (Recommended)
**Target:** `semantic_backends.py` - Update the expense table extraction prompt

**Changes:**
1. Add date column detection to the expense table prompt
2. Request full service descriptions without truncation
3. Include metadata fields (non-payable flags)
4. Add validation rule: description must be ≥ 5 words for completeness
5. Request date + service + amount triplet format

**Pros:**
- Fixes root cause at source (LLM extraction)
- Prevents data corruption
- Preserves all invoice metadata
- Smallest code change

**Cons:**
- May require LLM API call tuning
- Need to test with multiple document types

### Option B: Post-Process Extracted Data
**Target:** `semantic_extractor.py` - After LLM returns data

**Changes:**
1. Detect split/corrupted descriptions (< 3 words for services)
2. Merge adjacent rows with same date/category
3. Look for date tokens in region text, map back to expenses
4. Reconstruct full service names from fragments

**Pros:**
- Doesn't require LLM change
- Works with existing data

**Cons:**
- Complex heuristics that may fail
- Doesn't add missing dates
- Only repairs, not prevention

### Option C: Fallback to OCR Table Reconstruction
**Target:** New module to reconstruct from raw tokens

**Changes:**
1. When semantic extraction seems corrupted (check amount validation)
2. Fall back to parsing raw token text as tab-separated/columnar data
3. Extract: Date | Service | Amount | Metadata
4. Reconstruct proper expenses with dates

**Pros:**
- Deterministic, rule-based
- Dates preserved

**Cons:**
- Complex layout analysis needed
- Fragile to format changes

---

## Immediate Recommendation

**Implement Option A (Improve LLM Prompt)** because:
1. Fixes the root cause (LLM not extracting correctly)
2. Prevents this across all future claims
3. Smallest/safest code change
4. Preserves all invoice metadata

### Testing Strategy
1. Reparse claim 348ab724 with improved prompt
2. Verify: 25 items extracted with dates
3. Verify: Amounts sum to Rs. 99,142
4. Verify: Service descriptions complete (LSCS Delivery Package, etc.)
5. Run on 5-10 other claims with itemized expense tables

---

## Files to Review/Modify

| File | Purpose | Change Needed |
|---|---|---|
| `services/parser_v2/semantic_backends.py` | LLM prompt for expense extraction | Update prompt to include dates, full descriptions |
| `services/parser_v2/semantic_extractor.py` | Post-processing of LLM output | Add validation/restoration logic (optional) |
| `services/parser_v2/models.py` | Data models | May need Date field in expense row model |

---

## Analysis Completed

✓ Parser debug files examined  
✓ Expected vs actual data compared  
✓ Data corruption identified and quantified  
✓ Root cause: LLM semantic extraction issue  
✓ Solution options provided  

**Status:** Ready for implementation
