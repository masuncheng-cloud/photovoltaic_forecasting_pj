#!/usr/bin/env python3
"""
apply_final_calibration.py
=========================
Canonical wrapper → scripts/apply_round36_calibration.py

用法：
    python scripts/apply_final_calibration.py [--output-root output/pv_pipeline]
"""
from pathlib import Path
import runpy

SCRIPT_DIR = Path(__file__).resolve().parent
runpy.run_path(str(SCRIPT_DIR / "apply_round36_calibration.py"), run_name="__main__")
