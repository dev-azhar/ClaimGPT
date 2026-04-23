================================================================================
EXECUTIVE SUMMARY: ClaimGPT OCR Field Loss Problem & Dynamic Solution
================================================================================

For: Backend developers, ML engineers, architects, team leads
Date: 2026-04-09
Status: Analysis complete, recommendations ready for implementation

—————————————————————————————————————————————————————————————————————————————————

PRIMARY PROBLEM
═════════════════════════════════════════════════════════════════════════════

User observed: Three expense fields (surgery charges, laboratory charges, 
consumables) are present in OCR and parser debug output but missing from the 
final report.

ROOT CAUSE ANALYSIS
─────────────────────────────────────────────────────────────────────────────

Field Loss #1: LABORATORY → Investigation Charges
  Code Location:  services/parser/app/engine.py line 1798
  Issue:          Keyword "laboratory" not in _EXPENSE_CATEGORY_MAP (hard-coded)
  Result:         Field extracted as "investigation_charges" instead of "laboratory"
  Impact:         Label changes, but amount is preserved (less severe)
  Fix:            Add "laboratory" to categories.yaml keyword list
  
Field Loss #2: CONSUMABLES Discarded by Report Filter
  Code Location:  services/submission/app/main.py line 376
  Issue:          Canonical 5-field list = [room, investigation, surgery, consultation, pharmacy]
                  Consumables NOT in this list
  Condition:      When hospital_bill_subtotals extraction succeeds (printed Sub-Total A-E found)
                  Parser REPLACES all 20+ extracted fields with ONLY these 5 canonical
  Result:         Consumables value (35,000) extracted but then deleted from report
  Impact:         Data loss: complete field disappears from output
  Fix:            Replace hard-coded canonical with configurable templates

Field Loss #3: SURGERY Charges (Potential)
  Code Location:  services/submission/app/main.py line 369
  Issue:          Surgery IS in canonical 5, but may fail extraction if:
                  (a) Structured LLM endpoint not responding
                  (b) Heuristic doesn't match "Surgery Charges" text pattern
  Result:         Depends on whether heuristic pattern matched in parser phase
  Impact:         Full field loss if extraction failed earlier in pipeline
  Fix:            Improve heuristic patterns + confidence scoring

UNDERLYING ARCHITECTURAL PROBLEMS
─────────────────────────────────────────────────────────────────────────────

1. ❌ Hard-Coded Field Mapping (engine.py line 1778-1823)
   • Expense category keywords embedded in Python dict
   • Adding "laboratory" keyword requires code change + deployment
   • Can't add keywords at runtime or via config
   
   Example:
   ```python
   _EXPENSE_CATEGORY_MAP = {
       "lab": "investigation_charges",      # ← Hard-coded
       "laboratory": MISSING,                # ← PROBLEM
       "consumable": "consumables",
       # 30+ more lines ...
   }
   ```

2. ❌ Hard-Coded Canonical Report Fields (main.py line 362-367)
   • 5-field list = [room, investigation, surgery, consultation, pharmacy]
   • Directly embedded in Python code
   • When hospital_bill_subtotals found, REPLACES all parsed fields with only these 5
   • Consumables, nursing, ICU, ambulance charges always dropped
   • No flexibility for different insurance companies or use cases
   
   Example:
   ```python
   canonical = [
       ("room_charges", "Room Charges"),               # ← Hard-coded
       ("investigation_charges", "Diagnostics..."),   # ← Hard-coded
       ("surgery_charges", "Surgery Charges"),        # ← Hard-coded
       # ... rest hard-coded, consumables NOT here   # ← PROBLEM
   ]
   # Always use only these 5 if subtotals found
   if hospital_bill_subtotals:
       expenses = [extracted from canonical only]     # ← LOSSY!
   ```

3. ❌ Context Window Problem (engine.py line 839)
   • LLM receives full OCR (~24KB truncated at 24,000 chars)
   • If LLM times out, retries with even shorter context (8KB)
   • Can miss expense tables if they're at end of document
   • No semantic prioritization (billing tables should be prioritized)
   
   Example Flow:
   ```
   [Full OCR 30KB] → Truncate to 24KB → Send to LLM
     ↓ (if timeout)
   [Full OCR 30KB] → Truncate to 8KB → Send to LLM (likely fails again)
     ↓ (if fails)
   [Use heuristic fallback]  ← Currently active for your claim
   ```

4. ❌ No Confidence/Audit Trail
   • Discarded fields not tracked anywhere
   • Can't explain to user why consumables disappeared
   • No visibility into which extraction method was used (LLM vs heuristic)
   • Audit impossible

CURRENT OCR & EXTRACTION STACK
─────────────────────────────────────────────────────────────────────────────

What's Actually Running:
  
  OCR Engine:
    • PaddleOCR-VL (smart, markdown output): DISABLED (enable_paddle_vl=False)
    • Classic PaddleOCR (raw text only): ACTIVE ← Current choice
    • Fallback: Tesseract
    
  Parser Extraction:
    • Structured LLM (Ollama): Tries to call, but endpoint unavailable
    • LayoutLMv3 (transformer model): Not available
    • Heuristic-v2 (regex patterns): ACTIVE ← Currently used for your claim
    
  Field Mapping:
    • Hard-coded _EXPENSE_CATEGORY_MAP in engine.py ← The problem
    
  Report Generation:
    • Hard-coded 5-field canonical in main.py ← Loss point
    • No templates, no configuration

Why It Matters:
  All three are suboptimal for medical claims:
  • Classic OCR: Doesn't detect table structure → loses layout information
  • Heuristic: Works but brittle (missing 1 keyword = field lost)
  • Hard-coded canonical: Intentional but inflexible (loses consumables)


═════════════════════════════════════════════════════════════════════════════
PROPOSED SOLUTION: 4-PHASE TRANSITION TO DYNAMIC SYSTEM
═════════════════════════════════════════════════════════════════════════════

PHASE 1: Dynamic Category Mapping (Week 1) — HIGH IMPACT
─────────────────────────────────────────────────────────────────────────────

Replace hard-coded dict with config file:

  BEFORE (Hard-coded, can't change without code):
  ```python
  # services/parser/app/engine.py line 1778
  _EXPENSE_CATEGORY_MAP = {
      "lab": "investigation_charges",
      "laboratory": MISSING,              # ← FIX: Add this
      "consumable": "consumables",
      # 30+ more
  ```
  
  AFTER (Config-driven, easy to customize):
  ```yaml
  # services/parser/app/categories.yaml (NEW FILE)
  investigation_charges:
    keywords:
      - "investigation"
      - "diagnostic"
      - "lab"
      - "laboratory"                      # ← Now just add to YAML
      - "blood test"
      - "pathology"
      - "radiology"
  
  consumables:
    keywords:
      - "consumable"
      - "disposable"
      - "implant"
      - "stent"
      - "catheter"
  ```
  
  Engine loads config at runtime:
  ```python
  # services/parser/app/category_loader.py (NEW)
  config = CategoryConfig("categories.yaml")
  canonical_field = config.get_canonical_field("laboratory")  # → investigation_charges
  ```

RESULTS:
  ✅ "laboratory" now recognized
  ✅ Easy to add keywords (edit YAML, no code change)
  ✅ Non-engineers can maintain categories
  ✅ Confidence scores per category
  ✅ Validation rules per category
  ✅ Zero code risk (config-driven)


PHASE 2: Dynamic Report Templates (Week 2) — HIGH IMPACT
─────────────────────────────────────────────────────────────────────────────

Replace hard-coded 5-field canonical with configurable templates:

  BEFORE (Hard-coded for all use cases):
  ```python
  # services/submission/app/main.py line 362
  if hospital_bill_subtotals:
      canonical = [
          ("room_charges", "Room Charges"),
          ("investigation_charges", "Diagnostics & Investigations"),
          ("surgery_charges", "Surgery Charges"),
          ("consultation_charges", "Consultation Charges"),
          ("pharmacy_charges", "Pharmacy & Consumables"),  # ← Only 5
      ]  # ← Always same, loses consumables
      expenses = [build from canonical]
  ```
  
  AFTER (Multiple templates, template-driven selection):
  ```yaml
  # services/submission/app/report_templates.yaml (NEW FILE)
  templates:
    hospital_bill_standard:
      trigger: "hospital_bill_subtotals found"
      fields:
        - room_charges
        - investigation_charges
        - surgery_charges
        - consultation_charges
        - pharmacy_charges
    
    comprehensive:
      trigger: "no hospital_bill_subtotals OR explicit_request"
      fields:
        - room_charges
        - consultation_charges
        - pharmacy_charges
        - investigation_charges
        - surgery_charges
        - surgeon_fees
        - anaesthesia_charges
        - ot_charges
        - consumables              # ← NOW INCLUDED
        - nursing_charges
        - icu_charges
        - ambulance_charges
        - misc_charges
    
    insurance_company_a:
      trigger: "claim.insurance_provider == 'Insurance A'"
      fields:  [room_charges, surgery_charges, pharmacy_charges, investigation_charges]
    
    insurance_company_b:
      trigger: "claim.insurance_provider == 'Insurance B'"
      fields:  [ALL 20 categories]
    
    audit_template:
      trigger: "user requests audit"
      fields: "ALL"
      include_confidence_scores: true
      include_extraction_method: true
      include_validation_errors: true
  ```
  
  Engine selects template at runtime:
  ```python
  # services/submission/app/template_loader.py (NEW)
  template = select_report_template(claim_context)
  # Result: comprehensive template selected by default
  
  for field in template.fields:
      if field in parsed_fields:
          expenses.append(field)  # ← All fields can be included now
  ```

RESULTS:
  ✅ Consumables no longer automatically dropped
  ✅ Different templates for different insurance companies
  ✅ Audit reports show complete breakdown + confidence
  ✅ Easy to add new templates (edit YAML)
  ✅ Backward compatible (hospital_bill_standard template for legacy)
  ✅ Zero code risk (config-driven)


PHASE 3: Confidence Scoring & Semantic LLM (Week 3) — MEDIUM TERM
─────────────────────────────────────────────────────────────────────────────

Address context window problem by semantic prioritization:

  BEFORE (Dumb truncation, loses end of document):
  ```python
  raw_text = load_all_ocr(ocr_pages)  # 30KB
  if len(raw_text) > 24000:
      raw_text = raw_text[:24000]  # ← BRUTAL TRUNCATE
  prompt = f"Extract data from:\n{raw_text}"
  llm_result = call_llm(prompt)
  ```
  
  AFTER (Smart truncation, prioritizes important sections):
  ```python
  ocr_text = load_all_ocr(ocr_pages)  # 30KB
  
  # Semantic routing: Categorize each line
  sections = {
      "demographics": [],    # low priority
      "clinical": [],        # medium priority
      "billing": [],         # HIGH priority ← Send to LLM
      "other": []
  }
  
  for line in ocr_text.split("\n"):
      if matches_demographics_pattern(line):
          sections["demographics"].append(line)
      elif matches_clinical_pattern(line):
          sections["clinical"].append(line)
      elif matches_billing_pattern(line):  # Charges, amounts, totals
          sections["billing"].append(line)
  
  # Build prompt prioritizing billing
  prompt_text = sections["billing"] + sections["clinical"]
  # Only include demographics if space remains
  if room_in_context:
      prompt_text += sections["demographics"]
  
  # Now context is small (~4-6KB), safe from hallucination
  llm_result = call_llm(prompt_text)  # ← No timeout, no hallucination
  ```
  
  Also: Add confidence scores to every extracted field:
  ```python
  # Result includes confidence
  field_result = {
      "field_name": "surgery_charges",
      "field_value": 120000,
      "confidence": 0.95,              # ← NEW
      "extraction_method": "heuristic-v2",  # ← NEW
      "source_document": "page 5"      # ← NEW
  }
  ```

RESULTS:
  ✅ LLM contexts reduced from 24KB to ~4KB
  ✅ Fewer timeouts, less hallucination
  ✅ Per-document extraction possible (even smaller)
  ✅ Per-extraction confidence tracking
  ✅ Audit trail of why each field was included
  ✅ Can filter by confidence threshold in templates


PHASE 4: Per-Document Extraction (Week 3-4) — ADVANCED
─────────────────────────────────────────────────────────────────────────────

Instead of sending all documents together, extract each separately:

  BEFORE (Multi-doc claims timeout):
  ```
  [Hospital Bill] [Discharge Summary] [Lab Report]
         ↓              ↓                    ↓
  Concatenate all → 30KB total → Send to LLM
                    ❌ TIMEOUT or long-running
  ```
  
  AFTER (Per-doc extraction, merge results):
  ```
  [Hospital Bill]     [Discharge Summary]     [Lab Report]
         ↓                     ↓                        ↓
  ~4KB LLM call    ~2KB LLM call         ~3KB LLM call
  ✓ Fast, safe     ✓ Fast, safe         ✓ Fast, safe
         ↓                     ↓                        ↓
  Merge results (deduplicates, validates)
         ↓
  [Complete extraction with high confidence]
  ```

RESULTS:
  ✅ Individual doc timeouts won't affect entire claim
  ✅ Doc-specific extraction (hospital bill != lab report)
  ✅ Fine-grained fallback (doc1 succeeds, doc2 fails, doc3 succeeds)
  ✅ Much smaller context per call


═════════════════════════════════════════════════════════════════════════════
IMPLEMENTATION TIMELINE & EFFORT
═════════════════════════════════════════════════════════════════════════════

Phase   Task                                  Effort   Risk   Timeline  Owner
─────────────────────────────────────────────────────────────────────────────────────
1       Create categories.yaml config         2 days   LOW    Week 1    Backend
        Create category_loader.py              
        Update engine.py to load config       
        Add "laboratory" keyword to config    
        
2       Create report_templates.yaml          3 days   LOW    Week 2    Backend
        Create template_loader.py             
        Update main.py to use templates       
        Map templates to claim context        
        
3       Add confidence to ParsedField DB      1 day    LOW    Week 2    DB + Backend
        Implement semantic-aware truncation  2 days   MED    Week 3    Backend
        Update _build_structured_prompt()     
        
4       Per-document extraction refactor      2 days   MED    Week 3    Backend
        Doc-type-specific schemas            
        Merging logic for multi-doc claims   
        
TOTAL:  ~12-14 days development work, mostly config-driven (LOW-MEDIUM RISK)

TESTING REQUIREMENTS (1 week):
  • Unit tests for category_loader.py
  • Unit tests for template_loader.py  
  • Integration tests for full pipeline
  • Regression tests (ensure backward compatibility)
  • Manual testing with existing claims
  • Performance testing (config loading < 10ms)
  • Deployment to staging environment

TOTAL PROJECT: 3-4 weeks including testing


═════════════════════════════════════════════════════════════════════════════
QUESTIONS FOR DEVELOPERS & GTP MODELS
═════════════════════════════════════════════════════════════════════════════

Frame the Problem:

"We have a document processing pipeline:
  [OCR] → [Parser] → [Report Generator]
  
Three fields are disappearing: surgery charges, laboratory charges, consumables.
We traced the loss to:
  1. Missing keyword in hard-coded category map ("laboratory" not mapped)
  2. Hard-coded 5-field canonical report template (consumables not in list)
  3. Context window truncation at LLM stage (not all data reaches LLM)

Root cause: Design assumes fixed schemas, doesn't account for:
  • New keywords → need code deployment
  • Different report templates per user → hard-coded for all
  • Context limits → brutal truncation without semantic priority

Our Solution:
  • Replace hard-coded maps with config files (YAML)
  • Replace fixed templates with pluggable templates (selected at runtime)
  • Replace dumb truncation with semantic routing (priority-based)
  • Add confidence tracking throughout pipeline (audit-ready)

Key Question: Is this the right architectural direction?"


Key Discussion Points:

1. **Keywords & Extensibility**
   Ask: "If we need to add a new keyword tomorrow (e.g., 'vascular surgery'),
         should we require a code deployment, or let ops/business edit a config?"
   
   Answer Framework: "Config-driven. Non-engineers should be able to add
                      keywords without involving backend engineers."

2. **Context Window Management**
   Ask: "Our LLM can handle ~8KB context reliably. We have claims with 30KB OCR.
         Should we:
         A) Use a larger model (GPT-4-32K)?
         B) Split documents (per-doc extraction)?
         C) Truncate more aggressively?
         D) Archive old documents (keep only recent)?"
   
   Answer Framework: "B is best (per-doc extraction). D is organizational debt.
                      A has cost/latency tradeoffs, consider as fallback only.
                      C without prioritization just loses data silently."

3. **Template Customization**
   Ask: "Insurance Company A wants consumables hidden from reports,
         Company B wants consumables always shown,
         and C wants consumables shown only if > 10K.
         How do we handle this?"
   
   Answer Framework: "Template system with per-insurer customization.
                      Base templates (standard, comprehensive, audit)
                      inherited + overridden per company.
                      Same mechanism also supports internal A/B testing."

4. **Confidence & Audit**
   Ask: "When a field is dropped from a report (e.g., consumables),
         should we:
         A) Show an audit note?
         B) Mark it as 'extracted but not shown'?
         C) Just hide it completely?"
         D) Let the template decide?"
   
   Answer Framework: "D. Template controls. Audit template shows everything.
                      Summary template hides (but audit section available).
                      Default: Show what's extracted, confidence scores visible."


═════════════════════════════════════════════════════════════════════════════
QUICK REFERENCE: FILES TO CREATE & MODIFY
═════════════════════════════════════════════════════════════════════════════

Phase 1 (Week 1):
  CREATE:  services/parser/app/categories.yaml
  CREATE:  services/parser/app/category_loader.py
  MODIFY:  services/parser/app/config.py (add config path)
  MODIFY:  services/parser/app/engine.py (update _categorise_expense function)

Phase 2 (Week 2):
  CREATE:  services/submission/app/report_templates.yaml
  CREATE:  services/submission/app/template_loader.py
  MODIFY:  services/submission/app/main.py (use templates instead of canonical)

Phase 3 (Week 3):
  MODIFY:  Database schema (add confidence column to ParsedField)
  MODIFY:  services/parser/app/engine.py (semantic-aware truncation)
  CREATE:  services/parser/app/semantic_router.py

Phase 4 (Week 4):
  MODIFY:  services/parser/app/engine.py (per-document extraction)
  CREATE:  Per-doc-specific schemas

Detailed implementation code provided in: implementation_roadmap_dynamic_fields.md


═════════════════════════════════════════════════════════════════════════════
DECISION POINTS FOR STAKEHOLDERS
═════════════════════════════════════════════════════════════════════════════

Decision 1: Enable PaddleOCR-VL?
  Current: Disabled (enable_paddle_vl=False)
  
  Benefit: Better table detection, structured markdown output
  Risk:    Requires model download (~500MB), might be slow on CPU-only
  
  Recommendation: Enable in dev/staging first, benchmark performance

Decision 2: Semantic truncation + per-doc or per-section?
  Option A: Per-section (billing only to LLM, demographics to heuristic)
  Option B: Per-document (whole hospital bill to LLM, discharge separate)
  Option C: Both (per-doc, then per-section within each doc)
  
  Recommendation: Option C (most reliable, incremental complexity)

Decision 3: Default template for end user?
  Option A: "hospital_bill_standard" (5 field, matches printed bill)
  Option B: "comprehensive" (all extracted fields, more transparent)
  
  Recommendation: Option B (better, less data loss) + add config flag
                  to let users choose

Decision 4: Keep hard-coded categories as feature flag?
  Option A: Immediate switch to config-driven (no fallback)
  Option B: Keep both (config + hard-coded), pick one
  Option C: Keep hard-coded in code, load config as override
  
  Recommendation: Option C (minimal breaking change, easier rollback)


═════════════════════════════════════════════════════════════════════════════
MEASURABLE SUCCESS CRITERIA
═════════════════════════════════════════════════════════════════════════════

After Phase 1 (Categories):
  ✅ "laboratory" keyword recognized → investigation_charges field extracted
  ✅ Can add new keywords without deployment
  ✅ Category configuration loaded from categories.yaml

After Phase 2 (Templates):
  ✅ Consumables appears in comprehensive report
  ✅ Hospital bill standard template still works (backward compatible)
  ✅ Can create new templates without code change
  ✅ Template selection based on claim context

After Phase 3 (Confidence):
  ✅ All extracted fields have confidence score
  ✅ LLM timeout rate drops by >50%
  ✅ Can filter report by confidence threshold

After Phase 4 (Per-Doc):
  ✅ Multi-document claims no longer timeout
  ✅ Per-document extraction succeeds even if one doc fails
  ✅ Context-per-doc <8KB

OVERALL SUCCESS:
  ✅ No more silent field loss
  ✅ Consumables + nursing + ICU charges now visible in reports
  ✅ Easy to add keywords, templates, rule changes (config-driven)
  ✅ Full audit trail of what was extracted, confidence, why discarded
  ✅ Non-engineers can customize without backend involvement
  ✅ Reduced LLM errors/hallucinations


═════════════════════════════════════════════════════════════════════════════

DOCUMENTS PROVIDED WITH THIS ANALYSIS:

1. comprehensive_ocr_field_flow_technical_memo.md
   → Full technical breakdown, code references, all eight parts

2. ocr_field_loss_quick_reference.md
   → Visual flowchart, loss mechanisms, quick comparison table

3. implementation_roadmap_dynamic_fields.md
   → Detailed code implementations, step-by-step migration guide

4. architecture_comparison_current_vs_proposed.md
   → Side-by-side comparison, complexity matrix, stakeholder questions

5. EXECUTIVE_SUMMARY.md (this file)
   → High-level overview, decision points, success criteria

Use these to:
  • Brief stakeholders on the problem and solution
  • Ask targeted questions to GPT models or other teams
  • Plan implementation sprints
  • Set up code reviews
  • Measure success


NEXT STEPS:
─────────────────────────────────────────────────────────────────────────────

1. Review this executive summary with team
2. Discuss decision points (PaddleOCR-VL? Per-doc or per-section? Templates?)
3. Prioritize phases based on resource availability
4. Assign work & estimate timeline
5. Create implementation tickets
6. Bring in 1-2 other developers for peer feedback
7. Start Phase 1 (highest impact, lowest risk)

Questions? Contact the analysis author or refer to the detailed documents.

