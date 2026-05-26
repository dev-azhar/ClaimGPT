# Model Inventory — Full Pipeline Trace

## Claim 1: Two Images (claim_id=324eaeb8, 115s total)
## Claim 2: PDF File (claim_id=d76f99aa, 73s total)

---

## Step 1 — OCR Service (`gpu_queue` worker)

| Model | Type | Used When | Memory/Cost |
|---|---|---|---|
| **EasyOCR** (CRAFT + CRNN) | Deep learning OCR | Images — primary path | Heavy: loads PyTorch, CRAFT detector + CRNN recognizer ~300MB |
| **PP-OCRv5_server_rec** | PaddleOCR recognition | Cached, available as fallback | ~200MB (Paddle) |
| **PDF text extractor** | Direct extraction (no model) | PDF files — 1.6s flat | Zero — reads PDF text layer directly |

**From logs:**
- Claim 1 (images): `EasyOCR lazily initialized` → 55.5s for 2 images
- Claim 2 (PDF): `pdf-page:ok`, quality score=1.00 → 1.6s (no OCR model at all)

> **The OCR model (EasyOCR) only loads for image-based claims. PDFs skip it entirely.**

---

## Step 2 — Parser Service (`default` queue worker)

| Model | Type | Used When | Memory/Cost |
|---|---|---|---|
| **PaddleX PP-DocLayoutV3** | Layout analysis CNN | Every claim — parses bounding boxes and sections | Heavy: ~500MB, loaded locally from .paddlex cache |
| **OpenRouter GPT-4o-mini** | External LLM (API) | Field extraction for complex image documents | API call cost — 7 calls seen for image claim |

**From logs:**
- `_parse_pp_structure_output called` → Successfully handles wrapped `LayoutAnalysisResult` formats, canonicalizing layout sections (e.g. text regions and table bboxes). If the model finds a layout area but no explicit grid tables are detected, the system applies a robust geometric heuristic scanner.
- `HTTP Request: POST openrouter.ai` × 7 calls (image claim, 2.6s–10s each)
- `HTTP Request: POST openrouter.ai` × 0 calls (PDF — text extraction was clean enough)

> **The layout model is fully operational and parsed. It works in tandem with the OpenRouter LLM, which extracts key patient and billing fields.**

---

## Step 3 — Coding Service (`default` queue worker)

| Model | Type | Used When | Memory/Cost |
|---|---|---|---|
| **S-PubMedBert-MS-MARCO** | Bi-encoder (sentence-transformers) | Every claim — encodes diagnosis query → FAISS vector search | Medium: ~440MB, loaded once, stays in memory |
| **FAISS index** | Vector index (11,243 ICD codes) | Every claim — dense retrieval of top-50 candidates | ~35MB RAM |
| **BM25 index** | Sparse lexical index | Every claim — hybrid retrieval alongside FAISS | ~8MB RAM |
| **cross-encoder/ms-marco-MiniLM-L-6-v2** | Cross-encoder reranker | Every claim — final ICD code selection | Medium: ~120MB, lazy-loaded on first rerank |
| **scispaCy en_ner_bc5cdr_md** | Biomedical NER | Supplementary signal after LLM extraction | Medium: ~200MB |
| **OpenRouter GPT-4o-mini** | External LLM (API) | Diagnosis terminology extraction from OCR text | 2 API calls seen — one per diagnosis entity |

**From logs (d76f99aa claim):**
```
HTTP Request: POST openrouter.ai  ← diagnosis extraction call 1
Persisted OpenRouter diagnosis extraction ...
HTTP Request: POST openrouter.ai  ← diagnosis extraction call 2
Persisted OpenRouter diagnosis extraction ...
Coding complete — 2 entities, 8 codes   (11.2s total)
```

> **S-PubMedBert is NOT the reranker — it's the FAISS search engine.**  
> **The cross-encoder is the final decision maker (new, replaces dead stub).**  
> **LLM is for extraction only — NOT for reranking.**

---

## Step 4 — Risk Service (`default` queue worker)

| Model | Type | Used When | Memory/Cost |
|---|---|---|---|
| **XGBoost** (trained model) | Gradient boosting classifier | Every claim — rejection probability | Tiny: <5MB, instant inference |
| **LightGBM** (trained model) | Gradient boosting classifier | Every claim — ensembled with XGBoost | Tiny: <5MB, instant inference |

**From logs:**
```
XGBoost predicted rejection probability: 0.147
LightGBM predicted rejection probability: 0.069
Ensembled (w=0.44): 0.103  → LOW risk
```
> **Fast — both run in <1ms on CPU. No GPU needed.**

---

## Step 5 — Validator Service

| Model | Type | Used | Memory/Cost |
|---|---|---|---|
| **Rule engine** | Pure Python logic | Every claim — 11 rules checked | Zero |

---

## Summary: What's Actually Heavy

```
┌──────────────────────────────────────────────────────────────┐
│  SERVICE     MODEL                    SIZE    WHEN ACTIVE     │
├──────────────────────────────────────────────────────────────┤
│  OCR         EasyOCR (CRAFT+CRNN)    ~300MB  Images only     │
│              PP-OCRv5_server_rec     ~200MB  Fallback        │
│              PaddleX Layout V3       ~500MB  Every claim*    │
├──────────────────────────────────────────────────────────────┤
│  PARSER      GPT-4o-mini (API)       0MB     Image claims    │
├──────────────────────────────────────────────────────────────┤
│  CODING      S-PubMedBert            ~440MB  Every claim     │
│              FAISS index             ~35MB   Every claim     │
│              cross-encoder MiniLM    ~120MB  Every claim     │
│              scispaCy bc5cdr         ~200MB  Supplementary   │
│              GPT-4o-mini (API)       0MB     Per diagnosis   │
├──────────────────────────────────────────────────────────────┤
│  RISK        XGBoost + LightGBM      <10MB   Every claim     │
└──────────────────────────────────────────────────────────────┘

* PaddleX Layout PP-DocLayoutV3 is fully operational and integrated with structural result parsing.

Total in-process memory (coding worker): ~795MB
Total in-process memory (OCR/GPU worker): ~1GB+ for images
```

---

## Image vs PDF: Key Difference

| Step | PDF Claim | Image Claim |
|---|---|---|
| OCR | 1.6s (text extraction) | 55s (EasyOCR deep learning) |
| Parser LLM calls | 0 | 7 |
| Coding LLM calls | 2 | 2 |
| Total time | 73s | 115s |

The extra 42s for images is entirely EasyOCR + parser LLM calls.
