#!/usr/bin/env python3
"""
train_round73_backtest_candidates.py
=============================
基于回测窗口训练 Round73 候选模型。

候选：
    A: power_pred_round73_autumn_winter_residual
    B: power_pred_round73_noon_bias_guard
    C: power_pred_round73_high_error_shrinkage

输出：
    output/pv_pipeline/round73/round73_candidates.pkl
    output/pv_pipeline/round73/round73_candidate_training_summary.csv
    output/pv_pipeline/round73/round73_candidate_diff_check.csv
"""

import argparse
import math
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from lightgbm import LGBMRegressor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round73"

warnings.filterwarnings("ignore")


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def prep_X(df, feats):
    cols = [c for c in feats if c in df.columns]
    return pd.DataFrame(df[cols]).apply(pd.to_numeric, errors="coerce").fillna(0).values.astype(float)


def compute_city_nrmse(df, pred_col):
    cap_sum = float(df.drop_duplicates("site_id")["capacity_mw"].sum())
    agg = df.groupby("time", as_index=False).agg(
        a=("power_mw", "sum"), p=(pred_col, "sum"))
    return rmse(agg["a"].values, agg["p"].values) / cap_sum * 100 if cap_sum > 0 else np.nan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    cfg_path = PROJECT_ROOT / "configs/round73_conservative_residual.yaml"
    if args.config:
        cfg_path = Path(args.config)
    cfg = yaml.safe_load(open(cfg_path)) if cfg_path.exists() else {}

    OUT.mkdir(parents=True, exist_ok=True)

    # ── 读取回测数据集 ────────────────────────────────────────────────
    ds_path = OUT / "training_v2_backtest_dataset.parquet"
    if not ds_path.exists():
        print("[FAIL] 回测数据集不存在，先运行 build_training_v2_backtest_dataset.py")
        return
    print(f"[INFO] 读取: {ds_path}")
    df = pd.read_parquet(ds_path)
    print(f"  总行数: {len(df):,}")

    bl_col = "power_pred_final"
    cap_col = "capacity_mw"
    target_col = "power_mw"
    bl_fallback = "power_pred_round61_city_safe"

    # 构建统一基线
    df["_bl_pred"] = df[bl_col].fillna(df.get(bl_fallback, df["power_pred"]))

    # 计算归一化目标
    df["y_true_norm"] = (df[target_col] / df[cap_col].clip(lower=1e-6)).clip(0, 1)
    df["y_base_norm"] = (df["_bl_pred"] / df[cap_col].clip(lower=1e-6)).clip(0, 1)
    df["residual_norm"] = df["y_true_norm"] - df["y_base_norm"]
    df["residual_clipped"] = df["residual_norm"].clip(-0.10, 0.10)

    # 分割窗口
    wA = df[df["window"] == "window_A"].copy()
    wB = df[df["window"] == "window_B"].copy()
    wC = df[df["window"] == "window_C"].copy()
    wTest = df[df["window"] == "holdout_test"].copy()

    print(f"  window_A (2023-09~12): {len(wA):,}")
    print(f"  window_B (2024-09~12): {len(wB):,}")
    print(f"  window_C (2025-05~08): {len(wC):,}")
    print(f"  holdout_test (2025-09~12): {len(wTest):,}")

    # 特征
    FEAT = [
        "hour", "month", "dayofyear",
        "latitude", "longitude", "capacity_mw",
        "y_base_norm",
        "g_blend_pred", "clear_sky_ghi", "clear_sky_index",
        "scene_v151",
        "site_zero_ratio_6_19",
        "pr_median", "quality_score",
    ]
    FEAT = [f for f in FEAT if f in df.columns]

    lgb = dict(n_estimators=400, max_depth=7, num_leaves=63,
               learning_rate=0.05, reg_lambda=2.0, reg_alpha=0.5,
               min_child_samples=30, subsample=0.8, colsample_bytree=0.8,
               random_state=42, n_jobs=-1, verbose=-1)

    summary_rows = []
    trained_cands = []

    # ══════════════════════════════════════════════════════════════════════
    # 候选 A: 秋冬专用残差（只在 9-12 月窗口训练）
    # ══════════════════════════════════════════════════════════════════════
    CAND_A = "power_pred_round73_autumn_winter_residual"
    train_A = pd.concat([wA, wB], ignore_index=True)
    train_A = train_A[train_A[target_col].notna()].copy()

    if len(train_A) >= 200:
        X = prep_X(train_A, FEAT)
        y = train_A["residual_clipped"].values.astype(float)
        model = LGBMRegressor(**lgb)
        model.fit(X, y)
        print(f"\n[候选A] 训练完成: {len(train_A):,} 样本 (autumn-winter)")

        for wname, wdf, out_cands in [
            ("wA", wA, []), ("wB", wB, []),
            ("wC", wC, []), ("wTest", wTest, [])
        ]:
            if len(wdf) == 0:
                continue
            X2 = prep_X(wdf, FEAT)
            resid = np.clip(model.predict(X2), -0.10, 0.10)
            cap = wdf[cap_col].values.astype(float)
            bl = wdf["_bl_pred"].values.astype(float)
            wdf[CAND_A] = np.clip(bl + resid * cap, 0, cap)
            bl_n = compute_city_nrmse(wdf, "_bl_pred")
            cand_n = compute_city_nrmse(wdf, CAND_A)
            print(f"  [{wname}] nrmse: {bl_n:.3f}% → {cand_n:.3f}%  ({cand_n-bl_n:+.3f}pp)")

        summary_rows.append({
            "candidate": CAND_A, "condition": "autumn_winter",
            "trained": True, "n_train": len(train_A),
            "train_windows": "window_A+window_B",
        })
        trained_cands.append(CAND_A)
    else:
        print(f"[候选A] 样本不足，跳过")
        summary_rows.append({"candidate": CAND_A, "trained": False})

    # ══════════════════════════════════════════════════════════════════════
    # 候选 B: noon bias guard (10-14 点极保守修正)
    # ══════════════════════════════════════════════════════════════════════
    CAND_B = "power_pred_round73_noon_bias_guard"
    noon_hours = [10, 11, 12, 13, 14]
    noon_train = pd.concat([wA, wB, wC], ignore_index=True)
    noon_train = noon_train[
        noon_train[target_col].notna() & noon_train["hour"].isin(noon_hours)
    ].copy()

    if len(noon_train) >= 200:
        X = prep_X(noon_train, FEAT)
        y = noon_train["residual_clipped"].values.astype(float)
        model = LGBMRegressor(**{**lgb, "n_estimators": 200, "max_depth": 5})
        model.fit(X, y)
        print(f"\n[候选B] 训练完成: {len(noon_train):,} noon 样本")

        for wname, wdf in [("wA", wA), ("wB", wB), ("wC", wC), ("wTest", wTest)]:
            if len(wdf) == 0:
                continue
            noon_mask = wdf["hour"].isin(noon_hours)
            X2 = prep_X(wdf[noon_mask], FEAT)
            resid = np.clip(model.predict(X2), -0.03, 0.03)
            cap = wdf.loc[noon_mask, cap_col].values.astype(float)
            bl = wdf.loc[noon_mask, "_bl_pred"].values.astype(float)
            wdf[CAND_B] = wdf["_bl_pred"].values.copy()
            wdf.loc[noon_mask, CAND_B] = np.clip(bl + resid * cap, 0, cap)
            bl_n = compute_city_nrmse(wdf, "_bl_pred")
            cand_n = compute_city_nrmse(wdf, CAND_B)
            print(f"  [{wname}] nrmse: {bl_n:.3f}% → {cand_n:.3f}%  ({cand_n-bl_n:+.3f}pp)")

        summary_rows.append({
            "candidate": CAND_B, "condition": "noon_bias_guard",
            "trained": True, "n_train": len(noon_train),
            "train_windows": "window_A+window_B+window_C (noon only)",
        })
        trained_cands.append(CAND_B)
    else:
        print(f"[候选B] 样本不足，跳过")
        summary_rows.append({"candidate": CAND_B, "trained": False})

    # ══════════════════════════════════════════════════════════════════════
    # 候选 C: 高误差站点 shrinkage
    # ══════════════════════════════════════════════════════════════════════
    CAND_C = "power_pred_round73_high_error_shrinkage"

    # 用 wA+wB 的 valid 子集确定高误差站点
    ab_val = pd.concat([wA, wB], ignore_index=True)
    site_nrmse = {}
    for sid, sdf in ab_val.groupby("site_id"):
        cap = float(sdf[cap_col].iloc[0])
        if cap <= 0:
            continue
        r = rmse(sdf[target_col].values, sdf["_bl_pred"].values)
        site_nrmse[sid] = r / cap * 100

    sorted_sites = sorted(site_nrmse.items(), key=lambda x: x[1], reverse=True)
    n_high = 20
    high_sites = {s[0] for s in sorted_sites[:n_high]}
    print(f"\n[候选C] 高误差站点（前{n_high}）: {[s[0] for s in sorted_sites[:5]]}")

    # 训练集：高误差站点在 wA+wB
    high_train = ab_val[ab_val["site_id"].isin(high_sites) & ab_val[target_col].notna()].copy()
    if len(high_train) >= 100:
        X = prep_X(high_train, FEAT)
        y = high_train["residual_clipped"].values.astype(float)
        model = LGBMRegressor(**{**lgb, "n_estimators": 200, "max_depth": 5})
        model.fit(X, y)
        print(f"  训练完成: {len(high_train):,} 高误差样本")

        for wname, wdf in [("wA", wA), ("wB", wB), ("wC", wC), ("wTest", wTest)]:
            if len(wdf) == 0:
                continue
            he_mask = wdf["site_id"].isin(high_sites)
            X2 = prep_X(wdf[he_mask], FEAT)
            resid = np.clip(model.predict(X2), -0.10, 0.10)
            cap = wdf.loc[he_mask, cap_col].values.astype(float)
            bl = wdf.loc[he_mask, "_bl_pred"].values.astype(float)
            wdf[CAND_C] = wdf["_bl_pred"].values.copy()
            # shrinkage: alpha = 0.3
            wdf.loc[he_mask, CAND_C] = np.clip(bl + 0.3 * resid * cap, 0, cap)
            bl_n = compute_city_nrmse(wdf, "_bl_pred")
            cand_n = compute_city_nrmse(wdf, CAND_C)
            print(f"  [{wname}] nrmse: {bl_n:.3f}% → {cand_n:.3f}%  ({cand_n-bl_n:+.3f}pp)")

        summary_rows.append({
            "candidate": CAND_C, "condition": "high_error_shrinkage",
            "trained": True, "n_train": len(high_train),
            "n_high_sites": n_high,
            "alpha": 0.3,
            "train_windows": "window_A+window_B",
        })
        trained_cands.append(CAND_C)
    else:
        print(f"[候选C] 样本不足，跳过")
        summary_rows.append({"candidate": CAND_C, "trained": False})

    # ── 保存摘要 ──────────────────────────────────────────────────────
    pd.DataFrame(summary_rows).to_csv(
        OUT / "round73_candidate_training_summary.csv", index=False, encoding="utf-8-sig")
    print(f"\n[OK] 摘要: {OUT / 'round73_candidate_training_summary.csv'}")

    # ── 保存候选 pkl ──────────────────────────────────────────────
    print(f"\n[Save] 保存候选 pkl...")
    input_pkl = PROJECT_ROOT / "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl"
    full_df = pd.read_pickle(input_pkl)
    full_df["time"] = pd.to_datetime(full_df["time"])
    full_df["hour"] = full_df["time"].dt.hour

    # 用回测数据集里的预测值（只覆盖 wA/B/C/Test）
    # 需要将窗口数据映射回 full_df
    all_window_df = pd.concat([wA, wB, wC, wTest], ignore_index=True)

    for cand_col in trained_cands:
        if cand_col not in all_window_df.columns:
            continue
        for sname, src in [("valid", wC), ("test", wTest)]:
            # 注意：holdout_test 对应 test，wC 对应 valid 的模拟
            # 实际上 wC 是 2025-05~08，对应 valid 的时间范围
            mask = full_df["split"] == sname
            update_map = (
                src[["time", "site_id", cand_col]]
                .drop_duplicates(["time", "site_id"])
                .set_index(["time", "site_id"])[cand_col]
            )
            update_map = update_map[~update_map.index.duplicated(keep="first")]
            idx = full_df.loc[mask].set_index(["time", "site_id"]).index
            if cand_col not in full_df.columns:
                full_df[cand_col] = np.nan
            full_df.loc[mask, cand_col] = update_map.reindex(idx).values

    cand_pkl = OUT / "round73_candidates.pkl"
    full_df.to_pickle(cand_pkl)
    print(f"[OK] 候选表: {cand_pkl}  ({len(full_df):,} 行)")
    print(f"  训练候选: {trained_cands}")

    print("\n[OK] train_round73 完成!")


if __name__ == "__main__":
    main()
