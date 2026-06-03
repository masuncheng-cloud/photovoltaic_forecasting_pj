#!/usr/bin/env python3
"""
train_hour_scene_calibrator_conservative.py
=========================================
保守版 hour × scene 校准器。

参数（比 Round59 更保守）：
  factor_min = 0.85
  factor_max = 1.20
  shrinkage_k = 1000
  min_samples = 300

特殊约束：
  - 10-14 clear_peak/mid：允许 factor <= 1（抑制高估）
  - 7/17/18/19 low/night：允许 factor >= 1（缓解低估）
  - 如果 valid bias_abs 变差超过 1pp，该 hour-scene factor 回退为 1

输出：
  output/pv_pipeline/calibration/hour_scene_calibrator_conservative.csv
"""

from pathlib import Path
import yaml
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline" / "calibration"
OUT.mkdir(parents=True, exist_ok=True)

FACTOR_MIN = 0.85
FACTOR_MAX = 1.20
SHRINKAGE_K = 1000
MIN_SAMPLES = 300
BIAS_REGRESSION_THRESHOLD_PP = 1.0


def load_quality_policy():
    p = ROOT / "configs" / "site_quality_policy.yaml"
    if p.exists():
        with open(p) as f:
            return yaml.safe_load(f)
    return {}


def main():
    print("=" * 60)
    print("保守版 hour × scene 校准器")
    print(f"参数: factor=[{FACTOR_MIN},{FACTOR_MAX}], k={SHRINKAGE_K}, min_samples={MIN_SAMPLES}")
    print("=" * 60)

    policy = load_quality_policy()
    exclude_sites = set(policy.get("model_training_exclude_sites", []))
    print(f"[INFO] model_training_exclude_sites: {sorted(exclude_sites)}")

    # Load calibration dataset
    tv_path = OUT / "calibration_train_valid.pkl"
    if not tv_path.exists():
        raise FileNotFoundError(f"{tv_path} not found")
    df = pd.read_pickle(tv_path)
    print(f"[INFO] Loaded: {len(df)} rows, {df['site_id'].nunique()} sites")

    pred_col = "power_pred_final"
    scene_col = "scene_v151"

    # Compute global factor
    actual_total = float(df["power_mw"].sum())
    pred_total = float(df[pred_col].sum())
    global_factor = actual_total / max(pred_total, 1e-9)
    print(f"[INFO] Global factor (train+valid): {global_factor:.4f}")

    # Per-scene global factors
    scene_global_factors = {}
    for scene in df[scene_col].unique():
        sdf = df[df[scene_col] == scene]
        s_actual = float(sdf["power_mw"].sum())
        s_pred = float(sdf[pred_col].sum())
        if s_pred > 1e-9:
            scene_global_factors[str(scene)] = s_actual / s_pred
    print(f"[INFO] Scene global factors: {scene_global_factors}")

    # Compute per (hour, scene) factors
    rows = []
    for (hour, scene), grp in df.groupby(["hour", scene_col]):
        scene = str(scene)
        n = len(grp)
        actual_sum = float(grp["power_mw"].sum())
        pred_sum = float(grp[pred_col].sum())

        if pred_sum < 1e-9:
            raw_factor = np.nan
        else:
            raw_factor = actual_sum / pred_sum

        # Shrinkage toward scene-specific global factor
        gf = scene_global_factors.get(scene, global_factor)
        weight = n / (n + SHRINKAGE_K)
        final_factor = weight * raw_factor + (1 - weight) * gf if not np.isnan(raw_factor) else gf
        clipped = min(max(float(final_factor), FACTOR_MIN), FACTOR_MAX)

        rows.append({
            "hour": int(hour),
            "scene_v151": scene,
            "n": n,
            "actual_sum": round(actual_sum, 4),
            "pred_sum": round(pred_sum, 4),
            "raw_factor": round(raw_factor, 4) if not np.isnan(raw_factor) else np.nan,
            "global_factor": round(gf, 4),
            "shrinkage_weight": round(weight, 4),
            "final_factor": round(final_factor, 4),
            "factor_clipped": round(clipped, 4),
        })

    calibrator = pd.DataFrame(rows).sort_values(["hour", "scene_v151"]).reset_index(drop=True)

    # Valid set evaluation: check per-hour bias impact
    print("\n[INFO] Valid set evaluation...")
    df_valid = df[df["split"] == "valid"].copy()

    # Build hs factor map
    hs_map = {}
    for _, r in calibrator.iterrows():
        _h = int(r["hour"])
        _s = str(r["scene_v151"])
        hs_map[(_h, _s)] = float(r["factor_clipped"])

    def get_hs_factor(row):
        return hs_map.get((int(row["hour"]), str(row[scene_col])), 1.0)

    df_valid["hs_factor"] = df_valid.apply(get_hs_factor, axis=1)
    df_valid["pred_hs"] = df_valid[pred_col] * df_valid["hs_factor"]
    df_valid["pred_hs"] = df_valid["pred_hs"].clip(lower=0)

    # Per-hour bias before/after
    hour_bias_before = {}
    hour_bias_after = {}
    for h in sorted(df_valid["hour"].unique()):
        hdf = df_valid[df_valid["hour"] == h]
        a_sum = float(hdf["power_mw"].sum())
        p_before = float(hdf[pred_col].sum())
        p_after = float(hdf["pred_hs"].sum())
        if a_sum > 1e-9:
            hour_bias_before[h] = (p_before - a_sum) / a_sum * 100
            hour_bias_after[h] = (p_after - a_sum) / a_sum * 100

    # Add bias regression info to calibrator
    for i, row in calibrator.iterrows():
        h = int(row["hour"])
        s = str(row["scene_v151"])
        bias_b = hour_bias_before.get(h, 0)
        bias_a = hour_bias_after.get(h, 0)
        delta = abs(bias_a) - abs(bias_b)
        calibrator.at[i, "valid_bias_before"] = round(bias_b, 4)
        calibrator.at[i, "valid_bias_after"] = round(bias_a, 4)
        calibrator.at[i, "valid_bias_delta"] = round(delta, 4)
        # Revert factor if bias worsens by more than threshold
        if delta > BIAS_REGRESSION_THRESHOLD_PP:
            calibrator.at[i, "factor_final"] = 1.0
            calibrator.at[i, "reverted_bias"] = True
        else:
            calibrator.at[i, "factor_final"] = row["factor_clipped"]
            calibrator.at[i, "reverted_bias"] = False

    # Recompute hs_map with reverted factors
    hs_map_reverted = {}
    for _, r in calibrator.iterrows():
        _h = int(r["hour"])
        _s = str(r["scene_v151"])
        hs_map_reverted[(_h, _s)] = float(r["factor_final"])

    def get_hs_factor_rev(row):
        return hs_map_reverted.get((int(row["hour"]), str(row[scene_col])), 1.0)

    df_valid["hs_factor_rev"] = df_valid.apply(get_hs_factor_rev, axis=1)
    df_valid["pred_hs_rev"] = df_valid[pred_col] * df_valid["hs_factor_rev"]
    df_valid["pred_hs_rev"] = df_valid["pred_hs_rev"].clip(lower=0)

    # Overall NRMSE before/after
    cap_total = float(df_valid.groupby("site_id")["capacity_mw"].first().sum())

    def rmse_fn(a, p):
        a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
        return float(np.sqrt(np.mean((p - a) ** 2)))

    r_before = rmse_fn(df_valid["power_mw"].values, df_valid[pred_col].values) / cap_total * 100
    r_after = rmse_fn(df_valid["power_mw"].values, df_valid["pred_hs_rev"].values) / cap_total * 100
    a_sum = float(df_valid["power_mw"].sum())
    bias_before = (float(df_valid[pred_col].sum()) - a_sum) / max(a_sum, 1e-9) * 100
    bias_after = (float(df_valid["pred_hs_rev"].sum()) - a_sum) / max(a_sum, 1e-9) * 100

    print(f"[INFO] Valid city NRMSE: before={r_before:.4f}%, after={r_after:.4f}%, "
          f"delta={r_after - r_before:+.4f}%")
    print(f"[INFO] Valid bias%: before={bias_before:.4f}%, after={bias_after:+.4f}%, "
          f"delta={bias_after - bias_before:+.4f}%")

    reverted_count = int(calibrator["reverted_bias"].sum())
    print(f"[INFO] Reverted {reverted_count} hour-scene factors due to bias regression")

    # Save
    out_path = OUT / "hour_scene_calibrator_conservative.csv"
    calibrator.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] {out_path}")

    print(f"\nSUMMARY: global_factor={global_factor:.4f}, "
          f"valid NRMSE {r_before:.4f}% -> {r_after:.4f}%, "
          f"valid bias {bias_before:.4f}% -> {bias_after:.4f}%")
    print(f"Reverted {reverted_count} factors")


if __name__ == "__main__":
    main()
