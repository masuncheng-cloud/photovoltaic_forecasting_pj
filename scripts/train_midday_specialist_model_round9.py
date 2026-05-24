#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round9 10-14点专用模型训练（sklearn 版）
==========================================
使用 sklearn 的 HistGradientBoostingRegressor，直接从 final_full.pkl 训练
"""
from __future__ import annotations

from pathlib import Path
import sys, pickle

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import OrdinalEncoder

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pv_forecasting.core.utils import safe_pickle_load, safe_pickle_dump
from pv_forecasting.core.split import add_standard_split

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

MIDDAY = [10, 11, 12, 13, 14]
WATCH_SITES = {"S012", "S055", "S050", "S032", "S019", "S053", "S116", "S052"}

NUM_FEATURES = [
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
    print("Round9 中午专用模型训练 (sklearn HistGBDT)")
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

    # 2. 预处理
    print("\n[Step 2] 预处理...")
    df = full_df.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df["hour"] = df["time"].dt.hour
    df["month"] = df["time"].dt.month
    df["dayofyear"] = df["time"].dt.dayofyear
    df = df[df["hour"].isin(MIDDAY)].copy()

    for c in NUM_FEATURES:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    for c in CAT_FEATURES:
        if c in df.columns:
            df[c] = df[c].astype(str).fillna("unknown")

    cap = pd.to_numeric(df["capacity_mw"], errors="coerce").replace(0, np.nan)
    df["target_ratio"] = (pd.to_numeric(df["power_mw"], errors="coerce") / cap).clip(0.0, 1.2)

    df["weight"] = 1.0
    df.loc[df["site_id"].isin(WATCH_SITES), "weight"] = 2.5
    df.loc[df["hour"].isin([12, 13]), "weight"] *= 1.2

    if "split" not in df.columns:
        df = add_standard_split(df)

    train = df[df["split"] == "train"].copy()
    valid = df[df["split"] == "valid"].copy()
    test = df[df["split"] == "test"].copy()

    train_pos = train[train["target_ratio"].notna()].copy()
    valid_pos = valid[valid["target_ratio"].notna()].copy()
    test_pos = test[test["target_ratio"].notna()].copy()

    print(f"  train: {len(train_pos)}, valid: {len(valid_pos)}, test: {len(test_pos)}")

    feat_num = [c for c in NUM_FEATURES if c in df.columns]
    feat_cat = [c for c in CAT_FEATURES if c in df.columns]
    print(f"  数值特征: {feat_num}")
    print(f"  类别特征: {feat_cat}")

    # 3. 编码类别特征
    print("\n[Step 3] 编码类别特征...")
    X_train_num = train_pos[feat_num].values.astype(float)
    X_valid_num = valid_pos[feat_num].values.astype(float)
    X_test_num = test_pos[feat_num].values.astype(float)

    if feat_cat:
        from sklearn.preprocessing import OrdinalEncoder
        all_cat_values = pd.concat([
            train_pos[feat_cat],
            valid_pos[feat_cat],
            test_pos[feat_cat],
        ]).values.astype(str)
        enc = OrdinalEncoder(dtype=np.float64)
        enc.fit(all_cat_values.reshape(-1, len(feat_cat)))
        X_train_cat = enc.transform(train_pos[feat_cat].values.astype(str)).flatten()
        X_valid_cat = enc.transform(valid_pos[feat_cat].values.astype(str)).flatten()
        X_test_cat = enc.transform(test_pos[feat_cat].values.astype(str)).flatten()
        X_train = np.column_stack([X_train_num, X_train_cat])
        X_valid = np.column_stack([X_valid_num, X_valid_cat])
        X_test = np.column_stack([X_test_num, X_test_cat])
    else:
        X_train = X_train_num
        X_valid = X_valid_num
        X_test = X_test_num

    y_train = train_pos["target_ratio"].values.astype(float)
    w_train = train_pos["weight"].values.astype(float)

    print(f"  X_train: {X_train.shape}, dtype: {X_train.dtype}")

    # 4. 训练
    print("\n[Step 4] 训练 HistGradientBoostingRegressor...")
    model = HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.05,
        max_iter=500,
        max_depth=8,
        max_leaf_nodes=63,
        min_samples_leaf=30,
        l2_regularization=0.5,
        early_stopping=True,
        n_iter_no_change=30,
        validation_fraction=0.1,
        random_state=42,
        verbose=0,
    )
    model.fit(X_train, y_train, sample_weight=w_train)
    print(f"  训练完成: {model.n_iter_} iterations")

    # 5. 预测
    print("\n[Step 5] 预测...")
    results = []
    for name, X_part, part in [("train", X_train, train_pos), ("valid", X_valid, valid_pos), ("test", X_test, test_pos)]:
        pred_ratio = model.predict(X_part)
        cap_arr = pd.to_numeric(part["capacity_mw"], errors="coerce").fillna(1.0).values
        pred_mw = np.clip(pred_ratio * cap_arr, 0.0, cap_arr)

        y = pd.to_numeric(part["power_mw"], errors="coerce").values
        nr = nrmse_pct(y, pred_mw, cap_arr)
        ma = mape_active(y, pred_mw)

        part = part.copy()
        part["power_pred_midday_specialist"] = pred_mw
        if name == "test":
            test_pred = part
        elif name == "valid":
            valid_pred = part
        elif name == "train":
            train_pred = part

        results.append({"split": name, "rows": len(part), "nrmse_pct": round(nr, 4), "mape_pct": round(ma, 4)})
        print(f"  {name}: nrmse={nr:.2f}%, mape={ma:.2f}%")

    pd.DataFrame(results).to_csv(METRICS / "round9_specialist_metrics.csv", index=False, encoding="utf-8-sig")

    # 6. 保存模型
    model_path = TABLES / "distributed_model_midday_specialist_round9.pkl"
    bundle = {
        "model": model,
        "feat_num": feat_num,
        "feat_cat": feat_cat,
        "cat_encoder": enc if feat_cat else None,
    }
    with open(model_path, "wb") as f:
        pickle.dump(bundle, f)
    print(f"\n  模型: {model_path}")

    # 7. 保存预测
    full_pred = pd.concat([train_pred, valid_pred, test_pred], ignore_index=True)
    safe_pickle_dump(full_pred, TABLES / "distributed_predictions_midday_specialist_round9_full.pkl")

    if eval_df is not None:
        eval_pred = full_pred[full_pred["site_id"].isin(eval_df["site_id"].unique())].copy()
        eval_pred_h = eval_pred[eval_pred["hour"].isin(MIDDAY)].copy()
        safe_pickle_dump(eval_pred_h, TABLES / "distributed_predictions_midday_specialist_round9_eval.pkl")

    # 8. 与 MiddaySiteCalibrated 对比
    print("\n[Step 6] 与 MiddaySiteCalibrated 对比...")
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

            n_improved = (merged["delta_pp"] > 0).sum()
            print(f"\n  Specialist 改善: {n_improved}/{len(merged)} 小时")
            print(f"  平均改善: {merged['delta_pp'].mean():.3f} pp")

            # 保存对比
            merged.to_csv(METRICS / "round9_specialist_vs_mscal_hourly.csv", index=False, encoding="utf-8-sig")

    # 9. 逐站点明细
    print("\n[Step 7] 站点级明细...")
    if eval_pred_h is not None:
        site_rows = []
        for sid in sorted(eval_pred_h["site_id"].unique()):
            for h in MIDDAY:
                sg = eval_pred_h[(eval_pred_h["site_id"] == sid) & (eval_pred_h["hour"] == h)]
                if len(sg) == 0:
                    continue
                y = pd.to_numeric(sg["power_mw"], errors="coerce").values
                p = sg["power_pred_midday_specialist"].values
                c = pd.to_numeric(sg["capacity_mw"], errors="coerce").fillna(1.0).values
                nr = nrmse_pct(y, p, c)
                site_rows.append({
                    "site_id": sid, "hour": h,
                    "specialist_nrmse_pct": round(nr, 4) if not np.isnan(nr) else np.nan,
                })
        pd.DataFrame(site_rows).to_csv(
            METRICS / "round9_specialist_site_hourly_nrmse.csv", index=False, encoding="utf-8-sig"
        )
        print(f"  站点明细: round9_specialist_site_hourly_nrmse.csv")

    print("\n[OK] 完成!")


if __name__ == "__main__":
    main()
