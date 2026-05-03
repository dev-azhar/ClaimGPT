-- =====================================================
-- Migration: Add document_id and doc_type to parsed_fields
-- Date: April 24, 2026
-- Purpose: Track which document each parsed field comes from and its type
-- =====================================================

BEGIN;

-- Add new columns to parsed_fields table
ALTER TABLE parsed_fields
ADD COLUMN IF NOT EXISTS document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS doc_type TEXT;

-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_parsed_document_id ON parsed_fields(document_id);
CREATE INDEX IF NOT EXISTS idx_parsed_doc_type ON parsed_fields(doc_type);

-- Optional: Backfill existing fields with doc_type from document_validations
-- Uncomment if you want to populate historical data
-- UPDATE parsed_fields pf
-- SET doc_type = dv.doc_type
-- FROM document_validations dv
-- WHERE pf.claim_id = dv.claim_id
-- AND pf.document_id IS NOT NULL
-- AND pf.document_id = dv.document_id
-- AND pf.doc_type IS NULL;

COMMIT;

-- Verify the changes
-- SELECT column_name, data_type, is_nullable 
-- FROM information_schema.columns 
-- WHERE table_name = 'parsed_fields' 
-- AND column_name IN ('document_id', 'doc_type');
