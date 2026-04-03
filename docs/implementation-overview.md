# ClaimGPT — Implementation Overview

## Tech Stack

| Layer            | Technology                                                   |
| ---------------- | ------------------------------------------------------------ |
| **API Framework**| FastAPI 0.128 + Uvicorn 0.39                                 |
| **ORM**          | SQLAlchemy 2.0                                               |
| **Database**     | PostgreSQL 16 (18 tables)                                    |
| **OCR**          | Tesseract 5 + OpenCV 4.11 + pdfplumber                       |
| **NLP / NER**    | scispaCy (en_ner_bc5cdr_md), BioGPT, LayoutLMv3              |
| **ML**           | XGBoost 2.x, LightGBM 4.x                                    |
| **Search**       | FAISS (faiss-cpu), Sentence-Transformers (all-MiniLM-L6-v2)  |
| **LLM**          | Ollama (Llama 3.2), OpenAI, Anthropic, Cohere, Together, Replicate |
| **Auth**         | Keycloak 24 (OIDC / JWKS), HS256 JWT fallback                |
| **Storage**      | MinIO (S3-compatible), local filesystem fallback              |
| **Observability**| OpenTelemetry (Jaeger/Tempo), Prometheus                      |
| **Frontend**     | Next.js 15 + React 19 (Web UI + Admin UI)                    |
| **Containers**   | Docker Compose v2, Kubernetes (HPA)                           |
| **CI/CD**        | GitHub Actions                                                |
| **Language**     | Python 3.12+, TypeScript / Node.js 20+                       |

---

## Architecture Pattern

**Unified API Gateway** — A single FastAPI process (`main.py`, port 8000) dynamically imports routers from 10 microservices and exposes them under prefixed routes. Each service can also run standalone via its own `app/main.py`.

```
Service Registry (main.py):
  /ingress    → services.ingress.app.main.router
  /ocr        → services.ocr.app.main.router
  /parser     → services.parser.app.main.router
  /coding     → services.coding.app.main.router
  /predictor  → services.predictor.app.main.router
  /validator  → services.validator.app.main.router
  /workflow   → services.workflow.app.main.router
  /submission → services.submission.app.main.router
  /chat       → services.chat.app.main.router
  /search     → services.search.app.main.router
```

---

## Data Flow (End-to-End Pipeline)

```
User uploads claim files
    ↓
1. INGRESS  — Validate files, save to storage, create Claim + Document rows
    ↓ (auto-triggers workflow)
2. WORKFLOW — Orchestrates pipeline: OCR → Parse → Code → Predict → Validate
    ↓
3. OCR      — Tesseract + OpenCV extract text per page; detect medical scans;
              validate document relevance + cross-document patient identity matching
    ↓ (async — poll job until done)
4. PARSER   — LayoutLMv3 + 40 regex patterns → 20+ structured fields
    ↓ (async — poll job until done)
5. CODING   — scispaCy NER → ICD-10 / CPT code assignment + cost estimates
    ↓ (sync)
6. PREDICTOR — XGBoost + LightGBM → rejection risk score + top reasons
    ↓ (sync)
7. VALIDATOR — 10 deterministic rules (R001–R010) → pass/fail per rule
    ↓
8. SUBMISSION — TPA PDF report, FHIR R4 / X12 837P adapters, reimbursement brain
    ↓
9. CHAT      — Conversational Q&A via Ollama LLM with RAG context
10. SEARCH   — Full-text (Postgres ILIKE) + vector search (FAISS)
```

---

## Shared Libraries (`libs/`)

| Library           | Files                         | Purpose                                              |
| ----------------- | ----------------------------- | ---------------------------------------------------- |
| **auth**          | `middleware.py`, `models.py`  | JWT decode (RS256 JWKS + HS256), RBAC dependency, `AuthMiddleware` |
| **observability** | `metrics.py`, `tracing.py`   | Prometheus counters/histograms, OpenTelemetry tracing |
| **schemas**       | `claim.py`, `events.py`      | `ClaimStatus` (23 states), event envelopes            |
| **utils**         | `audit.py`, `phi.py`         | HIPAA audit logger, PHI/PII regex scrubber            |

---

## Database Layout

18 tables in PostgreSQL 16 — see [`infra/db/claimgpt_schema.sql`](../infra/db/claimgpt_schema.sql):

| Table             | Owner Service | Purpose                                    |
| ----------------- | ------------- | ------------------------------------------ |
| `claims`          | ingress       | Core claim records (UUID PK)               |
| `documents`       | ingress       | Uploaded files (FK → claims)               |
| `ocr_results`     | ocr           | Extracted text per page (FK → documents)   |
| `ocr_jobs`        | ocr           | Async OCR job tracking                     |
| `parsed_fields`   | parser        | Structured field extraction results        |
| `parse_jobs`      | parser        | Async parse job tracking                   |
| `medical_entities`| coding        | NER entities (DIAGNOSIS, PROCEDURE, etc.)  |
| `medical_codes`   | coding        | ICD-10 / CPT code assignments              |
| `features`        | predictor     | ML feature vectors (JSONB)                 |
| `predictions`     | predictor     | Rejection risk scores + reasons            |
| `validations`     | validator     | Rule engine results (R001–R010)            |
| `workflow_jobs`   | workflow      | Pipeline job tracking                      |
| `submissions`     | submission    | Payer submission records                   |
| `chat_messages`   | chat          | Conversational history                     |
| `audit_logs`      | utils         | HIPAA compliance audit trail               |
| `scan_analyses`   | ocr           | Medical scan detection results             |
| `document_validations` | ocr      | Patient relevance & medical document check |
| `tpa_providers`   | submission    | TPA/Insurance provider directory (25 rows) |

---

## Key Design Patterns

| Pattern                    | Where Used                      | Details                                                            |
| -------------------------- | ------------------------------- | ------------------------------------------------------------------ |
| **Async Job + Polling**    | OCR, Parser, Workflow           | Return 202 + job_id; client polls until COMPLETED/FAILED           |
| **Idempotent Writes**      | Coding, Validator, OCR Validation | Wipe old results before inserting; safe to re-run                |
| **Feature Store**          | Predictor                       | Computed features cached in `features` table; on-demand rebuild    |
| **ML Fallback Chain**      | OCR, Parser, Coding, Predictor  | ML model → heuristic/regex fallback if deps missing                |
| **PHI Scrubbing**          | Chat                            | Regex redaction of SSN, phone, email, MRN, DOB before LLM calls   |
| **RBAC Dependency Injection** | Auth middleware               | `require_role("admin")` as FastAPI Depends()                       |
| **Event Envelope**         | Schemas (ready for Kafka/Redis) | Typed event schemas with idempotency_key                           |
| **Unified Gateway**        | main.py                         | Single-process router that includes all service routers            |

---

## Deployment Modes

| Mode                  | Command                                            | Use Case       |
| --------------------- | -------------------------------------------------- | -------------- |
| **Local dev**         | `uvicorn main:app --reload`                        | Development    |
| **Docker Compose**    | `docker compose -f infra/docker/docker-compose.yml up` | Staging     |
| **Kubernetes**        | `kubectl apply -f infra/k8s/`                      | Production     |
| **Single service**    | `make run SVC=ocr PORT=8002`                       | Isolated debug |

---

## Security & Compliance

- **Auth**: Keycloak JWKS (RS256) + HS256 fallback; 5 roles (`ADMIN`, `REVIEWER`, `SUBMITTER`, `VIEWER`, `SERVICE`)
- **PHI**: Automated scrubbing (SSN, phone, email, MRN, DOB, policy patterns) — never sent to external LLM
- **Audit**: All mutations logged to `audit_logs` with actor, action, before/after
- **CORS**: Configurable allowlist per service
- **Network**: Internal services communicate over private Docker/K8s network
