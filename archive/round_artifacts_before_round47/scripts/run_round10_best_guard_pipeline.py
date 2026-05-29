#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round10/11：最优保护 pipeline — 每次 pipeline 运行后执行，保证 final 永不劣化"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(script: str):
    cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / script)]
    print("=" * 70)
    print("RUN:", " ".join(cmd))
    print("=" * 70)
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)


def main():
    run("save_current_best_round10.py")
    run("check_final_is_best_round10.py")
    run("regenerate_final_metrics_round7.py")
    run("assert_final_metrics_consistency_round7.py")
    run("compute_nrmse_reports_round10.py")
    run("summarize_candidate_decisions_round11.py")
    print("[OK] Round10/11 best guard pipeline completed.")


if __name__ == "__main__":
    main()
