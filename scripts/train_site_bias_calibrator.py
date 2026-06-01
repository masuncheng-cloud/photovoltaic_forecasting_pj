#!/usr/bin/env python3
"""
train_site_bias_calibrator.py
============================
基于站点的 shrinkage 校准器。

使用 train+valid 6-19 点数据学习每个站点的校准因子：
  site_factor = sum(actual) / sum(pred)

约束：
  factor_min = 0.70
  factor_max = 1.40
  min_samples = 300
  shrinkage_k = 1000

收缩到容量分组均值（small/medium/large）。

对 zero_actual_sites 不学习 site factor（从 hour_scene calibrator 获取因子）。

输出：
  output/pv_pipeline/calibration/site_bias_calibrator.csv
"""

from pathlib import Path
import yaml
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline" / "calibration"
OUT.mkdir(parents=True, exist_ok=True)

FACTOR_MIN = 0.70
FACTOR_MAX = 1.40
MIN_SAMPLES = 300
SHRINKAGE_K = 1000


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


def nrmse_fn(a, p, den):
    den = float(den)
    if den <= 0:
        return np.nan
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean((p - a) ** 2))) / den * 100


def main():
    print("=" * 60)
    print("站点 shrinkage 校准器训练")
    print(f"约束: factor=[{FACTOR_MIN}, {FACTOR_MAX}], min_samples={MIN_SAMPLES}, k={SHRINKAGE_K}")
    print("=" * 60)

    policy = load_quality_policy()
    exclude_sites = set(policy.get("calibration_exclude_sites", []))
    low_conf_sites = set(policy.get("low_confidence_geo_sites", []))
    print(f"[INFO] calibration_exclude_sites: {sorted(exclude_sites)}")
    print(f"[INFO] low_confidence_geo_sites: {sorted(low_conf_sites)}")

    # Load calibration dataset
    tv_path = OUT / "calibration_train_valid.pkl"
    if not tv_path.exists():
        raise FileNotFoundError("calibration_train_valid.pkl not found. Run build_calibration_dataset.py first.")
    df = pd.read_pickle(tv_path)
    print(f"[INFO] Loaded: {len(df)} rows, {df['site_id'].nunique()} sites")

    pred_col = "power_pred_final"

    # Compute group factors first
    site_caps = df.groupby("site_id")["capacity_mw"].first()
    df["cap_bucket"] = df["site_id"].map(lambda sid: capacity_bucket(float(site_caps.get(sid, 5.0))))
    group_stats = {}
    for bucket in ["small", "medium", "large"]:
        bdf = df[df["cap_bucket"] == bucket]
        if len(bdf) == 0:
            group_stats[bucket] = 1.0
            continue
        a_sum = float(bdf["power_mw"].sum())
        p_sum = float(bdf[pred_col].sum())
        group_stats[bucket] = a_sum / max(p_sum, 1e-9)
    print(f"[INFO] Group factors: {group_stats}")

    # Per-site computation
    rows = []
    for sid, sdf in df.groupby("site_id"):
        sid = str(sid)
        n = len(sdf)
        cap = float(sdf["capacity_mw"].mean())
        actual_sum = float(sdf["power_mw"].sum())
        pred_sum = float(sdf[pred_col].sum())
        bucket = capacity_bucket(cap)

        if pred_sum < 1e-9:
            raw_factor = np.nan
        else:
            raw_factor = actual_sum / pred_sum

        # Check exclusions
        is_excluded = sid in exclude_sites
        is_low_conf = sid in low_conf_sites

        if is_excluded:
            # zero_actual_sites: don't train site factor
            final_factor = 1.0
            status = "excluded_zero_actual"
        else:
            # Shrinkage toward group factor
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
            "final_factor": round(final_factor, 4),
            "factor_clipped": round(clipped, 4),
            "is_low_confidence_geo": is_low_conf,
            "status": status,
        })

    calibrator = pd.DataFrame(rows).sort_values("station_id").reset_index(drop=True)
    print(f"\n[INFO] Site calibrator: {len(calibrator)} sites")
    excluded = calibrator[calibrator["status"] == "excluded_zero_actual"]
    print(f"[INFO] Excluded (zero_actual): {len(excluded)} sites")
    low_conf = calibrator[calibrator["is_low_confidence_geo"]]
    print(f"[INFO] Low confidence geo: {len(low_conf)} sites: {list(low_conf['station_id'])}")

    # Evaluate on valid set
    print("\n[INFO] Valid set evaluation...")
    df_valid = df[df["split"] == "valid"].copy()

    # Build site factor map
    site_factor_map = {}
    for _, r in calibrator.iterrows():
        site_factor_map[str(r["station_id"])] = r["factor_clipped"]

    # Load hour_scene calibrator
    hs_path = OUT / "hour_scene_calibrator.csv"
    if hs_path.exists():
        hs_cal = pd.read_csv(hs_path)
        hs_map = {}
        for _, r in hs_cal.iterrows():
            k = (int(r["hour"]), str(r["scene_v151"]))
            hs_map[k] = float(r["factor_clipped"])
    else:
        hs_map = {}

    scene_col = "scene_v151"

    def get_hs_factor(row):
        return hs_map.get((int(row["hour"]), str(row[scene_col])), 1.0)

    # Apply calibrators
    df_valid["site_factor"] = df_valid["site_id"].map(site_factor_map).fillna(1.0)
    df_valid["hs_factor"] = df_valid.apply(get_hs_factor, axis=1)
    df_valid["pred_combined"] = (
        df_valid[pred_col] * df_valid["hs_factor"] * df_valid["site_factor"]
    ).clip(lower=0)

    # City-level eval
    cap_total = float(df_valid.groupby("site_id")["capacity_mw"].first().sum())
    a = df_valid["power_mw"].values
    p_before = df_valid[pred_col].values
    p_after = df_valid["pred_combined"].values

    nrmse_before = nrmse_fn(a, p_before, cap_total)
    nrmse_after = nrmse_fn(a, p_after, cap_total)

    a_sum = float(df_valid["power_mw"].sum())
    bias_before = (float(p_before.sum()) - a_sum) / max(a_sum, 1e-9) * 100
    bias_after = (float(p_after.sum()) - a_sum) / max(a_sum, 1e-9) * 100

    print(f"[INFO] Valid city NRMSE: before={nrmse_before:.4f}%, after={nrmse_after:.4f}%, "
          f"delta={nrmse_after - nrmse_before:+.4f}%")
    print(f"[INFO] Valid bias%: before={bias_before:.4f}%, after={bias_after:+.4f}%, "
          f"delta={bias_after - bias_before:+.4f}%")

    # Per-site eval
    site_improvement = []
    for sid, sdf in df_valid.groupby("site_id"):
        sid = str(sid)
        cap_s = float(sdf["capacity_mw"].mean())
        a_s = sdf["power_mw"].values
        p_b = sdf[pred_col].values
        p_a = sdf["pred_combined"].values
        nrmse_b = nrmse_fn(a_s, p_b, cap_s)
        nrmse_a = nrmse_fn(a_s, p_a, cap_s)
        delta = nrmse_a - nrmse_b
        site_improvement.append({
            "station_id": sid,
            "nrmse_before": round(nrmse_b, 4),
            "nrmse_after": round(nrmse_a, 4),
            "delta": round(delta, 4),
            "factor": site_factor_map.get(sid, 1.0),
        })

    site_eval_df = pd.DataFrame(site_improvement)
    site_eval_df.to_csv(OUT / "site_bias_calibrator_valid_eval.csv", index=False, encoding="utf-8-sig")

    improved = int((site_eval_df["delta"] < -0.1).sum())
    worsened = int((site_eval_df["delta"] > 0.1).sum())
    print(f"[INFO] Sites improved (>0.1%): {improved}, worsened: {worsened}")
    print(f"[INFO] Worst worsened sites:")
    worst = site_eval_df.sort_values("delta", ascending=False).head(5)
    print(worst[["station_id", "nrmse_before", "nrmse_after", "delta"]].to_string(index=False))

    # Add valid eval to calibrator
    cal_with_eval = calibrator.merge(
        site_eval_df[["station_id", "nrmse_before", "nrmse_after", "delta"]],
        left_on="station_id", right_on="station_id", how="left"
    )

    # Save
    out_path = OUT / "site_bias_calibrator.csv"
    cal_with_eval.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] site_bias_calibrator.csv → {out_path}")

    print(f"\n{'='*60}")
    print(f"SUMMARY: valid NRMSE {nrmse_before:.4f}% -> {nrmse_after:.4f}% "
          f"(delta={nrmse_after-nrmse_before:+.4f}%)")
    print(f"valid bias {bias_before:.4f}% -> {bias_after:.4f}%")


if __name__ == "__main__":
    main()
