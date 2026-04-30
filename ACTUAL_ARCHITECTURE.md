# ClaimGPT: Actual Implementation Architecture

**Date**: April 29, 2026  
**Status**: Deep-dive analysis of real codebase implementation  
**Focus**: What's actually implemented vs. initial documentation

---

## Table of Contents

1. [Overview](#overview)
2. [Celery + Redis Task Orchestration](#celery--redis-task-orchestration)
3. [OCR Service: Real Stack](#ocr-service-real-stack)
4. [Parser Service: Extraction Chain](#parser-service-extraction-chain)
5. [Workflow Orchestration](#workflow-orchestration)
6. [Scaling & Fault Tolerance](#scaling--fault-tolerance)
7. [Implementation Status](#implementation-status)

---

## Overview

ClaimGPT is **NOT DAG-based** (no Airflow/Prefect). Instead, it uses:
- **Celery 5.x** with **Redis** broker for task queuing
- **Sequential HTTP polling** for workflow orchestration
- **Dual-worker architecture** (GPU-bound + CPU-bound tasks)
- **Kubernetes HPA** for horizontal scaling
- **Multi-level retry logic** with exponential backoff

---

## Celery + Redis Task Orchestration

### Architecture

**Broker**: Redis (tcp://localhost:6379/0)  
**Result Backend**: Redis (persistent)  
**Framework**: Celery 5.x

### Worker Configuration

**File**: `libs/shared/celery_app.py`

```python
celery_app = Celery(
    "claim_app",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
)

# Queue configuration
default_exchange = Exchange("default", type="direct", durable=True)
gpu_exchange = Exchange("gpu_queue", type="direct", durable=True)
dead_letter_exchange = Exchange("dead_letter", type="direct", durable=True)
```

### Task Routing

| Task | Queue | Worker | Concurrency | Purpose |
|------|-------|--------|-------------|---------|
| `ocr_task` | `gpu_queue` | worker_gpu | 1 | Text extraction from documents |
| `parser_task` | `gpu_queue` | worker_gpu | 1 | Structured field parsing |
| `coding_task` | `default` | worker_cpu | 4 | Medical code assignment (ICD-10/CPT) |
| `risk_task` | `default` | worker_cpu | 4 | Rejection risk prediction |
| `validator_task` | `default` | worker_cpu | 4 | Rule-based validation |
| `finalize_claim_task` | `default` | worker_cpu | 4 | Pipeline completion & status update |

### Docker Compose Setup

**File**: `infra/docker/docker-compose.yml`

```yaml
worker_gpu:
  command: celery -A libs.shared.celery_app worker -Q gpu_queue --concurrency=1
  
worker_cpu:
  command: celery -A libs.shared.celery_app worker -Q default --concurrency=4

flower:
  command: celery -A libs.shared.celery_app flower --port=5555
  # Access at http://localhost:5555
```

### Task Retry Configuration

**File**: `services/shared_tasks.py`

```python
@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,  # 10 minutes max
    max_retries=5,
)
def ocr_task(self, claim_id: str) -> dict[str, str]:
    # Task will retry up to 5 times
    # Backoff: 1s, 2s, 4s, 8s, 16s (capped at 600s)
    ...
```

### Task Chain (Pipeline)

```
User Upload
    ↓
ocr_task (Celery)
    └─→ _run_ocr_job() - Tesseract/PaddleOCR
    
    ↓
parser_task (Celery)
    └─→ _run_parse_job() - Extract 20+ fields
    
    ↓
coding_task (Celery)
    └─→ _run_coding_job() - ICD-10/CPT assignment
    
    ↓
risk_task (Celery)
    └─→ _run_risk_job() - XGBoost/LightGBM prediction
    
    ↓
validator_task (Celery)
    └─→ _run_validator_job() - 10 validation rules
    
    ↓
finalize_claim_task (Celery)
    └─→ Mark claim as COMPLETED
```

### Dead Letter Queue Handling

Failed tasks are automatically routed to:
- **Exchange**: `dead_letter`
- **Routing Key**: `dead_letter`
- **Manual Replay**: Via Flower UI at http://localhost:5555

---

## OCR Service: Real Stack

### Service Configuration

**File**: `services/ocr/app/config.py`

```python
class Settings(BaseSettings):
    enable_paddle_ocr: bool = True
    enable_paddle_vl: bool = False  # ← Disabled (classic mode only)
    paddle_language: str = "en"
    tesseract_cmd: str = "tesseract"
    enable_secondary_ocr_on_pdf: bool = True
    debug_dump_enabled: bool = True
```

### OCR Engine Priority Chain

**File**: `services/ocr/app/engine.py`

#### 1. **Primary: PaddleOCR (Classic)**

```python
# Lazy-loaded singleton
_paddle_engine = PaddleOCR(
    lang="en",
    use_angle_cls=True,  # Detect orientation
    show_log=False
)
```

**Used for**: All image formats + PDF scanned pages

**Config**: Classic mode (NOT Vision-Language, VL disabled)

#### 2. **Fallback: Tesseract OCR**

```python
_tesseract_available = pytesseract.get_tesseract_version()

# If PaddleOCR fails:
if not paddle_text.strip():
    data = pytesseract.image_to_data(img)
    text, conf = _aggregate_tesseract_data(data)
```

**Used when**: PaddleOCR unavailable or fails

#### 3. **PDF Handling: Hybrid Approach**

```python
def _extract_from_pdf(path: Path) -> list[PageResult]:
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            # Step 1: Extract embedded text
            digital_text = page.extract_text()
            
            # Step 2: Extract tables
            tables = page.extract_tables()
            
            # Step 3: OCR fallback if scanned
            if not digital_text or enable_secondary_ocr_on_pdf:
                page_text, conf = _ocr_pdf_page(page)
                digital_text = _merge_text_digital_first(digital_text, page_text)
```

**Processing**:
- pdfplumber → embedded text + tables
- If no text or secondary OCR enabled → render to image → PaddleOCR/Tesseract

### Advanced Preprocessing Pipeline

**File**: `services/ocr/app/engine.py` - `_preprocess()`

```
Input Image
    ↓
1. Grayscale Conversion (RGB → Gray)
    ↓
2. Noise Removal
    └─→ cv2.fastNlMeansDenoising(h=10, templateWindowSize=7, searchWindowSize=21)
    ↓
3. Contrast Enhancement (CLAHE)
    └─→ clipLimit=2.0, tileGridSize=(8,8)
    ↓
4. Thresholding
    ├─→ Aggressive: Adaptive Gaussian (blockSize=31, C=10)
    └─→ Standard: Otsu's method
    ↓
5. Morphological Operations
    └─→ cv2.MORPH_CLOSE (fill 2×2 gaps in text)
    ↓
6. Deskewing
    └─→ Detect angle via minAreaRect
    └─→ Rotate to correct
    ↓
7. Upscaling (if < 600px)
    └─→ Scale up 2-4× for Tesseract
    ↓
Output: Preprocessed Image for OCR
```

### Multi-Format Support

| Format | Method | Handler |
|--------|--------|---------|
| **PDF** | Embedded + Scanned | pdfplumber + PaddleOCR |
| **JPEG, PNG** | Image OCR | PaddleOCR + Tesseract |
| **TIFF, BMP, WebP** | Image OCR | CV2 preprocessing + PaddleOCR |
| **DOCX** | Paragraph extraction | python-docx |
| **XLSX/XLS** | Sheet parsing | openpyxl |
| **CSV, JSON, XML, HTML** | Direct text | Standard parsing |

### Idempotency: Set-Based Hashing

**File**: `services/ocr/app/main.py` - `calculate_claim_documents_set_hash()`

```python
def calculate_claim_documents_set_hash(db: Session, claim_id: uuid.UUID) -> str:
    """
    Fetch all content_hash values for documents in a claim,
    sort, join, and hash them.
    """
    hashes = [d.content_hash for d in db.query(Document)
              .filter(Document.claim_id == claim_id).all()]
    
    return calculate_claim_set_hash(hashes)  # SHA-256
```

**Purpose**: Avoid re-processing identical document sets

---

## Parser Service: Extraction Chain

### Service Configuration

**File**: `services/parser/app/config.py`

```python
class Settings(BaseSettings):
    # Structured extraction via local LLM
    structured_extraction_enabled: bool = True
    llm_url: str = "http://ollama:11434/api/generate"
    llm_model: str = "llama3.2"
    structured_max_chars: int = 24000
    llm_timeout_seconds: int = 180
    
    # LayoutLMv3 model
    layoutlm_model: str = "microsoft/layoutlmv3-base"
    use_heuristic_fallback: bool = True
    
    # Document routing
    enable_document_router: bool = True
    enable_spatial_table_mapping: bool = True
    enable_strict_field_validation: bool = True
```

### Extraction Priority Chain

**File**: `services/parser/app/engine.py` - `parse_document()`

```python
def parse_document(ocr_pages, images=None) -> ParseOutput:
    page_objects = _build_page_objects(ocr_pages)
    
    # ═══════════════════════════════════════════════════════════
    # STEP 1: Structured LLM Extraction (PRIMARY)
    # ═══════════════════════════════════════════════════════════
    if settings.structured_extraction_enabled:
        try:
            structured_output = _extract_with_structured_llm(routed_pages)
            if structured_output is not None:
                return structured_output  # ← SUCCESS
        except Exception:
            logger.exception("Structured extraction failed")
            # Continue to Step 2
    
    # ═══════════════════════════════════════════════════════════
    # STEP 2: LayoutLMv3 Model (SECONDARY)
    # ═══════════════════════════════════════════════════════════
    if images and _load_model():
        try:
            model_output = _extract_with_model(routed_pages, images)
            return model_output  # ← SUCCESS
        except Exception:
            logger.exception("Model inference failed")
            # Continue to Step 3
    
    # ═══════════════════════════════════════════════════════════
    # STEP 3: Heuristic Fallback (GUARANTEED)
    # ═══════════════════════════════════════════════════════════
    if settings.use_heuristic_fallback:
        heuristic_output = _extract_with_heuristic(page_objects)
        return heuristic_output
    
    return ParseOutput(used_fallback=True)
```

### Step 1: Structured LLM Extraction

**Endpoint**: `http://ollama:11434/api/generate`  
**Model**: Llama 3.2  
**Timeout**: 180 seconds

**Implementation**: `_extract_with_structured_llm()`

```python
def _extract_with_structured_llm(ocr_pages: List[Dict]) -> Optional[ParseOutput]:
    if not ocr_pages:
        return None

    prompt = _build_structured_prompt(ocr_pages)
    
    # POST to Ollama
    extraction = _call_structured_llm(prompt)
    
    # RETRY 1: If timeout, reduce OCR context
    if extraction is None and settings.structured_retry_chars > 0:
        retry_prompt = _build_structured_prompt(
            ocr_pages,
            max_chars=settings.structured_retry_chars  # 8000
        )
        extraction = _call_structured_llm(retry_prompt)
    
    # RETRY 2: Multi-document per-document extraction
    if extraction is None and len(ocr_pages) > 1:
        grouped_pages: Dict[str, List] = {}
        for p in ocr_pages:
            did = str(p.get("document_id") or "")
            key = did or f"page-{p.get('page_number')}"
            grouped_pages.setdefault(key, []).append(p)
        
        merged: Optional[StructuredClaimExtraction] = None
        for _, pages in sorted(grouped_pages.items()):
            chunk_prompt = _build_structured_prompt(
                pages,
                max_chars=settings.structured_retry_chars
            )
            chunk_extraction = _call_structured_llm(chunk_prompt)
            if chunk_extraction:
                merged = _merge_structured_extractions(merged, chunk_extraction)
        
        extraction = merged
    
    return extraction
```

**Extracted Fields** (JSON):
```json
{
  "patient_name": "John Doe",
  "member_id": "MEM123456",
  "policy_number": "POL789456",
  "age": 42,
  "hospital_name": "Apollo Hospital",
  "admission_date": "2026-04-15",
  "discharge_date": "2026-04-28",
  "primary_diagnosis": "Type 2 Diabetes Mellitus",
  "procedures": ["Blood Sugar Test"],
  "treating_doctor": "Dr. Smith",
  "claimed_total": 50000.0,
  "bill_line_items": [
    {
      "description": "Room Charges",
      "quantity": 13,
      "unit_price": 500.0,
      "amount": 6500.0
    }
  ]
}
```

### Step 2: LayoutLMv3 Model Inference

**Model**: microsoft/layoutlmv3-base  
**Framework**: Transformers + PyTorch  
**Status**: Available but only runs if LLM fails

**Implementation**: `_extract_with_model()`

```python
def _extract_with_model(ocr_pages: List[Dict], images: List[Image]) -> ParseOutput:
    import torch
    
    all_fields: List[FieldResult] = []
    
    for page_info, img in zip(ocr_pages, images):
        page_num = page_info.get("page_number", 1)
        text = page_info.get("text", "")
        words = text.split()
        
        # Prepare input for LayoutLMv3
        encoding = _processor(
            img,
            words,
            boxes=word_boxes,  # Bounding boxes
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )
        
        # Token classification
        with torch.no_grad():
            outputs = _model(**encoding)
        
        predictions = outputs.logits.argmax(-1).squeeze().tolist()
        
        # Extract labeled tokens
        for word, pred in zip(words, predictions):
            label = _model.config.id2label.get(pred, "O")
            if label != "O":
                all_fields.append(FieldResult(
                    field_name=label,
                    field_value=word,
                    source_page=page_num,
                    model_version="layoutlmv3"
                ))
    
    return ParseOutput(
        fields=all_fields,
        model_version="layoutlmv3",
        used_fallback=False
    )
```

**Model Version Tracking**: "layoutlmv3" (when used successfully)

### Step 3: Heuristic Fallback - 40+ Regex Patterns

**File**: `services/parser/app/engine.py`

#### 3a. Patient Demographics

| Field | Regex Pattern | Example Match |
|-------|---------------|----------------|
| `patient_name` | `(?:patient\s*name\|...\|[^\n\|]+?)` | "Patient Name: John Doe" |
| `date_of_birth` | `(?:dob\|date of birth)\s*[:\-]?\s*([0-3]?\d...)` | "DOB: 15-Jan-1984" |
| `age` | `(?:age)\s*[:\-]?\s*(\d{1,3})` | "Age: 42" |
| `gender` | `(?:gender\|sex)\s*[:\-]?\s*(male\|female)` | "Gender: Male" |

#### 3b. Insurance Information

| Field | Regex Pattern |
|-------|---------------|
| `policy_number` | `(?:policy\s*no\|policy\s*number)\s*[:\-]?\s*([\w\-/]+)` |
| `member_id` | `(?:member\s*id\|uhid)\s*[:\-]?\s*([\w\-/]+)` |
| `insurer_name` | `(?:insurer\|insurance\s*company)\s*[:\-]:\s*([^\n\r\|]+?)` |

#### 3c. Clinical Information

| Field | Regex Pattern |
|-------|---------------|
| `diagnosis` | `(?:diagnosis)\s*[:\-]\s*([^\n\r\|]+?)` |
| `icd_code` | `\b([A-TV-Z]\d{2}(?:\.\d{1,4})?)\b` |
| `procedure` | `(?:procedure\s*performed)\s*[:\-]?\s*(.+)` |
| `cpt_code` | `\b(\d{5})\b` |
| `medication` | `(?:medication\|medicine)\s*[:\-]:\s*(.+)` |
| `allergy` | `(?:allergy\|allergy)\s*[:\-]?\s*(.+)` |

#### 3d. Billing/Expenses (15+ Categories)

```python
_EXPENSE_CATEGORIES = {
    "room rent": "room_charges",
    "consultation charges": "consultation_charges",
    "pharmacy": "pharmacy_charges",
    "investigation": "investigation_charges",
    "laboratory": "laboratory_charges",
    "radiology": "radiology_charges",
    "surgery": "surgery_charges",
    "surgeon fee": "surgeon_fees",
    "anaesthesia": "anaesthesia_charges",
    "ot charges": "ot_charges",
    "nursing": "nursing_charges",
    "consumables": "consumables",
    "ambulance": "ambulance_charges",
    "icu charges": "icu_charges",
    "physiotherapy": "physiotherapy_charges",
}
```

### Expense Table Extraction: 4-Pass Algorithm

**File**: `services/parser/app/engine.py` - `_extract_expense_table()`

#### Pass 1: Pipe-Separated Tables
```
| Description          | Amount   |
| Room Charges         | 6,500    |
| Pharmacy             | 12,300   |
```

#### Pass 2: Tab/Multi-Space Aligned
```
Description          Amount
Room Charges         6,500
Pharmacy            12,300
```

#### Pass 2c: Numbered-Line Fallback
```
1 HDU Charges - 2 Days              18,000
2 Consultant Fee                     5,000
```

#### Pass 3: CPT Code Blacklist

**Why**: Prevent 5-digit CPT codes (e.g., 38205, 96413) from being mistaken for rupee amounts

```python
known_cpt_codes = {
    f.field_value for f in fields if f.field_name == "cpt_code"
}

# Skip amounts that match known CPT codes
if str(int(amt)) in known_cpt_codes:
    continue  # Don't add as expense
```

### Document Routing & Field Whitelisting

**File**: `services/parser/app/engine.py` - `_classify_page_document_type()`

#### Document Type Detection

```python
DocumentType = {
    "DISCHARGE_SUMMARY": Highest priority for demographics
    "LAB_REPORT": Focus on test results, diagnostic data
    "PHARMACY_INVOICE": Focus on medications, amounts
    "HOSPITAL_BILL": Focus on itemized expenses
    "UNKNOWN": All fields allowed
}
```

#### Classification Logic

1. **Strong Cues** (highest priority):
   - "medical insurance claim form" → HOSPITAL_BILL
   - "policy number" + "admission date" → HOSPITAL_BILL

2. **Billing Keyword Detection**:
   - "expense category", "hospital expense breakdown" → HOSPITAL_BILL
   - "total amount", "itemised total" → HOSPITAL_BILL

3. **Keyword Scoring**:
   - Count medical keywords per document type
   - Table density heuristic (6+ numeric lines with |)

#### Field Whitelisting

```python
_DOC_TYPE_FIELD_ALLOWLIST = {
    "DISCHARGE_SUMMARY": {
        "patient_name", "date_of_birth", "age", "gender",
        "chief_complaint", "diagnosis", "icd_code", "procedure", "cpt_code",
        "medications", "allergies", "treating_doctor", "registration_date",
        "admission_date", "discharge_date", "hospital_name"
    },
    "LAB_REPORT": {
        "patient_name", "date_of_birth", "age", "gender",
        "test_name", "test_result", "investigation_charges", "total_amount"
    },
    "HOSPITAL_BILL": {
        "total_amount", "room_charges", "consultation_charges",
        "pharmacy_charges", "investigation_charges", "surgery_charges",
        "surgeon_fees", "anaesthesia_charges", "ot_charges", ...
    }
}
```

### Model Version Tracking

```python
ParseOutput.model_version = {
    "structured-llm": "Ollama Llama 3.2",
    "layoutlmv3": "microsoft/layoutlmv3-base",
    "heuristic-v2": "Regex + table extraction v2"
}

ParseOutput.used_fallback = {
    False: If LLM or LayoutLMv3 succeeded
    True: If heuristic was used
}
```

---

## Workflow Orchestration

### Service Architecture

**File**: `services/workflow/app/pipeline.py`

**NOT DAG-based**. Sequential HTTP polling with retry logic.

### Pipeline Steps

| Step | Method | Endpoint | Response | Poll? |
|------|--------|----------|----------|-------|
| 1. OCR | POST | `/ocr/{claim_id}` | 202 Accepted | ✅ Poll job status |
| 2. Parser | POST | `/parser/parse/{claim_id}` | 202 Accepted | ✅ Poll job status |
| 3. Coding | POST | `/coding/code-suggest/{claim_id}` | 200 OK | ❌ Sync |
| 4. Predictor | POST | `/predictor/predict/{claim_id}` | 200 OK | ❌ Sync |
| 5. Validator | POST | `/validator/validate/{claim_id}` | 200 OK | ❌ Sync |

### Async Step Polling

**File**: `services/workflow/app/pipeline.py` - `_wait_for_async_job()`

```python
def _wait_for_async_job(
    client: httpx.Client,
    step_name: str,
    poll_url: str,
) -> str:
    """Poll an async job until terminal state."""
    
    elapsed = 0.0
    MAX_WAIT = 1200  # 20 minutes (configurable)
    INTERVAL = 5     # 5 seconds (configurable)
    
    while elapsed < MAX_WAIT:
        time.sleep(INTERVAL)
        elapsed += INTERVAL
        
        try:
            resp = client.get(poll_url, timeout=120.0)
            
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status", "").upper()
                
                if status in ("COMPLETED", "DONE"):
                    return "COMPLETED"
                
                if status == "FAILED":
                    err = data.get("error_message", "unknown")
                    return f"FAILED:{err}"
                
                # Still running
                logger.debug(f"[{step_name}] Elapsed: {elapsed:.0f}s")
        
        except Exception as exc:
            logger.warning(f"Poll error for [{step_name}]: {exc}")
    
    return "FAILED:timeout waiting for job"
```

### HTTP Retry Logic

**File**: `services/workflow/app/pipeline.py` - `_call_with_retry()`

```python
def _call_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    max_retries: int = 3,
    backoff: float = 2.0,
) -> httpx.Response:
    """Call downstream service with exponential backoff."""
    
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"[{url}] Attempt {attempt}/{max_retries}")
            resp = client.request(method, url, timeout=120.0)
            
            if resp.status_code < 500:
                return resp  # 2xx, 3xx, 4xx
            
            logger.warning(
                f"Step {url} returned {resp.status_code} "
                f"(attempt {attempt}/{max_retries})"
            )
        
        except httpx.HTTPError as exc:
            logger.warning(
                f"Connection error (attempt {attempt}/{max_retries}): {exc}"
            )
        
        if attempt < max_retries:
            sleep_time = backoff * (2 ** (attempt - 1))
            time.sleep(sleep_time)
    
    raise RuntimeError(f"Step {url} failed after {max_retries} retries")
```

**Backoff Schedule**:
- Attempt 1: Immediate
- Attempt 2: 2.0s wait
- Attempt 3: 4.0s wait
- Attempt 4: 8.0s wait

### Workflow State Tracking

**File**: `libs/shared/models.py`

```python
class WorkflowState(Base):
    __tablename__ = "workflow_states"
    
    claim_id: UUID
    current_step: str  # OCR_IN_PROGRESS, PARSING_COMPLETED, FAILED, FINISHED
    status: str        # RUNNING, FAILED, FINISHED
    started_at: DateTime
    updated_at: DateTime
```

**Step Progression**:
```
OCR_IN_PROGRESS
    ↓
OCR_COMPLETED
    ↓
PARSING_IN_PROGRESS
    ↓
PARSING_COMPLETED
    ↓
CODING_ANALYSIS
    ↓
CODING_COMPLETED
    ↓
RISK_ANALYSIS
    ↓
RISK_COMPLETED
    ↓
VALIDATION_RUNNING
    ↓
VALIDATION_COMPLETED
    ↓
FINALIZING
    ↓
FINISHED (status=FINISHED)
```

### Error Handling: 409 Conflict

```python
if resp.status_code == 409:
    # Idempotency check: task already processed
    results.append(StepResult(
        step=step_name,
        status="SKIPPED",
        detail=resp.text
    ))
    continue  # Skip to next step
```

---

## Scaling & Fault Tolerance

### Kubernetes Horizontal Pod Autoscaler

**File**: `infra/k8s/hpa.yaml`

| Service | Min Replicas | Max Replicas | CPU Target | Memory Target |
|---------|--------------|--------------|-----------|---|
| Ingress | 2 | 10 | 70% | 80% |
| OCR | 2 | 8 | **60%** | 80% |
| Parser | 2 | 8 | 70% | 80% |
| Predictor | 2 | 6 | 70% | 80% |
| Validator | 2 | 6 | 70% | 80% |
| Workflow | 2 | 6 | 70% | 80% |
| Submission | 2 | 8 | 70% | 80% |

**Node Affinity**:
- OCR: CPU-pool nodes (compute-heavy Tesseract/PaddleOCR)

### Docker Compose Scaling

```yaml
worker_gpu:
  # Scale manually: docker-compose up -d --scale worker_gpu=3
  
worker_cpu:
  # Scale manually: docker-compose up -d --scale worker_cpu=8
```

### Fault Tolerance Mechanisms

#### 1. Celery Task Retries

```python
# Max 5 retries per task
@shared_task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,  # 10 min cap
    max_retries=5,
)
def ocr_task(self, claim_id):
    # Backoff: 1s, 2s, 4s, 8s, 16s, 32s, 64s, ...
    ...
```

#### 2. Dead Letter Queue

```python
Queue(
    "default",
    default_exchange,
    routing_key="default",
    queue_arguments={
        "x-dead-letter-exchange": "dead_letter",
        "x-dead-letter-routing-key": "dead_letter",
    }
)
```

**Failed Task Flow**:
```
Task Fails
    ↓
Retry (up to 5 times)
    ↓
Still Fails
    ↓
Route to: dead_letter_exchange → dead_letter queue
    ↓
Manual Intervention (Flower UI @ port 5555)
    └─→ Replay, debug, resolve
```

#### 3. Pipeline-Level Retries

Max 3 retries per workflow step with exponential backoff (2s base)

#### 4. Idempotency Guards

**OCR Level**:
```python
def calculate_claim_documents_set_hash(db, claim_id):
    # Hash all document content hashes
    # Skip reprocessing if hash matches
```

**Parser Level**:
```python
latest_job = db.query(ParseJob) \
    .filter(ParseJob.claim_id == job.claim_id) \
    .order_by(ParseJob.created_at.desc()) \
    .first()

if latest_job and latest_job.id != job.id:
    # Newer job exists, skip persistence
    job.error_message = "Superseded by newer parse job"
```

#### 5. Health Checks

**Liveness Probe** (K8s):
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 15
```

**Readiness Probe** (K8s):
```yaml
readinessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
```

**Health Endpoint Response**:
```json
{
  "status": "ok",
  "database": "up",
  "redis": "up",
  "dependencies": ["ocr", "parser"]
}
```

#### 6. Graceful Degradation

| Component | Degradation Path |
|-----------|------------------|
| **OCR** | PaddleOCR → Tesseract → Fail gracefully |
| **Parser** | LLM → LayoutLMv3 → Heuristic (guaranteed) |
| **Predictor** | XGBoost → LightGBM → Default score |
| **All Services** | Run standalone if dependencies fail |

---

## Implementation Status

### ✅ Fully Implemented

- [x] **Celery Task Orchestration**
  - Task routing to GPU/CPU queues
  - Retry logic with exponential backoff
  - Dead Letter Queue for failed tasks
  - Flower UI for monitoring

- [x] **OCR Service**
  - PaddleOCR (classic mode) + Tesseract fallback
  - Multi-format support (PDF, images, DOCX, Excel)
  - Advanced preprocessing pipeline
  - Set-based idempotency

- [x] **Parser Service**
  - Structured LLM extraction (Ollama Llama 3.2)
  - LayoutLMv3 backup model (available)
  - 40+ regex heuristics
  - Expense table 4-pass extraction
  - Document routing + field whitelisting

- [x] **Workflow Orchestration**
  - Sequential HTTP polling for async steps
  - Exponential backoff retry logic
  - WorkflowState tracking
  - 409 Conflict idempotency

- [x] **Scaling & Fault Tolerance**
  - Kubernetes HPA (2-10 replicas per service)
  - Health checks (liveness + readiness)
  - Graceful degradation
  - Dead letter queue handling

- [x] **Observability**
  - OpenTelemetry tracing
  - Prometheus metrics
  - Audit logging
  - Debug dumps (OCR + Parser)

### ❌ Not Implemented

- [ ] **DAG Orchestration** (Airflow/Prefect)
  - Using sequential HTTP polling instead

- [ ] **PaddleOCR-VL Mode** (disabled in config)
  - Classic mode only

- [ ] **scispaCy Medical NER** (disabled by default)
  - Optional enhancement, not core

- [ ] **LayoutLMv3 as Primary** (backup only)
  - Structured LLM is primary extraction

---

## Summary

ClaimGPT is a **production-ready microservices architecture** with:

1. **Task Orchestration**: Celery + Redis (not DAG-based)
2. **OCR**: PaddleOCR + Tesseract with advanced preprocessing
3. **Parsing**: LLM-first (Ollama) → LayoutLMv3 → Heuristic (guaranteed)
4. **Workflows**: HTTP polling with retry logic (not DAG)
5. **Scaling**: K8s HPA with health checks
6. **Fault Tolerance**: Multi-level retries, dead letter queue, idempotency guards

All components are resilient to failures with graceful fallbacks and comprehensive error handling.

---

**Document Generated**: April 29, 2026  
**Last Updated**: Current implementation  
**Maintainer**: ClaimGPT Development Team
