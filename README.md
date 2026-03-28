# ClaimGPT

AI-powered medical-claims processing platform. Ingest paper/electronic claims, extract structured data via OCR and NLP, assign medical codes, predict rejection risk, validate against payer rules, and submit to clearinghouses — all orchestrated through a microservice pipeline.

---

## Architecture

```
                        ┌─────────────┐
                        │   Web UI    │ (Next.js 15 — port 3000)
                        └──────┬──────┘
                               │
                        ┌──────┴──────┐
                        │  Admin UI   │ (Next.js 15 — port 3001)
                        └──────┬──────┘
                               │ REST
       ┌───────────────────────┼───────────────────────┐
       │                       │                       │
  ┌────▼────┐  ┌───────┐  ┌───▼────┐  ┌────────┐  ┌──▼───┐
  │ Ingress │→ │  OCR  │→ │ Parser │→ │ Coding │→ │Predict│
  │  8001   │  │ 8002  │  │  8003  │  │  8004  │  │ 8005  │
  └─────────┘  └───────┘  └────────┘  └────────┘  └──┬────┘
                                                      │
  ┌─────────┐  ┌────────┐  ┌──────────┐  ┌───────┐  ┌▼──────┐
  │  Chat   │  │ Search │  │Submission│← │Valid- │← │Work-  │
  │  8009   │  │  8010  │  │   8008   │  │ator  │  │ flow  │
  └─────────┘  └────────┘  └──────────┘  │ 8006  │  │ 8007  │
                                          └───────┘  └───────┘
```

### Services

| Service      | Port | Purpose                                           |
| ------------ | ---- | ------------------------------------------------- |
| **ingress**  | 8001 | Claim upload, file storage, deduplication          |
| **ocr**      | 8002 | PDF/image → text (Tesseract + OpenCV)              |
| **parser**   | 8003 | Structured field extraction (LayoutLMv3 + regex)   |
| **coding**   | 8004 | Medical NER → ICD-10 / CPT code assignment         |
| **predictor**| 8005 | Rejection risk scoring + feature store             |
| **validator**| 8006 | 10 deterministic rules (R001–R010)                 |
| **workflow** | 8007 | Pipeline orchestrator (OCR → Parse → Code → Predict → Validate) |
| **submission** | 8008 | Payer submission (FHIR R4, X12 837P, generic)    |
| **chat**     | 8009 | LLM chat with PHI scrubbing                       |
| **search**   | 8010 | Full-text + semantic vector search (FAISS)         |

### Shared Libraries (`libs/`)

| Library         | Purpose                                       |
| --------------- | --------------------------------------------- |
| **auth**        | JWT/JWKS verification, RBAC middleware         |
| **observability** | OpenTelemetry tracing, Prometheus metrics    |
| **schemas**     | Shared Pydantic models and event envelopes    |
| **utils**       | PHI scrubbing, audit logging                  |

---

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose v2
- Node.js 20+ (for UIs)
- (Optional) Tesseract OCR for local `ocr` service runs

### 1. Clone & configure

```bash
cp .env.example .env
# Edit .env — set DATABASE_URL, secrets, etc.
```

### 2. Start infrastructure

```bash
make dev          # Postgres 16, Redis 7, MinIO
```

### 3. Run a single service locally

```bash
# Install all Python deps
make install

# Start (e.g.) the ingress service
./infra/scripts/run-service.sh ingress
```

### 4. Run the full stack via Docker

```bash
make up           # builds & starts all 10 services + infra
make health       # verify every service is healthy
```

### 5. Run tests

```bash
make test         # pytest with coverage
make lint         # ruff + mypy
```

---

## Project Structure

```
claimgpt/
├── services/          # 10 FastAPI microservices
│   ├── ingress/
│   ├── ocr/
│   ├── parser/
│   ├── coding/
│   ├── predictor/
│   ├── validator/
│   ├── workflow/
│   ├── submission/
│   ├── chat/
│   └── search/
├── libs/              # Shared Python libraries
│   ├── auth/
│   ├── observability/
│   ├── schemas/
│   └── utils/
├── infra/
│   ├── db/            # PostgreSQL schema (13 tables)
│   ├── docker/        # Compose + Dockerfiles
│   ├── k8s/           # Kubernetes manifests
│   └── scripts/       # Dev & ops scripts
├── tests/             # Pytest test suite (60+ tests)
├── ui/
│   ├── admin/         # Admin dashboard (Next.js)
│   └── web/           # Patient portal (Next.js)
├── Makefile
├── pyproject.toml
├── requirements-dev.txt
└── .github/workflows/ci.yml
```

---

## Database

PostgreSQL 16 with 13 tables defined in [`infra/db/claimgpt_schema.sql`](infra/db/claimgpt_schema.sql):

`claims` · `documents` · `ocr_results` · `ocr_jobs` · `parsed_fields` · `parse_jobs` · `medical_entities` · `medical_codes` · `features` · `predictions` · `validations` · `workflow_jobs` · `submissions` · `chat_messages` · `audit_logs`

Each service owns its own SQLAlchemy ORM models mapped to these shared tables.

---

## API Endpoints (summary)

| Service    | Method | Path                        | Description                    |
| ---------- | ------ | --------------------------- | ------------------------------ |
| ingress    | POST   | `/claims`                   | Upload a new claim             |
| ingress    | GET    | `/claims`                   | List claims (paginated)        |
| ocr        | POST   | `/ocr`                      | Extract text from document     |
| parser     | POST   | `/parse`                    | Extract structured fields      |
| coding     | POST   | `/code`                     | Assign ICD-10/CPT codes        |
| predictor  | POST   | `/predict`                  | Score rejection risk           |
| predictor  | GET    | `/features/{claim_id}`      | Get feature vector             |
| validator  | POST   | `/validate`                 | Run validation rules           |
| workflow   | POST   | `/workflow`                 | Start end-to-end pipeline      |
| submission | POST   | `/submit`                   | Submit to payer                |
| chat       | POST   | `/chat`                     | Chat with LLM                  |
| search     | GET    | `/search`                   | Full-text + vector search      |
| search     | POST   | `/index/{claim_id}`         | Index claim for vector search  |
| *all*      | GET    | `/health`                   | Health check                   |

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
