#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复包2：增加 active / clipped / WAPE 多指标评价
===================================
在原有 MAPE 基础上，补充以下指标：
  1. MAPE_active: 仅评价有效发电样本（elev > 8, g > 150 W/m², power > 0）
  2. MAPE_clipped: 分母为 max(actual, 0.05 * capacity)
  3. WAPE_city  : sum(|e|) / sum(actual)
  4. NMAE_cap   : MAE / capacity
  5. NRMSE_cap  : RMSE / capacity

同时输出：
  - 按小时的指标表
  - 按场景的指标表
  - 按日期的指标表
"""
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path("/home/ac/data16t/msc/photovoltaic_forecasting_pj")
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
OUT_DIR.mkdir(parents=True, exist_ok=True)
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}

# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def mape(y_true, y_pred):
    mask = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / y_true[mask]) * 100)

def mape_active(y_true, y_pred, ghi):
    """Active MAPE: only samples with g_blend_pred > 150 W/m^2 (proxy for elev > 6 deg)."""
    mask = (
        (y_true > 0) &
        np.isfinite(y_true) & np.isfinite(y_pred) &
        (ghi > 150)
    )
    if not mask.any():
        return np.nan
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / y_true[mask]) * 100)

def mape_clipped(y_true, y_pred, capacity):
    """Clipped MAPE: denominator = max(actual, 0.05 * capacity)."""
    mask = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    denom = np.maximum(y_true, 0.05 * capacity)
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / denom[mask]) * 100)

def wape(y_true, y_pred):
    """WAPE: sum(|e|) / sum(|y|) * 100."""
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any() or np.sum(np.abs(y_true[mask])) == 0:
        return np.nan
    return float(np.sum(np.abs(y_true[mask] - y_pred[mask])) / np.sum(np.abs(y_true[mask])) * 100)

def nmae_cap(y_true, y_pred, capacity):
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any() or not np.isfinite(capacity) or capacity <= 0:
        return np.nan
    mae_val = float(np.mean(np.abs(y_true[mask] - y_pred[mask])))
    return mae_val / capacity

def nrmse_cap(y_true, y_pred, capacity):
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any() or not np.isfinite(capacity) or capacity <= 0:
        return np.nan
    rmse_val = float(np.sqrt(np.mean((y_true[mask] - y_pred[mask]) ** 2)))
    return rmse_val / capacity

def mae(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask])))

def rmse(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.sqrt(np.mean((y_true[mask] - y_pred[mask]) ** 2)))

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
print("Reading predictions ...")
pred_df = pd.read_pickle(PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "distributed_predictions.pkl")
pred_df["time"] = pd.to_datetime(pred_df["time"])
pred_df["year"] = pred_df["time"].dt.year
pred_df["month"] = pred_df["time"].dt.month
pred_df["date"] = pred_df["time"].dt.date
pred_df["hour"] = pred_df["time"].dt.hour

mask = (
    (pred_df["year"] >= 2025) & (pred_df["month"] >= 7) &
    (pred_df["hour"] >= 6) & (pred_df["hour"] <= 19) &
    (pred_df["power_mw"] > 0) &
    (~pred_df["site_id"].isin(BAD_SITES))
)
df = pred_df[mask].copy()
print(f"Filtered: {len(df):,} rows, {df['site_id'].nunique()} sites")

# ---------------------------------------------------------------------------
# Scene labels
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
# Per-hour multi-metric
# ---------------------------------------------------------------------------
print("Computing per-hour multi-metric ...")
rows_hourly = []
for h in range(6, 20):
    sub = df[df["hour"] == h].copy()
    if len(sub) == 0:
        continue

    yt = sub["power_mw"].values.astype(float)
    yp = sub["power_pred"].values.astype(float)
    cap = sub["capacity_mw"].values.astype(float)
    ghi = pd.to_numeric(sub.get("g_blend_pred", pd.Series(0, index=sub.index)), errors="coerce").fillna(0).values.astype(float)

    row = {
        "hour": int(h),
        "n_samples": len(sub),
        "n_sites": sub["site_id"].nunique(),
        # Original MAPE (site-level mean)
        "mape_raw_pct": mape(yt, yp),
        # Active MAPE
        "mape_active_pct": mape_active(yt, yp, ghi),
        # Clipped MAPE
        "mape_clipped_pct": mape_clipped(yt, yp, cap),
        # MAE / RMSE
        "mae": mae(yt, yp),
        "rmse": rmse(yt, yp),
        # WAPE
        "wape_pct": wape(yt, yp),
        # Capacity-normalized
        "nmae_cap_mean": np.nanmean([nmae_cap(yt[sub["site_id"] == sid], yp[sub["site_id"] == sid], cap[sub["site_id"] == sid][0])
                                      for sid in sub["site_id"].unique()]),
        "nrmse_cap_mean": np.nanmean([nrmse_cap(yt[sub["site_id"] == sid], yp[sub["site_id"] == sid], cap[sub["site_id"] == sid][0])
                                      for sid in sub["site_id"].unique()]),
    }
    rows_hourly.append(row)

df_hourly = pd.DataFrame(rows_hourly)

# ---------------------------------------------------------------------------
# Per-scene multi-metric
# ---------------------------------------------------------------------------
print("Computing per-scene multi-metric ...")
rows_scene = []
for scene in ["low", "ramp", "mid", "clear_peak"]:
    sub = df[df["scene_label"] == scene].copy()
    if len(sub) == 0:
        continue
    yt = sub["power_mw"].values.astype(float)
    yp = sub["power_pred"].values.astype(float)
    cap = sub["capacity_mw"].values.astype(float)
    ghi = pd.to_numeric(sub.get("g_blend_pred", pd.Series(0, index=sub.index)), errors="coerce").fillna(0).values.astype(float)

    rows_scene.append({
        "scene": scene,
        "n_samples": len(sub),
        "mape_raw_pct": mape(yt, yp),
        "mape_active_pct": mape_active(yt, yp, ghi),
        "mape_clipped_pct": mape_clipped(yt, yp, cap),
        "mae": mae(yt, yp),
        "rmse": rmse(yt, yp),
        "wape_pct": wape(yt, yp),
    })
df_scene = pd.DataFrame(rows_scene)

# ---------------------------------------------------------------------------
# Per-date multi-metric (city-level)
# ---------------------------------------------------------------------------
print("Computing per-date multi-metric ...")
rows_date = []
for date, day_df in df.groupby("date"):
    if len(day_df) == 0:
        continue
    yt_sum = day_df["power_mw"].sum()
    yp_sum = day_df["power_pred"].sum()
    yt = day_df["power_mw"].values.astype(float)
    yp = day_df["power_pred"].values.astype(float)

    rows_date.append({
        "date": date,
        "n_samples": len(day_df),
        "n_sites": day_df["site_id"].nunique(),
        "city_actual_mw": float(yt_sum),
        "city_pred_mw": float(yp_sum),
        "city_rel_err_pct": float(np.abs(yp_sum - yt_sum) / yt_sum * 100) if yt_sum > 0 else np.nan,
        "wape_city_pct": wape(yt, yp),
        "mape_raw_pct": mape(yt, yp),
        "mape_active_pct": np.nan,   # requires per-row elev/ghi
    })
df_date = pd.DataFrame(rows_date)

# ---------------------------------------------------------------------------
# Per-time-period summary
# ---------------------------------------------------------------------------
periods = [("dawn", 6, 7), ("morning", 8, 9), ("midday", 10, 14),
           ("afternoon", 15, 16), ("dusk", 17, 19)]
rows_period = []
for name, h_start, h_end in periods:
    sub = df[df["hour"].between(h_start, h_end)].copy()
    if len(sub) == 0:
        continue
    yt = sub["power_mw"].values.astype(float)
    yp = sub["power_pred"].values.astype(float)
    cap = sub["capacity_mw"].values.astype(float)
    ghi = pd.to_numeric(sub.get("g_blend_pred", pd.Series(0, index=sub.index)), errors="coerce").fillna(0).values.astype(float)

    rows_period.append({
        "time_period": name,
        "hour_range": f"{h_start}-{h_end}",
        "n_samples": len(sub),
        "mape_raw_pct": mape(yt, yp),
        "mape_active_pct": mape_active(yt, yp, ghi),
        "mape_clipped_pct": mape_clipped(yt, yp, cap),
        "mae": mae(yt, yp),
        "rmse": rmse(yt, yp),
        "wape_pct": wape(yt, yp),
    })
df_period = pd.DataFrame(rows_period)

# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
df_hourly.to_csv(OUT_DIR / "multi_metric_by_hour.csv", index=False, encoding="utf-8-sig")
df_scene.to_csv(OUT_DIR / "multi_metric_by_scene.csv", index=False, encoding="utf-8-sig")
df_date.to_csv(OUT_DIR / "multi_metric_by_date.csv", index=False, encoding="utf-8-sig")
df_period.to_csv(OUT_DIR / "multi_metric_by_period.csv", index=False, encoding="utf-8-sig")
print(f"\nSaved:")
print(f"  {OUT_DIR / 'multi_metric_by_hour.csv'}")
print(f"  {OUT_DIR / 'multi_metric_by_scene.csv'}")
print(f"  {OUT_DIR / 'multi_metric_by_date.csv'}")
print(f"  {OUT_DIR / 'multi_metric_by_period.csv'}")

# ---------------------------------------------------------------------------
# Print summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 90)
print("逐小时多指标评价（修复包2）")
print("=" * 90)
print(f"{'Hour':>5} | {'MAPE_raw%':>10} | {'MAPE_active%':>12} | {'MAPE_clip%':>11} | {'WAPE%':>7} | {'MAE':>7} | {'RMSE':>7}")
print("-" * 75)
for _, r in df_hourly.iterrows():
    h = int(r["hour"])
    print(f"{h:>5} | {r['mape_raw_pct']:>10.1f} | {r['mape_active_pct']:>12.1f} | "
          f"{r['mape_clipped_pct']:>11.1f} | {r['wape_pct']:>7.1f} | {r['mae']:>7.3f} | {r['rmse']:>7.3f}")

print("\n按时段汇总：")
for _, r in df_period.iterrows():
    print(f"  {r['time_period']:>10} ({r['hour_range']}): "
          f"MAPE_raw={r['mape_raw_pct']:.1f}%  MAPE_active={r['mape_active_pct']:.1f}%  "
          f"WAPE={r['wape_pct']:.1f}%")

print("\n按场景汇总：")
for _, r in df_scene.iterrows():
    print(f"  {r['scene']:>12}: "
          f"MAPE_raw={r['mape_raw_pct']:.1f}%  MAPE_active={r['mape_active_pct']:.1f}%  "
          f"WAPE={r['wape_pct']:.1f}%")

print("\nDone.")
