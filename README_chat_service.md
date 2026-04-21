# ClaimGPT Chat Service Setup Guide

This guide will help you set up and run the ClaimGPT **Chat Service** on your local system.

---



## 1. Create and Activate Virtual Environment

```
# Create venv (if not present)
python -m venv .venv

# Activate venv (Windows)
.\.venv\Scripts\activate

# (On Mac/Linux: source .venv/bin/activate)
```

---

## 3. Install Python Dependencies

```
pip install -r requirements.txt
```
To install packages required for chat service
```
pip install -r services\chat\requirements.txt
```

## 4. Install and Set Up Ollama

The chat service uses **Ollama** to run LLMs locally.

### 4.1 Install Ollama

- **Windows / Mac:** Download and install from https://ollama.com/download
- **Linux:**
  ```
  curl -fsSL https://ollama.com/install.sh | sh
  ```
### 4.2 Verify Ollama is Running

After installation, Ollama starts automatically. Confirm it's running:

```
ollama --version
```

Or check the API is reachable:

```
curl http://localhost:11434
```

You should see: `Ollama is running`

---

## 5. Configure Environment Variables 

The chat service requires the following environment variables. Set them in your `services\chat\app\config.py` file :

### Getting Langfuse API Keys
Used for agent tracing and observibility (laency, cost,prompt versioning, evaluation, token usage etc)

1. Go to [https://cloud.langfuse.com](https://cloud.langfuse.com) and sign up or log in.

2. After logging in, click **New Project** and give it a name (e.g. `claimgpt`).

3. Once inside the project, go to **Settings** (left sidebar) → **API Keys**.

4. Click **Create new API key**.

5. Copy credentials add to `services\chat\app\config.py` file:

```

# Langfuse (observability) 
LANGFUSE_PUBLIC_KEY=your_public_key
LANGFUSE_SECRET_KEY=your_secret_key
LANGFUSE_HOST=host

```

- If Langfuse keys are not set, the service will still run but observability will be skipped.

---

## 6. Start Infrastructure (Postgres, Redis, MinIO)

```
docker compose -f infra/docker/docker-compose.yml up -d postgres redis minio
```

---


## 7. Start Backend 

Open a new terminal for each:

```
uvicorn main:app --reload --port 8000

```

---

## 8. Start Frontend (if needed)

```
cd ui/web
npm install
npm run dev
```

---

## 9. Start Celery 

```
python -m celery -A libs.shared.celery_app worker --loglevel=info -Q celery --pool=threads --concurrency=4
```
---

## 10. Access the Application

- Frontend: http://localhost:3000
- **API docs: http://localhost:8000/docs**

---

## 11. Chat Service API Overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check (DB status) |
| `POST` | `/{session_id}/message` | Send a message, get a full response |
| `POST` | `/{session_id}/stream` | Send a message, stream response via SSE |
| `GET` | `/{session_id}/history` | Retrieve conversation history |
| `GET` | `/providers` | List available LLM providers |
| `POST` | `/fields/apply` | Apply add/modify/delete actions on claim fields |

---

## 12. Deactivate Virtual Environment (when done)

```
deactivate
```

---
