#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round9 中午专用模型训练（LightGBM + CatBoost 集成版）
=========================================================
使用 LightGBM 4.6 + CatBoost 1.2，从 distributed_predictions_final_full 训练
"""
from __future__ import annotations

from pathlib import Path
import sys, pickle

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pv_forecasting.core.utils import safe_pickle_load, safe_pickle_dump
from pv_forecasting.core.models import fit_tabular_regressor, predict_bundle
from pv_forecasting.core.split import add_standard_split

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

MIDDAY = [10, 11, 12, 13, 14]
WATCH_SITES = {"S012", "S055", "S050", "S032", "S019", "S053", "S116", "S052"}

REG_FEATURES = [
    "g_blend_pred", "clear_sky_ghi",
    "hour", "month", "dayofyear",
    "capacity_mw", "quality_score",
]
CAT_FEATURES = ["county", "capacity_bucket", "install_group"]


def nrmse_pct(y, p, cap):
    m = np.isfinite(y) & np.isfinite(p) & (cap > 0)
    if not m.any():
        return np.nan
    rmse = np.sqrt(np.mean((y[m] - p[m]) ** 2))
    return float(rmse / np.nanmean(cap[m]) * 100)


def mape_active(y, p):
    m = (y > 0) & np.isfinite(y) & np.isfinite(p)
    if not m.any():
        return np.nan
    return float(np.mean(np.abs(y[m] - p[m]) / y[m]) * 100)


def main():
    print("=" * 70)
    print("Round9 中午专用模型 (LightGBM + CatBoost 集成)")
    print("=" * 70)

    # 1. 加载
    print("\n[Step 1] 加载数据...")
    full_path = TABLES / "distributed_predictions_final_full.pkl"
    if not full_path.exists():
        full_path = TABLES / "distributed_predictions_fixed_full.pkl"
    full_df = safe_pickle_load(full_path)
    print(f"  全量: {len(full_df)} 行")

    eval_path = TABLES / "distributed_predictions_final_eval.pkl"
    if not eval_path.exists():
        eval_path = TABLES / "distributed_predictions_fixed_eval.pkl"
    eval_df = safe_pickle_load(eval_path) if eval_path.exists() else None
    print(f"  评估集: {len(eval_df)} 行" if eval_df is not None else "  评估集: 无")

    # 2. 预处理
    print("\n[Step 2] 预处理...")
    df = full_df.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df["hour"] = df["time"].dt.hour
    df["month"] = df["time"].dt.month
    df["dayofyear"] = df["time"].dt.dayofyear
    df = df[df["hour"].isin(MIDDAY)].copy()

    for c in REG_FEATURES:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    for c in CAT_FEATURES:
        if c in df.columns:
            df[c] = df[c].astype("string").fillna("unknown")

    cap = pd.to_numeric(df["capacity_mw"], errors="coerce").replace(0, np.nan)
    df["target_ratio"] = (pd.to_numeric(df["power_mw"], errors="coerce") / cap).clip(0.0, 1.2)

    df["weight_round9"] = 1.0
    df.loc[df["site_id"].isin(WATCH_SITES), "weight_round9"] = 2.5
    df.loc[df["hour"].isin([12, 13]), "weight_round9"] *= 1.2

    if "split" not in df.columns:
        df = add_standard_split(df)

    train = df[df["split"] == "train"].copy()
    valid = df[df["split"] == "valid"].copy()
    test = df[df["split"] == "test"].copy()

    train_pos = train[train["target_ratio"].notna()].copy()
    valid_pos = valid[valid["target_ratio"].notna()].copy()
    test_pos = test[test["target_ratio"].notna()].copy()

    feat_num = [c for c in REG_FEATURES if c in df.columns]
    feat_cat = [c for c in CAT_FEATURES if c in df.columns]
    print(f"  train: {len(train_pos)}, valid: {len(valid_pos)}, test: {len(test_pos)}")
    print(f"  数值: {feat_num}")
    print(f"  类别: {feat_cat}")

    # 3. 训练 (CatBoost + LightGBM 集成)
    print("\n[Step 3] 训练 (CatBoost + LightGBM)...")
    task_params = {
        "iterations": 1500,
        "depth": 7,
        "learning_rate": 0.05,
        "early_stopping_rounds": 100,
    }
    bundle = fit_tabular_regressor(
        train_pos, valid_pos,
        feat_num + feat_cat, "target_ratio",
        cat_cols=feat_cat,
        sample_weight_col="weight_round9",
        task_params=task_params,
    )
    print(f"  模型类型: {bundle.model_type}")
    if hasattr(bundle, "sub_models"):
        print(f"  子模型: {[(t, getattr(s, 'n_estimators', '?')) for t, s, _ in bundle.sub_models]}")

    # 4. 保存模型
    model_path = TABLES / "distributed_model_midday_specialist_round9_lgb.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(bundle, f)
    print(f"  保存: {model_path}")

    # 5. 预测
    print("\n[Step 4] 预测...")
    pred_parts = {}
    for name, part in [("train", train), ("valid", valid), ("test", test)]:
        if part.empty:
            continue
        pred_ratio = predict_bundle(bundle, part)
        cap_arr = pd.to_numeric(part["capacity_mw"], errors="coerce").fillna(1.0).to_numpy()
        pred_mw = np.clip(pred_ratio * cap_arr, 0.0, cap_arr)
        part = part.copy()
        part["power_pred_midday_specialist_lgb"] = pred_mw

        y = pd.to_numeric(part["power_mw"], errors="coerce").to_numpy()
        nr = nrmse_pct(y, pred_mw, cap_arr)
        ma = mape_active(y, pred_mw)
        pred_parts[name] = part
        print(f"  {name}: nrmse={nr:.2f}%, mape={ma:.2f}%")

    # 6. 保存预测
    full_pred = pd.concat(list(pred_parts.values()), ignore_index=True)
    safe_pickle_dump(full_pred, TABLES / "distributed_predictions_midday_specialist_round9_lgb_full.pkl")

    if eval_df is not None:
        eval_pred = full_pred[full_pred["site_id"].isin(eval_df["site_id"].unique())].copy()
        eval_pred_h = eval_pred[eval_pred["hour"].isin(MIDDAY)].copy()
        safe_pickle_dump(eval_pred_h, TABLES / "distributed_predictions_midday_specialist_round9_lgb_eval.pkl")
        print(f"  评估集: distributed_predictions_midday_specialist_round9_lgb_eval.pkl")

    # 7. 与 MiddaySiteCalibrated 对比
    print("\n[Step 5] 与 MiddaySiteCalibrated 对比...")
    from pv_forecasting.core.evaluation import hourly_nrmse_metrics

    mscal_path = TABLES / "distributed_predictions_midday_site_calibrated_eval.pkl"
    if mscal_path.exists():
        mscal = safe_pickle_load(mscal_path)
        mscal_h = hourly_nrmse_metrics(mscal[mscal["hour"].isin(MIDDAY)])

        if eval_pred_h is not None:
            spec_h = hourly_nrmse_metrics(eval_pred_h)
            merged = mscal_h[["hour", "site_nrmse_mean_pct", "city_nrmse_pct"]].merge(
                spec_h[["hour", "site_nrmse_mean_pct", "city_nrmse_pct"]],
                on="hour", suffixes=("_mscal", "_spec")
            )
            merged["delta_pp"] = merged["site_nrmse_mean_pct_mscal"] - merged["site_nrmse_mean_pct_spec"]
            print(merged.to_string(index=False))

            n_ok = (merged["delta_pp"] > 0).sum()
            print(f"\n  改善: {n_ok}/{len(merged)} 小时")
            print(f"  平均改善: {merged['delta_pp'].mean():.3f} pp")

            merged.to_csv(METRICS / "round9_specialist_lgb_vs_mscal.csv", index=False, encoding="utf-8-sig")

    print("\n[OK] LightGBM Specialist 训练完成!")


if __name__ == "__main__":
    main()
