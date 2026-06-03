#!/usr/bin/env python3
"""
train_site_bias_calibrator_conservative.py
========================================
保守版站点 shrinkage 校准器。

参数（比 Round59 更保守）：
  shrinkage_k = 3000
  factor_min = 0.85
  factor_max = 1.20
  min_samples = 500
  min_positive_actual_sum = 20

仅在 8-16 点应用 site factor（排除 6,7,17,18,19 低光时段）。

输出：
  output/pv_pipeline/calibration/site_bias_calibrator_conservative.csv
"""

from pathlib import Path
import yaml
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline" / "calibration"
OUT.mkdir(parents=True, exist_ok=True)

# Conservative parameters
SHRINKAGE_K = 3000
FACTOR_MIN = 0.85
FACTOR_MAX = 1.20
MIN_SAMPLES = 500
MIN_ACTUAL_SUM = 20.0
APPLY_HOURS = list(range(8, 17))  # 8-16 inclusive


def load_quality_policy():
    p = ROOT / "configs" / "site_quality_policy.yaml"
    if p.exists():
        with open(p) as f:
            return yaml.safe_load(f)
    return {}


def capacity_bucket(cap_mw):
    if cap_mw < 3.0:
        return "small"
    elif cap_mw < 10.0:
        return "medium"
    else:
        return "large"


def rmse_fn(a, p):
    a = np.asarray(a, dtype=float)
    p = np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean((p - a) ** 2)))


def main():
    print("=" * 60)
    print("保守版站点 shrinkage 校准器")
    print(f"参数: k={SHRINKAGE_K}, factor=[{FACTOR_MIN},{FACTOR_MAX}], "
          f"min_samples={MIN_SAMPLES}, apply_hours={APPLY_HOURS}")
    print("=" * 60)

    policy = load_quality_policy()
    exclude_sites = set(policy.get("calibration_exclude_sites", []))
    print(f"[INFO] calibration_exclude_sites: {sorted(exclude_sites)}")

    # Load calibration dataset
    tv_path = OUT / "calibration_train_valid.pkl"
    if not tv_path.exists():
        raise FileNotFoundError(f"{tv_path} not found")
    df = pd.read_pickle(tv_path)
    print(f"[INFO] Loaded: {len(df)} rows, {df['site_id'].nunique()} sites")

    # Use only 8-16 hours for site calibrator training
    df_use = df[df["hour"].isin(APPLY_HOURS)].copy()
    print(f"[INFO] Filtered to 8-16h: {len(df_use)} rows")

    pred_col = "power_pred_final"

    # Compute group factors (using 8-16 data)
    site_caps = {}
    for sid in df_use["site_id"].unique():
        cap = float(df_use[df_use["site_id"] == sid]["capacity_mw"].iloc[0])
        site_caps[str(sid)] = cap

    bucket_map = {}
    for sid, cap in site_caps.items():
        bucket_map[sid] = capacity_bucket(cap)

    group_stats = {}
    for bucket in ["small", "medium", "large"]:
        bdf = df_use[df_use["site_id"].apply(lambda s: bucket_map.get(str(s), "medium") == bucket)]
        if len(bdf) == 0:
            group_stats[bucket] = 1.0
            continue
        a_sum = float(bdf["power_mw"].sum())
        p_sum = float(bdf[pred_col].sum())
        group_stats[bucket] = a_sum / max(p_sum, 1e-9)
    print(f"[INFO] Group factors: {group_stats}")

    # Per-site computation
    rows = []
    for sid, sdf in df_use.groupby("site_id"):
        sid = str(sid)
        n = len(sdf)
        cap = float(sdf["capacity_mw"].mean())
        actual_sum = float(sdf["power_mw"].sum())
        pred_sum = float(sdf[pred_col].sum())
        bucket = bucket_map.get(sid, "medium")

        if pred_sum < 1e-9 or actual_sum < MIN_ACTUAL_SUM:
            raw_factor = np.nan
        else:
            raw_factor = actual_sum / pred_sum

        is_excluded = sid in exclude_sites

        if is_excluded:
            final_factor = 1.0
            status = "excluded_zero_actual"
        else:
            gf = group_stats.get(bucket, 1.0)
            weight = n / (n + SHRINKAGE_K)
            if np.isnan(raw_factor):
                final_factor = gf
                status = "used_group_factor"
            else:
                final_factor = weight * raw_factor + (1 - weight) * gf
                status = "ok"

        clipped = min(max(float(final_factor), FACTOR_MIN), FACTOR_MAX)

        rows.append({
            "station_id": sid,
            "capacity_mw": round(cap, 4),
            "capacity_bucket": bucket,
            "n": n,
            "actual_sum": round(actual_sum, 4),
            "pred_sum": round(pred_sum, 4),
            "raw_factor": round(raw_factor, 4) if not np.isnan(raw_factor) else np.nan,
            "group_factor": round(group_stats.get(bucket, 1.0), 4),
            "shrinkage_weight": round(n / (n + SHRINKAGE_K), 4),
            "final_factor": round(final_factor, 4),
            "factor_clipped": round(clipped, 4),
            "status": status,
            "apply_hours": f"{APPLY_HOURS[0]}-{APPLY_HOURS[-1]}",
        })

    calibrator = pd.DataFrame(rows).sort_values("station_id").reset_index(drop=True)
    print(f"\n[INFO] Sites: {len(calibrator)}")
    excluded = calibrator[calibrator["status"] == "excluded_zero_actual"]
    print(f"[INFO] Excluded: {len(excluded)} sites: {list(excluded['station_id'])}")

    # Evaluate on valid set
    print("\n[INFO] Valid set evaluation (8-16h)...")
    df_valid = df[df["split"] == "valid"].copy()
    df_valid_8_16 = df_valid[df_valid["hour"].isin(APPLY_HOURS)].copy()
    df_valid_all = df_valid.copy()

    site_factor_map = {}
    for _, r in calibrator.iterrows():
        site_factor_map[str(r["station_id"])] = float(r["factor_clipped"])

    def eval_site_nrmse(df_sub, factor_col, base_pred_col):
        vals = []
        for sid, sdf in df_sub.groupby("site_id"):
            cap_s = float(sdf["capacity_mw"].iloc[0])
            if cap_s <= 0:
                continue
            a = sdf["power_mw"].values
            p = sdf[factor_col].values
            r = rmse_fn(a, p) / cap_s * 100
            vals.append(r)
        return float(np.mean(vals)) if vals else np.nan

    def apply_site_factor(df_sub, base_col):
        df_out = df_sub.copy()
        df_out["pred_site"] = df_out[base_col] * df_out["site_id"].map(
            lambda s: site_factor_map.get(str(s), 1.0)
        ).fillna(1.0)
        return df_out

    # Baseline on valid 8-16h
    valid_base = df_valid_8_16.copy()
    base_nrmse = eval_site_nrmse(valid_base, pred_col, pred_col)

    # After site calibrator
    valid_after = apply_site_factor(df_valid_8_16, pred_col)
    after_nrmse = eval_site_nrmse(valid_after, "pred_site", pred_col)

    # Bias
    a_sum = float(df_valid_8_16["power_mw"].sum())
    p_before = float(df_valid_8_16[pred_col].sum())
    p_after = float(valid_after["pred_site"].sum())
    bias_before = (p_before - a_sum) / max(a_sum, 1e-9) * 100
    bias_after = (p_after - a_sum) / max(a_sum, 1e-9) * 100

    print(f"[INFO] Valid 8-16h site_mean_nrmse: {base_nrmse:.4f}% -> {after_nrmse:.4f}% "
          f"(delta={after_nrmse - base_nrmse:+.4f}%)")
    print(f"[INFO] Valid 8-16h bias%: {bias_before:.4f}% -> {bias_after:.4f}% "
          f"(delta={bias_after - bias_before:+.4f}%)")

    # Save
    out_path = OUT / "site_bias_calibrator_conservative.csv"
    calibrator.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] {out_path}")
    print(f"\nSUMMARY: valid 8-16h nrmse {base_nrmse:.4f}% -> {after_nrmse:.4f}%, "
          f"bias {bias_before:.4f}% -> {bias_after:.4f}%")


if __name__ == "__main__":
    main()
