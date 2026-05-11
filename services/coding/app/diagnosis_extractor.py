"""
Diagnosis-keyword extraction from long unstructured clinical narratives.

Why this exists
---------------
The OCR/parser output for many real-world claim documents puts an entire
admission note (vitals, exam findings, lab values, history, plan) into a
single ``diagnosis`` field. Feeding that as one search query into the
ICD-10 catalog returns near-random results because the dense+BM25
similarity gets diluted by hundreds of irrelevant tokens (BP-121/83,
RR-16, P-88, HBSAG-NR, ...).

This module reduces such a narrative to a *short* list of clean
diagnosis terms before catalog search runs. Each term then becomes its
own query against the ICD-10 index, and the highest-scoring code wins.

Strategy (ordered by priority)
------------------------------
1. **LLM extraction** via the existing chat-service Ollama helper, with a
   strict prompt that returns one diagnosis per line.  Bounded output,
   short timeout, response cached per-text.
2. **Deterministic fallback** that keeps only the parts of the text that
   look like diagnoses: explicit ``Diagnosis:`` / ``Impression:`` /
   ``Final Diagnosis:`` sections, lines that match diagnosis vocabulary,
   and short colon-headed clauses.  This always runs when the LLM is
   unreachable so the pipeline degrades gracefully.

The two paths return the *same* shape: a list of cleaned, lowercase
keyword phrases.  Empty list means "use the original text".
"""

from __future__ import annotations

import functools
import hashlib
import logging
import os
import re
from typing import Iterable

logger = logging.getLogger("coding.diagnosis")

# ──────────────────────────────────────────────────────────────────
# Tunables (env-overridable, sensible defaults for local Ollama).
# ──────────────────────────────────────────────────────────────────

# Trigger keyword extraction only for fields longer than this. Short
# fields like "Type 2 diabetes mellitus" already work well as queries.
LONG_NARRATIVE_THRESHOLD = int(
    os.environ.get("CODING_DIAGNOSIS_LONG_THRESHOLD", "120")
)

# Cap number of clean keywords returned (more = slower coding, more noise).
MAX_KEYWORDS = int(os.environ.get("CODING_DIAGNOSIS_MAX_KEYWORDS", "5"))

# LRU cache size for repeat lookups (same long narrative across pages).
_CACHE_SIZE = int(os.environ.get("CODING_DIAGNOSIS_CACHE_SIZE", "256"))

# Hard ceiling for a single keyword phrase. Anything longer is almost
# certainly the entire narrative again — drop it.
_MAX_PHRASE_LEN = 80

# Vocabulary that lets the deterministic fallback recognize a diagnosis
# line even when no header is present. Kept intentionally short so it
# stays maintainable; the LLM path is the high-recall route.
_DIAGNOSIS_VOCAB = (
    "diabetes",
    "hypertension",
    "pregnancy",
    "labour",
    "labor",
    "delivery",
    "episiotomy",
    "cesarean",
    "c-section",
    "myocardial",
    "infarction",
    "stroke",
    "fracture",
    "appendicitis",
    "cholecystitis",
    "pneumonia",
    "asthma",
    "copd",
    "cancer",
    "carcinoma",
    "tumor",
    "tumour",
    "anemia",
    "anaemia",
    "sepsis",
    "septicaemia",
    "hepatitis",
    "cirrhosis",
    "stone",
    "calculus",
    "hernia",
    "ulcer",
    "gastritis",
    "ckd",
    "chronic kidney",
    "renal failure",
    "heart failure",
    "tuberculosis",
    "dengue",
    "malaria",
    "typhoid",
    "covid",
    "fever",
    "trauma",
    "wound",
    "burn",
    "abscess",
    "syndrome",
    "disorder",
    "disease",
)

# Header patterns that explicitly introduce the diagnosis section.
_HEADER_PATTERNS = [
    re.compile(
        r"(?:^|\n)\s*(?:final\s+diagnosis|primary\s+diagnosis|diagnosis|impression|dx)\s*[:\-]\s*",
        re.IGNORECASE,
    ),
]

# Stop tokens that separate the diagnosis block from the next section.
_HEADER_STOP = re.compile(
    r"(?:^|\n)\s*(?:procedures?|treatment|hospital\s+course|medications?|"
    r"investigation|history|examination|vitals?|plan|discharge\s+condition)"
    r"\b",
    re.IGNORECASE,
)

# Anything that looks like vitals / lab abbreviations. We strip these
# before keyword scoring so they don't pollute results.
_NOISE_RE = re.compile(
    r"\b(?:bp|p|rr|temp|hr|spo2|hb|tlc|wbc|rbc|plt|na|k|cl|cr|esr|"
    r"hbsag|hiv|vdrl|fbs|ppbs|hba1c)\s*[-:]\s*[a-z0-9./+\-]*",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mmhg|mg|ml|kg|cm|wks?|days?|m)?\b", re.IGNORECASE)


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────


def needs_extraction(text: str) -> bool:
    """Should the catalog search run on the raw text or on extracted keywords?

    True for long narratives where direct similarity search is unreliable.
    """
    if not text:
        return False
    return len(text) >= LONG_NARRATIVE_THRESHOLD


def extract_diagnosis_keywords(text: str, max_terms: int = MAX_KEYWORDS) -> list[str]:
    """Reduce a long clinical narrative to a short list of diagnosis terms.

    Tries the LLM first, then falls back to deterministic extraction.
    Always returns at most ``max_terms`` phrases. Empty list means the
    extractor could not isolate anything useful, in which case the caller
    should fall back to using the original text.
    """
    text = (text or "").strip()
    if not text:
        return []
    key = _stable_key(text, max_terms)
    return list(_extract_cached(text, max_terms, key))


def clear_cache() -> None:
    """Clear memoized extraction results (useful in tests)."""
    _extract_cached.cache_clear()


# ──────────────────────────────────────────────────────────────────
# Internals
# ──────────────────────────────────────────────────────────────────


def _stable_key(text: str, max_terms: int) -> str:
    h = hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{h}:{max_terms}"


@functools.lru_cache(maxsize=_CACHE_SIZE)
def _extract_cached(text: str, max_terms: int, _key: str) -> tuple[str, ...]:
    """LLM-first, deterministic-fallback diagnosis keyword extraction."""
    try:
        llm_terms = _try_llm_extract(text, max_terms)
    except Exception:  # never let a buggy LLM helper crash coding
        logger.debug("LLM extractor raised; using deterministic fallback", exc_info=True)
        llm_terms = []
    if llm_terms:
        return tuple(llm_terms[:max_terms])

    fallback = _deterministic_extract(text, max_terms)
    return tuple(fallback[:max_terms])


# ── LLM path ──────────────────────────────────────────────────────


_LLM_SYSTEM = (
    "You extract DIAGNOSES from messy hospital admission notes for medical "
    "coding. Rules:\n"
    "1. Output ONE diagnosis per line, lowercase, no bullets, no numbering.\n"
    "2. Each line must be a short noun phrase a coder can map to ICD-10 "
    "(e.g. 'type 2 diabetes mellitus', 'normal vaginal delivery with "
    "episiotomy', 'acute myocardial infarction').\n"
    "3. Skip vital signs, lab values, history, exam findings, medications, "
    "procedures, and patient demographics.\n"
    "4. Skip negative findings ('HBsAg-NR', 'HIV negative', 'no fever').\n"
    "5. Output AT MOST {n} lines. If none found, output exactly the word: "
    "NONE\n"
    "6. Do not explain, do not repeat the input, do not add extra text."
)


def _try_llm_extract(text: str, max_terms: int) -> list[str]:
    """Use the chat-service Ollama helper if available; return [] on any failure."""
    try:
        # Local import keeps coding service standalone if chat is missing.
        from services.chat.app.llm import _call_ollama  # type: ignore
    except Exception:
        return []

    system = _LLM_SYSTEM.format(n=max_terms)
    user = (
        "Extract diagnoses from this admission note:\n\n"
        f"{text[:4000]}"  # ollama context guard
    )
    try:
        # _call_ollama is a sync wrapper around httpx; protect it with a
        # very short timeout via the env-tunable inside the chat module.
        raw = _call_ollama(system, [{"role": "user", "content": user}])
    except Exception as exc:
        logger.debug("LLM diagnosis extraction failed: %s", exc)
        return []

    return _parse_llm_lines(raw, max_terms)


def _parse_llm_lines(raw: str, max_terms: int) -> list[str]:
    """Coerce the LLM's free-form reply into a clean keyword list."""
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        # Strip bullets, numbering, quotes, commas at end.
        cleaned = re.sub(r"^[\s\-\*\d\.\)\(]+", "", line).strip(" .,:;\"'")
        if not cleaned:
            continue
        low = cleaned.lower()
        if low in {"none", "n/a", "null"}:
            continue
        if len(cleaned) > _MAX_PHRASE_LEN:
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(low)
        if len(out) >= max_terms:
            break
    return out


# ── Deterministic fallback ────────────────────────────────────────


def _deterministic_extract(text: str, max_terms: int) -> list[str]:
    """No-LLM path: header-based, then vocab-based, then keyword window."""
    candidates: list[str] = []

    # 1. Pull the 'Diagnosis:' / 'Impression:' / ... block if present.
    section = _diagnosis_section(text)
    if section:
        candidates.extend(_split_clauses(section))

    # 2. Otherwise scan all lines for medical vocabulary.
    if not candidates:
        for line in re.split(r"[\n;\.]+", text):
            line = line.strip()
            if 4 <= len(line) <= _MAX_PHRASE_LEN and _has_diagnosis_vocab(line):
                candidates.append(line)

    # 3. Last resort: even a single long unbroken sentence — pick a small
    #    window of words around each matched vocab token.
    if not candidates:
        candidates.extend(_keyword_windows(text, max_terms=max_terms * 2))

    return list(_postprocess(candidates, max_terms))


def _keyword_windows(text: str, max_terms: int, span: int = 4) -> list[str]:
    """For each vocab match, extract ``span`` tokens before/after it.

    Useful when the parser handed us one giant comma-less paragraph and
    no header to split on.
    """
    tokens = re.findall(r"[A-Za-z][A-Za-z\-]+", text)
    lower_tokens = [t.lower() for t in tokens]
    seen: set[str] = set()
    out: list[str] = []
    for i, tok in enumerate(lower_tokens):
        if not any(v in tok for v in _DIAGNOSIS_VOCAB):
            continue
        # Some vocab entries are multi-word — match exact substring on join.
        start = max(0, i - span)
        end = min(len(tokens), i + span + 1)
        phrase = " ".join(tokens[start:end]).lower()
        if phrase in seen or len(phrase) < 4 or len(phrase) > _MAX_PHRASE_LEN:
            continue
        seen.add(phrase)
        out.append(phrase)
        if len(out) >= max_terms:
            break
    return out


def _diagnosis_section(text: str) -> str:
    for pat in _HEADER_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        tail = text[m.end():]
        stop = _HEADER_STOP.search(tail)
        return (tail[: stop.start()] if stop else tail).strip()
    return ""


def _split_clauses(section: str) -> list[str]:
    parts = re.split(r"[\n;\.]+|\s+\d+[\)\.]\s+", section)
    return [p.strip(" -:") for p in parts if p and p.strip()]


def _has_diagnosis_vocab(line: str) -> bool:
    low = line.lower()
    return any(term in low for term in _DIAGNOSIS_VOCAB)


def _postprocess(items: Iterable[str], max_terms: int) -> Iterable[str]:
    seen: set[str] = set()
    for it in items:
        cleaned = _NUMBER_RE.sub(" ", _NOISE_RE.sub(" ", it)).strip(" -:,.")
        cleaned = re.sub(r"\s+", " ", cleaned).lower()
        if not cleaned or len(cleaned) < 4:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        yield cleaned
        if len(seen) >= max_terms:
            return
