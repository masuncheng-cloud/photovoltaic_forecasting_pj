from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..core.features import add_common_features, add_lag_features
from ..core.models import fit_tabular_regressor, predict_bundle
from ..core.utils import corr, mae, nrmse, rmse, safe_pickle_dump


REF_IRR = 1000.0
REF_TEMP = 25.0
BETA_DEFAULT = 0.004


def _coalesce_columns(df: pd.DataFrame, target: str, candidates: list[str], default=np.nan) -> pd.DataFrame:
    if target in df.columns:
        return df
    vals = None
    for c in candidates:
        if c in df.columns:
            vals = df[c] if vals is None else vals.combine_first(df[c])
    df[target] = vals if vals is not None else default
    return df



def _scene_label(df: pd.DataFrame) -> pd.Series:
    """
    场景分类（Round54 修复版）：elev 缺失时用辐照 ssrd_wm2 判断。
    """
    g = df["ssrd_wm2"].fillna(0)
    elev = df.get("solar_elevation_deg", pd.Series(np.nan, index=df.index))
    ramp = df.get("ssrd_wm2_diff1", pd.Series(0, index=df.index)).abs().fillna(0)

    elev_known = np.isfinite(elev.values)
    # 白天判断：hour 6-19
    hour = pd.to_numeric(df.get("hour", pd.Series(12, index=df.index)), errors="coerce")
    if pd.api.types.is_integer_dtype(hour) or pd.api.types.is_float_dtype(hour):
        hour_arr = hour.values
    else:
        hour_arr = pd.to_datetime(df["time"], errors="coerce").dt.hour.values

    scene = np.empty(len(df), dtype=object)
    # elev 已知：elev <= 0 → night
    mask_known = elev_known
    scene[mask_known] = np.where(
        elev.values[mask_known] <= 0, "night",
        np.where(g.values[mask_known] < 120, "low",
        np.where(ramp.values[mask_known] > 140, "ramp",
        np.where(g.values[mask_known] > 650, "clear_peak", "mid"))))
    # elev 缺失：白天用辐照判断（不默认 night）
    mask_unknown_day = ~elev_known & (hour_arr >= 6) & (hour_arr <= 19)
    scene[mask_unknown_day] = np.where(
        g.values[mask_unknown_day] < 120, "low",
        np.where(ramp.values[mask_unknown_day] > 140, "ramp",
        np.where(g.values[mask_unknown_day] > 650, "clear_peak", "mid")))
    # elev 缺失且夜间
    mask_unknown_night = ~elev_known & ~mask_unknown_day
    scene[mask_unknown_night] = "night"
    return pd.Series(scene, index=df.index, dtype="string")



def estimate_monthly_pr(df: pd.DataFrame) -> pd.DataFrame:
    tmp = df.copy()
    tmp["month"] = pd.to_datetime(tmp["time"]).dt.month
    den = (tmp["ssrd_wm2"].clip(lower=1) / REF_IRR) * (1 - BETA_DEFAULT * (tmp["t2m_c"] - REF_TEMP))
    tmp["pr_raw"] = (tmp["power_mw"] / tmp["capacity_mw"].clip(lower=1e-6)) / den
    tmp.loc[(tmp["ssrd_wm2"] < 50) | ~np.isfinite(tmp["pr_raw"]), "pr_raw"] = np.nan
    pr = tmp.groupby(["site_id", "month"], as_index=False)["pr_raw"].median()
    pr["pr_raw"] = pr["pr_raw"].clip(0.05, 1.2).fillna(0.82)
    return pr.rename(columns={"pr_raw": "pr_month"})



def prepare_inverse_dataset(power_clean: pd.DataFrame, site_master: pd.DataFrame, quality: pd.DataFrame) -> pd.DataFrame:
    central = power_clean[power_clean["dev_type"] == "集中式"].copy()
    central = central[central["site_id"].notna()].copy()
    meta_cols = [c for c in ["site_id", "lon", "lat", "county", "scheduler_type", "coastal_flag"] if c in site_master.columns]
    central = central.merge(site_master[meta_cols], on="site_id", how="left", suffixes=("", "_meta"))
    central = _coalesce_columns(central, "county", ["county", "county_meta", "county_x", "county_y"], default="unknown")
    central = _coalesce_columns(central, "scheduler_type", ["scheduler_type", "scheduler_type_meta", "scheduler_type_x", "scheduler_type_y"], default="unknown")
    central = _coalesce_columns(central, "coastal_flag", ["coastal_flag", "coastal_flag_meta", "coastal_flag_x", "coastal_flag_y"], default=0)
    central["county"] = central["county"].fillna("unknown")
    central["scheduler_type"] = central["scheduler_type"].fillna("unknown")
    central["coastal_flag"] = central["coastal_flag"].fillna(0)
    central = central.merge(quality[["site_id", "quality_score"]], on="site_id", how="left")
    pr = estimate_monthly_pr(central)
    central["month"] = pd.to_datetime(central["time"]).dt.month
    central = central.merge(pr, on=["site_id", "month"], how="left")
    central["pr_month"] = central["pr_month"].fillna(0.82)
    central["g_base"] = (
        central["power_mw"] / (central["capacity_mw"].clip(lower=1e-6) * central["pr_month"].clip(lower=0.05)
        * (1 - BETA_DEFAULT * (central["t2m_c"] - REF_TEMP)).clip(lower=0.4, upper=1.2))
    ) * REF_IRR
    central["g_base"] = central["g_base"].clip(lower=0, upper=1400)
    central["g_residual_target"] = central["ssrd_wm2"] - central["g_base"]
    central = add_common_features(central)
    central = add_lag_features(central, "site_id", ["power_mw", "ssrd_wm2", "g_base"], [1, 2])
    central["scene_label"] = _scene_label(central)
    return central



def train_inverse_model(df: pd.DataFrame, model_path: Path, metrics_path: Path):
    feature_cols = [
        "power_mw", "capacity_mw", "t2m_c", "hour", "month", "dayofyear",
        "hour_sin", "hour_cos", "doy_sin", "doy_cos", "solar_elevation_deg",
        "power_mw_lag1", "power_mw_lag2", "power_mw_diff1", "power_mw_diff2",
        "ssrd_wm2_lag1", "ssrd_wm2_lag2", "ssrd_wm2_diff1", "g_base", "g_base_lag1", "g_base_lag2",
        "quality_score", "county", "scheduler_type", "site_id", "coastal_flag", "scene_label",
    ]
    cat_cols = ["county", "scheduler_type", "site_id", "scene_label"]
    data = df[df["power_mw"].notna() & df["ssrd_wm2"].notna() & (df["ssrd_wm2"] >= 0)].copy()
    data = data[data["quality_score"].fillna(0) >= 0.10].copy()
    for col in ["county", "scheduler_type", "scene_label"]:
        data = _coalesce_columns(data, col, [col, f"{col}_x", f"{col}_y"], default="unknown")
        data[col] = data[col].fillna("unknown")
    data = _coalesce_columns(data, "coastal_flag", ["coastal_flag", "coastal_flag_x", "coastal_flag_y"], default=0)
    data["sample_weight"] = (
        np.where(data["ssrd_wm2"] > 250, 2.5, 1.0)
        * np.where(data["scene_label"].eq("ramp"), 1.25, 1.0)
        * data["quality_score"].fillna(0.5).clip(lower=0.1)
    )
    data["year"] = pd.to_datetime(data["time"]).dt.year
    train = data[data["year"] <= 2024].copy()
    valid = data[(data["year"] == 2025) & (data["month"] <= 6)].copy()
    test = data[(data["year"] == 2025) & (data["month"] > 6)].copy()
    bundle = fit_tabular_regressor(train, valid, feature_cols, "g_residual_target", cat_cols=cat_cols, sample_weight_col="sample_weight")

    metrics_rows = []
    from ..core.progress import progress_iter
    for item in progress_iter(
        [("train", train), ("valid", valid), ("test", test)],
        total=3,
        desc="[3b] inverse predict splits",
        min_interval=0.5,
    ):
        split_name, split_df = item
        if len(split_df) == 0:
            continue
        split_df = split_df.copy()
        split_df["g_residual_pred"] = predict_bundle(bundle, split_df)
        split_df["g_pred"] = (split_df["g_base"] + split_df["g_residual_pred"]).clip(lower=0, upper=1400)
        split_df["power_recon"] = (
            split_df["capacity_mw"] * split_df["pr_month"]
            * (split_df["g_pred"] / REF_IRR)
            * (1 - BETA_DEFAULT * (split_df["t2m_c"] - REF_TEMP)).clip(lower=0.4, upper=1.2)
        ).clip(lower=0)
        metrics_rows.append({
            "split": split_name,
            "irr_mae": mae(split_df["ssrd_wm2"].to_numpy(), split_df["g_pred"].to_numpy()),
            "irr_rmse": rmse(split_df["ssrd_wm2"].to_numpy(), split_df["g_pred"].to_numpy()),
            "irr_nrmse": nrmse(split_df["ssrd_wm2"].to_numpy(), split_df["g_pred"].to_numpy()),
            "irr_corr": corr(split_df["ssrd_wm2"].to_numpy(), split_df["g_pred"].to_numpy()),
            "power_recon_rmse": rmse(split_df["power_mw"].to_numpy(), split_df["power_recon"].to_numpy()),
            "power_recon_nrmse": nrmse(split_df["power_mw"].to_numpy(), split_df["power_recon"].to_numpy()),
            "rows": int(len(split_df)),
        })
        data.loc[split_df.index, "g_pred"] = split_df["g_pred"]
        data.loc[split_df.index, "power_recon"] = split_df["power_recon"]
    metrics_df = pd.DataFrame(metrics_rows)
    safe_pickle_dump(bundle, model_path)
    metrics_df.to_csv(metrics_path, index=False, encoding="utf-8-sig")
    pred_cols = ["time", "site_id", "ssrd_wm2", "g_base", "g_pred", "power_mw", "power_recon", "scene_label"]
    for c in ["county", "scheduler_type", "coastal_flag"]:
        if c in data.columns:
            pred_cols.append(c)
    return bundle, metrics_df, data[pred_cols]
