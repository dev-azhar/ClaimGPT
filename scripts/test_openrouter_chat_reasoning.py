"""
Test OpenRouter chat completions with reasoning enabled and preserved reasoning_details.

Usage:
  & .\.venv\Scripts\Activate.ps1
  python scripts/test_openrouter_chat_reasoning.py

Reads API key from `services.parser.app.config.settings.openrouter_api_key`.
"""
import json
import sys
import requests


API_KEY = "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"
MODEL = "openai/gpt-4o-mini"
URL = "https://openrouter.ai/api/v1/chat/completions"

if not API_KEY:
    print("OpenRouter API key not set in settings.openrouter_api_key or OPENROUTER_API_KEY environment variable.")
    sys.exit(2)

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

question = "How many r's are in the word 'strawberry'?"

payload1 = {
    "model": MODEL,
    "messages": [{"role": "user", "content": question}],
    "reasoning": {"enabled": True}
}

print("Sending first request to", URL)
try:
    r1 = requests.post(URL, headers=headers, data=json.dumps(payload1), timeout=30)
    print("Status:", r1.status_code)
    print("Raw response (truncated):\n", r1.text[:2000])
    j1 = r1.json()
except Exception as e:
    print("First request failed:", e)
    sys.exit(1)

# Extract assistant message with reasoning_details
try:
    choice = j1.get("choices", [])[0]
    message = choice.get("message") if isinstance(choice, dict) else None
    if not message:
        print("No assistant message found in response.\nFull response:\n", json.dumps(j1, indent=2))
        sys.exit(1)
    assistant_content = message.get("content")
    reasoning_details = message.get("reasoning_details")
    print("Assistant content:\n", assistant_content)
    print("Reasoning details present:", bool(reasoning_details))
except Exception as e:
    print("Failed to parse first response:", e)
    sys.exit(1)

# Build messages preserving reasoning_details and send follow-up
messages = [
    {"role": "user", "content": question},
    {"role": "assistant", "content": assistant_content, "reasoning_details": reasoning_details},
    {"role": "user", "content": "Are you sure? Think carefully."}
]

payload2 = {"model": MODEL, "messages": messages, "reasoning": {"enabled": True}}
print("Sending second request to", URL)
try:
    r2 = requests.post(URL, headers=headers, data=json.dumps(payload2), timeout=30)
    print("Status:", r2.status_code)
    print("Raw response (truncated):\n", r2.text[:2000])
    try:
        print("Parsed JSON keys:", list(r2.json().keys()) if isinstance(r2.json(), dict) else type(r2.json()))
    except Exception:
        pass
except Exception as e:
    print("Second request failed:", e)
    sys.exit(1)

print("Done.")
