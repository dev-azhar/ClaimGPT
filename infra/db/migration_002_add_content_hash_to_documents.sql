-- Migration: Add content_hash column to documents table
-- Purpose: Support idempotent document uploads with content hash fingerprinting
-- Date: 2026-04-27

BEGIN;

-- Add content_hash column if it doesn't exist
ALTER TABLE documents
ADD COLUMN IF NOT EXISTS content_hash TEXT;

-- Create index for fast lookups
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);

-- For existing documents without content_hash, set to empty string (will need backfill)
-- This is a temporary measure; proper backfill should be done separately
UPDATE documents
SET content_hash = ''
WHERE content_hash IS NULL;

-- Now make it NOT NULL after setting values
ALTER TABLE documents
ALTER COLUMN content_hash SET NOT NULL;

COMMIT;
