"""
run_round33_full_retrain.py
===========================
按 Round33 方案执行完整重训流程。

执行顺序：
  1. 训练 v1.5.9（PR重算 + LightGBM基线 + v152残差校正）
  2. 评估 pipeline（生成分布式指标）
  3. 生成 final_full 和 final_eval pkl（合并 train/valid/test/future）

训练原则（Round33 方案规定）：
  - y = power_mw / capacity_mw（容量归一化）
  - 预测后还原：power_pred = y_pred * capacity_mw
  - 物理裁剪：[0, capacity_mw]
  - 训练只用 train，模型选择只用 valid，test 只用于最终评估
"""
from __future__ import annotations

import os
import sys
import subprocess
import time
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

os.environ["OMP_NUM_THREADS"] = "4"

TRAIN_SCRIPT    = PROJECT_ROOT / "stages" / "03_power" / "train_distributed_model_v159.py"
EVAL_SCRIPT      = PROJECT_ROOT / "stages" / "04_evaluation" / "evaluate_pipeline.py"

TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"


def run_step(name: str, script_path: Path, extra_args: list[str] | None = None) -> float:
    cmd = [sys.executable, str(script_path)]
    if extra_args:
        cmd.extend(extra_args)
    print(f"\n{'='*60}")
    print(f"[Step] {name}")
    print(f"[CMD] {' '.join(cmd)}")
    print(f"{'='*60}")
    t0 = time.time()
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    elapsed = time.time() - t0
    if result.returncode != 0:
        print(f"[ERROR] {name} failed with exit code {result.returncode}")
        sys.exit(1)
    print(f"[OK] {name} 完成，耗时 {elapsed:.0f}s")
    return elapsed


def main():
    t_start = time.time()
    print("=" * 60)
    print(f"Round33 完整重训开始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ── Step 6a: 训练 v1.5.9 ─────────────────────────────────────────────────
    run_step("训练 v1.5.9（PR重算+LightGBM+v152残差校正）", TRAIN_SCRIPT)

    # ── Step 6b: 评估 pipeline ────────────────────────────────────────────────
    run_step("评估 pipeline（分布式指标）", EVAL_SCRIPT)

    # ── Step 6c: 生成 final eval pkl（只用 test）────────────────────────────
    print("\n生成 final_eval pkl...")
    elapsed_c = _build_final_eval()
    print(f"[OK] final_eval pkl 完成，耗时 {elapsed_c:.0f}s")

    total = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"Round33 重训完成！总耗时 {total:.0f}s ({total/60:.1f}min)")
    print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")


def _build_final_eval() -> float:
    """生成 distributed_predictions_final_eval.pkl（只含 test 6-19点）。"""
    import pickle
    import pandas as pd

    t0 = time.time()
    # 读取 v159 全量预测
    v159_path = TABLES_DIR / "distributed_predictions_v159.pkl"
    if not v159_path.exists():
        print(f"[WARN] {v159_path} 不存在，尝试读取 distributed_predictions.pkl")
        v159_path = TABLES_DIR / "distributed_predictions.pkl"

    print(f"读取预测文件: {v159_path}")
    with open(v159_path, "rb") as f:
        df = pickle.load(f)

    df["time"] = pd.to_datetime(df["time"])
    print(f"原始行数: {len(df):,}")

    # 只保留 test 且 6-19 点
    df_eval = df[
        (df["split"] == "test") &
        (df["hour"] >= 6) & (df["hour"] < 20)
    ].copy()

    # 物理裁剪
    df_eval["power_pred"] = df_eval["power_pred"].clip(lower=0)
    cap = df_eval["capacity_mw"]
    df_eval["power_pred"] = df_eval["power_pred"].where(df_eval["power_pred"] <= cap, cap)

    print(f"test 6-19 行数: {len(df_eval):,}")
    print(f"站点数: {df_eval['site_id'].nunique()}")

    out_path = TABLES_DIR / "distributed_predictions_final_eval_round33.pkl"
    with open(out_path, "wb") as f:
        pickle.dump(df_eval, f, protocol=4)
    print(f"已保存: {out_path}")
    return time.time() - t0


if __name__ == "__main__":
    main()
