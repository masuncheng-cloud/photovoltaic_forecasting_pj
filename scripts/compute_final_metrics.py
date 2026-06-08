#!/usr/bin/env python3
"""
compute_final_metrics.py
=======================
Canonical wrapper → scripts/compute_round36_metrics.py

用法：
    python scripts/compute_final_metrics.py [--output-root output/pv_pipeline]
"""
from pathlib import Path
import runpy

SCRIPT_DIR = Path(__file__).resolve().parent
runpy.run_path(str(SCRIPT_DIR / "compute_round36_metrics.py"), run_name="__main__")
