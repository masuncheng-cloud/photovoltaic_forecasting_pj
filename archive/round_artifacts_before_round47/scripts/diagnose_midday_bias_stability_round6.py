#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round6 脚本二：正午偏差稳定性诊断
===================================
判断高误差站点的小时级偏差是否在 train/valid 均稳定存在。
仅 train/valid 同向极端偏差的站点小时，才作为修正候选。
"""
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load

TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)

MIDDAY_HOURS = [10, 11, 12, 13, 14]
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}


def nrmse(y, p, c):
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(c, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (y > 0) & (c > 0)
    if not m.any():
        return np.nan
    return float(np.sqrt(np.mean((y[m] - p[m]) ** 2)) / np.nanmean(c[m]) * 100.0)


def ratio(y, p):
    y = pd.to_numeric(y, errors="coerce")
    p = pd.to_numeric(p, errors="coerce")
    m = y.notna() & p.notna() & (y > 0)
    if not m.any():
        return np.nan
    actual = float(y[m].sum())
    pred = float(p[m].sum())
    return pred / actual if actual > 0 else np.nan


def main():
    base_path = TABLES_DIR / "distributed_predictions_midday_site_calibrated_full.pkl"
    if not base_path.exists():
        base_path = TABLES_DIR / "distributed_predictions_final_full.pkl"
    if not base_path.exists():
        raise FileNotFoundError(base_path)

    df = safe_pickle_load(base_path)
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour

    work = df[
        df["hour"].isin(MIDDAY_HOURS)
        & (~df["site_id"].isin(BAD_SITES))
        & (pd.to_numeric(df["power_mw"], errors="coerce") > 0)
    ].copy()

    rows = []
    for (sid, h, split), g in work.groupby(["site_id", "hour", "split"]):
        rows.append({
            "site_id": sid,
            "hour": int(h),
            "split": split,
            "rows": len(g),
            "pred_actual_ratio": ratio(g["power_mw"], g["power_pred"]),
            "site_nrmse_pct": nrmse(g["power_mw"], g["power_pred"], g["capacity_mw"]),
        })
    long = pd.DataFrame(rows)
    long.to_csv(METRICS_DIR / "round6_midday_bias_stability_long.csv", index=False, encoding="utf-8-sig")

    piv = long.pivot_table(
        index=["site_id", "hour"],
        columns="split",
        values=["rows", "pred_actual_ratio", "site_nrmse_pct"],
        aggfunc="first",
    )
    piv.columns = [f"{a}_{b}" for a, b in piv.columns]
    piv = piv.reset_index()

    def classify(row):
        tr = row.get("pred_actual_ratio_train", np.nan)
        va = row.get("pred_actual_ratio_valid", np.nan)
        if not np.isfinite(tr) or not np.isfinite(va):
            return "insufficient"
        if tr > 1.35 and va > 1.35:
            return "stable_over_prediction"
        if tr < 0.75 and va < 0.75:
            return "stable_under_prediction"
        return "unstable_or_mild"

    piv["bias_class"] = piv.apply(classify, axis=1)
    piv["train_valid_ratio_gap"] = (
        piv.get("pred_actual_ratio_train", np.nan) - piv.get("pred_actual_ratio_valid", np.nan)
    ).abs()

    piv["is_stable_extreme_candidate"] = (
        piv["bias_class"].isin(["stable_over_prediction", "stable_under_prediction"])
        & (piv.get("rows_train", 0).fillna(0) >= 80)
        & (piv.get("rows_valid", 0).fillna(0) >= 30)
        & (piv["train_valid_ratio_gap"].fillna(999) <= 0.50)
    )

    piv = piv.sort_values(["is_stable_extreme_candidate", "site_nrmse_pct_valid"], ascending=[False, False])
    piv.to_csv(METRICS_DIR / "round6_midday_bias_stability_summary.csv", index=False, encoding="utf-8-sig")
    piv[piv["is_stable_extreme_candidate"]].to_csv(
        METRICS_DIR / "round6_stable_extreme_bias_candidates.csv",
        index=False,
        encoding="utf-8-sig",
    )

    print("稳定极端偏差候选:")
    print(piv[piv["is_stable_extreme_candidate"]].head(50).to_string(index=False))


if __name__ == "__main__":
    main()
