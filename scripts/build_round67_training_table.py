#!/usr/bin/env python3
"""
build_round67_training_table.py
==================================
为 Round67 场景分组主模型构建训练特征表。

输出：
  output/pv_pipeline/round67/round67_training_table.parquet
  output/pv_pipeline/round67/round67_feature_inventory.csv
  output/pv_pipeline/round67/round67_training_data_summary.csv
"""

from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import yaml

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
FINAL_PKL = OUT / "predictions" / "distributed_predictions_final_full.pkl"


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/round67_scene_main_model.yaml")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    cfg_path = ROOT / args.config
    if not cfg_path.exists():
        print(f"[FAIL] Config not found: {cfg_path}")
        return

    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    out_dir = Path(args.output_dir) if args.output_dir else OUT / "round67"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Round67 Training Table Builder")
    print("=" * 60)

    # Load data
    print(f"[INFO] Loading: {FINAL_PKL}")
    df = pd.read_pickle(FINAL_PKL)
    df["time"] = pd.to_datetime(df["time"])

    # Exclude future
    before = len(df)
    df = df[df["split"] != "future"].copy()
    print(f"[INFO] After future filter: {before} -> {len(df)} rows")

    # Keep 6-19h for modeling
    df = df[df["hour"].between(6, 19)].copy()
    print(f"[INFO] After 6-19h filter: {len(df)} rows")

    # Target
    df["y_norm"] = df["power_mw"] / df["capacity_mw"].clip(lower=0.01)

    # Time block
    tb = cfg.get("time_blocks", {})
    block_map = {}
    for blk, hrs in tb.items():
        for h in hrs:
            block_map[h] = blk
    df["time_block"] = df["hour"].map(block_map).fillna("other")

    # Site groups from data
    site_stats = df.groupby("site_id").agg(
        cap=("capacity_mw", "first"),
        zero_ratio=("power_mw", lambda x: (x <= 0).mean()),
        n_samples=("power_mw", "count"),
        pr_median=("y_norm", lambda x: x[x > 0].median() if (x > 0).any() else 0),
        bias=("y_norm", lambda x: x.mean() - 1),
    ).reset_index()

    cap_bins = {1: "low_capacity", 2: "mid_capacity", 3: "high_capacity"}
    site_stats["cap_group"] = pd.cut(
        site_stats["cap"],
        bins=[0, 3, 10, float("inf")],
        labels=["low_capacity", "mid_capacity", "high_capacity"]
    ).astype(str)

    zero_bins = site_stats["zero_ratio"].apply(
        lambda z: "high_zero" if z >= 0.3 else ("stable" if z <= 0.2 else "normal")
    )
    site_stats["zero_group"] = zero_bins
    site_stats["site_group"] = site_stats["cap_group"] + "_" + site_stats["zero_group"]

    df = df.merge(site_stats[["site_id", "cap_group", "zero_group", "site_group",
                               "pr_median", "bias", "zero_ratio"]], on="site_id", how="left")

    # Boolean features
    df["is_noon"] = df["hour"].between(11, 14).astype(int)
    df["is_dawn"] = df["time_block"] == "dawn"
    df["is_dusk"] = df["time_block"] == "dusk"
    df["is_high_zero_site"] = (df["zero_ratio"] >= 0.3).astype(int)

    # Normalized baseline
    df["baseline_norm"] = df[cfg["baseline_col"]] / df["capacity_mw"].clip(lower=0.01)

    # Feature columns
    feat_cols = ["hour", "month", "dayofyear", "capacity_mw",
                 "baseline_norm", cfg["baseline_col"],
                 "pr_median", "bias", "zero_ratio"]
    optional_cols = [
        "clear_sky_ghi", "clear_sky_index", "g_blend_pred",
        "latitude", "longitude", "quality_score",
        "scene_v151", "scene"
    ]
    for col in optional_cols:
        if col in df.columns:
            feat_cols.append(col)

    # Clip and clean features — deduplicate columns (keep first occurrence)
    avail_feats = [c for c in feat_cols if c in df.columns]
    base_cols = ["site_id", "time", "split", "hour", "time_block",
                 "site_group", "y_norm", "power_mw", "capacity_mw",
                 cfg["baseline_col"], "baseline_norm"] + avail_feats
    # Deduplicate while preserving order
    seen = set()
    unique_base = []
    for c in base_cols:
        if c not in seen:
            seen.add(c)
            unique_base.append(c)
    df_model = df[unique_base].copy()
    df_model = df_model.loc[:, ~df_model.columns.duplicated()]

    # Ensure numeric
    for c in avail_feats:
        try:
            df_model[c] = pd.to_numeric(df_model[c], errors="coerce")
        except Exception:
            try:
                df_model[c] = pd.to_numeric(df_model[c].astype(str), errors="coerce")
            except Exception:
                pass

    # Feature inventory
    inv_rows = []
    for c in df_model.columns:
        if c in ["site_id", "time", "split", "hour", "time_block",
                 "site_group", "y_norm", "power_mw", "capacity_mw",
                 cfg["baseline_col"], "baseline_norm"]:
            continue
        inv_rows.append({
            "feature": c,
            "dtype": str(df_model[c].dtype),
            "non_null": int(df_model[c].notna().sum()),
            "null_count": int(df_model[c].isna().sum()),
            "min": float(df_model[c].min()) if df_model[c].notna().any() else None,
            "max": float(df_model[c].max()) if df_model[c].notna().any() else None,
        })

    inv_df = pd.DataFrame(inv_rows)
    inv_path = out_dir / "round67_feature_inventory.csv"
    inv_df.to_csv(inv_path, index=False, encoding="utf-8-sig")
    print(f"[OK] Feature inventory: {inv_path} ({len(inv_df)} features)")

    # Save parquet
    df_out = df_model.copy()
    para_path = out_dir / "round67_training_table.parquet"
    df_out.to_parquet(para_path, index=False, compression="snappy")
    print(f"[OK] Training table: {para_path} ({len(df_out)} rows)")

    # Summary
    sum_rows = []
    for split in ["train", "valid", "test"]:
        sdf = df_model[df_model["split"] == split]
        sum_rows.append({
            "split": split,
            "rows": len(sdf),
            "sites": sdf["site_id"].nunique(),
            "hours": sorted(sdf["hour"].unique().tolist()),
            "y_norm_mean": round(float(sdf["y_norm"].mean()), 4),
            "y_norm_std": round(float(sdf["y_norm"].std()), 4),
            "positive_rate": round(float((sdf["y_norm"] > 0).mean()), 4),
        })

    sum_df = pd.DataFrame(sum_rows)
    sum_path = out_dir / "round67_training_data_summary.csv"
    sum_df.to_csv(sum_path, index=False, encoding="utf-8-sig")
    print(f"[OK] Data summary: {sum_path}")
    print(f"\n{sum_df.to_string(index=False)}")

    print(f"\n[OK] Training table build complete")
    print(f"  Features: {len(avail_feats)}")
    print(f"  Total rows: {len(df_model)}")


if __name__ == "__main__":
    main()
