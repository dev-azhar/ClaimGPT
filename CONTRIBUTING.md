# Contributing to ClaimGPT

Thanks for contributing! This guide explains how to get a PR merged smoothly.

## Quick start

1. Fork the repo and create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-change
   ```
2. Make your changes and commit with a clear message.
3. Run the local checks before pushing:
   ```bash
   pip install -r requirements-dev.txt
   python -m pytest tests/ -v
   python -m ruff check services/ libs/    # optional, informational
   ```
4. Push and open a Pull Request against `main`.

## What is required to merge

A PR can be merged once:

- ✅ The **`test`** CI job passes.
- ✅ At least one maintainer review approves the change.
- ✅ The branch is up to date with `main` (resolve conflicts via rebase or merge).

## What is NOT required (informational only)

- ⚠️ The **`quality`** job (ruff + mypy) runs on every PR but is **non-blocking**.
  Contributors are encouraged to fix lint/type warnings, but they will not
  prevent your PR from merging.

## Resolving merge conflicts

```bash
git fetch origin
git rebase origin/main
# fix conflicts, then:
git add .
git rebase --continue
git push --force-with-lease
```

## Need help?

Open a draft PR early and tag a maintainer — we're happy to help get it across
the finish line.
