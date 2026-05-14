#!/usr/bin/env python
"""
Diagnostic: Show which backend settings a worker process has loaded.

Run this BEFORE and AFTER restarting workers to prove they're still using old config.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# This imports the LIVE settings object from the running process
from services.parser.app.config import settings
from services.parser_v2.semantic_backends import SemanticBackendRegistry

print("=" * 70)
print("CURRENT PROCESS SETTINGS (what this process sees)")
print("=" * 70)
print(f"semantic_backend_order = {settings.semantic_backend_order}")
print(f"OpenRouter API Key present: {bool(settings.openrouter_api_key)}")
print(f"OpenRouter URL: {settings.openrouter_url}")

print("\n" + "=" * 70)
print("BACKEND REGISTRY (what will be chosen for parsing)")
print("=" * 70)

registry = SemanticBackendRegistry()
print(f"Total backends created: {len(registry.backends)}")
for i, backend in enumerate(registry.backends):
    avail = "[AVAILABLE]" if backend.available() else "[NOT AVAILABLE]"
    print(f"  [{i}] {backend.name:20s} {avail}")

selected = registry.choose()
print(f"\nWill use for parsing: {selected.name if selected else 'NONE'}")

print("\n" + "=" * 70)
if selected and selected.name == "openrouter":
    print("[SUCCESS] OpenRouter configured and selected!")
    print("\nThis worker is ready to use OpenRouter for semantic extraction.")
else:
    print("[WARNING] Not using OpenRouter!")
    print("\nPossible causes:")
    print("  1. Worker process was started BEFORE config change")
    print("  2. OpenRouter config is missing")
    print("  3. Another backend has higher priority and is available")
    print("\nSOLUTION: Restart the worker process to reload configuration")

print("=" * 70)
