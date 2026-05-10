# Parser Engine Audit Report
**Date:** 2026-05-08  
**Focus:** Semantic threshold logic, anchor reliability, and category mapping

---

## Q1: The Threshold Logic Audit

### Semantic Scoring Gate Location
- **File:** [services/parser/app/engine.py](services/parser/app/engine.py#L3090-L3110)
- **Function:** `add_expense_item()` (nested in `_extract_expense_table()`)

### Complete Scoring Pipeline

#### Step 1: Base Semantic Score Calculation
```python
sem = _semantic_score(raw_label)
```

**`_semantic_score()` implementation ([L2973-2985](services/parser/app/engine.py#L2973-L2985)):**

If embedding model is None (fallback mode):
```python
return 1.0 if re.search(
    r"(?:room|consult|medicine|lab|radiology|procedure|surgery|drug|pharmacy|diagnostic|nursing|icu|ot|operation|charge|fee|consumable|implant|investigation)", 
    text, re.I
) else 0.0
```

If embedding model loaded:
```python
# Cosine similarity: dot_product / (norm_vec × norm_concept_vec)
vec = _embed_model.encode([text], convert_to_numpy=True)[0]
denom = (np.linalg.norm(vec) * np.linalg.norm(_expense_concept_vec))
return float(np.dot(vec, _expense_concept_vec) / denom)  # Range: [0.0, 1.0]
```

**Concept vector:** `"medical expense charges billing item"` (all-MiniLM-L6-v2)

---

#### Step 2: First Hardcoded Boost (Charges/Fees Rule)
```python
if re.search(r"\b(?:charges?|fees?)\b", raw_label, re.I):
    sem = max(sem, 0.9)  # BOOST: Set minimum to 0.9
```

**Triggers on:** `charge`, `charges`, `fee`, `fees` (case-insensitive)  
**Boost magnitude:** `max(current_score, 0.9)`  
**Issue:** NO STRING LENGTH CHECK — "charges" alone (3+ chars) will boost

---

#### Step 3: Low-Score Fallback Gate
```python
if sem < 0.4:  # Gatekeeper: Reject low-confidence labels
    # Apply second boost
    if re.search(r"(?:room|board|consult|...)", raw_label, re.I):
        sem = 0.9  # BOOST: Set to 0.9
    else:
        return  # REJECT: Label fails to meet criteria
```

**Second boost triggers on (60+ keywords):**
- Medical facility roles: `consult`, `doctor`, `physician`
- Pharmacy/medication: `pharmacy`, `medicine`, `drug`, `injection`, `g-csf`, `filgrastim`
- Procedure/surgery: `surge`, `procedure`, `operation`, `ot`, `angio`, `cath`, `endoscopy`
- ICU/monitoring: `icu`, `hdu`, `nicu`, `nursing`, `monitoring`, `cardiac`, `eeg`, `ecg`
- Diagnostics: `investigation`, `diagnostic`, `lab`, `pathology`, `radiology`, `imaging`
- Room/board: `room`, `board`
- Other: `consumable`, `disposable`, `ambulance`, `misc`, `sundry`, `other`, `oxygen`, `diet`, `food`, `ppe`, `blood`, `implant`, `isolation`, `transplant`, `chemo`, `stem`, `dialysis`, `anaesth`, `anesthe`, `physio`, `rehabilitation`, `rehab`, `haematol`, `hematol`, `platelet`, `apheresis`, `conditioning`, `registration`, `admin`, `attendant`, `dietary`, `nutrition`

**Issue:** NO STRING LENGTH CHECK — "lab" (3 chars) in `"Patient Information: lab..."` would pass if it had a number

---

#### Step 4: Final Confidence Calculation
```python
conf = max(0.0, min(1.0, sem))  # Clamp between [0.0, 1.0]
```

### Mathematical Formula Summary
```
Final Score = 
  IF "charges" or "fees" in label:
    max(base_semantic_score, 0.9)
  ELSE IF base_semantic_score >= 0.4:
    base_semantic_score
  ELSE IF 60+ medical keywords in label:
    0.9
  ELSE:
    REJECT (return early)

RESULT = clamp(final_score, 0.0, 1.0)
```

### Critical Gaps
1. ✗ **No minimum label length enforced** — `"days"` (3 chars) + no keywords = passes if sem >= 0.4
2. ✗ **No check for "declaration/metadata" keywords** — `"Patient Information:"` contains "information" but semantic score may be 0.3
3. ✗ **Boost applies to ANY label with "charges"** — Even `"Days charges: 2"` gets boosted to 0.9
4. ✗ **Keyword match is substring-based** — `"radiation"` would match `"radiology"` in fallback keyword list (Pass 2e)

---

## Q2: The "Anchor" Reliability Audit

### Total/Grand Total Detection

#### Footer Anchor Search (_page_body_anchor_range)
**Location:** [L2914-2936](services/parser/app/engine.py#L2914-L2936)

**Logic:**
```python
if any(k in txt for k in (
    "declaration",      # 1
    "declarations",     # 2
    "signature",        # 3
    "grand total",      # 4
    "itemised total",   # 5
    "billed total",     # 6
    "total amount"      # 7
)):
    footer_y = y_center
```

**Regex patterns used:** **1 substring match pattern** with 7 keywords  
**Pattern:** Simple `in` operator (case-insensitive via `.lower()`)

---

#### Billed Total Extraction (Math Reconciliation)
**Location:** [L3368-L3373](services/parser/app/engine.py#L3368-L3373)

```python
for m in re.finditer(
    r"(?:billed total|itemised total|total amount|grand total|total)\s*[:\-]?\s*(?:Rs\.?\s*)?(\d[\d,]*\.?\d*)",
    section_text, re.I
):
```

**Regex variations:** 5 patterns
- `billed total`
- `itemised total`
- `total amount`
- `grand total`
- `total` (bare)

**Case-insensitive:** Yes (re.I flag)  
**Currency aware:** Yes (matches optional `Rs.`)

---

### Anchor Range Enforcement

#### Question: Is there a strict `if y > footer_y: skip` check?

**YES. Location:** [L3080-L3082](services/parser/app/engine.py#L3080-L3082)

```python
if header_y is not None and footer_y is not None and y_center is not None:
    if not (header_y - 5 <= y_center <= footer_y + 5):
        return  # SKIP: Outside valid range
```

**Enforcement:**
- Items MUST have y-coordinate between `header_y - 5` and `footer_y + 5`
- Tolerance: ±5 points (in normalized 0-1000 scale)
- If header_y OR footer_y is None: **CHECK IS SKIPPED** (no enforcement)

**Issue:** If footer_y is not detected (e.g., no "total" line found), ALL y-coordinates are accepted

---

### Anchor Detection Issues (Root Cause of Claim 55f4df5e)

**Scenario:** Hospital bill with "Medication Charges" at bottom but no "Total" line

1. `footer_y` = None (no "total" keyword found)
2. `header_y` = y-position of "Amount" column
3. `y_center` = position of "Medication Charges" line
4. **Anchor check skipped** (footer_y is None)
5. Item is added with incorrect label (due to Pass 2e fallback)

**Root cause:** Parser relies on "total" keyword; if missing, anchor enforcement disabled

---

## Q3: The Category Mapping Audit

### Standardized Categories

**Total categories in system:** 21

```
1. room_charges
2. surgery_charges  ◄─ "Anesthesia/Surgery Cluster" (YES, exists but not unified)
3. anaesthesia_charges
4. pharmacy_charges
5. icu_charges
6. consultation_charges
7. laboratory_charges
8. radiology_charges
9. ot_charges (Operation Theatre)
10. nursing_charges
11. consumables
12. blood_charges
13. transplant_charges
14. ambulance_charges
15. misc_charges
16. other_charges
17. investigation_charges
18. physiotherapy_charges
19. isolation_charges
20. chemotherapy_charges
21. surgeon_fees
```

---

### Medical Sentiment Clustering

#### Question: Is there a "Medical Sentiment" cluster for "Anesthesia" or "Surgery"?

**NO. Current structure is atomized:**

**Category: `anaesthesia_charges`**
- Keywords: `anaesthesia`, `anesthesia`, `anaesthetist`
- Map size: 3 terms
- Confidence level: Exact match

**Category: `surgery_charges`**
- Keywords: `surgery`, `surgical`, `procedure`
- Map size: 3 terms  
- Confidence level: Exact match

**Missing unified cluster:** Would need category like `surgical_intervention_charges` that captures:
- Surgery, surgical, procedure, operation, anesthesia, ot, cath lab, angio, endoscopy, etc.

---

### High Semantic Score Without Hardcoded Keyword

#### Question: How does the system handle labels with high semantic score but no hardcoded keyword?

**Answer:** Through a **three-pass approach** in `_categorise_expense()` [L2580-2618]:

```
Pass 1: Exact label match in _EXPENSE_LABEL_EXACT
        → If found, return mapped category (e.g., "room charges" → "room_charges")
        → Otherwise, continue

Pass 2: Prefix keyword match in _EXPENSE_CATEGORY_MAP
        → If label STARTS with keyword, return category immediately
        → Otherwise, continue

Pass 3: Longest keyword-first search
        → Find longest matching keyword in _EXPENSE_CATEGORY_MAP
        → Return mapped category
        → If NO keywords match → return "other_charges" (fallback)
```

**Example scenarios:**

| Label | Semantic Score | Keywords Match? | Result |
|-------|---------------|----|--------|
| "Anesthesia Charges" | 0.50 | Yes ("anesthesia") | `anaesthesia_charges` |
| "Specialist Consultation" | 0.65 | Yes ("consultation") | `consultation_charges` |
| "Device XYZ-123" | 0.25 | No keywords | `other_charges` (fallback) |
| "Physical Therapy Fees" | 0.71 | Yes ("physio") | `physiotherapy_charges` |

**Fallback behavior:** High semantic scores WITHOUT hardcoded keywords default to `other_charges`

**Issue:** System cannot learn new expense types via semantic embeddings alone; requires hardcoded keyword mapping

---

## Summary of Critical Issues

| Issue | Location | Severity | Impact |
|-------|----------|----------|--------|
| No string length check before boost | `add_expense_item` L3094 | HIGH | "days", "lab" can bypass semantic gate |
| Substring keyword matching in Pass 2e | `add_expense_item` L3298 | HIGH | "Patient Information" matches "information" |
| Anchor enforcement optional | `_page_body_anchor_range` L2914 | MEDIUM | If no "total" found, y-range not enforced |
| Only 7 footer anchor keywords | `_page_body_anchor_range` L2927 | MEDIUM | Misses variations like "total billed", "subtotal" |
| No unified medical sentiment cluster | `_categorise_expense` L2580 | MEDIUM | Cannot group related expenses by domain |
| Exact label match required for confidence | `_EXPENSE_LABEL_EXACT` L2321 | LOW | New expense types require manual mapping |

---

## Recommendations

1. **Add minimum label length check:** Require ≥ 4 chars OR 2+ words before boost
2. **Expand footer anchor keywords:** Add `subtotal`, `total billed`, `total charged`, `sum of charges`
3. **Require "total" line for anchor enforcement:** If not found, reject items outside header+20% range
4. **Create medical sentiment cluster:** Group "anesthesia", "surgery", "procedure" under `surgical_intervention` category
5. **Add confidence penalty for fallback keywords:** If only fallback keywords match, reduce confidence to 0.7 instead of 0.9
