#!/usr/bin/env python3
"""Verify that the active Python environment matches the pinned versions in
requirements.txt, and that per-service requirements files do not declare
conflicting specifiers for any package that is also pinned in the root file.

Exits 0 when everything matches, 1 when there is drift or cross-file conflict.
Designed to be cheap (uses importlib.metadata, no network) so it can run
inside a pre-push hook.

Usage:
    python infra/scripts/verify_deps.py                # check installed env
    python infra/scripts/verify_deps.py --cross-check  # check service files
    python infra/scripts/verify_deps.py --all          # both
"""

from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

# Match a fully-pinned entry: "package[extra]==1.2.3"
PIN_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9_.\-]+)(?:\[[^\]]+\])?\s*==\s*(?P<version>[^\s;]+)"
)
# Match any specifier line: "package[extra]>=1.2.3" / "==" / "<" / ...
SPEC_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9_.\-]+)(?:\[[^\]]+\])?\s*"
    r"(?P<op>==|>=|<=|<|>|~=|!=)\s*(?P<version>[^\s;,]+)"
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


def parse_specs(req_file: Path) -> dict[str, tuple[str, str, int]]:
    """Return {canonical_name: (op, version, line_no)} for any specifier line."""
    specs: dict[str, tuple[str, str, int]] = {}
    for i, raw in enumerate(req_file.read_text().splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = SPEC_RE.match(line)
        if m:
            specs[_norm(m.group("name"))] = (m.group("op"), m.group("version"), i)
    return specs


def check_installed(files: list[Path]) -> int:
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


def cross_check(repo_root: Path) -> int:
    """Verify per-service requirements.txt files do not conflict with root pins."""
    root = repo_root / "requirements.txt"
    if not root.exists():
        print(f"❌ root requirements file not found: {root}", file=sys.stderr)
        return 1

    root_specs = parse_specs(root)
    service_files = sorted((repo_root / "services").glob("*/requirements.txt"))

    conflicts: list[str] = []
    checked = 0

    for svc in service_files:
        svc_specs = parse_specs(svc)
        for pkg, (op, ver, lineno) in svc_specs.items():
            if pkg in root_specs:
                checked += 1
                r_op, r_ver, _ = root_specs[pkg]
                if (op, ver) != (r_op, r_ver):
                    conflicts.append(
                        f"  {pkg}: root [{r_op}{r_ver}]  vs  "
                        f"{svc.relative_to(repo_root)}:{lineno} [{op}{ver}]"
                    )

    if conflicts:
        print("❌ Per-service requirements drift from root:\n", file=sys.stderr)
        print("\n".join(conflicts), file=sys.stderr)
        print(
            "\nAlign service files to root specifiers, or update root if intentional.",
            file=sys.stderr,
        )
        return 1

    print(
        f"✅ {checked} shared pins consistent across "
        f"{len(service_files)} service requirements files"
    )
    return 0


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    args = argv[1:]

    do_cross = "--cross-check" in args or "--all" in args
    do_install = "--cross-check" not in args or "--all" in args
    files = [Path(a) for a in args if not a.startswith("--")] or [
        repo_root / "requirements.txt"
    ]

    rc = 0
    if do_install:
        rc |= check_installed(files)
    if do_cross:
        rc |= cross_check(repo_root)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
