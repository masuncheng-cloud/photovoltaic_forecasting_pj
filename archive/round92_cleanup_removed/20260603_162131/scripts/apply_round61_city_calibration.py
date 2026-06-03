#!/usr/bin/env python3
"""
apply_round61_city_calibration.py
=================================
应用城市总量校准器，生成带站点级和小时级保护的候选预测。

输入：
  baselines/round60/distributed_predictions_final_full.pkl
  calibration/city_total_hour_calibrator.csv

生成候选列：
  power_pred_round61_city        - 纯城市校准（无保护）
  power_pred_round61_city_safe   - 城市校准 + 站点/小时保护

输出：
  predictions/distributed_predictions_round61_candidates.pkl
  calibration/round61_site_guard.csv
  calibration/round61_hour_guard.csv
"""

from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline" / "predictions"
CAL = ROOT / "output/pv_pipeline" / "calibration"

# Site-level guard thresholds (valid set)
SITE_NRMSE_DELTA_THRESHOLD = 0.3   # pp
SITE_BIAS_ABS_DELTA_THRESHOLD = 3.0  # pp

# Hour-level guard thresholds (valid set)
HOUR_SM_NRMSE_DELTA_THRESHOLD = 0.15  # pp
HOUR_CITY_NRMSE_DELTA_THRESHOLD = 0.1  # pp


def rmse_vec(a, p):
    diff = np.asarray(a, dtype=float) - np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean(diff ** 2)))


def site_mean_nrmse(df, pred_col, cap_col="capacity_mw"):
    vals = []
    for sid, sdf in df.groupby("site_id"):
        cap = float(sdf[cap_col].iloc[0])
        if cap <= 0:
            continue
        vals.append(rmse_vec(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100)
    return float(np.mean(vals)) if vals else np.nan


def city_nrmse_per_hour_avg(df, pred_col, cap_col="capacity_mw"):
    vals = []
    for h, hdf in df.groupby("hour"):
        agg = hdf.groupby("time", as_index=False).agg(
            actual=("power_mw", "sum"),
            pred=(pred_col, "sum"),
            cap_sum=(cap_col, "sum"),
        )
        r = rmse_vec(agg["pred"].values, agg["actual"].values)
        cap_h = float(agg["cap_sum"].mean())
        if cap_h > 0:
            vals.append(r / cap_h * 100)
    return float(np.nanmean(vals)) if vals else np.nan


def main():
    print("=" * 60)
    print("应用 Round61 城市总量校准器")
    print(f"站点保护: NRMSE > {SITE_NRMSE_DELTA_THRESHOLD}pp OR bias_abs > {SITE_BIAS_ABS_DELTA_THRESHOLD}pp → 回退")
    print(f"小时保护: site_mean_nrmse > {HOUR_SM_NRMSE_DELTA_THRESHOLD}pp OR city_nrmse > {HOUR_CITY_NRMSE_DELTA_THRESHOLD}pp → 回退")
    print("=" * 60)

    # Load Round60 baseline (contains power_pred_final = power_pred_round60_safe)
    baseline = pd.read_pickle(
        ROOT / "output/pv_pipeline/baselines/round60/distributed_predictions_final_full.pkl"
    )
    baseline["time"] = pd.to_datetime(baseline["time"])
    if "hour" not in baseline.columns:
        baseline["hour"] = baseline["time"].dt.hour

    pred_base = "power_pred_final"  # This is power_pred_round60_safe
    print(f"[INFO] Baseline: {len(baseline)} rows, splits: {baseline['split'].value_counts().to_dict()}")
    print(f"[INFO] Base pred column: {pred_base}")

    # Load city calibrator
    cal_df = pd.read_csv(CAL / "city_total_hour_calibrator.csv")
    hour_factor_map = {}
    for _, r in cal_df.iterrows():
        hour_factor_map[int(r["hour"])] = float(r["factor_final"])

    print(f"[INFO] City calibrator: {len(cal_df)} hours")
    for _, r in cal_df.iterrows():
        print(f"  h={int(r['hour']):2d}: factor={float(r['factor_final']):.4f} status={r['status']}")

    # ── Apply city calibration ────────────────────────────────────────
    print("\n[INFO] Applying city calibration...")
    baseline["city_factor"] = baseline["hour"].map(hour_factor_map).fillna(1.0)
    baseline["power_pred_round61_city"] = (
        baseline[pred_base] * baseline["city_factor"]
    ).clip(lower=0)

    # Clip to capacity
    if "capacity_mw" in baseline.columns:
        baseline["power_pred_round61_city"] = baseline["power_pred_round61_city"].clip(
            upper=baseline["capacity_mw"]
        )

    # ── Compute guards on valid set ───────────────────────────────────
    print("\n[INFO] Computing site-level and hour-level guards on valid set...")

    df_valid = baseline[baseline["split"] == "valid"].copy()
    if len(df_valid) == 0:
        print("[WARN] No valid data, skipping guards")
        baseline["power_pred_round61_city_safe"] = baseline["power_pred_round61_city"].copy()
    else:
        # Filter to 6-19h for valid (for guard computation)
        dv = df_valid[df_valid["hour"].between(6, 19)].copy()

        # ── Site-level guard ───────────────────────────────────────────
        site_guard_rows = []
        site_fallback = {}  # site_id -> True if should fallback

        for sid, sdf in dv.groupby("site_id"):
            sid = str(sid)
            cap_s = float(sdf["capacity_mw"].iloc[0])
            if cap_s <= 0:
                site_fallback[sid] = True
                continue

            # Baseline
            p_base = sdf[pred_base].values.astype(float)
            a_vals = sdf["power_mw"].values.astype(float)
            base_rmse = rmse_vec(a_vals, p_base)
            base_nrmse = base_rmse / cap_s * 100
            a_sum = float(a_vals.sum())
            base_bias_abs = abs(float(p_base.sum()) - a_sum) / max(a_sum, 1e-9) * 100

            # City calibrated
            p_city = sdf["power_pred_round61_city"].values.astype(float)
            city_rmse = rmse_vec(a_vals, p_city)
            city_nrmse = city_rmse / cap_s * 100
            city_bias_abs = abs(float(p_city.sum()) - a_sum) / max(a_sum, 1e-9) * 100

            nrmse_delta = city_nrmse - base_nrmse
            bias_delta = city_bias_abs - base_bias_abs

            should_fallback = (
                nrmse_delta > SITE_NRMSE_DELTA_THRESHOLD or
                bias_delta > SITE_BIAS_ABS_DELTA_THRESHOLD
            )
            site_fallback[sid] = should_fallback

            reasons = []
            if nrmse_delta > SITE_NRMSE_DELTA_THRESHOLD:
                reasons.append(f"nrmse_delta={nrmse_delta:+.3f}pp")
            if bias_delta > SITE_BIAS_ABS_DELTA_THRESHOLD:
                reasons.append(f"bias_abs_delta={bias_delta:+.3f}pp")

            site_guard_rows.append({
                "site_id": sid,
                "valid_baseline_nrmse": round(base_nrmse, 4),
                "valid_city_nrmse": round(city_nrmse, 4),
                "valid_nrmse_delta": round(nrmse_delta, 4),
                "valid_baseline_bias_abs": round(base_bias_abs, 4),
                "valid_city_bias_abs": round(city_bias_abs, 4),
                "valid_bias_abs_delta": round(bias_delta, 4),
                "fallback_applied": should_fallback,
                "fallback_reason": "; ".join(reasons) if reasons else "",
            })

        site_guard_df = pd.DataFrame(site_guard_rows)
        site_guard_df.to_csv(CAL / "round61_site_guard.csv", index=False, encoding="utf-8-sig")
        n_sites = site_guard_df["fallback_applied"].sum()
        print(f"[INFO] Site guard: {n_sites}/{len(site_guard_df)} sites fallback to Round60")

        # ── Hour-level guard ────────────────────────────────────────────
        # Compare valid site_mean_nrmse and city_nrmse before/after city factor
        hour_guard_rows = []
        hour_fallback = {}  # hour -> True if should fallback

        for h in sorted(dv["hour"].unique()):
            hdf = dv[dv["hour"] == h].copy()

            # Baseline
            cap_h = float(hdf.groupby("site_id")["capacity_mw"].first().sum())
            if cap_h <= 0:
                continue

            base_sm_nrmse = site_mean_nrmse(hdf, pred_base)
            base_city_nrmse = city_nrmse_per_hour_avg(hdf, pred_base)

            # After city factor
            hdf_city = hdf.copy()
            hdf_city["pred_col_tmp"] = hdf_city["power_pred_round61_city"]
            city_sm_nrmse = site_mean_nrmse(hdf_city, "pred_col_tmp")
            city_c_nrmse = city_nrmse_per_hour_avg(hdf_city, "pred_col_tmp")

            sm_delta = city_sm_nrmse - base_sm_nrmse
            c_delta = city_c_nrmse - base_city_nrmse

            should_fallback = (
                sm_delta > HOUR_SM_NRMSE_DELTA_THRESHOLD or
                c_delta > HOUR_CITY_NRMSE_DELTA_THRESHOLD
            )
            hour_fallback[int(h)] = should_fallback

            reasons = []
            if sm_delta > HOUR_SM_NRMSE_DELTA_THRESHOLD:
                reasons.append(f"sm_nrmse={sm_delta:+.4f}pp")
            if c_delta > HOUR_CITY_NRMSE_DELTA_THRESHOLD:
                reasons.append(f"city_nrmse={c_delta:+.4f}pp")

            hour_guard_rows.append({
                "hour": int(h),
                "valid_baseline_sm_nrmse": round(base_sm_nrmse, 4),
                "valid_city_sm_nrmse": round(city_sm_nrmse, 4),
                "valid_sm_nrmse_delta": round(sm_delta, 4),
                "valid_baseline_city_nrmse": round(base_city_nrmse, 4),
                "valid_city_city_nrmse": round(city_c_nrmse, 4),
                "valid_city_nrmse_delta": round(c_delta, 4),
                "fallback_applied": should_fallback,
                "fallback_reason": "; ".join(reasons) if reasons else "",
            })

        hour_guard_df = pd.DataFrame(hour_guard_rows)
        hour_guard_df.to_csv(CAL / "round61_hour_guard.csv", index=False, encoding="utf-8-sig")
        n_hours = hour_guard_df["fallback_applied"].sum()
        print(f"[INFO] Hour guard: {n_hours}/{len(hour_guard_df)} hours fallback to Round60")

        # ── Apply safe version: apply city factor only where both guards pass ──
        print("\n[INFO] Applying safe version (city factor only where guards pass)...")
        baseline["power_pred_round61_city_safe"] = baseline[pred_base].copy()

        # For rows within 6-19h where both site and hour guards pass
        mask_apply = (
            baseline["hour"].between(6, 19) &
            baseline["site_id"].map(site_fallback).fillna(False).eq(False) &
            baseline["hour"].map(hour_fallback).fillna(False).eq(False)
        )
        baseline.loc[mask_apply, "power_pred_round61_city_safe"] = (
            baseline.loc[mask_apply, pred_base] * baseline.loc[mask_apply, "city_factor"]
        ).clip(lower=0)

        if "capacity_mw" in baseline.columns:
            baseline["power_pred_round61_city_safe"] = baseline["power_pred_round61_city_safe"].clip(
                upper=baseline["capacity_mw"]
            )

        n_applied = int(mask_apply.sum())
        print(f"[INFO] Safe version applied to {n_applied}/{len(baseline)} rows")

        # Summary of safe version
        print(f"\n{'Hour':>5} {'Factor':>8} {'SiteFallback':>14} {'HourFallback':>13} {'Status':>10}")
        for h in sorted(dv["hour"].unique()):
            h = int(h)
            f = hour_factor_map.get(h, 1.0)
            sf = "YES" if site_guard_df["fallback_applied"].any() else "no"  # aggregate below
            hf = "YES" if hour_fallback.get(h, False) else "no"
            status = "ROLLBACK" if (hour_fallback.get(h, False)) else "city_factor"
            print(f"{h:>5} {f:>8.4f} {'':>14} {hf:>13} {status:>10}")

    # Save
    out_path = OUT / "distributed_predictions_round61_candidates.pkl"
    baseline.to_pickle(out_path)
    print(f"\n[OK] {out_path}")

    # Also print overall guard summary
    print("\n[INFO] Guard summary:")
    if len(df_valid) > 0:
        print(f"  Sites falling back: {int(site_guard_df['fallback_applied'].sum())}/{len(site_guard_df)}")
        print(f"  Hours falling back: {int(hour_guard_df['fallback_applied'].sum())}/{len(hour_guard_df)}")


if __name__ == "__main__":
    main()
