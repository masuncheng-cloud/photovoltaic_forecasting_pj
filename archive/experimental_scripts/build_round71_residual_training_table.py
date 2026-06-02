#!/usr/bin/env python3
"""
build_round71_residual_training_table.py
======================================
构建 Round71 保守残差训练表。
目标不是全功率，而是 residual_norm_clipped。

输出：
    output/pv_pipeline/round71/round71_residual_training_table.parquet
    output/pv_pipeline/round71/round71_feature_inventory.csv
    output/pv_pipeline/round71/round71_training_summary.csv
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round71"


def main():
    parser = argparse.ArgumentParser(description="构建 Round71 残差训练表")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    if args.config is None:
        args.config = str(PROJECT_ROOT / "configs" / "round71_conservative_residual.yaml")
    cfg = yaml.safe_load(open(args.config))

    OUT.mkdir(parents=True, exist_ok=True)

    input_path = PROJECT_ROOT / cfg["paths"]["input_pred"]
    print(f"[INFO] 读取: {input_path}")
    df = pd.read_pickle(input_path)
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    df["month"] = df["time"].dt.month
    df["dayofyear"] = df["time"].dt.dayofyear
    print(f"  总行数: {len(df):,}")

    # 过滤
    df = df[df["split"] != "future"].copy()
    df = df[df["hour"].between(6, 19)].copy()
    df = df[df["capacity_mw"] > 0].copy()
    print(f"  过滤后: {len(df):,}")

    bl_col = cfg["baseline_col"]
    cap_col = cfg["capacity_col"]
    target_col = cfg["target_col"]

    # 残差目标：对于 train 用 power_pred（因为 power_pred_final 在 train 上全为空），
    # 对于 valid/test 用 power_pred_final
    df["y_true_norm"] = (df[target_col] / df[cap_col].clip(lower=1e-6)).clip(lower=0)

    # 优先用 power_pred_final，如果为空则回退到 power_pred
    df["_bl_pred"] = df[bl_col].fillna(df["power_pred"])

    df["y_base_norm"] = (df["_bl_pred"] / df[cap_col].clip(lower=1e-6)).clip(lower=0)
    df["residual_norm"] = df["y_true_norm"] - df["y_base_norm"]

    # 保守裁剪
    clip_cfg = cfg.get("residual_clip", {})
    max_clip = clip_cfg.get("max_abs_norm", 0.08)
    noon_max = clip_cfg.get("noon_max_abs_norm", 0.06)
    focus_hours = cfg.get("focus_hours", [10, 11, 12, 13, 14])

    df["residual_norm_clipped"] = df["residual_norm"].clip(-max_clip, max_clip)
    noon_mask = df["hour"].isin(focus_hours)
    df.loc[noon_mask, "residual_norm_clipped"] = df.loc[noon_mask, "residual_norm"].clip(-noon_max, noon_max)

    # 近期权重
    recency_cfg = cfg.get("recency_weight", {})
    if recency_cfg.get("enabled", True):
        train_df_temp = df[df["split"] == "train"].copy()
        if len(train_df_temp) > 0:
            valid_start = pd.Timestamp("2025-07-01")
            days = (train_df_temp["time"] - valid_start).dt.days.clip(lower=0)
            half_life = recency_cfg.get("half_life_days", 180)
            min_w = recency_cfg.get("min_weight", 0.4)
            max_w = recency_cfg.get("max_weight", 2.0)
            recency_w = np.exp(-days / half_life).clip(min_w, max_w).values
            df.loc[df["split"] == "train", "recency_weight"] = recency_w
            print(f"  近期权重: min={min_w:.2f}  max={max_w:.2f}  half_life={half_life}天")

    # 特征
    FEATURES = [
        "hour", "month", "dayofyear",
        "latitude", "longitude", "capacity_mw",
        "y_base_norm",
        "g_blend_pred", "clear_sky_ghi", "clear_sky_index",
        "scene_v151",
        "site_zero_ratio_6_19",
        "pr_median",
        "quality_score",
        "zero_ratio", "bias",
    ]
    FEATURES = [f for f in FEATURES if f in df.columns]

    # 站点统计
    print("\n[INFO] 计算站点统计特征...")
    site_stats = df[df["split"].isin(["train", "valid"])].groupby("site_id").agg(
        site_bias_valid=("residual_norm", "mean"),
        site_nrmse_valid=("residual_norm", lambda x: float(np.sqrt(np.nanmean(x**2)))),
        site_zero_ratio_6_19=("power_mw", lambda x: float((x <= 0).mean())),
        site_pr_median=("pr_median", "first"),
        site_quality_score=("quality_score", "first"),
    ).reset_index()

    df = df.merge(site_stats[["site_id", "site_bias_valid", "site_nrmse_valid"]], on="site_id", how="left")
    for f in ["site_bias_valid", "site_nrmse_valid"]:
        if f in df.columns:
            FEATURES.append(f)

    # 输出
    table_path = OUT / "round71_residual_training_table.parquet"
    df.to_parquet(table_path, index=False)
    print(f"[OK] 训练表: {table_path}  ({len(df):,} 行)")

    # feature inventory
    feat_inv = pd.DataFrame({
        "column": df.columns.tolist(),
        "dtype": [str(d) for d in df.dtypes.values],
        "non_null": df.count().values,
        "null_count": df.isnull().sum().values,
    })
    feat_inv.to_csv(OUT / "round71_feature_inventory.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] 特征清单: {OUT / 'round71_feature_inventory.csv'}")

    # 训练摘要
    summary_rows = []
    for split_name, g in df.groupby("split"):
        summary_rows.append({
            "split": split_name,
            "n_rows": len(g),
            "residual_mean": round(float(g["residual_norm"].mean()), 6),
            "residual_std": round(float(g["residual_norm"].std()), 6),
            "residual_clipped_mean": round(float(g["residual_norm_clipped"].mean()), 6),
            "residual_clipped_std": round(float(g["residual_norm_clipped"].std()), 6),
            "positive_rate": round(float((g[target_col] > 0).mean()), 4),
            "n_sites": int(g["site_id"].nunique()),
        })
    pd.DataFrame(summary_rows).to_csv(OUT / "round71_training_summary.csv",
                                      index=False, encoding="utf-8-sig")
    print(f"[OK] 训练摘要: {OUT / 'round71_training_summary.csv'}")
    print(pd.DataFrame(summary_rows).to_string(index=False))

    print("\n[OK] build_round71_residual_training_table 完成!")


if __name__ == "__main__":
    main()
