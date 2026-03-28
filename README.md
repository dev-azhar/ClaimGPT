# ClaimGPT

AI-powered medical insurance claim processing platform. Upload claim documents, automatically extract data via OCR, assign ICD-10/CPT codes, predict rejection risk, validate against payer rules, analyze medical scans, cross-reference documents for reimbursement intelligence, and generate TPA-ready PDF reports — all through a unified API gateway and a ChatGPT-style conversational UI.

---

## Architecture

```
  ┌─────────────────┐        ┌──────────────────┐
  │    Web UI        │        │    Admin UI       │
  │  Next.js 15      │        │  Next.js 15       │
  │  React 19        │        │  React 19         │
  │  port 3000       │        │  port 3001        │
  └────────┬─────────┘        └────────┬──────────┘
           │          REST / SSE       │
           └────────────┬──────────────┘
                        │
           ┌────────────▼────────────────┐
           │     Unified API Gateway     │
           │     FastAPI · port 8000     │
           │     /docs (Swagger UI)      │
           └────────────┬────────────────┘
                        │ Internal Router
    ┌───────────────────┼────────────────────────┐
    │         │         │         │               │
    ▼         ▼         ▼         ▼               ▼
 ┌───────┐ ┌─────┐ ┌───────┐ ┌───────┐    ┌──────────┐
 │Ingress│ │ OCR │ │Parser │ │Coding │    │Predictor │
 │/ingres│ │/ocr │ │/parser│ │/coding│    │/predictor│
 └───┬───┘ └──┬──┘ └───┬───┘ └───┬───┘    └────┬─────┘
     │        │        │         │              │
     │   ┌────▼────┐   │         │              │
     │   │  Scan   │   │         │              │
     │   │Analyzer │   │         │              │
     │   └─────────┘   │         │              │
     │                  │         │              │
    ┌▼──────────────────▼─────────▼──────────────▼──┐
    │              Workflow Orchestrator             │
    │              /workflow                         │
    │   OCR → Parse → Code → Predict → Validate     │
    └──────────────────────┬────────────────────────┘
                           │
    ┌──────────┬───────────┼───────────┬────────────┐
    ▼          ▼           ▼           ▼            ▼
 ┌──────┐ ┌───────┐ ┌──────────┐ ┌──────┐   ┌──────┐
 │Valid-│ │Submit │ │   Chat   │ │Search│   │ TPA  │
 │ator │ │ /sub- │ │  /chat   │ │/sear-│   │ PDF  │
 │/vali-│ │mission│ │ 7 LLM   │ │ch    │   │Report│
 │date  │ │       │ │providers │ │      │   │      │
 └──────┘ └───┬───┘ └──────────┘ └──────┘   └──────┘
              │
       ┌──────▼───────┐
       │Reimbursement │
       │  Brain       │
       │Cross-doc AI  │
       └──────────────┘

    ┌────────────────────────────────────────────────┐
    │            PostgreSQL 16 (16 tables)            │
    │  claims · documents · ocr_results · ocr_jobs   │
    │  parsed_fields · parse_jobs · medical_entities  │
    │  medical_codes · features · predictions         │
    │  validations · workflow_jobs · submissions      │
    │  chat_messages · audit_logs · scan_analyses     │
    └────────────────────────────────────────────────┘
    ┌──────────┐  ┌──────────┐  ┌──────────────────┐
    │  Ollama  │  │  MinIO   │  │   Keycloak       │
    │ Llama3.2 │  │ Storage  │  │   Auth / RBAC    │
    │ :11434   │  │          │  │                  │
    └──────────┘  └──────────┘  └──────────────────┘
```

### How It Works

1. **Upload** — Drop claim documents (PDF, images, Word, Excel, CSV) via Web UI or REST API
2. **OCR** — Tesseract + OpenCV extract text; scan analyzer detects MRI/CT/X-Ray/Ultrasound reports
3. **Parse** — LayoutLMv3 + regex extract 20+ structured fields (patient, diagnosis, expenses, etc.)
4. **Code** — NER engine assigns ICD-10 diagnosis codes and CPT procedure codes with cost estimates
5. **Predict** — XGBoost + LightGBM score rejection risk with top contributing factors
6. **Validate** — 10 deterministic rules (R001–R010) check completeness, date logic, coding validity
7. **Reimbursement Brain** — Cross-references all documents, verifies data consistency, builds readiness checklist
8. **Chat** — Ask questions about any claim via 7 LLM providers (Groq, Gemini, Claude, GPT-4o, Ollama, HuggingFace, OpenAI-compatible)
9. **Submit** — Generate TPA PDF reports or submit via FHIR R4 / X12 837P adapters

---

### Services

| Service        | Route         | Purpose                                                    |
| -------------- | ------------- | ---------------------------------------------------------- |
| **ingress**    | `/ingress`    | Claim upload, multi-file support, document management      |
| **ocr**        | `/ocr`        | PDF/image → text (Tesseract + OpenCV) + medical scan analysis |
| **parser**     | `/parser`     | Structured field extraction (LayoutLMv3 + regex, 20+ fields) |
| **coding**     | `/coding`     | ICD-10 / CPT code assignment with cost estimation          |
| **predictor**  | `/predictor`  | Rejection risk scoring (XGBoost + LightGBM) + feature store |
| **validator**  | `/validator`  | 10 deterministic rules (R001–R010)                         |
| **workflow**   | `/workflow`   | Pipeline orchestrator (OCR → Parse → Code → Predict → Validate) |
| **submission** | `/submission` | TPA PDF generation, reimbursement brain, payer submission  |
| **chat**       | `/chat`       | LLM chat with streaming, 7 providers, PHI scrubbing       |
| **search**     | `/search`     | Full-text + semantic vector search (FAISS)                 |

> All services are routed through a **unified API gateway** on **port 8000**. Each service can also be run standalone.

### Shared Libraries (`libs/`)

| Library           | Purpose                                       |
| ----------------- | --------------------------------------------- |
| **auth**          | JWT/JWKS verification, RBAC middleware         |
| **observability** | OpenTelemetry tracing, Prometheus metrics      |
| **schemas**       | Shared Pydantic models and event envelopes     |
| **utils**         | PHI scrubbing, audit logging                   |

---

## Key Features

- **Unified API Gateway** — Single FastAPI app (port 8000) routing to 10 microservices with Swagger UI at `/docs`
- **ChatGPT-Style UI** — Conversational interface with streaming responses, auto-suggestions, and starter prompts
- **7 LLM Providers** — Groq (Llama 3), Google Gemini, Anthropic Claude, OpenAI GPT-4o, Ollama (local), HuggingFace, OpenAI-compatible
- **Multi-File Upload** — Drag & drop, camera capture, screenshot support with smart document routing
- **Medical Scan Analyzer** — Auto-detects MRI, CT, X-Ray, Ultrasound, PET, Mammography reports; extracts findings with severity classification
- **Hospital Expense Extraction** — 8 categories (room, consultation, pharmacy, surgery, OT, anaesthesia, consumables, nursing)
- **Cross-Document Reimbursement Brain** — Classifies documents, cross-references fields across docs, builds reimbursement readiness checklist (75%+ completeness scoring)
- **TPA PDF Reports** — Professional claim reports with brain insights, expense breakdown, and medical code tables
- **AI Brain Preview** — Collapsible sections with KPI strip, verdict badge, risk assessment, validation rules, and sticky action footer
- **INR Currency** — All costs displayed in Rs. (Indian Rupees) with en-IN formatting

---

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose v2
- Node.js 20+ (for UIs)
- PostgreSQL 16
- (Optional) Ollama with Llama 3.2 for local LLM
- (Optional) Tesseract OCR for local OCR

### 1. Clone & configure

```bash
git clone https://github.com/dev-azhar/ClaimGPT.git
cd ClaimGPT
cp .env.example .env
# Edit .env — set DATABASE_URL, LLM keys, etc.
```

### 2. Start infrastructure

```bash
make dev          # Postgres 16, Redis 7, MinIO
```

### 3. Run the unified API gateway

```bash
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Run the Web UI

```bash
npm --prefix ui/web install
npm --prefix ui/web run dev    # http://localhost:3000
```

### 5. Run the full stack via Docker

```bash
make up           # builds & starts all 10 services + infra
make health       # verify every service is healthy
```

### 6. Run tests

```bash
make test         # pytest with coverage
make lint         # ruff + mypy
```

---

## Project Structure

```
ClaimGPT/
├── main.py                # Unified API Gateway (port 8000)
├── services/              # 10 FastAPI microservices
│   ├── ingress/           # Claim upload & document management
│   ├── ocr/               # OCR + medical scan analyzer
│   ├── parser/            # Structured field extraction
│   ├── coding/            # ICD-10 / CPT coding engine
│   ├── predictor/         # ML rejection prediction
│   ├── validator/         # Rule-based validation
│   ├── workflow/          # Pipeline orchestrator
│   ├── submission/        # TPA PDF, reimbursement brain, payer submission
│   ├── chat/              # LLM chat (7 providers, streaming)
│   └── search/            # Full-text + vector search
├── libs/                  # Shared Python libraries
│   ├── auth/              # JWT/RBAC middleware
│   ├── observability/     # Tracing & metrics
│   ├── schemas/           # Shared Pydantic models
│   └── utils/             # PHI scrubbing, audit logging
├── models/                # ML model artifacts (XGBoost, LightGBM)
├── infra/
│   ├── db/                # PostgreSQL schema (16 tables)
│   ├── docker/            # Compose + Dockerfiles
│   ├── k8s/               # Kubernetes manifests
│   ├── keycloak/          # Auth realm config
│   └── scripts/           # Dev & ops scripts
├── tests/                 # Pytest test suite
├── ui/
│   ├── web/               # Web UI (Next.js 15 + React 19)
│   └── admin/             # Admin dashboard (Next.js 15)
├── Makefile
├── pyproject.toml
└── .github/workflows/ci.yml
```

---

## Database

PostgreSQL 16 with **16 tables** defined in [`infra/db/claimgpt_schema.sql`](infra/db/claimgpt_schema.sql):

`claims` · `documents` · `ocr_results` · `ocr_jobs` · `parsed_fields` · `parse_jobs` · `medical_entities` · `medical_codes` · `features` · `predictions` · `validations` · `workflow_jobs` · `submissions` · `chat_messages` · `audit_logs` · `scan_analyses`

Each service owns its own SQLAlchemy ORM models mapped to these shared tables.

---

## API Endpoints (summary)

> All endpoints are prefixed with the service route (e.g., `/ingress/claims`, `/chat/{session_id}/stream`).  
> Swagger UI available at `http://localhost:8000/docs`.

| Service    | Method   | Path                                  | Description                           |
| ---------- | -------- | ------------------------------------- | ------------------------------------- |
| ingress    | `POST`   | `/ingress/claims`                     | Upload a new claim (multipart)        |
| ingress    | `POST`   | `/ingress/claims/{id}/documents`      | Add documents to existing claim       |
| ingress    | `GET`    | `/ingress/claims`                     | List claims (paginated)               |
| ingress    | `GET`    | `/ingress/claims/{id}`                | Get claim details                     |
| ingress    | `GET`    | `/ingress/claims/{id}/file`           | Download original file                |
| ingress    | `GET`    | `/ingress/claims/{id}/audit`          | Audit trail for claim                 |
| ingress    | `DELETE` | `/ingress/claims/{id}`                | Delete claim                          |
| ingress    | `DELETE` | `/ingress/claims/{id}/documents/{did}`| Remove single document                |
| ocr        | `POST`   | `/ocr/{claim_id}`                     | Start OCR job                         |
| ocr        | `GET`    | `/ocr/claim/{claim_id}`               | Get OCR results for claim             |
| parser     | `POST`   | `/parser/parse/{claim_id}`            | Start parsing job                     |
| parser     | `GET`    | `/parser/parse/{claim_id}`            | Get parsed fields                     |
| coding     | `POST`   | `/coding/code-suggest/{claim_id}`     | Assign ICD-10/CPT codes               |
| coding     | `GET`    | `/coding/code-suggest/{claim_id}`     | Get assigned codes                    |
| predictor  | `POST`   | `/predictor/predict/{claim_id}`       | Score rejection risk                  |
| predictor  | `GET`    | `/predictor/features/{claim_id}`      | Get feature vector                    |
| validator  | `POST`   | `/validator/validate/{claim_id}`      | Run validation rules                  |
| workflow   | `POST`   | `/workflow/start/{claim_id}`          | Start end-to-end pipeline             |
| submission | `POST`   | `/submission/submit/{claim_id}`       | Submit to payer                       |
| submission | `GET`    | `/submission/claims/{id}/preview`     | Full claim preview (JSON)             |
| submission | `GET`    | `/submission/claims/{id}/tpa-pdf`     | Generate TPA PDF report               |
| submission | `POST`   | `/submission/claims/{id}/code-feedback`| Code accept/reject feedback          |
| chat       | `POST`   | `/chat/{session_id}/message`          | Send chat message                     |
| chat       | `POST`   | `/chat/{session_id}/stream`           | Stream chat response (SSE)            |
| chat       | `GET`    | `/chat/{session_id}/history`          | Get chat history                      |
| chat       | `GET`    | `/chat/providers`                     | List available LLM providers          |
| search     | `GET`    | `/search/`                            | Full-text search                      |
| search     | `POST`   | `/search/vector-search`               | Semantic vector search                |
| search     | `POST`   | `/search/index/{claim_id}`            | Index claim for search                |
| *all*      | `GET`    | `/{service}/health`                   | Health check                          |

---

## Deployment

### Docker Compose (local / staging)

```bash
make up       # start everything
make down     # stop everything
make build    # rebuild images
```

### Kubernetes

Manifests in `infra/k8s/`:

```bash
kubectl apply -f infra/k8s/namespace.yaml
kubectl apply -f infra/k8s/config.yaml
kubectl apply -f infra/k8s/services.yaml
kubectl apply -f infra/k8s/hpa.yaml
```

HPA auto-scales ingress, ocr, workflow, and submission services.

---

## Security & Compliance

- **Auth**: Keycloak JWKS + HS256 JWT fallback; RBAC roles (`admin`, `reviewer`, `submitter`, `viewer`)
- **PHI**: Automated scrubbing via `libs/utils/phi.py` (SSN, phone, email, MRN, DOB, policy patterns)
- **Audit**: All mutations logged to `audit_logs` table with user, action, and before/after snapshots
- **Network**: CORS allowlist; internal services communicate over private Docker/K8s network
- **HIPAA**: PHI never sent to external LLM; scrubbed before chat context

---

## Contributing

1. Create a feature branch from `develop`
2. Write tests (`make test`)
3. Lint (`make lint`)
4. Open a PR — CI runs automatically

---

## License

Proprietary — all rights reserved.
