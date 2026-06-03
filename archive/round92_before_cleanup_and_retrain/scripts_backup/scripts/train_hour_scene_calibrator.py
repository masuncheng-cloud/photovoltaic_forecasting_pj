#!/usr/bin/env python3
"""
train_hour_scene_calibrator.py
=============================
基于 (hour, scene_v151) 的全局校准器。

使用 train + valid 6-19 点数据学习校准因子：
  factor = sum(actual) / sum(pred)

对样本量不足的组，使用 shrinkage 收缩到全局均值。

约束：
  factor_min = 0.75
  factor_max = 1.35
  min_samples = 100
  shrinkage_k = 500

应用时：
  pred_calibrated = pred * factor

输出：
  output/pv_pipeline/calibration/hour_scene_calibrator.csv
"""

from pathlib import Path
import yaml
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline" / "calibration"
OUT.mkdir(parents=True, exist_ok=True)

FACTOR_MIN = 0.75
FACTOR_MAX = 1.35
MIN_SAMPLES = 100
SHRINKAGE_K = 500


def load_quality_policy():
    policy_path = ROOT / "configs" / "site_quality_policy.yaml"
    if policy_path.exists():
        with open(policy_path) as f:
            return yaml.safe_load(f)
    return {}


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    if len(a) == 0:
        return np.nan
    return float(np.sqrt(np.mean((p - a) ** 2)))


def nrmse(a, p, den):
    den = float(den)
    if den <= 0:
        return np.nan
    return rmse(a, p) / den * 100


def main():
    print("=" * 60)
    print("hour × scene 全局校准器训练")
    print(f"约束: factor=[{FACTOR_MIN}, {FACTOR_MAX}], min_samples={MIN_SAMPLES}, k={SHRINKAGE_K}")
    print("=" * 60)

    policy = load_quality_policy()
    exclude_sites = set(policy.get("model_training_exclude_sites", []))
    print(f"[INFO] model_training_exclude_sites: {sorted(exclude_sites)}")

    # Load calibration dataset
    train_valid_path = OUT / "calibration_train_valid.pkl"
    if not train_valid_path.exists():
        raise FileNotFoundError(f"calibration_train_valid.pkl not found. Run build_calibration_dataset.py first.")
    df = pd.read_pickle(train_valid_path)
    print(f"[INFO] Loaded calibration data: {len(df)} rows, {df['site_id'].nunique()} sites")

    pred_col = "power_pred_final"
    scene_col = "scene_v151"

    # Compute global factor (used for shrinkage)
    actual_total = float(df["power_mw"].sum())
    pred_total = float(df[pred_col].sum())
    global_factor = actual_total / max(pred_total, 1e-9)
    print(f"[INFO] Global factor (train+valid): {global_factor:.4f}")

    # Also compute per-split global factors
    global_train = float(
        df[df["split"] == "train"]["power_mw"].sum()
    ) / max(
        float(df[df["split"] == "train"][pred_col].sum()), 1e-9
    )
    global_valid = float(
        df[df["split"] == "valid"]["power_mw"].sum()
    ) / max(
        float(df[df["split"] == "valid"][pred_col].sum()), 1e-9
    )
    print(f"[INFO] Global factor train: {global_train:.4f}, valid: {global_valid:.4f}")

    # Also compute per-scene global factors for night/misclassified handling
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

        # Shrinkage toward global_factor
        # For night scene, shrink toward scene-specific global factor
        if scene == "night":
            gf = scene_global_factors.get("night", global_factor)
        elif scene == "low":
            gf = scene_global_factors.get("low", global_factor)
        elif scene == "mid":
            gf = scene_global_factors.get("mid", global_factor)
        elif scene == "clear_peak":
            gf = scene_global_factors.get("clear_peak", global_factor)
        else:
            gf = global_factor

        weight = n / (n + SHRINKAGE_K)
        final_factor = weight * raw_factor + (1 - weight) * gf

        # Clip
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
    print(f"[INFO] Calibrator rows: {len(calibrator)}")
    print(calibrator.to_string(index=False))

    # Evaluate on valid set (before/after)
    print("\n[INFO] Valid set evaluation...")
    df_valid = df[df["split"] == "valid"].copy()
    cap_total = float(df_valid.groupby("site_id")["capacity_mw"].first().sum())

    # Apply calibrator
    cal_map = {}
    for _, r in calibrator.iterrows():
        k = (int(r["hour"]), str(r["scene_v151"]))
        cal_map[k] = r["factor_clipped"]

    def _get_factor(row):
        return cal_map.get((int(row["hour"]), str(row[scene_col])), 1.0)
    df_valid["hs_factor"] = df_valid.apply(_get_factor, axis=1)
    df_valid["pred_hs"] = df_valid[pred_col] * df_valid["hs_factor"]
    df_valid["pred_hs"] = df_valid["pred_hs"].clip(lower=0)

    # Before NRMSE
    before_nrmse = nrmse(
        df_valid["power_mw"].values,
        df_valid[pred_col].values,
        cap_total,
    )

    # After NRMSE
    after_nrmse = nrmse(
        df_valid["power_mw"].values,
        df_valid["pred_hs"].values,
        cap_total,
    )

    # Bias
    actual_sum = float(df_valid["power_mw"].sum())
    pred_before_sum = float(df_valid[pred_col].sum())
    pred_after_sum = float(df_valid["pred_hs"].sum())
    bias_before = (pred_before_sum - actual_sum) / max(actual_sum, 1e-9) * 100
    bias_after = (pred_after_sum - actual_sum) / max(actual_sum, 1e-9) * 100

    print(f"[INFO] Valid city NRMSE: before={before_nrmse:.4f}%, after={after_nrmse:.4f}%, delta={after_nrmse - before_nrmse:+.4f}%")
    print(f"[INFO] Valid bias%: before={bias_before:.4f}%, after={bias_after:+.4f}%")

    # Per-hour before/after
    print("\n[INFO] Per-hour valid improvement:")
    hour_comparison = []
    for hour in sorted(df_valid["hour"].unique()):
        hdf = df_valid[df_valid["hour"] == hour]
        h_cap = float(hdf.groupby("site_id")["capacity_mw"].first().sum())
        h_actual = hdf["power_mw"].sum()
        h_pred_before = hdf[pred_col].sum()
        h_pred_after = hdf["pred_hs"].sum()
        h_nrmse_before = nrmse(hdf["power_mw"].values, hdf[pred_col].values, h_cap)
        h_nrmse_after = nrmse(hdf["power_mw"].values, hdf["pred_hs"].values, h_cap)
        h_bias_before = (h_pred_before - h_actual) / max(h_actual, 1e-9) * 100
        h_bias_after = (h_pred_after - h_actual) / max(h_actual, 1e-9) * 100
        print(f"  Hour {int(hour):02d}: NRMSE {h_nrmse_before:.2f}% -> {h_nrmse_after:.2f}% (delta={h_nrmse_after-h_nrmse_before:+.2f}%), "
              f"bias {h_bias_before:.1f}% -> {h_bias_after:.1f}%")
        hour_comparison.append({
            "hour": int(hour),
            "valid_nrmse_before": round(h_nrmse_before, 4),
            "valid_nrmse_after": round(h_nrmse_after, 4),
            "valid_nrmse_delta": round(h_nrmse_after - h_nrmse_before, 4),
            "valid_bias_before": round(h_bias_before, 4),
            "valid_bias_after": round(h_bias_after, 4),
        })

    # If valid NRMSE gets worse, warn
    if after_nrmse > before_nrmse + 0.5:
        print(f"\n[WARN] Valid NRMSE worsened by {after_nrmse - before_nrmse:.2f}%. Consider not applying hour_scene calibration.")
    else:
        print(f"\n[OK] Valid NRMSE improved or stable.")

    # Save calibrator
    out_path = OUT / "hour_scene_calibrator.csv"
    calibrator.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] hour_scene_calibrator.csv → {out_path}")

    # Save hour comparison
    if hour_comparison:
        pd.DataFrame(hour_comparison).to_csv(
            OUT / "hour_scene_calibrator_valid_eval.csv", index=False, encoding="utf-8-sig"
        )

    print(f"\n{'='*60}")
    print(f"SUMMARY: global_factor={global_factor:.4f}")
    print(f"Valid NRMSE: {before_nrmse:.4f}% -> {after_nrmse:.4f}% (delta={after_nrmse-before_nrmse:+.4f}%)")
    print(f"Valid Bias%: {bias_before:.4f}% -> {bias_after:.4f}% (delta={bias_after-bias_before:+.4f}%)")


if __name__ == "__main__":
    main()
