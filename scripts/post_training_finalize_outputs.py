"""
post_training_finalize_outputs.py
================================
训练后统一收口脚本。

每次训练（或逻辑修正）完成后，唯一地执行以下收口步骤：
  1. 重新计算逐小时 consistent NRMSE 指标
  2. 重新导出可视化 dashboard 数据
  3. 检测 dashboard 是否真的刷新了
  4. 验证 dashboard stamp 文件有效
  5. 执行 dashboard 回归检查
  6. 输出一份本次收口的执行记录

此脚本不参与模型训练本身，只负责训练后处理。
只有训练成功（final pkl 已写出）才应执行本脚本。

用法（独立运行）：
  python scripts/post_training_finalize_outputs.py

用法（作为训练入口的一部分）：
  from scripts.post_training_finalize_outputs import run_finalize
  run_finalize()

  或 subprocess：
  subprocess.run([sys.executable, "scripts/post_training_finalize_outputs.py"], check=True)

依赖：
  - python (sys.executable)
  - output/pv_pipeline/tables/distributed_predictions_final_*.pkl  (必须存在)
  - scripts/round46_recompute_hourly_nrmse_consistent.py
  - scripts/export_interactive_dashboard_data.py
  - scripts/update_dashboard_after_training.py
  - scripts/check_dashboard_auto_update_stamp.py
  - scripts/round44_dashboard_regression_check.py
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pv_pipeline"
METRICS = OUT / "metrics"
DOCS = OUT / "docs"
DASHBOARD = OUT / "interactive_dashboard"

PYTHON = sys.executable


def run_step(name, cmd, cwd=None, required=True, timeout_sec=None):
    """Execute a single step. Returns (returncode, stdout+stderr)."""
    if cwd is None:
        cwd = str(ROOT)
    print(f"\n{'─' * 60}")
    print(f"[STEP] {name}")
    print(f"       {' '.join(cmd)}")
    print(f"{'─' * 60}")

    kwargs = {
        "cwd": cwd,
        "capture_output": True,
        "text": True,
        "timeout": timeout_sec,
    }
    result = subprocess.run(cmd, **kwargs)
    output = (result.stdout or "") + "\n" + (result.stderr or "")

    if result.returncode != 0:
        print(f"[FAIL] {name} — exit {result.returncode}")
        print(output[-3000:])
        if required:
            raise RuntimeError(f"[STEP FAIL] {name} (exit {result.returncode})")
    else:
        print(f"[OK]   {name} — done")
        # Print last 500 chars of output on success
        if output.strip():
            print(output[-500:])

    return result.returncode, output


def find_recompute_script():
    """Find the hourly NRMSE recompute script (prefer generic name)."""
    candidates = [
        ROOT / "scripts" / "compute_hourly_nrmse_consistent.py",
        ROOT / "scripts" / "round46_recompute_hourly_nrmse_consistent.py",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"找不到逐小时 NRMSE 重算脚本，尝试了: {[str(p) for p in candidates]}"
    )


def find_dashboard_check_script():
    """Find the dashboard regression check script."""
    candidates = [
        ROOT / "scripts" / "round44_dashboard_regression_check.py",
        ROOT / "scripts" / "dashboard_regression_check.py",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def check_final_pkl_exists():
    """Verify the final prediction pkl exists before proceeding."""
    tables_dir = ROOT / "output" / "pv_pipeline" / "tables"
    pkl_files = list(tables_dir.glob("distributed_predictions_final_*.pkl"))
    if not pkl_files:
        raise FileNotFoundError(
            f"未找到 final 预测文件（tables/distributed_predictions_final_*.pkl），"
            "训练可能未完成。请先运行完整训练流程。"
        )
    latest = max(pkl_files, key=lambda p: p.stat().st_mtime)
    print(f"  检测到 final pkl: {latest.name}")
    return latest


def run_finalize() -> dict:
    """
    执行训练后收口全流程。
    返回执行记录字典。
    """
    print("=" * 60)
    print("训练后统一收口流程 (post_training_finalize_outputs)")
    print("=" * 60)
    print(f"项目根目录 : {ROOT}")
    print(f"Python     : {PYTHON}")
    print(f"时间       : {datetime.now().isoformat(timespec='seconds')}")

    # Pre-flight check
    print("\n[PRE-FLIGHT] 检查 final 预测文件...")
    check_final_pkl_exists()

    DOCS.mkdir(parents=True, exist_ok=True)

    stamp = {
        "finalized_at": datetime.now().isoformat(timespec="seconds"),
        "python": PYTHON,
        "steps": [],
    }

    steps = [
        (
            "recompute_hourly_nrmse_consistent",
            [PYTHON, str(find_recompute_script())],
            "scripts/compute_hourly_nrmse_consistent.py or round46 variant",
        ),
        (
            "export_interactive_dashboard_data",
            [PYTHON, str(ROOT / "scripts" / "export_interactive_dashboard_data.py")],
            "scripts/export_interactive_dashboard_data.py",
        ),
        (
            "update_dashboard_after_training",
            [PYTHON, str(ROOT / "scripts" / "update_dashboard_after_training.py")],
            "scripts/update_dashboard_after_training.py",
        ),
        (
            "check_dashboard_auto_update_stamp",
            [PYTHON, str(ROOT / "scripts" / "check_dashboard_auto_update_stamp.py")],
            "scripts/check_dashboard_auto_update_stamp.py",
        ),
        (
            "check_dashboard_data_freshness",
            [PYTHON, str(ROOT / "scripts" / "check_dashboard_data_freshness.py")],
            "scripts/check_dashboard_data_freshness.py",
        ),
    ]

    for name, cmd, desc in steps:
        try:
            code, _ = run_step(name, cmd, timeout_sec=300)
            stamp["steps"].append({"name": name, "returncode": code, "status": "ok" if code == 0 else "fail"})
        except Exception as e:
            stamp["steps"].append({"name": name, "error": str(e), "status": "error"})
            raise

    # Dashboard regression check (optional — don't fail if not found)
    check_script = find_dashboard_check_script()
    if check_script:
        try:
            code, _ = run_step(
                "dashboard_regression_check",
                [PYTHON, str(check_script)],
                timeout_sec=60,
                required=False,
            )
            stamp["steps"].append({
                "name": "dashboard_regression_check",
                "script": str(check_script.relative_to(ROOT)),
                "returncode": code,
                "status": "ok" if code == 0 else "fail",
            })
        except Exception as e:
            stamp["steps"].append({
                "name": "dashboard_regression_check",
                "script": str(check_script.relative_to(ROOT)),
                "error": str(e),
                "status": "error",
            })
    else:
        print("\n[WARN] 未找到 dashboard 回归检查脚本，跳过此步")
        stamp["steps"].append({
            "name": "dashboard_regression_check",
            "status": "skipped",
            "reason": "script not found",
        })

    # Write stamp
    stamp_path = DOCS / "post_training_finalize_stamp.json"
    stamp_path.write_text(json.dumps(stamp, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] 收口记录已写入: {stamp_path}")

    # Summary
    ok_count = sum(1 for s in stamp["steps"] if s.get("status") == "ok")
    total_count = len(stamp["steps"])
    print()
    print("=" * 60)
    print(f"[{'PASS' if ok_count == total_count else 'PARTIAL'}] "
          f"post training finalize completed — {ok_count}/{total_count} steps OK")
    print("=" * 60)
    print(f"\n收口记录: {stamp_path}")
    print(f"Dashboard: {DASHBOARD}")
    print(f"\n如需检查，可运行: python scripts/check_post_training_auto_finalize.py")

    return stamp


def main():
    try:
        run_finalize()
    except Exception as e:
        print(f"\n[FATAL] 收口失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
