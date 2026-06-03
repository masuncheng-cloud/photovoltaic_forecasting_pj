#!/usr/bin/env python3
"""
build_round72_consistent_base_prediction.py
========================================
核心目标：为 train/valid/test 生成口径一致的全历史基线预测。

策略：
- 对 train：用时间滚动 OOF 方式训练 LGB，在更早数据上训练，预测更晚数据
- 对 valid/test：直接使用 power_pred_final（已有多轮优化）
- fallback：无法 OOF 覆盖的早期训练行用 power_pred_round61_city_safe

输出：
    output/pv_pipeline/round72/round72_consistent_base_predictions.pkl
    output/pv_pipeline/round72/round72_consistent_base_source_summary.csv
    output/pv_pipeline/round72/round72_oof_fold_metrics.csv
"""

import argparse
import json
import math
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from lightgbm import LGBMRegressor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round72"

warnings.filterwarnings("ignore", message="X does not have valid feature names")


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def prep_X(df, feats):
    cols = [c for c in feats if c in df.columns]
    return pd.DataFrame(df[cols]).apply(pd.to_numeric, errors="coerce").fillna(0).values.astype(float)


FEATURES = [
    "hour", "month", "dayofyear",
    "latitude", "longitude", "capacity_mw",
    "g_blend_pred", "clear_sky_ghi", "clear_sky_index",
    "scene_v151",
    "site_zero_ratio_6_19",
    "pr_median", "quality_score",
    "pred_baseline",
]


def main():
    parser = argparse.ArgumentParser(description="Round72 OOF 一致基线预测")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    if args.config is None:
        args.config = str(PROJECT_ROOT / "configs" / "round72_consistent_base.yaml")
    cfg = yaml.safe_load(open(args.config))

    OUT.mkdir(parents=True, exist_ok=True)

    # ── 读取数据 ─────────────────────────────────────────────────────────
    input_path = PROJECT_ROOT / cfg["input_pkl"]
    print(f"[INFO] 读取: {input_path}")
    df = pd.read_pickle(input_path)
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    df["month"] = df["time"].dt.month
    df["dayofyear"] = df["time"].dt.dayofyear
    print(f"  总行数: {len(df):,}")

    # 过滤
    df = df[df["split"] != "future"].copy()
    df = df[df["hour"].between(6, 19)].copy()
    df = df[df["capacity_mw"] > 0].copy()
    print(f"  过滤后: {len(df):,}  行")

    bl_final = cfg["baseline_final_col"]
    bl_consistent = cfg["consistent_base_col"]
    cap_col = cfg["capacity_col"]
    target_col = cfg["target_col"]

    # 初始化
    df[bl_consistent] = np.nan
    df["_base_source"] = "unknown"

    # ── 对 train 用 OOF ────────────────────────────────────────────────
    train_df = df[df["split"] == "train"].copy()
    valid_df = df[df["split"] == "valid"].copy()
    test_df = df[df["split"] == "test"].copy()

    # 可用特征
    available_feats = [f for f in FEATURES if f in train_df.columns]
    print(f"\n[INFO] 可用特征: {len(available_feats)} 个")

    # 滚动 OOF folds（按时间顺序）
    folds = cfg.get("oof", {}).get("folds", [])
    if not folds:
        # 自动构造：如果配置中没有，基于数据自动切
        folds = [
            {"train_end": "2024-06-30", "valid_start": "2024-07-01", "valid_end": "2025-06-30"},
            {"train_end": "2023-12-31", "valid_start": "2024-01-01", "valid_end": "2024-06-30"},
            {"train_end": "2023-06-30", "valid_start": "2023-07-01", "valid_end": "2023-12-31"},
        ]

    # 去掉与 train 时间重叠的 fold
    valid_period = (train_df["time"] >= "2025-07-01") & (train_df["time"] <= "2025-08-31")
    train_latest = train_df[~valid_period].copy()

    fold_metrics = []
    oof_predictions = {}

    for fi, fold in enumerate(folds):
        tr_end = pd.Timestamp(fold["train_end"])
        va_start = pd.Timestamp(fold["valid_start"])
        va_end = pd.Timestamp(fold["valid_end"])

        fold_train = train_latest[
            (train_latest["time"] <= tr_end) &
            train_latest[target_col].notna()
        ].copy()
        fold_valid = train_latest[
            (train_latest["time"] >= va_start) &
            (train_latest["time"] <= va_end) &
            train_latest[target_col].notna()
        ].copy()

        if len(fold_train) < 500 or len(fold_valid) < 100:
            print(f"  [Fold {fi+1}] 跳过：train={len(fold_train)} valid={len(fold_valid)}")
            continue

        print(f"\n[Fold {fi+1}] train<={tr_end.date()} → valid {va_start.date()}~{va_end.date()}")
        print(f"  train: {len(fold_train):,}  valid: {len(fold_valid):,}")

        # 训练集：只保留有过往数据支撑的样本（至少过去30天有数据）
        min_history = 30
        min_time = va_start - pd.Timedelta(days=min_history)
        fold_train_hist = fold_train[fold_train["time"] <= min_time].copy()

        X_tr = prep_X(fold_train_hist, available_feats)
        y_tr = (fold_train_hist[target_col] / fold_train_hist[cap_col].clip(lower=1e-6)).clip(0, 1).values

        X_va = prep_X(fold_valid, available_feats)
        y_va = fold_valid[target_col].values

        m = cfg.get("model", {})
        model = LGBMRegressor(
            n_estimators=m.get("n_estimators", 500),
            max_depth=m.get("max_depth", 8),
            num_leaves=m.get("num_leaves", 63),
            learning_rate=m.get("learning_rate", 0.05),
            reg_lambda=m.get("reg_lambda", 2.0),
            reg_alpha=m.get("reg_alpha", 0.5),
            min_child_samples=m.get("min_child_samples", 30),
            subsample=m.get("subsample", 0.8),
            colsample_bytree=m.get("colsample_bytree", 0.8),
            random_state=42, n_jobs=-1, verbose=-1,
        )
        model.fit(X_tr, y_tr)

        # OOF 预测
        pred_norm = model.predict(X_va)
        cap_va = fold_valid[cap_col].values
        pred_mw = np.clip(pred_norm * cap_va, 0, cap_va)

        # 记录到 oof_predictions
        for idx, row_idx in zip(pred_mw, fold_valid.index):
            oof_predictions[row_idx] = float(idx)

        # Fold 指标
        cap_sum = float(fold_valid[cap_col].sum())
        fold_rmse = rmse(y_va, pred_mw)
        fold_nrmse = fold_rmse / cap_sum * 100 if cap_sum > 0 else np.nan
        a_sum = float(y_va.sum())
        p_sum = float(pred_mw.sum())
        fold_bias = (p_sum - a_sum) / a_sum * 100 if abs(a_sum) > 1e-9 else np.nan
        fold_mae = float(np.nanmean(np.abs(y_va - pred_mw)))

        print(f"  OOF: nrmse={fold_nrmse:.3f}%  bias={fold_bias:.3f}%  mae={fold_mae:.4f}")
        fold_metrics.append({
            "fold": fi + 1,
            "train_end": str(tr_end.date()),
            "valid_start": str(va_start.date()),
            "valid_end": str(va_end.date()),
            "n_train": len(fold_train_hist),
            "n_valid": len(fold_valid),
            "oof_nrmse": round(fold_nrmse, 4),
            "oof_bias": round(fold_bias, 4),
            "oof_mae": round(fold_mae, 4),
        })

    pd.DataFrame(fold_metrics).to_csv(
        OUT / "round72_oof_fold_metrics.csv", index=False, encoding="utf-8-sig")
    print(f"\n[OK] OOF fold 指标: {OUT / 'round72_oof_fold_metrics.csv'}")

    # ── 应用 OOF 预测到 train ──────────────────────────────────────────
    print(f"\n[INFO] 应用 OOF 预测到 train ({len(oof_predictions):,} 行)...")
    train_df.loc[train_df.index.isin(oof_predictions.keys()), bl_consistent] = \
        train_df.loc[train_df.index.isin(oof_predictions.keys())].index.map(oof_predictions)
    train_df.loc[train_df.index.isin(oof_predictions.keys()), "_base_source"] = "oof"

    # ── 填充 fallback ────────────────────────────────────────────────
    # 对于 OOF 未覆盖的训练行（早期数据），用 power_pred_round61_city_safe
    fallback_mask = train_df[bl_consistent].isna()
    n_fallback = fallback_mask.sum()
    print(f"[INFO] OOF 未覆盖行: {n_fallback:,}  ({n_fallback/len(train_df)*100:.1f}%)")

    if n_fallback > 0:
        # 优先用 power_pred_round61_city_safe
        if "power_pred_round61_city_safe" in train_df.columns:
            train_df.loc[fallback_mask, bl_consistent] = \
                train_df.loc[fallback_mask, "power_pred_round61_city_safe"].values
            train_df.loc[fallback_mask, "_base_source"] = "fallback_round61"
            print(f"  回退到 power_pred_round61_city_safe: {n_fallback:,} 行")
        else:
            # 最后 fallback 到 power_pred
            train_df.loc[fallback_mask, bl_consistent] = \
                train_df.loc[fallback_mask, "power_pred"].values
            train_df.loc[fallback_mask, "_base_source"] = "fallback_power_pred"
            print(f"  回退到 power_pred: {n_fallback:,} 行")

    # ── 对 valid/test 使用 power_pred_final ───────────────────────────
    print("\n[INFO] valid/test 使用 power_pred_final...")
    if bl_final in valid_df.columns:
        valid_df[bl_consistent] = valid_df[bl_final].copy()
        valid_df["_base_source"] = "power_pred_final"
        n_final = valid_df[bl_consistent].notna().sum()
        print(f"  valid: {n_final}/{len(valid_df)} 行使用 power_pred_final")
    else:
        valid_df[bl_consistent] = valid_df["power_pred"].values
        valid_df["_base_source"] = "fallback_power_pred"

    if bl_final in test_df.columns:
        test_df[bl_consistent] = test_df[bl_final].copy()
        test_df["_base_source"] = "power_pred_final"
        n_final = test_df[bl_consistent].notna().sum()
        print(f"  test:  {n_final}/{len(test_df)} 行使用 power_pred_final")
    else:
        test_df[bl_consistent] = test_df["power_pred"].values
        test_df["_base_source"] = "fallback_power_pred"

    # ── 组装完整数据 ──────────────────────────────────────────────────
    full_df = pd.concat([train_df, valid_df, test_df], ignore_index=True)

    # 质量检查
    null_total = full_df[bl_consistent].isna().sum()
    null_train = full_df[full_df["split"]=="train"][bl_consistent].isna().sum()
    null_valid = full_df[full_df["split"]=="valid"][bl_consistent].isna().sum()
    null_test = full_df[full_df["split"]=="test"][bl_consistent].isna().sum()
    print(f"\n[Quality] 一致基线 null 数量: train={null_train}  valid={null_valid}  test={null_test}  total={null_total}")

    if null_total > 0:
        print(f"[WARN] 一致基线仍有 {null_total} 行空值！")
        full_df.loc[full_df[bl_consistent].isna(), bl_consistent] = 0.0
        full_df.loc[full_df[bl_consistent].isna(), "_base_source"] = "null_fill_zero"

    # 源分布
    source_summary = full_df.groupby(["split", "_base_source"]).size().reset_index(name="n_rows")
    source_summary["pct"] = source_summary["n_rows"] / source_summary.groupby("split")["n_rows"].transform("sum") * 100
    source_summary.to_csv(
        OUT / "round72_consistent_base_source_summary.csv", index=False, encoding="utf-8-sig")
    print(f"\n[OK] 源分布: {OUT / 'round72_consistent_base_source_summary.csv'}")
    print(source_summary.to_string(index=False))

    # ── 基础质量报告 ──────────────────────────────────────────────────
    quality_rows = []
    for sname, sdf in full_df.groupby("split"):
        valid_rows = sdf[sdf[target_col].notna() & sdf[bl_consistent].notna()]
        if len(valid_rows) == 0:
            continue
        a = valid_rows[target_col].values
        p = valid_rows[bl_consistent].values
        cap_sum = float(valid_rows[cap_col].sum())
        quality_rows.append({
            "split": sname,
            "n_rows": len(sdf),
            "n_valid": len(valid_rows),
            "null_consistent_base": sdf[bl_consistent].isna().sum(),
            "mean_base_pred": round(float(p.mean()), 4),
            "mean_actual": round(float(a.mean()), 4),
            "oof_nrmse_pct": round(rmse(a, p) / cap_sum * 100, 4) if cap_sum > 0 else None,
            "oof_bias_pct": round((p.sum() - a.sum()) / a.sum() * 100, 4) if a.sum() > 1e-9 else None,
        })

    quality_df = pd.DataFrame(quality_rows)
    quality_df.to_csv(OUT / "round72_consistent_base_quality.csv",
                      index=False, encoding="utf-8-sig")
    print(f"\n[OK] 质量报告: {OUT / 'round72_consistent_base_quality.csv'}")
    print(quality_df.to_string(index=False))

    # ── 保存 ──────────────────────────────────────────────────────────
    out_pkl = OUT / "round72_consistent_base_predictions.pkl"
    full_df.to_pickle(out_pkl)
    print(f"\n[OK] 一致基线预测: {out_pkl}  ({len(full_df):,} 行)")
    print(f"  source 分布: {dict(full_df['_base_source'].value_counts())}")

    # 验证 valid/test 与 final 差异
    if bl_final in full_df.columns:
        for sname in ["valid", "test"]:
            sdf = full_df[full_df["split"] == sname]
            if bl_final in sdf.columns and bl_consistent in sdf.columns:
                diff = (sdf[bl_consistent] - sdf[bl_final]).abs()
                print(f"  {sname}: consistent_base vs final max_diff={diff.max():.6f}  mean_diff={diff.mean():.6f}")

    print("\n[OK] build_round72_consistent_base_prediction 完成!")


if __name__ == "__main__":
    main()
