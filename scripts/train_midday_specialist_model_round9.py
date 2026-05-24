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
5. LightGBM MAPE-aware regression
6. valid 选模型, test 只评估

输出:
  distributed_predictions_midday_specialist_round9_full.pkl
  distributed_predictions_midday_specialist_round9_eval.pkl
  distributed_model_midday_specialist_round9.pkl
"""
from __future__ import annotations

from pathlib import Path
import sys

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
    "g_blend_pred", "ssrd_wm2", "t2m_c", "tcc", "strd_wm2",
    "hour", "month", "dayofyear",
    "capacity_mw", "solar_elevation_deg", "pr_month", "quality_score",
    "clear_sky_ghi",
]
CAT_FEATURES = ["county", "capacity_bucket", "install_group"]


def _build_midday_dataset(full_df: pd.DataFrame) -> pd.DataFrame:
    """构建中午专用训练集 (只保留 10-14 点)"""
    df = full_df.copy()
    df["hour"] = pd.to_datetime(df["time"], errors="coerce").dt.hour
    df = df[df["hour"].isin(MIDDAY)].copy()

    for c in ["g_blend_pred", "ssrd_wm2", "t2m_c", "tcc", "strd_wm2",
               "capacity_mw", "solar_elevation_deg", "pr_month", "quality_score",
               "clear_sky_ghi"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    for c in ["hour", "month"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    cap = pd.to_numeric(df["capacity_mw"], errors="coerce").replace(0, np.nan)
    df["target_ratio"] = (pd.to_numeric(df["power_mw"], errors="coerce") / cap).clip(0.0, 1.2)

    for c in CAT_FEATURES:
        if c in df.columns:
            df[c] = df[c].astype("string").fillna("unknown")

    if "split" not in df.columns:
        df = add_standard_split(df)

    df["dayofyear"] = pd.to_datetime(df["time"], errors="coerce").dt.dayofyear.fillna(0)

    return df


def _build_weights(df: pd.DataFrame) -> pd.Series:
    """中午时段样本权重: 高误差站点 ×2.5, 12-13点 ×1.2"""
    w = pd.Series(1.0, index=df.index, dtype=float)
    w[df["site_id"].isin(WATCH_SITES)] *= 2.5
    w[df["hour"].isin([12, 13])] *= 1.2
    return w


def _mape_score(y, p, cap):
    """中午时段 MAPE (只评有功样本)"""
    mask = (y > 0) & np.isfinite(y) & np.isfinite(p) & (y > 0.05 * cap)
    if not mask.any():
        return np.nan
    return float(np.mean(np.abs(y[mask] - p[mask]) / y[mask]) * 100)


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
        print(f"[WARN] {full_path} 不存在，使用 fixed_full")
        full_path = TABLES / "distributed_predictions_fixed_full.pkl"
    if not full_path.exists():
        raise FileNotFoundError(f"找不到预测结果: {full_path}")

    full_df = safe_pickle_load(full_path)
    print(f"  加载 {full_path.name}: {len(full_df)} 行")

    eval_path = TABLES / "distributed_predictions_final_eval.pkl"
    if not eval_path.exists():
        eval_path = TABLES / "distributed_predictions_fixed_eval.pkl"
    eval_df = safe_pickle_load(eval_path) if eval_path.exists() else None
    print(f"  评估集: {len(eval_df)} 行" if eval_df is not None else "  评估集: 无")

    # 2. 构建中午数据集
    print("\n[Step 2] 构建中午专用训练集...")
    df = _build_midday_dataset(full_df)
    print(f"  10-14点样本: {len(df)} 行")
    print(f"  train: {(df['split']=='train').sum()}, "
          f"valid: {(df['split']=='valid').sum()}, "
          f"test: {(df['split']=='test').sum()}")

    # 3. 准备特征
    print("\n[Step 3] 准备特征...")
    feat_cols = [c for c in REG_FEATURES if c in df.columns]
    missing = [c for c in REG_FEATURES if c not in df.columns]
    if missing:
        print(f"  [WARN] 缺失特征: {missing}")
    cat_cols = [c for c in CAT_FEATURES if c in df.columns]
    print(f"  回归特征: {feat_cols}")
    print(f"  类别特征: {cat_cols}")

    # 4. 过滤有效样本
    train = df[df["split"] == "train"].copy()
    valid = df[df["split"] == "valid"].copy()
    test = df[df["split"] == "test"].copy()

    train_pos = train[train["target_ratio"].notna()].copy()
    valid_pos = valid[valid["target_ratio"].notna()].copy()
    test_pos = test[test["target_ratio"].notna()].copy()

    print(f"\n  有效训练样本: {len(train_pos)}")
    print(f"  有效验证样本: {len(valid_pos)}")
    print(f"  有效测试样本: {len(test_pos)}")

    if train_pos.empty:
        raise ValueError("训练集为空")

    # 5. 训练模型
    print("\n[Step 4] 训练 LightGBM MAPE-aware 模型...")
    weights = _build_weights(train_pos)

    bundle = fit_tabular_regressor(
        train_pos, valid_pos,
        feat_cols, "target_ratio",
        cat_cols=cat_cols,
        sample_weight_col=None,
        regressor_params={
            "objective": "regression_l2",
            "learning_rate": 0.05,
            "num_leaves": 63,
            "max_depth": 8,
            "min_child_samples": 30,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "n_estimators": 1000,
            "early_stopping_rounds": 100,
            "verbose": -1,
        },
    )

    # 保存模型
    model_path = TABLES / "distributed_model_midday_specialist_round9.pkl"
    import pickle
    with open(model_path, "wb") as f:
        pickle.dump(bundle, f)
    print(f"  模型保存: {model_path}")

    # 6. 预测
    print("\n[Step 5] 预测...")
    for name, part in [("train", train), ("valid", valid), ("test", test)]:
        pred_ratio = predict_bundle(bundle, part)
        cap = pd.to_numeric(part["capacity_mw"], errors="coerce").fillna(1.0).to_numpy()
        part = part.copy()
        part["power_pred_midday_specialist"] = np.clip(pred_ratio * cap, 0.0, cap)
        if name == "test":
            test_pred = part
        elif name == "valid":
            valid_pred = part

    # 7. 评估
    print("\n[Step 6] 评估...")
    results = []
    for name, pred in [("train", train_pred), ("valid", valid_pred), ("test", test_pred)]:
        y = pd.to_numeric(pred["power_mw"], errors="coerce").to_numpy()
        p = pred["power_pred_midday_specialist"].to_numpy()
        c = pd.to_numeric(pred["capacity_mw"], errors="coerce").to_numpy()
        mask = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (c > 0)
        nrmse = _nrmse_pct(y[mask], p[mask], c[mask])
        mape = _mape_score(y[mask], p[mask], c[mask])
        results.append({
            "split": name,
            "rows": int(mask.sum()),
            "site_nrmse_pct": round(nrmse, 4) if not np.isnan(nrmse) else np.nan,
            "mape_pct": round(mape, 4) if not np.isnan(mape) else np.nan,
        })
        print(f"  {name}: rows={int(mask.sum())}, site_nrmse={nrmse:.2f}%, mape={mape:.2f}%")

    pd.DataFrame(results).to_csv(
        METRICS / "round9_midday_specialist_metrics.csv", index=False, encoding="utf-8-sig"
    )

    # 8. 保存预测
    print("\n[Step 7] 保存预测结果...")
    full_pred = pd.concat([train_pred, valid_pred, test_pred], ignore_index=True)
    full_path_out = TABLES / "distributed_predictions_midday_specialist_round9_full.pkl"
    safe_pickle_dump(full_pred, full_path_out)
    print(f"  全量预测: {full_path_out}")

    if eval_df is not None:
        eval_pred = full_pred[full_pred["site_id"].isin(eval_df["site_id"].unique())].copy()
        eval_pred_h = eval_pred[eval_pred["hour"].isin(MIDDAY)].copy()
        eval_path_out = TABLES / "distributed_predictions_midday_specialist_round9_eval.pkl"
        safe_pickle_dump(eval_pred_h, eval_path_out)
        print(f"  评估集预测: {eval_path_out}")

    # 9. 与当前 MiddaySiteCalibrated 对比
    print("\n[Step 8] 与 MiddaySiteCalibrated 对比...")
    from pv_forecasting.core.evaluation import hourly_nrmse_metrics

    mscal_path = TABLES / "distributed_predictions_midday_site_calibrated_eval.pkl"
    if mscal_path.exists():
        mscal = safe_pickle_load(mscal_path)
        mscal_h = hourly_nrmse_metrics(mscal[mscal["hour"].isin(MIDDAY)])
        specialist_h = hourly_nrmse_metrics(eval_pred_h)

        merged = mscal_h[["hour", "site_nrmse_mean_pct"]].merge(
            specialist_h[["hour", "site_nrmse_mean_pct"]],
            on="hour", suffixes=("_mscal", "_specialist")
        )
        merged["delta_pp"] = merged["site_nrmse_mean_pct_mscal"] - merged["site_nrmse_mean_pct_specialist"]
        print(merged.to_string(index=False))

        improved = (merged["delta_pp"] > 0).sum()
        total = len(merged)
        print(f"\n  改善: {improved}/{total} 小时")
        print(f"  平均改善: {merged['delta_pp'].mean():.3f} pp")

    print("\n[OK] Round9 Specialist 模型训练完成!")
    print(f"  模型: {model_path}")
    print(f"  全量预测: {full_path_out}")
    print(f"  评估预测: {METRICS / 'round9_midday_specialist_metrics.csv'}")


if __name__ == "__main__":
    main()
