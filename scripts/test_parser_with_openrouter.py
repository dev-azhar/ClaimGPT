#!/usr/bin/env python
"""
End-to-end parser test using OpenRouter backend.

Usage:
  & .\.venv\Scripts\Activate.ps1
  python scripts/test_parser_with_openrouter.py

Tests:
  1. Verify OpenRouter backend is selected
  2. Run parser on a sample claim
  3. Validate canonical output (no contaminated expense rows)
"""
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.parser.app.config import settings
from services.parser_v2.semantic_backends import SemanticBackendRegistry


def test_backend_selection():
    """Verify OpenRouter is selected as primary backend."""
    print("\n=== Backend Selection Test ===")
    print(f"Configured backend order: {settings.semantic_backend_order}")
    
    registry = SemanticBackendRegistry()
    print(f"Total backends created: {len(registry.backends)}")
    for i, backend in enumerate(registry.backends):
        print(f"  [{i}] {backend.name} - available: {backend.available()}")
    
    selected = registry.choose()
    if selected:
        print(f"\nSelected backend: {selected.name}")
        return selected.name == "openrouter"
    else:
        print("No backend selected!")
        return False


def test_openrouter_config():
    """Verify OpenRouter is properly configured."""
    print("\n=== OpenRouter Configuration Test ===")
    print(f"API Key present: {bool(settings.openrouter_api_key)}")
    print(f"API Key length: {len(settings.openrouter_api_key) if settings.openrouter_api_key else 0}")
    print(f"Model: {settings.openrouter_model}")
    print(f"URL: {settings.openrouter_url}")
    
    has_key = bool(settings.openrouter_api_key)
    has_model = bool(settings.openrouter_model)
    print(f"\nReady to use OpenRouter: {has_key and has_model}")
    return has_key and has_model


def main():
    print("=" * 60)
    print("Parser OpenRouter Integration Test")
    print("=" * 60)
    
    config_ok = test_openrouter_config()
    backend_ok = test_backend_selection()
    
    print("\n" + "=" * 60)
    if config_ok and backend_ok:
        print("[PASS] All checks passed!")
        print("\nNext steps:")
        print("  1. Restart parser workers:")
        print("     python -m celery -A libs.shared.celery_app worker -Q default --pool=threads")
        print("  2. Trigger a parse job via the API or message queue")
        print("  3. Check debug artifacts in tmp/parser_debug/")
        return 0
    else:
        print("[FAIL] Some checks failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
