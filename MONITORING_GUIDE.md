# ClaimGPT Monitoring Guide

This guide explains how the centralized monitoring infrastructure (Prometheus & Grafana) is set up for **ClaimGPT** and how to use the dashboard to monitor system health, throughput, speed, and resource utilization.

---

## 1. Quick Access Links

| Dashboard | Description | Local URL | Tunnel URL |
| :--- | :--- | :--- | :--- |
| **Grafana** | Centralized UI for charts & panels | [http://localhost:8000/grafana/](http://localhost:8000/grafana/) | [Grafana Link](https://smoky-reburial-chaplain.ngrok-free.dev/grafana/) |
| **ClaimGPT Dashboard** | Direct link to health metrics | [http://localhost:8000/grafana/d/claimgpt-health/](http://localhost:8000/grafana/d/claimgpt-health/) | [Dashboard Link](https://smoky-reburial-chaplain.ngrok-free.dev/grafana/d/claimgpt-health/) |
| **Prometheus** | Raw time-series database query engine | [http://localhost:8000/prometheus/](http://localhost:8000/prometheus/) | [Prometheus Link](https://smoky-reburial-chaplain.ngrok-free.dev/prometheus/) |
| **Flower** | Celery worker task execution dashboard | [http://localhost:8000/flower/](http://localhost:8000/flower/) | [Flower Link](https://smoky-reburial-chaplain.ngrok-free.dev/flower/) |

---

## 2. Core Concepts

### Prometheus
Prometheus is an open-source **Time Series Database (TSDB)**. It runs in the background and pulls (scrapes) telemetry data from each running service container every 10 seconds. It stores these values as metrics with timestamps (e.g. "how many requests has `gateway` handled at 12:00:00").

### Grafana
Grafana is the **visualization tool**. It is configured to query the Prometheus database and present the raw data in beautiful, easy-to-read charts, stats, and graphs.

---

## 3. "ClaimGPT E2E Health" Dashboard Overview

The pre-configured dashboard contains panels grouped by purpose:

### A. Uptime & Quality Gates (Top Row)
*   **Healthy / Active Scrape Targets:**
    *   *What it shows:* The number of microservice containers currently reporting online.
    *   *Why it matters:* If a service crashes, this count drops below 13.
*   **Total Processed HTTP Requests:**
    *   *What it shows:* Total API calls handled across the entire system.
*   **HTTP 5xx Server Errors:**
    *   *What it shows:* Counts of server-side crashes/exceptions (status code 500+).
    *   *Why it matters:* Ideally, this is **`0`**. A non-zero value indicates that a service crashed or failed to process a request.

### B. Speed & Volume (Middle Row)
*   **HTTP Throughput by Service (Rate):**
    *   *What it shows:* The rate of API requests in **requests per second (req/s)**.
    *   *Why it matters:* Displays which microservices are under the heaviest load. The **Gateway** (primary load balancer) will typically have the highest curve.
*   **95th Percentile HTTP Request Latency:**
    *   *What it shows:* The response time (in seconds or milliseconds) for 95% of your API requests.
    *   *Why it matters:* Tracks speed. Most normal APIs should respond in under `50ms - 200ms`.

### C. Pipeline Processing (Bottom Rows)
*   **Celery Task Throughput (Rate):**
    *   *What it shows:* The rate of background tasks executed by Celery workers.
    *   *Why it matters:* Visualizes document processing. You will see spikes corresponding to `intake_task`, `ocr_task`, `parser_task`, `coding_task`, and `finalize_claim_task` when documents are uploaded.
*   **Resident Memory Usage by Service:**
    *   *What it shows:* The live RAM memory consumption (in MB/GB) of each container.
    *   *Why it matters:* Helps detect memory leaks.
*   **CPU Utilization rate by Service:**
    *   *What it shows:* The CPU consumption of each microservice.

---

## 4. How to Run Manual Queries in Prometheus

If you want to debug or query specific metrics directly in Prometheus:
1. Open [Prometheus](https://smoky-reburial-chaplain.ngrok-free.dev/prometheus/).
2. Type any of these key metrics in the expression bar:
   *   `http_requests_total` — Total HTTP request counts.
   *   `http_request_duration_seconds_bucket` — Latency distributions.
   *   `flower_task_runtime_seconds_count` — Counts of background Celery tasks.
   *   `process_resident_memory_bytes` — Container memory usage.
3. Click **Execute** and switch to the **Graph** tab to see the plotted chart.

---

## 5. Reverse Proxy Routing (Under the Hood)
All monitoring dashboards are securely routed over HTTPS/HTTP via Nginx on port `8000`:
*   `nginx.conf` proxies subpaths:
    *   `/prometheus/` -> `http://prometheus:9090`
    *   `/grafana/` -> `http://grafana:3000`
    *   `/flower/` -> `http://flower:5555`
*   Grafana has embedding enabled (`GF_SECURITY_ALLOW_EMBEDDING=true` and secure cookies), allowing you to securely display this dashboard inside the Vercel web app.
