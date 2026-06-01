#!/usr/bin/env python3
"""
train_round70_high_error_site_expert.py
=======================================
对高误差站点训练专家模型，仅在高误差站点上使用。
在 valid 集上决定是否采用专家模型。

高误差站点定义：valid site_nrmse 排名前 15 或 > 12%

输出：
    output/pv_pipeline/round70/round70_high_error_site_list.csv
    output/pv_pipeline/round70/round70_high_error_expert_valid_compare.csv
    output/pv_pipeline/round70/round70_high_error_expert_test_compare.csv
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


def compute_site_nrmse(df, pred_col):
    rows = []
    for sid, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        r = rmse(sdf["power_mw"].values, sdf[pred_col].values)
        rows.append({"site_id": sid, "nrmse": r / cap * 100, "rmse": r, "capacity": cap})
    return pd.DataFrame(rows)


def compute_city_nrmse(df, pred_col):
    cap_sum = float(df.drop_duplicates("site_id")["capacity_mw"].sum())
    agg = df.groupby("time", as_index=False).agg(a=("power_mw", "sum"), p=(pred_col, "sum"))
    return rmse(agg["a"].values, agg["p"].values) / cap_sum * 100


def prep_X(df, feat_cols):
    cols = [c for c in feat_cols if c in df.columns]
    X = pd.DataFrame(df[cols]).apply(pd.to_numeric, errors="coerce").fillna(0)
    return X.values.astype(float)


def main():
    parser = argparse.ArgumentParser(description="Round70 高误差站点专家模型")
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
    CANDIDATE_COL = "power_pred_round70_high_error_expert"

    # ── 识别高误差站点 ────────────────────────────────────────────────────────
    print("\n[Step 1] 识别高误差站点...")
    he_cfg = cfg.get("high_error_site", {})
    top_n = he_cfg.get("top_n", 15)
    nrmse_thresh = he_cfg.get("nrmse_threshold_pct", 12.0)

    site_nrmse_valid = compute_site_nrmse(valid_df, bl_col)
    site_nrmse_valid = site_nrmse_valid.sort_values("nrmse", ascending=False)
    top_sites = set(site_nrmse_valid.head(top_n)["site_id"].tolist())
    above_thresh = set(site_nrmse_valid[site_nrmse_valid["nrmse"] > nrmse_thresh]["site_id"].tolist())
    high_error_sites = top_sites | above_thresh

    print(f"  top_{top_n} 站点 NRMSE > {nrmse_thresh}% 的站点: {len(high_error_sites)} 个")
    print(f"  高误差站点列表: {sorted(high_error_sites)}")

    site_list_df = site_nrmse_valid.copy()
    site_list_df["is_high_error"] = site_list_df["site_id"].isin(high_error_sites)
    site_list_df.to_csv(OUT / "round70_high_error_site_list.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] 高误差站点列表: {OUT / 'round70_high_error_site_list.csv'}")

    # ── 特征 ────────────────────────────────────────────────────────────────
    FEATURES = [
        "hour", "month", "dayofyear", "latitude", "longitude",
        "capacity_mw", "g_blend_pred", "clear_sky_ghi", "clear_sky_index",
        "t2m_c", "solar_elevation",
        "site_zero_ratio_6_19", "site_positive_count_train_valid",
        "pr_median", "quality_score",
        "baseline_norm",
    ]

    # ── 对高误差站点训练专家模型 ────────────────────────────────────────────
    print("\n[Step 2] 训练高误差站点专家模型...")

    train_he = train_df[train_df["site_id"].isin(high_error_sites)].copy()
    valid_he = valid_df[valid_df["site_id"].isin(high_error_sites)].copy()
    test_he = test_df[test_df["site_id"].isin(high_error_sites)].copy()

    print(f"  高误差站点训练样本: {len(train_he):,}")
    print(f"  高误差站点 valid 样本: {len(valid_he):,}")
    print(f"  高误差站点 test 样本: {len(test_he):,}")

    if len(train_he) < 100:
        print("  高误差站点训练样本不足，跳过高误差专家训练")
        # 直接保留 baseline
        valid_df[CANDIDATE_COL] = valid_df[bl_col].values
        test_df[CANDIDATE_COL] = test_df[bl_col].values
    else:
        X_tr = prep_X(train_he, FEATURES)
        y_tr = train_he["y_norm"].values.astype(float)

        w_cfg = cfg.get("sample_weight", {})
        train_he["sample_weight"] = train_he.apply(
            lambda r: float(np.clip(
                w_cfg.get("high_error_site", 1.8) * w_cfg.get("base", 1.0),
                w_cfg.get("min_weight", 0.3), w_cfg.get("max_weight", 3.0)
            )), axis=1
        )
        w_tr = train_he["sample_weight"].values.astype(float)

        model = LGBMRegressor(
            n_estimators=2500, max_depth=8, num_leaves=63,
            learning_rate=0.02, reg_lambda=2.0, reg_alpha=0.5,
            min_child_samples=10, subsample=0.85, colsample_bytree=0.85,
            random_state=42, n_jobs=-1, verbose=-1,
        )
        model.fit(X_tr, y_tr, sample_weight=w_tr)

        # valid 推理（per-site）
        valid_he = valid_he.copy()
        X_va = prep_X(valid_he, FEATURES)
        pred_norm = model.predict(X_va)
        cap_va = valid_he["capacity_mw"].values.astype(float)
        valid_he[CANDIDATE_COL] = np.clip(pred_norm * cap_va, 0, cap_va)

        # test 推理
        test_he = test_he.copy()
        X_te = prep_X(test_he, FEATURES)
        pred_norm_t = model.predict(X_te)
        cap_te = test_he["capacity_mw"].values.astype(float)
        test_he[CANDIDATE_COL] = np.clip(pred_norm_t * cap_te, 0, cap_te)

    # 非高误差站点保持 baseline
    valid_df[CANDIDATE_COL] = np.nan
    test_df[CANDIDATE_COL] = np.nan
    valid_df.loc[valid_df["site_id"].isin(high_error_sites), CANDIDATE_COL] = \
        valid_he.set_index(["time", "site_id"])[CANDIDATE_COL].reindex(
            valid_df.loc[valid_df["site_id"].isin(high_error_sites)].set_index(["time", "site_id"]).index
        ).values
    test_df.loc[test_df["site_id"].isin(high_error_sites), CANDIDATE_COL] = \
        test_he.set_index(["time", "site_id"])[CANDIDATE_COL].reindex(
            test_df.loc[test_df["site_id"].isin(high_error_sites)].set_index(["time", "site_id"]).index
        ).values

    # 缺失的填充 baseline
    valid_df[CANDIDATE_COL] = valid_df[CANDIDATE_COL].fillna(valid_df[bl_col])
    test_df[CANDIDATE_COL] = test_df[CANDIDATE_COL].fillna(test_df[bl_col])

    # ── valid 门控决策 ────────────────────────────────────────────────────
    print("\n[Step 3] valid 门控决策...")

    # per-site NRMSE 对比
    site_nrmse_base = compute_site_nrmse(valid_df, bl_col).set_index("site_id")
    site_nrmse_cand = compute_site_nrmse(valid_df, CANDIDATE_COL).set_index("site_id")

    improve_rows = []
    for sid in high_error_sites:
        if sid not in site_nrmse_base.index or sid not in site_nrmse_cand.index:
            continue
        base_n = site_nrmse_base.loc[sid, "nrmse"]
        cand_n = site_nrmse_cand.loc[sid, "nrmse"]
        delta = cand_n - base_n
        improve_rows.append({
            "site_id": sid,
            "base_nrmse": round(base_n, 4),
            "cand_nrmse": round(cand_n, 4),
            "delta_pp": round(delta, 4),
            "improve_min_pp": he_cfg.get("valid_improve_min_pp", 0.5),
            "adopted": delta < -he_cfg.get("valid_improve_min_pp", 0.5),
        })

    improve_df = pd.DataFrame(improve_rows)
    if len(improve_df) > 0:
        improve_df["adopted"] = improve_df["delta_pp"] < -he_cfg.get("valid_improve_min_pp", 0.5)
        adopted = set(improve_df[improve_df["adopted"]]["site_id"])
        print(f"  站点改善数量: {len(adopted)} / {len(high_error_sites)}")
        print(f"  采纳站点: {sorted(adopted)}")

        # city NRMSE 检查
        city_base = compute_city_nrmse(valid_df, bl_col)
        # 对采纳站点使用专家，对其他保持 baseline
        valid_df["temp_pred"] = valid_df[bl_col].values.copy()
        for sid in adopted:
            mask = (valid_df["site_id"] == sid) & valid_df[CANDIDATE_COL].notna()
            valid_df.loc[mask, "temp_pred"] = valid_df.loc[mask, CANDIDATE_COL].values
        city_adopted = compute_city_nrmse(valid_df, "temp_pred")
        city_worse = city_adopted - city_base
        print(f"  city_nrmse 变化: {city_base:.3f}% → {city_adopted:.3f}%  ({city_worse:+.3f}pp)")
        adopt_decision = city_worse <= he_cfg.get("city_nrmse_worse_max_pp", 0.05)
        print(f"  city NRMSE 门控: {'通过' if adopt_decision else '未通过'}")

        # 最终预测
        if adopt_decision:
            print("  决策：采纳专家预测")
        else:
            print("  决策：保持 baseline（city NRMSE 门控未通过）")
            valid_df[CANDIDATE_COL] = valid_df[bl_col].values
            test_df[CANDIDATE_COL] = test_df[bl_col].values

    # ── 输出对比 ────────────────────────────────────────────────────────────
    compare_rows = []
    for split_name, split_df in [("valid", valid_df), ("test", test_df)]:
        if len(split_df) == 0:
            continue
        site_base = compute_site_nrmse(split_df, bl_col)
        site_cand = compute_site_nrmse(split_df, CANDIDATE_COL)
        for _, row in site_base.iterrows():
            sid = row["site_id"]
            cand_row = site_cand[site_cand["site_id"] == sid]
            if len(cand_row) == 0:
                continue
            compare_rows.append({
                "split": split_name,
                "site_id": sid,
                "base_nrmse": round(row["nrmse"], 4),
                "cand_nrmse": round(cand_row.iloc[0]["nrmse"], 4),
                "delta_pp": round(cand_row.iloc[0]["nrmse"] - row["nrmse"], 4),
                "is_high_error": sid in high_error_sites,
            })

    comp_df = pd.DataFrame(compare_rows)
    if len(comp_df) > 0:
        comp_df.to_csv(OUT / "round70_high_error_expert_valid_compare.csv",
                       index=False, encoding="utf-8-sig")
        print(f"\n[OK] 高误差专家对比: {OUT / 'round70_high_error_expert_valid_compare.csv'}")

    # ── 更新候选 pkl ───────────────────────────────────────────────────────────
    print("\n[Step 4] 更新候选 pkl...")
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

    print("\n[OK] train_round70_high_error_site_expert 完成!")


if __name__ == "__main__":
    main()
