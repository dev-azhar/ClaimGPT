# Parser Architecture: Hardcoded vs. Dynamic Extraction

## Summary

The parser uses a **hybrid approach** with three escalating fallback layers:

1. **Structured LLM extraction** (dynamic, but schema-bound)
2. **LayoutLMv3 model extraction** (semi-dynamic via token classification)
3. **Heuristic regex-based extraction** (hardcoded patterns, but extensive)

---

## Layer 1: Structured LLM Extraction (Dynamic)

**When Used:** If `settings.structured_extraction_enabled=true` and LLM endpoint is available.

**Approach:** 
- Sends OCR text to an LLM (Ollama, Claude, or custom) with a **fixed schema** (`StructuredClaimExtraction`)
- LLM extracts structured JSON matching the schema fields
- Schema fields are **hardcoded** (not fully dynamic), but LLM can find any values within documents

**Schema fields (hardcoded):**
```python
class StructuredClaimExtraction(BaseModel):
    patient_name: Optional[str]
    member_id: Optional[str]
    policy_number: Optional[str]
    age: Optional[int]
    hospital_name: Optional[str]
    admission_date: Optional[str]
    discharge_date: Optional[str]
    primary_diagnosis: Optional[str]
    secondary_diagnosis: Optional[str]
    procedures: list[str]
    treating_doctor: Optional[str]
    claimed_total: Optional[float]
    bill_line_items: list[BillingLineItem]  # Dynamic: LLM extracts ALL line items
    notes: Optional[str]
    confidence: str
```

**Advantage:** LLM can extract **any** line items and expenses mentioned in the document dynamically.

**Fallback Chain:**
1. Try with full OCR text
2. If timeout, retry with truncated text (max 8000 chars)
3. If still fails and multi-document, try per-document extraction and merge

---

## Layer 2: LayoutLMv3 Token Classification (Semi-Dynamic)

**When Used:** If LLM fails AND `_load_model()` succeeds AND images are provided.

**Approach:**
- LayoutLMv3 model classifies each token/word as a field type (e.g., "patient_name", "total_amount")
- Returns token-level predictions (BIO tagging)
- More flexible than regex but limited to model's trained label set

**Limitation:** Token classification labels are **model-trained** and fixed; can't extract completely new field types.

---

## Layer 3: Heuristic Regex-Based Extraction (Hardcoded)

**When Used:** All else fails. Default if no LLM and no image.

**Approach:** Uses **40+ hand-crafted regex patterns** for specific fields.

### Hardcoded Field List (from `_PATTERNS`):

```python
_PATTERNS = [
    # Demographics (8 fields)
    ("patient_name", _PAT_PATIENT_NAME),
    ("date_of_birth", _PAT_DOB),
    ("age", _PAT_AGE),
    ("gender", _PAT_GENDER),
    ("address", _PAT_ADDRESS),
    ("phone", _PAT_PHONE),
    ("email", _PAT_EMAIL),
    ("patient_id", _PAT_PATIENT_ID),
    
    # Insurance (5 fields)
    ("policy_number", _PAT_POLICY),
    ("claim_number", _PAT_CLAIM_NO),
    ("member_id", _PAT_MEMBER_ID),
    ("group_number", _PAT_GROUP),
    ("insurer", _PAT_INSURER),
    
    # Clinical (8 fields)
    ("diagnosis", _PAT_DIAGNOSIS),
    ("icd_code", _PAT_ICD_CODE),
    ("procedure", _PAT_PROCEDURE),
    ("cpt_code", _PAT_CPT_CODE),
    ("medication", _PAT_MEDICATION),
    ("allergy", _PAT_ALLERGY),
    ("chief_complaint", _PAT_CHIEF_COMPLAINT),
    ("history_of_present_illness", _PAT_HISTORY),
    
    # Financial/Expenses (16 fields - **all hardcoded**)
    ("total_amount", _PAT_TOTAL_AMOUNT),
    ("surgeon_fees", _PAT_SURGEON_FEE),
    ("anaesthesia_charges", _PAT_ANAESTHESIA),
    ("ot_charges", _PAT_OT_CHARGE),
    ("surgery_charges", _PAT_SURGERY_CHARGE),
    ("consumables", _PAT_CONSUMABLES),
    ("room_charges", _PAT_ROOM_CHARGE),
    ("consultation_charges", _PAT_CONSULTATION),
    ("pharmacy_charges", _PAT_PHARMACY),
    ("laboratory_charges", _PAT_LABORATORY),
    ("radiology_charges", _PAT_RADIOLOGY),
    ("investigation_charges", _PAT_INVESTIGATION),
    ("nursing_charges", _PAT_NURSING),
    ("icu_charges", _PAT_ICU_CHARGE),
    ("ambulance_charges", _PAT_AMBULANCE),
    ("misc_charges", _PAT_MISC_CHARGE),
    
    # Provider (3 fields)
    ("hospital_name", _PAT_HOSPITAL),
    ("doctor_name", _PAT_DOCTOR),
    ("registration_number", _PAT_REG_NO),
    
    # Dates (3 fields)
    ("admission_date", _PAT_ADMISSION_DATE),
    ("discharge_date", _PAT_DISCHARGE_DATE),
    ("service_date", _PAT_SERVICE_DATE),
    
    # Vitals (4 fields)
    ("blood_pressure", _PAT_BLOOD_PRESSURE),
    ("pulse", _PAT_PULSE),
    ("temperature", _PAT_TEMPERATURE),
    ("spo2", _PAT_SPO2),
]
```

**Total: 50+ hardcoded fields.**

### Example Patterns (Regex):

```python
# Total amount - looks for keywords like "total amount", "grand total", "claimed amount"
_PAT_TOTAL_AMOUNT = re.compile(
    r"(?:(?:total|gross\s*total)\s*(?:amount|charge|cost|billed|bill|payable|hospital\s*expenses|claimed\s*amount)|"
    r"(?:total\s*)?gross\s*(?:total\s*)?amount|grand\s*total|net\s*(?:amount|payable)|claim\s*amount\s*requested)\s*"
    r"[:\-]?\s*(?:(?:rs|inr|usd|\$|₹)\.?\s*)?([\d,]+\.?\d*)",
    re.I,
)

# Room charges
_PAT_ROOM_CHARGE = re.compile(
    r"(?:room\s*(?:charges?|rent|rate)|bed\s*charges?|room\s*&?\s*board)\s*(?:\([^)]*\))?\s*[:\-]?\s*"
    r"(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", 
    re.I
)

# Surgery charges
_PAT_SURGERY_CHARGE = re.compile(
    r"(?:surgery\s*(?:charges?|cost|fees?)|surgical?\s*(?:charges?|fees?))\s*[:\-]?\s*"
    r"(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", 
    re.I
)
```

---

## How Expenses Are Extracted

### Method 1: Expense Table Parsing (Dynamic)

If a page is detected as a **HOSPITAL_BILL** or contains expense table headers, the parser calls `_extract_expense_table()`:

```python
if is_bill or header_match:
    expense_fields, line_items = _extract_expense_table(
        text, page_num, page.detected_tables, known_cpt_codes
    )
```

**This is DYNAMIC:** It parses detected tables and extracts ALL line items (description, category, quantity, unit price, amount) without predefined field names.

**Result:** Returns a list of `BillingLineItem` objects:
```python
class BillingLineItem(BaseModel):
    description: str          # e.g., "Room charges 2 days @ 500/day"
    category: Optional[str]   # e.g., "room", "consultation", "investigation"
    quantity: Optional[float]
    unit_price: Optional[float]
    amount: Optional[float]
```

### Method 2: Individual Expense Regexes (Hardcoded)

For each hardcoded pattern (room charges, consultation charges, etc.), the parser searches for a SINGLE value per page:

```python
# Only captures ONE value per pattern per page
for match in _PAT_ROOM_CHARGE.finditer(text):
    value = match.group(1).strip()  # e.g., "25000"
    fields.append(FieldResult(field_name="room_charges", field_value=value))
```

**Limitation:** Only finds one value per category. If a bill has multiple room charge entries, only the first is captured by regex.

---

## Comparison: Hardcoded vs. Dynamic

| Aspect | Layer 1 (LLM) | Layer 2 (LayoutLM) | Layer 3 (Regex) |
|---|---|---|---|
| **Field Names** | Hardcoded schema (18 fields) | Model-trained labels | Hardcoded 50+ fields |
| **Expense Line Items** | **DYNAMIC**: Extracts all line items mentioned | Limited | Single value per category |
| **Things/Medications** | **DYNAMIC**: LLM reads doc, lists all | Token classification | Regex captures multi-line text |
| **New Fields** | Requires schema update | Requires model retraining | Requires new regex patterns |
| **Speed** | Slow (LLM call: 5-30 sec) | Medium (inference: 1-5 sec) | Fast (regex: <100ms) |
| **Accuracy** | High (LLM understands context) | Medium | Low (pattern matching) |

---

## Production Setup (Recommendation)

### For Maximum Coverage:

1. **Use LLM-based extraction as primary** (Layer 1)
   - Set `settings.structured_extraction_enabled=true`
   - Point to Ollama/Claude/Grok endpoint
   - **Benefit:** Captures **all expenses and items** mentioned, not just predefined categories

2. **Fallback to regex** (Layer 3)
   - Only if LLM unavailable or times out
   - **Limitation:** Will miss many expenses not matching hardcoded patterns

### Adding New Expense Types:

**If you need to capture a new expense category NOT in the hardcoded list:**

**Option A (Best):** Use LLM extraction — no code change needed. LLM will extract it dynamically.

**Option B:** Add a new regex pattern to `_PATTERNS`:
```python
_PAT_DIALYSIS = re.compile(
    r"(?:dialysis\s*(?:charges?|cost|fees?))\s*[:\-]?\s*"
    r"(?:(?:rs|inr|\$|₹)\.?\s*)?([\d,]+\.?\d*)", 
    re.I
)
_PATTERNS.append(("dialysis_charges", _PAT_DIALYSIS))
```

Then update the expense field allowlist:
```python
_DOC_TYPE_FIELD_ALLOWLIST[DocumentType.HOSPITAL_BILL.value].add("dialysis_charges")
```

---

## Bottleneck Check: Things and Expenses Mentioned

**Critical Issue:** If using **regex-only** (Layer 3), the parser will miss any expense category NOT in the hardcoded list.

**Example:** Bill contains "Telemedicine consultation: ₹5000" but there's no regex for telemedicine → **MISSED**

**Solution:** **Always use Layer 1 (LLM extraction)** in production. LLM will dynamically extract ANY expense mentioned.

---

## Test It

Check which layer is active by looking at the extracted fields' `model_version`:

```python
for field in parsed_output.fields:
    print(f"{field.field_name}: {field.field_value} (source: {field.model_version})")
    # Output will be:
    # "patient_name: John Doe (source: ollama-structured-v1)" → Layer 1 (LLM)
    # "patient_name: John Doe (source: layoutlmv3-base)" → Layer 2 (Model)
    # "patient_name: John Doe (source: None)" → Layer 3 (Regex)
```

Also check the `used_fallback` flag:
```python
print(f"Used fallback (heuristic): {parsed_output.used_fallback}")
```
