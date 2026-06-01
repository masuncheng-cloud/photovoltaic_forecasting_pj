#!/usr/bin/env python3
"""
apply_round59_calibration.py
=============================
读取 Round58 baseline predictions，应用 hour_scene 和 site 校准器，
生成候选预测列，写入 candidates pkl。

候选列：
  power_pred_round59_hour_scene  - 只用 hour×scene 校准
  power_pred_round59_site        - 只用 site 校准（从 hour_scene 后）
  power_pred_round59_combined    - hour_scene + site 组合

对于 zero_actual_sites：
  不应用 site factor，只用 hour_scene factor

输出：
  output/pv_pipeline/predictions/distributed_predictions_round59_candidates.pkl
"""

from pathlib import Path
import yaml
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline" / "predictions"
OUT.mkdir(parents=True, exist_ok=True)


def load_quality_policy():
    p = ROOT / "configs" / "site_quality_policy.yaml"
    if p.exists():
        with open(p) as f:
            return yaml.safe_load(f)
    return {}


def main():
    print("=" * 60)
    print("应用 Round59 校准器")
    print("=" * 60)

    policy = load_quality_policy()
    zero_actual_sites = set(policy.get("zero_actual_sites", []))
    exclude_sites = set(policy.get("calibration_exclude_sites", []))
    print(f"[INFO] zero_actual_sites: {sorted(zero_actual_sites)}")
    print(f"[INFO] calibration_exclude_sites: {sorted(exclude_sites)}")

    # Load baseline
    baseline_path = ROOT / "output/pv_pipeline/baselines/round58/distributed_predictions_final_full.pkl"
    print(f"[INFO] Loading baseline: {baseline_path}")
    df = pd.read_pickle(baseline_path)
    print(f"[INFO] Baseline: {len(df)} rows, splits: {df['split'].value_counts().to_dict()}")

    pred_col = "power_pred_final"

    # Normalize time
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    if "scene_v151" not in df.columns:
        raise KeyError("scene_v151 not in df")

    # Load calibrators
    cal_dir = ROOT / "output/pv_pipeline/calibration"
    hs_path = cal_dir / "hour_scene_calibrator.csv"
    site_path = cal_dir / "site_bias_calibrator.csv"

    if not hs_path.exists():
        raise FileNotFoundError(f"{hs_path} not found")
    if not site_path.exists():
        raise FileNotFoundError(f"{site_path} not found")

    hs_cal = pd.read_csv(hs_path)
    site_cal = pd.read_csv(site_path)
    print(f"[INFO] Loaded hour_scene calibrator: {len(hs_cal)} rows")
    print(f"[INFO] Loaded site calibrator: {len(site_cal)} rows")

    # Build hour_scene factor map
    hs_map = {}
    for _, r in hs_cal.iterrows():
        h = int(r["hour"])
        s = str(r["scene_v151"])
        v = float(r["factor_clipped"])
        hs_map[(h, s)] = v

    # Build site factor map
    site_map = {}
    for _, r in site_cal.iterrows():
        sid = str(r["station_id"])
        site_map[sid] = float(r["factor_clipped"])

    # Apply hour_scene calibration
    print("[INFO] Applying hour_scene calibration...")
    def get_hs_factor(row):
        k = (int(row["hour"]), str(row["scene_v151"]))
        return hs_map.get(k, 1.0)

    df["hs_factor"] = df.apply(get_hs_factor, axis=1)
    df["power_pred_round59_hour_scene"] = (
        df[pred_col] * df["hs_factor"]
    ).clip(lower=0)

    # Apply site calibration (on baseline, not on hour_scene result)
    print("[INFO] Applying site calibration...")
    df["site_factor"] = df["site_id"].map(site_map).fillna(1.0)

    # For zero_actual_sites: no site factor
    for sid in zero_actual_sites:
        df.loc[df["site_id"] == sid, "site_factor"] = 1.0

    df["power_pred_round59_site"] = (
        df[pred_col] * df["site_factor"]
    ).clip(lower=0)

    # Combined: hour_scene then site
    print("[INFO] Applying combined calibration...")
    df["power_pred_round59_combined"] = (
        df[pred_col] * df["hs_factor"] * df["site_factor"]
    ).clip(lower=0)

    # Clip to capacity
    cap_col = "capacity_mw"
    if cap_col in df.columns:
        df["power_pred_round59_hour_scene"] = df["power_pred_round59_hour_scene"].clip(
            upper=df[cap_col]
        )
        df["power_pred_round59_site"] = df["power_pred_round59_site"].clip(
            upper=df[cap_col]
        )
        df["power_pred_round59_combined"] = df["power_pred_round59_combined"].clip(
            upper=df[cap_col]
        )

    # Summary stats
    print("\n[INFO] Calibrated prediction summary (all splits):")
    for col in ["power_pred_round59_hour_scene", "power_pred_round59_site", "power_pred_round59_combined"]:
        s = df[col].describe()
        print(f"  {col}: mean={s['mean']:.4f}, std={s['std']:.4f}, "
              f"min={s['min']:.4f}, max={s['max']:.4f}")

    # Save
    out_path = OUT / "distributed_predictions_round59_candidates.pkl"
    df.to_pickle(out_path)
    print(f"\n[OK] {out_path}")
    print(f"[INFO] Shape: {df.shape}")
    print(f"[INFO] Columns: {list(df.columns)}")

    # Per-split quick check
    print("\n[INFO] Per-split predictions vs baseline (mean):")
    for split in ["train", "valid", "test", "future"]:
        sdf = df[df["split"] == split]
        if len(sdf) == 0:
            continue
        print(f"  {split}: baseline={sdf[pred_col].mean():.4f}, "
              f"hs={sdf['power_pred_round59_hour_scene'].mean():.4f}, "
              f"site={sdf['power_pred_round59_site'].mean():.4f}, "
              f"combined={sdf['power_pred_round59_combined'].mean():.4f}")


if __name__ == "__main__":
    main()
