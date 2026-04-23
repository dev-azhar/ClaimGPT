================================================================================
QUICK REFERENCE: OCR→FIELD→REPORT FLOW WITH LOSS POINTS
================================================================================

VISUAL FLOW DIAGRAM
─────────────────────────────────────────────────────────────────────────────

INPUT: PDF/Image (Hospital Bill + Discharge Summary + Lab Report)
   │
   ├─→ [OCR ENGINE]
   │     • PaddleOCR-VL (VL model for layout) — DISABLED (enable_paddle_vl=False)
   │     • Classic PaddleOCR (text only) — ACTIVE (fallback: Tesseract)
   │     OUTPUT: Raw OCR text for each page
   │
   ├─→ [SEMANTIC ROUTER] (Parser config)
   │     • Classify each page: HOSPITAL_BILL | LAB_REPORT | PHARMACY | DISCHARGE | UNKNOWN
   │     • Restrict field allowlist per type
   │     • For our claim: Routed as LAB_REPORT (restrictive)
   │     OUTPUT: Routed pages + document type
   │
   ├─→ [FIELD EXTRACTION]  ← ALL 3 FIELDS PRESENT HERE
   │   ├─ Try [Structured LLM]
   │   │   • Sends to Ollama (http://localhost:11434)
   │   │   • Full OCR + JSON schema → tries to extract
   │   │   • ❌ TIMEOUT or ENDPOINT DOWN → fallback
   │   │
   │   ├─ Try [LayoutLMv3 Model]
   │   │   • Token-level classification on images
   │   │   • ❌ MODEL NOT AVAILABLE → fallback
   │   │
   │   └─ Use [Heuristic-v2] (40+ regex patterns) ✓ ACTIVE
   │       • Regex matches: _PAT_SURGERY_CHARGE, _PAT_CONSUMABLES, etc.
   │       • Expense category map normalizes keywords:
   │         - "Surgery Charges" → surgery_charges
   │         - "Laboratory" → investigation_charges (via keyword "lab")
   │         - "Consumables" → consumables
   │       OUTPUT: Extracted fields (all 20 categories possible)
   │         \→ ParsedField table: [ surgery_charges, investigation_charges, consumables ]
   │
   ├─→ [SUBMISSION LAYER] (Report Assembly)
   │     • Gathers all parsed fields from DB
   │     • Stage 1: Builds full expense list (all 20 categories)
   │     • Stage 2: Tries to find hospital_bill_subtotals (pattern match)
   │       ✓ FOUND: "Sub-Total A:36000 B:18000 C:120000 D:16500 E:22000"
   │     • Stage 3: IF subtotals found → REPLACE full list with CANONICAL 5 only
   │       ❌ LOSS POINT: consumables, nursing_charges, icu_charges dropped
   │     • Stage 4: Build report with canonical 5 fields
   │
   └─→ OUTPUT: Report/Preview
         • Room Charges: 36,000
         • Diagnostics & Investigations: 18,000
         • Surgery Charges: 120,000
         • Consultation: 16,500
         • Pharmacy & Consumables: 22,000
         
         ❌ MISSING: surgery_charges detail breakdown
         ❌ MISSING: consumables (120,000 if surgery was breakdown)
         ❌ MISSING: nursing charges, ICU charges, ambulance


KEY LOSS MECHANISMS
─────────────────────────────────────────────────────────────────────────────

Loss #1: LABORATORY → INVESTIGATION
   Location: parser/app/engine.py line 1798 (_EXPENSE_CATEGORY_MAP)
   Problem: "laboratory" keyword NOT mapped; "lab" IS mapped to investigation_charges
   Evidence: Your OCR shows "Laboratory Cardiac enzymes..." but report shows "Diagnostics"
   Impact: Field renamed, not lost (still appears as investigation_charges)
   
Loss #2: CONSUMABLES DROPPED
   Location: submission/app/main.py line 376
   Problem: Canonical 5-field list does not include consumables
   Condition: Only happens IF hospital_bill_subtotals extraction succeeds
   Evidence: Your hospital bill has Sub-Total A-E, not consumables separately
   Impact: Consumables value DISCARDED even if it was extracted (120,000 lost)
   
Loss #3: SURGERY CHARGES (Potential)
   Location: submission/app/main.py line 369 (canonical list)
   Problem: "Surgery Charges" IS in canonical 5, but mapped to wrong subtotal?
   Condition: Only if LLM or heuristic didn't extract "surgery_charges" field
   Evidence: Check if parsed_fields table has surgery_charges row
   
Loss #4: CONTEXT WINDOW (LLM Path — Currently Disabled)
   Location: parser/app/engine.py line 839 (max truncation)
   Problem: Full OCR truncated at 24,000 chars; LLM never sees complete bill items
   Impact: LLM hallucinates or skips fields not in first 24KB
   Status: Mitigated by fallback to heuristic (which uses full text via regex)


WHAT'S ACTUALLY USED (YOUR CONFIG)
─────────────────────────────────────────────────────────────────────────────

OCR Model Stack:
  1. PaddleOCR-VL 1.5 with doc-parser? NO (disabled in production)
  2. Classic PaddleOCR? YES (default fallback)
  3. Tesseract? YES (final fallback)

Parser Extraction Stack:
  1. Structured LLM? YES, but endpoint not responding (fallback → heuristic)
  2. LayoutLMv3? NO (transformer not loaded in this environment)
  3. Heuristic-v2? YES, currently used for your claim

Report Generation:
  1. Full 20-field list? YES (intermediate stage)
  2. Canonical 5-field filtering? YES (if hospital_bill_subtotals found)
  3. Audit trail of dropped fields? NO


SOLUTION SUMMARY
─────────────────────────────────────────────────────────────────────────────

Issue               | Root Cause                  | Fix
─────────────────────────────────────────────────────────────────────────────
VLM disabled        | OCR_enable_paddle_vl=False  | Set to True (needs model download)
Laboratory lost     | "lab" keyword only in map   | Add "laboratory" to keyword list
Consumables lost    | Not in canonical 5-field    | Add to list OR make configurable
LLM hallucination   | Full OCR truncated          | Send only billing section to LLM
Multi-doc timeout   | LLM tries all docs together | Per-document extraction instead
Report inflexible   | 5 fields hard-coded         | Make template config-driven
No visibility       | No confidence scores        | Add validation + audit layer


QUESTIONS TO ASK OTHER TEAMS
─────────────────────────────────────────────────────────────────────────────

Q1: "Our OCR-to-LLM pipeline truncates context windows at 24KB. Should we:
     A) Truncate less (bigger context windows)?
     B) Truncate smarter (priority-based sections)?
     C) Split input (per-document extraction)?
     D) Use different model (long-context LLM)?"
     
     RECOMMENDATION: C + B (combine strategies)

Q2: "We have 20 extractable expense fields but only show 5 in the report.
     The missing 5 are based on a regex pattern for 'Sub-Total A-E' printed on bills.
     If that pattern isn't found, should we:
     A) Report all 20 fields?
     B) Report 5 + flag missing ones?
     C) Ask user which template to use?
     D) Use ML to predict which fields are trustworthy?"
     
     RECOMMENDATION: B + C (confidence-aware + user-selectable)

Q3: "Our heuristic extraction works well (uses full text), but LLM extraction
     is sensitive to input size (timeouts). Should we:
     A) Make heuristic the default, LLM optional?
     B) Pre-process OCR to remove low-signal content?
     C) Use specialized LLMs per document type?
     D) Keep both, use confidence to blend results?"
     
     RECOMMENDATION: C + D (doc-type-specific, ensemble scoring)


DATABASE VERIFICATION (If You Want to Verify)
─────────────────────────────────────────────────────────────────────────────

Check what was actually extracted:
```sql
SELECT field_name, field_value, parser_model_version 
FROM parsed_field 
WHERE parse_job_id = (SELECT id FROM parse_job WHERE claim_id = your_claim_id)
ORDER BY field_name;
```

Expected output (your case):
  surgery_charges       | 120000
  investigation_charges | 18000
  consumables           | 35000
  [other fields...]

If consumables is missing from query, it was never extracted.
If present, the submission layer discarded it (Loss #2).

Check if hospital_bill_subtotals was found:
```sql
SELECT sub_total_a, sub_total_b, sub_total_c, sub_total_d, sub_total_e
FROM claim 
WHERE id = your_claim_id;
```

If these are populated, it triggered the "replace with canonical" logic.


TECHNICAL DEBT TRACKER
─────────────────────────────────────────────────────────────────────────────

⚠️  IMMEDIATE (Days)
   - Add "laboratory" to category keyword map
   - Enable/test PaddleOCR-VL in dev environment

⚠️  SHORT TERM (Weeks)
   - Make expense template configurable (YAML)
   - Implement semantic-aware LLM truncation
   - Add confidence scoring to parsed fields

⚠️  MEDIUM TERM (Months)
   - Per-document extraction by default
   - Doc-type-specific LLM schemas
   - Validation layer with audit trails

⚠️  LONG TERM (Strategic)
   - Semantic router (intelligent section prioritization)
   - Multi-model ensemble (LLM + heuristic + ML blend)
   - Pluggable report templates system
   - Confidence-driven fallback chains

