"""Replace the reranker section in icd10_rag.py."""
import re

path = r"c:\Project\ClaimGPT\services\coding\app\icd10_rag.py"
content = open(path, encoding="utf-8").read()

start_marker = "def _try_llm_rerank_icd(query:"
end_marker = "\ndef lookup_icd10_rag"
start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

new_functions = r'''def _try_llm_rerank_icd(query: str, candidates: list[tuple[str, str, str, float]]) -> str | None:
    """Ask OpenRouter to pick the best ICD code. Disabled by default (CODING_ENABLE_LLM_RERANK=1 to enable)."""
    if not candidates:
        return None
    if os.environ.get("CODING_ENABLE_LLM_RERANK", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    try:
        import httpx
        from services.parser.app.config import settings as parser_settings  # type: ignore
    except Exception:
        return None
    api_key = getattr(parser_settings, "openrouter_api_key", "") or os.environ.get("OPENROUTER_API_KEY", "")
    model = getattr(parser_settings, "openrouter_model", "") or os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    url = getattr(parser_settings, "openrouter_url", "") or "https://openrouter.ai/api/v1/chat/completions"
    if not api_key:
        return None
    short_list = sorted(candidates, key=lambda item: item[3], reverse=True)[:40]
    system_prompt = (
        "You are an ICD-10 reranker. Choose the single best ICD-10 code from the candidates. "
        "Prefer the code that matches the primary clinical event. "
        "When both a parent code and a subtype are candidates, prefer the parent unless the query specifies the subtype. "
        "Return only the code, no explanation."
    )
    candidate_block = "\n".join(f"- {code}: {desc} [{cat}]" for code, desc, cat, _score in short_list)
    user_message = f"Query: {query}\n\nCandidates:\n{candidate_block}\n\nPick the single best code."
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
        "temperature": 0.0,
        "max_tokens": 12,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        resp = httpx.post(url, json=payload, headers=headers,
                          timeout=int(os.environ.get("CODING_RERANKER_TIMEOUT", "20")))
        resp.raise_for_status()
        data = resp.json()
        raw = ""
        if isinstance(data, dict) and data.get("choices"):
            msg = data["choices"][0].get("message", {})
            raw = str(msg.get("content") or "") if isinstance(msg, dict) else str(msg)
        _persist_icd_rerank_debug("openrouter_icd_rerank", query, short_list,
                                  system_prompt, user_message, raw)
        codes = {c.upper(): c for c, *_ in short_list}
        norm = re.sub(r"[^A-Z0-9.]", "", raw.upper())
        if norm in codes:
            return codes[norm]
        for c in codes.values():
            if c.upper() in raw.upper():
                return c
        return None
    except Exception:
        logger.debug("LLM reranker (OpenRouter) failed", exc_info=True)
        return None


def _try_crossencoder_rerank(query: str, candidates: list[tuple[str, str, str, float]]) -> str | None:
    """Rerank ICD candidates using a cross-encoder model.

    A cross-encoder takes (query, candidate_description) as a PAIR and produces
    a direct relevance score in a single forward pass.  This is far more accurate
    than bi-encoder cosine similarity (S-PubMedBert) because the model attends to
    BOTH texts simultaneously.

    Model: cross-encoder/ms-marco-MiniLM-L-6-v2 (fast, ~50ms/batch on CPU).
    Override via CODING_CROSSENCODER_MODEL env var.
    """
    global _crossencoder_model, _crossencoder_load_attempted
    if not candidates:
        return None
    try:
        if _crossencoder_model is None and not _crossencoder_load_attempted:
            _crossencoder_load_attempted = True
            from sentence_transformers import CrossEncoder  # type: ignore
            _crossencoder_model = CrossEncoder(_CROSSENCODER_MODEL)
            logger.info("Loaded cross-encoder reranker: %s", _CROSSENCODER_MODEL)
        if _crossencoder_model is None:
            return None
        # Score top-50 candidates; cross-encoder is fast enough for this pool size.
        short_list = sorted(candidates, key=lambda item: item[3], reverse=True)[:50]
        pairs = [(query, f"{desc} | {cat}") for code, desc, cat, _score in short_list]
        scores = _crossencoder_model.predict(pairs, show_progress_bar=False)
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        chosen_code = short_list[best_idx][0]
        # Prefer parent code when it scores within threshold of the best child.
        parent_pref = float(os.environ.get("CODING_PARENT_PREF_THRESH", "0.05"))
        for i, (code, _desc, _cat, _) in enumerate(short_list):
            if "." in code:
                parent = code.split(".", 1)[0]
                for j, (pcode, *_rest) in enumerate(short_list):
                    if pcode == parent:
                        if (best_score - float(scores[j])) <= parent_pref:
                            chosen_code = parent
                        break
        try:
            _persist_icd_rerank_debug("crossencoder_rerank", query, short_list,
                                      f"cross_encoder:{_CROSSENCODER_MODEL}",
                                      "cross_encoder_relevance_scoring", chosen_code)
        except Exception:
            pass
        return chosen_code
    except Exception:
        logger.debug("Cross-encoder reranker failed", exc_info=True)
        return None


def _try_local_clinical_rerank(query: str, candidates: list[tuple[str, str, str, float]]) -> str | None:
    """S-PubMedBert bi-encoder fallback reranker (used when cross-encoder is unavailable)."""
    global _clinical_embed_model
    if not candidates:
        return None
    try:
        if _clinical_embed_model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore
            _clinical_embed_model = SentenceTransformer(
                os.environ.get("CLINICAL_EMBED_MODEL", "pritamdeka/S-PubMedBert-MS-MARCO")
            )
        short_list = sorted(candidates, key=lambda item: item[3], reverse=True)[:16]
        texts = [query] + [f"{desc} | {cat}" for code, desc, cat, _ in short_list]
        embs = _clinical_embed_model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        q_emb = embs[0]
        q_norm = sqrt((q_emb * q_emb).sum())
        sims = np.array([
            float((q_emb @ e) / (q_norm * sqrt((e * e).sum()))) if q_norm * sqrt((e * e).sum()) > 0 else 0.0
            for e in embs[1:]
        ])
        best_idx = int(np.argmax(sims))
        best_score = float(sims[best_idx])
        chosen = short_list[best_idx][0]
        parent_pref = float(os.environ.get("CODING_PARENT_PREF_THRESH", "0.05"))
        for i, (code, *_) in enumerate(short_list):
            if "." in code:
                parent = code.split(".", 1)[0]
                for j, (pcode, *_r) in enumerate(short_list):
                    if pcode == parent and (best_score - float(sims[j])) <= parent_pref:
                        chosen = parent
                        break
        try:
            _persist_icd_rerank_debug("local_clinical_rerank", query, candidates,
                                      "bi_encoder:S-PubMedBert", "cosine_rerank", chosen)
        except Exception:
            pass
        return chosen
    except Exception:
        logger.debug("Local clinical reranker unavailable or failed", exc_info=True)
        return None

'''

new_content = content[:start_idx] + new_functions + content[end_idx:]
open(path, "w", encoding="utf-8").write(new_content)
print(f"Done. Total lines: {new_content.count(chr(10))}")

# Quick syntax check
import py_compile
try:
    py_compile.compile(path, doraise=True)
    print("Syntax OK")
except py_compile.PyCompileError as e:
    print(f"SYNTAX ERROR: {e}")
