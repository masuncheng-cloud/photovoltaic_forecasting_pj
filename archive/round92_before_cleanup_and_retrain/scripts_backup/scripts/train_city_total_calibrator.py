#!/usr/bin/env python3
"""
train_city_total_calibrator.py
=============================
城市总量小时级校准器（高效版）。

基于 Round60 的 power_pred_final，在 valid 集上学习每小时的
城市总量校准因子：
  city_factor_hour = sum(actual) / sum(pred)

约束：
  10-14: factor ∈ [0.94, 1.04]
  6-9, 15-19: factor ∈ [0.97, 1.03]

收缩：
  final_factor = shrink * raw_factor + (1 - shrink) * 1.0
  shrink = n / (n + 3000)

回退条件（基于 valid）：
  - city_nrmse 变差 > 0.1pp → factor = 1.0
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


def rmse_vec(a, p):
    diff = np.asarray(a, dtype=float) - np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean(diff ** 2)))


def main():
    print("=" * 60)
    print("城市总量小时级校准器（高效版）")
    print(f"参数: shrink_k={SHRINK_K}")
    print("  10-14h: factor=[0.94, 1.04]")
    print("  6-9,15-19h: factor=[0.97, 1.03]")
    print("=" * 60)

    # Load Round60 baseline
    r60_path = ROOT / "output/pv_pipeline/baselines/round60/distributed_predictions_final_full.pkl"
    df = pd.read_pickle(r60_path)
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour

    pred_col = "power_pred_final"

    # Filter valid 6-19h
    dv = df[(df["split"] == "valid") & df["hour"].between(6, 19)].copy()
    print(f"[INFO] Valid 6-19h: {len(dv)} rows, {dv['hour'].nunique()} hours")

    # Pre-aggregate per (time, hour) for city metrics
    city_agg = (
        dv.groupby(["time", "hour"], as_index=False)
        .agg(
            actual_sum=("power_mw", "sum"),
            pred_sum=(pred_col, "sum"),
            cap_sum=("capacity_mw", "sum"),
            n_sites=("site_id", "nunique"),
        )
    )
    print(f"[INFO] City aggregation: {len(city_agg)} time-slices")

    # Pre-aggregate per (time, hour, site) for site metrics
    site_agg = (
        dv.groupby(["time", "hour", "site_id"], as_index=False)
        .agg(
            actual=("power_mw", "first"),
            pred=(pred_col, "first"),
            cap=("capacity_mw", "first"),
        )
    )

    # Per-site capacity (constant per site)
    site_cap = dv.groupby("site_id")["capacity_mw"].first().to_dict()

    # ── Step 1: Compute per-hour city factor ─────────────────────────
    hour_cal = {}
    for h, gag in city_agg.groupby("hour"):
        h = int(h)
        n_ts = len(gag)  # number of time-slices for this hour
        n_rows = n_ts * gag["n_sites"].mean()  # approximate total rows

        actual_sum = float(gag["actual_sum"].sum())
        pred_sum = float(gag["pred_sum"].sum())
        cap_h = float(gag["cap_sum"].mean())  # ~constant

        raw_factor = actual_sum / max(pred_sum, 1e-9)
        shrink = n_ts / (n_ts + SHRINK_K)
        final_factor = shrink * raw_factor + (1 - shrink) * 1.0

        if h in range(10, 15):
            f_min, f_max = 0.94, 1.04
        else:
            f_min, f_max = 0.97, 1.03

        clipped = min(max(float(final_factor), f_min), f_max)

        hour_cal[h] = {
            "n_ts": n_ts,
            "actual_sum": actual_sum,
            "pred_sum": pred_sum,
            "cap_h": cap_h,
            "raw_factor": raw_factor,
            "shrink": shrink,
            "final_factor": final_factor,
            "factor_clipped": clipped,
            "f_min": f_min,
            "f_max": f_max,
        }

    cal_df = pd.DataFrame.from_dict(hour_cal, orient="index").reset_index()
    cal_df.columns = ["hour", "n_ts", "actual_sum", "pred_sum", "cap_h",
                      "raw_factor", "shrink", "final_factor", "factor_clipped", "f_min", "f_max"]

    # ── Step 2: Compute per-hour valid metrics before/after ──────────
    results = []
    for h in sorted(hour_cal.keys()):
        c = hour_cal[h]
        gag = city_agg[city_agg["hour"] == h]

        # Before
        r_before = rmse_vec(gag["pred_sum"].values, gag["actual_sum"].values)
        c_nrmse_b = r_before / c["cap_h"] * 100
        bias_b = (c["pred_sum"] - c["actual_sum"]) / max(c["actual_sum"], 1e-9) * 100

        # After
        pred_after = gag["pred_sum"].values * c["factor_clipped"]
        r_after = rmse_vec(pred_after, gag["actual_sum"].values)
        c_nrmse_a = r_after / c["cap_h"] * 100
        bias_a = (c["pred_sum"] * c["factor_clipped"] - c["actual_sum"]) / max(c["actual_sum"], 1e-9) * 100

        # Site mean NRMSE for this hour
        sag = site_agg[site_agg["hour"] == h]
        sm_vals_b, sm_vals_a = [], []
        for sid in sag["site_id"].unique():
            sd = sag[sag["site_id"] == sid]
            cap_s = site_cap.get(str(sid), 1.0)
            if cap_s <= 0:
                continue
            a_vals = sd["actual"].values
            p_b = sd["pred"].values
            p_a = sd["pred"].values * c["factor_clipped"]
            sm_vals_b.append(rmse_vec(a_vals, p_b) / cap_s * 100)
            sm_vals_a.append(rmse_vec(a_vals, p_a) / cap_s * 100)
        sm_nrmse_b = float(np.mean(sm_vals_b)) if sm_vals_b else np.nan
        sm_nrmse_a = float(np.mean(sm_vals_a)) if sm_vals_a else np.nan

        c_delta = c_nrmse_a - c_nrmse_b
        sm_delta = sm_nrmse_a - sm_nrmse_b
        bias_abs_delta = abs(bias_a) - abs(bias_b)

        rollback = (
            c_delta > 0.1 or
            abs(bias_abs_delta) > 1.0 or
            sm_delta > 0.15
        )
        reasons = []
        if c_delta > 0.1:
            reasons.append(f"c_nrmse={c_delta:+.3f}")
        if abs(bias_abs_delta) > 1.0:
            reasons.append(f"bias_abs={bias_abs_delta:+.3f}")
        if sm_delta > 0.15:
            reasons.append(f"sm_nrmse={sm_delta:+.3f}")

        results.append({
            "hour": h,
            "factor_clipped": round(c["factor_clipped"], 4),
            "city_nrmse_before": round(c_nrmse_b, 4),
            "city_nrmse_after": round(c_nrmse_a, 4),
            "city_nrmse_delta": round(c_delta, 4),
            "sm_nrmse_before": round(sm_nrmse_b, 4),
            "sm_nrmse_after": round(sm_nrmse_a, 4),
            "sm_nrmse_delta": round(sm_delta, 4),
            "bias_before": round(bias_b, 4),
            "bias_after": round(bias_a, 4),
            "bias_abs_delta": round(bias_abs_delta, 4),
            "status": "rollback" if rollback else "ok",
            "rollback_reason": "; ".join(reasons),
        })

    rm_df = pd.DataFrame(results)

    # Apply rollback
    for _, row in rm_df.iterrows():
        h = int(row["hour"])
        if row["status"] == "rollback":
            hour_cal[h]["factor_final"] = 1.0
        else:
            hour_cal[h]["factor_final"] = hour_cal[h]["factor_clipped"]

    # Merge into calibrator
    cal_df["factor_final"] = cal_df["hour"].map(lambda h: round(hour_cal[int(h)]["factor_final"], 4))

    for col in ["city_nrmse_before", "city_nrmse_after", "city_nrmse_delta",
                "sm_nrmse_before", "sm_nrmse_after", "sm_nrmse_delta",
                "bias_before", "bias_after", "bias_abs_delta", "status", "rollback_reason"]:
        if col in rm_df.columns:
            cal_df[col] = cal_df["hour"].map(lambda h: rm_df[rm_df["hour"] == h][col].iloc[0])

    rolled_back = int((rm_df["status"] == "rollback").sum())
    print(f"[INFO] Hours rolled back: {rolled_back}/{len(rm_df)}")

    # Print summary
    print(f"\n{'Hour':>5} {'factor':>8} {'c_nrmse_b':>10} {'c_nrmse_a':>10} {'delta':>8} {'sm_d':>8} {'bias_d':>8} {'status':>10}")
    for _, r in rm_df.iterrows():
        h = int(r["hour"])
        f = hour_cal[h]["factor_final"]
        print(
            f"{h:>5} "
            f"{f:>8.4f} "
            f"{r['city_nrmse_before']:>10.4f} {r['city_nrmse_after']:>10.4f} "
            f"{r['city_nrmse_delta']:>+8.4f} "
            f"{r['sm_nrmse_delta']:>+8.4f} "
            f"{r['bias_abs_delta']:>+8.2f} "
            f"{r['status']:>10}"
        )

    # Overall valid metrics
    c_nrmse_b_all = float(np.mean(rm_df["city_nrmse_before"]))
    c_nrmse_a_all = float(np.mean(rm_df["city_nrmse_after"]))
    sm_nrmse_b_all = float(np.mean(rm_df["sm_nrmse_before"]))
    sm_nrmse_a_all = float(np.mean(rm_df["sm_nrmse_after"]))
    bias_b_all = float(np.mean(rm_df["bias_before"]))
    bias_a_all = float(np.mean(rm_df["bias_after"]))

    print(f"\n[INFO] Valid overall (6-19h):")
    print(f"  city_nrmse: {c_nrmse_b_all:.4f}% -> {c_nrmse_a_all:.4f}% (delta={c_nrmse_a_all-c_nrmse_b_all:+.4f}%)")
    print(f"  sm_nrmse:   {sm_nrmse_b_all:.4f}% -> {sm_nrmse_a_all:.4f}% (delta={sm_nrmse_a_all-sm_nrmse_b_all:+.4f}%)")
    print(f"  bias%:      {bias_b_all:.4f}% -> {bias_a_all:.4f}% (delta={bias_a_all-bias_b_all:+.4f}%)")

    # Save
    out_path = OUT / "city_total_hour_calibrator.csv"
    cal_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] {out_path}")


if __name__ == "__main__":
    main()
