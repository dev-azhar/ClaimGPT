# Parser Rebuild: Clean Section-Aware Architecture

**Date:** May 12, 2026
**Status:** Architecture Design (Before Implementation)

---

## PROBLEM SUMMARY

**Current Flow (Broken):**
```
OCR (CORRECT) 
→ Layout Analysis (finds tables globally)
→ Document Classification
→ Type-Specific Parser (bill_parser, discharge_parser, etc.)
→ GLOBAL ROW RECONSTRUCTION
→ Schema Normalization
→ Renderer (gets corrupted schema)
```

**Failure Modes:**
- Patient Name field treated as medication_name
- Insurance Provider label becomes expense row
- Hospital header becomes medication table row
- Expense tables disappear or are misclassified
- Form fields merged into fake table rows
- Section boundaries ignored during extraction

**Root Cause:** Parser reconstructs entire document into rows BEFORE understanding document structure. It treats all horizontal alignment as table indication.

---

## NEW ARCHITECTURE (Clean Design)

```
┌─────────────────────────────────────────────────────────────────┐
│ OCR LAYER (EasyOCR, pdfplumber, PaddleOCR-VL) ✓ CORRECT         │
│ Returns: tokens with x0,y0,x1,y1 coordinates                     │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. SECTION ZONING ENGINE                                        │
│    Purpose: Identify logical document regions BEFORE extraction  │
│                                                                  │
│    Input:  OCR tokens + page metadata                            │
│    Process: Coordinate clustering, whitespace gaps,              │
│             heading anchors, font density, bbox grouping         │
│    Output: Labeled zones with bounding boxes                     │
│                                                                  │
│    Zones detected:                                               │
│    - page_header                                                │
│    - patient_info_section                                       │
│    - insurance_info_section                                     │
│    - hospitalization_info_section                               │
│    - diagnosis_section                                          │
│    - expense_table_region                                       │
│    - medication_table_region                                    │
│    - lab_table_region                                           │
│    - vitals_section                                             │
│    - footer                                                     │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. SECTION CLASSIFIER                                           │
│    Purpose: Classify each zone BEFORE extracting data            │
│                                                                  │
│    Input:  Zones from zoning engine                              │
│    Process: Content analysis, header keywords, structure          │
│             Table detection (LOCAL to zone, not global)          │
│    Output: Zone classifications                                  │
│                                                                  │
│    Classifications:                                              │
│    - form_section (has labels on left, values on right)         │
│    - expense_table (rows, columns, aligned amounts)             │
│    - medication_table (row-based structured data)               │
│    - lab_table (lab results with values/ranges)                 │
│    - diagnosis_block (multiple short text items)                │
│    - vitals_block (key-value structured)                        │
│    - header / footer (metadata, not data)                       │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. LOCAL SECTION PARSERS (Independent Per Zone)                │
│                                                                  │
│    3A. FORM SECTION PARSER (patient, insurance, hospital info)  │
│    ───────────────────────────────────────────────────────────  │
│    Input:  Zone content + zone type = "form_section"             │
│    Parsing Rules:                                                │
│      • Label anchors (Patient Name:, Age:, Hospital:)            │
│      • Value extraction: right-side only, same-row search        │
│      • Stop at next label or next line                           │
│      • NO vertical merging, NO full-page scanning                │
│      • NO global field inference                                 │
│    Output: FieldResult[] with confidence, source_bbox            │
│    Example:                                                      │
│      FieldResult(field_name='patient_name',                      │
│                  field_value='John Doe',                         │
│                  source_bbox=[x0,y0,x1,y1],                     │
│                  confidence=0.95)                                │
│                                                                  │
│    3B. TABLE SECTION PARSER (Local row reconstruction)           │
│    ───────────────────────────────────────────────────────────  │
│    Input:  Zone content + zone type = "expense_table" | etc.    │
│    Parsing Rules:                                                │
│      • Row detection: Y-coordinate clustering INSIDE zone        │
│      • Column detection: X-coordinate clustering INSIDE zone     │
│      • Multiline row merge: detect cells spanning Y-space        │
│      • Local column inference: don't require header row          │
│      • Do NOT require: currency symbols, specific keywords       │
│      • Do NOT scan: outside zone boundaries                      │
│    Output: TableRow[] with cell values and position              │
│    Example:                                                      │
│      [                                                           │
│        {                                                         │
│          'description': 'Room Charges 2 days',                   │
│          'amount': '5000',                                       │
│          'row_bbox': [x0,y0,x1,y1],                             │
│          'cells': [...]                                          │
│        }                                                         │
│      ]                                                           │
│                                                                  │
│    3C. DIAGNOSIS PARSER (Block text extraction)                  │
│    ───────────────────────────────────────────────────────────  │
│    Input:  Zone content + zone type = "diagnosis_block"         │
│    Parsing Rules:                                                │
│      • Extract text items separated by newlines/bullets         │
│      • Parse diagnostic codes if present (ICD-10, ICD-9)        │
│      • Map to primary/secondary diagnosis                        │
│      • Extract procedures and procedure codes if present         │
│    Output: DiagnosisSet with primary, secondary, procedures     │
│                                                                  │
│    3D. VITALS PARSER (Key-value extraction)                      │
│    ───────────────────────────────────────────────────────────  │
│    Input:  Zone content + zone type = "vitals_block"             │
│    Parsing Rules:                                                │
│      • Label-anchor based (BP:, Pulse:, Temp:)                   │
│      • Value extraction: same-row right-side only                │
│      • Parse units if present (mmHg, bpm, etc.)                  │
│    Output: VitalsSet with parsed values                          │
│                                                                  │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. TABLE RECONSTRUCTION (Inside Zone Only)                      │
│    Purpose: Convert aligned cells into structured table          │
│                                                                  │
│    Input:  Sorted tokens from table zone + zone boundaries       │
│    Process:                                                      │
│      • Y-coordinate clustering (row detection)                   │
│      • X-coordinate clustering (column detection)                │
│      • Cell assignment: which tokens belong to which cell        │
│      • Multiline cell handling: merge cells spanning Y           │
│      • Missing cell handling: interpolate columns                │
│    Output: StructuredTable with rows and column schema           │
│                                                                  │
│    CRITICAL: Only processes tokens WITHIN zone bbox              │
│              Does NOT scan full page                             │
│              Does NOT require header row                         │
│              Does NOT require all cells filled                   │
│                                                                  │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. FIELD RESOLVER (Conflict Resolution)                         │
│    Purpose: Merge results from multiple parsers                  │
│                                                                  │
│    Input:  FieldResult[] from all section parsers                │
│    Process:                                                      │
│      • Group by field_name (e.g., "patient_name")                │
│      • Filter by confidence threshold                            │
│      • Validate field values (age < 150, dates are valid)        │
│      • Select highest-confidence, valid result                   │
│      • Track provenance: which extractor produced value          │
│    Rules:                                                        │
│      ✗ Age cannot become patient_name                            │
│      ✗ Headers cannot become expense rows                        │
│      ✓ Physician name extracted by form parser wins              │
│      ✓ Expense rows from table parser used as-is                 │
│      ✓ Low-confidence results get confidence flag                │
│    Output: ResolvedFields {field_name → (value, confidence)}    │
│                                                                  │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. SCHEMA NORMALIZER                                            │
│    Purpose: Convert all parsed sections into canonical schema    │
│                                                                  │
│    Input:  ResolvedFields + StructuredTables                     │
│    Output: CanonicalClaim (immutable, renderer-ready)            │
│                                                                  │
│    Canonical Schema:                                             │
│    {                                                             │
│      "patient": {                                                │
│        "name": string,                                           │
│        "member_id": string,                                      │
│        "policy_number": string,                                  │
│        "age": int,                                               │
│        "sex": string,                                            │
│        "address": string                                         │
│      },                                                          │
│      "insurance": {                                              │
│        "payer": string,                                          │
│        "policy_number": string,                                  │
│        "member_id": string,                                      │
│        "group_number": string                                    │
│      },                                                          │
│      "hospitalization": {                                        │
│        "hospital_name": string,                                  │
│        "admission_date": string (ISO 8601),                      │
│        "discharge_date": string (ISO 8601),                      │
│        "doctor_name": string,                                    │
│        "bed_type": string                                        │
│      },                                                          │
│      "diagnosis": {                                              │
│        "primary": string,                                        │
│        "primary_code": string (ICD code),                        │
│        "secondary": [string],                                    │
│        "procedures": [string],                                   │
│        "procedure_codes": [string]                               │
│      },                                                          │
│      "medical": {                                                │
│        "medications": [                                          │
│          {                                                       │
│            "name": string,                                       │
│            "dosage": string,                                     │
│            "frequency": string,                                  │
│            "route": string                                       │
│          }                                                       │
│        ],                                                        │
│        "lab_results": [                                          │
│          {                                                       │
│            "test_name": string,                                  │
│            "result_value": string,                               │
│            "reference_range": string,                            │
│            "unit": string                                        │
│          }                                                       │
│        ],                                                        │
│        "vitals": [                                               │
│          {                                                       │
│            "vital_name": string,                                 │
│            "value": string,                                      │
│            "unit": string                                        │
│          }                                                       │
│        ]                                                         │
│      },                                                          │
│      "claims": {                                                 │
│        "claimed_total": float,                                   │
│        "calculated_total": float (sum of expenses),              │
│        "confidence": string (HIGH/MEDIUM/LOW)                    │
│      },                                                          │
│      "expenses": [                                               │
│        {                                                         │
│          "description": string,                                  │
│          "category": string,                                     │
│          "amount": float,                                        │
│          "quantity": float,                                      │
│          "unit_price": float                                     │
│        }                                                         │
│      ]                                                           │
│    }                                                             │
│                                                                  │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. RENDERER (Existing, Unchanged)                               │
│    Purpose: Render canonical schema to PDF/HTML/JSON             │
│                                                                  │
│    Input:  CanonicalClaim (schema-locked, no parsing)            │
│    Process:                                                      │
│      ✓ Read from canonical_json                                  │
│      ✓ No OCR re-parsing                                         │
│      ✓ No regex inference                                        │
│      ✓ No field reconstruction                                   │
│      ✓ No schema modification                                    │
│    Output: PDF / HTML preview                                    │
│                                                                  │
│    NEVER:                                                        │
│      ✗ Parse OCR again                                           │
│      ✗ Infer missing fields                                      │
│      ✗ Reconstruct tables                                        │
│      ✗ Modify schema structure                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## ZONING LOGIC (Detailed)

### Zone Detection Strategy

```python
def detect_zones(tokens: List[Token]) -> List[Zone]:
    """
    Zones are detected by analyzing:
    1. Vertical whitespace gaps → Section boundaries
    2. Heading anchors → Section starts
    3. Font density changes → Region changes
    4. Horizontal alignment patterns → Table vs. form
    5. Coordinate clustering → Group related tokens
    
    NOT:
    - Keyword matching (unreliable with OCR errors)
    - Global page structure (only local analysis)
    """
    
    # Step 1: Build vertical gap map (y-coordinates)
    # Find large gaps between token clusters
    gaps = find_vertical_gaps(tokens, min_gap=50)  # 50pt gap = section boundary
    
    # Step 2: Find heading anchors
    # Keywords that likely start sections
    anchors = [
        "Patient", "Insurance", "Hospital", "Admission",
        "Discharge", "Diagnosis", "Medication", "Lab",
        "Expense", "Bill", "Vitals", "Charges"
    ]
    anchor_positions = find_anchors(tokens, anchors)
    
    # Step 3: Cluster tokens by Y-coordinate
    # Group horizontally adjacent tokens
    y_clusters = cluster_by_y(tokens, tolerance=5)  # 5pt clustering
    
    # Step 4: Classify each cluster
    # Is it a form line, table row, heading, etc.?
    cluster_types = classify_clusters(y_clusters)
    
    # Step 5: Merge consecutive similar clusters into zones
    zones = merge_clusters_into_zones(
        clusters=y_clusters,
        gaps=gaps,
        anchors=anchor_positions
    )
    
    return zones
```

### Zone Output Format

```python
@dataclass
class Zone:
    section_type: str  # "patient_info", "expense_table", etc.
    bbox: Bbox         # [x0, y0, x1, y1]
    tokens: List[Token]
    confidence: float  # 0.0-1.0 based on heuristics
    metadata: dict
    
    # Example:
    # Zone(
    #   section_type="expense_table",
    #   bbox=[50, 300, 550, 600],
    #   tokens=[...],
    #   confidence=0.92
    # )
```

---

## SECTION CLASSIFICATION LOGIC (Detailed)

### Classification Decision Tree

```python
def classify_zone(zone: Zone) -> str:
    """
    Classify zone into extraction category.
    
    NOTE: Classification happens AFTER zoning.
    NOT on entire document.
    """
    
    # Rule 1: If zone has extreme aspect ratio, it's a list/form
    if zone.aspect_ratio() > 3:  # Wide and short
        # Multiple columns → table
        if has_aligned_columns(zone):
            return "table"
        else:
            # Multiple labels on same line → form
            return "form_section"
    
    # Rule 2: Check for table structure INSIDE zone
    # NOT globally
    if has_repeated_y_alignment(zone, min_rows=3):
        # Multiple rows with same X structure
        return classify_table_type(zone)
    
    # Rule 3: Check for label-value pairs
    if has_label_colon_pattern(zone, min_pairs=2):
        # "Patient Name:", "Age:", etc.
        return "form_section"
    
    # Rule 4: Check for block text (multiple lines, no alignment)
    if is_block_text(zone):
        if contains_keywords(zone, ["Diagnosis", "Assessment"]):
            return "diagnosis_block"
        if contains_keywords(zone, ["BP", "Pulse", "Temp"]):
            return "vitals_block"
        return "text_block"
    
    # Rule 5: Header/footer detection
    if is_header_or_footer(zone):
        return "header"
    
    return "unknown"


def classify_table_type(zone: Zone) -> str:
    """Classify what kind of table is in this zone."""
    text = zone.text.lower()
    
    if any(k in text for k in ["expense", "charge", "amount", "bill", "cost"]):
        return "expense_table"
    if any(k in text for k in ["medicine", "medication", "drug", "tablet"]):
        return "medication_table"
    if any(k in text for k in ["lab", "result", "test", "investigation"]):
        return "lab_table"
    if any(k in text for k in ["vital", "bp", "pulse", "temp"]):
        return "vitals_table"
    
    # Generic table - use local row/column detection
    return "generic_table"
```

---

## FORM PARSER LOGIC (Detailed)

### Example: Patient Info Extraction

```python
def parse_form_section(zone: Zone) -> List[FieldResult]:
    """
    Extract form fields from zone.
    
    Rules:
    - Scan for label anchors only
    - Extract value from same row only
    - Stop at next anchor or next row
    """
    
    anchors = {
        "Patient Name": ("patient_name", r"^patient\s+name"),
        "Age": ("age", r"^age"),
        "Hospital": ("hospital_name", r"^hospital"),
        "Insurance Provider": ("insurance_provider", r"^insurance\s+provider"),
    }
    
    results = []
    
    # Sort tokens by Y, then X (top to bottom, left to right)
    sorted_tokens = sorted(zone.tokens, key=lambda t: (t.y0, t.x0))
    
    # Group by Y (row)
    rows = group_by_y_coordinate(sorted_tokens, tolerance=5)
    
    for row in rows:
        # Check if this row contains a label
        row_text = " ".join(t.text for t in row)
        
        for label_name, (field_name, pattern) in anchors.items():
            if re.search(pattern, row_text, re.I):
                # Found anchor, extract value from rest of row
                # Split row at anchor token
                anchor_token = find_token_matching(row, pattern)
                anchor_idx = row.index(anchor_token)
                
                # Value tokens are after anchor, same row
                value_tokens = row[anchor_idx + 1:]
                
                if value_tokens:
                    value = " ".join(t.text for t in value_tokens)
                    bbox = merge_bboxes([t.bbox for t in value_tokens])
                    
                    results.append(FieldResult(
                        field_name=field_name,
                        field_value=value,
                        source_bbox=bbox,
                        confidence=0.90,  # Form fields are high confidence
                        extractor_name="form_parser"
                    ))
    
    return results
```

**Critical Rules:**
- ✗ Do NOT scan full page for "patient_name"
- ✗ Do NOT vertically merge rows
- ✗ Do NOT merge values from multiple pages
- ✓ Do extract from right side of label only
- ✓ Do stop at next label in same row
- ✓ Do preserve source_bbox for validation

---

## TABLE RECONSTRUCTION LOGIC (Detailed)

### Example: Local Row/Column Detection

```python
def reconstruct_table(zone: Zone) -> List[Dict[str, Any]]:
    """
    Reconstruct table structure from zone tokens.
    
    CRITICAL: Only uses tokens WITHIN zone bbox
    """
    
    # Step 1: Extract tokens in zone (with margin for safety)
    zone_tokens = [t for t in zone.tokens if is_inside_bbox(t, zone.bbox)]
    
    # Step 2: Cluster by Y (row detection)
    y_clusters = cluster_by_y(zone_tokens, tolerance=3)  # Tight clustering
    rows = [Row(tokens=cluster) for cluster in y_clusters]
    
    # Step 3: Skip header detection
    # We don't assume first row is header
    # Use column inference instead
    
    # Step 4: For each row, detect columns (X clustering)
    all_x_positions = []
    for row in rows:
        x_positions = [t.x0 for t in row.tokens]
        all_x_positions.extend(x_positions)
    
    # Find consistent column boundaries across rows
    x_columns = cluster_by_x(all_x_positions, tolerance=10)
    
    # Step 5: Assign tokens to cells
    cells = []
    for row in rows:
        row_cells = []
        for col_boundary in x_columns:
            col_tokens = [t for t in row.tokens if overlaps_x(t, col_boundary)]
            cell_text = " ".join(t.text for t in col_tokens)
            row_cells.append(cell_text)
        cells.append(row_cells)
    
    # Step 6: Return structured rows
    return [
        {
            "cells": row,
            "raw_text": " | ".join(row),
            "row_bbox": merge_bboxes([...])
        }
        for row in cells
    ]
```

**Critical Rules:**
- ✗ Do NOT scan outside zone.bbox
- ✗ Do NOT require header row
- ✗ Do NOT merge rows vertically
- ✗ Do NOT require all cells filled
- ✓ Do use local column inference
- ✓ Do handle multiline cells

---

## FIELD RESOLVER LOGIC (Detailed)

```python
def resolve_fields(results: List[FieldResult]) -> Dict[str, ResolvedField]:
    """
    Merge field results from multiple parsers.
    Highest confidence valid value wins.
    """
    
    # Group by field_name
    field_groups = defaultdict(list)
    for result in results:
        field_groups[result.field_name].append(result)
    
    resolved = {}
    
    for field_name, candidates in field_groups.items():
        # Filter by confidence threshold
        valid = [c for c in candidates if c.confidence >= 0.5]
        
        if not valid:
            continue
        
        # Validate field value (domain-specific)
        valid = [c for c in valid if is_valid_field(field_name, c.field_value)]
        
        if not valid:
            continue
        
        # Select highest confidence
        winner = max(valid, key=lambda c: c.confidence)
        
        resolved[field_name] = ResolvedField(
            value=winner.field_value,
            confidence=winner.confidence,
            source_bbox=winner.source_bbox,
            extractor=winner.extractor_name
        )
    
    return resolved


def is_valid_field(field_name: str, value: str) -> bool:
    """Validate field value based on field type."""
    
    if field_name == "age":
        try:
            age = int(value)
            return 0 < age < 150
        except:
            return False
    
    if field_name in ["admission_date", "discharge_date"]:
        try:
            from dateutil import parser
            parser.parse(value)
            return True
        except:
            return False
    
    if field_name == "patient_name":
        # Must have at least one letter, not purely numeric
        return any(c.isalpha() for c in value) and len(value.strip()) > 0
    
    return True
```

---

## MODULES TO CREATE (New)

```
services/parser/app/
├── zoning_engine.py          # Section boundary detection
├── section_classifier.py      # Zone classification
├── form_parser.py             # Extract patient, insurance, hospital info
├── table_parser.py            # Local table reconstruction
├── diagnosis_parser.py         # Extract diagnosis/procedures
├── vitals_parser.py            # Extract vital signs
├── field_resolver.py           # Conflict resolution (UPDATED from current)
└── table_reconstruction.py    # Helper for row/column detection
```

---

## MODULES TO KEEP (Minimal Changes)

- `schema_normalizer.py` — Convert resolved fields to canonical schema (unchanged)
- `models.py` — Data structures (updated with new types)
- Renderer layer — Consumes canonical schema only (unchanged)

---

## MODULES TO REMOVE (Deprecated)

**These rely on global page reconstruction and will be replaced:**

```
❌ bill_parser.py           → Replaced by zoning + local table parser
❌ discharge_parser.py      → Replaced by section-based parsers
❌ prescription_parser.py    → Replaced by table parser + classification
❌ lab_parser.py             → Replaced by table parser + vitals parser
❌ table_extractor.py        → Replaced by local table_reconstruction
❌ form_extractor.py         → Replaced by form_parser
❌ layout_analyzer.py        → Replaced by zoning_engine
❌ document_classifier.py    → Replaced by section_classifier
```

---

## EXECUTION FLOW (Detailed)

### Pipeline Entry Point

```python
def parse_document_v2(
    ocr_pages: List[Dict[str, Any]],
    images: Optional[List[Any]] = None
) -> CanonicalClaim:
    """New clean pipeline."""
    
    # Merge all OCR pages into flat token list
    all_tokens = []
    for page_idx, page in enumerate(ocr_pages):
        tokens = page.get("tokens", [])
        for token in tokens:
            token["page"] = page_idx  # Track source page
        all_tokens.extend(tokens)
    
    # Step 1: Detect zones
    zones = zoning_engine.detect_zones(all_tokens)
    logger.info(f"Detected {len(zones)} zones")
    
    # Step 2: Classify zones
    for zone in zones:
        zone.classification = section_classifier.classify_zone(zone)
    
    # Step 3: Parse each zone independently
    all_field_results = []
    all_tables = []
    
    for zone in zones:
        if zone.classification == "form_section":
            results = form_parser.parse_form_section(zone)
            all_field_results.extend(results)
        
        elif zone.classification.endswith("_table"):
            table_data = table_parser.parse_table_zone(zone)
            all_tables.append({
                "type": zone.classification,
                "rows": table_data
            })
        
        elif zone.classification == "diagnosis_block":
            results = diagnosis_parser.parse_diagnosis_zone(zone)
            all_field_results.extend(results)
        
        elif zone.classification == "vitals_block":
            results = vitals_parser.parse_vitals_zone(zone)
            all_field_results.extend(results)
    
    # Step 4: Resolve field conflicts
    resolved_fields = field_resolver.resolve_fields(all_field_results)
    
    # Step 5: Build canonical schema
    canonical = schema_normalizer.build_canonical_schema(
        form_data=resolved_fields,
        table_data=all_tables
    )
    
    return canonical
```

---

## VALIDATION RULES (What Makes Valid Extraction)

### Form Fields
```
✓ Patient Name: "John Doe" (letters, spaces, apostrophes)
✗ "Patient Name:" (just the label)
✗ "Insurance Provider" (field name, not value)
✓ Age: "45" (0 < age < 150)
✗ "Patient" or "age" (incomplete)
```

### Table Rows
```
✓ Multiple rows (at least 2-3 rows for table confidence)
✓ Aligned columns (consistent X positions across rows)
✓ Row spacing (consistent Y distances)
✗ Single row (not a table)
✗ Random text (no alignment)
```

### Expense Rows
```
✓ Description + Amount (both present)
✓ Generic table with 2+ columns (allows for unknown schema)
✗ Just labels ("Room Charges" without amount)
✗ Non-numeric amounts
```

---

## RENDERER INTERFACE (No Changes)

```python
@dataclass
class CanonicalClaim:
    """
    Schema-locked, renderer-ready output.
    Renderer NEVER modifies or infers fields.
    """
    patient: PatientInfo
    insurance: InsuranceInfo
    hospitalization: HospitalizationInfo
    diagnosis: DiagnosisInfo
    medical: MedicalData
    claims: ClaimsData
    expenses: List[ExpenseItem]
    
    # Persistence
    def to_json(self) -> str:
        """Serialize for storage."""
        return json.dumps(asdict(self), indent=2)
    
    @classmethod
    def from_json(cls, data: str) -> "CanonicalClaim":
        """Load from storage."""
        return cls(**json.loads(data))
```

---

## TESTING STRATEGY

### Test Cases

```
1. Zoning Tests
   ✓ Multiple sections detected
   ✓ Zone boundaries correct
   ✓ Patient info vs. table distinction
   ✓ Medication table vs. expense table

2. Classification Tests
   ✓ Form sections identified
   ✓ Tables classified by type
   ✓ Diagnosis blocks detected
   ✓ Vitals sections identified

3. Extraction Tests
   ✓ Patient Name extracted (not "Insurance Provider")
   ✓ Hospital name not from medication table
   ✓ Expense rows with amounts
   ✓ Medication rows parsed correctly
   ✓ Lab results with reference ranges

4. Integration Tests
   ✓ End-to-end claim parsing
   ✓ Multi-document handling
   ✓ Conflict resolution
   ✓ Canonical schema correctness

5. Regression Tests
   ✓ Previous failure cases now work
   ✓ No new regressions introduced
```

---

## IMPLEMENTATION PHASES

### Phase 1: Core Zoning Engine
- Implement `zoning_engine.py`
- Build zone detection with vertical/horizontal gap analysis
- Unit tests for zone detection

### Phase 2: Section Classifier
- Implement `section_classifier.py`
- Classification decision tree
- Unit tests for zone classification

### Phase 3: Local Parsers
- Implement `form_parser.py` (patient, insurance, hospital)
- Implement `table_reconstruction.py` (row/column detection)
- Implement `diagnosis_parser.py`, `vitals_parser.py`
- Unit tests for each parser

### Phase 4: Field Resolver & Normalizer
- Update `field_resolver.py` with new conflict resolution
- Update `schema_normalizer.py` to consume resolved fields
- Unit tests for resolver

### Phase 5: Integration & Testing
- New `parse_document_v2()` entry point
- End-to-end tests
- Comparison with existing pipeline (side-by-side)
- Remove old modules once validated

---

## SUCCESS CRITERIA

- ✓ Patient Name never becomes medication_name
- ✓ Insurance Provider never becomes expense row
- ✓ Hospital header never becomes table row
- ✓ Expense tables completely extracted (no rows dropped)
- ✓ Canonical schema matches renderer expectations
- ✓ All old failing test cases now pass
- ✓ No new regressions on working documents

---

## RISKS & MITIGATION

| Risk | Mitigation |
|------|-----------|
| Zoning misses section boundaries | Extensive unit tests with diverse documents |
| Table columns misaligned | Tolerance tuning, multiline cell handling |
| Form parser catches wrong labels | Anchor-pattern matching only, no fuzzy logic |
| Renderer breaks on new schema | Backward compatibility layer initially |

---

## Summary

This architecture replaces global page reconstruction with **local section-aware parsing**. Each section is understood independently before data extraction. Fields cannot be contaminated from adjacent sections.

**Key Principles:**
1. **Zoning First** — Understand structure before extraction
2. **Local Parsing** — Extract within zone boundaries only
3. **High Confidence** — Validate domain-specific constraints
4. **Section Isolation** — Form fields separate from tables
5. **Canonical Schema** — One immutable output format
6. **Renderer Readonly** — No post-extraction inference

The new pipeline is **clean, testable, and debuggable** at each stage.
