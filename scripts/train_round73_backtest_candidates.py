#!/usr/bin/env python3
"""
train_round73_backtest_candidates.py
=============================
基于回测窗口训练 Round73 候选模型。

候选：
    A: power_pred_round73_autumn_winter_residual
    B: power_pred_round73_noon_bias_guard
    C: power_pred_round73_high_error_shrinkage
"""

import argparse
import math
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
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


def apply_residual_to_df(wdf, model, feat_list, cand_col, clip_val, cap_col, bl_col, noon_only_hours=None):
    """将残差模型预测写入 wdf 的 cand_col 列。"""
    result = wdf.copy()
    mask = result["hour"].isin(noon_only_hours) if noon_only_hours else pd.Series(True, index=result.index)
    X = prep_X(result[mask], feat_list)
    resid = np.clip(model.predict(X), -clip_val, clip_val)
    cap = result.loc[mask, cap_col].values.astype(float)
    bl = result.loc[mask, bl_col].values.astype(float)
    result.loc[mask, cand_col] = np.clip(bl + resid * cap, 0, cap)
    non_mask = ~mask if noon_only_hours else pd.Series(False, index=result.index)
    if non_mask.any():
        result.loc[non_mask, cand_col] = result.loc[non_mask, bl_col].values
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    ds_path = OUT / "training_v2_backtest_dataset.parquet"
    if not ds_path.exists():
        print("[FAIL] 回测数据集不存在，先运行 build_training_v2_backtest_dataset.py")
        return
    print(f"[INFO] 读取: {ds_path}")
    df = pd.read_parquet(ds_path)
    print(f"  总行数: {len(df):,}")

    bl_col = "power_pred_final"
    bl_fallback = "power_pred_round61_city_safe"
    cap_col = "capacity_mw"
    target_col = "power_mw"

    # 统一基线
    df["_bl_pred"] = df[bl_col].fillna(df.get(bl_fallback, df["power_pred"]))
    df["y_true_norm"] = (df[target_col] / df[cap_col].clip(lower=1e-6)).clip(0, 1)
    df["y_base_norm"] = (df["_bl_pred"] / df[cap_col].clip(lower=1e-6)).clip(0, 1)
    df["residual_norm"] = df["y_true_norm"] - df["y_base_norm"]
    df["residual_clipped"] = df["residual_norm"].clip(-0.10, 0.10)

    wA = df[df["window"] == "window_A"].copy()
    wB = df[df["window"] == "window_B"].copy()
    wC = df[df["window"] == "window_C"].copy()
    wTest = df[df["window"] == "holdout_test"].copy()

    print(f"  wA: {len(wA):,}  wB: {len(wB):,}  wC: {len(wC):,}  wTest: {len(wTest):,}")

    FEAT = [f for f in [
        "hour", "month", "dayofyear",
        "latitude", "longitude", "capacity_mw",
        "y_base_norm",
        "g_blend_pred", "clear_sky_ghi", "clear_sky_index",
        "scene_v151",
        "site_zero_ratio_6_19",
        "pr_median", "quality_score",
    ] if f in df.columns]

    lgb_base = dict(n_estimators=400, max_depth=7, num_leaves=63,
                    learning_rate=0.05, reg_lambda=2.0, reg_alpha=0.5,
                    min_child_samples=30, subsample=0.8, colsample_bytree=0.8,
                    random_state=42, n_jobs=-1, verbose=-1)

    summary_rows = []
    trained_cands = []
    cand_results = {}  # name -> {wA, wB, wC, wTest}

    # ══ 候选 A: 秋冬专用残差 ══════════════════════════════════════════════
    CAND_A = "power_pred_round73_autumn_winter_residual"
    train_A = pd.concat([wA, wB], ignore_index=True)
    train_A = train_A[train_A[target_col].notna()].copy()
    if len(train_A) >= 200:
        model = LGBMRegressor(**lgb_base)
        model.fit(prep_X(train_A, FEAT), train_A["residual_clipped"].values.astype(float))
        print(f"\n[候选A] 训练完成: {len(train_A):,} 样本")

        results = {}
        for wname, wdf in [("wA", wA), ("wB", wB), ("wC", wC), ("wTest", wTest)]:
            if len(wdf) == 0:
                continue
            wdf = apply_residual_to_df(wdf, model, FEAT, CAND_A, 0.10, cap_col, "_bl_pred")
            results[wname] = wdf.copy()
            bn = compute_city_nrmse(wdf, "_bl_pred")
            cn = compute_city_nrmse(wdf, CAND_A)
            print(f"  [{wname}] nrmse {bn:.3f}% → {cn:.3f}%  ({cn-bn:+.3f}pp)")
        cand_results[CAND_A] = results
        trained_cands.append(CAND_A)
        summary_rows.append({"candidate": CAND_A, "condition": "autumn_winter",
                          "trained": True, "n_train": len(train_A)})
    else:
        print(f"[候选A] 样本不足")
        summary_rows.append({"candidate": CAND_A, "trained": False})

    # ══ 候选 B: noon bias guard ══════════════════════════════════════════
    CAND_B = "power_pred_round73_noon_bias_guard"
    noon_hours = [10, 11, 12, 13, 14]
    noon_train = pd.concat([wA, wB, wC], ignore_index=True)
    noon_train = noon_train[noon_train[target_col].notna() & noon_train["hour"].isin(noon_hours)].copy()
    if len(noon_train) >= 200:
        model = LGBMRegressor(**{**lgb_base, "n_estimators": 200, "max_depth": 5})
        model.fit(prep_X(noon_train, FEAT), noon_train["residual_clipped"].values.astype(float))
        print(f"\n[候选B] 训练完成: {len(noon_train):,} noon 样本")

        results = {}
        for wname, wdf in [("wA", wA), ("wB", wB), ("wC", wC), ("wTest", wTest)]:
            if len(wdf) == 0:
                continue
            wdf = apply_residual_to_df(wdf, model, FEAT, CAND_B, 0.03, cap_col, "_bl_pred",
                                      noon_only_hours=noon_hours)
            results[wname] = wdf.copy()
            bn = compute_city_nrmse(wdf, "_bl_pred")
            cn = compute_city_nrmse(wdf, CAND_B)
            print(f"  [{wname}] nrmse {bn:.3f}% → {cn:.3f}%  ({cn-bn:+.3f}pp)")
        cand_results[CAND_B] = results
        trained_cands.append(CAND_B)
        summary_rows.append({"candidate": CAND_B, "condition": "noon_bias_guard",
                          "trained": True, "n_train": len(noon_train)})
    else:
        print(f"[候选B] 样本不足")
        summary_rows.append({"candidate": CAND_B, "trained": False})

    # ══ 候选 C: 高误差站点 shrinkage ══════════════════════════════════
    CAND_C = "power_pred_round73_high_error_shrinkage"
    ab_df = pd.concat([wA, wB], ignore_index=True)
    site_nrmse_vals = {}
    for sid, sdf in ab_df.groupby("site_id"):
        cap = float(sdf[cap_col].iloc[0])
        if cap <= 0:
            continue
        r = rmse(sdf[target_col].values, sdf["_bl_pred"].values)
        site_nrmse_vals[sid] = r / cap * 100
    sorted_sites = sorted(site_nrmse_vals.items(), key=lambda x: x[1], reverse=True)
    high_sites = {s[0] for s in sorted_sites[:20]}
    print(f"\n[候选C] 高误差站点: {[s[0] for s in sorted_sites[:5]]}")

    high_train = ab_df[ab_df["site_id"].isin(high_sites) & ab_df[target_col].notna()].copy()
    if len(high_train) >= 100:
        model = LGBMRegressor(**{**lgb_base, "n_estimators": 200, "max_depth": 5})
        model.fit(prep_X(high_train, FEAT), high_train["residual_clipped"].values.astype(float))
        print(f"  训练完成: {len(high_train):,} 高误差样本")

        results = {}
        for wname, wdf in [("wA", wA), ("wB", wB), ("wC", wC), ("wTest", wTest)]:
            if len(wdf) == 0:
                continue
            he_mask = wdf["site_id"].isin(high_sites)
            result = wdf.copy()
            result[CAND_C] = result["_bl_pred"].values.copy()
            if he_mask.any():
                X2 = prep_X(wdf[he_mask], FEAT)
                resid = np.clip(model.predict(X2), -0.10, 0.10)
                cap = wdf.loc[he_mask, cap_col].values.astype(float)
                bl = wdf.loc[he_mask, "_bl_pred"].values.astype(float)
                result.loc[he_mask, CAND_C] = np.clip(bl + 0.3 * resid * cap, 0, cap)
            results[wname] = result
            bn = compute_city_nrmse(result, "_bl_pred")
            cn = compute_city_nrmse(result, CAND_C)
            print(f"  [{wname}] nrmse {bn:.3f}% → {cn:.3f}%  ({cn-bn:+.3f}pp)")
        cand_results[CAND_C] = results
        trained_cands.append(CAND_C)
        summary_rows.append({"candidate": CAND_C, "condition": "high_error_shrinkage",
                          "trained": True, "n_train": len(high_train), "n_high_sites": len(high_sites), "alpha": 0.3})
    else:
        print(f"[候选C] 样本不足")
        summary_rows.append({"candidate": CAND_C, "trained": False})

    # ── 保存 ─────────────────────────────────────────────────────────
    pd.DataFrame(summary_rows).to_csv(
        OUT / "round73_candidate_training_summary.csv", index=False, encoding="utf-8-sig")
    print(f"\n[OK] 摘要: {OUT / 'round73_candidate_training_summary.csv'}")

    # 合并所有窗口候选预测，保存 pkl
    all_w = pd.concat([wA, wB, wC, wTest], ignore_index=True)
    input_pkl = PROJECT_ROOT / "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl"
    full_df = pd.read_pickle(input_pkl)
    full_df["time"] = pd.to_datetime(full_df["time"])
    full_df["hour"] = full_df["time"].dt.hour

    for cand in trained_cands:
        if cand not in cand_results:
            continue
        for sname, src_wdf in [("valid", wC), ("test", wTest)]:
            src = cand_results[cand].get(sname)
            if src is None:
                continue
            mask = full_df["split"] == sname
            update_map = (
                src[["time", "site_id", cand]]
                .drop_duplicates(["time", "site_id"])
                .set_index(["time", "site_id"])[cand]
            )
            update_map = update_map[~update_map.index.duplicated(keep="first")]
            idx = full_df.loc[mask].set_index(["time", "site_id"]).index
            if cand not in full_df.columns:
                full_df[cand] = np.nan
            full_df.loc[mask, cand] = update_map.reindex(idx).values

    full_df.to_pickle(OUT / "round73_candidates.pkl")
    print(f"[OK] 候选表: {OUT / 'round73_candidates.pkl'}  ({len(full_df):,} 行)")
    print(f"  候选: {trained_cands}")
    print("\n[OK] train_round73 完成!")


if __name__ == "__main__":
    main()
