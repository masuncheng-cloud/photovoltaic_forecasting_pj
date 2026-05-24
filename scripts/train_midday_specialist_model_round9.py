#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round9 10-14点专用模型训练
=====================================
目标: 专门针对中午时段优化，降低 10-14 点站点平均 NRMSE

关键设计:
1. 只训练 10-14 点样本
2. 目标: power_mw / capacity_mw (归一化功率)
3. 样本权重: 高误差站点 ×2.5, 12-13点 ×1.2
4. 特征: 辐照融合 + 气象 + 时间 + 站点属性
5. LightGBM + CatBoost 集成
6. valid 选模型, test 只评估

输出:
  distributed_predictions_midday_specialist_round9_full.pkl
  distributed_predictions_midday_specialist_round9_eval.pkl
  distributed_model_midday_specialist_round9.pkl
"""
from __future__ import annotations

from pathlib import Path
import sys
import pickle

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

# 高误差站点 (Round9 诊断确认)
WATCH_SITES = {"S012", "S055", "S050", "S032", "S019", "S053", "S116", "S052"}

REG_FEATURES = [
    "g_blend_pred", "clear_sky_ghi",
    "hour", "month", "dayofyear",
    "capacity_mw", "quality_score",
]
CAT_FEATURES = ["county", "capacity_bucket", "install_group"]


def _nrmse_pct(y, p, cap):
    mask = np.isfinite(y) & np.isfinite(p) & (cap > 0)
    if not mask.any():
        return np.nan
    rmse = np.sqrt(np.mean((y[mask] - p[mask]) ** 2))
    return float(rmse / np.nanmean(cap[mask]) * 100)


def main():
    print("=" * 70)
    print("Round9 中午专用模型训练")
    print("=" * 70)

    # 1. 加载数据
    print("\n[Step 1] 加载数据...")
    full_path = TABLES / "distributed_predictions_final_full.pkl"
    if not full_path.exists():
        print(f"  [WARN] {full_path} 不存在，使用 fixed_full")
        full_path = TABLES / "distributed_predictions_fixed_full.pkl"
    full_df = safe_pickle_load(full_path)
    print(f"  全量: {len(full_df)} 行, columns: {list(full_df.columns)}")

    eval_path = TABLES / "distributed_predictions_final_eval.pkl"
    eval_path = eval_path if eval_path.exists() else TABLES / "distributed_predictions_fixed_eval.pkl"
    eval_df = safe_pickle_load(eval_path) if eval_path.exists() else None
    print(f"  评估集: {len(eval_df)} 行" if eval_df is not None else "  评估集: 无")

    # 2. 预处理
    print("\n[Step 2] 预处理...")
    df = full_df.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df["hour"] = df["time"].dt.hour
    df["month"] = df["time"].dt.month
    df["dayofyear"] = df["time"].dt.dayofyear

    # 只保留 10-14 点
    df = df[df["hour"].isin(MIDDAY)].copy()
    print(f"  10-14 点样本: {len(df)} 行")

    # 数值特征
    for c in REG_FEATURES:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    # 类别特征
    for c in CAT_FEATURES:
        if c in df.columns:
            df[c] = df[c].astype("string").fillna("unknown")

    # 目标
    cap = pd.to_numeric(df["capacity_mw"], errors="coerce").replace(0, np.nan)
    df["target_ratio"] = (pd.to_numeric(df["power_mw"], errors="coerce") / cap).clip(0.0, 1.2)

    # 样本权重列
    df["sample_weight_round9"] = 1.0
    df.loc[df["site_id"].isin(WATCH_SITES), "sample_weight_round9"] = 2.5
    df.loc[df["hour"].isin([12, 13]), "sample_weight_round9"] *= 1.2

    if "split" not in df.columns:
        df = add_standard_split(df)

    train = df[df["split"] == "train"].copy()
    valid = df[df["split"] == "valid"].copy()
    test = df[df["split"] == "test"].copy()

    train_pos = train[train["target_ratio"].notna()].copy()
    valid_pos = valid[valid["target_ratio"].notna()].copy()
    test_pos = test[test["target_ratio"].notna()].copy()

    print(f"  train: {len(train_pos)}, valid: {len(valid_pos)}, test: {len(test_pos)}")

    # 可用特征
    feat_cols = [c for c in REG_FEATURES if c in df.columns]
    cat_cols = [c for c in CAT_FEATURES if c in df.columns]
    missing = [c for c in REG_FEATURES if c not in df.columns]
    if missing:
        print(f"  [WARN] 缺失特征: {missing}")
    print(f"  回归特征: {feat_cols}")
    print(f"  类别特征: {cat_cols}")
    print(f"  权重: 高误差站点 ×2.5, 12-13点 ×1.2")

    # 3. 训练
    print("\n[Step 3] 训练 (CatBoost + LightGBM 集成)...")
    task_params = {
        "iterations": 1500,
        "depth": 7,
        "learning_rate": 0.05,
        "early_stopping_rounds": 100,
    }
    bundle = fit_tabular_regressor(
        train_pos, valid_pos,
        feat_cols, "target_ratio",
        cat_cols=cat_cols,
        sample_weight_col="sample_weight_round9",
        task_params=task_params,
    )
    print(f"  模型类型: {bundle.model_type}")

    model_path = TABLES / "distributed_model_midday_specialist_round9.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(bundle, f)
    print(f"  保存: {model_path}")

    # 4. 预测
    print("\n[Step 4] 预测...")
    pred_parts = {}
    for name, part in [("train", train), ("valid", valid), ("test", test)]:
        if part.empty:
            continue
        pred_ratio = predict_bundle(bundle, part)
        cap_arr = pd.to_numeric(part["capacity_mw"], errors="coerce").fillna(1.0).to_numpy()
        pred_mw = np.clip(pred_ratio * cap_arr, 0.0, cap_arr)
        part = part.copy()
        part["power_pred_midday_specialist"] = pred_mw
        pred_parts[name] = part
        # 评估
        y = pd.to_numeric(part["power_mw"], errors="coerce").to_numpy()
        p = pred_mw
        c = cap_arr
        nrmse = _nrmse_pct(y, p, c)
        print(f"  {name}: rows={len(part)}, site_nrmse={nrmse:.2f}%")

    # 5. 保存
    full_pred = pd.concat(list(pred_parts.values()), ignore_index=True)
    safe_pickle_dump(full_pred, TABLES / "distributed_predictions_midday_specialist_round9_full.pkl")
    print(f"\n  全量预测: distributed_predictions_midday_specialist_round9_full.pkl")

    if eval_df is not None:
        eval_pred = full_pred[full_pred["site_id"].isin(eval_df["site_id"].unique())].copy()
        eval_pred_h = eval_pred[eval_pred["hour"].isin(MIDDAY)].copy()
        safe_pickle_dump(eval_pred_h, TABLES / "distributed_predictions_midday_specialist_round9_eval.pkl")
        print(f"  评估集预测: distributed_predictions_midday_specialist_round9_eval.pkl")

    # 6. 与 MiddaySiteCalibrated 对比
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
                on="hour", suffixes=("", "_spec")
            )
            merged = merged.rename(columns={
                "site_nrmse_mean_pct": "mscal_pct",
                "city_nrmse_pct": "mscal_city_pct",
                "site_nrmse_mean_pct_spec": "specialist_pct",
                "city_nrmse_pct_spec": "specialist_city_pct",
            })
            merged["delta_pp"] = merged["mscal_pct"] - merged["specialist_pct"]
            print(merged.to_string(index=False))

            improved = (merged["delta_pp"] > 0).sum()
            print(f"\n  Specialist 改善: {improved}/{len(merged)} 小时")
            print(f"  平均改善: {merged['delta_pp'].mean():.3f} pp")

    # 7. 站点明细
    print("\n[Step 6] 站点级明细 (Round9 vs MiddaySiteCalibrated)...")
    if eval_pred_h is not None:
        site_results = []
        for sid in sorted(eval_pred_h["site_id"].unique()):
            for hour_key in MIDDAY:
                sg = eval_pred_h[(eval_pred_h["site_id"] == sid) & (eval_pred_h["hour"] == hour_key)]
                if len(sg) == 0:
                    continue
                y = pd.to_numeric(sg["power_mw"], errors="coerce").to_numpy()
                p = sg["power_pred_midday_specialist"].to_numpy()
                c = pd.to_numeric(sg["capacity_mw"], errors="coerce").fillna(1.0).to_numpy()
                nrmse = _nrmse_pct(y, p, c)
                site_results.append({
                    "site_id": sid, "hour": hour_key,
                    "specialist_nrmse_pct": round(nrmse, 4) if not np.isnan(nrmse) else np.nan,
                })

        pd.DataFrame(site_results).to_csv(
            METRICS / "round9_specialist_hourly_site_nrmse.csv", index=False, encoding="utf-8-sig"
        )
        print(f"  站点明细: round9_specialist_hourly_site_nrmse.csv")

    print("\n[OK] Round9 Specialist 模型训练完成!")


if __name__ == "__main__":
    main()
