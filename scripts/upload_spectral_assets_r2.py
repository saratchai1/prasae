#!/usr/bin/env python3
"""Validate and upload Spectral Studio visualization assets to Cloudflare R2 DEV.

The uploader validates the exact 12-date/no-fallback contract, checks payload size before
remote writes, uploads only spectral manifests/band PNGs, and can suppress the portfolio
index during sharded runs so the final index is published once after all shards succeed.

Uploads intentionally use low concurrency and exponential backoff. Cloudflare's REST
endpoint can return HTTP 429 when several matrix shards each start multiple Wrangler
processes at once. Retrying transient failures prevents a nearly-complete shard from
failing because of a short rate-limit window.
"""

from __future__ import annotations

import json
import mimetypes
import os
import random
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_MONTHS = [
    "2023-09", "2023-12", "2024-03", "2024-06",
    "2024-09", "2024-12", "2025-03", "2025-06",
    "2025-09", "2025-12", "2026-03", "2026-08",
]
EXPECTED_BANDS = ("B02", "B03", "B04", "B08", "B11", "B12")
OBSERVED = {"observed_single_scene", "observed_monthly_composite"}

ROOT = Path(__file__).resolve().parents[1]
PLOTS_ROOT = Path(os.environ.get("PRASAE_SPECTRAL_PLOTS_ROOT", str(ROOT / "data" / "plots")))
BUCKET = os.environ.get("PRASAE_R2_BUCKET", "drone-pointcloud-v2-dev").strip()
PREFIX = os.environ.get(
    "PRASAE_R2_PREFIX",
    "mangrove-drone-dashboard-v2-dev/assets/prasae/spectral/v1",
).strip("/")
PUBLIC_BASE = os.environ.get(
    "PRASAE_R2_PUBLIC_BASE",
    "https://mangrove-drone-dashboard-dev.saratchai.workers.dev/assets/prasae/spectral/v1",
).rstrip("/")
MAX_BYTES = int(os.environ.get("PRASAE_MAX_SPECTRAL_BYTES", "8000000000"))
UPLOAD_WORKERS = max(1, int(os.environ.get("PRASAE_R2_UPLOAD_WORKERS", "1")))
MAX_UPLOAD_ATTEMPTS = max(1, int(os.environ.get("PRASAE_R2_MAX_UPLOAD_ATTEMPTS", "8")))
RETRY_BASE_SECONDS = max(0.5, float(os.environ.get("PRASAE_R2_RETRY_BASE_SECONDS", "2")))
DRY_RUN = os.environ.get("PRASAE_R2_DRY_RUN", "1").strip().lower() in {"1", "true", "yes", "y"}
UPLOAD_INDEX = os.environ.get("PRASAE_R2_UPLOAD_INDEX", "1").strip().lower() in {"1", "true", "yes", "y"}
WRANGLER = shlex.split(os.environ.get("WRANGLER", "wrangler"))


def validate_manifest(path: Path) -> tuple[dict[str, Any], list[Path], int]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    plot_id = int(manifest["plot_id"])
    plot_dir = path.parent

    if manifest.get("asset_role") != "browser_visualization_only":
        raise ValueError(f"{path}: unexpected asset_role")
    rules = manifest.get("rules") or {}
    required_rules = {
        "exact_declared_month_only": True,
        "nearest_month_fallback": False,
        "interpolation": False,
        "synthetic_imagery": False,
    }
    for key, expected in required_rules.items():
        if rules.get(key) is not expected:
            raise ValueError(f"{path}: {key} must be {expected}")

    dates = manifest.get("dates") or []
    months = [item.get("month") for item in dates]
    if months != EXPECTED_MONTHS:
        raise ValueError(f"{path}: dates must be exactly {EXPECTED_MONTHS}; got {months}")

    files = [path]
    observed_count = 0
    seen_names = set()
    for item in dates:
        status = item.get("status")
        declared = item.get("files") or {}
        if status not in OBSERVED:
            if declared:
                raise ValueError(f"{path}: non-observed {item['month']} declares spectral files")
            continue

        observed_count += 1
        if set(declared) != set(EXPECTED_BANDS):
            raise ValueError(f"{path}: {item['month']} does not contain all six bands")
        for band in EXPECTED_BANDS:
            filename = str(declared[band])
            if "/" in filename or "\\" in filename or filename in seen_names:
                raise ValueError(f"{path}: unsafe/duplicate filename {filename}")
            seen_names.add(filename)
            asset = plot_dir / filename
            if not asset.is_file():
                raise FileNotFoundError(asset)
            if asset.suffix.lower() != ".png":
                raise ValueError(f"{asset}: spectral band asset must be PNG")
            files.append(asset)

    if observed_count == 0:
        raise ValueError(f"{path}: no observed spectral dates")

    payload_bytes = sum(file.stat().st_size for file in files)
    manifest["r2"] = {
        "bucket": BUCKET,
        "prefix": f"{PREFIX}/plots/{plot_id}",
        "public_base": f"{PUBLIC_BASE}/plots/{plot_id}",
    }
    return manifest, files, payload_bytes


def collect_payload() -> tuple[list[tuple[Path, str]], dict[str, Any], int]:
    manifest_paths = sorted(PLOTS_ROOT.glob("*/spectral_manifest.json"), key=lambda p: int(p.parent.name))
    if not manifest_paths:
        raise RuntimeError(f"No spectral_manifest.json files found under {PLOTS_ROOT}")

    uploads: list[tuple[Path, str]] = []
    plots = []
    total = 0
    for path in manifest_paths:
        manifest, files, plot_bytes = validate_manifest(path)
        plot_id = int(manifest["plot_id"])
        plot_dir = path.parent

        deployment_manifest = plot_dir / "spectral_manifest.r2.json"
        deployment_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        file_by_name = {file.name: file for file in files if file.name != "spectral_manifest.json"}
        uploads.append((deployment_manifest, f"{PREFIX}/plots/{plot_id}/spectral_manifest.json"))
        for filename, asset in sorted(file_by_name.items()):
            uploads.append((asset, f"{PREFIX}/plots/{plot_id}/{filename}"))

        observed_months = [d["month"] for d in manifest["dates"] if d["status"] in OBSERVED]
        plots.append({
            "plot_id": plot_id,
            "plot_code": manifest.get("plot_code"),
            "plot_name": manifest.get("plot_name"),
            "observed_months": observed_months,
            "manifest_url": f"{PUBLIC_BASE}/plots/{plot_id}/spectral_manifest.json",
            "payload_bytes": plot_bytes,
        })
        total += plot_bytes

    index = {
        "schema_version": "1.0",
        "asset_role": "browser_visualization_only",
        "environment": "dev",
        "storage": {
            "provider": "cloudflare-r2",
            "bucket": BUCKET,
            "prefix": PREFIX,
            "public_base": PUBLIC_BASE,
        },
        "rules": {
            "exact_declared_month_only": True,
            "nearest_month_fallback": False,
            "interpolation": False,
            "synthetic_imagery": False,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plot_count": len(plots),
        "payload_bytes": total,
        "plots": plots,
    }
    index_path = ROOT / ".spectral-r2-index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    if UPLOAD_INDEX:
        uploads.append((index_path, f"{PREFIX}/index.json"))
        total += index_path.stat().st_size
    return uploads, index, total


def content_type(path: Path) -> str:
    if path.suffix.lower() == ".json":
        return "application/json; charset=utf-8"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def is_retryable_upload_error(output: str) -> bool:
    lowered = output.lower()
    retry_markers = (
        "429:",
        "too many requests",
        "500:",
        "502:",
        "503:",
        "504:",
        "econnreset",
        "etimedout",
        "timed out",
        "socket hang up",
        "network error",
    )
    return any(marker in lowered for marker in retry_markers)


def upload_one(item: tuple[Path, str]) -> tuple[str, int]:
    path, key = item
    cache_control = (
        "public, max-age=60, must-revalidate"
        if path.suffix.lower() == ".json"
        else "public, max-age=31536000, immutable"
    )
    cmd = [
        *WRANGLER,
        "r2", "object", "put", f"{BUCKET}/{key}",
        "--file", str(path),
        "--content-type", content_type(path),
        "--cache-control", cache_control,
        "--remote",
        "--force",
    ]

    last_output = ""
    for attempt in range(1, MAX_UPLOAD_ATTEMPTS + 1):
        result = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        last_output = result.stdout or ""
        if result.returncode == 0:
            return key, path.stat().st_size

        # Auth/permission problems should fail immediately; retrying cannot fix them.
        if "401:" in last_output or "403:" in last_output:
            break
        if not is_retryable_upload_error(last_output) or attempt >= MAX_UPLOAD_ATTEMPTS:
            break

        delay = min(60.0, RETRY_BASE_SECONDS * (2 ** (attempt - 1))) + random.uniform(0.0, 1.0)
        print(
            f"Transient R2 upload error for {key}; retry {attempt}/{MAX_UPLOAD_ATTEMPTS} "
            f"after {delay:.1f}s",
            flush=True,
        )
        time.sleep(delay)

    raise RuntimeError(f"Upload failed for {key}:\n{last_output[-4000:]}")


def main() -> int:
    uploads, index, total = collect_payload()
    print(f"Validated {index['plot_count']} plot manifests")
    print(f"Objects to upload: {len(uploads)}")
    print(f"Payload size: {total:,} bytes ({total / 1_000_000_000:.3f} GB)")
    print(f"Hard cap: {MAX_BYTES:,} bytes ({MAX_BYTES / 1_000_000_000:.3f} GB)")
    print(f"Upload portfolio index in this run: {UPLOAD_INDEX}")
    print(f"R2 upload workers: {UPLOAD_WORKERS}; max attempts/object: {MAX_UPLOAD_ATTEMPTS}")
    print(f"Target: r2://{BUCKET}/{PREFIX}")

    if total > MAX_BYTES:
        raise RuntimeError(
            f"ABORT: spectral payload {total:,} bytes exceeds guardrail {MAX_BYTES:,} bytes"
        )

    if DRY_RUN:
        print("DRY RUN: validation/size gate passed; no R2 objects were written")
        return 0

    if BUCKET != "drone-pointcloud-v2-dev":
        raise RuntimeError(f"Refusing non-DEV R2 bucket: {BUCKET}")
    if not PREFIX.startswith("mangrove-drone-dashboard-v2-dev/assets/prasae/spectral/"):
        raise RuntimeError(f"Refusing unexpected DEV prefix: {PREFIX}")

    uploaded_bytes = 0
    uploaded_count = 0
    with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as executor:
        futures = [executor.submit(upload_one, item) for item in uploads]
        for future in as_completed(futures):
            key, size = future.result()
            uploaded_count += 1
            uploaded_bytes += size
            if uploaded_count % 100 == 0 or uploaded_count == len(uploads):
                print(f"Uploaded {uploaded_count}/{len(uploads)} objects ({uploaded_bytes:,} bytes)")

    print(f"Upload complete for {index['plot_count']} plots")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise
