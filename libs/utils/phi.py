"""
PHI / PII scrubbing utilities.

Used before sending data to external LLMs, logging, or any
context where protected health information must be redacted.
"""

from __future__ import annotations

import re

# Compiled patterns for performance
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE_RE = re.compile(r"\b(?:\+?1[-.]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
_MRN_RE = re.compile(r"\bMRN[:\s#]*\d{4,12}\b", re.IGNORECASE)
_DOB_RE = re.compile(
    r"\b(?:DOB|Date of Birth|Birth Date)[:\s]*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b",
    re.IGNORECASE,
)
_POLICY_RE = re.compile(r"\b[A-Z]{2,4}\d{8,15}\b")

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (_SSN_RE, "[SSN_REDACTED]"),
    (_PHONE_RE, "[PHONE_REDACTED]"),
    (_EMAIL_RE, "[EMAIL_REDACTED]"),
    (_MRN_RE, "[MRN_REDACTED]"),
    (_DOB_RE, "[DOB_REDACTED]"),
    (_POLICY_RE, "[POLICY_REDACTED]"),
]


def scrub_phi(text: str, extra_patterns: dict[str, str] | None = None) -> str:
    """
    Remove PHI/PII from text using regex patterns.

    Parameters
    ----------
    text : str
        The input text potentially containing PHI.
    extra_patterns : dict, optional
        Additional {regex_pattern: replacement} pairs.

    Returns
    -------
    str
        Text with PHI replaced by redaction tokens.
    """
    result = text
    for pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)

    if extra_patterns:
        for pat_str, repl in extra_patterns.items():
            result = re.sub(pat_str, repl, result)

    return result
