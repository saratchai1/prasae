#!/usr/bin/env python3
"""Compatibility runner for PDD22 FCD V3.

pystac-client 0.9 exposes item lookup through ItemSearch in this environment.
Patch V3's retryable item resolver to search one exact Sentinel-2 item ID at a
time, retaining the retry/backoff logic while avoiding large multi-ID queries.
"""
from __future__ import annotations

import time

import process_pdd22_fcd_v3 as v3


def get_item_retry(catalog, scene_id: str):
    last_exc = None
    for attempt in range(v3.STAC_RETRIES):
        try:
            items = list(catalog.search(collections=[v3.sat.COLLECTION], ids=[scene_id]).items())
            if not items:
                raise RuntimeError(f"STAC item not found: {scene_id}")
            exact = next((item for item in items if item.id == scene_id), None)
            if exact is None:
                raise RuntimeError(f"STAC returned no exact match for {scene_id}")
            return exact
        except Exception as exc:
            last_exc = exc
            if attempt == v3.STAC_RETRIES - 1:
                break
            delay = min(20, 2 ** attempt)
            print(
                f"STAC retry {attempt + 1}/{v3.STAC_RETRIES} for {scene_id}: "
                f"{exc}; sleeping {delay}s",
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError(
        f"Failed to fetch STAC item {scene_id} after {v3.STAC_RETRIES} attempts: {last_exc}"
    )


v3.get_item_retry = get_item_retry

if __name__ == "__main__":
    v3.main()
