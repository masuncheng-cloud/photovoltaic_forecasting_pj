#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round14 Step 3: 统一执行完整重训。

依次运行：
  1. train_fixed.py (完整训练流水线)
  2. run_round10_best_guard_pipeline.py (best guard pipeline)
  3. regenerate_chinese_metrics.py (中文指标)
  4. compute_nrmse_reports_round10.py (NRMSE 报告)
  5. export_interactive_dashboard_data.py (交互页面)

日志写入：
  output/pv_pipeline/logs/round14_full_retrain.log
"""
from __future__ import annotations

import subprocess
import sys
import logging
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output" / "pv_pipeline"
LOG_DIR = OUT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def run(script: Path, desc: str, check: bool = True) -> None:
    """执行单个脚本。"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_file = LOG_DIR / "round14_full_retrain.log"
    cmd = [sys.executable, str(script)]

    msg = f"[{timestamp}] RUN: {' '.join(cmd)}"
    print(msg)
    with open(log_file, "a") as f:
        f.write(msg + "\n")
        f.flush()

    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        text=True,
    )
    if result.stdout:
        with open(log_file, "a") as f:
            f.write(result.stdout + "\n")
    if result.stderr:
        with open(log_file, "a") as f:
            f.write("STDERR: " + result.stderr + "\n")

    if check and result.returncode != 0:
        print(f"[FAIL] {desc} 失败 (code={result.returncode})")
        raise SystemExit(1)
    print(f"[OK] {desc} 完成")
    with open(log_file, "a") as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] OK: {desc}\n")


def main():
    print("=" * 70)
    print("Round14 Step 3: 完整重新训练")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    log_file = LOG_DIR / "round14_full_retrain.log"
    with open(log_file, "w") as f:
        f.write(f"Round14 Full Retrain started at {datetime.now().isoformat()}\n")

    # Step 3a: 完整训练流水线
    run(
        PROJECT_ROOT / "scripts" / "train_fixed.py",
        "train_fixed.py (完整训练)",
    )

    # Step 3b: best guard pipeline
    run(
        PROJECT_ROOT / "scripts" / "run_round10_best_guard_pipeline.py",
        "run_round10_best_guard_pipeline.py",
    )

    # Step 3c: 中文指标
    run(
        PROJECT_ROOT / "scripts" / "regenerate_chinese_metrics.py",
        "regenerate_chinese_metrics.py",
    )

    # Step 3d: NRMSE 报告
    run(
        PROJECT_ROOT / "scripts" / "compute_nrmse_reports_round10.py",
        "compute_nrmse_reports_round10.py",
    )

    # Step 3e: 交互页面
    run(
        PROJECT_ROOT / "scripts" / "export_interactive_dashboard_data.py",
        "export_interactive_dashboard_data.py",
    )

    # Step 3f: 审计
    run(
        PROJECT_ROOT / "scripts" / "audit_training_process_and_results.py",
        "audit_training_process_and_results.py",
    )

    print()
    print("=" * 70)
    print(f"Round14 完整重训完成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)


if __name__ == "__main__":
    main()
