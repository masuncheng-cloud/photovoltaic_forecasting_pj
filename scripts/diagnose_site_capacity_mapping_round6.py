#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round6 脚本一：站点容量与映射诊断
===================================
核查 S012/S055/S050/S032 等站点的：
1. 装机容量 vs 实际峰值功率
2. 10-14 点预测/实际比值
3. 零值占比
4. 生成诊断标记
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
WATCH_SITES = {"S012", "S055", "S050", "S032", "S019", "S053", "S072", "S002", "S059"}


def safe_num(s):
    return pd.to_numeric(s, errors="coerce")


def summarize_site(g: pd.DataFrame) -> dict:
    power = safe_num(g["power_mw"])
    cap = safe_num(g["capacity_mw"])
    pred = safe_num(g["power_pred"]) if "power_pred" in g.columns else pd.Series(np.nan, index=g.index)
    nonnull = power.notna()
    pos = power > 0
    cap_med = float(cap.median()) if cap.notna().any() else np.nan
    p95 = float(power[pos].quantile(0.95)) if pos.any() else np.nan
    p99 = float(power[pos].quantile(0.99)) if pos.any() else np.nan
    pmax = float(power[pos].max()) if pos.any() else np.nan

    actual_sum = float(power[pos].sum()) if pos.any() else np.nan
    pred_sum = float(pred[pos].sum()) if pos.any() and pred.notna().any() else np.nan

    return {
        "site_id": g["site_id"].iloc[0],
        "rows": int(len(g)),
        "nonnull_power_rows": int(nonnull.sum()),
        "positive_power_rows": int(pos.sum()),
        "zero_rows": int(((power == 0) & nonnull).sum()),
        "zero_ratio_pct": round(float(((power == 0) & nonnull).sum() / max(nonnull.sum(), 1) * 100.0), 2),
        "capacity_mw": round(cap_med, 4) if np.isfinite(cap_med) else np.nan,
        "p95_power_mw": round(p95, 4) if np.isfinite(p95) else np.nan,
        "p99_power_mw": round(p99, 4) if np.isfinite(p99) else np.nan,
        "max_power_mw": round(pmax, 4) if np.isfinite(pmax) else np.nan,
        "p99_over_capacity": round(p99 / cap_med, 4) if np.isfinite(p99) and np.isfinite(cap_med) and cap_med > 0 else np.nan,
        "max_over_capacity": round(pmax / cap_med, 4) if np.isfinite(pmax) and np.isfinite(cap_med) and cap_med > 0 else np.nan,
        "eval_pred_actual_ratio": round(pred_sum / actual_sum, 4) if np.isfinite(pred_sum) and np.isfinite(actual_sum) and actual_sum > 0 else np.nan,
    }


def main():
    full_path = TABLES_DIR / "distributed_predictions_final_full.pkl"
    eval_path = TABLES_DIR / "distributed_predictions_final_eval.pkl"
    if not full_path.exists():
        raise FileNotFoundError(full_path)
    if not eval_path.exists():
        raise FileNotFoundError(eval_path)

    full = safe_pickle_load(full_path)
    eval_df = safe_pickle_load(eval_path)

    full["time"] = pd.to_datetime(full["time"], errors="coerce")
    if "hour" not in full.columns:
        full["hour"] = full["time"].dt.hour

    eval_df["time"] = pd.to_datetime(eval_df["time"], errors="coerce")
    if "hour" not in eval_df.columns:
        eval_df["hour"] = eval_df["time"].dt.hour

    rows = []
    for sid, g in full.groupby("site_id"):
        rows.append(summarize_site(g))
    site_summary = pd.DataFrame(rows)

    midday = eval_df[eval_df["hour"].isin(MIDDAY_HOURS)].copy()
    err_rows = []
    for sid, g in midday.groupby("site_id"):
        y = safe_num(g["power_mw"]).to_numpy(dtype=float)
        p = safe_num(g["power_pred"]).to_numpy(dtype=float)
        c = safe_num(g["capacity_mw"]).to_numpy(dtype=float)
        m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (y > 0) & (c > 0)
        if not m.any():
            continue
        rmse = float(np.sqrt(np.mean((y[m] - p[m]) ** 2)))
        cap = float(np.nanmean(c[m]))
        actual = float(np.sum(y[m]))
        pred = float(np.sum(p[m]))
        err_rows.append({
            "site_id": sid,
            "midday_eval_rows": int(m.sum()),
            "midday_site_nrmse_pct": round(rmse / cap * 100.0, 4) if cap > 0 else np.nan,
            "midday_pred_actual_ratio": round(pred / actual, 4) if actual > 0 else np.nan,
            "midday_bias_pct": round((pred - actual) / actual * 100.0, 4) if actual > 0 else np.nan,
        })
    err = pd.DataFrame(err_rows)

    out = site_summary.merge(err, on="site_id", how="left")
    out["is_watch_site"] = out["site_id"].isin(WATCH_SITES)

    def flag(row):
        flags = []
        if pd.notna(row.get("p99_over_capacity")) and row["p99_over_capacity"] > 1.10:
            flags.append("p99_power_exceeds_capacity")
        if pd.notna(row.get("max_over_capacity")) and row["max_over_capacity"] > 1.20:
            flags.append("max_power_exceeds_capacity")
        if pd.notna(row.get("midday_pred_actual_ratio")) and row["midday_pred_actual_ratio"] > 1.60:
            flags.append("midday_prediction_over_high")
        if pd.notna(row.get("midday_pred_actual_ratio")) and row["midday_pred_actual_ratio"] < 0.65:
            flags.append("midday_prediction_too_low")
        if pd.notna(row.get("zero_ratio_pct")) and row["zero_ratio_pct"] > 70:
            flags.append("zero_ratio_high")
        return ";".join(flags)

    out["diagnostic_flags"] = out.apply(flag, axis=1)
    out = out.sort_values(["is_watch_site", "midday_site_nrmse_pct"], ascending=[False, False])

    out.to_csv(METRICS_DIR / "round6_site_capacity_mapping_diagnosis.csv", index=False, encoding="utf-8-sig")
    out[out["is_watch_site"]].to_csv(METRICS_DIR / "round6_watch_site_diagnosis.csv", index=False, encoding="utf-8-sig")
    out[out["diagnostic_flags"] != ""].to_csv(METRICS_DIR / "round6_flagged_site_diagnosis.csv", index=False, encoding="utf-8-sig")

    print("重点站点诊断:")
    print(out[out["is_watch_site"]].to_string(index=False))
    print()
    print("异常标记站点:")
    print(out[out["diagnostic_flags"] != ""].head(50).to_string(index=False))


if __name__ == "__main__":
    main()
