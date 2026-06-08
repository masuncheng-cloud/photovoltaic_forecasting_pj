#!/usr/bin/env python3
"""
recompute_hourly_nrmse_consistent.py
====================================
Canonical wrapper → scripts/round46_recompute_hourly_nrmse_consistent.py

用法：
    python scripts/recompute_hourly_nrmse_consistent.py [--output-root output/pv_pipeline]
"""
from pathlib import Path
import runpy

SCRIPT_DIR = Path(__file__).resolve().parent
runpy.run_path(str(SCRIPT_DIR / "round46_recompute_hourly_nrmse_consistent.py"), run_name="__main__")
