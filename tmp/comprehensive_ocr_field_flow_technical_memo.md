=================================================================
TECHNICAL MEMO: ClaimGPT OCR-to-Report Field Flow & Context Window Problem
=================================================================

Date: 2026-04-09
Audience: Backend developers, AI/ML engineers, system architects
Purpose: Explain current architecture, root cause of field loss, and propose dynamic solutions

---

## PART 1: WHAT OCR IS ACTUALLY USED

### Current Stack (Priority Order)
1. **PaddleOCR-VL (Vision Language Model) 1.5 with doc-parser in markdown mode** (DEFAULT)
   - Config: OCR_enable_paddle_vl=False (currently disabled in production)
   - But when enabled: enabled_spatial_table_mapping=True, use_doc_parser=True
   - Output format: markdown stream (tables as markdown, structured text)
   - Location: services/ocr/app/engine.py line 126, 141-143

2. **Fallback: Classic PaddleOCR (text extract only)**
   - Used when VL model fails or is disabled
   - Output: raw OCR text per page, no markdown formatting
   - Location: services/ocr/app/engine.py line 169

3. **Final Fallback: Tesseract (for scanned images)**
   - Used when both PaddleOCR versions fail
   - Lowest accuracy for structured data

### Why This Matters
- **VL model (1.5)**: Designed to understand document layout, can output table markdown, recognizes form fields
- **Disabled by default**: Because it's experimental; config shows enable_paddle_vl=False by default
- **Doc-parser mode**: When ON, returns structured markdown instead of raw text
  - Location: services/ocr/app/config.py line 16, paddle_vl_doc_parser=True
  - This is the "smart OCR" that understands billing table headers, totals, etc.
- **Currently used**: Classic PaddleOCR in production, which only gives raw text

### Recommendation: Check Your Config
```bash
# In services/ocr/app/config.py or .env
OCR_enable_paddle_vl=False          # Set to True to use VL model
OCR_paddle_vl_doc_parser=True       # Already True, enables markdown output
```

---

## PART 2: WHERE ARE BILLS & FIELDS CONSIDERED

### The Field Consideration Pipeline

**Stage 0: OCR Extracts Raw Text**
- Input: PDF or image pages  
- Output: raw OCR text (and optionally markdown with VL model)
- All content is here, including Surgery, Laboratory, Consumables

**Stage 1: Parser Routes by Document Type**
- Input: OCR text
- Logic: Classifies page as DISCHARGE_SUMMARY | LAB_REPORT | PHARMACY_INVOICE | HOSPITAL_BILL | UNKNOWN
- Location: services/parser/app/engine.py line 655-680 (_classify_page_document_type)
- **Field allowlist per document type**: services/parser/app/engine.py line 272-290
  ```python
  HOSPITAL_BILL allowlist includes:
    room_charges, consultation_charges, pharmacy_charges, 
    investigation_charges, surgery_charges, surgeon_fees, 
    anaesthesia_charges, ot_charges, consumables, nursing_charges,
    icu_charges, ambulance_charges, misc_charges
  ```
- If page is HOSPITAL_BILL, the extracted fields are limited to this allowlist

**Stage 2: Parser Tries Three Methods in Order**
1. **Structured LLM** (if enabled): services/parser/app/engine.py line 608-611
   - Sends all OCR markdown + schema to local LLM (Ollama)
   - Expects JSON response with bill_line_items, amounts, etc.
   - Problem: If LLM endpoint unreachable or times out, falls back immediately

2. **LayoutLMv3 Model** (if images available): services/parser/app/engine.py line 622-630
   - Token-level field classification on document images + OCR text
   - Used for precise bounding box extraction
   - Fallback triggered: if transformers/torch not installed or model load fails

3. **Heuristic-v2** (40+ regex patterns): services/parser/app/engine.py line 635-650
   - Regex patterns for each field type
   - Location of patterns: services/parser/app/engine.py line 1160-1190
   - This is the ONLY path currently active in your debug dump (used_fallback=true)

**Stage 3: Expense Line Parser Extracts Bill Items**
- Location: services/parser/app/engine.py line 1828-2000 (_extract_expense_table)
- Three sub-methods:
  1. Geometric/column-aware table parsing (most accurate)
  2. Pipe-delimited line parsing | Item | Amount |
  3. Space-delimited line parsing with regex _EXPENSE_LINE
- Key mapping: services/parser/app/engine.py line 1778-1823 (_EXPENSE_CATEGORY_MAP)
  ```python
  Maps free-text labels to canonical categories:
    "lab" → "investigation_charges"
    "laboratory" → NOT IN MAP (problem found!)
    "consumable" → "consumables"
    "surgical consumable" → "consumables"
    "implant" → "consumables"
    "disposable" → "consumables"
  ```
- **Output**: FieldResult for each recognized category (surgery_charges, consumables, etc.)

---

## PART 3: WHAT "CANONICAL" MEANS

### Definition
"Canonical" refers to the **hard-coded, fixed list of expense categories** that the system recognizes as the "source of truth" for what should appear in the final report.

### Where Canonical Is Defined

**1. Parser Phase (40+ recognized categories)**
- Location: services/parser/app/engine.py line 1268-1274
```python
ALL_FIELD_PATTERNS = [
    # ... many patterns ...
    ("surgery_charges", _PAT_SURGERY_CHARGE),
    ("consumables", _PAT_CONSUMABLES),
    ("investigation_charges", ...),
    # etc.
]
```
- This is the FULL set the parser can extract
- Includes all 20 categories: room, consultation, pharmacy, investigation, surgery, surgeon fees, anaesthesia, OT, consumables, nursing, ICU, ambulance, misc, etc.

**2. Submission Phase (5-item canonical subset)**
- Location: services/submission/app/main.py line 362-367
```python
canonical = [
    ("room_charges", "Room Charges"),
    ("investigation_charges", "Diagnostics & Investigations"),
    ("surgery_charges", "Surgery Charges"),
    ("consultation_charges", "Consultation Charges"),
    ("pharmacy_charges", "Pharmacy & Consumables"),
]
```
- This is the REDUCED set used for the final report when hospital-bill subtotals are found
- Only 5 categories, NOT 20
- Consumables is deliberately excluded
- Pharmacy becomes "Pharmacy & Consumables" (conflates two things)

### Why Two Different Canonicals?
**Reason**: The submission layer tries to anchor report data to the master hospital bill's printed subtotals (Sub Total A = Room, B = Investigation, C = Surgery, etc.)
- This prevents mixing line-item pharmacy invoices with master bill pharmacy total
- But it also LOSES data: consumables, nursing, ambulance charges disappear from the report
- Location of this logic: services/submission/app/main.py line 361-376

---

## PART 4: WHY FIELDS ARE TRIMMED IN THE LAST STEP

### The Trimming Flow

**Step 1: Parser Extracts All 20+ Categories** ✓
- Parser finds: surgery_charges, consumables, investigation_charges, nursing_charges, etc.
- All stored in ParsedField table in database

**Step 2: Submission Gathers Fields** ✓
- Location: services/submission/app/main.py line 330-360
- Reads parsed_fields from DB
- Maps them to _EXPENSE_FIELDS (all 20 categories)
```python
_EXPENSE_FIELDS = {
    "room_charges": "Room Charges",
    "consultation_charges": "Consultation Charges",
    "pharmacy_charges": "Pharmacy & Medicines",
    "investigation_charges": "Diagnostics & Investigations",
    "surgery_charges": "Surgery Charges",
    "surgeon_fees": "Surgeon & Professional Fees",
    "anaesthesia_charges": "Anaesthesia Charges",
    "ot_charges": "Operation Theatre Charges",
    "consumables": "Medical & Surgical Consumables",    # ← ALL HERE
    "nursing_charges": "Nursing & Support Services",
    "icu_charges": "ICU Charges",
    "ambulance_charges": "Ambulance Charges",
    "misc_charges": "Miscellaneous Charges",
    "other_charges": "Other Charges",
}
```
- Produces: expenses = [all 20+ items found]

**Step 3: Hospital Bill Subtotal Extraction** (THE TRIMMING POINT)
- Location: services/submission/app/main.py line 340-376
- Calls _extract_hospital_bill_subtotals(dtext) searching for pattern like:
  ```
  Sub-Total A - Room & Boarding:  36,000
  Sub-Total B - Investigations:   18,000
  Sub-Total C - Procedures/Implants: 1,20,000
  Sub-Total D - Consultations:    16,500
  Sub-Total E - Pharmacy & Consumables: 22,000
  ```
- If found (hospital_bill_subtotals is not empty):
  ```python
  canonical = [
      ("room_charges", "Room Charges"),
      ("investigation_charges", "Diagnostics & Investigations"),
      ("surgery_charges", "Surgery Charges"),
      ("consultation_charges", "Consultation Charges"),
      ("pharmacy_charges", "Pharmacy & Consumables"),  # ← ONLY THESE 5
  ]
  anchored_expenses = []
  for key, label in canonical:
      val = hospital_bill_subtotals.get(key)
      if val and val > 0:
          anchored_expenses.append({"category": label, "amount": val})
  expenses = anchored_expenses  # ← REPLACE!!! NOW ONLY 5 ITEMS
  ```

**Result**: Consumables, nursing_charges, icu_charges, ambulance_charges ALL DISCARDED

### Why This Trimming Exists
1. **Reconciliation**: When hospital bill says "Total = 3,94,000", trust that total + its sub-category breakdown
2. **Deduplication**: Don't mix pharmacy invoice ($1,000) with master bill pharmacy charge ($5,000) — use the master
3. **Authority**: The printed hospital bill is treated as the authoritative summary

### The Problem
- It's **too rigid** — assumes hospital bills ALWAYS follow the Sub-Total A-E pattern
- It's **lossy** — throws away other expense categories that weren't printed as subtotals
- It's **not dynamic** — built-in, no config to disable or customize

---

## PART 5: THE CONTEXT WINDOW & HALLUCINATION PROBLEM

### Current Approach (Problematic)

**How It Works Now**
1. Parser config: PARSER_structured_extraction_enabled=True
2. Parser builds full prompt with all OCR: services/parser/app/engine.py line 825-850
   ```python
   def _build_structured_prompt(ocr_pages, max_chars=None):
       raw_text = "\n\n".join(all page text)
       
       effective_max_chars = max_chars or settings.structured_max_chars  # 24000
       if len(raw_text) > effective_max_chars:
           raw_text = raw_text[: effective_max_chars]  # BRUTAL TRUNCATE
       
       prompt = "You are extracting data from hospital claim documents...\n"
       prompt += f"[Document OCR markdown stream:\n{raw_text}"  # SEND TO LLM
   ```
3. Sends to LLM endpoint (Ollama at http://localhost:11434/api/generate)
4. If times out or fails, falls back to heuristic

**Specific Problems**
1. **Truncation loss**: If OCR > 24,000 chars, last part is cut off silently
   - Expense tables often appear at end of document
   - Surgery, laboratory, consumables rows get truncated before LLM sees them
   
2. **Retry truncation**: If full prompt times out, retries with 8,000 chars
   - Even more data lost
   
3. **Hallucination risk**: LLM sees only partial document
   - Asked for "primary diagnosis", might invent one from secondary diagnosis or procedure notes
   - Sees fragmented billing data, might guess missing amounts

4. **No semantic prioritization**: Truncates linearly (front to back)
   - Should truncate discharge summary details first, keep billing tables
   - But system doesn't know what's important

5. **No per-document fallback strategy**: If claim has 3 documents (bill + discharge + lab)
   - Tries all 3 together, times out
   - Retries smaller, often fails again
   - Falls back to heuristic for entire claim
   - Per-document LLM extraction exists but is only tried as last resort

---

## PART 6: RECOMMENDED SOLUTIONS

### Solution 1: Dynamic Field Mapping (Easy, High Impact)

**Problem It Solves**
- Laboratory not mapped to investigation_charges
- Consumables disappears in report

**Implementation**
```python
# Create config-driven category mapping instead of hard-coded dict
# File: services/parser/app/categories.yaml
expense_categories:
  room:
    keywords: ["room", "bed", "boarding", "accommodation"]
    canonical_field: "room_charges"
    display_label: "Room Charges"
  
  investigation:
    keywords: ["lab", "laboratory", "investigation", "diagnostic", 
               "pathology", "blood test", "radiology"]
    canonical_field: "investigation_charges"
    display_label: "Diagnostics & Investigations"
  
  surgery:
    keywords: ["surgery", "surgical", "procedure", "operation"]
    canonical_field: "surgery_charges"
    display_label: "Surgery Charges"
  
  consumables:
    keywords: ["consumable", "disposable", "implant", "stent", "catheter"]
    canonical_field: "consumables"
    display_label: "Consumables"
  # ... more categories ...

# Then in parser: parser/app/engine.py
def _load_expense_categories():
    with open("categories.yaml") as f:
        return yaml.safe_load(f)["expense_categories"]

# Makes it easy to add new keywords without code change
```

**Benefit**: "Laboratory" will now map to investigation_charges correctly

---

### Solution 2: Semantic-Aware LLM Truncation (Medium Effort, High Impact)

**Problem It Solves**
- Expense tables get truncated before LLM sees them
- Hallucination from incomplete billing data

**Implementation**
```python
# In parser/app/engine.py, replace brutal truncation with smart segmentation

def _build_structured_prompt_smart(ocr_pages, max_chars=24000):
    """
    Segment OCR by document section (demographics, clinical, billing)
    Prioritize sections when truncating.
    """
    organized = {
        "demographics": [],     # Patient info (low importance)
        "clinical": [],         # Diagnosis, procedures, notes (medium importance)
        "billing": [],          # Bill items, totals (HIGH importance)
        "other": []             # Risk factors, etc. (low importance)
    }
    
    # Classify each line by section using regex/heuristics
    for page in ocr_pages:
        text = page.get("text", "")
        for line in text.split("\n"):
            if re.search(r"patient|dob|age|policy|member", line, re.I):
                organized["demographics"].append(line)
            elif re.search(r"diagnosis|procedure|icd|cpt|medication", line, re.I):
                organized["clinical"].append(line)
            elif re.search(r"charge|amount|total|rs|inr|payment", line, re.I):
                organized["billing"].append(line)
            else:
                organized["other"].append(line)
    
    # Build prompt prioritizing billing section
    chunks = []
    for section in ["billing", "clinical", "demographics", "other"]:
        content = "\n".join(organized[section])
        if len("\n\n".join(chunks)) + len(content) < max_chars:
            chunks.append(f"[{section.upper()}]\n{content}")
        # else: skip this section if over limit, but keep higher-priority sections
    
    return "\n\n".join(chunks)
```

**Benefit**: LLM always sees complete billing tables, even if demographics are truncated

---

### Solution 3: Per-Document LLM Extraction by Default (Medium Effort, Very High Impact)

**Problem It Solves**
- Multi-document claims timeout with full concatenation
- Allows fine-grained fallback (doc1 LLM succeeds, doc2 heuristic, doc3 LLM)
- Per-doc extraction with per-doc schema

**Implementation**
```python
# In parser/app/engine.py

def parse_document(ocr_pages):
    page_objects = _build_page_objects(ocr_pages)
    routed_pages = _route_document_pages(page_objects)  # Groups by doc
    
    # Try per-document LLM first (NEW)
    if settings.per_doc_extraction_first:  # NEW CONFIG FLAG
        per_doc_results = {}
        for doc_id, doc_pages in routed_pages.items():
            doc_ocr = [p for p in ocr_pages if p.get("document_id") == doc_id]
            doc_result = _extract_with_structured_llm(doc_ocr)
            per_doc_results[doc_id] = doc_result or _extract_with_model(...) or _extract_with_heuristic(...)
        
        # Merge per-document results
        merged = _merge_structured_extractions(*per_doc_results.values())
        return merged
    
    # Fall back to current behavior (try full doc first, then per-doc)
    full_result = _extract_with_structured_llm(ocr_pages)
    if full_result:
        return full_result
    
    # ... rest of existing logic ...
```

**Benefit**: 
- Smaller context windows per doc (less hallucination risk)
- Faster LLM calls (timeouts less likely)
- Granular fallback (one doc fails, others still succeed)

---

### Solution 4: Configurable Expense Report Template (Medium Effort, Medium Impact)

**Problem It Solves**
- Hard-coded 5-item canonical list loses consumables, nursing, etc.
- Different insurers/regions need different field sets

**Implementation**
```python
# File: services/submission/config/report_templates.yaml
templates:
  default:
    name: "Standard 5-Field Hospital Bill"
    when: "hospital_bill_subtotals found"
    categories:
      - room_charges
      - investigation_charges
      - surgery_charges
      - consultation_charges
      - pharmacy_charges
    description: "Uses Sub-Total A through E from printed bill"
  
  comprehensive:
    name: "Full Expense Breakdown"
    when: "no hospital_bill_subtotals OR explicit_request"
    categories:
      - room_charges
      - consultation_charges
      - pharmacy_charges
      - investigation_charges
      - surgery_charges
      - surgeon_fees
      - anaesthesia_charges
      - ot_charges
      - consumables         # ← NOW INCLUDED
      - nursing_charges
      - icu_charges
      - ambulance_charges
      - misc_charges
    description: "All extracted categories, even if not in printed subtotals"
  
  minimal:
    name: "Subtotals Only"
    when: "high_confidence_hospital_bill"
    categories:
      - room_charges
      - investigation_charges
      - surgery_charges
    description: "Only most reliable categories"

# In submission/app/main.py
report_template = load_report_template(claim.context)  # Config or data-driven
for category in report_template.categories:
    if value := parsed.get(category):
        expenses.append(...)
```

**Benefit**: Report generation becomes pluggable; insurers can customize what appears

---

### Solution 5: Structured Data Pipeline with Semantic Routing (Advanced, Highest Impact)

**Problem It Solves**
- Everything: OCR→Parser→LLM→Report is monolithic
- No way to intercept, validate, or transform at intermediate stages

**Implementation**
```
[OCR] → [Semantic Router] → [Specialised Extractors] → [Validator] → [Report]
  ↓           ↓                    ↓                        ↓
Raw text   Document type      Doc-specific LLM         Field schema
           Confidence          (with small context)     audit trail
           Section markers
           
New workflow:
1. OCR produces page + confidence
2. Semantic Router:
   - Classifies as HOSPITAL_BILL | LAB_REPORT | PHARMACY | etc.
   - Extracts section boundaries (demographics, clinical, billing)
   - Routes to specialized handler
   
3. Specialized Extractors:
   - LLM gets ONLY the relevant section (billing for hospital bill)
   - Context window 4,000-6,000 chars (not 24,000)
   - Schema is doc-type specific (not generic StructuredClaimExtraction)
   
4. Validator:
   - Cross-references fields across documents
   - Flags inconsistencies (patient name mismatch, duplicate charges)
   - Suggests fallback strategy
   
5. Report:
   - Uses validation results to decide which fields to trust
   - Multiple report templates based on data confidence
```

**Pseudo-code**
```python
# services/parser/app/semantic_router.py
class SemanticRouter:
    def route(self, ocr_pages: List[Dict]) -> List[Dict]:
        """Return list of (doc_type, sections_map, confidence, pages)"""
        results = []
        for page_batch in ocr_pages:
            doc_type = classify_document_type(page_batch)
            sections = extract_sections(page_batch)  # {demographics: ..., billing: ...}
            confidence = calculate_confidence(doc_type, sections)
            results.append({
                "document_type": doc_type,
                "sections": sections,
                "confidence": confidence,
                "pages": page_batch,
                "recommendation": determine_extractor(doc_type, confidence)
            })
        return results

# services/parser/app/extractors/hospital_bill_extractor.py
class HospitalBillExtractor:
    def extract(self, semantic_route: Dict) -> ParseOutput:
        """Extract from routed hospital bill with small context window"""
        # LLM sees ONLY billing section (< 6000 chars)
        billing_section = semantic_route["sections"]["billing"]
        prompt = self._build_focused_prompt(billing_section)
        
        # Doc-type-specific schema (not generic)
        llm_result = self._call_llm(prompt, schema=HospitalBillSchema)
        
        # Validate: cross-reference totals
        errors = self._validate_bill_integrity(llm_result)
        llm_result.confidence = self._adjust_confidence(errors)
        
        return llm_result

# services/submission/app/report_engine.py
class ReportEngine:
    def build(self, extraction: ParseOutput) -> Dict:
        """Use confidence scores to select report template"""
        if extraction.confidence >= 0.95:
            template = "comprehensive"  # Include all extracted fields
        elif extraction.confidence >= 0.75:
            template = "default"        # Use canonical 5-field set
        else:
            template = "audit"          # Flag all fields, require manual review
        
        return self._render_template(template, extraction)
```

**Benefit**: 
- Context per doc <6KB (safe from LLM hallucination)
- Confidence scoring throughout pipeline
- Doc-type-specific extraction (hospital bill != lab report)
- Multiple report templates based on data quality

---

## PART 7: PRIORITIZED ACTION PLAN

### Week 1 (Quick Wins)
1. ✅ Enable PaddleOCR-VL in dev environment → Improved OCR structure
2. ✅ Fix expense_category_map to include "laboratory" → Fixes missing investigation_charges
3. ✅ Add config flag for which expense template to use (canonical vs comprehensive)

### Week 2 (Medium Effort)
4. Implement semantic-aware LLM truncation (Solution 2)
5. Make per-document LLM extraction the default (Solution 3)
6. Add expense category mapping from config file (Solution 1)

### Week 3+ (Advanced)
7. Implement semantic router (Solution 5)
8. Build doc-type-specific extractors
9. Add validation layer with audit trails

---

## PART 8: DISCUSSION POINTS FOR OTHER DEVELOPERS/GPT MODELS

### Frame It as:
"We have a multi-stage document processing pipeline where data flows through OCR → field extraction → report assembly. Currently:

1. **OCR Stage**: We use PaddleOCR (classic), optionally PaddleOCR-VL
   - Problem: Classic version doesn't understand table layouts; VL version disabled
   
2. **Extraction Stage**: We try LLM → LayoutLMv3 → heuristic fallback
   - Problem: LLM gets full OCR (~24KB), truncates brutally, causes hallucination
   - Solution: Semantic routing to send small, focused sections to LLM
   
3. **Report Stage**: We have 20+ extracted fields but show only 5 in final report
   - Problem: Field list is hard-coded; users can't customize
   - Problem: Consumables, nursing charges get discarded
   - Solution: Pluggable report templates based on document type + confidence
   
**The Core Issue**: We're treating all documents the same, and all context as equally important.
**The Core Fix**: Route documents to specialized extractors, prioritize sections by semantic importance, make report field selection dynamic."

### Questions to Ask GPT/Developers:
1. "How would you handle a multi-document claim (bill + discharge + lab) without concatenating everything into one LLM prompt?"
   - Hint: Per-document extraction + merging
   
2. "If an LLM times out on 24KB of context, should we retry with 8KB, or change the input?"
   - Hint: Change input — prioritize billing tables, discard demographics
   
3. "The final report drops 'consumables' fields even though they're extracted. Why might this be intentional?"
   - Hint: Reconciliation — trust printed subtotals, not derived calculations
   - Better approach: Add reconciliation warnings ("Extracted consumables ≠ printed total")
   
4. "How would you make the expense category list dynamic instead of hard-coded?"
   - Hint: Config file (YAML/JSON) + inheritance (base template + custom overrides)

---

## APPENDIX A: FILE REFERENCE QUICK LOOKUP

| Component | Problem | File | Lines |
|-----------|---------|------|-------|
| OCR Engine | Which model is used? | services/ocr/app/config.py | 16 |
| OCR Engine | VL model selection | services/ocr/app/engine.py | 126, 141 |
| Parser | Document type routing | services/parser/app/engine.py | 655-680 |
| Parser | Field allowlists | services/parser/app/engine.py | 272-290 |
| Parser | Category mapping | services/parser/app/engine.py | 1778-1823 |
| Parser | Why LLM truncates | services/parser/app/engine.py | 839 |
| Parser | Fallback mechanisms | services/parser/app/engine.py | 579-652 |
| Submission | Expense extraction | services/submission/app/main.py | 330-360 |
| Submission | Canonical 5 fields | services/submission/app/main.py | 362-367 |
| Submission | Why trim happens | services/submission/app/main.py | 361-376 |

---

## APPENDIX B: EXAMPLE DEBUG OUTPUT INTERPRETATION

Your debug file shows:
```json
{
  "model_version": "heuristic-v2",
  "used_fallback": true,
  "ocr_pages": [...],
  "fields": [
    {"field_name": "surgery_charges", "field_value": "120000"},
    {"field_name": "investigation_charges", "field_value": "18000"},
    {"field_name": "consumables", "field_value": "35000"}
  ]
}
```

**Interpretation**:
1. Parser tried structured LLM → no response or schema validation failed
2. Parser fell back to LayoutLMv3 → not available or failed
3. Parser fell back to heuristic-v2 (regex patterns)
4. Heuristic successfully extracted surgery, investigation, consumables
5. BUT... when report is built, consumables disappears

**Why**: The submission layer finds hospital_bill_subtotals (Sub-Total A-E printed on bill)
- Replaces ALL 3 extracted fields with only 5 canonical ones from subtotals
- Consumables not in Sub-Total breakdown, so it disappears

**Solution**: Make the report template configurable, or flag confidence for discarded fields.

