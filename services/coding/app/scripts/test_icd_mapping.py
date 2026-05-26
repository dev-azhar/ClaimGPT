"""
Test ICD mapping from parser debug artifacts.

Usage:
    python -m services.coding.app.scripts.test_icd_mapping --file tmp/parser_debug/<file>.json

The script will set CHAT_OPENROUTER_* env vars from the parser config so
LLM calls use OpenRouter, then extract diagnosis keywords and map them
to ICD-10 using the project's RAG index.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def ensure_openrouter_env_from_parser():
    try:
        from services.parser.app.config import settings as parser_settings
    except Exception:
        return
    if getattr(parser_settings, "openrouter_api_key", None):
        os.environ.setdefault("CHAT_OPENROUTER_API_KEY", str(parser_settings.openrouter_api_key))
    if getattr(parser_settings, "openrouter_url", None):
        os.environ.setdefault("CHAT_OPENROUTER_URL", str(parser_settings.openrouter_url))
    if getattr(parser_settings, "openrouter_model", None):
        os.environ.setdefault("CHAT_OPENROUTER_MODEL", str(parser_settings.openrouter_model))


def find_debug_file(provided: str | None) -> Path | None:
    if provided:
        p = Path(provided)
        return p if p.exists() else None
    d = Path("tmp/parser_debug")
    if not d.exists():
        return None
    files = sorted(d.glob("*.json"))
    return files[0] if files else None


def load_parsed_fields(debug_json: Path) -> dict[str, Any]:
    data = json.loads(debug_json.read_text(encoding="utf-8"))
    # Try common locations
    for key in ("parsed_fields", "normalized_fields", "canonical_claim", "renderer_input"):
        v = data.get(key)
        if isinstance(v, dict) and v:
            return v
    # fallback: top-level fields
    return data


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--file", "-f", help="Path to parser debug JSON")
    args = p.parse_args(argv)

    dbg = find_debug_file(args.file)
    if not dbg:
        print("No debug JSON found in tmp/parser_debug/; provide --file path")
        return 2

    print("Using debug file:", dbg)

    # Ensure OpenRouter env for chat LLM is set from parser config
    ensure_openrouter_env_from_parser()

    # Import extractor + rag after env is set
    try:
        from services.coding.app.diagnosis_extractor import (
            needs_extraction,
            extract_diagnosis_keywords,
        )
        from services.coding.app import icd10_rag
    except Exception as e:
        print("Failed to import extractor or rag module:", e)
        return 1

    parsed = load_parsed_fields(dbg)

    # Collect likely diagnosis text fields, prioritize structured locations
    candidates = []
    # 1) canonical diagnosis block (primary/secondary/procedure)
    diag_block = parsed.get("diagnosis") if isinstance(parsed.get("diagnosis"), dict) else None
    if diag_block:
        for key in ("primary", "secondary", "procedure"):
            v = diag_block.get(key)
            if isinstance(v, str) and v.strip():
                candidates.append(v.strip())

    # 2) medical_entities.diagnosis
    med_ent = parsed.get("medical_entities") if isinstance(parsed.get("medical_entities"), dict) else None
    if med_ent:
        d = med_ent.get("diagnosis")
        if isinstance(d, str) and d.strip() and d.strip() not in candidates:
            candidates.append(d.strip())

    # 3) fallback: scan top-level string fields
    if not candidates:
        for k, v in parsed.items():
            if not isinstance(v, str):
                continue
            key = str(k).lower()
            if "diagnos" in key or key in ("impression", "dx", "final_diagnosis"):
                candidates.append(v.strip())

    # 4) final fallback to any text field
    if not candidates:
        for k, v in parsed.items():
            if isinstance(v, str) and v.strip():
                candidates.append(v.strip())
                break

    if not candidates:
        print("No textual fields found in debug file")
        return 1

    raw = "\n\n".join(candidates[:5])
    print("Raw diagnosis summary (exact):\n", raw)

    # Extract diagnosis keywords (LLM-first, will use OpenRouter)
    terms = []
    if needs_extraction(raw):
        terms = extract_diagnosis_keywords(raw)
    if not terms:
        terms = [raw]

    print("\nExtracted diagnosis terms:")
    for t in terms:
        print(" -", t)

    print("\nICD-10 RAG results:")
    for t in terms:
        hits = icd10_rag.search_icd10_rag(t, max_results=5)
        print(f"\nQuery: {t}")
        if not hits:
            print("  (no hits)")
            continue
        for code, desc, cat, score in hits:
            print(f"  {code} — {desc} (category: {cat}, score: {score:.3f})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
