"""
build_round36_predictions.py
=============================
将 v159 训练输出（distributed_predictions_v159.pkl）整合为：

  Canonical 路径（正式输出）:
    <output-root>/predictions/distributed_predictions_final_full.pkl  ← 含 train/valid/test/future
    <output-root>/predictions/distributed_predictions_final_eval.pkl  ← 仅 test 6-19h

  兼容路径（从 canonical 同步，供历史脚本兼容）:
    <output-root>/tables/distributed_predictions_final_round36.pkl
    <output-root>/tables/distributed_predictions_final_eval_round36.pkl

用法：
  python scripts/build_round36_predictions.py
  python scripts/build_round36_predictions.py --output-root output/pv_pipeline
"""
import argparse
import os
import pickle
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

SPLIT_START = {
    "train":  "2023-01-01",
    "valid":  "2025-07-01",
    "test":   "2025-09-01",
    "future": "2026-01-01",
}


def main():
    parser = argparse.ArgumentParser(description="Build Round36 Predictions")
    parser.add_argument(
        "--output-root",
        type=str,
        default="output/pv_pipeline",
        help="输出根目录 (default: output/pv_pipeline)",
    )
    args = parser.parse_args()
    output_root = PROJECT_ROOT / args.output_root

    TABLES     = output_root / "tables"
    PREDICTIONS = output_root / "predictions"
    METRICS    = output_root / "metrics"

    # Canonical 路径（正式输出）
    OUT_FULL = PREDICTIONS / "distributed_predictions_final_full.pkl"
    OUT_EVAL = PREDICTIONS / "distributed_predictions_final_eval.pkl"
    # 兼容路径（历史别名）
    OUT_FULL_LEGACY = TABLES / "distributed_predictions_final_round36.pkl"
    OUT_EVAL_LEGACY = TABLES / "distributed_predictions_final_eval_round36.pkl"

    print("=" * 60)
    print("Build Round36 Predictions")
    print(f"Output root: {output_root}")
    print("=" * 60)

    # ── 读取 v159 预测结果 ─────────────────────────────────
    v159_path = TABLES / "distributed_predictions_v159.pkl"
    if not v159_path.exists():
        print(f"[ERROR] {v159_path} 不存在，请先运行训练！")
        sys.exit(1)

    print(f"\n读取 {v159_path}...")
    df = pd.read_pickle(v159_path)
    print(f"  行数: {len(df):,}, 列: {len(df.columns)}")

    # ── 确保 split 列存在 ──────────────────────────────────
    if "split" not in df.columns:
        print("[WARN] 无 split 列，按时间重新划分...")
        df["time"] = pd.to_datetime(df["time"])
        df["split"] = "train"
        for split_name, start in SPLIT_START.items():
            mask = df["time"] >= pd.Timestamp(start)
            df.loc[mask, "split"] = split_name
        print(f"  划分后: {df['split'].value_counts().to_dict()}")
    else:
        print(f"  split: {df['split'].value_counts().to_dict()}")

    # ── 确保 hour 列存在 ──────────────────────────────────
    if "hour" not in df.columns:
        df["hour"] = pd.to_datetime(df["time"]).dt.hour
        print("  [+] 添加 hour 列")

    # ── 确保 site_id 为字符串 ─────────────────────────────
    df["site_id"] = df["site_id"].astype(str)

    # ── 添加 power_pred_raw（初始等于 power_pred） ─────────
    if "power_pred_raw" not in df.columns:
        if "power_pred" in df.columns:
            df["power_pred_raw"] = df["power_pred"].copy()
            print("  [+] power_pred_raw = power_pred")
        else:
            df["power_pred_raw"] = df["power_pred_cal"].copy()
            print("  [+] power_pred_raw = power_pred_cal")

    # ── 添加 power_pred_final（初始等于 power_pred_raw） ───
    if "power_pred_final" not in df.columns:
        df["power_pred_final"] = df["power_pred_raw"].copy()
        print("  [+] power_pred_final = power_pred_raw（待校准后更新）")
    else:
        print("  [i] power_pred_final 已存在（可能已有校准值）")

    # ── 确保必要列存在 ───────────────────────────────────
    required = ["site_id", "time", "split", "hour", "power_mw",
                "capacity_mw", "power_pred_raw", "power_pred_final"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"[ERROR] 缺少列: {missing}")
        sys.exit(1)

    # ── 物理裁剪 power_pred_raw 和 power_pred_final ────────
    print("\n物理裁剪（限制在 [0, capacity_mw]）...")
    df["power_pred_raw"] = df["power_pred_raw"].clip(lower=0)
    df["power_pred_final"] = df["power_pred_final"].clip(lower=0)
    # 同时 clip 到 capacity
    df["power_pred_raw"] = df[["power_pred_raw", "capacity_mw"]].min(axis=1)
    df["power_pred_final"] = df[["power_pred_final", "capacity_mw"]].min(axis=1)

    # ── 填充 NaN ─────────────────────────────────────────
    for col in ["power_pred_raw", "power_pred_final"]:
        if df[col].isna().any():
            print(f"  {col}: {df[col].isna().sum()} 个 NaN，填充为 0")
            df[col] = df[col].fillna(0.0)

    # ── 排序 ─────────────────────────────────────────────
    df = df.sort_values(["site_id", "time"]).reset_index(drop=True)

    # ── 保存 full pkl ────────────────────────────────────
    PREDICTIONS.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)
    print(f"\n保存 full pkl: {OUT_FULL}")
    df.to_pickle(OUT_FULL)
    shutil.copy2(OUT_FULL, OUT_FULL_LEGACY)  # 兼容
    print(f"  行数: {len(df):,}, 列: {list(df.columns)}")

    # ── 保存 eval pkl（只含 test 6-19h）───────────────────
    df_eval = df[(df["split"] == "test") & df["hour"].between(6, 19)].copy()
    df_eval = df_eval.sort_values(["site_id", "time"]).reset_index(drop=True)
    print(f"\n保存 eval pkl: {OUT_EVAL}")
    df_eval.to_pickle(OUT_EVAL)
    shutil.copy2(OUT_EVAL, OUT_EVAL_LEGACY)  # 兼容
    print(f"  行数: {len(df_eval):,}, 站点: {df_eval['site_id'].nunique()}")

    # ── 统计 ─────────────────────────────────────────────
    print("\n各 split 行数:")
    for split_name, count in df["split"].value_counts().sort_index().items():
        print(f"  {split_name}: {count:,}")

    print("\n各 split eval 行数（test 6-19h）:")
    eval_counts = df_eval["split"].value_counts()
    for s, c in eval_counts.items():
        print(f"  {s}: {c:,}")

    print(f"""
[OK] build_round36_predictions.py 完成！
  canonical:
    full: {OUT_FULL}
    eval: {OUT_EVAL}
  兼容:
    full: {OUT_FULL_LEGACY}
    eval: {OUT_EVAL_LEGACY}
""")


if __name__ == "__main__":
    import pandas as pd
    sys.exit(main())
