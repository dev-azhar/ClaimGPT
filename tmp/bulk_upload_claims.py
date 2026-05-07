"""Bulk upload files to the ClaimGPT ingress API.

Each immediate subfolder inside the input directory is uploaded as one claim.

Usage:
    python tmp/bulk_upload_claims.py --api http://localhost:8000 \
        --input-dir C:\\path\\to\\documents \
        --concurrency 8

Optional metadata can be provided per file via a CSV mapping with columns:
    file_name,policy_id,patient_id
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".json", ".xml", ".html"}
MIME_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".json": "application/json",
    ".xml": "application/xml",
    ".html": "text/html",
}


@dataclass
class FileMetadata:
    policy_id: str | None = None
    patient_id: str | None = None


@dataclass
class UploadGroup:
    group_key: str
    files: list[Path]
    metadata: FileMetadata


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


def build_upload_groups(input_dir: Path, recursive: bool, metadata_map: dict[str, FileMetadata]) -> list[UploadGroup]:
    if recursive:
        candidate_dirs = sorted({path.parent for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS})
    else:
        candidate_dirs = [path for path in sorted(input_dir.iterdir()) if path.is_dir()]

    groups: list[UploadGroup] = []
    root_files: list[Path] = []

    if recursive:
        for folder in candidate_dirs:
            files = sorted(path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS)
            if files:
                groups.append(UploadGroup(group_key=folder.name, files=files, metadata=_merge_group_metadata(files, metadata_map)))

        root_files = sorted(path for path in input_dir.iterdir() if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS)
    else:
        for folder in candidate_dirs:
            files = sorted(path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS)
            if files:
                groups.append(UploadGroup(group_key=folder.name, files=files, metadata=_merge_group_metadata(files, metadata_map)))

        root_files = sorted(path for path in input_dir.iterdir() if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS)

    for file_path in root_files:
        groups.append(UploadGroup(group_key=file_path.name, files=[file_path], metadata=metadata_map.get(file_path.name, FileMetadata())))

    return sorted(groups, key=lambda group: group.group_key.lower())


def _merge_group_metadata(files: list[Path], metadata_map: dict[str, FileMetadata]) -> FileMetadata:
    merged = FileMetadata()
    for file_path in files:
        metadata = metadata_map.get(file_path.name)
        if metadata is None:
            continue
        if merged.policy_id is None and metadata.policy_id is not None:
            merged.policy_id = metadata.policy_id
        if merged.patient_id is None and metadata.patient_id is not None:
            merged.patient_id = metadata.patient_id
    return merged


async def upload_one(client: httpx.AsyncClient, api_base: str, files: list[Path], metadata: FileMetadata) -> dict[str, Any]:
    payload = {}
    if metadata.policy_id is not None:
        payload["policy_id"] = metadata.policy_id
    if metadata.patient_id is not None:
        payload["patient_id"] = metadata.patient_id

    multipart_files: list[tuple[str, tuple[str, Any, str]]] = []
    handles: list[Any] = []
    try:
        for file_path in files:
            handle = file_path.open("rb")
            handles.append(handle)
            content_type = MIME_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
            multipart_files.append(("files", (file_path.name, handle, content_type)))

        response = await client.post(f"{api_base.rstrip('/')}/ingress/claims", data=payload, files=multipart_files)
    finally:
        for handle in handles:
            handle.close()

    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        raise RuntimeError(
            f"Invalid JSON response from {api_base.rstrip('/')}/ingress/claims: "
            f"status={response.status_code} body={response.text!r}"
        )


async def run(api_base: str, input_dir: Path, recursive: bool, metadata_map: dict[str, FileMetadata], concurrency: int) -> None:
    sem = asyncio.Semaphore(concurrency)
    upload_groups = build_upload_groups(input_dir, recursive, metadata_map)
    total_groups = len(upload_groups)
    completed_groups = 0

    async with httpx.AsyncClient(timeout=300.0) as client:
        async def guarded_upload(upload_group: UploadGroup) -> tuple[UploadGroup, dict[str, Any] | None, str | None]:
            async with sem:
                try:
                    print(f"START {upload_group.group_key}: {len(upload_group.files)} file(s)")
                    result = await upload_one(client, api_base, upload_group.files, upload_group.metadata)
                    return upload_group, result, None
                except Exception as exc:
                    return upload_group, None, str(exc)

        tasks = [guarded_upload(upload_group) for upload_group in upload_groups]
        for finished in asyncio.as_completed(tasks):
            upload_group, result, error = await finished
            completed_groups += 1
            if error:
                print(f"FAIL  {upload_group.group_key}: {error}")
            elif result is None:
                print(f"FAIL  {upload_group.group_key}: empty response from server")
            else:
                claim_id = result.get("id") or result.get("claim_id")
                status = result.get("status")
                group_label = ", ".join(file_path.name for file_path in upload_group.files)
                if claim_id is None:
                    print(f"WARN  {upload_group.group_key} [{group_label}] -> missing claim id in response: {result}")
                else:
                    print(f"OK    {upload_group.group_key} [{group_label}] -> claim={claim_id} status={status}")

            print(f"PROGRESS {completed_groups}/{total_groups} claim groups processed")

    print(f"\nUploaded {completed_groups}/{total_groups} claim groups successfully.")


def collect_files(input_dir: Path, recursive: bool) -> list[Path]:
    if recursive:
        files = [p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS]
    else:
        files = [p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS]
    return sorted(files)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bulk upload claim folders to ClaimGPT.")
    parser.add_argument("--api", default="http://localhost:8000", help="Ingress API base URL")
    parser.add_argument("--input-dir", required=True, type=Path, help="Directory containing documents to upload")
    parser.add_argument("--metadata-csv", type=Path, default=None, help="Optional CSV mapping file_name to policy_id/patient_id")
    parser.add_argument("--concurrency", type=int, default=8, help="Number of parallel uploads")
    parser.add_argument("--recursive", action="store_true", help="Search input directory recursively")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.input_dir.exists() or not args.input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {args.input_dir}")

    if not any(path.is_dir() for path in args.input_dir.iterdir()) and not collect_files(args.input_dir, False):
        raise SystemExit(f"No supported files or subfolders found in {args.input_dir}")

    metadata_map = load_metadata_map(args.metadata_csv)
    asyncio.run(run(args.api, args.input_dir, args.recursive, metadata_map, max(1, args.concurrency)))


if __name__ == "__main__":
    main()
