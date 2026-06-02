#!/usr/bin/env python3
"""
build_round70_training_table.py
================================
构建 Round70 训练表，统一口径为 6-19 点，排除 future 数据，
构造发电状态标签，输出分布统计。

用法：
    python scripts/build_round70_training_table.py --config configs/round70_state_expert_model.yaml

输出：
    output/pv_pipeline/round70/round70_training_table.parquet
    output/pv_pipeline/round70/round70_training_distribution_by_split.csv
    output/pv_pipeline/round70/round70_training_distribution_by_hour.csv
    output/pv_pipeline/round70/round70_training_distribution_by_site.csv
    output/pv_pipeline/round70/round70_feature_inventory.csv
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml
import numpy as np


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_config(cfg_path: str) -> dict:
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def compute_site_stats(df: pd.DataFrame) -> pd.DataFrame:
    """计算每个站点的统计特征：零值率、正样本率、中位数 PR、发电小时数等。"""
    rows = []
    for site_id, g in df.groupby("site_id"):
        active_thresh = max(0.02, 0.02 * g["capacity_mw"].iloc[0])
        train_valid = g[g["split"].isin(["train", "valid"])]
        if len(train_valid) == 0:
            continue
        rows.append({
            "site_id": site_id,
            "capacity_mw": g["capacity_mw"].iloc[0],
            "n_total": len(g),
            "n_train_valid": len(train_valid),
            "zero_count": (train_valid["power_mw"] <= 0).sum(),
            "weak_count": ((train_valid["power_mw"] > 0) & (train_valid["power_mw"] < active_thresh)).sum(),
            "active_count": (train_valid["power_mw"] >= active_thresh).sum(),
            "zero_ratio": (train_valid["power_mw"] <= 0).mean(),
            "weak_ratio": ((train_valid["power_mw"] > 0) & (train_valid["power_mw"] < active_thresh)).mean(),
            "active_ratio": (train_valid["power_mw"] >= active_thresh).mean(),
            "positive_count_6_19": (train_valid["power_mw"] > 0).sum(),
            "power_mean": train_valid["power_mw"].mean(),
            "power_median": train_valid["power_mw"].median(),
            "power_p90": train_valid["power_mw"].quantile(0.9),
        })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="构建 Round70 训练表")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    if args.config is None:
        args.config = str(project_root() / "configs" / "round70_state_expert_model.yaml")

    cfg = load_config(args.config)
    root = project_root()

    # ── 输入 ──────────────────────────────────────────────────────────────────
    input_path = root / cfg["paths"]["input_pred"]
    out_dir = root / cfg["paths"]["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] 读取预测文件: {input_path}")
    df = pd.read_pickle(input_path)
    print(f"  总行数: {len(df):,}  总列数: {len(df.columns)}")
    print(f"  列名: {df.columns.tolist()}")

    # ── Step 1: 排除 future ───────────────────────────────────────────────────
    n_before = len(df)
    if cfg.get("exclude_future", True):
        df = df[df["split"] != "future"].copy()
    print(f"\n[Step 1] 排除 future: {n_before:,} → {len(df):,} 行")

    # ── Step 2: 只保留 6-19 点 ────────────────────────────────────────────────
    n_before = len(df)
    eval_hours = cfg.get("eval_hours", list(range(6, 20)))
    if "hour" not in df.columns:
        df["hour"] = pd.to_datetime(df["time"]).dt.hour
    df = df[df["hour"].isin(eval_hours)].copy()
    print(f"[Step 2] 6-19 点过滤: {n_before:,} → {len(df):,} 行")

    # ── Step 3: 只保留容量有效站点 ─────────────────────────────────────────────
    n_before = len(df)
    df = df[df["capacity_mw"] > 0].copy()
    print(f"[Step 3] 排除零容量: {n_before:,} → {len(df):,} 行")

    # ── Step 4: 构造发电状态标签 ──────────────────────────────────────────────
    active_thresh = df["capacity_mw"].clip(lower=1e-6).apply(
        lambda c: max(cfg["active_threshold"]["min_mw"], cfg["active_threshold"]["capacity_ratio"] * c)
    )
    df["active_threshold_mw"] = active_thresh

    conditions = [
        df["power_mw"] <= 0,
        df["power_mw"] < df["active_threshold_mw"],
    ]
    choices = ["inactive", "weak"]
    df["state_label"] = np.select(conditions, choices, default="active")
    print(f"\n[Step 4] 发电状态分布:")
    print(df["state_label"].value_counts())

    # ── Step 5: 构造目标变量 ──────────────────────────────────────────────────
    df["y_norm"] = (df["power_mw"] / df["capacity_mw"].clip(lower=1e-6)).clip(lower=0)
    df["baseline_norm"] = (df[cfg["baseline_col"]] / df["capacity_mw"].clip(lower=1e-6)).clip(lower=0)
    df["residual_norm"] = df["y_norm"] - df["baseline_norm"]

    # ── Step 6: 时间块 ───────────────────────────────────────────────────────
    blocks = cfg.get("time_blocks", {})
    block_map = {}
    for block_name, hours in blocks.items():
        for h in hours:
            block_map[h] = block_name
    df["time_block"] = df["hour"].map(block_map).fillna("unknown")

    # ── Step 7: 站点统计特征（from train+valid） ───────────────────────────────
    print("\n[Step 7] 计算站点统计特征...")
    site_stats = compute_site_stats(df)
    df = df.merge(site_stats[["site_id", "zero_ratio", "positive_count_6_19",
                               "power_median", "power_p90"]].rename(columns={
        "zero_ratio": "site_zero_ratio_6_19",
        "positive_count_6_19": "site_positive_count_train_valid",
        "power_median": "site_power_median",
        "power_p90": "site_power_p90",
    }), on="site_id", how="left")

    # ── Step 8: 输出 parquet ───────────────────────────────────────────────────
    table_path = out_dir / "round70_training_table.parquet"
    df.to_parquet(table_path, index=False)
    print(f"\n[OK] 训练表写出: {table_path}  ({len(df):,} 行)")

    # ── Step 9: 分布统计 by split ────────────────────────────────────────────
    split_stats = df.groupby("split").agg(
        n_rows=("site_id", "count"),
        active_count=("state_label", lambda x: (x == "active").sum()),
        weak_count=("state_label", lambda x: (x == "weak").sum()),
        inactive_count=("state_label", lambda x: (x == "inactive").sum()),
        mean_power=("power_mw", "mean"),
        median_power=("power_mw", "median"),
        mean_y_norm=("y_norm", "mean"),
        mean_baseline_norm=("baseline_norm", "mean"),
        mean_residual=("residual_norm", "mean"),
        n_sites=("site_id", "nunique"),
        capacity_sum=("capacity_mw", "first"),
    ).reset_index()
    split_stats["positive_rate"] = split_stats["active_count"] / split_stats["n_rows"]
    split_stats["weak_rate"] = split_stats["weak_count"] / split_stats["n_rows"]
    split_stats["inactive_rate"] = split_stats["inactive_count"] / split_stats["n_rows"]
    split_stats_path = out_dir / "round70_training_distribution_by_split.csv"
    split_stats.to_csv(split_stats_path, index=False, encoding="utf-8-sig")
    print(f"[OK] split 分布: {split_stats_path}")
    print(split_stats.to_string(index=False))

    # ── Step 10: 分布统计 by hour ─────────────────────────────────────────────
    hour_stats = df.groupby(["split", "hour"]).agg(
        n_rows=("site_id", "count"),
        active_count=("state_label", lambda x: (x == "active").sum()),
        weak_count=("state_label", lambda x: (x == "weak").sum()),
        inactive_count=("state_label", lambda x: (x == "inactive").sum()),
        mean_power=("power_mw", "mean"),
    ).reset_index()
    hour_stats["positive_rate"] = hour_stats["active_count"] / hour_stats["n_rows"]
    hour_stats_path = out_dir / "round70_training_distribution_by_hour.csv"
    hour_stats.to_csv(hour_stats_path, index=False, encoding="utf-8-sig")
    print(f"[OK] hour 分布: {hour_stats_path}")

    # ── Step 11: 分布统计 by site ─────────────────────────────────────────────
    site_dist = site_stats.copy()
    site_dist_path = out_dir / "round70_training_distribution_by_site.csv"
    site_dist.to_csv(site_dist_path, index=False, encoding="utf-8-sig")
    print(f"[OK] site 分布: {site_dist_path}")

    # ── Step 12: 特征清单 ─────────────────────────────────────────────────────
    feature_inventory = pd.DataFrame({
        "column": df.columns.tolist(),
        "dtype": [str(d) for d in df.dtypes.values],
        "non_null_count": df.count().values,
        "null_count": df.isnull().sum().values,
        "n_unique": df.nunique().values,
    })
    feat_path = out_dir / "round70_feature_inventory.csv"
    feature_inventory.to_csv(feat_path, index=False, encoding="utf-8-sig")
    print(f"[OK] 特征清单: {feat_path}")

    print("\n[OK] build_round70_training_table 完成!")
    print(f"  输出目录: {out_dir}")


if __name__ == "__main__":
    main()
