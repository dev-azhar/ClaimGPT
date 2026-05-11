#!/usr/bin/env python3
"""Verify that the active Python environment matches the pinned versions in
requirements.txt.

Exits 0 when everything matches, 1 when there is drift.
Designed to be cheap (uses importlib.metadata, no network) so it can run
inside a pre-push hook.

Usage:
    python infra/scripts/verify_deps.py [requirements.txt ...]
"""

from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

# Match lines like: "package[extra,extra]==1.2.3"  (only fully-pinned entries)
PIN_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9_.\-]+)(?:\[[^\]]+\])?\s*==\s*(?P<version>[^\s;]+)"
)


def _norm(name: str) -> str:
    """PEP 503 canonical name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_pins(req_file: Path) -> list[tuple[str, str, int]]:
    """Return list of (name, version, line_no) for fully-pinned entries."""
    pins: list[tuple[str, str, int]] = []
    for i, raw in enumerate(req_file.read_text().splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = PIN_RE.match(line)
        if m:
            pins.append((m.group("name"), m.group("version"), i))
    return pins


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    files = [Path(p) for p in argv[1:]] or [repo_root / "requirements.txt"]

    drift: list[str] = []
    missing: list[str] = []
    checked = 0

    for req_file in files:
        if not req_file.exists():
            print(f"❌ requirements file not found: {req_file}", file=sys.stderr)
            return 1
        for name, expected, lineno in parse_pins(req_file):
            checked += 1
            try:
                installed = metadata.version(name)
            except metadata.PackageNotFoundError:
                missing.append(f"  {name}=={expected}  ({req_file.name}:{lineno})")
                continue
            if installed != expected:
                drift.append(
                    f"  {name}: installed={installed} expected={expected} "
                    f"({req_file.name}:{lineno})"
                )

    if drift or missing:
        print("❌ Dependency drift detected:\n", file=sys.stderr)
        if drift:
            print("Mismatched versions:", file=sys.stderr)
            print("\n".join(drift), file=sys.stderr)
        if missing:
            print("\nNot installed:", file=sys.stderr)
            print("\n".join(missing), file=sys.stderr)
        print(
            "\nFix with:  make sync   (or: pip install -r requirements.txt --upgrade)",
            file=sys.stderr,
        )
        return 1

    print(f"✅ {checked} pinned dependencies match requirements.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
