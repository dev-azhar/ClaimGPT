# ClaimGPT - swagathupdates Branch

Quick start guide for running the application locally.

---

## Prerequisites

- Node.js 18+
- Python 3.9+
- Docker & Docker Compose
- Git

---

## Quick Start

### 1. Pull the Branch

```bash
git checkout swagathupdates
git pull origin swagathupdates
```

### 2. Start Backend (Port 8000)

```bash
cd /path/to/ClaimGPT

# Start all backend services + PostgreSQL
docker compose up -d

# Verify backend is running on port 8000
curl http://localhost:8000/health
```

This starts:
- **PostgreSQL** (database on 5432)
- **API Gateway** (FastAPI on port 8000)
- **All microservices** (OCR, Parser, Ingress, etc.)

### 3. Start Frontend (Port 3000)

In a new terminal:

```bash
cd ui/web

# Install dependencies (first time only)
npm install

# Run development server (port 3000)
npm run dev
```

### 4. Access the Application

- **Web UI:** http://localhost:3000
- **API Gateway & Docs:** http://localhost:8000/docs

---

## What's New in This Branch?

✨ **Key Features Added:**
- **PaddleOCR Backend** - Better OCR accuracy with Vision-Language support
- **Identity Gating** - Automatic patient name validation across documents
- **Demographic Backfill** - Fills missing fields from priority-ordered documents
- **Smart Parser** - Document-type aware field extraction with allowlists

For detailed changes, see [BRANCH_CHANGES_DOCUMENTATION.md](./BRANCH_CHANGES_DOCUMENTATION.md)

---

## Development Workflow

### Check Backend Health (Port 8000)

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "healthy", "services": {"ocr": "running", "parser": "running"}}
```

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f parser
docker compose logs -f ocr
docker compose logs -f ingress
```

### Stop Backend (Port 8000)

```bash
docker compose down
```

### Rebuild Backend After Code Changes

```bash
# If you modified backend code
docker compose build

# Then restart
docker compose up -d

# Verify running on port 8000
curl http://localhost:8000/health
```

---

## Database & Environment

### Database Initialization

PostgreSQL starts automatically. Schema is applied on container startup.

To manually apply migrations:
```bash
docker compose exec postgres psql -U postgres -d claimgpt < infra/db/claimgpt_schema.sql
```

### Environment Variables

Create `.env` in project root (optional):

```env
# Database
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/claimgpt
POSTGRES_PASSWORD=postgres

# OCR
ENABLE_PADDLE_OCR=true
ENABLE_PADDLE_VL=true

# Parser
PARSER_STRUCTURED_EXTRACTION_ENABLED=false
PARSER_USE_DEMOGRAPHIC_BACKFILL=true

# API
API_HOST=0.0.0.0
API_PORT=8000
```

---

## Testing

### Run Tests

```bash
# All tests
pytest tests/ -v

# Specific service tests
pytest tests/ocr/ -v
pytest tests/parser/ -v
pytest tests/ingress/ -v
```

### Manual API Testing

```bash
# Upload claim
curl -X POST http://localhost:8000/ingress/upload \
  -F "claim_id=test-123" \
  -F "documents=@file.pdf"

# Get preview
curl http://localhost:8000/parser/claims/test-123/preview

# Get report
curl http://localhost:8000/submission/claims/test-123/report
```

---

## Troubleshooting

### Port Already in Use

```bash
# Change port in npm
npm run dev -- -p 3001

# Or kill process using port 3000
lsof -ti:3000 | xargs kill -9  # macOS/Linux
```

### Docker Services Not Starting

```bash
# Check logs
docker compose logs postgres
docker compose logs ocr

# Restart
docker compose down
docker compose up -d
```

### PaddleOCR Models Not Downloaded

```bash
# Download models
python -c "from paddleocr import PaddleOCR; ocr = PaddleOCR(lang='en')"
```

---

## Pushing to GitHub

When ready to submit:

```bash
# Verify branch
git branch  # Should show * swagathupdates

# Push to remote
git push origin swagathupdates -u

# Check it's there
git branch -r
```

---

## Documentation

- **[BRANCH_CHANGES_DOCUMENTATION.md](./BRANCH_CHANGES_DOCUMENTATION.md)** - What changed vs main
- **[docs/implementation-overview.md](./docs/implementation-overview.md)** - Architecture
- **[README.md](./README.md)** - Full project documentation

---

## Support

Issues? Check:
1. `docker compose logs -f` - service logs
2. `curl http://localhost:8000/health` - API health
3. Browser console (F12) - frontend errors

---

**Happy coding! 🚀**
