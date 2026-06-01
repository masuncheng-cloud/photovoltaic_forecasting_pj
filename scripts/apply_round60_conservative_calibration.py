#!/usr/bin/env python3
"""
apply_round60_conservative_calibration.py
======================================
应用保守校准器并生成候选预测列，包含站点级和小时级回退。

输入：
  baselines/round58/distributed_predictions_final_full.pkl
  calibration/hour_scene_calibrator_conservative.csv
  calibration/site_bias_calibrator_conservative.csv

生成候选列：
  power_pred_round60_hour_scene
  power_pred_round60_site_conservative
  power_pred_round60_combined_conservative
  power_pred_round60_safe

输出：
  predictions/distributed_predictions_round60_candidates.pkl
  calibration/round60_site_level_guard.csv
  calibration/round60_hour_level_guard.csv
"""

from pathlib import Path
import yaml
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline" / "predictions"
CAL = ROOT / "output/pv_pipeline" / "calibration"

SITE_SITE_FACTOR_HOURS = list(range(8, 17))  # 8-16
SAFE_NRMSE_DELTA_THRESHOLD = 0.5  # pp
SAFE_BIAS_DELTA_THRESHOLD = 5.0  # pp


def load_quality_policy():
    p = ROOT / "configs" / "site_quality_policy.yaml"
    if p.exists():
        with open(p) as f:
            return yaml.safe_load(f)
    return {}


def rmse_fn(a, p):
    a = np.asarray(a, dtype=float)
    p = np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean((p - a) ** 2)))


def main():
    print("=" * 60)
    print("应用 Round60 保守校准器")
    print("=" * 60)

    policy = load_quality_policy()
    zero_actual_sites = set(policy.get("zero_actual_sites", []))
    print(f"[INFO] zero_actual_sites: {sorted(zero_actual_sites)}")

    # Load baseline
    baseline = pd.read_pickle(
        ROOT / "output/pv_pipeline/baselines/round58/distributed_predictions_final_full.pkl"
    )
    baseline["time"] = pd.to_datetime(baseline["time"])
    if "hour" not in baseline.columns:
        baseline["hour"] = baseline["time"].dt.hour
    print(f"[INFO] Baseline: {len(baseline)} rows, splits: {baseline['split'].value_counts().to_dict()}")

    pred_col = "power_pred_final"

    # Load calibrators
    hs_cal = pd.read_csv(CAL / "hour_scene_calibrator_conservative.csv")
    site_cal = pd.read_csv(CAL / "site_bias_calibrator_conservative.csv")

    # Build maps
    hs_map = {}
    for _, r in hs_cal.iterrows():
        _h = int(r["hour"])
        _s = str(r["scene_v151"])
        hs_map[(_h, _s)] = float(r.get("factor_final", r["factor_clipped"]))

    site_map = {}
    for _, r in site_cal.iterrows():
        site_map[str(r["station_id"])] = float(r["factor_clipped"])

    # Apply hour_scene
    print("[INFO] Applying hour_scene calibration...")
    def get_hs(row):
        return hs_map.get((int(row["hour"]), str(row["scene_v151"])), 1.0)
    baseline["hs_factor"] = baseline.apply(get_hs, axis=1)
    baseline["power_pred_round60_hour_scene"] = (
        baseline[pred_col] * baseline["hs_factor"]
    ).clip(lower=0)

    # Apply site factor (only 8-16h)
    print("[INFO] Applying site factor (8-16h only)...")
    baseline["site_factor"] = baseline["site_id"].map(site_map).fillna(1.0)
    # Zero actual sites: no site factor
    for sid in zero_actual_sites:
        baseline.loc[baseline["site_id"] == sid, "site_factor"] = 1.0

    baseline["power_pred_round60_site_conservative"] = baseline[pred_col].copy()
    mask_site = baseline["hour"].isin(SITE_SITE_FACTOR_HOURS)
    baseline.loc[mask_site, "power_pred_round60_site_conservative"] = (
        baseline.loc[mask_site, pred_col] * baseline.loc[mask_site, "site_factor"]
    )
    baseline["power_pred_round60_site_conservative"] = baseline["power_pred_round60_site_conservative"].clip(lower=0)

    # Combined: hour_scene × site (only 8-16h)
    print("[INFO] Applying combined calibration (8-16h)...")
    baseline["power_pred_round60_combined_conservative"] = baseline[pred_col].copy()
    baseline.loc[mask_site, "power_pred_round60_combined_conservative"] = (
        baseline.loc[mask_site, pred_col] *
        baseline.loc[mask_site, "hs_factor"] *
        baseline.loc[mask_site, "site_factor"]
    )
    baseline["power_pred_round60_combined_conservative"] = baseline["power_pred_round60_combined_conservative"].clip(lower=0)

    # Clip to capacity
    cap_col = "capacity_mw"
    if cap_col in baseline.columns:
        for col in ["power_pred_round60_hour_scene",
                    "power_pred_round60_site_conservative",
                    "power_pred_round60_combined_conservative"]:
            baseline[col] = baseline[col].clip(upper=baseline[cap_col])

    # ── Compute guards ────────────────────────────────────────────────
    print("\n[INFO] Computing site-level and hour-level guards on valid set...")

    df_valid = baseline[baseline["split"] == "valid"].copy()
    if len(df_valid) == 0:
        print("[WARN] No valid data, skipping guards")
        baseline["power_pred_round60_safe"] = baseline["power_pred_round60_combined_conservative"].copy()
        baseline.to_pickle(OUT / "distributed_predictions_round60_candidates.pkl")
        return

    candidates_map = {
        "round60_hour_scene": "power_pred_round60_hour_scene",
        "round60_site": "power_pred_round60_site_conservative",
        "round60_combined": "power_pred_round60_combined_conservative",
    }

    # ── Site-level guard ─────────────────────────────────────────────
    site_guard_rows = []
    site_fallback_map = {}  # site_id -> bool (True = fallback)

    for sid, sdf in df_valid.groupby("site_id"):
        sid = str(sid)
        cap_s = float(sdf["capacity_mw"].iloc[0])
        if cap_s <= 0:
            site_fallback_map[sid] = True
            continue

        base_nrmse_vals = []
        cand_nrmse_vals = {cname: [] for cname in candidates_map}

        for _, row_s in sdf.iterrows():
            a = float(row_s["power_mw"])
            p_base = float(row_s[pred_col])
            base_nrmse_vals.append((p_base - a) ** 2)
            for cname, col in candidates_map.items():
                p_c = float(row_s[col])
                cand_nrmse_vals[cname].append((p_c - a) ** 2)

        base_rmse = float(np.sqrt(np.mean(base_nrmse_vals)))
        base_nrmse = base_rmse / cap_s * 100

        for cname, vals in cand_nrmse_vals.items():
            c_rmse = float(np.sqrt(np.mean(vals)))
            c_nrmse = c_rmse / cap_s * 100
            delta = c_nrmse - base_nrmse

            a_sum = float(sdf["power_mw"].sum())
            p_base_sum = float(sdf[pred_col].sum())
            p_c_sum = float(sdf[col].sum()) if False else float(sdf[candidates_map[cname]].sum())
            bias_base = (p_base_sum - a_sum) / max(a_sum, 1e-9) * 100
            bias_c = (p_c_sum - a_sum) / max(a_sum, 1e-9) * 100
            bias_delta = abs(bias_c) - abs(bias_base)

            should_fallback = (delta > SAFE_NRMSE_DELTA_THRESHOLD) or (bias_delta > SAFE_BIAS_DELTA_THRESHOLD)

            site_guard_rows.append({
                "site_id": sid,
                "candidate": cname,
                "valid_baseline_nrmse": round(base_nrmse, 4),
                "valid_candidate_nrmse": round(c_nrmse, 4),
                "valid_delta_nrmse": round(delta, 4),
                "valid_baseline_bias": round(bias_base, 4),
                "valid_candidate_bias": round(bias_c, 4),
                "valid_delta_bias": round(bias_delta, 4),
                "fallback_applied": should_fallback,
                "fallback_reason": (
                    f"nrmse_delta={delta:.2f}pp" if delta > SAFE_NRMSE_DELTA_THRESHOLD else ""
                ) + (
                    f" bias_delta={bias_delta:.2f}pp" if bias_delta > SAFE_BIAS_DELTA_THRESHOLD else ""
                ),
            })

            if should_fallback:
                site_fallback_map[sid] = True

    site_guard_df = pd.DataFrame(site_guard_rows)
    site_guard_df.to_csv(CAL / "round60_site_level_guard.csv", index=False, encoding="utf-8-sig")
    n_fallback = site_guard_df["fallback_applied"].sum()
    print(f"[INFO] Site guard: {n_fallback}/{len(site_guard_df)} site-candidate combos fallback")

    # ── Hour-level guard ──────────────────────────────────────────────
    # Per hour: compare candidate vs baseline on valid
    HOUR_NRMSE_THRESHOLD = 0.3
    HOUR_BIAS_THRESHOLD = 3.0
    hour_guard_rows = []
    hour_fallback_map = {}  # hour -> set of candidate names

    for h in sorted(df_valid["hour"].unique()):
        hdf = df_valid[df_valid["hour"] == h]
        cap_h = float(hdf.groupby("site_id")["capacity_mw"].first().sum())
        if cap_h <= 0:
            continue

        base_nrmse_vals = []
        cand_nrmse_vals = {cname: [] for cname in candidates_map}
        a_vals = []
        p_base_vals = []
        p_cand_vals = {cname: [] for cname in candidates_map}

        for _, row_h in hdf.iterrows():
            a = float(row_h["power_mw"])
            p_base = float(row_h[pred_col])
            a_vals.append(a)
            p_base_vals.append(p_base)
            base_nrmse_vals.append((p_base - a) ** 2)
            for cname, col in candidates_map.items():
                p_c = float(row_h[col])
                p_cand_vals[cname].append(p_c)
                cand_nrmse_vals[cname].append((p_c - a) ** 2)

        base_rmse = float(np.sqrt(np.mean(base_nrmse_vals)))
        base_h_nrmse = base_rmse / cap_h * 100
        a_sum_h = float(sum(a_vals))
        p_base_sum_h = float(sum(p_base_vals))
        base_bias = (p_base_sum_h - a_sum_h) / max(a_sum_h, 1e-9) * 100

        for cname, vals in cand_nrmse_vals.items():
            c_rmse = float(np.sqrt(np.mean(vals)))
            c_h_nrmse = c_rmse / cap_h * 100
            c_bias = (float(sum(p_cand_vals[cname])) - a_sum_h) / max(a_sum_h, 1e-9) * 100

            nrmse_delta = c_h_nrmse - base_h_nrmse
            bias_delta = abs(c_bias) - abs(base_bias)
            should_fallback = (nrmse_delta > HOUR_NRMSE_THRESHOLD) or (bias_delta > HOUR_BIAS_THRESHOLD)

            hour_guard_rows.append({
                "hour": int(h),
                "candidate": cname,
                "valid_baseline_nrmse": round(base_h_nrmse, 4),
                "valid_candidate_nrmse": round(c_h_nrmse, 4),
                "valid_delta_nrmse": round(nrmse_delta, 4),
                "valid_baseline_bias": round(base_bias, 4),
                "valid_candidate_bias": round(c_bias, 4),
                "valid_delta_bias": round(bias_delta, 4),
                "fallback_applied": should_fallback,
            })

            if should_fallback:
                if h not in hour_fallback_map:
                    hour_fallback_map[h] = set()
                hour_fallback_map[h].add(cname)

    hour_guard_df = pd.DataFrame(hour_guard_rows)
    hour_guard_df.to_csv(CAL / "round60_hour_level_guard.csv", index=False, encoding="utf-8-sig")
    n_h_fallback = hour_guard_df["fallback_applied"].sum()
    print(f"[INFO] Hour guard: {n_h_fallback}/{len(hour_guard_df)} hour-candidate combos fallback")

    # ── Build safe prediction ───────────────────────────────────────────
    print("[INFO] Building safe prediction column...")

    # Default to baseline
    baseline["power_pred_round60_safe"] = baseline[pred_col].copy()

    for cname, col in candidates_map.items():
        # Apply if not fallbacked for this site or hour
        for h in sorted(df_valid["hour"].unique()):
            for sid in df_valid["site_id"].unique():
                sid = str(sid)
                h = int(h)

                # Check site guard
                site_key = (sid, cname)
                sg_rows = site_guard_df[
                    (site_guard_df["site_id"] == sid) & (site_guard_df["candidate"] == cname)
                ]
                site_fallback = False
                if len(sg_rows) > 0:
                    site_fallback = bool(sg_rows.iloc[0]["fallback_applied"])

                # Check hour guard
                hg_rows = hour_guard_df[
                    (hour_guard_df["hour"] == h) & (hour_guard_df["candidate"] == cname)
                ]
                hour_fallback = False
                if len(hg_rows) > 0:
                    hour_fallback = bool(hg_rows.iloc[0]["fallback_applied"])

                # If both guards pass, apply this candidate
                if not site_fallback and not hour_fallback:
                    mask = (baseline["site_id"] == sid) & (baseline["hour"] == h)
                    baseline.loc[mask, "power_pred_round60_safe"] = baseline.loc[mask, col]

    # Clip to capacity
    if cap_col in baseline.columns:
        baseline["power_pred_round60_safe"] = baseline["power_pred_round60_safe"].clip(
            lower=0, upper=baseline[cap_col]
        )

    # Save
    out_path = OUT / "distributed_predictions_round60_candidates.pkl"
    baseline.to_pickle(out_path)
    print(f"[OK] {out_path}")
    print(f"[INFO] Columns: {list(baseline.columns)}")

    # Summary
    print("\n[INFO] Guard summary:")
    print(f"  Site fallback: {n_fallback}/{len(site_guard_df)}")
    print(f"  Hour fallback: {n_h_fallback}/{len(hour_guard_df)}")


if __name__ == "__main__":
    main()
