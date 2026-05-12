# PARSER REBUILD: MODULES & CHANGES SUMMARY

## NEW MODULES TO CREATE (7 files)

### 1. `services/parser/app/zoning_engine.py` ~300 lines

**Purpose:** Detect logical document regions (zones) before extraction

**Key Functions:**
- `detect_zones(tokens: List[Token]) -> List[Zone]` — Main entry point
- `find_vertical_gaps(tokens) -> List[float]` — Find section boundaries
- `find_heading_anchors(tokens) -> Dict[str, List[float]]` — Locate section starts
- `cluster_by_y(tokens, tolerance=5) -> List[List[Token]]` — Group horizontal rows
- `cluster_by_x(x_positions, tolerance=10) -> List[Tuple[float, float]]` — Find column boundaries
- `is_inside_bbox(token, bbox) -> bool` — Check token containment

**Output Type:**
```python
@dataclass
class Zone:
    section_type: str  # "patient_info", "expense_table", "diagnosis_block", etc.
    bbox: [x0, y0, x1, y1]
    tokens: List[Token]
    confidence: float  # 0.0-1.0
    metadata: dict
```

---

### 2. `services/parser/app/section_classifier.py` ~200 lines

**Purpose:** Classify zones into extraction categories AFTER zoning

**Key Functions:**
- `classify_zone(zone: Zone) -> str` — Determine zone type
- `classify_table_type(zone: Zone) -> str` — Distinguish table types
- `has_aligned_columns(zone) -> bool` — Detect column structure
- `has_repeated_y_alignment(zone, min_rows=3) -> bool` — Detect table rows
- `has_label_colon_pattern(zone) -> bool` — Detect form fields
- `is_block_text(zone) -> bool` — Detect paragraph text

**Output Type:** `zone.classification` field (one of):
- `form_section`
- `expense_table`
- `medication_table`
- `lab_table`
- `diagnosis_block`
- `vitals_block`
- `header`
- `footer`
- `text_block`

---

### 3. `services/parser/app/form_parser.py` ~250 lines

**Purpose:** Extract label-value pairs from form sections (patient, insurance, hospital info)

**Key Functions:**
- `parse_form_section(zone: Zone) -> List[FieldResult]` — Main extraction
- `extract_label_value_pairs(zone: Zone) -> Dict[str, str]` — Find label:value patterns
- `extract_field_by_anchor(zone, anchor_pattern, field_name) -> FieldResult` — Extract specific field
- `get_row_value(row_tokens, anchor_idx) -> str` — Get value after label

**Output Type:**
```python
class FieldResult:
    field_name: str
    field_value: str
    source_bbox: [x0, y0, x1, y1]
    confidence: float  # 0.85-0.95 for form fields
    extractor_name: str  # "form_parser"
```

**Rules:**
- ✓ Extract value from right side of label only
- ✓ Stop at next label or next row
- ✓ One value per label per zone
- ✗ Never scan outside zone boundaries
- ✗ Never merge values across rows

---

### 4. `services/parser/app/table_reconstruction.py` ~300 lines

**Purpose:** Detect rows and columns INSIDE a table zone (local reconstruction)

**Key Functions:**
- `reconstruct_table(zone: Zone) -> List[Dict[str, str]]` — Main reconstruction
- `extract_rows_from_zone(zone) -> List[Row]` — Y-coordinate clustering
- `infer_columns(rows) -> List[Tuple[float, float]]` — X-coordinate clustering
- `assign_tokens_to_cells(rows, column_boundaries) -> List[List[str]]` — Map tokens to cells
- `merge_multiline_cells(cells) -> List[List[str]]` — Handle cells spanning Y

**Output Type:**
```python
[
    {
        "cells": ["Room", "5000"],
        "raw_text": "Room | 5000",
        "row_bbox": [x0, y0, x1, y1]
    },
    {
        "cells": ["Medicine", "2000"],
        "raw_text": "Medicine | 2000",
        "row_bbox": [x0, y0, x1, y1]
    }
]
```

**Rules:**
- ✓ Only process tokens INSIDE zone.bbox
- ✓ Use Y-clustering for row detection
- ✓ Use X-clustering for column detection
- ✓ Handle multiline cells
- ✗ Do NOT require header row
- ✗ Do NOT require all cells filled
- ✗ Do NOT scan outside zone

---

### 5. `services/parser/app/diagnosis_parser.py` ~150 lines

**Purpose:** Extract diagnosis and procedure information from diagnosis blocks

**Key Functions:**
- `parse_diagnosis_block(zone: Zone) -> List[FieldResult]` — Extract diagnoses/procedures
- `extract_diagnosis_items(zone) -> Dict[str, str]` — Parse diagnosis text
- `extract_icd_codes(text) -> Dict[str, str]` — Parse ICD codes if present
- `extract_procedures(zone) -> List[str]` — Extract procedure names/codes

**Output Type:**
```python
[
    FieldResult(field_name="diagnosis", field_value="Type 2 Diabetes Mellitus"),
    FieldResult(field_name="icd_code", field_value="E11.9"),
    FieldResult(field_name="procedure", field_value="Blood glucose monitoring"),
]
```

---

### 6. `services/parser/app/vitals_parser.py` ~150 lines

**Purpose:** Extract vital signs from vitals sections

**Key Functions:**
- `parse_vitals_block(zone: Zone) -> List[FieldResult]` — Extract vitals
- `extract_vital_pair(row_tokens, vital_name) -> FieldResult` — Extract single vital

**Output Type:**
```python
[
    FieldResult(field_name="blood_pressure", field_value="120/80 mmHg"),
    FieldResult(field_name="pulse", field_value="72 bpm"),
    FieldResult(field_name="temperature", field_value="37.2°C"),
]
```

---

### 7. `services/parser/app/table_parser_dispatcher.py` ~150 lines

**Purpose:** Route table zones to appropriate specialized parser

**Key Functions:**
- `parse_table_zone(zone: Zone) -> List[Dict[str, Any]]` — Main dispatcher
- `parse_expense_table(zone) -> List[Dict]` — Extract expense rows
- `parse_medication_table(zone) -> List[Dict]` — Extract medication rows
- `parse_lab_table(zone) -> List[Dict]` — Extract lab result rows
- `parse_generic_table(zone) -> List[Dict]` — Fallback generic extraction

**Flow:**
```
Zone classification (e.g., "expense_table")
  ↓
Route to specialized parser (e.g., parse_expense_table)
  ↓
Use table_reconstruction for local row/column detection
  ↓
Post-process table-specific fields (e.g., validate amounts for expense)
  ↓
Return structured rows
```

---

## UPDATED MODULES (Minimal changes)

### `services/parser/app/field_resolver.py` (Updated)

**Current Status:** Exists, needs update

**Changes:**
- ✓ Keep conflict resolution logic (unchanged)
- ✓ Update `is_valid_field()` with domain validation rules
- ✓ Add confidence-weighted selection (unchanged)
- ✓ Keep provenance tracking (enhanced with source_bbox)

**No major restructuring needed**

---

### `services/parser/app/schema_normalizer.py` (No changes)

**Current Status:** Exists, working

**Changes:** None required
- Accepts resolved fields from field_resolver
- Builds canonical schema
- Ready for new pipeline

---

### `services/parser/app/models.py` (Minor additions)

**Changes:**
- Add `Zone` dataclass
- Add `ResolvedField` dataclass
- Update `FieldResult` (add confidence, source_bbox)
- Keep existing models

---

## MODULES TO REMOVE/DEPRECATE (Will be replaced)

These modules rely on global page reconstruction and will be deprecated after new pipeline is validated:

| Module | Reason | Replaced By |
|--------|--------|-------------|
| `bill_parser.py` | Global row reconstruction | Zoning + table_parser_dispatcher |
| `discharge_parser.py` | Global row reconstruction | Section-specific parsers |
| `prescription_parser.py` | Global table parsing | table_parser_dispatcher + vitals_parser |
| `lab_parser.py` | Global table parsing | table_parser_dispatcher |
| `table_extractor.py` | Global extraction | table_reconstruction.py (local only) |
| `form_extractor.py` | Global field scanning | form_parser.py (zone-based) |
| `layout_analyzer.py` | Global layout analysis | zoning_engine.py |
| `layout_analyzer_lightweight.py` | Unused fallback | Remove |
| `document_classifier.py` | Document-level only | section_classifier.py (zone-level) |

**Note:** Removal happens in Phase 5 after new pipeline is validated.

---

## NEW ENTRY POINT

### `services/parser/app/engine_v2.py` (New)

```python
def parse_document_v2(
    ocr_pages: List[Dict[str, Any]],
    images: Optional[List[Any]] = None
) -> CanonicalClaim:
    """
    New clean pipeline:
    OCR → Zoning → Classification → Local Parsers → Field Resolution → Schema Normalization
    """
```

**Phase-in Strategy:**
1. New `parse_document_v2()` runs in parallel
2. Both versions output to same schema for comparison
3. Once validated, switch router to use v2
4. Keep v1 as fallback initially
5. Remove v1 after 1-2 weeks of production stability

---

## FILE STRUCTURE (After creation)

```
services/parser/app/
├── __init__.py
├── config.py
├── db.py
├── models.py (updated)
├── schemas.py
│
├── (NEW) zoning_engine.py
├── (NEW) section_classifier.py
├── (NEW) form_parser.py
├── (NEW) table_reconstruction.py
├── (NEW) table_parser_dispatcher.py
├── (NEW) diagnosis_parser.py
├── (NEW) vitals_parser.py
│
├── field_resolver.py (updated)
├── schema_normalizer.py (unchanged)
│
├── (OLD, deprecated)
│   ├── bill_parser.py
│   ├── discharge_parser.py
│   ├── prescription_parser.py
│   ├── lab_parser.py
│   ├── table_extractor.py
│   ├── form_extractor.py
│   ├── layout_analyzer.py
│   └── layout_analyzer_lightweight.py
│
├── engine.py (old, kept as v1)
├── (NEW) engine_v2.py
├── document_classifier.py (deprecated)
├── lightweight_ner.py (old, kept)
├── main.py (entry point, will be updated)
└── __pycache__/
```

---

## CONCRETE EXAMPLE: How It Works

### Input Document
```
=== CLAIM FORM ===
Patient Name:           John Doe
Date of Birth:          01-JAN-1980
Age:                    45
Insurance Provider:     XYZ Insurance Corp
Member ID:              XYZ-12345

=== HOSPITAL BILL ===
Description             | Amount (Rs.)
Room Charges - 2 days   | 5,000
Medicine/Consumables    | 2,500
Investigation           | 1,200
Total                   | 8,700
```

### Processing Flow

**Step 1: Zoning (zoning_engine.py)**
```
Raw tokens from OCR (all on one list)
  ↓
Detect vertical gaps at:
  - Y=120 (after "XYZ Insurance Corp")
  - Y=200 (after "Member ID")
  - Y=280 (after "=== HOSPITAL BILL ===")
  ↓
Create zones:
  Zone 1: "patient_info" [y: 0-120]
  Zone 2: "insurance_info" [y: 120-200]
  Zone 3: "expense_table" [y: 280-450]
```

**Step 2: Classification (section_classifier.py)**
```
Zone 1: Check for label:value patterns
  → "Patient Name:" + "John Doe"
  → "Age:" + "45"
  → Classification: "form_section" ✓

Zone 2: Check for label:value patterns
  → "Insurance Provider:" + "XYZ Insurance Corp"
  → Classification: "form_section" ✓

Zone 3: Check for aligned columns
  → Multiple rows with same X structure
  → "Description" column (x=50-200)
  → "Amount" column (x=300-450)
  → Classification: "expense_table" ✓
```

**Step 3: Local Parsing**

**Zone 1 → form_parser.parse_form_section()**
```
Input: Zone 1 tokens
Process:
  - Find "Patient Name:" anchor
  - Extract value: "John Doe" (same row, right side)
  - Find "Age:" anchor
  - Extract value: "45" (same row, right side)
Output:
  FieldResult(field_name="patient_name", field_value="John Doe", confidence=0.95)
  FieldResult(field_name="age", field_value="45", confidence=0.95)
```

**Zone 2 → form_parser.parse_form_section()**
```
Input: Zone 2 tokens
Output:
  FieldResult(field_name="insurance_provider", field_value="XYZ Insurance Corp", confidence=0.92)
  FieldResult(field_name="member_id", field_value="XYZ-12345", confidence=0.90)
```

**Zone 3 → table_parser_dispatcher → parse_expense_table()**
```
Input: Zone 3 tokens
Process:
  - table_reconstruction.reconstruct_table(zone)
  - Y-clustering: Find 4 rows (header + 3 data rows)
  - X-clustering: Find 2 columns (description, amount)
  - Extract cells
  - Validate: amounts are numeric
Output:
  [
    {"cells": ["Room Charges - 2 days", "5,000"], "amount": 5000},
    {"cells": ["Medicine/Consumables", "2,500"], "amount": 2500},
    {"cells": ["Investigation", "1,200"], "amount": 1200},
  ]
```

**Step 4: Field Resolution (field_resolver.py)**
```
Merge all FieldResults:
  patient_name: "John Doe" (confidence: 0.95, from form_parser)
  age: "45" (confidence: 0.95, from form_parser)
  insurance_provider: "XYZ Insurance Corp" (confidence: 0.92, from form_parser)
  member_id: "XYZ-12345" (confidence: 0.90, from form_parser)
  [expense rows from table]

Resolve conflicts: (none in this example)
```

**Step 5: Schema Normalization**
```
Build CanonicalClaim:
{
  "patient": {
    "name": "John Doe",
    "age": 45
  },
  "insurance": {
    "payer": "XYZ Insurance Corp",
    "member_id": "XYZ-12345"
  },
  "expenses": [
    {
      "description": "Room Charges - 2 days",
      "amount": 5000
    },
    {
      "description": "Medicine/Consumables",
      "amount": 2500
    },
    {
      "description": "Investigation",
      "amount": 1200
    }
  ],
  "claims": {
    "calculated_total": 8700,
    "confidence": "HIGH"
  }
}
```

**Step 6: Rendering (renderer, unchanged)**
```
Read canonical schema:
  - No OCR re-parsing
  - No field inference
  - Just render to PDF/HTML
```

---

## VALIDATION CHECKLIST (Before Implementation)

- [ ] Architecture document reviewed
- [ ] Zoning logic makes sense
- [ ] Classification decision tree is clear
- [ ] Local parsing rules are understood
- [ ] Field resolver conflict logic is clear
- [ ] Schema normalization is compatible with renderer
- [ ] Module dependencies are clear (no circular)
- [ ] New module count is manageable (7 new + 2 updates)
- [ ] Deprecation plan is clear (remove after validation)
- [ ] Test strategy is defined

---

## NEXT STEPS (After Approval)

1. **Phase 1:** Implement zoning_engine.py + unit tests
2. **Phase 2:** Implement section_classifier.py + unit tests  
3. **Phase 3:** Implement local parsers (form, table, diagnosis, vitals)
4. **Phase 4:** Implement field_resolver + schema_normalizer integration
5. **Phase 5:** Create engine_v2.py and end-to-end tests
6. **Phase 6:** Side-by-side comparison (v1 vs v2)
7. **Phase 7:** Cutover to v2, remove v1
8. **Phase 8:** Remove deprecated modules

---

**Status:** Ready for Implementation ✓

Once you approve this architecture, I'll proceed with Phase 1 implementation.
