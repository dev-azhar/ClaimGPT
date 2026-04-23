================================================================================
ARCHITECTURE COMPARISON: Current vs. Proposed Dynamic System
================================================================================

═══════════════════════════════════════════════════════════════════════════════
CURRENT ARCHITECTURE (Hard-Coded, Lossy)
═══════════════════════════════════════════════════════════════════════════════

┌─ USER UPLOADS PDF ───────────────────────────────────────────────────────┐
│                                                                            │
│  [Hospital Bill] [Discharge Summary] [Lab Report] → Single PDF            │
│                                                                            │
└────────────────────────────────────────┬─────────────────────────────────┘
                                         │
┌─ OCR ENGINE ─────────────────────────┐ │
│                                      │ │
│  PaddleOCR-VL? NO (disabled)         ├─┘
│  Classic PaddleOCR? YES               │
│  Output: Raw text per page           │
│                                      │
│  ❌ No table structure preserved      │
│  ❌ No document layout understanding  │
└──────────┬───────────────────────────┘
           │ (Raw OCR text containing all fields)
           │
     ┌─────▼──────────────────────────────────────┐
     │ "Surgery Charges  120000                   │
     │  Laboratory Cardiac enzymes 18000          │
     │  Consumables/Implants 35000"               │
     └─────┬──────────────────────────────────────┘
           │
┌─ PARSER ENGINE ──────────────────────────────────────────┐
│                                                          │
│  Try [Structured LLM] → Full 24KB prompt               │
│  ❌ Endpoint not responding → Fallback                  │
│                                                          │
│  Try [LayoutLMv3] → Model not available → Fallback     │
│  ❌ Transformer not loaded                              │
│                                                          │
│  Use [Heuristic-v2] ✓ ACTIVE                            │
│  • Regex patterns for each field                        │
│  • Expense category map (HARD-CODED in engine.py)      │
│    - "lab" → investigation_charges                      │
│    - "laboratory" → NOT MAPPED ❌ (missing keyword)     │
│    - "consumable" → consumables ✓                       │
│    - "surgery" → surgery_charges ✓                      │
│                                                          │
│  Output: 3 ParsedField rows                             │
│    ├─ surgery_charges: 120,000 ✓                       │
│    ├─ investigation_charges: 18,000 ✓                  │
│    └─ consumables: 35,000 ✓                            │
│                                                          │
└──────────┬─────────────────────────────────────────────┘
           │
┌─ DATABASE ─────────────────────────────────┐
│  ParsedField table (all fields stored)    │
│    ├─ surgery_charges ✓                   │
│    ├─ investigation_charges ✓             │
│    └─ consumables ✓                       │
└──────────┬─────────────────────────────────┘
           │
┌─ SUBMISSION LAYER ──────────────────────────────────────┐
│                                                          │
│  Stage 1: Get all parsed fields from DB                 │
│    ├─ surgery_charges ✓                                 │
│    ├─ investigation_charges ✓                           │
│    └─ consumables ✓                                     │
│  Subtotal: 3 fields, Total: 173,000                     │
│                                                          │
│  Stage 2: Try to find hospital_bill_subtotals           │
│    ✓ FOUND: Sub-Total pattern extracted                 │
│    ├─ Sub-Total A (Room): 36,000                        │
│    ├─ Sub-Total B (Investigation): 18,000              │
│    ├─ Sub-Total C (Surgery): 120,000                   │
│    ├─ Sub-Total D (Consultation): 16,500               │
│    └─ Sub-Total E (Pharmacy): 22,000                   │
│  Grand Total: 212,500                                   │
│                                                          │
│  Stage 3: ❌ HARD-CODED LOGIC                            │
│    if hospital_bill_subtotals:                          │
│        canonical = [                                    │
│            ("room_charges", "Room Charges"),             │
│            ("investigation_charges", "Diagnostics"),    │
│            ("surgery_charges", "Surgery Charges"),      │
│            ("consultation_charges", "Consultation"),    │
│            ("pharmacy_charges", "Pharmacy & Meds"),     │
│        ]  ← ONLY 5 FIELDS, CONSUMABLES EXCLUDED!       │
│        expenses = build_from_canonical()               │
│                                                          │
│  Result: THROW AWAY 2 FIELDS (consumables, others)     │
│    ├─ Room Charges: 36,000 ✓                           │
│    ├─ Diagnostics: 18,000 ✓                            │
│    ├─ Surgery: 120,000 ✓                               │
│    ├─ Consultation: 16,500 ✓                           │
│    ├─ Pharmacy: 22,000 ✓                               │
│    └─ ❌ CONSUMABLES: 35,000 LOST                        │
│  New Total: 212,500 (matches subtotals but is lossy)    │
│                                                          │
└──────────┬──────────────────────────────────────────────┘
           │
┌─ FINAL REPORT ─────────────────────────────────┐
│                                                 │
│  Expense Summary (5 Fields)                    │
│  ├─ Room Charges             36,000           │
│  ├─ Diagnostics               18,000           │
│  ├─ Surgery Charges          120,000           │
│  ├─ Consultation              16,500           │
│  └─ Pharmacy & Consumables    22,000           │
│                                                 │
│  ⚠️  Missing: Consumables (35,000) was extracted │
│      but dropped by canonical 5-field filter   │
│                                                 │
│  Total: 212,500 ✓ (matches printed bill)       │
│                                                 │
└─────────────────────────────────────────────────┘

ISSUES WITH CURRENT ARCHITECTURE:
────────────────────────────────────────────────
1. ❌ OCR is dumb (no layout/structure preservation)
2. ❌ Field mapping is hard-coded (can't add keywords without code change)
3. ❌ "laboratory" keyword missing → investigation_charges not recognized
4. ❌ Canonical list is hard-coded to 5 fields → consumables always dropped
5. ❌ No configurability (insurance A vs B need different templates)
6. ❌ No confidence scores (can't audit what was discarded)
7. ❌ LLM truncation is brutal (context window issues not visible)


═══════════════════════════════════════════════════════════════════════════════
PROPOSED ARCHITECTURE (Dynamic, Config-Driven, Extensible)
═══════════════════════════════════════════════════════════════════════════════

┌─ USER UPLOADS PDF ───────────────────────────────────────────────────────┐
│                                                                            │
│  [Hospital Bill] [Discharge Summary] [Lab Report] → Single PDF            │
│                                                                            │
└────────────────────────────────────────┬─────────────────────────────────┘
                                         │
┌─ OCR ENGINE ─────────────────────────┐ │
│                                      │ │
│  PaddleOCR-VL? YES (enable_paddle_vl) ├─┘
│  With doc-parser mode (markdown)     │
│  Classic PaddleOCR fallback          │
│                                      │
│  ✅ Tables detected & output as markdown
│  ✅ Document layout understood        │
│  Output: Structured markdown + text  │
│                                      │
│  | Header | Amount |                │
│  | ---... | ...    |                │
└──────────┬───────────────────────────┘
           │
     ┌─────▼──────────────────────────────────────────┐
     │ [BILLING TABLE - MARKDOWN]                    │
     │ | Item | Amount |                             │
     │ | Surgery Charges | 120000 |                  │
     │ | Laboratory Cardiac enzymes | 18000 |        │
     │ | Consumables/Implants | 35000 |             │
     │ ...                                           │
     └─────┬──────────────────────────────────────────┘
           │
┌─ SEMANTIC ROUTER (NEW) ──────────────────────────┐
│                                                  │
│  Purpose: Classify + prioritize for LLM          │
│  1. Detect document type (HOSPITAL_BILL)        │
│  2. Extract section boundaries                   │
│     ├─ Demographics (low priority)              │
│     ├─ Clinical (medium priority)               │
│     └─ Billing (HIGH priority) ← Send to LLM    │
│  3. Calculate semantic confidence               │
│  4. Choose specialized extractor                │
│                                                  │
│  Output: Routed document with context           │
└──────────┬─────────────────────────────────────┘
           │
┌─ PARSER ENGINE ──────────────────────────────────────────────┐
│                                                              │
│  Try [Specialized LLM] (small context)                       │
│  • Billing section only (~4KB, not 24KB)                    │
│  • Doc-type specific schema (HOSPITAL_BILL != LAB)          │
│  • Timeout less likely, hallucination reduced ✅             │
│                                                              │
│  Try [LayoutLMv3] (if enabled)                              │
│  Try [Heuristic-v2]                                         │
│                                                              │
│  CRITICAL: Use config-driven category map (NOT hard-coded)  │
│  • Load from categories.yaml at runtime                     │
│  • "laboratory" → investigation_charges ✅ (in config now)   │
│  • Easy to add keywords: just edit YAML                     │
│                                                              │
│  Output: ParsedField rows + CONFIDENCE SCORES               │
│    ├─ surgery_charges: 120,000 [confidence: 0.95] ✓        │
│    ├─ investigation_charges: 18,000 [confidence: 0.95] ✓   │
│    ├─ consumables: 35,000 [confidence: 0.90] ✓             │
│    └─ [other fields...]                                     │
│                                                              │
│  Validation: Check consistency across documents             │
│  • Flags: "Total mismatch", "Duplicate entries", etc.       │
│                                                              │
└──────────┬─────────────────────────────────────────────────┘
           │
┌─ DATABASE ────────────────────────────────────────────┐
│  ParsedField table (enhanced)                        │
│    • field_name, field_value (as before)             │
│    • confidence_score (NEW) for each field           │
│    • extraction_method (NEW): "llm", "heuristic"    │
│    • source_document (NEW): which doc it came from   │
│    • validation_issues (NEW): audit trail            │
│                                                      │
│  All 3 fields still stored:                          │
│    ├─ surgery_charges [0.95]                        │
│    ├─ investigation_charges [0.95]                  │
│    └─ consumables [0.90]                            │
│                                                      │
└──────────┬─────────────────────────────────────────────┘
           │
┌─ REPORT TEMPLATE SELECTOR (NEW) ─────────────────────────┐
│                                                          │
│  Logic: Which template to use?                          │
│  Conditions (from report_templates.yaml):               │
│    • If hospital_bill_subtotals found                   │
│      → Use "hospital_bill_standard" (5 fields)          │
│    • Else                                               │
│      → Use "comprehensive" (all extracted)              │
│    • If insurance_provider == "Insurance A"             │
│      → Use "insurance_company_a_template"               │
│    • If audit_requested                                │
│      → Use "audit_template" (show everything)           │
│                                                          │
│  Selected: "comprehensive" (because explicit request)   │
│                                                          │
└──────────┬──────────────────────────────────────────────┘
           │
┌─ SUBMISSION & FILTERING ───────────────────────────────┐
│                                                         │
│  Get all parsed fields from DB                        │
│    ├─ surgery_charges: 120,000 ✓                      │
│    ├─ investigation_charges: 18,000 ✓                 │
│    ├─ consumables: 35,000 ✓                           │
│    ├─ nursing_charges: 8,000 ✓                        │
│    └─ [other fields...]                               │
│                                                         │
│  Apply template filter:                                │
│  For each field in template:                           │
│    if confidence >= threshold (0.80):                  │
│      include in report ✓                              │
│    else:                                               │
│      add to discarded_fields_audit ✓                   │
│                                                         │
│  Result: All extracted fields can be shown             │
│    Depending on template selection                    │
│                                                         │
└──────────┬─────────────────────────────────────────────┘
           │
┌─ FINAL REPORT ──────────────────────────────────────────┐
│                                                          │
│  OPTION 1: Hospital Bill Standard (5 fields)           │
│  ├─ Room Charges          36,000                       │
│ ├─ Diagnostics            18,000                       │
│  ├─ Surgery Charges      120,000                       │
│  ├─ Consultation          16,500                       │
│  └─ Pharmacy             22,000                        │
│  [Discarded: Consumables 35,000 (not in subtotals)]  │
│                                                          │
│  OPTION 2: Comprehensive (all extracted) ✅ NOW DEFAULT  │
│  ├─ Room Charges          36,000 [confidence: 0.95]   │
│  ├─ Diagnostics           18,000 [confidence: 0.95]   │
│  ├─ Surgery Charges      120,000 [confidence: 0.95]   │
│  ├─ Consultation          16,500 [confidence: 0.92]   │
│  ├─ Pharmacy              22,000 [confidence: 0.90]   │
│  ├─ Consumables           35,000 [confidence: 0.90] ← NOW INCLUDED
│  ├─ Nursing Services       8,000 [confidence: 0.85]   │
│  └─ [others...]                                        │
│  Total: 255,500 (includes all extracted values)        │
│                                                          │
│  OPTION 3: Audit Report (full transparency)            │
│  Same as Option 2, plus:                               │
│  • Extraction method: "LayoutLMv3", "heuristic-v2"    │
│  • Source document: "page 5 of bill"                  │
│  • Validation notes: "±matches subtotals"             │
│  • Confidence breakdown by extraction method          │
│                                                          │
│  ✅ Non-engineers can define new templates in YAML     │
│  ✅ Insurance company A can have different template    │
│  ✅ Consumables no longer lost silently                │
│  ✅ Confidence scores provide audit trail              │
│                                                          │
└──────────────────────────────────────────────────────────┘

IMPROVEMENTS IN PROPOSED ARCHITECTURE:
───────────────────────────────────────
✅ OCR is smart (table detection, structure preservation)
✅ Field mapping is config-driven (categories.yaml, not hard-coded)
✅ "laboratory" keyword added to config → investigation_charges recognized
✅ Canonical list is template-based (can be anything: 5, 10, 20+ fields)
✅ Multiple templates per use case (insurance A, B, audit, minimal, etc.)
✅ Confidence scores throughout pipeline → audit-ready
✅ Smaller LLM contexts (per-document, per-section) → less hallucination
✅ Specialized extractors per document type
✅ Easy to debug: configuration is visible, not buried in code


═══════════════════════════════════════════════════════════════════════════════
SIDE-BY-SIDE COMPARISON TABLE
═══════════════════════════════════════════════════════════════════════════════

Feature                          Current              Proposed
─────────────────────────────────────────────────────────────────────────
OCR Model                        Classic PaddleOCR    PaddleOCR-VL (smart)
OCR Output                       Raw text             Markdown + structure
Field Mapping                    Hard-coded dict      Config file (YAML)
Add new keyword                  Code change          Edit categories.yaml
Expense Categories              20 possible, 5 shown  20 possible, 5-20 shown
Report Templates                 1 canonical         N templates (configurable)
Consumables in report            ❌ (dropped)         ✅ (in comprehensive)
Confidence tracking             None                 All fields scored
Discarded fields audit          None                 Full audit section
LLM Context Window              24KB (risky)         ~4KB per section (safe)
Timeouts                        Common               Rare
LLM Hallucination Risk          High                 Low
Insurance A vs B               Same report          Different templates
Per-doc extraction             Last resort          Default strategy
Template customization         Code change          Config file edit
Data transparency              Low (black box)      High (audit trail)
Learning curve (new feature)   Medium               Low (config-driven)
Time to deploy new category    2-3 days             10 minutes (edit YAML)


═══════════════════════════════════════════════════════════════════════════════
IMPLEMENTATION COMPLEXITY MATRIX
═══════════════════════════════════════════════════════════════════════════════

Phase    Feature                      Effort    Impact     Risk    Timeline
─────────────────────────────────────────────────────────────────────────────
1        Dynamic category mapping     2 days    HIGH      LOW     Week 1
         + Load from categories.yaml

2        Report templates             3 days    HIGH      LOW     Week 2
         + Config-driven selection

3        Confidence scoring           2 days    MEDIUM    LOW     Week 2
         + Store in DB

4        Semantic-aware LLM trunc.    4 days    HIGH      MED     Week 3
         + Section prioritization

5        Per-document extraction      2 days    HIGH      LOW     Week 3
         + Doc-type-specific schemas

TOTAL:   3-4 weeks of development, mostly config-based (LOW RISK)


═══════════════════════════════════════════════════════════════════════════════
QUESTIONS FOR STAKEHOLDERS
═══════════════════════════════════════════════════════════════════════════════

Q1: "Currently, consumables charges are extracted by the parser but dropped
     in the report. Should the final report always show consumables if they're
     found, or only when insurance policy allows?"
     
     ANSWER: "Template-driven. If policy says show consumables, template includes it.
              If not, template excludes it, but audit section can show it was extracted."

Q2: "We use a local Ollama LLM for field extraction. It times out on large documents.
     Should we use a remote GPT-4 instead, or optimize our input?"
     
     ANSWER: "Optimize input first (semantic truncation + per-doc extraction).
              Remote GPT-4 has cost/latency tradeoffs, better as fallback only."

Q3: "Different insurance companies have different billing formats. How many
     templates do we need?"
     
     ANSWER: "Start with 3: standard (5-field), comprehensive (20-field), audit.
              Each insurance company inherits + customizes. Easy to scale."

Q4: "The parser sometimes misses fields due to document variability.
     How do we know when to trust the parser vs. the printed subtotals?"
     
     ANSWER: "Confidence scoring + validation. If parser says 'consumables: 35K'
              but subtotals don't mention it, we validate it and flag for review."

