"""
round45_apply_site_hour_shrinkage_calibration.py
===============================================
Round45 Step 2: 应用站点-小时收缩校准。

策略：
- 对每个 (site_id, hour) 组合拟合 alpha
- alpha_final = w * alpha_site_hour + (1 - w) * alpha_hour
- w = n / (n + K)，K=300
- alpha 限制在 [0.75, 1.25]
- 只用 train+valid 中 active 样本拟合（避免零值主导）
- 先写候选列到 PKL，由 guard 决定是否启用

注意：此脚本不修改 power_pred_final，由 round45_guard_and_commit.py 决定是否采纳候选。
"""

from pathlib import Path
import json
import math
import shutil
import numpy as np
import pandas as pd


ROOT = Path("output/pv_pipeline")
TABLE_DIR = ROOT / "tables"
METRIC_DIR = ROOT / "metrics"
METRIC_DIR.mkdir(parents=True, exist_ok=True)

K = 300
ALPHA_MIN = 0.75
ALPHA_MAX = 1.25


def find_final_pkl():
    candidates = sorted(TABLE_DIR.glob("distributed_predictions_final_round*.pkl"))
    if candidates:
        return candidates[-1]
    for name in ["distributed_predictions_final_full.pkl", "distributed_predictions_final.pkl"]:
        p = TABLE_DIR / name
        if p.exists():
            return p
    raise FileNotFoundError("找不到 distributed_predictions_final*.pkl")


def normalize(df):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    return df


def fit_alpha(y, p):
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    valid = np.isfinite(y) & np.isfinite(p) & (p > 1e-9)
    y = y[valid]
    p = p[valid]
    if len(y) < 20:
        return 1.0, len(y)
    alpha = float(np.sum(y * p) / max(np.sum(p * p), 1e-9))
    return float(np.clip(alpha, ALPHA_MIN, ALPHA_MAX)), len(y)


def build_calibration_table(df):
    train = df[
        df["split"].isin(["train", "valid"])
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df["power_pred_final"].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()

    train["actual_mw"] = pd.to_numeric(train["power_mw"], errors="coerce")
    train["pred_mw"] = pd.to_numeric(train["power_pred_final"], errors="coerce")
    train["capacity_mw"] = pd.to_numeric(train["capacity_mw"], errors="coerce")
    train["active_threshold_mw"] = np.maximum(0.02 * train["capacity_mw"], 0.05)

    # 只用有效发电样本拟合，避免大量0值主导系数
    train = train[train["actual_mw"] > train["active_threshold_mw"]].copy()

    # 全局小时系数
    hour_rows = []
    for hour, g in train.groupby("hour"):
        alpha_h, n = fit_alpha(g["actual_mw"], g["pred_mw"])
        hour_rows.append({
            "hour": int(hour),
            "alpha_hour": alpha_h,
            "hour_fit_samples": int(n),
        })
    hour_alpha = pd.DataFrame(hour_rows)

    # 站点-小时系数
    rows = []
    for (sid, hour), g in train.groupby(["site_id", "hour"]):
        alpha_sh, n = fit_alpha(g["actual_mw"], g["pred_mw"])
        rows.append({
            "site_id": sid,
            "hour": int(hour),
            "alpha_site_hour": alpha_sh,
            "fit_samples": int(n),
        })
    site_hour = pd.DataFrame(rows)

    table = site_hour.merge(hour_alpha, on="hour", how="left")
    table["alpha_hour"] = table["alpha_hour"].fillna(1.0)
    table["weight"] = table["fit_samples"] / (table["fit_samples"] + K)
    table["alpha_final"] = table["weight"] * table["alpha_site_hour"] + (1 - table["weight"]) * table["alpha_hour"]
    table["alpha_final"] = table["alpha_final"].clip(ALPHA_MIN, ALPHA_MAX)

    return table, hour_alpha


def apply_calibration(df, table):
    out = df.merge(table[["site_id", "hour", "alpha_final"]], on=["site_id", "hour"], how="left")
    out["alpha_final"] = out["alpha_final"].fillna(1.0)
    out["power_pred_final_before_round45"] = out["power_pred_final"]
    out["power_pred_final_round45_candidate"] = out["power_pred_final"] * out["alpha_final"]
    out["power_pred_final_round45_candidate"] = out["power_pred_final_round45_candidate"].clip(lower=0)
    out["power_pred_final_round45_candidate"] = np.minimum(
        out["power_pred_final_round45_candidate"],
        out["capacity_mw"],
    )
    out = out.drop(columns=["alpha_final"])
    return out


def main():
    pkl = find_final_pkl()
    backup = pkl.with_suffix(".before_round45.pkl")
    shutil.copy2(pkl, backup)
    print("[OK] backup:", backup)

    df = pd.read_pickle(pkl)
    df = normalize(df)

    table, hour_alpha = build_calibration_table(df)
    table.to_csv(METRIC_DIR / "round45_site_hour_alpha.csv", index=False, encoding="utf-8-sig")
    hour_alpha.to_csv(METRIC_DIR / "round45_hour_alpha.csv", index=False, encoding="utf-8-sig")

    out = apply_calibration(df, table)

    # 先写候选列，不直接覆盖
    tmp = pkl.with_suffix(".round45_candidate.tmp.pkl")
    out.to_pickle(tmp)
    check = pd.read_pickle(tmp)
    assert "power_pred_final_round45_candidate" in check.columns
    assert len(check) == len(out)
    tmp.replace(pkl)

    print(f"[OK] wrote candidate to: {pkl}")
    print(f"[OK] alpha rows: {len(table)}, hours: {len(hour_alpha)}")
    print(f"\nalpha_hour summary:")
    print(hour_alpha.to_string(index=False))
    print(f"\nalpha_final distribution:")
    print(f"  min={table['alpha_final'].min():.4f}, max={table['alpha_final'].max():.4f}, "
          f"mean={table['alpha_final'].mean():.4f}")
    print(f"  median={table['alpha_final'].median():.4f}")


if __name__ == "__main__":
    main()
