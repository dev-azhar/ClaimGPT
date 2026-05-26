"""Quick test script for OpenRouter-hosted model

Usage:
  & .\.venv\Scripts\Activate.ps1
  python scripts/test_openrouter_model.py

It reads API key and model from `services.parser.app.config.settings`.
"""
import json
import sys
import httpx
from services.parser.app.config import settings

MODEL = getattr(settings, "openrouter_model", "openai/gpt-oss-120b:free")
API_KEY = getattr(settings, "openrouter_api_key", None)
URL = getattr(settings, "openrouter_url", "https://api.openrouter.ai/v1/completions")

PROMPT = (
    "You are a JSON-only responder. Return a JSON object with keys: region_type, table_kind, confidence,"
    " fields (list), tables (list). Return one example field and one table row. Strict JSON only."
)

if not API_KEY:
    print("OpenRouter API key is not set in settings.openrouter_api_key or OPENROUTER_API_KEY env var.")
    sys.exit(2)

headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

def try_endpoint(url: str) -> None:
    print(f"Trying {url} with model {MODEL}")
    # Try chat-style payload first
    chat_payload = {"model": MODEL, "messages": [{"role": "user", "content": PROMPT}], "max_output_tokens": 512}
    completions_payload = {"model": MODEL, "input": PROMPT, "max_output_tokens": 512}

    for payload, name in ((chat_payload, "chat-style"), (completions_payload, "completions-style")):
        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=30)
        except Exception as e:
            print(f"Request to {url} ({name}) failed: {e}")
            continue

        print(f"Status: {r.status_code}")
        text = r.text
        print("Raw response (first 2000 chars):")
        print(text[:2000])
        try:
            j = r.json()
            print("Response JSON type:", type(j))
            if isinstance(j, dict):
                print("JSON keys:", list(j.keys()))
                # Try common shapes
                if "choices" in j and isinstance(j["choices"], list) and j["choices"]:
                    ch = j["choices"][0]
                    msg = ch.get("message") or ch.get("delta") or ch.get("text") or None
                    print("choices[0] snippet:", msg if isinstance(msg, str) else (msg and (msg.get('content') if isinstance(msg, dict) else str(msg))))
                if "output" in j:
                    print("output:", j.get("output"))
                if "result" in j:
                    print("result:", j.get("result"))
                if "response" in j:
                    print("response:", j.get("response"))
        except Exception as e:
            print("Failed to parse JSON from response:", e)


# Try the configured URL first, then the chat variant
candidates = [URL]
if "/completions" in URL and not URL.endswith("/chat/completions"):
    candidates.append(URL.replace("/completions", "/chat/completions"))
elif "/chat/completions" in URL:
    candidates.append(URL.replace("/chat/completions", "/completions"))
else:
    # Add chat endpoint as common alternative
    candidates.append("https://api.openrouter.ai/v1/chat/completions")

for url in candidates:
    try_endpoint(url)

print("Done.")
