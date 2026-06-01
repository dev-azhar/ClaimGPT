#!/usr/bin/env python3
"""
Diagnostic script to test if the OpenRouter API key is active and working.
Uses ONLY standard library modules so it runs on any python installation without pip.
Specifically checks both the root .env and the Docker infra/docker/.env.

Usage:
  python scripts/test_openrouter_key.py
"""
import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

# Setup paths
root_dir = Path(__file__).resolve().parent.parent
root_env_path = root_dir / ".env"
docker_env_path = root_dir / "infra" / "docker" / ".env"

def read_key_from_env_file(path: Path) -> str:
    if not path.exists():
        return ""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                if key.strip() == "OPENROUTER_API_KEY":
                    return val.strip()
    return ""

def mask_key(key: str) -> str:
    if not key:
        return "None / Empty"
    if len(key) <= 12:
        return "****"
    return f"{key[:8]}...{key[-8:]}"

def test_api_key(key_to_test: str, model: str, url: str) -> bool:
    headers = {
        "Authorization": f"Bearer {key_to_test}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/google-deepmind/claimgpt",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a validation utility. Output exactly the word 'SUCCESS' if you receive this."},
            {"role": "user", "content": "Ping test."}
        ],
        "max_tokens": 10,
        "temperature": 0.0
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            status_code = response.status
            response_body = response.read().decode("utf-8")
            
            if status_code == 200:
                res_data = json.loads(response_body)
                choices = res_data.get("choices", [])
                if choices:
                    reply = choices[0].get("message", {}).get("content", "").strip()
                    if reply == "SUCCESS" or len(reply) > 0:
                        return True
            return False

    except Exception:
        return False

def main():
    print("=" * 70)
    print(" CLAIMGPT: OPENROUTER API KEY DIAGNOSTIC TEST (Zero-Dependency Version)")
    print("=" * 70)

    # Load keys
    root_key = read_key_from_env_file(root_env_path)
    docker_key = read_key_from_env_file(docker_env_path)

    openrouter_model = "openai/gpt-4o-mini"
    openrouter_url = "https://openrouter.ai/api/v1/chat/completions"

    print("\n[1] Environment Files Check:")
    print(f"  - Root .env Location:        {root_env_path}")
    print(f"    Key found:                 {mask_key(root_key)}")
    print(f"  - Docker .env Location:      {docker_env_path}")
    print(f"    Key found:                 {mask_key(docker_key)}")

    # 2. Match Validation
    print("\n[2] Key Consistency Verification:")
    if root_key != docker_key:
        print("  [MISMATCH] The keys in root .env and infra/docker/.env do NOT match!")
        print("             Docker will use the key configured in infra/docker/.env.")
    else:
        print("  [OK] The keys in root .env and infra/docker/.env match perfectly.")

    # 3. Connection Tests
    print("\n[3] Testing Root .env API Key:")
    if not root_key:
        print("  No key to test in root .env.")
    else:
        success = test_api_key(root_key, openrouter_model, openrouter_url)
        print(f"  Result: {'[WORKING]' if success else '[FAILED / 402 / INVALID]'}")

    print("\n[4] Testing Docker .env API Key:")
    if not docker_key:
        print("  No key to test in Docker .env.")
    else:
        success = test_api_key(docker_key, openrouter_model, openrouter_url)
        print(f"  Result: {'[WORKING]' if success else '[FAILED / 402 / INVALID]'}")

    # 5. Fixing Steps
    print("\n" + "=" * 70)
    print(" ACTION REQUIRED TO FIX YOUR DOCKER CONTAINERS")
    print("=" * 70)
    print(f"1. Open the Docker env file:")
    print(f"   {docker_env_path}")
    print(f"2. Replace the OPENROUTER_API_KEY with your working key:")
    print(f"   OPENROUTER_API_KEY={root_key if root_key else 'sk-or-v1-xxxxxxxx'}")
    print("3. Restart your Docker containers:")
    print("   docker compose down && docker compose up -d")
    print("=" * 70)

if __name__ == "__main__":
    main()
