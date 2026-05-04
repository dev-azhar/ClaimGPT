---

# ClaimGPT Architectural & Service Specification Report

## 1. Executive Summary
ClaimGPT is a distributed, asynchronous document processing platform designed to ingest medical insurance documents and produce validated, risk-assessed claim reports. The architecture utilizes a "Cheapest-Path" strategy to prioritize digital data extraction while maintaining a high-fidelity image processing pipeline for scanned documents.

---

## 2. Infrastructure & Orchestration
The system's foundation rests on a producer-consumer model to manage high-latency tasks.

*   **Task Broker (Redis):** Manages the communication between the API and background workers. It handles task "chains" (sequential) and "chords" (parallel) to ensure a controlled data flow.
*   **Worker Strategy (Celery):** 
    *   **GPU Workers (`gpu_queue`):** Reserved for OCR and image preprocessing to prevent resource contention.
    *   **CPU Workers (`default` queue):** Handle medical coding, risk prediction, and deterministic validation rules.
*   **Data Persistence (PostgreSQL):** Stores business entities, OCR text results, and structured `ParsedField` rows.

---

## 3. The Extraction Pipeline

### Stage 1: Ingestion & Routing
*   **Deduplication:** Every file is assigned a SHA-256 content hash upon upload.
*   **Format Routing:** Digital PDFs are sent to `pdfplumber` for immediate text and table extraction. Scanned documents are routed to the image preprocessing pipeline.

### Stage 2: Image Preprocessing (OCR Only)
Before OCR inference, images undergo a specific **OpenCV** sequence:
*   **Denoising:** `fastNlMeansDenoising` removes artifacts.
*   **Contrast Enhancement:** `CLAHE` sharpens text-background separation.
*   **Deskewing:** `minAreaRect` corrects tilts $\geq 0.5^{\circ}$ to maintain coordinate accuracy.

### Stage 3: OCR Engines
*   **EasyOCR/PaddleOCR:** Primary engines for rasterized text.
*   **Tesseract:** Acts as a fallback if confidence scores drop below 60%.

### Stage 4: The Parser (Spatial & Semantic)
The parser transforms raw strings into medical categories using a five-pass heuristic system.
*   **Vertical Binning:** Groups fragments into 10-unit vertical (Y-axis) buckets to pair descriptions and amounts in the absence of table borders.
*   **Dynamic Labeling:** Unknown labels are sanitized into unique keys (e.g., `labour_charges_expense`) to prevent "Other Charges" grouping and data loss.

---

## 4. Intelligence & Validation Services
Once data is parsed, a parallel **Celery Chord** fans out three services:

| Service | Technology Used | Function |
| :--- | :--- | :--- |
| **Coding** | scispaCy (NER) | Maps medical entities to ICD-10/CPT codes. |
| **Predictor** | XGBoost / LightGBM | Predicts rejection probability based on historical patterns. |
| **Validator** | Rule-based engine | Checks for clinical and mathematical consistency. |

---

## 5. Financial Reconciliation Logic
The **Submission Service** ensures the itemized expenses reflect the physical bill.

*   **Anchor Total:** Scans for "Grand Total" or "Net Payable" as the master financial truth.
*   **Source Priority:** Enforces a hierarchy: **HOSPITAL_BILL > PHARMACY_INVOICE > LAB_REPORT**.
*   **De-duplication:** If an amount appears on both a bill and a supporting invoice, the bill's value is used to prevent double-counting.
*   **Reconciliation Flag:** Emits a warning if the itemized sum differs from the Anchor Total by $>1\%$.

---

## 6. Critical Operational Risks
*   **Scalability:** Current `gpu_queue` concurrency is set to 1, leading to linear backlogs under heavy load.
*   **Persistence:** The "delete-then-insert" model for `ParsedField` risks database contention at high concurrency.
*   **Attribution:** Page-number-only mapping can cause data collisions in multi-document claims.