-- =====================================================
-- ClaimGPT Database Schema
-- Single-file, production-ready
-- =====================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================================================
-- 1. Core Claims (Source of Truth)
-- =====================================================
CREATE TABLE claims (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    policy_id TEXT,
    patient_id TEXT,
    status TEXT NOT NULL DEFAULT 'UPLOADED',
    source TEXT DEFAULT 'PATIENT',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- =====================================================
-- 2. Uploaded Documents (PDFs, Images)
-- =====================================================
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    file_type TEXT,
    minio_path TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_documents_claim_id ON documents(claim_id);

-- =====================================================
-- Auto-update updated_at on claims
-- =====================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_claims_updated_at
    BEFORE UPDATE ON claims
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =====================================================
-- 3. OCR Results (Raw Text)
-- =====================================================
CREATE TABLE ocr_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    page_number INT,
    text TEXT,
    confidence FLOAT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_ocr_document_id ON ocr_results(document_id);

-- =====================================================
-- 3b. OCR Jobs (Async Job Tracking)
-- =====================================================
CREATE TABLE ocr_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id UUID REFERENCES claims(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    total_documents INT NOT NULL DEFAULT 0,
    processed_documents INT NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_ocr_jobs_claim_id ON ocr_jobs(claim_id);

-- =====================================================
-- 4. Parsed / Extracted Fields (Structured)
-- =====================================================
CREATE TABLE parsed_fields (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id UUID REFERENCES claims(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    field_value TEXT,
    bounding_box JSONB,
    source_page INT,
    model_version TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_parsed_claim_id ON parsed_fields(claim_id);

-- =====================================================
-- 4b. Parse Jobs (Async Job Tracking)
-- =====================================================
CREATE TABLE parse_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id UUID REFERENCES claims(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    total_documents INT NOT NULL DEFAULT 0,
    processed_documents INT NOT NULL DEFAULT 0,
    model_version TEXT,
    used_fallback BOOLEAN NOT NULL DEFAULT false,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_parse_jobs_claim_id ON parse_jobs(claim_id);

-- =====================================================
-- 5. Medical NER Entities
-- =====================================================
CREATE TABLE medical_entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id UUID REFERENCES claims(id) ON DELETE CASCADE,
    entity_text TEXT NOT NULL,
    entity_type TEXT NOT NULL, -- DIAGNOSIS / PROCEDURE / MEDICATION
    start_offset INT,
    end_offset INT,
    confidence FLOAT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_medical_entities_claim_id ON medical_entities(claim_id);

-- =====================================================
-- 6. Medical Codes (ICD-10 / CPT)
-- =====================================================
CREATE TABLE medical_codes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id UUID REFERENCES claims(id) ON DELETE CASCADE,
    entity_id UUID REFERENCES medical_entities(id),
    code TEXT NOT NULL,
    code_system TEXT NOT NULL, -- ICD10 / CPT
    description TEXT,
    confidence FLOAT,
    is_primary BOOLEAN DEFAULT false,
    estimated_cost FLOAT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_medical_codes_claim_id ON medical_codes(claim_id);

-- =====================================================
-- 7. Feature Store (ML Inputs)
-- =====================================================
CREATE TABLE features (
    claim_id UUID PRIMARY KEY REFERENCES claims(id) ON DELETE CASCADE,
    feature_vector JSONB NOT NULL,
    generated_at TIMESTAMPTZ DEFAULT now()
);

-- =====================================================
-- 8. ML Predictions
-- =====================================================
CREATE TABLE predictions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id UUID REFERENCES claims(id) ON DELETE CASCADE,
    rejection_score FLOAT,
    top_reasons JSONB,
    model_name TEXT,
    model_version TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_predictions_claim_id ON predictions(claim_id);

-- =====================================================
-- 9. Rule Engine Validations
-- =====================================================
CREATE TABLE validations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id UUID REFERENCES claims(id) ON DELETE CASCADE,
    rule_id TEXT,
    rule_name TEXT,
    severity TEXT, -- INFO / WARN / ERROR
    message TEXT,
    passed BOOLEAN,
    evaluated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_validations_claim_id ON validations(claim_id);

-- =====================================================
-- 10. Workflow Orchestration
-- =====================================================
CREATE TABLE workflow_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id UUID REFERENCES claims(id) ON DELETE CASCADE,
    job_type TEXT,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    current_step TEXT,
    error_message TEXT,
    retries INT DEFAULT 0,
    started_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_workflow_claim_id ON workflow_jobs(claim_id);

-- =====================================================
-- 11. Submission to Insurer / TPA
-- =====================================================
CREATE TABLE submissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id UUID REFERENCES claims(id) ON DELETE CASCADE,
    payer TEXT,
    request_payload JSONB,
    response_payload JSONB,
    status TEXT,
    submitted_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_submissions_claim_id ON submissions(claim_id);

-- =====================================================
-- 12. Chat History (UX Layer)
-- =====================================================
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id UUID REFERENCES claims(id) ON DELETE CASCADE,
    role TEXT, -- USER / SYSTEM / ASSISTANT
    message TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_chat_claim_id ON chat_messages(claim_id);

-- =====================================================
-- 13. Audit Logs (HIPAA / Compliance)
-- =====================================================
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id UUID,
    actor TEXT,
    action TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_audit_claim_id ON audit_logs(claim_id);

-- =====================================================
-- 14. Scan Analyses (MRI / CT / X-Ray)
-- =====================================================
CREATE TABLE scan_analyses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    claim_id UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    scan_type TEXT NOT NULL,
    body_part TEXT,
    modality TEXT,
    findings JSONB,
    impression TEXT,
    recommendation TEXT,
    confidence FLOAT,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_scan_analyses_claim_id ON scan_analyses(claim_id);
CREATE INDEX idx_scan_analyses_document_id ON scan_analyses(document_id);

-- =====================================================
-- ✅ Schema creation complete
-- =====================================================