-- =====================================================
-- Migration 003: Add fraud_assessments table
-- Hybrid fraud detection signal (rules + ML + optional LLM)
-- =====================================================

CREATE TABLE IF NOT EXISTS fraud_assessments (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id        UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    fraud_score     FLOAT NOT NULL,                -- blended [0.0, 1.0]
    fraud_category  TEXT  NOT NULL,                -- LOW | MEDIUM | HIGH
    rules_score     FLOAT,
    ml_score        FLOAT,
    llm_score       FLOAT,
    indicators      JSONB,                         -- list of {code, name, layer, severity, weight, message, evidence}
    model_name      TEXT,
    model_version   TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_fraud_assessments_claim_id  ON fraud_assessments(claim_id);
CREATE INDEX IF NOT EXISTS idx_fraud_assessments_category  ON fraud_assessments(fraud_category);
CREATE INDEX IF NOT EXISTS idx_fraud_assessments_score     ON fraud_assessments(fraud_score);
