#!/usr/bin/env python3
"""
build_training_v2_backtest_dataset.py
================================
构建回测式训练数据集，包含多个时间窗口。

窗口设计：
    window_A: 2023-09~2023-12  (秋冬早期)
    window_B: 2024-09~2024-12  (秋冬中期)
    window_C: 2025-05~2025-08  (夏季当前)
    holdout_test: 2025-09~2025-12 (最终测试)

输出：
    output/pv_pipeline/round73/training_v2_backtest_dataset.parquet
    output/pv_pipeline/round73/training_v2_backtest_windows.csv
    output/pv_pipeline/round73/training_v2_data_quality.csv
"""

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round73"


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def window_metrics(win_df, pred_col):
    if len(win_df) == 0:
        return {}
    d = win_df[win_df["hour"].between(6, 19)].copy()
    if len(d) == 0:
        return {}
    cap_sum = float(d.drop_duplicates("site_id")["capacity_mw"].sum())
    agg = d.groupby("time", as_index=False).agg(
        a=("power_mw", "sum"), p=(pred_col, "sum"))
    nrmse = rmse(agg["a"].values, agg["p"].values) / cap_sum * 100 if cap_sum > 0 else np.nan
    a_sum = float(d["power_mw"].sum())
    p_sum = float(d[pred_col].sum())
    bias = (p_sum - a_sum) / a_sum * 100 if abs(a_sum) > 1e-9 else np.nan
    pos_rate = float((d["power_mw"] > 0).mean())
    inactive = float((d["power_mw"] <= 0).mean())
    site_vals = []
    for _, sdf in d.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        site_vals.append(rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100)
    return {
        "sample_count": len(d),
        "n_sites": int(d["site_id"].nunique()),
        "positive_rate": round(pos_rate, 4),
        "inactive_rate": round(inactive, 4),
        "city_nrmse_baseline": round(nrmse, 4),
        "abs_bias_baseline": round(abs(bias), 4),
        "city_bias_baseline": round(bias, 4),
        "site_mean_nrmse_baseline": round(float(np.mean(site_vals)), 4) if site_vals else np.nan,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)

    input_pkl = PROJECT_ROOT / "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl"
    print(f"[INFO] 读取: {input_pkl}")
    df = pd.read_pickle(input_pkl)
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    df["month"] = df["time"].dt.month
    print(f"  总行数: {len(df):,}")

    df = df[df["split"] != "future"].copy()
    df = df[df["hour"].between(6, 19)].copy()
    df = df[df["capacity_mw"] > 0].copy()
    print(f"  过滤后: {len(df):,}")

    bl_col = "power_pred_final"
    # 对于 train 部分没有 bl_col，使用 power_pred_round61_city_safe 作为代理
    df["_base_pred"] = df[bl_col].fillna(df.get("power_pred_round61_city_safe", df["power_pred"]))

    # 窗口定义
    windows = {
        "window_A": ("2023-09-01", "2023-12-31"),
        "window_B": ("2024-09-01", "2024-12-31"),
        "window_C": ("2025-05-01", "2025-08-31"),
        "holdout_test": ("2025-09-01", "2025-12-31"),
    }

    # 给每个样本打窗口标签
    df["window"] = "unused"
    for wname, (start, end) in windows.items():
        mask = df["time"].between(start, end)
        df.loc[mask, "window"] = wname

    # 构建回测数据集（只包含可评估的样本）
    backtest_df = df[df["window"].isin(["window_A", "window_B", "window_C", "holdout_test"])].copy()
    print(f"\n[INFO] 回测数据集: {len(backtest_df):,} 行")
    print(df["window"].value_counts().to_string())

    # 质量报告
    quality_rows = []
    for wname in ["window_A", "window_B", "window_C", "holdout_test"]:
        win_df = backtest_df[backtest_df["window"] == wname]
        m = window_metrics(win_df, "_base_pred")
        row = {"window": wname, **m}
        quality_rows.append(row)
        print(f"\n{wname}: {len(win_df)} 行")
        for k, v in m.items():
            print(f"  {k}: {v}")

    quality_df = pd.DataFrame(quality_rows)
    quality_df.to_csv(OUT / "training_v2_data_quality.csv", index=False, encoding="utf-8-sig")

    windows_df = pd.DataFrame([{"window": k, "start": v[0], "end": v[1]}
                               for k, v in windows.items()])
    windows_df.to_csv(OUT / "training_v2_backtest_windows.csv", index=False, encoding="utf-8-sig")

    # 保存回测数据集
    backtest_df.to_parquet(OUT / "training_v2_backtest_dataset.parquet", index=False)
    print(f"\n[OK] {OUT / 'training_v2_backtest_dataset.parquet'}")
    print(f"[OK] {OUT / 'training_v2_backtest_windows.csv'}")
    print(f"[OK] {OUT / 'training_v2_data_quality.csv'}")
    print("\n[OK] build_training_v2 完成!")


if __name__ == "__main__":
    main()
