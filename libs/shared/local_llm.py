from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Any

logger = logging.getLogger("shared.local_llm")

_llm = None
_llm_load_attempted = False
_lock = threading.Lock()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0))
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def _get_llm():
    global _llm, _llm_load_attempted
    if _llm_load_attempted:
        return _llm

    with _lock:
        if _llm_load_attempted:
            return _llm
        _llm_load_attempted = True

        model_path = os.getenv("LOCAL_LLM_GGUF_PATH", "").strip()
        if not model_path:
            logger.info("LOCAL_LLM_GGUF_PATH not set; local LLM disabled")
            return None

        if not os.path.exists(model_path):
            logger.warning("Local GGUF model file not found: %s", model_path)
            return None

        try:
            from llama_cpp import Llama

            n_ctx = int(os.getenv("LOCAL_LLM_N_CTX", "4096"))
            n_threads = int(os.getenv("LOCAL_LLM_N_THREADS", "8"))
            _llm = Llama(
                model_path=model_path,
                n_ctx=n_ctx,
                n_threads=n_threads,
                verbose=False,
            )
            logger.info("Local llama.cpp model loaded: %s", model_path)
            return _llm
        except Exception:
            logger.exception("Failed to initialize llama-cpp local model")
            return None


def generate_semantic_json(
    prompt: str,
    schema: dict[str, Any] | None = None,
    max_tokens: int = 900,
    temperature: float = 0.0,
) -> dict[str, Any] | None:
    llm = _get_llm()
    if llm is None:
        return None

    schema_hint = ""
    if schema:
        schema_hint = f"JSON schema (follow this shape): {json.dumps(schema)}\n"

    final_prompt = (
        "You are an expert medical claim extraction model.\n"
        "Return ONLY valid JSON object. No prose. No markdown.\n"
        f"{schema_hint}"
        "Input:\n"
        f"{prompt}"
    )

    try:
        output = llm(
            final_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=["\n\n```", "\nEND"],
        )
        text = output.get("choices", [{}])[0].get("text", "")
        return _extract_json_object(text)
    except Exception:
        logger.exception("Local semantic generation failed")
        return None
