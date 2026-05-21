# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

from pv_forecasting.core.models import fit_tabular_regressor, predict_bundle
from pv_forecasting.core.split import add_standard_split
from pv_forecasting.core.utils import corr, mae, rmse, nrmse, safe_pickle_dump


def _ensure_time_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    out["hour"] = out["time"].dt.hour
    out["date"] = out["time"].dt.date
    out["month"] = out["time"].dt.month
    return out


def _ensure_default_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    defaults = {
        "quality_score": 0.5,
        "site_weight": 1.0,
        "alpha_pred": 0.5,
        "pr_month": 0.78,
        "tcc": 0.5,
        "strd_wm2": 300.0,
        "t2m_c": 15.0,
        "ssrd_wm2": 0.0,
        "solar_elevation_deg": 0.0,
        "coastal_flag": 0,
        "capacity_bucket": "unknown",
        "install_group": "unknown",
        "county": "unknown",
    }

    for col, val in defaults.items():
        if col not in out.columns:
            out[col] = val

    if "g_blend_pred" not in out.columns:
        out["g_blend_pred"] = out["ssrd_wm2"]

    out["capacity_mw"] = pd.to_numeric(out["capacity_mw"], errors="coerce")
    out["power_mw"] = pd.to_numeric(out["power_mw"], errors="coerce")
    out["g_blend_pred"] = pd.to_numeric(out["g_blend_pred"], errors="coerce").fillna(
        pd.to_numeric(out["ssrd_wm2"], errors="coerce").fillna(0.0)
    )
    out["pr_month"] = pd.to_numeric(out["pr_month"], errors="coerce").fillna(0.78)

    if "p_base" not in out.columns:
        out["p_base"] = out["capacity_mw"] * out["pr_month"] * out["g_blend_pred"] / 1000.0

    out["p_base"] = pd.to_numeric(out["p_base"], errors="coerce").fillna(0.0)
    out["p_base"] = np.clip(out["p_base"], 0.0, out["capacity_mw"].fillna(0.0))

    if "pred_baseline" not in out.columns:
        out["pred_baseline"] = out["p_base"]

    out["pred_baseline"] = pd.to_numeric(out["pred_baseline"], errors="coerce").fillna(out["p_base"])
    out["pred_baseline"] = np.clip(out["pred_baseline"], 0.0, out["capacity_mw"].fillna(0.0))

    return out


def prepare_distributed_dataset(
    power_clean: pd.DataFrame,
    site_master: pd.DataFrame,
    quality: pd.DataFrame,
    site_irradiance: pd.DataFrame,
) -> pd.DataFrame:
    """构建分布式功率预测训练表。

    该函数用于恢复 v159/v152/V3 训练链路，重点保证字段完整、split 一致、容量归一化训练可用。
    """
    power = power_clean.copy()
    power = power[power["dev_type"] == "分布式"].copy()
    power = _ensure_time_cols(power)

    irr = site_irradiance.copy()
    irr["time"] = pd.to_datetime(irr["time"], errors="coerce")

    keep_irr_cols = [
        "time", "site_id", "g_blend_pred", "alpha_pred", "ssrd_wm2",
        "t2m_c", "tcc", "strd_wm2", "solar_elevation_deg",
    ]
    keep_irr_cols = [c for c in keep_irr_cols if c in irr.columns]
    irr = irr[keep_irr_cols].drop_duplicates(["time", "site_id"])

    df = power.merge(irr, on=["time", "site_id"], how="left", suffixes=("", "_irr"))

    # 补充 quality_score / site_weight
    q = quality.copy()
    if "site_id" in q.columns:
        q_cols = [c for c in ["site_id", "quality_score", "site_weight"] if c in q.columns]
        q = q[q_cols].drop_duplicates("site_id")
        df = df.merge(q, on="site_id", how="left", suffixes=("", "_q"))

    # 补充站点元数据
    meta_cols = [
        "site_id", "capacity_mw", "county", "lat", "lon", "capacity_bucket",
        "install_group", "coastal_flag", "site_short_name",
    ]
    meta_cols = [c for c in meta_cols if c in site_master.columns]
    meta = site_master[meta_cols].drop_duplicates("site_id")
    df = df.merge(meta, on="site_id", how="left", suffixes=("", "_meta"))

    # 合并后优先使用原列，缺失时使用 meta 列
    for col in ["capacity_mw", "county", "lat", "lon", "capacity_bucket", "install_group", "coastal_flag"]:
        meta_col = f"{col}_meta"
        if meta_col in df.columns:
            if col in df.columns:
                df[col] = df[col].where(df[col].notna(), df[meta_col])
            else:
                df[col] = df[meta_col]

    df = _ensure_default_cols(df)
    df = _ensure_time_cols(df)

    df = df[
        df["time"].notna()
        & df["site_id"].notna()
        & df["power_mw"].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()

    df = add_standard_split(df)

    return df


def train_distributed_model(df: pd.DataFrame, model_path: Path, metrics_path: Path):
    """训练基础分布式功率模型。

    目标使用容量归一化功率 power_mw / capacity_mw，预测后还原到 MW。
    """
    data = df.copy()
    data = _ensure_default_cols(data)
    data = _ensure_time_cols(data)

    if "split" not in data.columns:
        data = add_standard_split(data)

    cap = pd.to_numeric(data["capacity_mw"], errors="coerce").replace(0, np.nan)
    data["target_ratio"] = (pd.to_numeric(data["power_mw"], errors="coerce") / cap).clip(0.0, 1.2)

    feature_cols = [
        "g_blend_pred", "ssrd_wm2", "t2m_c", "tcc", "strd_wm2",
        "hour", "month", "capacity_mw", "p_base", "pred_baseline",
        "solar_elevation_deg", "alpha_pred", "pr_month", "quality_score",
        "site_weight", "coastal_flag",
    ]
    cat_cols = [
        "site_id", "county", "capacity_bucket", "install_group",
    ]

    for c in feature_cols:
        if c not in data.columns:
            data[c] = 0.0
        data[c] = pd.to_numeric(data[c], errors="coerce").fillna(0.0)

    for c in cat_cols:
        if c not in data.columns:
            data[c] = "unknown"
        data[c] = data[c].astype("string").fillna("unknown")

    train = data[(data["split"] == "train") & data["target_ratio"].notna()].copy()
    valid = data[(data["split"] == "valid") & data["target_ratio"].notna()].copy()

    if train.empty:
        raise ValueError("分布式模型训练集为空")
    if valid.empty:
        valid = train.sample(min(len(train), 5000), random_state=42).copy()

    bundle = fit_tabular_regressor(
        train,
        valid,
        feature_cols,
        "target_ratio",
        cat_cols=cat_cols,
        sample_weight_col="site_weight" if "site_weight" in train.columns else None,
    )

    pred = data.copy()
    yhat = predict_bundle(bundle, pred)
    yhat = np.clip(yhat, 0.0, 1.2)
    pred["power_pred"] = np.clip(
        yhat * pd.to_numeric(pred["capacity_mw"], errors="coerce").fillna(0.0).to_numpy(),
        0.0,
        pd.to_numeric(pred["capacity_mw"], errors="coerce").fillna(0.0).to_numpy(),
    )

    keep_cols = [
        "time", "site_id", "split", "power_mw", "power_pred",
        "pred_baseline", "p_base", "capacity_mw", "hour", "date",
        "county", "capacity_bucket", "install_group", "quality_score",
        "site_weight", "g_blend_pred", "solar_elevation_deg",
    ]
    keep_cols = [c for c in keep_cols if c in pred.columns]
    pred_df = pred[keep_cols].copy()

    test = pred_df[(pred_df["split"] == "test") & pred_df["power_mw"].notna()].copy()
    yt = test["power_mw"].to_numpy(dtype=float)
    yp = test["power_pred"].to_numpy(dtype=float)
    cap_test = test["capacity_mw"].to_numpy(dtype=float)

    actual_sum = float(np.nansum(yt))
    pred_sum = float(np.nansum(yp))
    capacity_sum = float(np.nansum(cap_test))

    metrics = [
        {"metric": "Corr", "value": corr(yt, yp)},
        {"metric": "MAE", "value": mae(yt, yp)},
        {"metric": "RMSE", "value": rmse(yt, yp)},
        {"metric": "NRMSE", "value": rmse(yt, yp) / max(np.nanmean(cap_test), 1e-9) * 100},
        {"metric": "bias_pct", "value": (pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100},
        {"metric": "pred_actual_ratio", "value": pred_sum / max(actual_sum, 1e-9)},
        {"metric": "actual_sum_mwh", "value": actual_sum},
        {"metric": "pred_sum_mwh", "value": pred_sum},
        {"metric": "capacity_sum_mw", "value": capacity_sum},
    ]
    metrics_df = pd.DataFrame(metrics)

    model_path = Path(model_path)
    metrics_path = Path(metrics_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    safe_pickle_dump(bundle, model_path)
    metrics_df.to_csv(metrics_path, index=False, encoding="utf-8-sig")

    return bundle, metrics_df, pred_df
