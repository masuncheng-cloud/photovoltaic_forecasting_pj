#!/usr/bin/env python3
"""
build_round69_performance_training_table.py
==================================
构建 Round69 性能提升实验所需的训练表。

特征工程策略：
  - 基础：hour, month, dayofyear, capacity, lat/lon
  - 气象代理：clear_sky_ghi, clear_sky_index, g_blend_pred, scene_v151
  - 站点统计：pr_median, quality_score, bias, zero_ratio, scene features
  - 预测残差：round67/68 的 lgb/hgb/ridge 归一化预测差
  - 交互特征：hour × scene, hour × clear_sky_index, capacity_bucket × time_block
"""

from pathlib import Path
import numpy as np
import pandas as pd
import pickle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
FINAL_PKL = OUT / "predictions" / "distributed_predictions_final_full.pkl"
ROUND69 = OUT / "round69"
ROUND67_TBL = OUT / "round67" / "round67_training_table.parquet"
MODEL_STORE = OUT / "round67" / "round67_model_files" / "model_store.pkl"
ROUND69.mkdir(exist_ok=True)


def compute_solar_elevation(hour, month, dayofyear, latitude=34.5):
    """近似太阳高度角（度）。"""
    lat_rad = np.radians(latitude)
    doy = np.asarray(dayofyear, dtype=float)
    hour_arr = np.asarray(hour, dtype=float)
    decl = 23.45 * np.sin(np.radians(360 / 365 * (doy - 81)))
    decl_rad = np.radians(decl)
    hour_angle = (hour_arr - 12) * 15
    ha_rad = np.radians(hour_angle)
    sin_elev = (np.sin(lat_rad) * np.sin(decl_rad)
                 + np.cos(lat_rad) * np.cos(decl_rad) * np.cos(ha_rad))
    elev = np.degrees(np.arcsin(np.clip(sin_elev, -1, 1)))
    return elev


def main():
    print("=" * 60)
    print("Round69 Performance Training Table Builder")
    print("=" * 60)

    # Load final pkl (only train/valid/test, no future)
    print("\n[INFO] Loading final pkl...")
    df = pd.read_pickle(FINAL_PKL)
    df["time"] = pd.to_datetime(df["time"])
    print(f"  Loaded: {len(df)} rows, splits: {df['split'].value_counts().to_dict()}")

    # Keep only needed columns to save memory
    needed = ["site_id", "time", "split", "hour", "month", "dayofyear",
              "capacity_mw", "latitude", "longitude", "power_mw",
              "power_pred_final", "clear_sky_ghi", "clear_sky_index",
              "g_blend_pred", "pr_median", "bias", "zero_ratio",
              "quality_score", "scene_v151", "scene",
              "site_group", "time_block", "capacity_bucket",
              "power_pred_lgb_residual", "power_pred_ridge_residual",
              "baseline_norm", "y_norm"]
    cols = [c for c in needed if c in df.columns]
    df = df[cols].copy()

    # ── Reconstruct round67 lgb predictions for residual features ──────
    print("\n[INFO] Reconstructing round67 model predictions...")

    # Build features for prediction reconstruction
    exclude_pred = {"site_id", "time", "split", "hour", "time_block", "site_group",
                   "y_norm", "power_mw", "capacity_mw", "power_pred_final",
                   "baseline_norm", "capacity_bucket", "zero_group"}
    feat_cols = [c for c in df.columns if c not in exclude_pred]

    with open(MODEL_STORE, "rb") as f:
        store = pickle.load(f)
    models = store["models"]

    for model_name in ["lgb", "hgb", "ridge"]:
        if model_name not in models:
            continue
        df[f"pred_{model_name}_norm"] = np.nan
        for block, model_obj in models[model_name].items():
            mask = df["time_block"] == block
            if mask.sum() == 0:
                continue
            X = (pd.DataFrame(df.loc[mask, feat_cols])
                   .apply(pd.to_numeric, errors="coerce")
                   .fillna(0).values.astype(float))
            if model_name == "ridge":
                X = model_obj["scaler"].transform(X)
                pred_norm = model_obj["model"].predict(X)
            else:
                pred_norm = model_obj.predict(X)
            cap = df.loc[mask, "capacity_mw"].values.astype(float)
            df.loc[mask, f"pred_{model_name}_norm"] = np.clip(pred_norm, 0, 1)
        df[f"pred_{model_name}_norm"] = df[f"pred_{model_name}_norm"].fillna(
            df["power_pred_final"] / df["capacity_mw"].clip(lower=0.1)
        )

    # ── Target: y_norm ───────────────────────────────────────────────
    df["y_norm"] = df["power_mw"] / df["capacity_mw"].clip(lower=0.1)
    df["residual_norm"] = (df["power_mw"] - df["power_pred_final"]) / df["capacity_mw"].clip(lower=0.1)
    df["baseline_norm"] = df["power_pred_final"] / df["capacity_mw"].clip(lower=0.1)

    # ── Feature Engineering ───────────────────────────────────────────
    print("\n[INFO] Feature engineering...")

    # Solar elevation
    df["solar_elevation"] = compute_solar_elevation(
        df["hour"].values, df["month"].values, df["dayofyear"].values
    )
    df["solar_elevation"] = df["solar_elevation"].clip(lower=0)

    # Capacity bucket
    df["cap_bucket"] = pd.cut(
        df["capacity_mw"],
        bins=[0, 3, 7, 15, 100],
        labels=["tiny", "small", "medium", "large"]
    ).astype(str)

    # Interaction: hour × clear_sky_index
    df["hour_x_clear_sky"] = df["hour"] * df["clear_sky_index"]

    # Interaction: hour × g_blend_pred
    df["hour_x_gblend"] = df["hour"] * df["g_blend_pred"] / 1000.0

    # Interaction: capacity_bucket × time_block
    df["cap_x_block"] = df["cap_bucket"] + "_" + df["time_block"]

    # Interaction: site_group × time_block
    df["group_x_block"] = df["site_group"].fillna("unknown") + "_" + df["time_block"]

    # Scene indicator features
    for col in ["scene_v151", "scene"]:
        if col in df.columns:
            vals = df[col].fillna("unknown").astype(str)
            vals_oh = pd.get_dummies(vals, prefix=col, drop_first=True)
            df = pd.concat([df, vals_oh], axis=1)

    # Clear sky derived
    df["ghi_ratio"] = df["g_blend_pred"] / df["clear_sky_ghi"].clip(lower=1)

    # Hour sin/cos (cyclical encoding)
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)

    # Season indicator (bimodal for PV)
    df["is_summer"] = (df["month"] >= 5) & (df["month"] <= 9)
    df["is_winter"] = (df["month"] <= 2) | (df["month"] >= 11)
    df["is_spring_autumn"] = (~df["is_summer"]) & (~df["is_winter"])

    # Zero/night indicator
    df["is_zero_power"] = (df["power_mw"] < 0.01).astype(float)

    # Previous model residual (already have in df as residual_norm)
    # Explicit round68 lgb residual
    if "pred_lgb_norm" in df.columns:
        df["lgb_residual_from_round68"] = df["y_norm"] - df["pred_lgb_norm"]

    # ── Station-level statistics (from train data) ─────────────────────
    print("\n[INFO] Computing station-level statistics...")
    train_df = df[df["split"] == "train"].copy()

    # NRMSE per site from train (as proxy for site quality)
    site_stats = []
    for sid, sdf in train_df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        base_pred = sdf["power_pred_final"].values
        actual = sdf["power_mw"].values
        rmse = float(np.sqrt(np.mean((base_pred - actual) ** 2)))
        bias = float(np.mean(base_pred - actual))
        nrmse = rmse / cap * 100
        zero_ratio = float((sdf["power_mw"] < 0.01).mean())
        pos_count = int((sdf["power_mw"] >= 0.01).sum())
        pr = float(sdf["pr_median"].iloc[0]) if "pr_median" in sdf.columns else float("nan")
        qs = float(sdf["quality_score"].iloc[0]) if "quality_score" in sdf.columns else float("nan")
        site_stats.append({
            "site_id": str(sid),
            "site_nrmse_train": round(nrmse, 4),
            "site_bias_train": round(bias, 4),
            "site_zero_ratio_train": round(zero_ratio, 4),
            "site_pos_count_train": pos_count,
            "site_pr_median": round(pr, 4),
            "site_quality_score": round(qs, 4),
            "site_capacity": round(cap, 4),
        })
    site_stats_df = pd.DataFrame(site_stats)

    # Merge back
    df = df.merge(site_stats_df, on="site_id", how="left")

    # Fill missing
    for c in ["site_nrmse_train", "site_bias_train", "site_zero_ratio_train",
              "site_pr_median", "site_quality_score"]:
        df[c] = df[c].fillna(df[c].median())

    # ── Final feature list ───────────────────────────────────────────
    feature_cols = [
        # Basic
        "hour", "month", "dayofyear", "capacity_mw", "latitude", "longitude",
        "hour_sin", "hour_cos", "month_sin", "month_cos",
        # Meteorological
        "clear_sky_ghi", "clear_sky_index", "g_blend_pred",
        "solar_elevation", "ghi_ratio",
        # Site stats
        "pr_median", "quality_score", "bias", "zero_ratio",
        "site_nrmse_train", "site_bias_train", "site_zero_ratio_train",
        "site_pr_median", "site_quality_score",
        # Interactions
        "hour_x_clear_sky", "hour_x_gblend",
        # Baseline prediction
        "baseline_norm",
        # Round67 model predictions
        "pred_lgb_norm", "pred_hgb_norm", "pred_ridge_norm",
        # Scene features (already in df as one-hot)
    ]

    # Add scene one-hot columns
    for c in df.columns:
        if c.startswith("scene_v151_") or c.startswith("scene_"):
            feature_cols.append(c)

    # Remove dups
    feature_cols = list(dict.fromkeys(feature_cols))
    feature_cols = [c for c in feature_cols if c in df.columns]

    print(f"\n[INFO] Total features: {len(feature_cols)}")

    # ── Add capacity and zero groups ─────────────────────────────────
    df["cap_group"] = df["cap_bucket"]
    df["zero_group"] = pd.cut(
        df["zero_ratio"],
        bins=[-1, 0.1, 0.3, 1.0],
        labels=["low_zero", "mid_zero", "high_zero"]
    ).astype(str)

    # ── Save ────────────────────────────────────────────────────────
    out_cols = (
        ["site_id", "time", "split", "hour", "time_block", "site_group",
         "y_norm", "power_mw", "capacity_mw", "power_pred_final",
         "baseline_norm", "residual_norm"] +
        feature_cols
    )
    out_cols = [c for c in out_cols if c in df.columns]
    df_out = df[out_cols].copy()

    # Save training table
    out_path = ROUND69 / "round69_training_table.parquet"
    df_out.to_parquet(out_path, index=False, compression="snappy")
    print(f"\n[OK] Training table: {out_path} ({len(df_out)} rows, {len(df_out.columns)} cols)")

    # Feature inventory
    feat_inv = pd.DataFrame({"feature": feature_cols})
    feat_inv["dtype"] = feat_inv["feature"].map(lambda c: str(df_out[c].dtype))
    feat_inv["null_count"] = feat_inv["feature"].map(lambda c: int(df_out[c].isnull().sum()))
    feat_inv.to_csv(ROUND69 / "round69_feature_inventory.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] Feature inventory: {ROUND69 / 'round69_feature_inventory.csv'}")

    # Training summary
    summary_rows = []
    for split_name, sdf in df_out.groupby("split"):
        summary_rows.append({
            "split": split_name,
            "rows": len(sdf),
            "sites": sdf["site_id"].nunique(),
            "y_norm_mean": round(float(sdf["y_norm"].mean()), 4),
            "y_norm_std": round(float(sdf["y_norm"].std()), 4),
            "zero_ratio": round(float((sdf["power_mw"] < 0.01).mean()), 4),
            "capacity_mean": round(float(sdf["capacity_mw"].mean()), 4),
        })
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(ROUND69 / "round69_training_summary.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] Training summary: {ROUND69 / 'round69_training_summary.csv'}")
    print(f"\n{summary_df.to_string(index=False)}")

    # Station group summary
    grp_rows = []
    for grp, gdf in site_stats_df.groupby("site_nrmse_train", dropna=False):
        pass
    site_stats_df.to_csv(ROUND69 / "round69_station_group_summary.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] Station groups: {ROUND69 / 'round69_station_group_summary.csv'}")


if __name__ == "__main__":
    main()
