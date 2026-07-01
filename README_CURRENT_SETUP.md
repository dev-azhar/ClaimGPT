# ClaimGPT Setup Guide (Docker Stack - Optimized)

Follow these steps to run the ClaimGPT application. This optimized configuration uses a unified Docker image to reduce memory/disk footprints and local host directory mounts to bypass container space limits.

---

## Prerequisites (Environment Configuration)

Make sure you have `.env` files in both the project root and the `infra/docker/` directory. If they don't exist, copy `.env.example` to `.env` in both locations and configure your API keys:

```properties
# Add your API keys to the .env files
OPENROUTER_API_KEY=your_openrouter_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
```

---

## 1. Setup Local Storage Folders & Permissions

Because we use host bind mounts under `./data` (to bypass virtual disk space limits inside container volumes), you **must** pre-create the storage folders and grant full write permissions so that container-based services (like Postgres and Redis) can write to them.

Run this in your terminal:
```bash
# 1. Create all local data directories
mkdir -p infra/docker/data/pgdata infra/docker/data/pgreplica-data infra/docker/data/redisdata infra/docker/data/miniodata infra/docker/data/shared-storage infra/docker/data/prometheusdata infra/docker/data/grafanadata infra/docker/data/huggingface-cache infra/docker/data/paddlex-models

# 2. Grant full read/write permissions
chmod -R 777 infra/docker/data
```

*(To perform a 100% clean database wipe in the future, run `sudo rm -rf infra/docker/data/*` followed by the mkdir/chmod commands above).*

---

## 2. Stop and Clean Previous Builds
To prevent configuration or caching conflicts, stop any running containers and remove legacy volumes:
```bash
docker-compose -f infra/docker/docker-compose.yml down -v
```

---

## 3. Build & Start the Docker Stack
This command will compile the unified image (`claimgpt-backend:latest`) exactly once and launch the entire 31-container microservice stack:
```bash
docker-compose -f infra/docker/docker-compose.yml up --build -d
```

---

## 4. Initialize Database Tables
After the containers are up and running, you must initialize the database tables by running the setup script inside the active gateway container:
```bash
docker exec -it docker-gateway-1 python init_db.py
```
*(This registers the parser, coding, and predictor schemas in your Postgres database).*

---

## 5. Connecting a Cloud Frontend (e.g. Vercel)

If you are developing inside GitHub Codespaces and want to connect a public frontend (like Vercel) to your backend:

1. Go to the **Ports** tab in your Codespace window.
2. Find port **`8000`** (Nginx Gateway / Router).
3. Right-click on its visibility (`Private`) and change it to **`Public`**.
4. Copy the public **Forwarded Address** of port `8000` (e.g., `https://...-8000.app.github.dev`).
5. Open your **Vercel Dashboard Settings** and configure the environment variables:
   * **`GATEWAY_URL`**: `https://...-8000.app.github.dev` *(No trailing slash)*
   * **Delete** these three variables if they exist in Vercel to force relative routing: `NEXT_PUBLIC_API_BASE`, `NEXT_PUBLIC_CHAT_BASE`, `NEXT_PUBLIC_SUBMISSION_BASE`.
6. Redeploy the frontend:
   ```bash
   npx vercel --prod --force
   ```

---

## 6. Access and Monitoring URLs

* **API Gateway Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs) (Or your public Port 8000 Codespace address)
* **Keycloak Auth Console**: [http://localhost:8080](http://localhost:8080) (Or your public Port 8080 Codespace address)
* **Flower (Celery Monitor)**: [http://localhost:5555/flower/](http://localhost:5555/flower/)
* **MinIO Storage Console**: [http://localhost:9001](http://localhost:9001) (User: `claimgpt` / Pass: `claimgpt123`)
* **Grafana Dashboards**: [http://localhost:3000](http://localhost:3000)
