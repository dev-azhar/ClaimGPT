# Setup & Execution Guide: swagathupdates Branch

**Branch:** `swagathupdates`  
**Purpose:** Patient identity gating + PaddleOCR + Parser enhancement  
**Status:** Ready for testing  
**Commits:** 3 (merged from feature/patient-identity-gating)

---

## Prerequisites

### System Requirements
- **OS:** Windows 10+ / Linux / macOS
- **Python:** 3.9+
- **Docker:** 20.10+ with Docker Compose
- **RAM:** Minimum 8GB (recommended 16GB due to PaddleOCR models)
- **Disk Space:** 5GB+ (for PaddleOCR models)

### Company Account Access
- ✅ Company email with GitHub organization access
- ✅ Repository push permissions
- ✅ Docker registry credentials (if private)

---

## Step 1: Login to VS Code with Company Email

### On Windows (VS Code):

1. **Open VS Code**
   ```
   File > Preferences > Accounts
   ```

2. **Sign in with GitHub (Company Account)**
   - Click "Sign in with GitHub"
   - Login with your **company email** (the one manager gave permission for)
   - Authorize the GitHub App
   - Verify: Account shows in bottom-left corner

3. **Verify Access**
   ```powershell
   git config --global user.name "Your Name"
   git config --global user.email "your.company.email@company.com"
   git config --global credential.helper store
   ```

4. **Test GitHub Access**
   ```powershell
   cd c:\Project\ClaimGPT
   git remote -v
   ```
   Should show your company's GitHub URLs.

---

## Step 2: Verify You're on swagathupdates Branch

```powershell
cd c:\Project\ClaimGPT

# Check current branch (should show * next to swagathupdates)
git branch

# Output:
# * swagathupdates
#   main
#   feature/patient-identity-gating
```

If not on swagathupdates:
```powershell
git checkout swagathupdates
```

---

## Step 3: Setup Local Environment

### A. Install Python Dependencies

```powershell
# Navigate to project
cd c:\Project\ClaimGPT

# Create virtual environment (optional but recommended)
python -m venv venv

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Install requirements
pip install -r requirements.txt
pip install -r services/ocr/requirements.txt
pip install -r services/parser/requirements.txt
pip install -r services/ingress/requirements.txt
pip install -r services/submission/requirements.txt
```

### B. Install PaddleOCR (Already in requirements.txt)

```powershell
# Verify PaddleOCR installation
python -c "from paddleocr import PaddleOCR; print('✅ PaddleOCR installed')"

# Download language models (one-time, ~200MB for English)
python -c "from paddleocr import PaddleOCR; ocr = PaddleOCR(lang='en'); print('✅ Models downloaded')"
```

### C. Install System Dependencies

**For Tesseract (fallback OCR):**

**Windows:**
```powershell
# Using Chocolatey
choco install tesseract -y

# Or download from: https://github.com/UB-Mannheim/tesseract/wiki
# Then set in .env: TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe"
```

**Linux/WSL:**
```bash
sudo apt-get install -y tesseract-ocr
```

---

## Step 4: Database Setup

### A. Start PostgreSQL (Docker)

```powershell
cd c:\Project\ClaimGPT

# Start only database
docker compose up -d postgres

# Verify it's running
docker ps | Select-String postgres
```

### B. Apply Migrations

```powershell
# From project root
python -m alembic upgrade head

# Or if using direct SQL:
psql -h localhost -U postgres -d claimgpt < infra/db/claimgpt_schema.sql
```

### C. Check Database Tables

```powershell
# Connect to database
docker compose exec postgres psql -U postgres -d claimgpt

# Inside psql:
\dt  # List all tables

# Check document_validations has new columns:
\d document_validations  # Should show: excluded_at_timestamp, exclusion_reason, identity_match_confidence

\q  # Exit psql
```

---

## Step 5: Start Services with Docker Compose

### A. Build Images

```powershell
cd c:\Project\ClaimGPT

# Build all services (includes PaddleOCR in OCR service)
docker compose build

# Or build specific services:
docker compose build ocr     # OCR with PaddleOCR
docker compose build parser  # Parser with heuristic-v2
docker compose build ingress # Ingress with identity gating
```

### B. Start Services

```powershell
# Start all services
docker compose up -d

# Verify services are running
docker compose ps

# Should show:
# postgres      ✅ Up
# pgadmin       ✅ Up  
# ocr           ✅ Up
# parser        ✅ Up
# ingress       ✅ Up
# submission    ✅ Up
# workflow      ✅ Up
# chat          ✅ Up
```

### C. Check Logs

```powershell
# View overall logs
docker compose logs -f

# View specific service logs
docker compose logs -f ocr
docker compose logs -f parser
docker compose logs -f ingress

# Look for:
# ✅ "OCR backend mode: vl" or "classic"
# ✅ "Parser initialized with heuristic-v2"
# ✅ "Identity gating enabled"
```

---

## Step 6: Verify Installation

### A. Health Check

```powershell
# Check if services are healthy
curl http://localhost:8000/health

# Expected response:
# {
#   "status": "healthy",
#   "services": {
#     "ocr": "running",
#     "parser": "running",
#     "ingress": "running"
#   }
# }
```

### B. Swagger API Docs

Open in browser:
```
http://localhost:8000/docs
```

Should show all API endpoints for:
- `/ingress` - Upload documents
- `/ocr` - OCR processing
- `/parser` - Field extraction
- `/submission` - Report generation
- `/workflow` - Orchestration

---

## Step 7: Test the Features

### A. Test Upload & Identity Gating

```powershell
# Create test claim
$claimId = "test-claim-$(Get-Random)"

# Upload test documents (replace with your PDF paths)
curl -X POST "http://localhost:8000/ingress/upload" `
  -H "Content-Type: multipart/form-data" `
  -F "claim_id=$claimId" `
  -F "documents=@C:\path\to\discharge_summary.pdf" `
  -F "documents=@C:\path\to\lab_report.pdf"

# Response should show:
# {
#   "document_ids": [...],
#   "identity_gate_results": {
#     "patient_name": "extracted name",
#     "matched_count": 2,
#     "excluded_count": 0
#   }
# }
```

### B. Test OCR with PaddleOCR

```powershell
# Check OCR backend (should be PaddleOCR)
docker compose logs ocr | Select-String "OCR backend mode"

# Should show:
# "OCR backend mode: vl" or "OCR backend mode: classic (VL disabled by config)"
```

### C. Test Parser with Demographic Backfill

```powershell
# Check parsed fields include patient_name
curl "http://localhost:8000/parser/claims/$claimId/preview" | ConvertFrom-Json

# Response should include:
# {
#   "claim_id": "...",
#   "patient_name": "Mr. Ravi Kumar Sharma",  # ✅ NOW INCLUDED
#   "parsed_fields": {
#     "patient_name": {...},
#     "age": {...},
#     "gender": {...}
#   }
# }
```

### D. Run Unit Tests

```powershell
# Run all tests
pytest tests/ -v

# Run specific test suites
pytest tests/ocr/ -v              # OCR tests
pytest tests/parser/ -v           # Parser tests
pytest tests/ingress/ -v          # Ingress/identity gating tests

# Expected output:
# test_patient_name_extraction PASSED ✅
# test_identity_gating_workflow PASSED ✅
# test_demographic_backfill PASSED ✅
```

---

## Step 8: Test End-to-End Workflow

### Full Test Flow

```powershell
# 1. Upload mixed-document claim
$claimId = "e2e-test-$(Get-Random)"
curl -X POST "http://localhost:8000/ingress/upload" `
  -F "claim_id=$claimId" `
  -F "documents=@discharge.pdf" `
  -F "documents=@pharmacy_invoice.pdf" `
  -F "documents=@lab_report.pdf"

# 2. Wait for OCR (check logs)
docker compose logs ocr | Select-String $claimId

# 3. Wait for Parser (check logs)
docker compose logs parser | Select-String $claimId

# 4. Get preview/report
curl "http://localhost:8000/parser/claims/$claimId/preview" | ConvertFrom-Json | ConvertTo-Json -Depth 10

# 5. Verify in submission (report generation)
curl "http://localhost:8000/submission/claims/$claimId/report"

# Expected:
# ✅ All documents processed
# ✅ patient_name extracted and visible
# ✅ Demographics filled from priority order
# ✅ No identity gate exclusions (if same patient in all docs)
```

---

## Step 9: Push Branch to GitHub

Once verified locally:

### A. Verify Changes Are Committed

```powershell
cd c:\Project\ClaimGPT

# Check status (should be clean)
git status

# Should show: "On branch swagathupdates, nothing to commit"
```

### B. Push to Remote

```powershell
# Push with upstream tracking
git push origin swagathupdates -u

# Or if already tracked:
git push origin swagathupdates

# Verify it's pushed
git branch -r | Select-String swagathupdates

# Should show: origin/swagathupdates
```

### C. Verify on GitHub Web UI

1. Go to: `https://github.com/your-company/claimgpt`
2. Check **Branches** tab
3. Verify `swagathupdates` is listed
4. Click on it to see:
   - Commit history (3 commits)
   - File changes
   - Latest commit: "feat: add patient identity gating and parser backfill"

---

## Environment Variables Reference

Create `.env` file in project root if not exists:

```bash
# Database
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/claimgpt
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=claimgpt

# OCR Settings
ENABLE_PADDLE_OCR=true
ENABLE_PADDLE_VL=true
PADDLE_LANGUAGE=en
PADDLE_VL_DOC_PARSER=true
PADDLE_VL_MERGE_CROSS_PAGE_TABLES=false
TESSERACT_CMD=/usr/bin/tesseract  # Linux/WSL
# TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe  # Windows

# Parser Settings
PARSER_STRUCTURED_EXTRACTION_ENABLED=false  # Fast heuristic-only mode
PARSER_USE_DEMOGRAPHIC_BACKFILL=true

# Identity Gating
IDENTITY_GATING_ENABLED=true

# Logging
LOG_LEVEL=INFO
```

---

## Troubleshooting

### Issue: "PaddleOCR not found"
```powershell
# Solution:
pip install paddleocr>=2.7.0.0 --upgrade
python -c "from paddleocr import PaddleOCR; print('✅')"
```

### Issue: "Out of memory" running OCR
```powershell
# Increase Docker memory allocation:
# Windows: Settings > Resources > Memory: 4GB or higher
# Then restart: docker compose restart ocr
```

### Issue: "Tesseract not found" (fallback)
```powershell
# Windows: Install from https://github.com/UB-Mannheim/tesseract/wiki
# Set: $env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"

# Linux/WSL: 
# sudo apt-get install -y tesseract-ocr
```

### Issue: "Database connection refused"
```powershell
# Verify postgres is running:
docker compose ps postgres

# Restart database:
docker compose down postgres
docker compose up -d postgres

# Wait 5 seconds, then retry
```

### Issue: Parser not extracting patient_name
```powershell
# Check parser logs:
docker compose logs parser | Select-String "patient_name"

# Verify structured extraction is disabled:
docker compose exec parser env | Select-String PARSER_STRUCTURED_EXTRACTION_ENABLED

# Should show: PARSER_STRUCTURED_EXTRACTION_ENABLED=false
```

---

## Rollback to Main

If issues occur:

```powershell
cd c:\Project\ClaimGPT

# Switch to main branch
git checkout main

# Stop and remove containers
docker compose down

# Rebuild
docker compose build

# Restart
docker compose up -d
```

---

## Documentation Files

- **[BRANCH_CHANGES_DOCUMENTATION.md](./BRANCH_CHANGES_DOCUMENTATION.md)** - Detailed branch diff
- **[README.md](./README.md)** - Main project documentation
- **[docs/implementation-overview.md](./docs/implementation-overview.md)** - Architecture overview
- **[docs/lld.md](./docs/lld.md)** - Low-level design details

---

## Push Checklist

Before pushing to GitHub:

- [ ] All local tests passing (`pytest tests/`)
- [ ] Docker services running and healthy
- [ ] Branch is `swagathupdates` (verify with `git branch`)
- [ ] No uncommitted changes (`git status` is clean)
- [ ] Company email configured in git
- [ ] GitHub credentials updated in VS Code login
- [ ] Verified pushed branch on GitHub web UI
- [ ] Created Pull Request (if team reviews before main merge)

---

## Next Steps After Push

1. **Share with team:** Send PR link to team for review
2. **Code review:** Wait for manager/team approval
3. **Merge to main:** Once approved, create PR from swagathupdates → main
4. **Deploy:** Follow company deployment process
5. **Monitor:** Track OCR/parser performance in production

---

## Support & Contact

For issues or questions:
- Check logs: `docker compose logs -f service_name`
- Review documentation in `docs/` folder
- Check [BRANCH_CHANGES_DOCUMENTATION.md](./BRANCH_CHANGES_DOCUMENTATION.md) for detailed changes

---

**Happy testing! 🚀**

**Branch:** swagathupdates  
**Status:** ✅ Ready for company email push
