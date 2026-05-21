# Database Migration: Add Document Tracking to Parsed Fields

**Date:** April 24, 2026  
**Status:** Implementation Complete  
**Version:** 1.0

---

## Overview

We've added two new columns to the `parsed_fields` table to track which document each parsed field comes from and what type of document it is. This enables filtering and processing of extracted fields by document type during the parsing pipeline.

### New Columns:
- **`document_id`** (UUID, FK) - Links parsed fields to specific documents
- **`doc_type`** (TEXT) - Stores the document type (e.g., DISCHARGE_SUMMARY, LAB_REPORT, PHARMACY_INVOICE)

---

## Code Changes Made

### 1. **Database Schema** (`infra/db/claimgpt_schema.sql`)
- Added `document_id` and `doc_type` columns to `parsed_fields` table
- Added indexes for efficient querying:
  - `idx_parsed_document_id` - for filtering by document
  - `idx_parsed_doc_type` - for filtering by document type

### 2. **ORM Models** (`services/parser/app/models.py`)
```python
class ParsedField(Base):
    document_id = Column(UUID, ForeignKey("documents.id"), nullable=True)
    doc_type = Column(Text, nullable=True)
    document = relationship("Document")
```

### 3. **Parser Engine** (`services/parser/app/engine.py`)
- Updated `FieldResult` dataclass with `document_id` and `doc_type` fields

### 4. **Parser Service** (`services/parser/app/main.py`)
- `_persist_fields()` - Now saves document_id and doc_type
- `_get_document_type_map()` - Fetches doc_type from DocValidation table
- `_enrich_fields_with_doc_info()` - Enriches fields with document metadata before persistence
- `_run_parse_job()` - Calls enrichment before persisting parsed fields

### 5. **API Schemas** (`services/parser/app/schemas.py`)
- Updated `ParsedFieldOut` response model to include `document_id` and `doc_type`

---

## What Colleagues Need to Do

### Step 1: Pull the Latest Code
```powershell
git pull origin <branch>
```

### Step 2: Update Existing Databases (IMPORTANT)

Choose ONE option below based on your setup:

#### **Option A: Using Docker (Your Setup) - RECOMMENDED**

After running your postgres container with:
```bash
docker compose -f infra/docker/docker-compose.yml up -d postgres redis minio
```

Run SQL commands directly:
```bash
docker compose -f infra/docker/docker-compose.yml exec postgres psql -U claimgpt -d claimgpt
```
```bash
ALTER TABLE parsed_fields
ADD COLUMN IF NOT EXISTS document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS doc_type TEXT;
```
```bash
CREATE INDEX IF NOT EXISTS idx_parsed_document_id ON parsed_fields(document_id);
CREATE INDEX IF NOT EXISTS idx_parsed_doc_type ON parsed_fields(doc_type);
```

**Verify the migration:**
```bash
docker compose -f infra/docker/docker-compose.yml exec postgres psql -U claimgpt -d claimgpt 
```
```bash
\d parsed_fields
```

#### **Option B: Using Raw SQL (Direct Database Access)**

If you have direct database access (not Docker):

```bash
psql -U postgres -d claimgpt -f infra/db/migration_001_add_parsed_fields_columns.sql
```

#### **Option C: Fresh Database (New Installations)**
Just run the updated schema from scratch - the new columns will be created automatically:
```bash
docker compose -f infra/docker/docker-compose.yml exec postgres psql -U postgres -d claimgpt -f infra/db/claimgpt_schema.sql
```

### Step 3: Verify the Migration

Check that the columns exist:

**Using Docker (your setup):**
```bash
docker compose -f infra/docker/docker-compose.yml exec postgres psql -U postgres -d claimgpt -c "\d parsed_fields"
```

**Or directly:**
```sql
\d parsed_fields;  -- In psql
-- or
DESC parsed_fields;  -- In other SQL clients
```

Expected output should show:
```
 document_id | uuid
 doc_type    | text
```

### Step 4: Restart Services

After the database update, restart the services:

```bash
# Using your docker-compose setup
docker compose -f infra/docker/docker-compose.yml restart

# Or if you need to pull latest images and restart
docker compose -f infra/docker/docker-compose.yml down
docker compose -f infra/docker/docker-compose.yml up -d postgres redis minio
```

### Step 5: Test

Trigger a new parse job to verify the new fields are being populated:

```bash
curl -X POST http://localhost:8001/parse/{claim_id}
```

Verify in the database:
```sql
SELECT id, claim_id, document_id, doc_type, field_name FROM parsed_fields LIMIT 5;
```

---

## Important Notes

⚠️ **Data Consistency:**
- Existing parsed fields will have `NULL` values for `document_id` and `doc_type`
- Only NEW parsed fields will have these values populated
- To backfill historical data, run this command (Docker):
  ```bash
  docker compose -f infra/docker/docker-compose.yml exec postgres psql -U postgres -d claimgpt << 'EOF'
  UPDATE parsed_fields pf
  SET doc_type = dv.doc_type
  FROM document_validations dv
  WHERE pf.claim_id = dv.claim_id
  AND pf.document_id = dv.document_id;
  EOF
  ```

⚠️ **API Changes:**
- The response from `/parse/{claim_id}` endpoint now includes `document_id` and `doc_type` fields
- Clients should update their code to handle these new fields (they're optional)

⚠️ **Backward Compatibility:**
- Old API clients that ignore these fields will continue to work
- New fields are optional and won't break existing integrations

---

## Troubleshooting

### Issue: "column already exists"
- The columns are already added. No action needed.

### Issue: Migration fails with foreign key error
- Ensure the `documents` table exists and has records
- Check that `document_id` values are valid UUIDs

### Issue: Services won't start after migration
- Ensure all services have the latest code pulled
- Check that ORM models match the database schema
- Restart Docker containers: `docker compose -f infra/docker/docker-compose.yml restart`

### Issue: Can't connect to postgres container
- Verify container is running: `docker compose -f infra/docker/docker-compose.yml ps`
- Check logs: `docker compose -f infra/docker/docker-compose.yml logs postgres`
- Ensure postgres started: `docker compose -f infra/docker/docker-compose.yml up -d postgres`

---

## Questions or Issues?

If you encounter any problems:
1. Check the service logs: `docker-compose logs parser`
2. Verify database connection and credentials
3. Ensure all code is up-to-date
4. Reach out to the dev team

---

## Timeline

| Phase | Status | Date |
|-------|--------|------|
| Code Implementation | ✅ Complete | Apr 24, 2026 |
| Schema Update | ✅ Complete | Apr 24, 2026 |
| Colleague Deployment | ⏳ In Progress | Apr 24, 2026 |
| Testing | ⏳ Pending | TBD |
| Production Rollout | ⏳ Pending | TBD |
