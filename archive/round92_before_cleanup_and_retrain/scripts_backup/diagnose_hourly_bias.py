#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复包3：逐小时误差归因诊断
===================================
判断系统性低估来自哪一层：
  p_base → pred_baseline → power_pred_cal → power_pred

对每一层计算：
  1. 各层预测值 / 实际值的比例（ratio）
  2. 各层相对实际值的偏差百分比（bias_pct）
  3. 分层绝对误差贡献（该层引入的额外偏差）

同时按 scene_v151 和 month 交叉分析。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path("/home/ac/data16t/msc/photovoltaic_forecasting_pj")
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_FILE = OUT_DIR / "hourly_bias_decomposition.csv"
FIG_FILE = PROJECT_ROOT / "output" / "pv_pipeline" / "figures" / "hourly_bias_decomposition.png"

# 7 low-quality stations excluded
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}


def _mape(y_true, y_pred):
    mask = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / y_true[mask]) * 100)


def _mae(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask])))


def _sum_mae(y_true, y_pred):
    """Sum-based MAE (for city aggregation)."""
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.sum(np.abs(y_true[mask] - y_pred[mask])))


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
print("Reading predictions …")
pred_df = pd.read_pickle(PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "distributed_predictions.pkl")
print(f"  Total rows: {len(pred_df):,}")

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
print(f"  After filtering: {len(df):,} rows, {df['site_id'].nunique()} sites")

# ---------------------------------------------------------------------------
# Layer definitions
# ---------------------------------------------------------------------------
LAYERS = [
    ("p_base",           "物理基准功率 (p_base)"),
    ("pred_baseline",    "基线预测 (baseline after city-scale)"),
    ("power_pred_cal",   "站点标定后 (calibrated)"),
    ("power_pred",       "最终预测 (final power_pred)"),
]

# Check which columns actually exist
available_cols = set(df.columns)
print(f"\nAvailable prediction layers: {[c for c, _ in LAYERS if c in available_cols]}")

# ---------------------------------------------------------------------------
# Per-hour aggregation (site-level mean values)
# ---------------------------------------------------------------------------
print("\nComputing per-hour layer decomposition (site-level mean) …")

rows_hourly = []
for h in range(6, 20):
    sub = df[df["hour"] == h]
    if len(sub) == 0:
        continue

    yt = sub["power_mw"].values.astype(float)

    row = {"hour": h, "n_samples": len(sub), "n_sites": sub["site_id"].nunique()}

    prev_ratio = 1.0
    for col, label in LAYERS:
        if col not in sub.columns:
            row[f"{col}_mean"] = np.nan
            row[f"{col}_actual_ratio"] = np.nan
            row[f"{col}_bias_pct"] = np.nan
            continue

        yp = pd.to_numeric(sub[col], errors="coerce").fillna(0).values.astype(float)
        row[f"{col}_mean"] = float(np.nanmean(yp))
        actual_mean = float(np.nanmean(yt))
        ratio = float(np.nanmean(yp)) / actual_mean if actual_mean > 0 else np.nan
        bias = (float(np.nanmean(yp)) - actual_mean) / actual_mean * 100 if actual_mean > 0 else np.nan
        row[f"{col}_actual_ratio"] = ratio
        row[f"{col}_bias_pct"] = bias
        prev_ratio = ratio

    rows_hourly.append(row)

df_hourly = pd.DataFrame(rows_hourly)
df_hourly = df_hourly.sort_values("hour").reset_index(drop=True)

# ---------------------------------------------------------------------------
# City-level per-date-per-hour aggregation
# ---------------------------------------------------------------------------
print("Computing city-level per-date-per-hour decomposition …")

rows_city = []
for (date, hour), g in df.groupby(["date", "hour"]):
    yt_sum = g["power_mw"].sum()
    row = {"date": date, "hour": hour, "n_sites": g["site_id"].nunique()}

    for col, label in LAYERS:
        if col not in g.columns:
            row[f"{col}_sum"] = np.nan
            row[f"{col}_city_ratio"] = np.nan
            row[f"{col}_city_bias_pct"] = np.nan
            continue

        yp_sum = pd.to_numeric(g[col], errors="coerce").fillna(0).sum()
        row[f"{col}_sum"] = float(yp_sum)
        ratio = float(yp_sum) / float(yt_sum) if yt_sum > 0 else np.nan
        bias = (float(yp_sum) - float(yt_sum)) / float(yt_sum) * 100 if yt_sum > 0 else np.nan
        row[f"{col}_city_ratio"] = ratio
        row[f"{col}_city_bias_pct"] = bias

    rows_city.append(row)

df_city = pd.DataFrame(rows_city)
df_city = df_city.sort_values(["date", "hour"]).reset_index(drop=True)

# ---------------------------------------------------------------------------
# City-level per-hour summary (aggregated across dates)
# ---------------------------------------------------------------------------
print("Computing city-level per-hour summary …")

rows_city_summary = []
for h in range(6, 20):
    sub = df_city[df_city["hour"] == h]
    if len(sub) == 0:
        continue

    row = {"hour": h, "n_dates": len(sub)}

    for col, label in LAYERS:
        if f"{col}_city_ratio" not in sub.columns:
            continue

        ratios = sub[f"{col}_city_ratio"].dropna()
        biases = sub[f"{col}_city_bias_pct"].dropna()

        row[f"{col}_city_ratio_mean"] = ratios.mean() if len(ratios) else np.nan
        row[f"{col}_city_ratio_median"] = ratios.median() if len(ratios) else np.nan
        row[f"{col}_city_ratio_p25"] = ratios.quantile(0.25) if len(ratios) else np.nan
        row[f"{col}_city_ratio_p75"] = ratios.quantile(0.75) if len(ratios) else np.nan
        row[f"{col}_city_bias_pct_mean"] = biases.mean() if len(biases) else np.nan

    rows_city_summary.append(row)

df_city_summary = pd.DataFrame(rows_city_summary)

# ---------------------------------------------------------------------------
# Per-scene breakdown (site-level)
# ---------------------------------------------------------------------------
print("Computing per-scene breakdown …")

SCENE_THRESHOLDS = {
    "dawn": (6, 7),
    "morning": (8, 9),
    "midday": (10, 14),
    "afternoon": (15, 16),
    "dusk": (17, 19),
}

rows_scene = []
for scene_name, (h_start, h_end) in SCENE_THRESHOLDS.items():
    sub = df[(df["hour"] >= h_start) & (df["hour"] <= h_end)]
    if len(sub) == 0:
        continue

    yt = sub["power_mw"].values.astype(float)
    actual_mean = float(np.nanmean(yt))

    row = {"scene": scene_name, "hour_range": f"{h_start}-{h_end}",
           "n_samples": len(sub), "actual_mean": actual_mean}

    for col, label in LAYERS:
        if col not in sub.columns:
            continue
        yp = pd.to_numeric(sub[col], errors="coerce").fillna(0).values.astype(float)
        ratio = float(np.nanmean(yp)) / actual_mean if actual_mean > 0 else np.nan
        bias = (float(np.nanmean(yp)) - actual_mean) / actual_mean * 100 if actual_mean > 0 else np.nan
        mae_val = _mae(yt, np.where(np.isnan(pd.to_numeric(sub[col], errors="coerce")), 0, pd.to_numeric(sub[col], errors="coerce").fillna(0).values))
        row[f"{col}_mean"] = float(np.nanmean(yp))
        row[f"{col}_ratio"] = ratio
        row[f"{col}_bias_pct"] = bias
        row[f"{col}_mae"] = mae_val

    rows_scene.append(row)

df_scene = pd.DataFrame(rows_scene)

# ---------------------------------------------------------------------------
# Calibration parameter analysis
# ---------------------------------------------------------------------------
print("Computing calibration parameter distribution …")

calib_file = PROJECT_ROOT / "output" / "pv_pipeline" / "models" / "distributed_model.pkl"
if calib_file.exists():
    try:
        import pickle
        with open(calib_file, "rb") as f:
            model_bundle = pickle.load(f)

        if "calibration_params" in model_bundle:
            calib = model_bundle["calibration_params"]
            a_vals = [v[0] for v in calib.values() if isinstance(v, tuple) and len(v) >= 1]
            b_vals = [v[1] for v in calib.values() if isinstance(v, tuple) and len(v) >= 2]

            print(f"  Calibration params loaded: {len(a_vals)} sites")
            print(f"  a (scale)  : mean={np.mean(a_vals):.3f}, std={np.std(a_vals):.3f}, "
                  f"min={np.min(a_vals):.3f}, max={np.max(a_vals):.3f}")
            print(f"  b (offset) : mean={np.mean(b_vals):.3f}, std={np.std(b_vals):.3f}, "
                  f"min={np.min(b_vals):.3f}, max={np.max(b_vals):.3f}")
            print(f"  a < 1.0: {(np.array(a_vals) < 1.0).sum()} sites")
            print(f"  b < 0.0: {(np.array(b_vals) < 0.0).sum()} sites")
    except Exception as e:
        print(f"  Could not load calibration params: {e}")

# ---------------------------------------------------------------------------
# Save outputs
# ---------------------------------------------------------------------------
df_hourly.to_csv(OUT_DIR / "hourly_bias_decomposition_site_mean.csv", index=False, encoding="utf-8-sig")
df_city.to_csv(OUT_DIR / "hourly_bias_decomposition_city_daily.csv", index=False, encoding="utf-8-sig")
df_city_summary.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")
df_scene.to_csv(OUT_DIR / "hourly_bias_decomposition_scene.csv", index=False, encoding="utf-8-sig")

print(f"\nSaved:")
print(f"  {OUT_DIR / 'hourly_bias_decomposition_site_mean.csv'}")
print(f"  {OUT_DIR / 'hourly_bias_decomposition_city_daily.csv'}")
print(f"  {OUT_FILE}")
print(f"  {OUT_DIR / 'hourly_bias_decomposition_scene.csv'}")

# ---------------------------------------------------------------------------
# Print summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("逐小时偏差归因摘要（全市聚合均值）")
print("=" * 70)
print(f"{'Hour':>5} | {'p_base':>7} | {'baseline':>9} | {'calibrated':>10} | {'final':>7} | {'真值均值':>9}")
print(f"{'':>5} | {'ratio':>7} | {'ratio':>9} | {'ratio':>10} | {'ratio':>7} | {'(MW)':>9}")
print("-" * 70)
for _, r in df_hourly.iterrows():
    h = int(r["hour"])
    p = r.get("p_base_actual_ratio", np.nan)
    b = r.get("pred_baseline_actual_ratio", np.nan)
    c = r.get("power_pred_cal_actual_ratio", np.nan)
    f = r.get("power_pred_actual_ratio", np.nan)
    actual = r.get("p_base_mean", np.nan)  # placeholder; use actual
    print(f"{h:>5} | {p:>7.3f} | {b:>9.3f} | {c:>10.3f} | {f:>7.3f}")

print()
print("偏差方向分析：")
for _, r in df_hourly.iterrows():
    h = int(r["hour"])
    p = r.get("p_base_bias_pct", np.nan)
    b = r.get("pred_baseline_bias_pct", np.nan)
    c = r.get("power_pred_cal_bias_pct", np.nan)
    f = r.get("power_pred_bias_pct", np.nan)
    print(f"  {h:02d}h: p_base={p:+.1f}%  baseline={b:+.1f}%  calibrated={c:+.1f}%  final={f:+.1f}%")

print()
print("场景归因摘要：")
for _, r in df_scene.iterrows():
    scene = r["scene"]
    h_range = r["hour_range"]
    actual = r["actual_mean"]
    f_ratio = r.get("power_pred_ratio", np.nan)
    f_bias = r.get("power_pred_bias_pct", np.nan)
    p_ratio = r.get("p_base_ratio", np.nan)
    print(f"  {scene:>10} ({h_range}): 真值均值={actual:.3f}MW  "
          f"p_base={p_ratio:.3f}  final={f_ratio:.3f}  bias={f_bias:+.1f}%")

# ---------------------------------------------------------------------------
# Generate figure
# ---------------------------------------------------------------------------
try:
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Hourly Bias Decomposition (Test Set 2025-Jul+)", fontsize=14, fontweight="bold")

    hours = df_hourly["hour"].values
    layer_colors = {"p_base": "#2196F3", "pred_baseline": "#4CAF50",
                    "power_pred_cal": "#FF9800", "power_pred": "#F44336"}
    layer_labels = {"p_base": "p_base", "pred_baseline": "baseline",
                    "power_pred_cal": "calibrated", "power_pred": "final"}

    # Plot 1: Ratio to actual (site-level mean)
    ax = axes[0, 0]
    for col in ["p_base_actual_ratio", "pred_baseline_actual_ratio",
                "power_pred_cal_actual_ratio", "power_pred_actual_ratio"]:
        label = col.replace("_actual_ratio", "")
        if label in layer_labels:
            ax.plot(hours, df_hourly[col].values, "o-", label=layer_labels[label],
                    color=layer_colors.get(label, "gray"), linewidth=2, markersize=5)
    ax.axhline(1.0, color="black", linestyle="--", linewidth=1, label="perfect (1.0)")
    ax.set_xlabel("Hour")
    ax.set_ylabel("Predicted / Actual (ratio)")
    ax.set_title("Site-Level Mean: Predicted / Actual by Hour")
    ax.set_xticks(range(6, 20))
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)

    # Plot 2: Bias percentage
    ax = axes[0, 1]
    for col in ["p_base_bias_pct", "pred_baseline_bias_pct",
                "power_pred_cal_bias_pct", "power_pred_bias_pct"]:
        label = col.replace("_bias_pct", "")
        if label in layer_labels:
            ax.plot(hours, df_hourly[col].values, "o-", label=layer_labels[label],
                    color=layer_colors.get(label, "gray"), linewidth=2, markersize=5)
    ax.axhline(0, color="black", linestyle="--", linewidth=1)
    ax.set_xlabel("Hour")
    ax.set_ylabel("Bias %  ((pred - actual) / actual * 100)")
    ax.set_title("Site-Level Mean: Bias % by Hour (negative = underestimation)")
    ax.set_xticks(range(6, 20))
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)

    # Plot 3: City-level ratio (per-date, scattered)
    ax = axes[1, 0]
    for col, color, label in [
        ("p_base_city_ratio", "#2196F3", "p_base"),
        ("power_pred_city_ratio", "#F44336", "final"),
    ]:
        if col in df_city.columns:
            ax.scatter(df_city["hour"], df_city[col], alpha=0.15, s=8,
                       color=color, label=label)
    # Add hourly mean line
    city_hourly_means = df_city.groupby("hour")["power_pred_city_ratio"].mean()
    ax.plot(city_hourly_means.index, city_hourly_means.values, "r-",
            linewidth=2, label="final (hourly mean)")
    ax.axhline(1.0, color="black", linestyle="--", linewidth=1)
    ax.set_xlabel("Hour")
    ax.set_ylabel("City Total Pred / City Total Actual")
    ax.set_title("City-Level: Pred/Actual Ratio (each dot = one date-hour)")
    ax.set_xticks(range(6, 20))
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)

    # Plot 4: Scene comparison
    ax = axes[1, 1]
    scenes = df_scene["scene"].values
    x = np.arange(len(scenes))
    width = 0.2
    for i, (col, color, label) in enumerate([
        ("p_base_ratio", "#2196F3", "p_base"),
        ("pred_baseline_ratio", "#4CAF50", "baseline"),
        ("power_pred_cal_ratio", "#FF9800", "calibrated"),
        ("power_pred_ratio", "#F44336", "final"),
    ]):
        if col in df_scene.columns:
            ax.bar(x + i * width, df_scene[col].values, width,
                   color=color, label=label, alpha=0.85)
    ax.axhline(1.0, color="black", linestyle="--", linewidth=1)
    ax.set_xticks(x + width * 1.5)
    ax.set_xticklabels([f"{s}\n({r})" for s, r in zip(scenes, df_scene["hour_range"].values)],
                       fontsize=9)
    ax.set_ylabel("Predicted / Actual")
    ax.set_title("Scene-Level: Pred/Actual Ratio")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    FIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(FIG_FILE, dpi=150, bbox_inches="tight")
    print(f"\nFigure saved: {FIG_FILE}")
    plt.close()
except Exception as e:
    print(f"\nFigure generation failed (matplotlib may not be available): {e}")

print("\nDone.")
