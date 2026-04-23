#!/usr/bin/env bash
# =====================================================
# Seed the database with sample claim data for testing
# =====================================================

set -euo pipefail

DB_URL="${DATABASE_URL:-postgresql://claimgpt:claimgpt@postgres:5432/claimgpt}"

echo "[seed] Inserting sample data..."

psql "$DB_URL" <<'SQL'
-- Sample claim
INSERT INTO claims (id, policy_id, patient_id, status, source)
VALUES (
    'a0000000-0000-0000-0000-000000000001',
    'POL-12345',
    'PAT-67890',
    'UPLOADED',
    'PATIENT'
) ON CONFLICT (id) DO NOTHING;

-- Sample document
INSERT INTO documents (id, claim_id, file_name, file_type, minio_path)
VALUES (
    'b0000000-0000-0000-0000-000000000001',
    'a0000000-0000-0000-0000-000000000001',
    'claim_form.pdf',
    'application/pdf',
    '/storage/raw/a0000000-0000-0000-0000-000000000001/claim_form.pdf'
) ON CONFLICT (id) DO NOTHING;

-- Sample parsed fields
INSERT INTO parsed_fields (claim_id, field_name, field_value) VALUES
    ('a0000000-0000-0000-0000-000000000001', 'patient_name', 'John Doe'),
    ('a0000000-0000-0000-0000-000000000001', 'date_of_birth', '1985-03-15'),
    ('a0000000-0000-0000-0000-000000000001', 'policy_number', 'POL-12345'),
    ('a0000000-0000-0000-0000-000000000001', 'diagnosis', 'Type 2 diabetes mellitus'),
    ('a0000000-0000-0000-0000-000000000001', 'service_date', '2026-01-15'),
    ('a0000000-0000-0000-0000-000000000001', 'total_amount', '1250.00'),
    ('a0000000-0000-0000-0000-000000000001', 'provider_name', 'City Medical Center')
ON CONFLICT DO NOTHING;

-- Sample medical entities
INSERT INTO medical_entities (claim_id, entity_text, entity_type, confidence) VALUES
    ('a0000000-0000-0000-0000-000000000001', 'Type 2 diabetes mellitus', 'DIAGNOSIS', 0.95),
    ('a0000000-0000-0000-0000-000000000001', 'HbA1c blood test', 'PROCEDURE', 0.88)
ON CONFLICT DO NOTHING;

-- Sample medical codes
INSERT INTO medical_codes (claim_id, code, code_system, description, confidence, is_primary) VALUES
    ('a0000000-0000-0000-0000-000000000001', 'E11.9', 'ICD10', 'Type 2 diabetes mellitus without complications', 0.92, true),
    ('a0000000-0000-0000-0000-000000000001', '83036', 'CPT', 'Hemoglobin; glycosylated (A1c)', 0.89, false)
ON CONFLICT DO NOTHING;

SQL

echo "[seed] Done. Sample claim ID: a0000000-0000-0000-0000-000000000001"
