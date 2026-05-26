"""
End-to-end HTTP smoke test of the live ClaimGPT gateway.

Hits every router in services/ at least once and prints a pass/fail
table. Read-only by default — does NOT mutate data.

Usage:
    PYTHONPATH=. python tmp/e2e_smoke.py
"""

from __future__ import annotations

import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8000"

# Exit code: 0 if every probe returned an acceptable status, else 1
results: list[tuple[str, str, int, str, float]] = []


def probe(method: str, path: str, body: dict | None = None,
          ok_codes: tuple[int, ...] = (200, 204), timeout: float = 30.0) -> tuple[int, str, float]:
    url = f"{BASE}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, method=method, headers=headers)
    t0 = time.perf_counter()
    try:
        with urlopen(req, timeout=timeout) as resp:
            ms = (time.perf_counter() - t0) * 1000
            return resp.status, "ok", ms
    except HTTPError as e:
        ms = (time.perf_counter() - t0) * 1000
        body_preview = ""
        try:
            body_preview = e.read().decode("utf-8", errors="replace")[:120]
        except Exception:
            pass
        ok = "ok" if e.code in ok_codes else f"HTTP {e.code}: {body_preview}"
        return e.code, ok, ms
    except URLError as e:
        return 0, f"NET {e}", (time.perf_counter() - t0) * 1000
    except Exception as e:  # noqa: BLE001
        return 0, f"ERR {e}", (time.perf_counter() - t0) * 1000


def check(label: str, method: str, path: str, body: dict | None = None,
          ok_codes: tuple[int, ...] = (200, 204)) -> bool:
    code, msg, ms = probe(method, path, body, ok_codes=ok_codes)
    ok = msg == "ok" or code in ok_codes
    results.append((label, f"{method} {path}", code, msg if not ok else "ok", ms))
    return ok


# ── 1. Health endpoints ──
check("root health",       "GET", "/health")
check("chat health",       "GET", "/chat/health")
check("coding health",     "GET", "/coding/health")
check("ocr health",        "GET", "/ocr/health")
check("parser health",     "GET", "/parser/health")
check("predictor health",  "GET", "/predictor/health")
check("validator health",  "GET", "/validator/health")
check("workflow health",   "GET", "/workflow/health")
check("search health",     "GET", "/search/health")

# ── 2. Discover claims & pick a real seeded one ──
code, msg, ms = probe("GET", "/ingress/claims?limit=100")
results.append(("ingress.list", "GET /ingress/claims?limit=100", code, msg, ms))
sample_claim = None
processed_claim = None
try:
    raw = urlopen(Request(f"{BASE}/ingress/claims?limit=100", headers={"Accept": "application/json"})).read()
    items = json.loads(raw)
    if isinstance(items, dict):
        items = items.get("items") or items.get("claims") or []
    for it in items:
        cid = it.get("id") or it.get("claim_id")
        if not cid:
            continue
        status = (it.get("status") or "").upper()
        if sample_claim is None:
            sample_claim = cid
        # Prefer a claim that's already through the pipeline
        if status in {"COMPLETED", "MANUAL_REVIEW_REQUIRED", "APPROVED", "REJECTED", "DECISIONED"} and processed_claim is None:
            processed_claim = cid
        if processed_claim:
            break
except Exception as e:
    print(f"!! could not parse claims list: {e}")

print(f"sample_claim    = {sample_claim}")
print(f"processed_claim = {processed_claim}")
target = processed_claim or sample_claim
print(f"using target    = {target}")

# ── 3. Ingress GET single ──
if target:
    check("ingress.get",        "GET", f"/ingress/claims/{target}")

# ── 4. OCR result ──
if target:
    check("ocr.claim",          "GET", f"/ocr/claim/{target}", ok_codes=(200, 404))
    check("ocr.validate",       "GET", f"/ocr/validate/{target}", ok_codes=(200, 404))

# ── 5. Parser result ──
if target:
    check("parser.get",         "GET", f"/parser/parse/{target}", ok_codes=(200, 404))

# ── 6. Coding suggestions ──
if target:
    check("coding.get",         "GET", f"/coding/code-suggest/{target}", ok_codes=(200, 404))
    check("coding.cache_stats", "GET", "/coding/search/cache-stats")

# ── 7. Predictor ──
if target:
    check("predictor.features", "GET", f"/predictor/features/{target}", ok_codes=(200, 404))
    check("predictor.predict",  "GET", f"/predictor/predict/{target}", ok_codes=(200, 404))

# ── 8. Validator ──
if target:
    check("validator.get",      "GET", f"/validator/validate/{target}", ok_codes=(200, 404))

# ── 9. Submission ──
if target:
    check("submission.preview", "GET", f"/submission/claims/{target}/preview", ok_codes=(200, 404))
    check("submission.audit",   "GET", f"/submission/claims/{target}/audit", ok_codes=(200, 404))

# ── 10. Search endpoints (catalog-side RAG/BM25/hybrid) ──
check("search.dense",    "GET", "/search/?q=diabetes&mode=dense&limit=3")
check("search.bm25",     "GET", "/search/?q=diabetes&mode=bm25&limit=3")
check("search.hybrid",   "GET", "/search/?q=diabetes&mode=hybrid&limit=3")
check("search.stats",    "GET", "/search/index/stats", ok_codes=(200, 404))

# ── 11. Chat providers + history ──
check("chat.providers",  "GET", "/chat/providers")

# ── Print table ──
print()
print(f"{'label':<24} {'endpoint':<58} {'code':>5}  {'time':>7}  status")
print("-" * 120)
fails = 0
for label, ep, code, msg, ms in results:
    status = "PASS" if msg == "ok" else "FAIL"
    if status == "FAIL":
        fails += 1
    print(f"{label:<24} {ep:<58} {code:>5}  {ms:>6.0f}ms  {status}  {'' if msg == 'ok' else msg[:80]}")

print()
print(f"Total: {len(results)} probes, {fails} fail(s)")
sys.exit(1 if fails else 0)
