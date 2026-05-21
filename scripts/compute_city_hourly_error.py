#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复包1：修正全市误差统计口径
===================================
明确区分以下三种不同的城市级误差指标：

1. city_total_relative_error_pct : 先聚合（sum）再计算相对误差，最严格的城市总量指标
2. WAPE_city                   : sum(|e|) / sum(actual)，加权绝对百分比误差
3. mean_site_mape_pct          : 各站点逐条 MAPE 的均值（原有口径，不混淆命名）

同时输出：
  - 逐日逐小时详细 CSV
  - 按小时汇总的摘要 CSV
  - 按 scene 汇总的摘要 CSV
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path("/home/ac/data16t/msc/photovoltaic_forecasting_pj")
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_DETAIL = OUT_DIR / "city_hourly_total_error_fixed.csv"
OUT_SUMMARY = OUT_DIR / "city_hourly_total_error_summary_fixed.csv"
OUT_SCENE = OUT_DIR / "city_hourly_scene_error_fixed.csv"

# 7 low-quality stations excluded
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def mape(y_true, y_pred):
    """MAPE(%): mean(|e| / |y|) * 100, only where y_true > 0 and finite."""
    mask = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / y_true[mask]) * 100)


def wape(y_true, y_pred):
    """WAPE(%): sum(|e|) / sum(|y|) * 100."""
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.sum(np.abs(y_true[mask] - y_pred[mask])) / np.sum(np.abs(y_true[mask])) * 100)


def city_rel_err(y_true_sum, y_pred_sum):
    """City total relative error(%): |sum(pred) - sum(actual)| / sum(actual) * 100."""
    if not np.isfinite(y_true_sum) or y_true_sum <= 0:
        return np.nan
    return float(np.abs(y_pred_sum - y_true_sum) / y_true_sum * 100)


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
print("Reading predictions …")
pred_df = pd.read_pickle(PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "distributed_predictions.pkl")
pred_df["time"] = pd.to_datetime(pred_df["time"])
pred_df["year"] = pred_df["time"].dt.year
pred_df["month"] = pred_df["time"].dt.month
pred_df["date"] = pred_df["time"].dt.date
pred_df["hour"] = pred_df["time"].dt.hour

# Filter: test set 2025-Jul+, hour 6-19, power > 0, exclude bad sites
mask = (
    (pred_df["year"] >= 2025) &
    (pred_df["month"] >= 7) &
    (pred_df["hour"] >= 6) &
    (pred_df["hour"] <= 19) &
    (pred_df["power_mw"] > 0) &
    (~pred_df["site_id"].isin(BAD_SITES))
)
df = pred_df[mask].copy()
print(f"Filtered: {len(df):,} rows, {df['site_id'].nunique()} sites, "
      f"date range {df['date'].min()} – {df['date'].max()}")

# ---------------------------------------------------------------------------
# Scene labels (same as v152)
# ---------------------------------------------------------------------------
def _scene_v151(g):
    elev = pd.to_numeric(g.get("solar_elevation_deg", pd.Series(-90, index=g.index)), errors="coerce").fillna(-90)
    g_val = pd.to_numeric(g.get("g_blend_pred", pd.Series(0, index=g.index)), errors="coerce").fillna(0)
    ramp = pd.to_numeric(g.get("g_blend_pred_diff1", pd.Series(0, index=g.index)), errors="coerce").abs().fillna(0)
    k = pd.to_numeric(g.get("g_blend_pred_kt", pd.Series(0, index=g.index)), errors="coerce").fillna(0)
    scene = np.where(elev <= 0, "night",
              np.where((g_val < 120) | (k < 0.18), "low",
              np.where(ramp > 140, "ramp",
              np.where((g_val > 520) & (elev > 18), "clear_peak",
              "mid"))))
    return pd.Series(scene, index=g.index, dtype="string")

df["scene_label"] = _scene_v151(df)

# ---------------------------------------------------------------------------
# Group: dawn / morning / midday / afternoon / dusk
# ---------------------------------------------------------------------------
def _time_period(h):
    if h in (6, 7):
        return "dawn"
    elif h in (8, 9):
        return "morning"
    elif h in (10, 11, 12, 13, 14):
        return "midday"
    elif h in (15, 16):
        return "afternoon"
    else:
        return "dusk"

df["time_period"] = df["hour"].apply(_time_period)

# ---------------------------------------------------------------------------
# Per-date × per-hour (city-level) metrics
# ---------------------------------------------------------------------------
print("Computing city-level per-date-per-hour metrics …")

rows_detail = []
for (date, hour), g in df.groupby(["date", "hour"]):
    yt = g["power_mw"].values.astype(float)
    yp = g["power_pred"].values.astype(float)

    yt_sum = float(np.nansum(yt))
    yp_sum = float(np.nansum(yp))

    row = {
        "date": date,
        "hour": int(hour),
        "n_sites": g["site_id"].nunique(),
        # Original (mean of site MAPEs) - keep for backward compat
        "mean_site_mape_pct": mape(yt, yp),
        # True city total metrics
        "city_total_actual_mw": yt_sum,
        "city_total_pred_mw": yp_sum,
        "city_total_rel_err_pct": city_rel_err(yt_sum, yp_sum),
        "WAPE_city_pct": wape(yt, yp),
        "city_total_abs_err_mw": float(np.nansum(np.abs(yt - yp))),
    }
    rows_detail.append(row)

df_detail = pd.DataFrame(rows_detail)
df_detail = df_detail.sort_values(["date", "hour"]).reset_index(drop=True)

# ---------------------------------------------------------------------------
# Per-hour summary (aggregated across dates)
# ---------------------------------------------------------------------------
print("Computing per-hour summary …")

rows_summary = []
for h in range(6, 20):
    sub = df_detail[df_detail["hour"] == h]
    if len(sub) == 0:
        continue

    row = {
        "hour": int(h),
        "n_dates": len(sub),
        "n_sites_mean": sub["n_sites"].mean(),
        # Mean across dates of each day's city total relative error
        "city_total_rel_err_pct_mean": sub["city_total_rel_err_pct"].mean(),
        "city_total_rel_err_pct_median": sub["city_total_rel_err_pct"].median(),
        "city_total_rel_err_pct_p25": sub["city_total_rel_err_pct"].quantile(0.25),
        "city_total_rel_err_pct_p75": sub["city_total_rel_err_pct"].quantile(0.75),
        "city_total_rel_err_pct_p90": sub["city_total_rel_err_pct"].quantile(0.90),
        # WAPE
        "WAPE_city_pct_mean": sub["WAPE_city_pct"].mean(),
        "WAPE_city_pct_median": sub["WAPE_city_pct"].median(),
        # Mean of site MAPEs (original metric)
        "mean_site_mape_pct": sub["mean_site_mape_pct"].mean(),
        "mean_site_mape_pct_median": sub["mean_site_mape_pct"].median(),
        # Aggregated city totals
        "city_total_actual_mw_mean": sub["city_total_actual_mw"].mean(),
        "city_total_pred_mw_mean": sub["city_total_pred_mw"].mean(),
        "city_total_abs_err_mw_mean": sub["city_total_abs_err_mw"].mean(),
        # Bias
        "city_total_bias_mw_mean": (sub["city_total_pred_mw"] - sub["city_total_actual_mw"]).mean(),
        "city_total_bias_pct_mean": ((sub["city_total_pred_mw"] - sub["city_total_actual_mw"]) / sub["city_total_actual_mw"] * 100).mean(),
    }
    rows_summary.append(row)

df_summary = pd.DataFrame(rows_summary)

# ---------------------------------------------------------------------------
# Per-scene summary
# ---------------------------------------------------------------------------
print("Computing per-scene summary …")

rows_scene = []
for scene, g in df.groupby("scene_label"):
    if scene == "night":
        continue
    for h in range(6, 20):
        sub = g[g["hour"] == h]
        if len(sub) == 0:
            continue
        yt = sub["power_mw"].values.astype(float)
        yp = sub["power_pred"].values.astype(float)
        yt_sum = float(np.nansum(yt))
        yp_sum = float(np.nansum(yp))
        rows_scene.append({
            "scene": scene,
            "hour": int(h),
            "n_samples": len(sub),
            "n_sites": sub["site_id"].nunique(),
            "mean_site_mape_pct": mape(yt, yp),
            "city_total_actual_mw": yt_sum,
            "city_total_pred_mw": yp_sum,
            "city_total_rel_err_pct": city_rel_err(yt_sum, yp_sum),
            "WAPE_city_pct": wape(yt, yp),
        })

df_scene = pd.DataFrame(rows_scene)

# ---------------------------------------------------------------------------
# Per-time-period summary
# ---------------------------------------------------------------------------
print("Computing per-time-period summary …")

rows_period = []
for period in ["dawn", "morning", "midday", "afternoon", "dusk"]:
    for h_range, h_start, h_end in [("dawn", 6, 7), ("morning", 8, 9),
                                      ("midday", 10, 14), ("afternoon", 15, 16), ("dusk", 17, 19)]:
        if period != h_range:
            continue
        sub = df_detail[df_detail["hour"].isin(range(h_start, h_end + 1))]
        if len(sub) == 0:
            continue
        rows_period.append({
            "time_period": period,
            "hour_range": f"{h_start}-{h_end}",
            "n_dates": len(sub),
            "city_total_rel_err_pct_mean": sub["city_total_rel_err_pct"].mean(),
            "city_total_rel_err_pct_median": sub["city_total_rel_err_pct"].median(),
            "WAPE_city_pct_mean": sub["WAPE_city_pct"].mean(),
            "mean_site_mape_pct_mean": sub["mean_site_mape_pct"].mean(),
        })

df_period = pd.DataFrame(rows_period)

# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
df_detail.to_csv(OUT_DETAIL, index=False, encoding="utf-8-sig")
df_summary.to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")
df_scene.to_csv(OUT_SCENE, index=False, encoding="utf-8-sig")
if len(df_period) > 0:
    df_period.to_csv(OUT_DIR / "city_hourly_period_error_fixed.csv", index=False, encoding="utf-8-sig")

print(f"\nSaved:")
print(f"  {OUT_DETAIL}")
print(f"  {OUT_SUMMARY}")
print(f"  {OUT_SCENE}")

# ---------------------------------------------------------------------------
# Print summary table
# ---------------------------------------------------------------------------
print("\n" + "=" * 90)
print("全市逐小时误差指标（修复包1：正确口径）")
print("=" * 90)
print(f"{'Hour':>5} | {'真值均值MW':>11} | {'预测均值MW':>11} | {'bias%':>8} | "
      f"{'city_rel_err%':>14} | {'WAPE%':>8} | {'mean_site_mape%':>16}")
print(f"{'':>5} | {'':>11} | {'':>11} | {'':>8} | "
      f"{'(sum后计算)':>14} | {'(加权)':>8} | {'(站点评均)':>16}")
print("-" * 90)
for _, r in df_summary.iterrows():
    h = int(r["hour"])
    print(f"{h:>5} | {r['city_total_actual_mw_mean']:>11.1f} | {r['city_total_pred_mw_mean']:>11.1f} | "
          f"{r['city_total_bias_pct_mean']:>+8.1f} | {r['city_total_rel_err_pct_mean']:>14.1f} | "
          f"{r['WAPE_city_pct_mean']:>8.1f} | {r['mean_site_mape_pct']:>16.1f}")

print()
print("=" * 70)
print("按时段汇总")
print("=" * 70)
for _, r in df_period.iterrows():
    print(f"  {r['time_period']:>10} ({r['hour_range']}): "
          f"city_rel_err={r['city_total_rel_err_pct_mean']:.1f}%  "
          f"WAPE={r['WAPE_city_pct_mean']:.1f}%  "
          f"mean_site_mape={r['mean_site_mape_pct_mean']:.1f}%")

print("\nDone.")
