# ClaimGPT — Packages & Dependencies

## Root Dependencies (`requirements.txt`)

### Core Framework

| Package              | Version   | Purpose                                  |
| -------------------- | --------- | ---------------------------------------- |
| `fastapi`            | 0.128.8   | Async web framework (OpenAPI, validation)|
| `uvicorn`            | 0.39.0    | ASGI server                              |
| `httptools`          | 0.6.4     | Fast HTTP parser for uvicorn             |
| `uvloop`             | 0.21.0    | High-performance event loop (Unix only)  |
| `SQLAlchemy`         | 2.0.48    | ORM + database abstraction               |
| `psycopg2-binary`    | 2.9.11    | PostgreSQL driver                        |
| `pydantic`           | 2.12.5    | Data validation & serialization          |
| `pydantic-settings`  | 2.9.1     | Settings management via env vars         |
| `python-multipart`   | 0.0.20    | Multipart form parsing (file uploads)    |
| `aiofiles`           | 24.1.0    | Async file I/O                           |
| `httpx`              | 0.28.1    | Async HTTP client (inter-service calls)  |

### OCR & Document Processing

| Package                      | Version   | Purpose                                |
| ---------------------------- | --------- | -------------------------------------- |
| `pytesseract`                | 0.3.13    | Python wrapper for Tesseract OCR       |
| `pdfplumber`                 | 0.11.4    | PDF text/table extraction              |
| `Pillow`                     | 11.2.1    | Image manipulation                     |
| `opencv-python-headless`     | 4.11.0.86 | Image preprocessing (denoise, deskew)  |
| `python-docx`                | 1.1.2     | DOCX file reading                      |
| `openpyxl`                   | 3.1.5     | XLSX/XLS file reading                  |
| `pdf2image`                  | 1.17.0    | PDF → image conversion (for OCR)       |
| `numpy`                      | ≥1.26.0   | Numerical operations                   |

### ML & NLP

| Package              | Version   | Purpose                                     |
| -------------------- | --------- | ------------------------------------------- |
| `transformers`       | ≥4.40.0   | LayoutLMv3 (parser), BioGPT (coding)        |
| `torch`              | ≥2.1.0    | PyTorch (model inference)                    |
| `accelerate`         | ≥0.28.0   | HuggingFace model loading                    |
| `sentencepiece`      | ≥0.2.0    | Tokenizer for multilingual models            |
| `protobuf`           | ≥4.25.0   | Serialization for ML models                  |
| `sacremoses`         | ≥0.1.0    | Tokenization/detokenization utilities        |
| `xgboost`            | ≥2.0.0    | Gradient-boosted trees (rejection predictor) |
| `lightgbm`           | ≥4.0.0    | Ensemble model (secondary scorer)            |

### Search

| Package                | Version       | Purpose                               |
| ---------------------- | ------------- | ------------------------------------- |
| `sentence-transformers`| 3.4.1         | Text → embedding vectors              |
| `faiss-cpu`            | 1.9.0.post1   | Approximate nearest neighbor search   |

---

## Dev Dependencies (`requirements-dev.txt`)

| Package          | Version | Purpose                         |
| ---------------- | ------- | ------------------------------- |
| `pytest`         | 8.3.5   | Test runner                     |
| `pytest-asyncio` | 0.24.0  | Async test support              |
| `httpx`          | 0.28.1  | Test client for FastAPI         |
| `ruff`           | 0.9.10  | Linter + formatter              |
| `mypy`           | 1.15.0  | Static type checker             |

---

## Service-Specific Dependencies

Each service under `services/` has its own `requirements.txt`. Below are packages **unique** to each service (beyond the root requirements).

### OCR Service

| Package          | Note                                          |
| ---------------- | --------------------------------------------- |
| `tesseract-ocr`  | **System package** — must be installed via OS package manager |
| `libleptonica-dev`| System dep for Tesseract                     |

**macOS:** `brew install tesseract`
**Windows:** Download installer from [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) or `choco install tesseract`

### Parser Service

| Package        | Version  | Purpose                         |
| -------------- | -------- | ------------------------------- |
| `transformers` | ≥4.40.0  | LayoutLMv3 token classification |
| `torch`        | ≥2.2.0   | Model inference                 |

### Coding Service

| Package    | Version  | Purpose                              |
| ---------- | -------- | ------------------------------------ |
| `spacy`    | ≥3.7.0   | NLP pipeline framework               |
| `scispacy` | ≥0.5.4   | Biomedical NER (en_ner_bc5cdr_md)    |

**Model download:** `pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz`

### Predictor Service

| Package    | Version  | Purpose                      |
| ---------- | -------- | ---------------------------- |
| `xgboost`  | ≥2.0.0   | Primary rejection scorer     |
| `lightgbm` | ≥4.0.0   | Secondary ensemble scorer    |

### Chat Service

| Package        | Note                                    |
| -------------- | --------------------------------------- |
| `httpx`        | Ollama / external LLM provider calls    |
| `python-docx`  | Document reading in chat context        |
| `openpyxl`     | Spreadsheet reading in chat context     |

### Search Service

| Package                | Note                            |
| ---------------------- | ------------------------------- |
| `sentence-transformers`| Text embedding (all-MiniLM-L6-v2) |
| `faiss-cpu`            | Vector index & similarity search |

---

## Infrastructure Dependencies

| Component        | Version      | Purpose                   | Default Port |
| ---------------- | ------------ | ------------------------- | ------------ |
| PostgreSQL       | 16-alpine    | Primary database          | 5432         |
| Redis            | 7-alpine     | Caching / pub-sub (ready) | 6379         |
| MinIO            | latest       | S3-compatible storage     | 9000 / 9001  |
| Keycloak         | 24.0         | OIDC / SSO / RBAC         | 8080         |
| Ollama           | latest       | Local LLM (Llama 3.2)    | 11434        |
| Tesseract OCR    | 5.x          | OCR engine (system dep)   | —            |

---

## Frontend Dependencies

### Web UI (`ui/web/package.json`)

| Package     | Purpose                |
| ----------- | ---------------------- |
| `next`      | React framework (v15)  |
| `react`     | UI library (v19)       |
| `react-dom` | DOM renderer           |

### Admin UI (`ui/admin/package.json`)

| Package     | Purpose                |
| ----------- | ---------------------- |
| `next`      | React framework (v15)  |
| `react`     | UI library (v19)       |
| `react-dom` | DOM renderer           |

---

## ML Model Artifacts (`models/`)

| File                        | Format    | Purpose                                      |
| --------------------------- | --------- | -------------------------------------------- |
| `xgb_rejection.json`       | XGBoost   | Primary rejection risk model                 |
| `xgb_feature_importance.json` | JSON   | Feature importance for explainability         |
| `lgbm_rejection.txt`       | LightGBM  | Secondary ensemble model                     |

> Models are auto-trained on synthetic data if not present at predictor startup.

---

## Installation Notes

### macOS

```bash
# System deps
brew install tesseract poppler

# Python deps
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional: scispaCy biomedical model
pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz
```

### Windows

```powershell
# System deps
choco install tesseract poppler

# Python deps
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Optional: scispaCy biomedical model
pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz
```

> **Windows Tip:** If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` first.
