================================================================================
IMPLEMENTATION ROADMAP: Making Field Mapping & Report Generation Dynamic
================================================================================

Current State: Hard-coded field lists, fixed 5-item canonical, no configurability
Target State: Config-driven categories, pluggable templates, confidence-based selection
Effort: 3-4 weeks across parser + submission services


═══════════════════════════════════════════════════════════════════════════════
PHASE 1: DYNAMIC CATEGORY MAPPING (Week 1)
═══════════════════════════════════════════════════════════════════════════════

PROBLEM
─────────────────────────────────────────────────────────────────────────────
Current: Hard-coded _EXPENSE_CATEGORY_MAP in services/parser/app/engine.py
```python
_EXPENSE_CATEGORY_MAP = {
    "lab": "investigation_charges",              # "laboratory" NOT here
    "laboratory": MISSING,                       # ← FIX THIS
    "consumable": "consumables",
    "disposable": "consumables",
    "implant": "consumables",
    # ... 30+ more mappings
}
```

If you add "laboratory": "investigation_charges", it's another hard-code.
Need: YAML configuration file so non-engineers can add keywords.


SOLUTION 1A: Create categories.yaml config file
─────────────────────────────────────────────────────────────────────────────

File: services/parser/app/categories.yaml

```yaml
# Expense Category Keyword Mappings
# Format: Canonical field name → Keywords that trigger this category

investigation_charges:
  canonical_field: "investigation_charges"
  display_label: "Diagnostics & Investigations"
  keywords:
    - "investigation"
    - "diagnostic"
    - "lab"
    - "laboratory"              # ← ADD THIS
    - "blood test"
    - "pathology"
    - "radiology"
    - "ct scan"
    - "ultrasound"
    - "ecg"
    - "x-ray"
  confidence: 0.95              # Used for field validation
  validation_rules:
    - "amount > 0"
    - "amount < 5000000"        # Sanity check

surgery_charges:
  canonical_field: "surgery_charges"
  display_label: "Surgery Charges"
  keywords:
    - "surgery"
    - "surgical"
    - "operation"
    - "procedure"
    - "operative"
    - "surgical procedure"
    - "emergency procedure"
  confidence: 0.95
  validation_rules:
    - "amount > 0"

consumables:
  canonical_field: "consumables"
  display_label: "Medical & Surgical Consumables"
  keywords:
    - "consumable"
    - "disposable"
    - "implant"
    - "implants"
    - "stent"
    - "catheter"
    - "dressing"
    - "gauze"
    - "suture"
    - "pacemaker"
  confidence: 0.90
  validation_rules:
    - "amount > 0"

room_charges:
  canonical_field: "room_charges"
  display_label: "Room Charges"
  keywords:
    - "room"
    - "bed"
    - "boarding"
    - "accommodation"
    - "icu"
    - "room rent"
    - "bed charge"
  confidence: 0.95
  validation_rules:
    - "amount > 0"

pharmacy_charges:
  canonical_field: "pharmacy_charges"
  display_label: "Pharmacy & Medicines"
  keywords:
    - "pharmacy"
    - "medicine"
    - "drug"
    - "medication"
    - "prescription"
  confidence: 0.90
  validation_rules:
    - "amount > 0"

nursing_charges:
  canonical_field: "nursing_charges"
  display_label: "Nursing & Support Services"
  keywords:
    - "nursing"
    - "nurse"
    - "nursing care"
  confidence: 0.85
  validation_rules:
    - "amount > 0"

consultation_charges:
  canonical_field: "consultation_charges"
  display_label: "Consultation Charges"
  keywords:
    - "consultation"
    - "doctor"
    - "physician"
    - "specialist"
    - "consultation fee"
  confidence: 0.90
  validation_rules:
    - "amount > 0"

icu_charges:
  canonical_field: "icu_charges"
  display_label: "ICU Charges"
  keywords:
    - "icu"
    - "intensive care"
  confidence: 0.95
  validation_rules:
    - "amount > 0"

ambulance_charges:
  canonical_field: "ambulance_charges"
  display_label: "Ambulance Charges"
  keywords:
    - "ambulance"
    - "transport"
    - "patient transport"
  confidence: 0.85
  validation_rules:
    - "amount > 0"

# Add more as needed
```


SOLUTION 1B: Load and use categories from YAML
─────────────────────────────────────────────────────────────────────────────

File: services/parser/app/category_loader.py (NEW FILE)

```python
import yaml
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel

class CategoryKeywords(BaseModel):
    canonical_field: str
    display_label: str
    keywords: List[str]
    confidence: float = 0.90
    validation_rules: List[str] = []

class CategoryConfig:
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent / "categories.yaml"
        
        with open(config_path) as f:
            raw_config = yaml.safe_load(f)
        
        self.categories: Dict[str, CategoryKeywords] = {}
        for cat_name, cat_data in raw_config.items():
            self.categories[cat_name] = CategoryKeywords(**cat_data)
        
        # Build keyword → canonical_field reverse map
        self.keyword_map: Dict[str, str] = {}
        for cat_name, cat_config in self.categories.items():
            for keyword in cat_config.keywords:
                self.keyword_map[keyword.lower()] = cat_config.canonical_field
    
    def get_canonical_field(self, keyword: str) -> Optional[str]:
        """Get the canonical field for a keyword."""
        return self.keyword_map.get(keyword.lower())
    
    def get_confidence(self, canonical_field: str) -> float:
        """Get confidence score for a canonical field."""
        for cat in self.categories.values():
            if cat.canonical_field == canonical_field:
                return cat.confidence
        return 0.5  # Default low confidence if not found
    
    def validate_field(self, canonical_field: str, value: float) -> bool:
        """Apply validation rules for field."""
        for cat in self.categories.values():
            if cat.canonical_field != canonical_field:
                continue
            for rule in cat.validation_rules:
                # Simple rule evaluation: "amount > 0" → value > 0
                if not self._eval_rule(rule, value):
                    return False
        return True
    
    @staticmethod
    def _eval_rule(rule: str, amount: float) -> bool:
        """Evaluate a simple validation rule."""
        rule = rule.replace("amount", str(amount))
        try:
            return eval(rule)
        except:
            return True  # If rule fails, don't invalidate

# Global instance
_category_config: Optional[CategoryConfig] = None

def get_category_config() -> CategoryConfig:
    global _category_config
    if _category_config is None:
        _category_config = CategoryConfig()
    return _category_config

def reload_categories(config_path: str = None):
    """Reload categories at runtime (for testing)."""
    global _category_config
    _category_config = CategoryConfig(config_path)
```

File: services/parser/app/config.py (UPDATE)

```python
# Add to ParserConfig class
category_config_path: str = "services/parser/app/categories.yaml"
```


SOLUTION 1C: Replace hard-coded map with dynamic loader in engine.py
─────────────────────────────────────────────────────────────────────────────

File: services/parser/app/engine.py (REPLACE section around line 1778)

OLD CODE (REMOVE):
```python
_EXPENSE_CATEGORY_MAP = {
    "lab": "investigation_charges",
    "laboratory": "investigation_charges",        # Hardcoded
    "consumable": "consumables",
    # ... 30 more lines
}

def _categorise_expense(label: str) -> Optional[str]:
    """Map user-visible label to canonical category."""
    label_lower = label.lower()
    for keyword, category in _EXPENSE_CATEGORY_MAP.items():
        if keyword in label_lower:
            return category
    return None
```

NEW CODE (REPLACE WITH):
```python
from .category_loader import get_category_config

def _categorise_expense(label: str) -> Optional[str]:
    """Map user-visible label to canonical category using config."""
    label_lower = label.lower()
    category_config = get_category_config()
    
    # Try exact keyword matches first
    for keyword in label_lower.split():
        canonical_field = category_config.get_canonical_field(keyword)
        if canonical_field:
            return canonical_field
    
    # Try substring matches
    for keyword in category_config.keyword_map.keys():
        if keyword in label_lower:
            return category_config.keyword_map[keyword]
    
    return None
```


RESULT OF PHASE 1
─────────────────────────────────────────────────────────────────────────────
✅ "laboratory" keyword now recognized
✅ Easy to add new keywords without code change
✅ Confidence scores attached to each category
✅ Validation rules per category
✅ Non-engineers can update categories.yaml


═══════════════════════════════════════════════════════════════════════════════
PHASE 2: DYNAMIC REPORT TEMPLATES (Week 2)
═══════════════════════════════════════════════════════════════════════════════

PROBLEM
─────────────────────────────────────────────────────────────────────────────
Current: Hard-coded 5-item canonical list in submission/app/main.py line 362-367
```python
if hospital_bill_subtotals:
    canonical = [
        ("room_charges", "Room Charges"),           # ← Hard-coded
        ("investigation_charges", "Diagnostics & Investigations"),
        ("surgery_charges", "Surgery Charges"),
        ("consultation_charges", "Consultation Charges"),
        ("pharmacy_charges", "Pharmacy & Consumables"),
    ]
    # Replace ALL parsed fields with only these 5 ← LOSSY!
    expenses = [build from canonical]
```

Problem:
- Consumables always dropped (even if extracted)
- Insurance company A wants 5 fields, company B wants 10
- User X wants audit trail of what was discarded, user Y wants clean report
- No flexibility


SOLUTION 2A: Create report_templates.yaml
─────────────────────────────────────────────────────────────────────────────

File: services/submission/app/report_templates.yaml

```yaml
# Report Template Definitions
# Each template specifies which fields to include in the final report

templates:
  hospital_bill_standard:
    description: "5-field standard when printed subtotals found"
    trigger: "hospital_bill_subtotals found"
    fields:
      - room_charges
      - investigation_charges
      - surgery_charges
      - consultation_charges
      - pharmacy_charges
    include_discarded_fields_section: false
    section_heading: "Expense Summary"
    sort_by: "amount desc"
  
  comprehensive:
    description: "All extracted fields, even if not in printed subtotals"
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
      - consumables                    # ← INCLUDED
      - nursing_charges
      - icu_charges
      - ambulance_charges
      - misc_charges
    include_discarded_fields_section: false
    section_heading: "Complete Expense Breakdown"
    sort_by: "amount desc"
  
  insurance_company_a:
    description: "Template for Insurance Company A (conservative)"
    trigger: "claim.insurance_provider == 'Insurance A'"
    fields:
      - room_charges
      - surgery_charges
      - pharmacy_charges
      - investigation_charges
    include_discarded_fields_section: true
    discarded_section_title: "Other Charges (Not Covered)"
    confidence_minimum: 0.85           # Only include high-confidence fields
    section_heading: "Covered Expenses"
    sort_by: "canonical"               # Order by template definition
  
  insurance_company_b:
    description: "Template for Insurance Company B (comprehensive)"
    trigger: "claim.insurance_provider == 'Insurance B'"
    fields:
      - room_charges
      - consultation_charges
      - pharmacy_charges
      - investigation_charges
      - surgery_charges
      - surgeon_fees
      - anaesthesia_charges
      - ot_charges
      - consumables
      - nursing_charges
      - icu_charges
      - ambulance_charges
    include_discarded_fields_section: true
    confidence_minimum: 0.80
    section_heading: "All Expenses"
    sort_by: "amount desc"
  
  audit:
    description: "Full audit report - all fields with confidence scores"
    trigger: "user requests detailed audit"
    fields:
      - "ALL"                          # Special: include everything
    include_discarded_fields_section: true
    show_confidence_scores: true
    show_extraction_method: true       # LLM vs heuristic
    show_field_source: true            # Which document
    include_validation_errors: true
    section_heading: "Complete Audit Report"
    sort_by: "extraction_confidence desc"
```


SOLUTION 2B: Template loader and selection logic
─────────────────────────────────────────────────────────────────────────────

File: services/submission/app/template_loader.py (NEW FILE)

```python
import yaml
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel

class ReportTemplate(BaseModel):
    name: str  # Key from YAML
    description: str
    trigger: str  # When to use this template
    fields: List[str]
    include_discarded_fields_section: bool = False
    discarded_section_title: Optional[str] = None
    confidence_minimum: float = 0.0
    section_heading: str = "Expenses"
    sort_by: str = "amount desc"  # "amount desc", "canonical", etc.
    show_confidence_scores: bool = False
    show_extraction_method: bool = False
    show_field_source: bool = False
    include_validation_errors: bool = False

class ReportTemplateConfig:
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent / "report_templates.yaml"
        
        with open(config_path) as f:
            raw_config = yaml.safe_load(f)
        
        self.templates: Dict[str, ReportTemplate] = {}
        for template_name, template_data in raw_config.get("templates", {}).items():
            template_data["name"] = template_name
            self.templates[template_name] = ReportTemplate(**template_data)
    
    def select_template(self, claim: Dict, explicit_template: Optional[str] = None) -> ReportTemplate:
        """Select template based on claim context or explicit request."""
        if explicit_template:
            return self.templates.get(explicit_template) or self.templates["comprehensive"]
        
        # Try to match trigger conditions
        for template in self.templates.values():
            if self._matches_trigger(template.trigger, claim):
                return template
        
        # Default fallback
        return self.templates.get("comprehensive") or list(self.templates.values())[0]
    
    @staticmethod
    def _matches_trigger(trigger: str, claim: Dict) -> bool:
        """Check if trigger condition matches claim context."""
        # Examples:
        #   "hospital_bill_subtotals found" → check if subtotals exist
        #   "claim.insurance_provider == 'Insurance A'" → check provider
        
        if "hospital_bill_subtotals found" in trigger:
            return bool(claim.get("hospital_bill_subtotals"))
        
        if "no hospital_bill_subtotals" in trigger:
            return not bool(claim.get("hospital_bill_subtotals"))
        
        if "claim." in trigger:
            # Simple evaluation for claim.field == value
            # e.g., "claim.insurance_provider == 'Insurance A'"
            try:
                # Replace claim.field with actual values
                condition = trigger
                for key, value in claim.items():
                    condition = condition.replace(f"claim.{key}", f"'{value}'")
                return eval(condition)
            except:
                return False
        
        return False

# Global instance
_template_config: Optional[ReportTemplateConfig] = None

def get_template_config() -> ReportTemplateConfig:
    global _template_config
    if _template_config is None:
        _template_config = ReportTemplateConfig()
    return _template_config

def select_report_template(claim: Dict, explicit_template: Optional[str] = None) -> ReportTemplate:
    config = get_template_config()
    return config.select_template(claim, explicit_template)
```


SOLUTION 2C: Update submission/app/main.py to use templates
─────────────────────────────────────────────────────────────────────────────

File: services/submission/app/main.py (REPLACE section around line 340-376)

OLD CODE (REMOVE):
```python
if hospital_bill_subtotals:
    canonical = [
        ("room_charges", "Room Charges"),
        ("investigation_charges", "Diagnostics & Investigations"),
        ("surgery_charges", "Surgery Charges"),
        ("consultation_charges", "Consultation Charges"),
        ("pharmacy_charges", "Pharmacy & Consumables"),
    ]
    anchored_expenses: List[Dict[str, Any]] = []
    for key, label in canonical:
        val = hospital_bill_subtotals.get(key)
        if val is None or val <= 0:
            continue
        anchored_expenses.append({"category": label, "amount": float(val)})
    if anchored_expenses:
        expenses = anchored_expenses
        expense_total = sum(e["amount"] for e in expenses)
```

NEW CODE (REPLACE WITH):
```python
from .template_loader import select_report_template

# Select template based on claim context
claim_context = {
    "hospital_bill_subtotals": bool(hospital_bill_subtotals),
    "insurance_provider": parsed.get("insurance_company", ""),
    "num_documents": len(docs),
}
selected_template = select_report_template(claim_context)

# Filter expenses based on template
filtered_expenses: List[Dict[str, Any]] = []
discarded_expenses: List[Dict[str, Any]] = []

if "ALL" in selected_template.fields:
    # Include all fields
    filtered_expenses = expenses
else:
    # Filter to template fields only
    for expense in expenses:
        category = expense.get("category")
        field_key = _expense_category_to_field_key(category)  # New helper
        
        if field_key in selected_template.fields:
            # Check confidence threshold
            confidence = _field_confidence_map.get(field_key, 0.9)
            if confidence >= selected_template.confidence_minimum:
                filtered_expenses.append(expense)
            else:
                discarded_expenses.append((expense, "low_confidence"))
        else:
            discarded_expenses.append((expense, "not_in_template"))

# Use selected template settings
if selected_template.show_confidence_scores:
    for exp in filtered_expenses:
        field_key = _expense_category_to_field_key(exp.get("category"))
        exp["confidence"] = _field_confidence_map.get(field_key, 0.9)

expenses = filtered_expenses
expense_total = sum(e["amount"] for e in expenses)
```

NEW: Add to handle discarded fields in report
```python
# In the report building section
if selected_template.include_discarded_fields_section and discarded_expenses:
    report["discarded_expenses_section"] = {
        "title": selected_template.discarded_section_title or "Not Included",
        "items": [
            {
                "category": exp[0].get("category"),
                "amount": exp[0].get("amount"),
                "reason": exp[1]  # "not_in_template", "low_confidence"
            }
            for exp in discarded_expenses
        ]
    }
```


RESULT OF PHASE 2
─────────────────────────────────────────────────────────────────────────────
✅ Consumables now included in comprehensive template
✅ Different templates for different use cases
✅ Insurance company can specify their template
✅ Audit reports show what was discarded and why
✅ No code changes needed to add new templates


═══════════════════════════════════════════════════════════════════════════════
PHASE 3: CONFIDENCE SCORING & SEMANTIC TRUNCATION (Week 3)
═══════════════════════════════════════════════════════════════════════════════

(See comprehensive_ocr_field_flow_technical_memo.md for detailed implementation)

QUICK SUMMARY:
1. Add confidence metadata to extracted fields
2. Implement semantic-aware LLM truncation (prioritize billing sections)
3. Per-document extraction by default


═══════════════════════════════════════════════════════════════════════════════
MIGRATION CHECKLIST
═══════════════════════════════════════════════════════════════════════════════

PHASE 1 Deployment:
  ☐ Create services/parser/app/categories.yaml
  ☐ Create services/parser/app/category_loader.py
  ☐ Update services/parser/app/config.py
  ☐ Update services/parser/app/engine.py (_categorise_expense function)
  ☐ Add "laboratory" keyword to investigation_charges in categories.yaml
  ☐ Test: Verify "laboratory" now maps to investigation_charges
  ☐ Commit & deploy

PHASE 2 Deployment:
  ☐ Create services/submission/app/report_templates.yaml
  ☐ Create services/submission/app/template_loader.py
  ☐ Update services/submission/app/main.py (use templates instead of hard-coded canonical)
  ☐ Add template selection logic based on claim context
  ☐ Test: Verify consumables appears in comprehensive template
  ☐ Test: Verify hospital_bill_standard still works for backward compatibility
  ☐ Commit & deploy

PHASE 3 Deployment:
  ☐ Add confidence scores to ParsedField table (new column)
  ☐ Implement semantic-aware LLM truncation
  ☐ Switch to per-document extraction by default
  ☐ Test: LLM should no longer timeout on large documents
  ☐ Commit & deploy

VERIFICATION:
  ☐ Run integration tests for field extraction
  ☐ Run integration tests for report generation
  ☐ Test with existing claims to verify backward compatibility
  ☐ Test with new edge cases (large multi-doc claims, unusual bill formats)
  ☐ Performance testing (template selection should < 10ms)


═══════════════════════════════════════════════════════════════════════════════
METRICS TO TRACK
═══════════════════════════════════════════════════════════════════════════════

Before & After:
1. Field extraction completeness: "laboratory" charge recognition (should go from 0% → 100%)
2. Report field count: average fields in report (5 → 8+ with comprehensive template)
3. LLM timeout rate: (should drop with semantic truncation)
4. Confidence distribution: % high/medium/low confidence fields
5. Template selection distribution: which templates are used most


═══════════════════════════════════════════════════════════════════════════════
DISCUSSION POINTS FOR TEAM
═══════════════════════════════════════════════════════════════════════════════

"We're implementing dynamic field mapping and report templating to solve:
1. Fixed 5-field canonical list loses data (consumables, nursing, etc.)
2. Keyword mapping not extensible (need to add 'laboratory' each time)
3. Different use cases need different reports (insurance A vs B, audit vs summary)

Old approach: Hard-coded Python dicts → Hard to change, error-prone, lossy
New approach: Config files (YAML) → Easy to customize, transparent, flexible

This decouples reporting policy from code, which means:
- Non-engineers can modify templates (insurance company policies)
- Easy to add new categories without code change
- Audit trail of what was discarded and why
- Per-use-case report generation"

