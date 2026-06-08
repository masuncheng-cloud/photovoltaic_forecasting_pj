#!/usr/bin/env python3
"""
build_site_validity.py
=====================
Canonical wrapper → scripts/build_site_validity_round36.py

用法：
    python scripts/build_site_validity.py [--output-root output/pv_pipeline]
"""
from pathlib import Path
import runpy

SCRIPT_DIR = Path(__file__).resolve().parent
runpy.run_path(str(SCRIPT_DIR / "build_site_validity_round36.py"), run_name="__main__")
