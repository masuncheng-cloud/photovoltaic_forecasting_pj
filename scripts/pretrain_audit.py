#!/usr/bin/env python3
"""
pretrain_audit.py
================
Canonical wrapper → scripts/pretrain_audit_round36.py

用法：
    python scripts/pretrain_audit.py [--output-root output/pv_pipeline]
"""
from pathlib import Path
import runpy
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
runpy.run_path(str(SCRIPT_DIR / "pretrain_audit_round36.py"), run_name="__main__")
