# ClaimGPT — Architecture

> Two views of the system:
> 1. **Component diagram** — services, datastores, and external integrations.
> 2. **Sequence diagram** — end-to-end claim processing flow (upload → OCR → parse → code → predict → fraud → validate → submit), styled after the Azure AD JWT auth flow we use as a reference.
>
> Both diagrams render natively on GitHub. To preview locally in VS Code install `bierner.markdown-mermaid` or use the **Markdown: Open Preview** command.

---

## 1. Component Diagram

```mermaid
flowchart LR
    %% ─────── Clients ───────
    subgraph Clients
        WEB["Next.js Web UI<br/>(ui/web :3000)"]
        ADMIN["Admin Console<br/>(ui/admin)"]
        EXT["External clients<br/>(curl / TPA portals)"]
    end

    %% ─────── Gateway ───────
    subgraph Edge["API Gateway (main.py :8000)"]
        GW["FastAPI Gateway<br/>CORS + Auth + OpenAPI"]
    end

    %% ─────── Microservices ───────
    subgraph Services["Microservices (services/*/app)"]
        ING["Ingress<br/>/ingress"]
        OCR["OCR<br/>/ocr"]
        PAR["Parser<br/>/parser"]
        COD["Coding<br/>/coding"]
        PRD["Predictor<br/>/predictor"]
        FRD["Fraud<br/>/fraud"]
        VAL["Validator<br/>/validator"]
        WFL["Workflow<br/>/workflow"]
        SUB["Submission<br/>/submission"]
        CHT["Chat<br/>/chat"]
        SRC["Search<br/>/search"]
    end

    %% ─────── Async / Cache ───────
    subgraph Async["Async layer"]
        CEL["Celery workers<br/>(OCR + Ingress)"]
        FLO["Flower :5555"]
        RDS[("Redis 5.2.1<br/>broker + cache")]
    end

    %% ─────── Datastores ───────
    subgraph Data["Data layer"]
        PG[("PostgreSQL<br/>claims · documents<br/>predictions · fraud_assessments<br/>validations · audit_log")]
        FS[("Local FS / Blob<br/>uploaded docs · IRDAI PDFs")]
        IDX[("FAISS + BM25<br/>ICD/CPT vector index")]
    end

    %% ─────── External / AI ───────
    subgraph External["External services"]
        OLM["Ollama / vLLM<br/>(local LLM)"]
        TES["Tesseract + PaddleOCR"]
        LFS["LangFuse / OTel"]
    end

    %% ─────── Edges ───────
    WEB & ADMIN & EXT --> GW
    GW --> ING & OCR & PAR & COD & PRD & FRD & VAL & WFL & SUB & CHT & SRC

    ING -- enqueue --> CEL
    OCR -- enqueue --> CEL
    CEL <--> RDS
    FLO --- RDS

    ING & OCR & PAR & COD & PRD & FRD & VAL & SUB & CHT --> PG
    ING --> FS
    SUB --> FS
    OCR --> TES
    PAR --> OLM
    COD --> OLM
    SRC --> IDX
    CHT --> OLM
    CHT --> IDX

    GW & WFL --> LFS

    %% ─────── Workflow orchestration ───────
    WFL -. drives .-> OCR
    WFL -. drives .-> PAR
    WFL -. drives .-> COD
    WFL -. drives .-> PRD
    WFL -. drives .-> FRD
    WFL -. drives .-> VAL

    classDef edge   fill:#FFF4E0,stroke:#D69E2E,color:#744210;
    classDef svc    fill:#EFF6FF,stroke:#3B82F6,color:#1E3A8A;
    classDef async  fill:#F0FDF4,stroke:#16A34A,color:#14532D;
    classDef data   fill:#FEF2F2,stroke:#DC2626,color:#7F1D1D;
    classDef ext    fill:#F5F3FF,stroke:#7C3AED,color:#4C1D95;

    class GW edge;
    class ING,OCR,PAR,COD,PRD,FRD,VAL,WFL,SUB,CHT,SRC svc;
    class CEL,FLO,RDS async;
    class PG,FS,IDX data;
    class OLM,TES,LFS ext;
```

### Service registry (from `main.py`)

| Prefix        | Module                              | Purpose                                                             |
| ------------- | ----------------------------------- | ------------------------------------------------------------------- |
| `/ingress`    | `services.ingress.app.main`         | Claim creation, document upload, deduplication, activity log.       |
| `/ocr`        | `services.ocr.app.main`             | Tesseract + PaddleOCR text extraction (Celery-backed).              |
| `/parser`     | `services.parser.app.main`          | LLM-based field extraction (patient, policy, diagnosis…).           |
| `/coding`     | `services.coding.app.main`          | ICD-10 / CPT code suggestion (BioGPT + RAG).                        |
| `/predictor`  | `services.predictor.app.main`       | XGBoost + LightGBM ensemble — rejection-risk score.                 |
| `/fraud`      | `services.fraud.app.main`           | 10 rule detectors + IsolationForest + LLM blend.                    |
| `/validator`  | `services.validator.app.main`       | R001–R011 rules; consumes predictor + fraud scores.                 |
| `/workflow`   | `services.workflow.app.main`        | 6-step pipeline orchestrator (`PIPELINE_STEPS`).                    |
| `/submission` | `services.submission.app.main`      | IRDAI Standard Claim Form (WeasyPrint + AcroForm fallback).         |
| `/chat`       | `services.chat.app.main`            | LangGraph agent with Postgres checkpointer.                         |
| `/search`     | `services.search.app.main`          | FAISS + BM25 hybrid search over ICD/CPT corpora.                    |

---

## 2. Sequence Diagram — Claim Processing Pipeline

The end-to-end happy path and the partial-failure path, modeled after the same alt-branch style as the Azure AD JWT flow.

> 📎 A pre-rendered SVG of this diagram is checked in at [docs/img/claims_processing_pipeline.svg](img/claims_processing_pipeline.svg) for use in slides / external docs without a Mermaid renderer.

```mermaid
sequenceDiagram
    autonumber
    participant Client      as Client (Web UI / TPA)
    participant Gateway     as API Gateway<br/>(FastAPI :8000)
    participant Ingress     as Ingress Service
    participant Workflow    as Workflow Orchestrator
    participant OCR         as OCR Service
    participant Celery      as Celery Worker<br/>+ Redis
    participant Parser      as Parser Service
    participant Coding      as Coding Service
    participant Predictor   as Predictor Service
    participant Fraud       as Fraud Service
    participant Validator   as Validator Service
    participant DB          as PostgreSQL<br/>(claims · documents · …)

    Client->>Gateway: (1) POST /ingress/claims<br/>multipart upload (PDF/JPG)
    Gateway->>Ingress: (2) Forward request<br/>(JWT verified)
    Ingress->>Ingress: Compute SHA-256 content hash<br/>(dedup check)
    Ingress->>DB: INSERT claim + documents
    Ingress->>Celery: Enqueue OCR job (claim_id)
    Ingress-->>Client: (3) 202 Accepted<br/>{claim_id, status: PROCESSING}

    Note over Workflow,Celery: Pipeline driven by services/workflow/app/pipeline.py<br/>PIPELINE_STEPS = ocr → parse → code_suggest → predict → fraud_check → validate

    Workflow->>OCR: (4) POST /ocr/{claim_id}
    OCR->>Celery: dispatch tesseract + paddleocr
    Celery-->>OCR: extracted text + parsed_fields
    OCR->>DB: UPDATE documents.ocr_text

    Workflow->>Parser: (5) POST /parser/parse/{claim_id}
    Parser->>DB: UPDATE claims.parsed_fields<br/>(patient, policy, diagnosis, amounts)

    Workflow->>Coding: (6) POST /coding/code-suggest/{claim_id}
    Coding->>DB: INSERT icd_codes / cpt_codes

    Workflow->>Predictor: (7) POST /predictor/predict/{claim_id}
    Predictor->>DB: INSERT prediction<br/>(rejection_score, risk_category)

    Workflow->>Fraud: (8) POST /fraud/detect/{claim_id}
    Fraud->>Fraud: rules (R-DUP/R-BILL/…)<br/>+ IsolationForest + LLM blend
    Fraud->>DB: INSERT fraud_assessment<br/>(score, category, indicators)

    Workflow->>Validator: (9) POST /validator/validate/{claim_id}
    Validator->>DB: SELECT latest prediction + fraud_assessment

    alt ✅ All steps succeed
        Validator->>DB: INSERT validations.status = PASSED
        Validator-->>Workflow: PipelineResult(success=True, 6 DONE steps)
        Workflow->>DB: UPDATE claims.status = READY_FOR_REVIEW
        Client->>Gateway: (10) GET /ingress/claims/{id}
        Gateway-->>Client: (11) 200 OK<br/>{status: READY_FOR_REVIEW,<br/> rejection_score, fraud_category, validations}
    else ⚠️ Step returns 4xx/5xx (e.g. parser fails)
        Parser-->>Workflow: 422 / 503
        Workflow->>DB: StepResult(step=parse, status=FAILED, detail=…)
        Workflow->>DB: UPDATE claims.status = NEEDS_ATTENTION
        Workflow-->>Workflow: stop pipeline (failed_step recorded)
        Client->>Gateway: GET /ingress/claims/{id}
        Gateway-->>Client: 200 OK<br/>{status: NEEDS_ATTENTION,<br/> failed_step: "parse"}
    else ⏭️ Step returns 409 (precondition not met)
        OCR-->>Workflow: 409 (already processed)
        Workflow->>DB: StepResult(step=ocr, status=SKIPPED)
        Note over Workflow: pipeline continues with next step
    end

    Note over Client,DB: Optional follow-ups<br/>POST /submission/irda-pdf → IRDAI Standard Claim Form (WeasyPrint)<br/>POST /chat → LangGraph agent for ad-hoc Q&A
```

### Where each step is implemented

| Step             | Service     | Entrypoint                               |
| ---------------- | ----------- | ---------------------------------------- |
| Upload + dedup   | Ingress     | `POST /ingress/claims`                   |
| OCR              | OCR         | `POST /ocr/{claim_id}` (Celery-backed)   |
| Field parsing    | Parser      | `POST /parser/parse/{claim_id}`          |
| Code suggestion  | Coding      | `POST /coding/code-suggest/{claim_id}`   |
| Risk prediction  | Predictor   | `POST /predictor/predict/{claim_id}`     |
| Fraud assessment | Fraud       | `POST /fraud/detect/{claim_id}`          |
| Rule validation  | Validator   | `POST /validator/validate/{claim_id}`    |
| IRDAI form       | Submission  | `POST /submission/irda-pdf`              |

---

## 3. Cross-cutting concerns

- **Observability** — every service emits OTLP traces/metrics + propagates `X-Request-ID`; LangFuse captures LLM spans.
- **Activity log** — `libs/observability/file_logger.py` (rotating, log4net-style) writes to `logs/claim_uploads.txt`; UPLOAD_START / UPLOAD_SUCCESS / UPLOAD_PARTIAL / UPLOAD_FAILURE.
- **Auth** — JWT (Keycloak) verified at the gateway; downstream services trust headers.
- **Dependency hygiene** — `infra/scripts/verify_deps.py --all` enforces both installed-env match and per-service consistency with `requirements.txt`; pre-push hook blocks drift.
