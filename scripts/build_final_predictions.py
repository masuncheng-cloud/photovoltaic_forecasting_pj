#!/usr/bin/env python3
"""
build_final_predictions.py
=========================
Canonical wrapper → scripts/build_round36_predictions.py

用法：
    python scripts/build_final_predictions.py [--output-root output/pv_pipeline]
"""
from pathlib import Path
import runpy

SCRIPT_DIR = Path(__file__).resolve().parent
runpy.run_path(str(SCRIPT_DIR / "build_round36_predictions.py"), run_name="__main__")
