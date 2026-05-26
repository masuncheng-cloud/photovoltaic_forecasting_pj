#!/usr/bin/env python3
"""
Step 3: Run Full Retrain
==========================
执行完整训练流水线：
  1. train_fixed.py（完整训练）
  2. run_round10_best_guard_pipeline.py（最优保护 guard）
  3. export_interactive_dashboard_data.py（页面数据）
  4. 审计验证

日志写入：
  output/pv_pipeline/logs/round14_full_retrain.log

执行：
    python scripts/run_full_retrain_round14.py
    # 后台运行：
    nohup /home/mjj/anaconda3/bin/python3 scripts/run_full_retrain_round14.py \
        >> output/pv_pipeline/logs/round14_full_retrain.log 2>&1 &
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "logs"
PYTHON = "/home/mjj/anaconda3/bin/python3"


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "round14_full_retrain.log", "a") as f:
        f.write(line + "\n")


def run(script_path: str, description: str, timeout: int = 0):
    log(f"=== START: {description} ===")
    cmd = [PYTHON, str(PROJECT_ROOT / script_path)]
    try:
        if timeout > 0:
            result = subprocess.run(cmd, cwd=PROJECT_ROOT, timeout=timeout, check=True)
        else:
            result = subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
        log(f"=== DONE : {description} ===")
        return True
    except subprocess.TimeoutExpired:
        log(f"=== TIMEOUT: {description} (>{timeout}s) ===")
        return False
    except subprocess.CalledProcessError as e:
        log(f"=== FAILED: {description} (exit {e.returncode}) ===")
        raise


def main():
    start = time.time()
    log("=" * 70)
    log("Round14 Full Retrain Starting")
    log("=" * 70)

    # Step 3a: Full training
    ok = run("scripts/train_fixed.py", "Full Training (train_fixed.py)", timeout=0)
    if not ok:
        log("[FATAL] Training failed — stop here")
        raise SystemExit(1)

    elapsed = time.time() - start
    log(f"Training done in {elapsed/60:.1f} min")

    # Step 3b: Best guard pipeline
    run("scripts/run_round10_best_guard_pipeline.py", "Best Guard Pipeline", timeout=3600)

    # Step 3c: Dashboard export
    run(
        "scripts/export_interactive_dashboard_data.py",
        "Dashboard Data Export",
        timeout=600,
    )

    # Step 3d: Audit
    run(
        "scripts/audit_training_process_and_results.py",
        "Audit Verification",
        timeout=300,
    )

    total = time.time() - start
    log(f"=== Round14 Full Retrain Complete in {total/60:.1f} min ===")
    print(f"\n[DONE] Full retrain completed in {total/60:.1f} minutes")


if __name__ == "__main__":
    main()
