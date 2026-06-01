#!/usr/bin/env python3
"""
train_city_total_calibrator.py
=============================
城市总量小时级校准器。

基于 Round60 的 power_pred_final（即 power_pred_round60_safe），在 valid 集上学习每小时的
城市总量校准因子：
  city_factor_hour = sum(actual) / sum(pred)

只允许轻量校准：
  10-14: factor ∈ [0.94, 1.04]
  6-9, 15-19: factor ∈ [0.97, 1.03]

收缩：
  final_factor = shrink * raw_factor + (1 - shrink) * 1.0
  shrink = n / (n + 3000)

回退条件（基于 valid）：
  - city_nrmse 变差 → factor = 1.0
  - bias_abs 变差 > 1pp → factor = 1.0
  - site_mean_nrmse 变差 > 0.15pp → factor = 1.0

输出：
  output/pv_pipeline/calibration/city_total_hour_calibrator.csv
"""

from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline" / "calibration"
OUT.mkdir(parents=True, exist_ok=True)

SHRINK_K = 3000


def rmse(a, p=None):
    if p is None:
        p = np.zeros_like(a)
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean((p - a) ** 2)))


def site_mean_nrmse(df, pred_col):
    vals = []
    for sid, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        r = rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100
        vals.append(r)
    return float(np.mean(vals)) if vals else np.nan


def city_nrmse_hourly(df, pred_col):
    """Per-timestamp aggregation, per-hour average."""
    vals = []
    for h, hdf in df.groupby("hour"):
        agg = hdf.groupby("time", as_index=False).agg(
            actual=("power_mw", "sum"),
            pred=(pred_col, "sum"),
            cap_sum=("capacity_mw", "sum"),
        )
        r = rmse(agg["pred"].values - agg["actual"].values)
        cap_h = float(agg["cap_sum"].mean())
        if cap_h > 0:
            vals.append(r / cap_h * 100)
    return float(np.mean(vals)) if vals else np.nan


def main():
    print("=" * 60)
    print("城市总量小时级校准器")
    print(f"参数: shrink_k={SHRINK_K}")
    print("  10-14h: factor=[0.94, 1.04]")
    print("  6-9,15-19h: factor=[0.97, 1.03]")
    print("=" * 60)

    # Load calibration dataset
    # Since we want to calibrate Round60's prediction, use the valid split from Round60's full pkl
    r60_path = ROOT / "output/pv_pipeline/baselines/round60/distributed_predictions_final_full.pkl"
    df = pd.read_pickle(r60_path)
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    print(f"[INFO] Round60 baseline: {len(df)} rows")

    # Use valid split
    df_valid = df[df["split"] == "valid"].copy()
    df_valid = df_valid[df_valid["hour"].between(6, 19)].copy()
    print(f"[INFO] Valid 6-19h: {len(df_valid)} rows")

    # The prediction column to calibrate
    # Round60's final prediction is power_pred_final (which equals power_pred_round60_safe)
    # But we should use the stored Round60 power_pred_final directly
    pred_col = "power_pred_final"
    print(f"[INFO] Calibrating column: {pred_col}")

    # Per-hour city factor
    rows = []
    for h in sorted(df_valid["hour"].unique()):
        hdf = df_valid[df_valid["hour"] == h].copy()
        n = len(hdf)

        actual_sum = float(hdf["power_mw"].sum())
        pred_sum = float(hdf[pred_col].sum())

        if pred_sum < 1e-9:
            raw_factor = np.nan
        else:
            raw_factor = actual_sum / pred_sum

        # Shrinkage toward 1.0
        shrink = n / (n + SHRINK_K)
        if np.isnan(raw_factor):
            final_factor = 1.0
        else:
            final_factor = shrink * raw_factor + (1 - shrink) * 1.0

        # Clipping
        if h in range(10, 15):  # 10-14
            f_min, f_max = 0.94, 1.04
        else:
            f_min, f_max = 0.97, 1.03

        clipped = min(max(float(final_factor), f_min), f_max)

        rows.append({
            "hour": int(h),
            "n": n,
            "actual_sum": round(actual_sum, 4),
            "pred_sum": round(pred_sum, 4),
            "raw_factor": round(raw_factor, 4) if not np.isnan(raw_factor) else np.nan,
            "shrink": round(shrink, 4),
            "final_factor": round(final_factor, 4),
            "factor_clipped": round(clipped, 4),
            "factor_min": f_min,
            "factor_max": f_max,
        })

    cal = pd.DataFrame(rows)

    # Valid evaluation: per-hour impact
    print("\n[INFO] Valid set evaluation...")
    hs_map = {}
    for _, r in cal.iterrows():
        hs_map[int(r["hour"])] = float(r["factor_clipped"])

    def get_factor(h):
        return hs_map.get(int(h), 1.0)

    df_valid["city_factor"] = df_valid["hour"].map(get_factor)
    df_valid["pred_calibrated"] = (df_valid[pred_col] * df_valid["city_factor"]).clip(lower=0)

    # Per-hour metrics before/after
    hour_metrics = []
    for h in sorted(df_valid["hour"].unique()):
        hdf_before = df_valid[df_valid["hour"] == h].copy()
        hdf_after = hdf_before.copy()
        hdf_after[pred_col] = hdf_after["pred_calibrated"]

        # Baseline
        cap_h = float(hdf_before.groupby("site_id")["capacity_mw"].first().sum())
        agg_before = hdf_before.groupby("time", as_index=False).agg(
            actual=("power_mw", "sum"),
            pred=(pred_col, "sum"),
            cap_sum=("capacity_mw", "sum"),
        )
        r_before = rmse(agg_before["pred"].values - agg_before["actual"].values)
        c_nrmse_b = r_before / cap_h * 100 if cap_h > 0 else np.nan
        sm_nrmse_b = site_mean_nrmse(hdf_before, pred_col)
        bias_b = (float(hdf_before[pred_col].sum()) - float(hdf_before["power_mw"].sum())) / max(float(hdf_before["power_mw"].sum()), 1e-9) * 100

        # After calibration
        agg_after = hdf_after.groupby("time", as_index=False).agg(
            actual=("power_mw", "sum"),
            pred=(pred_col, "sum"),
        )
        r_after = rmse(agg_after["pred"].values - agg_after["actual"].values)
        c_nrmse_a = r_after / cap_h * 100 if cap_h > 0 else np.nan
        sm_nrmse_a = site_mean_nrmse(hdf_after, pred_col)
        bias_a = (float(hdf_after[pred_col].sum()) - float(hdf_after["power_mw"].sum())) / max(float(hdf_after["power_mw"].sum()), 1e-9) * 100

        # Rollback conditions
        c_delta = c_nrmse_a - c_nrmse_b
        sm_delta = sm_nrmse_a - sm_nrmse_b
        bias_abs_delta = abs(bias_a) - abs(bias_b)

        rollback = (
            c_delta > 0.1 or
            abs(bias_abs_delta) > 1.0 or
            sm_delta > 0.15
        )
        rollback_reasons = []
        if c_delta > 0.1:
            rollback_reasons.append(f"city_nrmse_delta={c_delta:+.3f}")
        if abs(bias_abs_delta) > 1.0:
            rollback_reasons.append(f"bias_abs_delta={bias_abs_delta:+.3f}")
        if sm_delta > 0.15:
            rollback_reasons.append(f"sm_nrmse_delta={sm_delta:+.3f}")

        if rollback:
            factor_final = 1.0
            status = "rollback"
        else:
            factor_final = hs_map[int(h)]
            status = "ok"

        hour_metrics.append({
            "hour": int(h),
            "n": n,
            "city_nrmse_before": round(c_nrmse_b, 4),
            "city_nrmse_after": round(c_nrmse_a, 4),
            "city_nrmse_delta": round(c_delta, 4),
            "sm_nrmse_before": round(sm_nrmse_b, 4),
            "sm_nrmse_after": round(sm_nrmse_a, 4),
            "sm_nrmse_delta": round(sm_delta, 4),
            "bias_before": round(bias_b, 4),
            "bias_after": round(bias_a, 4),
            "bias_abs_delta": round(bias_abs_delta, 4),
            "factor_clipped": round(hs_map[int(h)], 4),
            "factor_final": round(factor_final, 4),
            "status": status,
            "rollback_reason": "; ".join(rollback_reasons) if rollback else "",
        })

    hm = pd.DataFrame(hour_metrics)

    # Update calibrator with final factors
    for i, row in cal.iterrows():
        h = int(row["hour"])
        final_f = hm[hm["hour"] == h]["factor_final"].iloc[0]
        cal.at[i, "factor_final"] = round(final_f, 4)

    # Add valid metrics to calibrator
    cal = cal.merge(hm[["hour", "city_nrmse_before", "city_nrmse_after", "city_nrmse_delta",
                          "sm_nrmse_before", "sm_nrmse_after", "sm_nrmse_delta",
                          "bias_before", "bias_after", "bias_abs_delta",
                          "status", "rollback_reason"]],
                    on="hour", how="left")

    # Overall valid metrics
    df_before = df_valid.copy()
    df_after = df_valid.copy()
    df_after[pred_col] = df_after["pred_calibrated"]

    c_nrmse_b_all = city_nrmse_hourly(df_before, pred_col)
    c_nrmse_a_all = city_nrmse_hourly(df_after, pred_col)
    sm_nrmse_b_all = site_mean_nrmse(df_before, pred_col)
    sm_nrmse_a_all = site_mean_nrmse(df_after, pred_col)
    a_sum = float(df_before["power_mw"].sum())
    bias_b_all = (float(df_before[pred_col].sum()) - a_sum) / max(a_sum, 1e-9) * 100
    bias_a_all = (float(df_after[pred_col].sum()) - a_sum) / max(a_sum, 1e-9) * 100

    print(f"\n[INFO] Valid overall (6-19h):")
    print(f"  city_nrmse: {c_nrmse_b_all:.4f}% -> {c_nrmse_a_all:.4f}% (delta={c_nrmse_a_all-c_nrmse_b_all:+.4f}%)")
    print(f"  sm_nrmse:   {sm_nrmse_b_all:.4f}% -> {sm_nrmse_a_all:.4f}% (delta={sm_nrmse_a_all-sm_nrmse_b_all:+.4f}%)")
    print(f"  bias%:      {bias_b_all:.4f}% -> {bias_a_all:.4f}% (delta={bias_a_all-bias_b_all:+.4f}%)")

    rolled_back = int((hm["status"] == "rollback").sum())
    print(f"\n[INFO] Hours rolled back: {rolled_back}/{len(hm)}")

    print(f"\n[INFO] Per-hour summary:")
    print(f"{'Hour':>5} {'factor':>8} {'c_nrmse_b':>10} {'c_nrmse_a':>10} {'delta':>8} {'sm_delta':>8} {'bias_d':>8} {'status':>10}")
    for _, r in hm.iterrows():
        print(
            f"{int(r['hour']):>5} "
            f"{r['factor_final']:>8.4f} "
            f"{r['city_nrmse_before']:>10.4f} {r['city_nrmse_after']:>10.4f} "
            f"{r['city_nrmse_delta']:>+8.4f} "
            f"{r['sm_nrmse_delta']:>+8.4f} "
            f"{r['bias_abs_delta']:>+8.2f} "
            f"{r['status']:>10}"
        )

    # Save
    out_path = OUT / "city_total_hour_calibrator.csv"
    cal.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] {out_path}")


if __name__ == "__main__":
    main()
