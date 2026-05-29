import os
import sys
import json

# Try to load .env file manually to avoid dependency issues
env_vars = {}
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                env_vars[key.strip()] = val.strip()

import urllib.request
import urllib.error

# Retrieve OpenRouter settings with fallbacks
api_key = env_vars.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
model = env_vars.get("OPENROUTER_MODEL") or os.environ.get("OPENROUTER_MODEL", "google/gemma-4-31b-it:free")
url = env_vars.get("OPENROUTER_URL") or os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")

print("==================================================")
print("             OPENROUTER API TESTER                ")
print("==================================================")
print(f"URL:   {url}")
print(f"Model: {model}")

if not api_key:
    print("\n[ERROR] OPENROUTER_API_KEY is not set in your .env file!")
    print("Please open your '.env' file and add your key like this:")
    print("OPENROUTER_API_KEY=your-actual-api-key-here")
    sys.exit(1)

# Support multiple keys separated by commas or pipes
keys = [k.strip() for k in api_key.replace("|", ",").split(",") if k.strip()]
print(f"Parsed {len(keys)} API keys from config.")

payload = {
    "model": model,
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello! Please reply with exactly the phrase 'OpenRouter connectivity check successful.' and nothing else."}
    ],
    "max_tokens": 50,
    "temperature": 0.1,
}

for idx, key in enumerate(keys):
    masked_key = key[:8] + "..." + key[-8:] if len(key) > 16 else "***"
    print(f"\n--------------------------------------------------")
    print(f"Testing Key {idx+1}/{len(keys)}: {masked_key}")
    print(f"--------------------------------------------------")

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    try:
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
        
        with urllib.request.urlopen(req, timeout=15) as response:
            status_code = response.status
            resp_data = response.read().decode("utf-8")
            data = json.loads(resp_data)
            
        print(f"[HTTP Status] {status_code} (urllib)")
        
        if status_code == 200:
            if data and "choices" in data:
                choice = data["choices"][0]
                content = choice.get("message", {}).get("content", "").strip()
                print(f"[SUCCESS] Key {idx+1} is WORKING!")
                print(f"Response: \"{content}\"")
            else:
                print(f"[WARNING] HTTP Status 200 but response format was unexpected:")
                print(json.dumps(data, indent=2))
                
    except urllib.error.HTTPError as e:
        status_code = e.code
        error_msg = e.read().decode("utf-8", errors="ignore")
        print(f"[HTTP Status] {status_code} (urllib)")
        
        if status_code == 401:
            print("[ERROR] HTTP 401 Unauthorized!")
            print("This key is invalid, revoked, or expired.")
        elif status_code == 429:
            print("[ERROR] HTTP 429 Too Many Requests!")
            print("This key has exceeded its rate limits or run out of free credits.")
        elif status_code == 400:
            print("[ERROR] HTTP 400 Bad Request!")
            print(f"Details: {error_msg}")
        else:
            print(f"[ERROR] HTTP Error {status_code}:")
            print(error_msg)

    except Exception as e:
        print(f"[ERROR] Connection failed: {e}")
        print("Please verify your internet connection.")

print("\n==================================================")
