#!/usr/bin/env python3
"""
train_round71_conservative_residual_candidates.py
=============================================
训练 Round71 保守残差候选模型。只在诊断条件成立时训练对应候选。

候选：
    power_pred_round71_seasonal_residual      (条件A)
    power_pred_round71_recency_residual       (条件B)
    power_pred_round71_noon_conservative      (条件C)

输出：
    output/pv_pipeline/round71/round71_candidates.pkl
    output/pv_pipeline/round71/round71_candidate_diff_check.csv
    output/pv_pipeline/round71/round71_model_training_summary.csv
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from lightgbm import LGBMRegressor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round71"


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def prep_X(df, feat_cols):
    cols = [c for c in feat_cols if c in df.columns]
    return pd.DataFrame(df[cols]).apply(pd.to_numeric, errors="coerce").fillna(0).values.astype(float)


def compute_city_nrmse(df, pred_col):
    cap_sum = float(df.drop_duplicates("site_id")["capacity_mw"].sum())
    agg = df.groupby("time", as_index=False).agg(a=("power_mw", "sum"), p=(pred_col, "sum"))
    return rmse(agg["a"].values, agg["p"].values) / cap_sum * 100 if cap_sum > 0 else np.nan


def main():
    parser = argparse.ArgumentParser(description="Round71 保守残差候选训练")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    if args.config is None:
        args.config = str(PROJECT_ROOT / "configs" / "round71_conservative_residual.yaml")
    cfg = yaml.safe_load(open(args.config))

    OUT.mkdir(parents=True, exist_ok=True)

    # ── 读取诊断结果 ───────────────────────────────────────────────────────
    diag_path = OUT / "round71_diagnosis_summary.json"
    if not diag_path.exists():
        print("[WARN] 诊断结果不存在，先运行诊断脚本")
        conditions = {}
    else:
        with open(diag_path) as f:
            diag = json.load(f)
        conditions = diag.get("conditions", {})
        print(f"[INFO] 诊断条件: {[k for k, v in conditions.items() if v.get('允许训练')]}")

    # ── 读取训练表 ─────────────────────────────────────────────────────────
    table_path = OUT / "round71_residual_training_table.parquet"
    if not table_path.exists():
        print(f"[FAIL] 训练表不存在: {table_path}")
        import sys; sys.exit(1)
    print(f"[INFO] 读取训练表: {table_path}")
    df = pd.read_parquet(table_path)
    print(f"  总行数: {len(df):,}")

    bl_col = cfg["baseline_col"]
    cap_col = cfg["capacity_col"]
    actual_col = cfg["target_col"]
    focus_hours = cfg.get("focus_hours", [10, 11, 12, 13, 14])

    train_df = df[df["split"] == "train"].copy()
    valid_df = df[df["split"] == "valid"].copy()
    test_df = df[df["split"] == "test"].copy()

    # ── 特征定义 ───────────────────────────────────────────────────────────
    SEASONAL_FEATURES = [
        "hour", "month", "dayofyear",
        "latitude", "longitude", "capacity_mw",
        "y_base_norm",
        "g_blend_pred", "clear_sky_ghi", "clear_sky_index",
        "scene_v151",
        "site_zero_ratio_6_19", "site_bias_valid", "site_nrmse_valid",
        "pr_median", "quality_score",
    ]
    RECENCY_FEATURES = [
        "hour", "month", "dayofyear",
        "latitude", "longitude", "capacity_mw",
        "y_base_norm",
        "g_blend_pred", "clear_sky_ghi", "clear_sky_index",
        "site_zero_ratio_6_19", "site_bias_valid",
        "pr_median", "quality_score",
    ]
    NOON_FEATURES = [
        "hour", "month", "dayofyear",
        "latitude", "longitude", "capacity_mw",
        "y_base_norm",
        "g_blend_pred", "clear_sky_ghi", "clear_sky_index",
        "site_bias_valid", "pr_median",
    ]

    lgb_params = {
        "n_estimators": cfg.get("models", {}).get("lgb", {}).get("n_estimators", 500),
        "max_depth": cfg.get("models", {}).get("lgb", {}).get("max_depth", 6),
        "num_leaves": cfg.get("models", {}).get("lgb", {}).get("num_leaves", 31),
        "learning_rate": cfg.get("models", {}).get("lgb", {}).get("learning_rate", 0.05),
        "reg_lambda": cfg.get("models", {}).get("lgb", {}).get("reg_lambda", 2.0),
        "reg_alpha": cfg.get("models", {}).get("lgb", {}).get("reg_alpha", 0.5),
        "min_child_samples": cfg.get("models", {}).get("lgb", {}).get("min_child_samples", 30),
        "subsample": cfg.get("models", {}).get("lgb", {}).get("subsample", 0.8),
        "colsample_bytree": cfg.get("models", {}).get("lgb", {}).get("colsample_bytree", 0.8),
        "random_state": 42, "n_jobs": -1, "verbose": -1,
    }

    summary_rows = []
    trained_candidates = []

    # ── 辅助函数：组装候选预测 ──────────────────────────────────────────────
    def apply_candidate_residual(split_df, model, features, clip_val, candidate_col, noon_only=False):
        """对 split_df 应用残差模型，clip 后加到 baseline 上。"""
        result_df = split_df.copy()
        mask = result_df["hour"].isin(focus_hours) if noon_only else slice(None)
        X = prep_X(result_df[mask], features)
        residual_pred = model.predict(X)
        residual_pred = np.clip(residual_pred, -clip_val, clip_val)
        cap = result_df.loc[mask, cap_col].values.astype(float)
        # 优先用 power_pred_final，如果为空则回退到 power_pred
        bl_vals = np.where(
            pd.notna(result_df.loc[mask, bl_col].values),
            result_df.loc[mask, bl_col].values,
            result_df.loc[mask, "power_pred"].values,
        )
        result_df.loc[mask, candidate_col] = np.clip(
            bl_vals + residual_pred * cap, 0, cap
        )
        # 非 focus 时段保持 baseline（power_pred_final 优先）
        non_mask = ~mask
        if non_mask.any():
            bl_non = np.where(
                pd.notna(result_df.loc[non_mask, bl_col].values),
                result_df.loc[non_mask, bl_col].values,
                result_df.loc[non_mask, "power_pred"].values,
            )
            result_df.loc[non_mask, candidate_col] = bl_non
        return result_df

    # ═══════════════════════════════════════════════════════════════════════
    # 候选一：seasonal_residual（条件A）
    # ═══════════════════════════════════════════════════════════════════════
    cond_a = conditions.get("A_seasonal_drift", {}).get("允许训练", False)
    CAND_A = "power_pred_round71_seasonal_residual"

    if cond_a:
        print(f"\n[候选A] seasonal_residual（条件A成立）")
        train_c = train_df[train_df["power_mw"].notna()].copy()
        X_tr = prep_X(train_c, SEASONAL_FEATURES)
        y_tr = train_c["residual_norm_clipped"].values.astype(float)
        w_tr = train_c["recency_weight"].fillna(1.0).values.astype(float)

        model = LGBMRegressor(**lgb_params)
        model.fit(X_tr, y_tr, sample_weight=w_tr)
        print(f"  训练完成: {len(train_c):,} 样本")

        # valid 推理
        clip_cfg = cfg.get("residual_clip", {})
        max_clip = clip_cfg.get("max_abs_norm", 0.08)
        valid_df = apply_candidate_residual(valid_df, model, SEASONAL_FEATURES, max_clip, CAND_A)
        test_df = apply_candidate_residual(test_df, model, SEASONAL_FEATURES, max_clip, CAND_A)

        nrmse_b = compute_city_nrmse(valid_df, bl_col)
        nrmse_c = compute_city_nrmse(valid_df, CAND_A)
        summary_rows.append({
            "candidate": CAND_A, "condition": "A", "trained": True,
            "n_train": len(train_c), "clip_norm": max_clip,
            "valid_city_nrmse_base": round(nrmse_b, 4),
            "valid_city_nrmse_cand": round(nrmse_c, 4),
            "valid_delta": round(nrmse_c - nrmse_b, 4),
        })
        trained_candidates.append(CAND_A)
        print(f"  valid: city_nrmse {nrmse_b:.3f}% → {nrmse_c:.3f}%  ({nrmse_c-nrmse_b:+.3f}pp)")
    else:
        print(f"\n[候选A] seasonal_residual 跳过（条件A不成立）")
        summary_rows.append({"candidate": CAND_A, "condition": "A", "trained": False,
                           "reason": "condition_A_not_met"})

    # ═══════════════════════════════════════════════════════════════════════
    # 候选二：recency_residual（条件B）
    # ═══════════════════════════════════════════════════════════════════════
    cond_b = conditions.get("B_recency", {}).get("允许训练", False)
    CAND_B = "power_pred_round71_recency_residual"

    if cond_b:
        print(f"\n[候选B] recency_residual（条件B成立）")
        train_c = train_df[train_df["power_mw"].notna()].copy()
        X_tr = prep_X(train_c, RECENCY_FEATURES)
        y_tr = train_c["residual_norm_clipped"].values.astype(float)
        w_tr = train_c["recency_weight"].fillna(1.0).values.astype(float)

        model = LGBMRegressor(**lgb_params)
        model.fit(X_tr, y_tr, sample_weight=w_tr)
        print(f"  训练完成: {len(train_c):,} 样本")

        clip_cfg = cfg.get("residual_clip", {})
        max_clip = clip_cfg.get("max_abs_norm", 0.08)
        valid_df = apply_candidate_residual(valid_df, model, RECENCY_FEATURES, max_clip, CAND_B)
        test_df = apply_candidate_residual(test_df, model, RECENCY_FEATURES, max_clip, CAND_B)

        nrmse_b = compute_city_nrmse(valid_df, bl_col)
        nrmse_c = compute_city_nrmse(valid_df, CAND_B)
        summary_rows.append({
            "candidate": CAND_B, "condition": "B", "trained": True,
            "n_train": len(train_c), "clip_norm": max_clip,
            "valid_city_nrmse_base": round(nrmse_b, 4),
            "valid_city_nrmse_cand": round(nrmse_c, 4),
            "valid_delta": round(nrmse_c - nrmse_b, 4),
        })
        trained_candidates.append(CAND_B)
        print(f"  valid: city_nrmse {nrmse_b:.3f}% → {nrmse_c:.3f}%  ({nrmse_c-nrmse_b:+.3f}pp)")
    else:
        print(f"\n[候选B] recency_residual 跳过（条件B不成立）")
        summary_rows.append({"candidate": CAND_B, "condition": "B", "trained": False,
                           "reason": "condition_B_not_met"})

    # ═══════════════════════════════════════════════════════════════════════
    # 候选三：noon_conservative（条件C）
    # ═══════════════════════════════════════════════════════════════════════
    cond_c = conditions.get("C_noon_bias", {}).get("允许训练", False)
    CAND_C = "power_pred_round71_noon_conservative"

    if cond_c:
        print(f"\n[候选C] noon_conservative（条件C成立）")
        train_c = train_df[train_df["power_mw"].notna()].copy()
        noon_c = train_c[train_c["hour"].isin(focus_hours)].copy()

        X_tr = prep_X(noon_c, NOON_FEATURES)
        y_tr = noon_c["residual_norm_clipped"].values.astype(float)

        lgb_noon = lgb_params.copy()
        lgb_noon["n_estimators"] = 300
        lgb_noon["max_depth"] = 5
        model = LGBMRegressor(**lgb_noon)
        model.fit(X_tr, y_tr)
        print(f"  训练完成: {len(noon_c):,} noon 样本")

        clip_cfg = cfg.get("residual_clip", {})
        noon_clip = clip_cfg.get("noon_max_abs_norm", 0.06)
        valid_df = apply_candidate_residual(valid_df, model, NOON_FEATURES, noon_clip, CAND_C, noon_only=True)
        test_df = apply_candidate_residual(test_df, model, NOON_FEATURES, noon_clip, CAND_C, noon_only=True)

        nrmse_b = compute_city_nrmse(valid_df, bl_col)
        nrmse_c = compute_city_nrmse(valid_df, CAND_C)
        summary_rows.append({
            "candidate": CAND_C, "condition": "C", "trained": True,
            "n_train": len(noon_c), "clip_norm": noon_clip,
            "valid_city_nrmse_base": round(nrmse_b, 4),
            "valid_city_nrmse_cand": round(nrmse_c, 4),
            "valid_delta": round(nrmse_c - nrmse_b, 4),
        })
        trained_candidates.append(CAND_C)
        print(f"  valid: city_nrmse {nrmse_b:.3f}% → {nrmse_c:.3f}%  ({nrmse_c-nrmse_b:+.3f}pp)")
    else:
        print(f"\n[候选C] noon_conservative 跳过（条件C不成立）")
        summary_rows.append({"candidate": CAND_C, "condition": "C", "trained": False,
                           "reason": "condition_C_not_met"})

    # ── 保存训练摘要 ──────────────────────────────────────────────────────
    pd.DataFrame(summary_rows).to_csv(OUT / "round71_model_training_summary.csv",
                                     index=False, encoding="utf-8-sig")
    print(f"\n[OK] 训练摘要: {OUT / 'round71_model_training_summary.csv'}")

    # ── 保存候选 pkl ──────────────────────────────────────────────────────
    print(f"\n[Save] 保存候选 pkl...")
    cand_path = OUT / "round71_candidates.pkl"
    input_path = PROJECT_ROOT / cfg["paths"]["input_pred"]
    full_df = pd.read_pickle(input_path)
    full_df["time"] = pd.to_datetime(full_df["time"])
    full_df = full_df[full_df["split"] != "future"]
    full_df["hour"] = full_df["time"].dt.hour

    # 对每个训练好的候选，映射到 full_df
    for cand_col in trained_candidates:
        src_df = valid_df if cand_col in valid_df.columns else test_df
        if cand_col not in src_df.columns:
            continue
        for split_name, src in [("valid", valid_df), ("test", test_df)]:
            if cand_col not in src.columns:
                continue
            mask = full_df["split"] == split_name
            if mask.sum() == 0:
                continue
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

    full_df.to_pickle(cand_path)
    print(f"[OK] 候选表: {cand_path}  ({len(full_df):,} 行)")
    print(f"  训练候选: {trained_candidates}")

    print("\n[OK] train_round71_conservative_residual_candidates 完成!")


if __name__ == "__main__":
    main()
