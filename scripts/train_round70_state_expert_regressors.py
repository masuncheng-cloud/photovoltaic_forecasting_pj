#!/usr/bin/env python3
"""
train_round70_state_expert_regressors.py
=======================================
独立的状态专家回归模型训练脚本（按 actual_state 训练，按 pred_state 预测）。

本脚本为 Stage 8 的独立版本，不依赖 train_round70_active_state_model.py 的预训练结果。
读取 round70_training_table.parquet，使用独立的分类器预测状态，再按状态训练专家回归器。

用法：
    python scripts/train_round70_state_expert_regressors.py --config configs/round70_state_expert_model.yaml

输出：
    output/pv_pipeline/round70/round70_state_expert_regressors_summary.csv
    output/pv_pipeline/round70/round70_candidates.pkl
"""

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from lightgbm import LGBMClassifier, LGBMRegressor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round70"


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def compute_city_nrmse(df, pred_col):
    cap_sum = float(df.drop_duplicates("site_id")["capacity_mw"].sum())
    agg = df.groupby("time", as_index=False).agg(a=("power_mw", "sum"), p=(pred_col, "sum"))
    return rmse(agg["a"].values, agg["p"].values) / cap_sum * 100


def compute_site_mean_nrmse(df, pred_col):
    vals = []
    for _, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        vals.append(rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100)
    return float(np.mean(vals)) if vals else np.nan


def compute_city_bias(df, pred_col):
    a_sum = float(df["power_mw"].sum())
    p_sum = float(df[pred_col].sum())
    return (p_sum - a_sum) / a_sum * 100 if abs(a_sum) > 1e-9 else np.nan


def prep_X(df, feat_cols):
    cols = [c for c in feat_cols if c in df.columns]
    X = pd.DataFrame(df[cols]).apply(pd.to_numeric, errors="coerce").fillna(0)
    return X.values.astype(float)


def main():
    parser = argparse.ArgumentParser(description="Round70 独立状态专家回归器")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    if args.config is None:
        args.config = str(PROJECT_ROOT / "configs" / "round70_state_expert_model.yaml")
    cfg = yaml.safe_load(open(args.config))

    OUT.mkdir(parents=True, exist_ok=True)

    table_path = PROJECT_ROOT / cfg["paths"]["output_dir"] / "round70_training_table.parquet"
    print(f"[INFO] 读取训练表: {table_path}")
    df = pd.read_parquet(table_path)
    df["time"] = pd.to_datetime(df["time"])

    train_df = df[df["split"] == "train"].copy()
    valid_df = df[df["split"] == "valid"].copy()
    test_df = df[df["split"] == "test"].copy()

    bl_col = cfg["baseline_col"]
    CANDIDATE_COL = "power_pred_round70_state_expert"

    # ── Stage 1: 训练独立分类器 ───────────────────────────────────────────
    print("\n[Stage 1] 训练发电状态分类器...")

    CLF_FEATURES = [
        "hour", "month", "dayofyear", "latitude", "longitude",
        "capacity_mw", "g_blend_pred", "clear_sky_ghi", "clear_sky_index",
        "site_zero_ratio_6_19", "site_positive_count_train_valid",
        "pr_median", "quality_score",
        "baseline_norm",
    ]

    train_c = train_df[train_df["power_mw"].notna()].copy()
    valid_c = valid_df[valid_df["power_mw"].notna()].copy()
    test_c = test_df[test_df["power_mw"].notna()].copy()

    X_train = prep_X(train_c, CLF_FEATURES)
    X_valid = prep_X(valid_c, CLF_FEATURES)
    X_test = prep_X(test_c, CLF_FEATURES)

    label_map = {"inactive": 0, "weak": 1, "active": 2}
    rev_label_map = {v: k for k, v in label_map.items()}
    y_train = np.array([label_map.get(v, 0) for v in train_c["state_label"].values])

    clf = LGBMClassifier(
        n_estimators=1500, max_depth=8, num_leaves=63,
        learning_rate=0.03, reg_lambda=1.0, reg_alpha=0.2,
        min_child_samples=20, subsample=0.85, colsample_bytree=0.85,
        random_state=42, n_jobs=-1, verbose=-1, class_weight="balanced",
    )
    clf.fit(X_train, y_train)

    # ── Stage 2: 状态专家回归 ────────────────────────────────────────────
    print("\n[Stage 2] 训练状态专家回归器...")

    # 为 train + valid 预测状态
    for split_df in [train_df, valid_df, test_df]:
        proba = clf.predict_proba(prep_X(split_df, CLF_FEATURES))
        split_df["pred_state_prob_active"] = proba[:, 2]
        split_df["pred_state_prob_weak"] = proba[:, 1]
        split_df["pred_state_prob_inactive"] = proba[:, 0]
        split_df["pred_state"] = np.array([rev_label_map[p] for p in np.argmax(proba, axis=1)])

    # 样本权重
    w_cfg = cfg.get("sample_weight", {})
    focus_hours = cfg.get("focus_hours", [10, 11, 12, 13, 14])

    def compute_weight(row):
        w = w_cfg.get("base", 1.0)
        if row.get("hour", 12) in focus_hours:
            w *= w_cfg.get("focus_10_14", 2.0)
        if row.get("hour", 12) in [6, 7, 8, 17, 18, 19]:
            w *= w_cfg.get("dawn_dusk", 1.3)
        state = row.get("state_label", "active")
        if state == "weak":
            w *= w_cfg.get("weak_power", 1.4)
        if state == "inactive":
            w *= w_cfg.get("inactive", 0.5)
        return float(np.clip(w, w_cfg.get("min_weight", 0.3), w_cfg.get("max_weight", 3.0)))

    train_df["sample_weight"] = train_df.apply(compute_weight, axis=1)

    EXPERT_FEATURES = [
        "hour", "month", "dayofyear", "latitude", "longitude",
        "capacity_mw", "g_blend_pred", "clear_sky_ghi", "clear_sky_index",
        "site_zero_ratio_6_19", "site_positive_count_train_valid",
        "pr_median", "quality_score",
        "baseline_norm",
        "pred_state_prob_active", "pred_state_prob_weak",
    ]

    expert_models = {}
    summary_rows = []

    for state_name in ["active", "weak", "inactive"]:
        tr_s = train_df[train_df["state_label"] == state_name].copy()
        va_s = valid_df[valid_df["state_label"] == state_name].copy()

        if len(tr_s) < 50:
            print(f"  [{state_name}] 训练样本不足（{len(tr_s)}），跳过")
            summary_rows.append({
                "state": state_name, "n_train": len(tr_s), "n_valid": len(va_s),
                "valid_rmse": np.nan, "valid_nrmse": np.nan, "trained": False,
            })
            continue

        X_tr = prep_X(tr_s, EXPERT_FEATURES)
        y_tr = tr_s["y_norm"].values.astype(float)
        w_tr = tr_s["sample_weight"].values.astype(float)

        model = LGBMRegressor(
            n_estimators=2500, max_depth=10, num_leaves=127,
            learning_rate=0.02, reg_lambda=1.5, reg_alpha=0.3,
            min_child_samples=15, subsample=0.85, colsample_bytree=0.85,
            random_state=42, n_jobs=-1, verbose=-1,
        )
        model.fit(X_tr, y_tr, sample_weight=w_tr)

        if len(va_s) > 0:
            X_va = prep_X(va_s, EXPERT_FEATURES)
            y_va = va_s["y_norm"].values.astype(float)
            cap_va = va_s["capacity_mw"].values.astype(float)
            pred_va = np.clip(model.predict(X_va) * cap_va, 0, cap_va)
            r = rmse(y_va * cap_va, pred_va)
            r_nrmse = r / float(np.nanmean(cap_va)) * 100 if len(cap_va) > 0 else np.nan
            print(f"  [{state_name}] n_train={len(tr_s):,}  valid_rmse={r:.4f}  valid_nrmse={r_nrmse:.2f}%")
            summary_rows.append({
                "state": state_name, "n_train": len(tr_s), "n_valid": len(va_s),
                "valid_rmse": round(r, 4), "valid_nrmse": round(r_nrmse, 2), "trained": True,
            })
        else:
            summary_rows.append({
                "state": state_name, "n_train": len(tr_s), "n_valid": 0,
                "valid_rmse": np.nan, "valid_nrmse": np.nan, "trained": True,
            })

        expert_models[state_name] = model

    pd.DataFrame(summary_rows).to_csv(
        OUT / "round70_state_expert_regressors_summary.csv",
        index=False, encoding="utf-8-sig"
    )
    print(f"[OK] 专家回归摘要: {OUT / 'round70_state_expert_regressors_summary.csv'}")

    # ── Stage 3: 预测 valid + test ───────────────────────────────────────
    print("\n[Stage 3] 组装候选预测...")

    for split_df in [valid_df, test_df]:
        split_df[CANDIDATE_COL] = np.nan
        for state_name, model in expert_models.items():
            mask = split_df["pred_state"] == state_name
            if mask.sum() == 0:
                continue
            X_m = prep_X(split_df[mask], EXPERT_FEATURES)
            pred_norm = model.predict(X_m)
            cap_m = split_df.loc[mask, "capacity_mw"].values.astype(float)
            split_df.loc[mask, CANDIDATE_COL] = np.clip(pred_norm * cap_m, 0, cap_m)

    # valid 指标
    valid_eval = valid_df[valid_df[CANDIDATE_COL].notna()].copy()
    if len(valid_eval) > 0:
        nrmse_b = compute_city_nrmse(valid_eval, bl_col)
        nrmse_c = compute_city_nrmse(valid_eval, CANDIDATE_COL)
        site_b = compute_site_mean_nrmse(valid_eval, bl_col)
        site_c = compute_site_mean_nrmse(valid_eval, CANDIDATE_COL)
        bias_b = compute_city_bias(valid_eval, bl_col)
        bias_c = compute_city_bias(valid_eval, CANDIDATE_COL)
        print(f"\n  valid 集对比 ({bl_col} vs {CANDIDATE_COL}):")
        print(f"    city_nrmse:  {nrmse_b:.3f}% → {nrmse_c:.3f}%  ({nrmse_c-nrmse_b:+.3f}pp)")
        print(f"    site_nrmse:  {site_b:.3f}% → {site_c:.3f}%  ({site_c-site_b:+.3f}pp)")
        print(f"    city_bias:    {bias_b:.3f}% → {bias_c:.3f}%  ({bias_c-bias_b:+.3f}pp)")

    # ── 更新候选 pkl ────────────────────────────────────────────────────────
    print("\n[Stage 4] 保存候选 pkl...")
    cand_path = OUT / "round70_candidates.pkl"
    if cand_path.exists():
        full_df = pd.read_pickle(cand_path)
    else:
        full_df = pd.read_pickle(PROJECT_ROOT / cfg["paths"]["input_pred"])
        full_df["time"] = pd.to_datetime(full_df["time"])
        full_df = full_df[full_df["split"] != "future"]
    if CANDIDATE_COL not in full_df.columns:
        full_df[CANDIDATE_COL] = np.nan

    for src_df, split_name in [(valid_df, "valid"), (test_df, "test")]:
        mask = full_df["split"] == split_name
        if mask.sum() == 0:
            continue
        update_map = (
            src_df[["time", "site_id", CANDIDATE_COL]]
            .drop_duplicates(["time", "site_id"])
            .set_index(["time", "site_id"])[CANDIDATE_COL]
        )
        update_map = update_map[~update_map.index.duplicated(keep="first")]
        idx = full_df.loc[mask].set_index(["time", "site_id"]).index
        full_df.loc[mask, CANDIDATE_COL] = update_map.reindex(idx).values

    full_df.to_pickle(cand_path)
    print(f"[OK] 候选表已更新: {cand_path}")

    print("\n[OK] train_round70_state_expert_regressors 完成!")


if __name__ == "__main__":
    main()
