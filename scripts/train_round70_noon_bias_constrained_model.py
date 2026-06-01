#!/usr/bin/env python3
"""
train_round70_noon_bias_constrained_model.py
============================================
训练 10-14 点 bias 约束模型，重点降低中午时段高估问题。
使用更高样本权重 + valid bias 约束选择。

输出：
    output/pv_pipeline/round70/round70_noon_bias_valid_compare.csv
    output/pv_pipeline/round70/round70_noon_bias_test_compare.csv
    output/pv_pipeline/round70/round70_candidates.pkl
"""

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from lightgbm import LGBMRegressor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round70"


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def compute_city_nrmse(df, pred_col):
    cap_sum = float(df.drop_duplicates("site_id")["capacity_mw"].sum())
    agg = df.groupby("time", as_index=False).agg(a=("power_mw", "sum"), p=(pred_col, "sum"))
    return rmse(agg["a"].values, agg["p"].values) / cap_sum * 100


def compute_city_nrmse_hourly(df, pred_col, hours):
    vals = []
    for h, g in df[df["hour"].isin(hours)].groupby("hour"):
        agg = g.groupby("time", as_index=False).agg(a=("power_mw", "sum"), p=(pred_col, "sum"))
        cap = float(g.drop_duplicates("site_id")["capacity_mw"].sum())
        if cap > 0:
            vals.append(rmse(agg["a"].values, agg["p"].values) / cap * 100)
    return float(np.mean(vals)) if vals else np.nan


def compute_site_mean_nrmse(df, pred_col, hours=None):
    vals = []
    d = df[df["hour"].isin(hours)] if hours else df
    for _, sdf in d.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        vals.append(rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100)
    return float(np.mean(vals)) if vals else np.nan


def compute_city_bias(df, pred_col):
    a_sum = float(df["power_mw"].sum())
    p_sum = float(df[pred_col].sum())
    return (p_sum - a_sum) / a_sum * 100 if abs(a_sum) > 1e-9 else np.nan


def compute_city_bias_hourly(df, pred_col, hours):
    d = df[df["hour"].isin(hours)]
    a_sum = float(d["power_mw"].sum())
    p_sum = float(d[pred_col].sum())
    return (p_sum - a_sum) / a_sum * 100 if abs(a_sum) > 1e-9 else np.nan


def prep_X(df, feat_cols):
    cols = [c for c in feat_cols if c in df.columns]
    X = pd.DataFrame(df[cols]).apply(pd.to_numeric, errors="coerce").fillna(0)
    return X.values.astype(float)


def main():
    parser = argparse.ArgumentParser(description="Round70 10-14点 bias 约束模型")
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
    print(f"  总行数: {len(df):,}")

    train_df = df[df["split"] == "train"].copy()
    valid_df = df[df["split"] == "valid"].copy()
    test_df = df[df["split"] == "test"].copy()

    bl_col = cfg["baseline_col"]
    focus_hours = cfg.get("focus_hours", [10, 11, 12, 13, 14])

    # ── 特征 ─────────────────────────────────────────────────────────────────
    FEATURES = [
        "hour", "month", "dayofyear", "latitude", "longitude",
        "capacity_mw", "g_blend_pred", "clear_sky_ghi", "clear_sky_index",
        "t2m_c", "solar_elevation",
        "site_zero_ratio_6_19", "site_positive_count_train_valid",
        "pr_median", "quality_score",
        "baseline_norm",
    ]

    # ── 样本权重 ─────────────────────────────────────────────────────────────
    w_cfg = cfg.get("sample_weight", {})
    def compute_weight(row):
        w = w_cfg.get("base", 1.0)
        if row.get("hour", 12) in focus_hours:
            w *= w_cfg.get("focus_10_14", 2.0)
        if row.get("hour", 12) in [6, 7, 8, 17, 18, 19]:
            w *= w_cfg.get("dawn_dusk", 1.3)
        if row.get("state_label") == "weak":
            w *= w_cfg.get("weak_power", 1.4)
        if row.get("state_label") == "inactive":
            w *= w_cfg.get("inactive", 0.5)
        return float(np.clip(w, w_cfg.get("min_weight", 0.3), w_cfg.get("max_weight", 3.0)))

    train_df["sample_weight"] = train_df.apply(compute_weight, axis=1)
    valid_df["sample_weight"] = valid_df.apply(compute_weight, axis=1)
    test_df["sample_weight"] = test_df.apply(compute_weight, axis=1)

    # ── Baseline 指标 ─────────────────────────────────────────────────────────
    print("\n[Baseline] valid 集指标:")
    print(f"  city_nrmse_6_19: {compute_city_nrmse(valid_df, bl_col):.3f}%")
    print(f"  city_nrmse_10_14: {compute_city_nrmse_hourly(valid_df, bl_col, focus_hours):.3f}%")
    print(f"  site_mean_nrmse_10_14: {compute_site_mean_nrmse(valid_df, bl_col, focus_hours):.3f}%")
    print(f"  city_bias_6_19: {compute_city_bias(valid_df, bl_col):.3f}%")
    print(f"  city_bias_10_14: {compute_city_bias_hourly(valid_df, bl_col, focus_hours):.3f}%")

    # ── 训练 noon bias 模型 ──────────────────────────────────────────────────
    print("\n[Model] 训练 noon_bias_constrained_lgb...")

    X_train = prep_X(train_df, FEATURES)
    y_train = train_df["y_norm"].values.astype(float)
    w_train = train_df["sample_weight"].values.astype(float)

    model = LGBMRegressor(
        n_estimators=2500, max_depth=10, num_leaves=127,
        learning_rate=0.02, reg_lambda=1.5, reg_alpha=0.3,
        min_child_samples=15, subsample=0.85, colsample_bytree=0.85,
        random_state=42, n_jobs=-1, verbose=-1,
    )
    model.fit(X_train, y_train, sample_weight=w_train)
    print(f"  训练完成: {X_train.shape[0]:,} 样本")

    # ── valid 推理 ───────────────────────────────────────────────────────────
    CANDIDATE_COL = "power_pred_round70_noon_bias_lgb"

    for split_df in [valid_df, test_df]:
        X_s = prep_X(split_df, FEATURES)
        pred_norm = model.predict(X_s)
        cap = split_df["capacity_mw"].values.astype(float)
        split_df[CANDIDATE_COL] = np.clip(pred_norm * cap, 0, cap)

    # ── valid 对比 ────────────────────────────────────────────────────────────
    print("\n[Compare] valid 集指标对比:")
    rows = []
    for split_name, split_df in [("valid", valid_df), ("test", test_df)]:
        for metric_name, metric_fn, hours in [
            ("city_nrmse_6_19", compute_city_nrmse, None),
            ("city_nrmse_10_14", lambda d, c: compute_city_nrmse_hourly(d, c, focus_hours), focus_hours),
            ("site_mean_nrmse_6_19", compute_site_mean_nrmse, None),
            ("site_mean_nrmse_10_14", lambda d, c: compute_site_mean_nrmse(d, c, focus_hours), focus_hours),
            ("city_bias_6_19", compute_city_bias, None),
            ("city_bias_10_14", lambda d, c: compute_city_bias_hourly(d, c, focus_hours), focus_hours),
        ]:
            if hours:
                d = split_df[split_df["hour"].isin(hours)]
            else:
                d = split_df
            base_val = metric_fn(d, bl_col) if hours else metric_fn(split_df, bl_col)
            cand_val = metric_fn(d, CANDIDATE_COL) if hours else metric_fn(split_df, CANDIDATE_COL)
            delta = cand_val - base_val if (base_val is not None and cand_val is not None) else np.nan
            rows.append({
                "split": split_name, "metric": metric_name,
                "baseline": round(base_val, 4) if base_val is not None else np.nan,
                "candidate": round(cand_val, 4) if cand_val is not None else np.nan,
                "delta_pp": round(delta, 4) if delta is not None else np.nan,
            })

    comp_df = pd.DataFrame(rows)
    print(comp_df.to_string(index=False))

    if len(valid_df) > 0:
        comp_df.to_csv(OUT / "round70_noon_bias_valid_compare.csv",
                       index=False, encoding="utf-8-sig")
        print(f"[OK] noon_bias valid 对比: {OUT / 'round70_noon_bias_valid_compare.csv'}")

    if len(test_df) > 0:
        pd.DataFrame([r for r in rows if r["split"] == "test"]).to_csv(
            OUT / "round70_noon_bias_test_compare.csv", index=False, encoding="utf-8-sig")

    # ── 更新候选 pkl ───────────────────────────────────────────────────────────
    print("\n[Save] 更新候选 pkl...")
    cand_path = OUT / "round70_candidates.pkl"
    if cand_path.exists():
        full_df = pd.read_pickle(cand_path)
    else:
        full_df = pd.read_pickle(PROJECT_ROOT / cfg["paths"]["input_pred"])
        full_df["time"] = pd.to_datetime(full_df["time"])
        full_df = full_df[full_df["split"] != "future"]

    # 确保候选列存在
    if CANDIDATE_COL not in full_df.columns:
        full_df[CANDIDATE_COL] = np.nan

    for src_df, split_name in [(valid_df, "valid"), (test_df, "test")]:
        mask = full_df["split"] == split_name
        if mask.sum() == 0:
            continue
        # 直接从 src_df 构建映射再赋值，避免索引对齐问题
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

    print("\n[OK] train_round70_noon_bias_constrained_model 完成!")


if __name__ == "__main__":
    main()
