#!/usr/bin/env python3
"""Compatibility entrypoint for the retired separate all-plots workspace test.

The product now has one unified 210-plot workspace. Keep this historical test
path so existing CI callers do not become stale; execute the canonical unified
browser test instead.
"""
from pathlib import Path
import runpy

ROOT=Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT/'tests'/'unified-workspace-browser.py'),run_name='__main__')
