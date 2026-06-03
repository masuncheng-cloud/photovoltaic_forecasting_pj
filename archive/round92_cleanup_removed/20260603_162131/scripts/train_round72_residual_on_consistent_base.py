#!/usr/bin/env python3
"""
train_round72_residual_on_consistent_base.py
========================================
基于一致基线训练保守残差候选。

目标：
    residual_norm = (power_mw / capacity_mw) - (power_pred_consistent_base / capacity_mw)

候选：
    power_pred_round72_season_residual
    power_pred_round72_noon_residual
    power_pred_round72_high_error_residual

输出：
    output/pv_pipeline/round72/round72_residual_candidates.pkl
    output/pv_pipeline/round72/round72_residual_model_training_summary.csv
    output/pv_pipeline/round72/round72_residual_feature_importance.csv
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


def compute_city_nrmse(df, pred_col):
    cap_sum = float(df.drop_duplicates("site_id")["capacity_mw"].sum())
    agg = df.groupby("time", as_index=False).agg(
        a=("power_mw", "sum"), p=(pred_col, "sum"))
    return rmse(agg["a"].values, agg["p"].values) / cap_sum * 100 if cap_sum > 0 else np.nan


def apply_residual(split_df, model, features, clip_val, cand_col, cfg, noon_only=False):
    """对 split_df 应用残差模型。"""
    result_df = split_df.copy()
    focus_hours = cfg.get("focus_hours", [10, 11, 12, 13, 14])

    if noon_only:
        focus_mask = result_df["hour"].isin(focus_hours)
    else:
        focus_mask = pd.Series(True, index=result_df.index)

    X = prep_X(result_df[focus_mask], features)
    residual_pred = model.predict(X)
    residual_pred = np.clip(residual_pred, -clip_val, clip_val)
    cap = result_df.loc[focus_mask, "capacity_mw"].values.astype(float)
    bl = result_df.loc[focus_mask, cfg["consistent_base_col"]].values.astype(float)
    result_df.loc[focus_mask, cand_col] = np.clip(bl + residual_pred * cap, 0, cap)

    non_mask = ~focus_mask
    if non_mask.any():
        result_df.loc[non_mask, cand_col] = result_df.loc[non_mask, cfg["consistent_base_col"]].values
    return result_df


def main():
    parser = argparse.ArgumentParser(description="Round72 残差训练")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    if args.config is None:
        args.config = str(PROJECT_ROOT / "configs" / "round72_consistent_base.yaml")
    cfg = yaml.safe_load(open(args.config))

    # ── 读取数据 ─────────────────────────────────────────────────────
    pkl_path = OUT / "round72_consistent_base_predictions.pkl"
    print(f"[INFO] 读取: {pkl_path}")
    df = pd.read_pickle(pkl_path)
    print(f"  总行数: {len(df):,}")

    bl_consistent = cfg["consistent_base_col"]
    bl_final = cfg["baseline_final_col"]
    cap_col = cfg["capacity_col"]
    target_col = cfg["target_col"]
    clip_cfg = cfg.get("residual_clip", {})
    max_clip = clip_cfg.get("max_abs_norm", 0.10)
    noon_clip = clip_cfg.get("noon_max_abs_norm", 0.08)
    focus_hours = cfg.get("focus_hours", [10, 11, 12, 13, 14])

    # 计算残差目标
    df["y_true_norm"] = (df[target_col] / df[cap_col].clip(lower=1e-6)).clip(0, 1)
    df["y_base_norm"] = (df[bl_consistent] / df[cap_col].clip(lower=1e-6)).clip(0, 1)
    df["residual_norm"] = df["y_true_norm"] - df["y_base_norm"]
    df["residual_clipped"] = df["residual_norm"].clip(-max_clip, max_clip)

    # 分割
    train_df = df[df["split"] == "train"].copy()
    valid_df = df[df["split"] == "valid"].copy()
    test_df = df[df["split"] == "test"].copy()

    print(f"  train={len(train_df):,}  valid={len(valid_df):,}  test={len(test_df):,}")
    print(f"  residual mean={float(df['residual_norm'].mean()):.5f}  std={float(df['residual_norm'].std()):.5f}")

    # 特征
    BASE_FEAT = [
        "hour", "month", "dayofyear",
        "latitude", "longitude", "capacity_mw",
        "y_base_norm",
        "g_blend_pred", "clear_sky_ghi", "clear_sky_index",
        "scene_v151",
        "site_zero_ratio_6_19",
        "pr_median", "quality_score",
    ]
    SEASON_FEAT = BASE_FEAT + ["month", "dayofyear"]
    NOON_FEAT = BASE_FEAT + ["hour", "clear_sky_index"]

    lgb_params = {
        "n_estimators": 500,
        "max_depth": 8, "num_leaves": 63,
        "learning_rate": 0.05,
        "reg_lambda": 2.0, "reg_alpha": 0.5,
        "min_child_samples": 30,
        "subsample": 0.8, "colsample_bytree": 0.8,
        "random_state": 42, "n_jobs": -1, "verbose": -1,
    }

    summary_rows = []
    trained_cands = []

    def train_and_apply(name, feat, train_mask_fn, clip_val, cand_col, noon_only=False):
        """通用训练+应用函数。"""
        train_c = train_df[train_mask_fn(train_df) & train_df[target_col].notna()].copy()
        if len(train_c) < 200:
            print(f"  [{name}] 训练样本不足（{len(train_c)}），跳过")
            summary_rows.append({"candidate": cand_col, "trained": False,
                               "reason": "insufficient_samples"})
            return

        X_tr = prep_X(train_c, feat)
        y_tr = train_c["residual_clipped"].values.astype(float)

        model = LGBMRegressor(**lgb_params)
        model.fit(X_tr, y_tr)
        print(f"  [{name}] 训练完成: {len(train_c):,} 样本")

        # 应用到 valid/test
        nonlocal valid_df, test_df
        valid_df = apply_residual(valid_df, model, feat, clip_val, cand_col, cfg, noon_only)
        test_df = apply_residual(test_df, model, feat, clip_val, cand_col, cfg, noon_only)

        # 用 valid 评估
        bl_nrmse = compute_city_nrmse(valid_df, bl_final)
        cand_nrmse = compute_city_nrmse(valid_df, cand_col)
        bias_b = float((valid_df[bl_final].sum() - valid_df[target_col].sum()) /
                       valid_df[target_col].sum() * 100)
        bias_c = float((valid_df[cand_col].sum() - valid_df[target_col].sum()) /
                       valid_df[target_col].sum() * 100)

        summary_rows.append({
            "candidate": cand_col, "trained": True,
            "n_train": len(train_c), "clip_norm": clip_val,
            "valid_city_nrmse_base": round(bl_nrmse, 4),
            "valid_city_nrmse_cand": round(cand_nrmse, 4),
            "valid_delta": round(cand_nrmse - bl_nrmse, 4),
            "valid_bias_base": round(bias_b, 4),
            "valid_bias_cand": round(bias_c, 4),
            "valid_bias_delta": round(bias_c - bias_b, 4),
        })
        print(f"  [{name}] valid: nrmse {bl_nrmse:.3f}% → {cand_nrmse:.3f}%  "
              f"({cand_nrmse-bl_nrmse:+.3f}pp)  "
              f"bias {bias_b:.3f}% → {bias_c:.3f}%  ({bias_c-bias_b:+.3f}pp)")

        # Feature importance
        feat_imp = pd.DataFrame({
            "feature": [f for f in feat if f in train_c.columns],
            "importance": model.feature_importances_[:len([f for f in feat if f in train_c.columns])]
        }).sort_values("importance", ascending=False)
        feat_imp.to_csv(OUT / f"round72_feat_importance_{name}.csv",
                       index=False, encoding="utf-8-sig")
        print(f"  [{name}] Top features: {feat_imp.head(5).to_string(index=False)}")

    # ── 候选一：seasonal residual ──────────────────────────────────────
    train_and_apply(
        "season_residual",
        SEASON_FEAT,
        lambda df: df["split"] == "train",
        max_clip,
        "power_pred_round72_season_residual",
        noon_only=False,
    )
    if summary_rows[-1]["trained"]:
        trained_cands.append("power_pred_round72_season_residual")

    # ── 候选二：noon residual ─────────────────────────────────────────
    train_and_apply(
        "noon_residual",
        NOON_FEAT,
        lambda df: df["split"] == "train",
        noon_clip,
        "power_pred_round72_noon_residual",
        noon_only=True,
    )
    if summary_rows[-1]["trained"]:
        trained_cands.append("power_pred_round72_noon_residual")

    # ── 候选三：high_error site residual ──────────────────────────────
    # 只对高误差站点做修正
    site_nrmse = []
    for sid, sdf in valid_df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        r = rmse(sdf[target_col].values, sdf[bl_final].values)
        site_nrmse.append((sid, r / cap * 100))
    site_nrmse.sort(key=lambda x: x[1], reverse=True)
    high_error_sites = {s[0] for s in site_nrmse[:20]}
    print(f"\n[INFO] 高误差站点（前20）: {[s[0] for s in site_nrmse[:5]]}")

    def high_error_mask(df_sub):
        return df_sub["split"] == "train"
    train_he = train_df[train_df[target_col].notna() &
                        df["site_id"].isin(high_error_sites)].copy()
    if len(train_he) >= 200:
        X_tr = prep_X(train_he, BASE_FEAT)
        y_tr = train_he["residual_clipped"].values.astype(float)
        model = LGBMRegressor(**{**lgb_params, "n_estimators": 300, "max_depth": 6})
        model.fit(X_tr, y_tr)
        print(f"  [high_error_residual] 训练完成: {len(train_he):,} 样本（高误差站点）")

        cand_col = "power_pred_round72_high_error_residual"
        # 只对高误差站点应用
        he_mask_valid = valid_df["site_id"].isin(high_error_sites)
        he_mask_test = test_df["site_id"].isin(high_error_sites)
        X_va = prep_X(valid_df[he_mask_valid], BASE_FEAT)
        residual_pred = np.clip(model.predict(X_va), -max_clip, max_clip)
        cap_va = valid_df.loc[he_mask_valid, "capacity_mw"].values.astype(float)
        bl_va = valid_df.loc[he_mask_valid, bl_consistent].values.astype(float)
        valid_df.loc[he_mask_valid, cand_col] = np.clip(bl_va + residual_pred * cap_va, 0, cap_va)
        non_he = ~he_mask_valid
        valid_df.loc[non_he, cand_col] = valid_df.loc[non_he, bl_consistent].values

        X_te = prep_X(test_df[he_mask_test], BASE_FEAT)
        residual_pred_t = np.clip(model.predict(X_te), -max_clip, max_clip)
        cap_te = test_df.loc[he_mask_test, "capacity_mw"].values.astype(float)
        bl_te = test_df.loc[he_mask_test, bl_consistent].values.astype(float)
        test_df.loc[he_mask_test, cand_col] = np.clip(bl_te + residual_pred_t * cap_te, 0, cap_te)
        non_he_t = ~he_mask_test
        test_df.loc[non_he_t, cand_col] = test_df.loc[non_he_t, bl_consistent].values

        bl_nrmse = compute_city_nrmse(valid_df, bl_final)
        cand_nrmse = compute_city_nrmse(valid_df, cand_col)
        summary_rows.append({
            "candidate": cand_col, "trained": True,
            "n_train": len(train_he), "clip_norm": max_clip,
            "valid_city_nrmse_base": round(bl_nrmse, 4),
            "valid_city_nrmse_cand": round(cand_nrmse, 4),
            "valid_delta": round(cand_nrmse - bl_nrmse, 4),
        })
        trained_cands.append(cand_col)
    else:
        print(f"  [high_error_residual] 样本不足，跳过")
        summary_rows.append({"candidate": "power_pred_round72_high_error_residual",
                           "trained": False, "reason": "insufficient_samples"})

    # ── 保存摘要 ───────────────────────────────────────────────────
    pd.DataFrame(summary_rows).to_csv(
        OUT / "round72_residual_model_training_summary.csv",
        index=False, encoding="utf-8-sig")
    print(f"\n[OK] 训练摘要: {OUT / 'round72_residual_model_training_summary.csv'}")

    # ── 保存候选 pkl ────────────────────────────────────────────────
    print(f"\n[Save] 保存候选 pkl...")
    cand_pkl = OUT / "round72_residual_candidates.pkl"

    # 用原始 pkl 做骨架，填入候选
    input_pkl = PROJECT_ROOT / cfg["input_pkl"]
    full_df = pd.read_pickle(input_pkl)
    full_df["time"] = pd.to_datetime(full_df["time"])
    full_df["hour"] = full_df["time"].dt.hour

    for cand_col in trained_cands:
        src_df = valid_df if cand_col in valid_df.columns else test_df
        for sname, src in [("valid", valid_df), ("test", test_df)]:
            if cand_col not in src.columns:
                continue
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

    full_df.to_pickle(cand_pkl)
    print(f"[OK] 候选表: {cand_pkl}  ({len(full_df):,} 行)")
    print(f"  训练候选: {trained_cands}")

    print("\n[OK] train_round72_residual 完成!")


if __name__ == "__main__":
    main()
