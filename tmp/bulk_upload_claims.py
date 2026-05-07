"""Bulk upload files to the ClaimGPT ingress API.

Each immediate subfolder inside the input directory is uploaded as one claim.

Usage:
    python bulk_upload_claims.py --api http://localhost:8000 \
        --input-dir C:\\path\\to\\documents \
        --concurrency 6 \
        --batch-mode

Batch mode behaviour (--batch-mode):
    - Claims inside a batch  → uploaded in PARALLEL
    - Batches themselves     → run SEQUENTIALLY
    - Before advancing to the next batch the script POLLS the API until
      every Celery task in the current batch reaches a terminal state
      (complete / failed / cancelled).  Only then does the next batch start.

Sliding-window mode (default, no --batch-mode):
    - All claims fire at once, throttled to --concurrency in-flight.
    - No inter-batch waiting; all treated as one batch.

Optional metadata CSV columns: file_name,policy_id,patient_id

Results →
         bulk_upload_results_<timestamp>.csv
         bulk_upload_results_<timestamp>.txt
         bulk_upload_results_<timestamp>.json
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
    ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".json", ".xml", ".html",
}
MIME_TYPES = {
    ".pdf":   "application/pdf",
    ".png":   "image/png",
    ".jpg":   "image/jpeg",
    ".jpeg":  "image/jpeg",
    ".tif":   "image/tiff",
    ".tiff":  "image/tiff",
    ".bmp":   "image/bmp",
    ".webp":  "image/webp",
    ".doc":   "application/msword",
    ".docx":  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls":   "application/vnd.ms-excel",
    ".xlsx":  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv":   "text/csv",
    ".txt":   "text/plain",
    ".json":  "application/json",
    ".xml":   "application/xml",
    ".html":  "text/html",
}

# Celery polling defaults (overridable via CLI flags)
POLL_INTERVAL_SEC = 5
POLL_TIMEOUT_SEC  = 600
TERMINAL_STATUSES = {"complete", "completed", "failed", "error", "cancelled", "canceled"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FileMetadata:
    policy_id:  str | None = None
    patient_id: str | None = None


@dataclass
class UploadGroup:
    group_key: str
    files:     list[Path]
    metadata:  FileMetadata


@dataclass
class UploadResult:
    group_key:           str
    files:               list[str]
    batch_number:        int
    upload_status:       str           # "OK" or "FAIL"
    celery_status:       str | None    # final Celery task status after polling
    claim_id:            str | None
    error:               str | None
    # Pinpoints exactly where failure occurred (None when upload_status=="OK"):
    #   "file_open"     — could not open a local file for reading
    #   "http_upload"   — network/connection error during POST
    #   "http_status"   — server returned non-2xx HTTP status
    #   "celery_failed" — Celery task reached failed/error/cancelled state
    #   "celery_timeout"— Celery task did not finish within poll_timeout
    #   "celery_poll"   — status endpoint consistently unreachable
    failure_stage:       str | None
    upload_started_at:   str
    upload_finished_at:  str
    upload_duration_sec: float
    celery_wait_sec:     float         # time spent polling until terminal state


@dataclass
class BatchSummary:
    batch_number:        int
    total_claims:        int
    upload_ok:           int
    upload_fail:         int
    celery_complete:     int
    celery_failed:       int
    wall_duration_sec:   float         # total wall time incl. Celery polling
    upload_duration_sec: float         # time until all HTTP uploads finished
    celery_wait_sec:     float         # additional time waiting for Celery
    fastest_upload_sec:  float
    slowest_upload_sec:  float
    avg_upload_sec:      float
    started_at:          str
    finished_at:         str


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

def load_metadata_map(metadata_csv: Path | None) -> dict[str, FileMetadata]:
    if metadata_csv is None:
        return {}
    mapping: dict[str, FileMetadata] = {}
    with metadata_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            file_name = (row.get("file_name") or "").strip()
            if not file_name:
                continue
            mapping[file_name] = FileMetadata(
                policy_id=(row.get("policy_id") or "").strip() or None,
                patient_id=(row.get("patient_id") or "").strip() or None,
            )
    return mapping


def _merge_group_metadata(files: list[Path], metadata_map: dict[str, FileMetadata]) -> FileMetadata:
    merged = FileMetadata()
    for fp in files:
        meta = metadata_map.get(fp.name)
        if meta is None:
            continue
        if merged.policy_id is None and meta.policy_id is not None:
            merged.policy_id = meta.policy_id
        if merged.patient_id is None and meta.patient_id is not None:
            merged.patient_id = meta.patient_id
    return merged


# ---------------------------------------------------------------------------
# Group building
# ---------------------------------------------------------------------------

def build_upload_groups(
    input_dir:    Path,
    recursive:    bool,
    metadata_map: dict[str, FileMetadata],
) -> list[UploadGroup]:
    if recursive:
        candidate_dirs = sorted({
            path.parent
            for path in input_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS
        })
    else:
        candidate_dirs = [p for p in sorted(input_dir.iterdir()) if p.is_dir()]

    groups:     list[UploadGroup] = []

    scan = (
        (lambda d: sorted(p for p in d.rglob("*")   if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS))
        if recursive else
        (lambda d: sorted(p for p in d.iterdir()    if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS))
    )

    for folder in candidate_dirs:
        files = scan(folder)
        if files:
            groups.append(UploadGroup(
                group_key=folder.name,
                files=files,
                metadata=_merge_group_metadata(files, metadata_map),
            ))

    root_files = sorted(
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS
    )
    for fp in root_files:
        groups.append(UploadGroup(
            group_key=fp.name,
            files=[fp],
            metadata=metadata_map.get(fp.name, FileMetadata()),
        ))

    return sorted(groups, key=lambda g: g.group_key.lower())


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

async def upload_one(
    client:   httpx.AsyncClient,
    api_base: str,
    files:    list[Path],
    metadata: FileMetadata,
) -> dict[str, Any]:
    """POST files to /ingress/claims and return the JSON response."""
    payload: dict[str, str] = {}
    if metadata.policy_id  is not None: payload["policy_id"]  = metadata.policy_id
    if metadata.patient_id is not None: payload["patient_id"] = metadata.patient_id

    multipart: list[tuple[str, tuple[str, Any, str]]] = []
    handles:   list[Any] = []
    try:
        for fp in files:
            h = fp.open("rb")
            handles.append(h)
            ct = MIME_TYPES.get(fp.suffix.lower(), "application/octet-stream")
            multipart.append(("files", (fp.name, h, ct)))
        response = await client.post(
            f"{api_base.rstrip('/')}/ingress/claims",
            data=payload,
            files=multipart,
        )
    finally:
        for h in handles:
            h.close()

    response.raise_for_status()
    return response.json()


async def fetch_claim_status(
    client:   httpx.AsyncClient,
    api_base: str,
    claim_id: str,
) -> str | None:
    """
    Poll GET /ingress/claims/{claim_id} and return the status string.
    Returns None on any HTTP/network error so the caller retries next cycle.

    Adjust the response field names below if your API uses different keys.
    """
    try:
        response = await client.get(
            f"{api_base.rstrip('/')}/ingress/claims/{claim_id}",
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        return (
            data.get("status")
            or data.get("processing_status")
            or data.get("state")
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-claim timed upload
# ---------------------------------------------------------------------------

async def _timed_upload(
    client:       httpx.AsyncClient,
    api_base:     str,
    upload_group: UploadGroup,
    batch_number: int,
) -> UploadResult:
    started_at = datetime.now().isoformat(timespec="seconds")
    t0 = time.perf_counter()

    # ── attempt upload, classify failure stage on any exception ──────────
    failure_stage: str | None = None
    error_msg:     str | None = None
    claim_id:      str | None = None

    try:
        # Pre-check: can we open all files?  Catches permission/missing errors
        # before we even touch the network.
        for fp in upload_group.files:
            try:
                fp.open("rb").close()
            except OSError as e:
                raise _StagedError("file_open", str(e)) from e

        result   = await upload_one(client, api_base, upload_group.files, upload_group.metadata)
        claim_id = result.get("id") or result.get("claim_id")

    except _StagedError as exc:
        failure_stage = exc.stage
        error_msg     = exc.message
    except httpx.HTTPStatusError as exc:
        failure_stage = "http_status"
        error_msg     = f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
        failure_stage = "http_upload"
        error_msg     = str(exc)
    except Exception as exc:
        failure_stage = "http_upload"
        error_msg     = str(exc)

    duration    = time.perf_counter() - t0
    finished_at = datetime.now().isoformat(timespec="seconds")
    ok          = failure_stage is None

    return UploadResult(
        group_key=upload_group.group_key,
        files=[f.name for f in upload_group.files],
        batch_number=batch_number,
        upload_status="OK" if ok else "FAIL",
        celery_status=None,
        claim_id=str(claim_id) if claim_id is not None else None,
        error=error_msg,
        failure_stage=failure_stage,
        upload_started_at=started_at,
        upload_finished_at=finished_at,
        upload_duration_sec=round(duration, 3),
        celery_wait_sec=0.0,
    )


class _StagedError(Exception):
    """Internal exception that carries a failure_stage label."""
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage   = stage
        self.message = message


# ---------------------------------------------------------------------------
# Celery polling gate — blocks until every claim in the batch is terminal
# ---------------------------------------------------------------------------

async def wait_for_batch_completion(
    client:        httpx.AsyncClient,
    api_base:      str,
    results:       list[UploadResult],
    poll_interval: int = POLL_INTERVAL_SEC,
    poll_timeout:  int = POLL_TIMEOUT_SEC,
) -> None:
    """
    Polls the status endpoint for every accepted claim until each reports a
    terminal Celery status or the timeout expires.

    Mutates result.celery_status and result.celery_wait_sec in-place.

    THIS IS THE GATE: run_strict_batches awaits this before starting the
    next batch, so Batch N+1 never starts while Batch N's Celery workers
    are still running.
    """
    pending: dict[str, UploadResult] = {
        r.claim_id: r
        for r in results
        if r.upload_status == "OK" and r.claim_id is not None
    }

    if not pending:
        print("  (no claims to poll — skipping Celery wait)")
        return

    poll_start = time.perf_counter()
    deadline   = poll_start + poll_timeout

    print(f"\n  Waiting for {len(pending)} Celery task(s) to reach terminal state "
          f"(polling every {poll_interval}s, timeout={poll_timeout}s)…")

    while pending and time.perf_counter() < deadline:
        await asyncio.sleep(poll_interval)

        newly_done: list[str] = []
        for claim_id, result in list(pending.items()):
            status = await fetch_claim_status(client, api_base, claim_id)
            if status is None:
                continue  # transient error — retry next cycle
            result.celery_status   = status
            result.celery_wait_sec = round(time.perf_counter() - poll_start, 3)
            if status.lower() in TERMINAL_STATUSES:
                icon = "v" if status.lower() in {"complete", "completed"} else "x"
                if status.lower() not in {"complete", "completed"}:
                    result.failure_stage = "celery_failed"
                print(f"    [{icon}] claim={claim_id} ({result.group_key}) "
                      f"-> celery_status={status}  celery_wait={result.celery_wait_sec}s")
                newly_done.append(claim_id)

        for cid in newly_done:
            del pending[cid]

        if pending:
            print(f"      still waiting on {len(pending)} claim(s)…")

    # Mark any that exceeded the timeout
    for claim_id, result in pending.items():
        result.celery_status   = "timeout"
        result.failure_stage   = "celery_timeout"
        result.celery_wait_sec = round(time.perf_counter() - poll_start, 3)
        print(f"    [!] claim={claim_id} ({result.group_key}) TIMED OUT after "
              f"{result.celery_wait_sec}s")


# ---------------------------------------------------------------------------
# Batch summary builder
# ---------------------------------------------------------------------------

def _build_batch_summary(
    batch_num:       int,
    batch_results:   list[UploadResult],
    wall_duration:   float,
    upload_end_ts:   float,
    batch_t0:        float,
    started_at:      str,
) -> BatchSummary:
    upload_secs   = [r.upload_duration_sec for r in batch_results]
    upload_done   = upload_end_ts - batch_t0
    celery_wait   = wall_duration - upload_done

    celery_complete = sum(
        1 for r in batch_results
        if r.celery_status and r.celery_status.lower() in {"complete", "completed"}
    )
    celery_failed = sum(
        1 for r in batch_results
        if r.celery_status and r.celery_status.lower() not in {"complete", "completed"}
    )

    return BatchSummary(
        batch_number=batch_num,
        total_claims=len(batch_results),
        upload_ok=sum(1 for r in batch_results if r.upload_status == "OK"),
        upload_fail=sum(1 for r in batch_results if r.upload_status == "FAIL"),
        celery_complete=celery_complete,
        celery_failed=celery_failed,
        wall_duration_sec=round(wall_duration, 3),
        upload_duration_sec=round(upload_done, 3),
        celery_wait_sec=round(max(celery_wait, 0.0), 3),
        fastest_upload_sec=round(min(upload_secs), 3),
        slowest_upload_sec=round(max(upload_secs), 3),
        avg_upload_sec=round(sum(upload_secs) / len(upload_secs), 3),
        started_at=started_at,
        finished_at=datetime.now().isoformat(timespec="seconds"),
    )


# ---------------------------------------------------------------------------
# Core runners
# ---------------------------------------------------------------------------

async def run_strict_batches(
    client:        httpx.AsyncClient,
    api_base:      str,
    upload_groups: list[UploadGroup],
    batch_size:    int,
    json_logger:   JsonLogger,
) -> tuple[list[UploadResult], list[BatchSummary]]:
    """
    Execution model:
        for each batch:
            1. Fire all claims in parallel      (asyncio.gather — all start at once)
            2. Block until ALL HTTP POSTs done  (gather awaits all)
            3. Poll until ALL Celery tasks done (wait_for_batch_completion)
            4. Flush JSON log for this batch    ← written to disk right here
            5. ONLY NOW move to next batch
    """
    all_results:     list[UploadResult] = []
    batch_summaries: list[BatchSummary] = []

    batches = [
        upload_groups[i: i + batch_size]
        for i in range(0, len(upload_groups), batch_size)
    ]

    for batch_num, batch in enumerate(batches, start=1):
        print(f"\n{'='*70}")
        print(f"  BATCH {batch_num}/{len(batches)}  —  {len(batch)} claims uploading in parallel")
        print(f"{'='*70}")
        started_at = datetime.now().isoformat(timespec="seconds")
        batch_t0   = time.perf_counter()

        # Step 1 + 2: parallel upload, block until all HTTP requests finish
        batch_results: list[UploadResult] = await asyncio.gather(*[
            _timed_upload(client, api_base, g, batch_number=batch_num)
            for g in batch
        ])
        upload_end_ts = time.perf_counter()

        print(f"\n  All HTTP uploads done in {upload_end_ts - batch_t0:.3f}s")
        for r in batch_results:
            _print_upload_result(r)

        # Step 3: block until every Celery task in this batch is terminal
        # Next batch CANNOT start until this returns.
        await wait_for_batch_completion(client, api_base, batch_results)

        wall_duration = time.perf_counter() - batch_t0
        summary = _build_batch_summary(
            batch_num, batch_results, wall_duration,
            upload_end_ts, batch_t0, started_at,
        )
        batch_summaries.append(summary)
        all_results.extend(batch_results)

        # Step 4: flush JSON immediately — this batch is now fully on disk
        json_logger.flush_batch(batch_results, summary)

        print(
            f"\n  Batch {batch_num} fully done in {summary.wall_duration_sec:.3f}s  "
            f"(http={summary.upload_duration_sec}s + celery_wait={summary.celery_wait_sec}s)  "
            f"upload: {summary.upload_ok} OK / {summary.upload_fail} FAIL  |  "
            f"celery: {summary.celery_complete} complete / {summary.celery_failed} failed"
        )

    return all_results, batch_summaries


async def run_sliding_window(
    client:        httpx.AsyncClient,
    api_base:      str,
    upload_groups: list[UploadGroup],
    concurrency:   int,
    json_logger:   JsonLogger,
) -> tuple[list[UploadResult], list[BatchSummary]]:
    """Sliding-window: keep `concurrency` uploads in-flight; no Celery polling."""
    sem = asyncio.Semaphore(concurrency)

    async def guarded(g: UploadGroup) -> UploadResult:
        async with sem:
            return await _timed_upload(client, api_base, g, batch_number=1)

    started_at = datetime.now().isoformat(timespec="seconds")
    t0 = time.perf_counter()
    results: list[UploadResult] = await asyncio.gather(*[guarded(g) for g in upload_groups])
    wall = time.perf_counter() - t0

    for r in results:
        _print_upload_result(r)

    upload_secs = [r.upload_duration_sec for r in results]
    summary = BatchSummary(
        batch_number=1,
        total_claims=len(results),
        upload_ok=sum(1 for r in results if r.upload_status == "OK"),
        upload_fail=sum(1 for r in results if r.upload_status == "FAIL"),
        celery_complete=0,
        celery_failed=0,
        wall_duration_sec=round(wall, 3),
        upload_duration_sec=round(wall, 3),
        celery_wait_sec=0.0,
        fastest_upload_sec=round(min(upload_secs), 3),
        slowest_upload_sec=round(max(upload_secs), 3),
        avg_upload_sec=round(sum(upload_secs) / len(upload_secs), 3),
        started_at=started_at,
        finished_at=datetime.now().isoformat(timespec="seconds"),
    )
    json_logger.flush_batch(results, summary)
    return results, [summary]


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def _print_upload_result(r: UploadResult) -> None:
    files_label = ", ".join(r.files)
    timing = (f"started={r.upload_started_at}  finished={r.upload_finished_at}  "
              f"upload_took={r.upload_duration_sec}s")
    if r.upload_status == "OK":
        print(f"  OK    {r.group_key} [{files_label}]  claim={r.claim_id}")
        print(f"        {timing}")
    else:
        print(f"  FAIL  {r.group_key} [{files_label}]  error={r.error}")
        print(f"        {timing}")


# ---------------------------------------------------------------------------
# File output
# ---------------------------------------------------------------------------

def write_results(
    results:         list[UploadResult],
    batch_summaries: list[BatchSummary],
    total_duration:  float,
    output_dir:      Path,
    mode:            str,
    ts:              str,
) -> None:
    output_dir = (
        output_dir
        if output_dir.exists() and output_dir.is_dir()
        else Path("./tmp/bulk_test_debug")
    )
    csv_path  = output_dir / f"bulk_upload_results_{ts}.csv"
    txt_path  = output_dir / f"bulk_upload_results_{ts}.txt"

    # ── CSV ─────────────────────────────────────────────────────────────────
    fields = [
        "batch_number", "group_key", "files",
        "upload_status", "failure_stage", "celery_status", "claim_id", "error",
        "upload_started_at", "upload_finished_at",
        "upload_duration_sec", "celery_wait_sec",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow({
                "batch_number":        r.batch_number,
                "group_key":           r.group_key,
                "files":               " | ".join(r.files),
                "upload_status":       r.upload_status,
                "failure_stage":       r.failure_stage or "",
                "celery_status":       r.celery_status or "",
                "claim_id":            r.claim_id or "",
                "error":               r.error or "",
                "upload_started_at":   r.upload_started_at,
                "upload_finished_at":  r.upload_finished_at,
                "upload_duration_sec": r.upload_duration_sec,
                "celery_wait_sec":     r.celery_wait_sec,
            })

    # ── TXT ─────────────────────────────────────────────────────────────────
    total      = len(results)
    ok_count   = sum(1 for r in results if r.upload_status == "OK")
    fail_count = total - ok_count

    L: list[str] = []
    sep  = "=" * 80
    dash = "-" * 80

    L += [sep, "  ClaimGPT Bulk Upload - Results Report", sep]
    L += [
        f"  Mode            : {mode}",
        f"  Generated at    : {datetime.now().isoformat(timespec='seconds')}",
        f"  Total claims    : {total}",
        f"  Upload OK       : {ok_count}",
        f"  Upload FAIL     : {fail_count}",
        f"  Total wall time : {total_duration:.3f}s",
        "",
    ]

    # Batch summary table
    L += [dash, "  BATCH TIMING SUMMARY", dash]
    L.append(
        f"  {'Batch':<7} {'Claims':<8} {'UpOK':<6} {'UpFail':<8} "
        f"{'CelOK':<7} {'CelFail':<9} "
        f"{'Wall(s)':>8}  {'Upload(s)':>9}  {'CelWait(s)':>11}  "
        f"{'Fast(s)':>7}  {'Slow(s)':>7}  {'Avg(s)':>7}  Started at"
    )
    L.append(
        f"  {'-'*5:<7} {'-'*6:<8} {'-'*4:<6} {'-'*6:<8} "
        f"{'-'*5:<7} {'-'*7:<9} "
        f"{'-'*7:>8}  {'-'*8:>9}  {'-'*10:>11}  "
        f"{'-'*6:>7}  {'-'*6:>7}  {'-'*6:>7}  {'-'*19}"
    )
    for bs in batch_summaries:
        L.append(
            f"  {bs.batch_number:<7} {bs.total_claims:<8} {bs.upload_ok:<6} {bs.upload_fail:<8} "
            f"{bs.celery_complete:<7} {bs.celery_failed:<9} "
            f"{bs.wall_duration_sec:>8.3f}  {bs.upload_duration_sec:>9.3f}  {bs.celery_wait_sec:>11.3f}  "
            f"{bs.fastest_upload_sec:>7.3f}  {bs.slowest_upload_sec:>7.3f}  {bs.avg_upload_sec:>7.3f}  {bs.started_at}"
        )
    L.append("")

    # Per-claim detail
    L += [dash, "  INDIVIDUAL CLAIM DETAIL", dash]
    current_batch = None
    for r in results:
        if r.batch_number != current_batch:
            current_batch = r.batch_number
            bs = batch_summaries[r.batch_number - 1]
            L.append(
                f"\n  [ Batch {r.batch_number} ]  "
                f"wall={bs.wall_duration_sec}s  "
                f"http_uploads={bs.upload_duration_sec}s  "
                f"celery_wait={bs.celery_wait_sec}s  "
                f"fastest_upload={bs.fastest_upload_sec}s  "
                f"slowest_upload={bs.slowest_upload_sec}s  "
                f"avg_upload={bs.avg_upload_sec}s"
            )

        icon = "OK" if r.upload_status == "OK" else "FAIL"
        L.append(f"    [{icon}] {r.group_key}")
        L.append(f"        Files              : {' | '.join(r.files)}")
        L.append(f"        Upload started at  : {r.upload_started_at}")
        L.append(f"        Upload finished at : {r.upload_finished_at}")
        L.append(f"        Upload duration    : {r.upload_duration_sec}s")
        L.append(f"        Celery wait        : {r.celery_wait_sec}s")
        L.append(f"        Claim ID           : {r.claim_id or 'N/A'}")
        L.append(f"        Upload status      : {r.upload_status}")
        L.append(f"        Celery status      : {r.celery_status or 'not polled'}")
        if r.failure_stage:
            L.append(f"        Failure stage      : {r.failure_stage}")
        if r.error:
            L.append(f"        Error              : {r.error}")

    L += [
        "",
        sep,
        f"  Done. {ok_count}/{total} uploaded  |  total time: {total_duration:.3f}s",
        sep,
    ]

    txt_path.write_text("\n".join(L), encoding="utf-8")

    # JSON is written live by JsonLogger — no write needed here
    print(f"\nResults written to:")
    print(f"  CSV  : {csv_path}")
    print(f"  TXT  : {txt_path}")
    print(f"  JSON : {output_dir / f'bulk_upload_results_{ts}.json'}  (live-updated throughout run)")


def _write_json_log(
    json_path:       Path,
    results:         list[UploadResult],
    batch_summaries: list[BatchSummary],
    total_duration:  float,
    mode:            str,
) -> None:
    """
    Structured JSON log.  Shape:
    {
      "run": { generated_at, mode, total_claims, upload_ok, upload_fail,
               total_wall_sec, failures_by_stage },
      "batches": [
        {
          "batch_number": 1,
          "summary": { ...BatchSummary fields... },
          "claims": [ { ...UploadResult fields... }, ... ]
        }, ...
      ]
    }
    """
    total      = len(results)
    ok_count   = sum(1 for r in results if r.upload_status == "OK")
    fail_count = total - ok_count

    # Count failures grouped by their stage
    failures_by_stage: dict[str, int] = {}
    for r in results:
        if r.failure_stage:
            failures_by_stage[r.failure_stage] = failures_by_stage.get(r.failure_stage, 0) + 1

    # Group claims by batch
    batches_map: dict[int, list[UploadResult]] = {}
    for r in results:
        batches_map.setdefault(r.batch_number, []).append(r)

    def _result_to_dict(r: UploadResult) -> dict[str, Any]:
        return {
            "group_key":           r.group_key,
            "files":               r.files,
            "upload_status":       r.upload_status,
            "failure_stage":       r.failure_stage,        # None when OK
            "celery_status":       r.celery_status,
            "claim_id":            r.claim_id,
            "error":               r.error,
            "timing": {
                "upload_started_at":   r.upload_started_at,
                "upload_finished_at":  r.upload_finished_at,
                "upload_duration_sec": r.upload_duration_sec,
                "celery_wait_sec":     r.celery_wait_sec,
            },
        }

    def _summary_to_dict(bs: BatchSummary) -> dict[str, Any]:
        return {
            "batch_number":        bs.batch_number,
            "total_claims":        bs.total_claims,
            "upload_ok":           bs.upload_ok,
            "upload_fail":         bs.upload_fail,
            "celery_complete":     bs.celery_complete,
            "celery_failed":       bs.celery_failed,
            "timing": {
                "started_at":          bs.started_at,
                "finished_at":         bs.finished_at,
                "wall_duration_sec":   bs.wall_duration_sec,
                "upload_duration_sec": bs.upload_duration_sec,
                "celery_wait_sec":     bs.celery_wait_sec,
                "fastest_upload_sec":  bs.fastest_upload_sec,
                "slowest_upload_sec":  bs.slowest_upload_sec,
                "avg_upload_sec":      bs.avg_upload_sec,
            },
        }

    batches_json = []
    for bs in batch_summaries:
        claims_in_batch = batches_map.get(bs.batch_number, [])
        # Split claims into OK / failed sub-lists for easy scanning
        ok_claims   = [_result_to_dict(r) for r in claims_in_batch if r.upload_status == "OK"
                       and (r.celery_status or "").lower() not in {"failed", "error", "cancelled", "canceled", "timeout"}]
        fail_claims = [_result_to_dict(r) for r in claims_in_batch
                       if r.upload_status == "FAIL"
                       or (r.celery_status or "").lower() in {"failed", "error", "cancelled", "canceled", "timeout"}]

        batches_json.append({
            "summary": _summary_to_dict(bs),
            "claims": {
                "all":    [_result_to_dict(r) for r in claims_in_batch],
                "ok":     ok_claims,
                "failed": fail_claims,
            },
        })

    payload = {
        "run": {
            "generated_at":      datetime.now().isoformat(timespec="seconds"),
            "mode":              mode,
            "total_claims":      total,
            "upload_ok":         ok_count,
            "upload_fail":       fail_count,
            "total_wall_sec":    round(total_duration, 3),
            "failures_by_stage": failures_by_stage,  # e.g. {"http_status": 2, "celery_timeout": 1}
        },
        "batches": batches_json,
    }

    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# Live JSON logger — flushes after every batch, not just at the end
# ---------------------------------------------------------------------------

class JsonLogger:
    """
    Writes (and continuously updates) a single JSON file throughout the run.

    Call flush_batch() immediately after each batch completes — it rewrites
    the file atomically (tmp → rename) so a crash mid-run still leaves a
    valid JSON with everything processed so far.

    Call finalize() once at the very end to stamp the completed run metadata.

    File shape:
    {
      "run": {
        "started_at":        "...",
        "finished_at":       null,          # null until finalize()
        "status":            "in_progress", # → "completed" after finalize()
        "mode":              "...",
        "total_groups":      N,
        "batches_total":     N,
        "batches_done":      N,             # increments each flush
        "upload_ok":         N,             # running totals
        "upload_fail":       N,
        "total_wall_sec":    null,          # filled by finalize()
        "failures_by_stage": { ... }
      },
      "batches": [ ... ]    # appended to on each flush_batch()
    }
    """

    def __init__(self, json_path: Path, mode: str, total_groups: int, batches_total: int) -> None:
        self._path         = json_path
        self._tmp_path     = json_path.with_suffix(".json.tmp")
        self._mode         = mode
        self._total_groups = total_groups
        self._batches_total = batches_total
        self._started_at   = datetime.now().isoformat(timespec="seconds")
        self._batches:     list[dict[str, Any]] = []
        self._all_results: list[UploadResult]   = []
        # Write the initial skeleton immediately so the file exists from t=0
        self._flush_to_disk(finished_at=None, status="in_progress", total_wall_sec=None)
        print(f"  JSON log      : {self._path}  (live — updated after each batch)")

    # ── public API ──────────────────────────────────────────────────────────

    def flush_batch(
        self,
        batch_results:  list[UploadResult],
        batch_summary:  BatchSummary,
    ) -> None:
        """Call this right after a batch (uploads + Celery wait) finishes."""
        self._all_results.extend(batch_results)
        self._batches.append(self._batch_to_dict(batch_summary, batch_results))
        self._flush_to_disk(finished_at=None, status="in_progress", total_wall_sec=None)

    def finalize(self, total_wall_sec: float) -> None:
        """Call once after all batches are done to stamp the final metadata."""
        self._flush_to_disk(
            finished_at=datetime.now().isoformat(timespec="seconds"),
            status="completed",
            total_wall_sec=round(total_wall_sec, 3),
        )

    # ── internals ───────────────────────────────────────────────────────────

    def _flush_to_disk(
        self,
        finished_at:    str | None,
        status:         str,
        total_wall_sec: float | None,
    ) -> None:
        """Atomic write: serialise → .tmp → rename over real file."""
        results      = self._all_results
        ok_count     = sum(1 for r in results if r.upload_status == "OK")
        fail_count   = len(results) - ok_count
        failures_by_stage: dict[str, int] = {}
        for r in results:
            if r.failure_stage:
                failures_by_stage[r.failure_stage] = \
                    failures_by_stage.get(r.failure_stage, 0) + 1

        payload: dict[str, Any] = {
            "run": {
                "started_at":        self._started_at,
                "finished_at":       finished_at,
                "status":            status,
                "mode":              self._mode,
                "total_groups":      self._total_groups,
                "batches_total":     self._batches_total,
                "batches_done":      len(self._batches),
                "upload_ok":         ok_count,
                "upload_fail":       fail_count,
                "total_wall_sec":    total_wall_sec,
                "failures_by_stage": failures_by_stage,
            },
            "batches": self._batches,
        }

        try:
            self._tmp_path.write_text(
                json.dumps(payload, indent=2, default=str), encoding="utf-8"
            )
            self._tmp_path.replace(self._path)   # atomic on POSIX; best-effort on Windows
        except OSError as exc:
            print(f"  [warn] JSON flush failed: {exc}")

    # ── serialisation helpers ────────────────────────────────────────────────

    @staticmethod
    def _result_to_dict(r: UploadResult) -> dict[str, Any]:
        return {
            "group_key":     r.group_key,
            "files":         r.files,
            "upload_status": r.upload_status,
            "failure_stage": r.failure_stage,
            "celery_status": r.celery_status,
            "claim_id":      r.claim_id,
            "error":         r.error,
            "timing": {
                "upload_started_at":   r.upload_started_at,
                "upload_finished_at":  r.upload_finished_at,
                "upload_duration_sec": r.upload_duration_sec,
                "celery_wait_sec":     r.celery_wait_sec,
            },
        }

    def _batch_to_dict(
        self,
        bs:      BatchSummary,
        results: list[UploadResult],
    ) -> dict[str, Any]:
        ok_claims   = [self._result_to_dict(r) for r in results
                       if r.upload_status == "OK"
                       and (r.celery_status or "").lower()
                       not in {"failed", "error", "cancelled", "canceled", "timeout"}]
        fail_claims = [self._result_to_dict(r) for r in results
                       if r.upload_status == "FAIL"
                       or (r.celery_status or "").lower()
                       in {"failed", "error", "cancelled", "canceled", "timeout"}]
        return {
            "summary": {
                "batch_number":    bs.batch_number,
                "total_claims":    bs.total_claims,
                "upload_ok":       bs.upload_ok,
                "upload_fail":     bs.upload_fail,
                "celery_complete": bs.celery_complete,
                "celery_failed":   bs.celery_failed,
                "timing": {
                    "started_at":          bs.started_at,
                    "finished_at":         bs.finished_at,
                    "wall_duration_sec":   bs.wall_duration_sec,
                    "upload_duration_sec": bs.upload_duration_sec,
                    "celery_wait_sec":     bs.celery_wait_sec,
                    "fastest_upload_sec":  bs.fastest_upload_sec,
                    "slowest_upload_sec":  bs.slowest_upload_sec,
                    "avg_upload_sec":      bs.avg_upload_sec,
                },
            },
            "claims": {
                "all":    [self._result_to_dict(r) for r in results],
                "ok":     ok_claims,
                "failed": fail_claims,
            },
        }


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

async def run(
    api_base:      str,
    input_dir:     Path,
    recursive:     bool,
    metadata_map:  dict[str, FileMetadata],
    concurrency:   int,
    batch_mode:    bool,
    output_dir:    Path,
    poll_interval: int,
    poll_timeout:  int,
) -> None:
    upload_groups = build_upload_groups(input_dir, recursive, metadata_map)
    if not upload_groups:
        print("No upload groups found. Nothing to do.")
        return

    mode = (f"strict-batch (size={concurrency}, celery-aware polling every {poll_interval}s)"
            if batch_mode else
            f"sliding-window (concurrency={concurrency})")

    batches_total = (
        (len(upload_groups) + concurrency - 1) // concurrency if batch_mode else 1
    )

    print(f"Upload mode   : {mode}")
    print(f"Total groups  : {len(upload_groups)}")
    print(f"Output dir    : {output_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    ts         = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path  = output_dir / f"bulk_upload_results_{ts}.json"

    # JsonLogger writes the file immediately and updates it after every batch
    json_logger = JsonLogger(json_path, mode, len(upload_groups), batches_total)

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=300.0) as client:
        if batch_mode:
            # Monkey-patch module globals so wait_for_batch_completion picks them up
            import bulk_upload_claims as _self
            _self.POLL_INTERVAL_SEC = poll_interval
            _self.POLL_TIMEOUT_SEC  = poll_timeout
            results, summaries = await run_strict_batches(
                client, api_base, upload_groups,
                batch_size=concurrency, json_logger=json_logger,
            )
        else:
            print("\nRunning uploads…")
            results, summaries = await run_sliding_window(
                client, api_base, upload_groups,
                concurrency=concurrency, json_logger=json_logger,
            )
    total_duration = time.perf_counter() - t0

    # Stamp the JSON as fully completed
    json_logger.finalize(total_duration)

    ok = sum(1 for r in results if r.upload_status == "OK")
    print(f"\nUploaded {ok}/{len(upload_groups)} claims in {total_duration:.3f}s total.")

    write_results(results, summaries, total_duration, output_dir, mode, ts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def collect_files(input_dir: Path, recursive: bool) -> list[Path]:
    it = input_dir.rglob("*") if recursive else input_dir.iterdir()
    return sorted(p for p in it if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bulk upload claim folders to ClaimGPT.")
    p.add_argument("--api",           default="http://localhost:8000")
    p.add_argument("--input-dir",     required=True, type=Path)
    p.add_argument("--metadata-csv",  type=Path, default=None)
    p.add_argument("--concurrency",   type=int,  default=8,
                   help="Parallel uploads (sliding-window) OR batch size (batch-mode)")
    p.add_argument("--recursive",     action="store_true")
    p.add_argument("--batch-mode",    action="store_true",
                   help="Parallel within batch, sequential between batches, waits for Celery")
    p.add_argument("--output-dir",    type=Path, default=Path("."))
    p.add_argument("--poll-interval", type=int,  default=POLL_INTERVAL_SEC,
                   help="Seconds between Celery status polls (default: 5)")
    p.add_argument("--poll-timeout",  type=int,  default=POLL_TIMEOUT_SEC,
                   help="Max seconds to wait for a batch Celery tasks (default: 600)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not args.input_dir.exists() or not args.input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {args.input_dir}")
    if not collect_files(args.input_dir, args.recursive) and \
       not any(p.is_dir() for p in args.input_dir.iterdir()):
        raise SystemExit(f"No supported files or subfolders found in {args.input_dir}")

    metadata_map = load_metadata_map(args.metadata_csv)
    asyncio.run(run(
        api_base=args.api,
        input_dir=args.input_dir,
        recursive=args.recursive,
        metadata_map=metadata_map,
        concurrency=max(1, args.concurrency),
        batch_mode=args.batch_mode,
        output_dir=args.output_dir,
        poll_interval=args.poll_interval,
        poll_timeout=args.poll_timeout,
    ))


if __name__ == "__main__":
    main()