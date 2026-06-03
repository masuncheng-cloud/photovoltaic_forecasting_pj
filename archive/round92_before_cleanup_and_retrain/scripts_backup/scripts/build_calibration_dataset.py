#!/usr/bin/env python3
"""
build_calibration_dataset.py
===========================
构建校准训练数据集。

从 full prediction pkl 中提取 train/valid 6-19 点数据，
排除 calibration_exclude_sites，输出校准训练表。

输出：
  output/pv_pipeline/calibration/calibration_train_valid.pkl
  output/pv_pipeline/calibration/calibration_valid.pkl

用法：
    python scripts/build_calibration_dataset.py
"""

from pathlib import Path
import yaml
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline/calibration"
OUT.mkdir(parents=True, exist_ok=True)


def load_quality_policy():
    policy_path = ROOT / "configs" / "site_quality_policy.yaml"
    if policy_path.exists():
        with open(policy_path) as f:
            return yaml.safe_load(f)
    return {}


def main():
    print("=" * 60)
    print("构建校准训练数据集")
    print("=" * 60)

    policy = load_quality_policy()
    exclude_sites = set(policy.get("calibration_exclude_sites", []))
    print(f"[INFO] calibration_exclude_sites: {sorted(exclude_sites)}")

    # Load full pkl
    full_pkl = ROOT / "output/pv_pipeline/predictions" / "distributed_predictions_final_full.pkl"
    print(f"[INFO] Loading: {full_pkl}")
    df = pd.read_pickle(full_pkl)
    print(f"[INFO] Full pkl: {len(df)} rows, splits: {df['split'].value_counts().to_dict()}")

    # Normalize time
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    if "month" not in df.columns:
        df["month"] = df["time"].dt.month

    # Filter to train/valid only
    df_tv = df[df["split"].isin(["train", "valid"])].copy()
    print(f"[INFO] After train/valid filter: {len(df_tv)} rows")

    # Filter to 6-19 hours
    df_tv = df_tv[df_tv["hour"].between(6, 19)].copy()
    print(f"[INFO] After 6-19 filter: {len(df_tv)} rows")

    # Exclude calibration_exclude_sites
    if exclude_sites:
        before = len(df_tv)
        df_tv = df_tv[~df_tv["site_id"].isin(exclude_sites)].copy()
        after = len(df_tv)
        print(f"[INFO] After excluding calibration_sites: {after} rows (removed {before - after})")

    # Ensure power_pred_final exists (use power_pred if not)
    if "power_pred_final" not in df_tv.columns:
        if "power_pred" in df_tv.columns:
            df_tv["power_pred_final"] = df_tv["power_pred"]
            print("[WARN] power_pred_final not found, using power_pred")
        else:
            raise KeyError("Neither power_pred_final nor power_pred found")

    # Build residual/ratio columns
    pred_col = "power_pred_final"
    df_tv["residual_mw"] = df_tv["power_mw"] - df_tv[pred_col]
    eps = 1e-9
    df_tv["ratio"] = df_tv["power_mw"] / df_tv[pred_col].clip(lower=eps)
    df_tv["actual_norm"] = df_tv["power_mw"] / df_tv["capacity_mw"].clip(lower=eps)
    df_tv["pred_norm"] = df_tv[pred_col] / df_tv["capacity_mw"].clip(lower=eps)
    df_tv["residual_norm"] = df_tv["actual_norm"] - df_tv["pred_norm"]

    # Split into train and valid
    df_train = df_tv[df_tv["split"] == "train"].copy()
    df_valid = df_tv[df_tv["split"] == "valid"].copy()

    # Select columns
    cols = [
        "time", "site_id", "capacity_mw", "split", "hour", "month",
        "scene_v151", "power_mw", "power_pred_final",
        "residual_mw", "ratio", "actual_norm", "pred_norm", "residual_norm",
        "g_blend_pred", "clear_sky_ghi",
    ]
    cols = [c for c in cols if c in df_train.columns]

    df_train_out = df_train[cols].copy()
    df_valid_out = df_valid[cols].copy()

    # Save
    train_path = OUT / "calibration_train.pkl"
    valid_path = OUT / "calibration_valid.pkl"
    train_valid_path = OUT / "calibration_train_valid.pkl"

    df_train_out.to_pickle(train_path)
    df_valid_out.to_pickle(valid_path)
    df_tv[cols].to_pickle(train_valid_path)

    print(f"[INFO] calibration_train.pkl: {len(df_train_out)} rows, {df_train_out['site_id'].nunique()} sites")
    print(f"[INFO] calibration_valid.pkl: {len(df_valid_out)} rows, {df_valid_out['site_id'].nunique()} sites")
    print(f"[INFO] calibration_train_valid.pkl: {len(df_tv)} rows")

    # Quick stats
    print("\n[INFO] Valid set per (hour, scene) coverage:")
    if "scene_v151" in df_valid_out.columns:
        hs = df_valid_out.groupby(["hour", "scene_v151"]).size().unstack(fill_value=0)
        print(f"  Hours: {sorted(hs.index.tolist())}")
        print(f"  Scenes: {sorted(hs.columns.tolist())}")

    print(f"\n[OK] 输出目录: {OUT}")
    print(f"  {train_path.name}: {len(df_train_out):,} rows")
    print(f"  {valid_path.name}: {len(df_valid_out):,} rows")
    print(f"  {train_valid_path.name}: {len(df_tv):,} rows")


if __name__ == "__main__":
    main()
