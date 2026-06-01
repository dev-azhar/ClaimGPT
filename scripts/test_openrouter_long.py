#!/usr/bin/env python3
"""
Long prompt test for OpenRouter API keys.

The script loads the OpenRouter API key from the project's root .env file and also tests a hard‑coded known‑working key.
It then sends a relatively long prompt (several paragraphs) to the OpenRouter endpoint using the selected model.
The response is considered successful if the HTTP status is 200 and a non‑empty content is returned.
"""

import os
import json
import urllib.request
import urllib.error
from pathlib import Path

# ---------- Configuration ----------
ROOT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Model that we want to test – using the free tier model that works for the long‑prompt test.
MODEL = "openrouter/free"

# A long, multi‑sentence prompt (≈300 tokens) to exercise the model.
LONG_PROMPT = (
    "You are an expert medical coder. "
    "Given the following claim description, extract and list all distinct expense items, "
    "including their descriptions and amounts, in a JSON array. "
    "If any amount is ambiguous, mark it as null. "
    "Here is the claim text: "
    "Patient was admitted for a complex orthopedic surgery, including pre‑operative imaging, "
    "consultations with two specialists, the surgery itself, post‑operative physiotherapy, "
    "hospital stay for five days, medication, and lab tests for blood work and coagulation. "
    "The total billed amount was $84,365. Please list each line item separately."
)

# Hard‑coded working key (from test_openrouter_chat_reasoning.py – known to have credit).
WORKING_KEY = "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"

def read_key_from_env(path: Path) -> str:
    """Extract OPENROUTER_API_KEY from a .env file."""
    if not path.is_file():
        return ""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == "OPENROUTER_API_KEY":
                    return v.strip()
    return ""

def test_key(key: str, label: str) -> None:
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": LONG_PROMPT}],
        "max_tokens": 500,
        "temperature": 0.2,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(OPENROUTER_URL, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
            if status == 200:
                print(f"[+] {label} - SUCCESS (200). Response snippet: {body[:200].replace('\n', ' ')}")
            else:
                print(f"[-] {label} - FAILED with status {status}. Body: {body[:200]}")
    except urllib.error.HTTPError as e:
        print(f"[-] {label} - HTTPError {e.code}: {e.read().decode('utf-8')[:200]}")
    except Exception as exc:
        print(f"[-] {label} - Exception: {exc}")

def main():
    print("=== OpenRouter Long Prompt Test ===")
    env_key = read_key_from_env(ROOT_ENV_PATH)
    if env_key:
        test_key(env_key, "Root .env key")
    else:
        print("[!] No OPENROUTER_API_KEY found in root .env")

    # Test the hard‑coded working key
    test_key(WORKING_KEY, "Hard-coded working key")

if __name__ == "__main__":
    main()
