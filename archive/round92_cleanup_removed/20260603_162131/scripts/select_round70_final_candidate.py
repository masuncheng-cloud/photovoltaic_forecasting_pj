#!/usr/bin/env python3
"""
select_round70_final_candidate.py
================================
在 valid 上对所有候选进行门控评估，选择最优 safe blend 权重，
并决定是否采用 Round70。

候选列表：
    power_pred_final          （当前正式基线）
    power_pred_round70_active_state_lgb
    power_pred_round70_noon_bias_lgb
    power_pred_round70_high_error_expert

融合方式：
    P_blend = baseline + w1*(active_state - baseline)
                     + w2*(noon_bias - baseline)
                     + w3*(high_error - baseline)

输出：
    output/pv_pipeline/round70/round70_valid_candidate_compare.csv
    output/pv_pipeline/round70/round70_candidate_decision.json
    output/pv_pipeline/round70/round70_stacked_blend_weights.csv
"""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round70"


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def compute_site_mean_nrmse(df, pred_col):
    vals = []
    for _, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        vals.append(rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100)
    return float(np.mean(vals)) if vals else np.nan


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


def compute_city_bias(df, pred_col):
    a_sum = float(df["power_mw"].sum())
    p_sum = float(df[pred_col].sum())
    return (p_sum - a_sum) / a_sum * 100 if abs(a_sum) > 1e-9 else np.nan


def compute_city_bias_hourly(df, pred_col, hours):
    d = df[df["hour"].isin(hours)]
    a_sum = float(d["power_mw"].sum())
    p_sum = float(d[pred_col].sum())
    return (p_sum - a_sum) / a_sum * 100 if abs(a_sum) > 1e-9 else np.nan


def count_bad_sites(df, base_col, pred_col, threshold=1.0):
    n = 0
    details = []
    for _, sdf in df[df["hour"].between(6, 19)].groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        b_r = rmse(sdf["power_mw"].values, sdf[base_col].values)
        c_r = rmse(sdf["power_mw"].values, sdf[pred_col].values)
        delta = (c_r - b_r) / cap * 100
        if delta > threshold:
            n += 1
            details.append((str(sdf["site_id"].iloc[0]), round(delta, 2)))
    return n, details


def main():
    parser = argparse.ArgumentParser(description="Round70 最终候选选择")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    if args.config is None:
        args.config = str(PROJECT_ROOT / "configs" / "round70_state_expert_model.yaml")
    cfg = yaml.safe_load(open(args.config))

    OUT.mkdir(parents=True, exist_ok=True)

    # ── 读取候选表 ──────────────────────────────────────────────────────────
    cand_path = OUT / "round70_candidates.pkl"
    print(f"[INFO] 读取候选表: {cand_path}")
    df = pd.read_pickle(cand_path)
    df["time"] = pd.to_datetime(df["time"])
    print(f"  总行数: {len(df):,}")

    bl_col = cfg["baseline_col"]
    focus_hours = cfg.get("focus_hours", [10, 11, 12, 13, 14])

    # 只保留 6-19 点
    df = df[df["hour"].between(6, 19)].copy()
    valid_df = df[df["split"] == "valid"].copy()
    test_df = df[df["split"] == "test"].copy()
    print(f"  valid={len(valid_df):,}  test={len(test_df):,}")

    # ── 候选列 ─────────────────────────────────────────────────────────────
    candidate_cols = [
        "power_pred_round70_active_state_lgb",
        "power_pred_round70_noon_bias_lgb",
        "power_pred_round70_high_error_expert",
    ]
    # 只保留存在的列
    candidate_cols = [c for c in candidate_cols if c in df.columns]
    print(f"\n[INFO] 候选列: {candidate_cols}")

    guards = cfg.get("candidate_guards", {})

    # ── Step 1: 门控评估每个候选 ──────────────────────────────────────────
    print("\n[Step 1] 门控评估...")
    guard_rows = []
    for col in candidate_cols:
        if col not in valid_df.columns:
            print(f"  [SKIP] {col} 不存在")
            continue

        # 基础指标
        city_nrmse_base = compute_city_nrmse(valid_df, bl_col)
        city_nrmse_cand = compute_city_nrmse(valid_df, col)
        site_nrmse_base = compute_site_mean_nrmse(valid_df, bl_col)
        site_nrmse_cand = compute_site_mean_nrmse(valid_df, col)
        city_nrmse_10_14_base = compute_city_nrmse_hourly(valid_df, bl_col, focus_hours)
        city_nrmse_10_14_cand = compute_city_nrmse_hourly(valid_df, col, focus_hours)
        bias_base = compute_city_bias(valid_df, bl_col)
        bias_cand = compute_city_bias(valid_df, col)
        bias_10_14_base = compute_city_bias_hourly(valid_df, bl_col, focus_hours)
        bias_10_14_cand = compute_city_bias_hourly(valid_df, col, focus_hours)
        bad_sites, _ = count_bad_sites(valid_df, bl_col, col, threshold=guards.get("bad_site_gt_1pp_max", 0) + 0.001)

        # 差异检查
        max_diff = float(np.nanmax(np.abs(valid_df[col].values - valid_df[bl_col].values)))
        mean_diff = float(np.nanmean(np.abs(valid_df[col].values - valid_df[bl_col].values)))
        n_changed = int((np.abs(valid_df[col].values - valid_df[bl_col].values) > 1e-8).sum())

        # 门控判定
        site_improve = site_nrmse_base - site_nrmse_cand
        city_worse = city_nrmse_cand - city_nrmse_base
        city_10_14_worse = city_nrmse_10_14_cand - city_nrmse_10_14_base
        abs_bias_worse = abs(bias_cand) - abs(bias_base)
        abs_bias_10_14_worse = abs(bias_10_14_cand) - abs(bias_10_14_base)

        passes = [
            bad_sites <= guards.get("bad_site_gt_1pp_max", 0),
            site_improve >= -guards.get("site_mean_nrmse_improve_min_pp", 0.10),
            city_worse <= guards.get("city_nrmse_6_19_max_worse_pp", 0.05),
            city_10_14_worse <= 0 if guards.get("city_nrmse_10_14_must_not_worse", True) else 999,
            abs_bias_worse <= guards.get("abs_bias_6_19_max_worse_pp", 0.30),
            abs_bias_10_14_worse <= guards.get("abs_bias_10_14_max_worse_pp", 0.30),
            max_diff > guards.get("require_candidate_diff_min_mw", 1e-6),
        ]

        guard_rows.append({
            "candidate_col": col,
            "city_nrmse_base": round(city_nrmse_base, 4),
            "city_nrmse_cand": round(city_nrmse_cand, 4),
            "city_nrmse_delta": round(city_nrmse_cand - city_nrmse_base, 4),
            "site_nrmse_base": round(site_nrmse_base, 4),
            "site_nrmse_cand": round(site_nrmse_cand, 4),
            "site_nrmse_delta": round(site_nrmse_cand - site_nrmse_base, 4),
            "city_nrmse_10_14_base": round(city_nrmse_10_14_base, 4),
            "city_nrmse_10_14_cand": round(city_nrmse_10_14_cand, 4),
            "city_nrmse_10_14_delta": round(city_nrmse_10_14_cand - city_nrmse_10_14_base, 4),
            "city_bias_base": round(bias_base, 4),
            "city_bias_cand": round(bias_cand, 4),
            "city_bias_delta": round(bias_cand - bias_base, 4),
            "city_bias_10_14_base": round(bias_10_14_base, 4),
            "city_bias_10_14_cand": round(bias_10_14_cand, 4),
            "bad_sites": bad_sites,
            "max_abs_diff_mw": round(max_diff, 6),
            "mean_abs_diff_mw": round(mean_diff, 6),
            "n_changed": n_changed,
            "pass_all_guards": all(passes),
            "reason_fail": " | ".join([
                f"bad_sites={bad_sites}" if not passes[0] else "",
                f"site_improve={site_improve:.3f}pp" if not passes[1] else "",
                f"city_worse={city_worse:.3f}pp" if not passes[2] else "",
                f"city_10_14_worse={city_10_14_worse:.3f}pp" if not passes[3] else "",
                f"abs_bias_worse={abs_bias_worse:.3f}pp" if not passes[4] else "",
                f"abs_bias_10_14_worse={abs_bias_10_14_worse:.3f}pp" if not passes[5] else "",
                f"max_diff={max_diff:.2e}<=min" if not passes[6] else "",
            ]).strip(" |"),
        })
        print(f"  {'✓' if all(passes) else '✗'} {col}")
        print(f"    city_nrmse: {city_nrmse_base:.3f} → {city_nrmse_cand:.3f} ({city_nrmse_cand-city_nrmse_base:+.3f}pp)")
        print(f"    site_nrmse: {site_nrmse_base:.3f} → {site_nrmse_cand:.3f} ({site_nrmse_cand-site_nrmse_base:+.3f}pp)")
        print(f"    city_nrmse_10_14: {city_nrmse_10_14_base:.3f} → {city_nrmse_10_14_cand:.3f} ({city_nrmse_10_14_cand-city_nrmse_10_14_base:+.3f}pp)")
        print(f"    bad_sites: {bad_sites}")

    guard_df = pd.DataFrame(guard_rows)
    guard_df.to_csv(OUT / "round70_valid_candidate_compare.csv",
                    index=False, encoding="utf-8-sig")
    print(f"\n[OK] valid 对比: {OUT / 'round70_valid_candidate_compare.csv'}")

    # ── Step 2: safe blend 权重搜索 ─────────────────────────────────────────
    print("\n[Step 2] Safe Blend 权重搜索...")

    BLEND_COL = "power_pred_round70_stacked_safe_blend"
    weights_grid = cfg.get("blend_weights", {}).get("grid", [0.0, 0.25, 0.50, 0.75, 1.0])

    blend_rows = []
    best_city_nrmse = compute_city_nrmse(valid_df, bl_col)
    best_weights = {c: 0.0 for c in candidate_cols}

    for w1 in weights_grid:
        for w2 in weights_grid:
            for w3 in weights_grid:
                w_sum = w1 + w2 + w3
                if w_sum == 0:
                    continue

                # 归一化
                w1n, w2n, w3n = w1 / w_sum, w2 / w_sum, w3 / w_sum

                blend = valid_df[bl_col].values.copy()
                for i, c in enumerate(candidate_cols):
                    if c in valid_df.columns:
                        ww = [w1n, w2n, w3n][i] if i < 3 else 0.0
                        blend = blend + ww * (valid_df[c].values - valid_df[bl_col].values)

                valid_df[BLEND_COL] = blend

                city_nrmse = compute_city_nrmse(valid_df, BLEND_COL)
                site_nrmse = compute_site_mean_nrmse(valid_df, BLEND_COL)
                city_nrmse_10_14 = compute_city_nrmse_hourly(valid_df, BLEND_COL, focus_hours)
                bad_s, _ = count_bad_sites(valid_df, bl_col, BLEND_COL)

                blend_rows.append({
                    "w1_active_state": round(w1, 4),
                    "w2_noon_bias": round(w2, 4),
                    "w3_high_error": round(w3, 4),
                    "w1n": round(w1n, 4),
                    "w2n": round(w2n, 4),
                    "w3n": round(w3n, 4),
                    "city_nrmse": round(city_nrmse, 4),
                    "site_mean_nrmse": round(site_nrmse, 4),
                    "city_nrmse_10_14": round(city_nrmse_10_14, 4),
                    "bad_sites": bad_s,
                    "city_nrmse_delta": round(city_nrmse - best_city_nrmse, 4),
                })

                # 更新最优
                passes_blend = [
                    bad_s <= guards.get("bad_site_gt_1pp_max", 0),
                    (site_nrmse - compute_site_mean_nrmse(valid_df, bl_col)) >= -guards.get("site_mean_nrmse_improve_min_pp", 0.10),
                    (city_nrmse - best_city_nrmse) <= guards.get("city_nrmse_6_19_max_worse_pp", 0.05),
                    (city_nrmse_10_14 - compute_city_nrmse_hourly(valid_df, bl_col, focus_hours)) <= 0 if guards.get("city_nrmse_10_14_must_not_worse", True) else 999,
                ]
                if all(passes_blend) and city_nrmse < best_city_nrmse:
                    best_city_nrmse = city_nrmse
                    best_weights = {"w1_active_state": w1, "w2_noon_bias": w2, "w3_high_error": w3,
                                    "w1n": w1n, "w2n": w2n, "w3n": w3n}

    blend_df = pd.DataFrame(blend_rows)
    blend_df.to_csv(OUT / "round70_stacked_blend_weights.csv",
                    index=False, encoding="utf-8-sig")
    print(f"[OK] blend 权重搜索: {OUT / 'round70_stacked_blend_weights.csv'}")

    print(f"\n  最优 blend 权重: {best_weights}")
    print(f"  最优 city_nrmse: {best_city_nrmse:.4f}%")
    print(f"  Baseline city_nrmse: {compute_city_nrmse(valid_df, bl_col):.4f}%")

    # ── Step 3: 最终决策 ──────────────────────────────────────────────────
    print("\n[Step 3] 最终决策...")

    # 检查是否有候选优于 baseline
    pass_candidates = guard_df[guard_df["pass_all_guards"]]
    print(f"  通过门控的候选: {len(pass_candidates)}")

    # 比较最优候选 vs baseline
    baseline_city_nrmse = compute_city_nrmse(valid_df, bl_col)
    baseline_site_nrmse = compute_site_mean_nrmse(valid_df, bl_col)

    decision = {
        "recommend_adopt": False,
        "adopted_col": bl_col,
        "baseline_city_nrmse_valid": round(baseline_city_nrmse, 4),
        "baseline_site_nrmse_valid": round(baseline_site_nrmse, 4),
        "best_candidate": None,
        "best_city_nrmse_valid": round(baseline_city_nrmse, 4),
        "best_site_nrmse_valid": round(baseline_site_nrmse, 4),
        "best_blend_weights": best_weights,
        "passing_candidates": pass_candidates["candidate_col"].tolist(),
        "reason": "no candidate passed all guards",
    }

    # 找最优通过门控的候选
    if len(pass_candidates) > 0:
        # 检查 blended 方案
        if best_weights and any(v > 0 for v in [best_weights.get("w1", 0), best_weights.get("w2", 0), best_weights.get("w3", 0)]):
            best_combination = {
                "recommend_adopt": best_city_nrmse < baseline_city_nrmse - 0.01,  # 至少 0.01pp 改善
                "adopted_col": BLEND_COL if best_city_nrmse < baseline_city_nrmse - 0.01 else bl_col,
                "baseline_city_nrmse_valid": round(baseline_city_nrmse, 4),
                "baseline_site_nrmse_valid": round(baseline_site_nrmse, 4),
                "best_candidate": BLEND_COL,
                "best_city_nrmse_valid": round(best_city_nrmse, 4),
                "best_blend_weights": best_weights,
                "passing_candidates": pass_candidates["candidate_col"].tolist(),
                "reason": f"blend city_nrmse={best_city_nrmse:.4f}% vs baseline={baseline_city_nrmse:.4f}%",
            }
            decision = best_combination
        else:
            # 找单个最优候选
            best_single = pass_candidates.sort_values("city_nrmse_cand").iloc[0]
            if best_single["city_nrmse_cand"] < baseline_city_nrmse - 0.01:
                decision.update({
                    "recommend_adopt": True,
                    "adopted_col": best_single["candidate_col"],
                    "best_candidate": best_single["candidate_col"],
                    "best_city_nrmse_valid": round(best_single["city_nrmse_cand"], 4),
                    "reason": f"{best_single['candidate_col']} passed guards and improves city_nrmse",
                })

    print(f"\n  决策: {decision['reason']}")
    print(f"  建议采用: {decision['adopted_col']}")

    with open(OUT / "round70_candidate_decision.json", "w", encoding="utf-8") as f:
        json.dump(decision, f, ensure_ascii=False, indent=2)
    print(f"[OK] 决策写出: {OUT / 'round70_candidate_decision.json'}")

    # ── Step 4: 生成最终 test 评估 ─────────────────────────────────────────
    print("\n[Step 4] 生成 test 预测...")
    # 应用最优 blend 到 test
    if decision["recommend_adopt"] and decision["adopted_col"] == BLEND_COL:
        w1n = best_weights.get("w1n", 0)
        w2n = best_weights.get("w2n", 0)
        w3n = best_weights.get("w3n", 0)
        test_blend = test_df[bl_col].values.copy()
        for i, c in enumerate(candidate_cols):
            if c in test_df.columns:
                ww = [w1n, w2n, w3n][i] if i < 3 else 0.0
                test_blend = test_blend + ww * (test_df[c].values - test_df[bl_col].values)
        test_df[BLEND_COL] = test_blend

    print("\n[OK] select_round70_final_candidate 完成!")


if __name__ == "__main__":
    main()
