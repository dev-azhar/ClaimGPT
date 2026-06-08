# ClaimGPT Setup Guide (Docker Stack)

Follow these steps to run the ClaimGPT application. This guide ensures all code updates are built from scratch in Docker, database migrations are applied before the main services boot, and the stack runs cleanly.

---

## 1. Environment Configuration
Make sure you have `.env` files in both the project root and the `infra/docker/` directory. If they don't exist, copy `.env.example` to `.env` in both locations and configure your API keys:
```properties
# Add your API keys to the .env files
OPENROUTER_API_KEY=your_openrouter_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
```

---

## 2. Clean and Stop Previous Builds
Stop all running containers and clean up existing Docker resources to prevent conflicts:
```powershell
docker compose -f infra/docker/docker-compose.yml down
```

---

## 3. Build Containers from Scratch
Build all backend and worker Docker images from scratch to compile the pulled code changes:
```powershell
docker compose -f infra/docker/docker-compose.yml build --no-cache
```

---

## 4. Start the Database Container
Start only the database services and wait for them to become healthy before running migrations:
```powershell
docker compose -f infra/docker/docker-compose.yml up -d postgres
```

---

## 5. Run Database Migrations
Apply the alembic database migrations using a temporary one-off container *without* starting any other dependent backend containers or workers (by using the `--no-deps` flag, which prevents other services from trying to connect to an unmigrated database):
```powershell
docker compose -f infra/docker/docker-compose.yml run --rm --no-deps gateway alembic upgrade head
```
*(Note: The `gateway` container image pre-installs `alembic`. The schema script initialized by Postgres on first boot contains the head version markers so this command will verify schema alignment instantly without conflicts.)*

---

## 6. Start the Rest of the Stack
Now that the database is fully updated, launch all backend services, workers, and infrastructure in the background:
```powershell
docker compose -f infra/docker/docker-compose.yml up -d
```

---

## 7. Start the Frontend
The frontend runs locally using Node.js:
```powershell
cd ui/web
npm install
npm run dev
```

---

## 8. Access and Monitoring URLs

- **Frontend UI**: [http://localhost:3000](http://localhost:3000)
- **API Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Flower (Celery Worker Monitor)**: [http://localhost:5555/flower/](http://localhost:5555/flower/)
- **MinIO Storage Console**: [http://localhost:9001](http://localhost:9001) (User: `claimgpt` / Pass: `claimgpt123`)
