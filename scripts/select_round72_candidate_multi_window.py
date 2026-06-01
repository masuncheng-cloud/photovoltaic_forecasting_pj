#!/usr/bin/env python3
"""
select_round72_candidate_multi_window.py
====================================
Round72 多窗口候选选择（基于一致基线的候选）。

输出：
    output/pv_pipeline/round72/round72_valid_window_compare.csv
    output/pv_pipeline/round72/round72_candidate_decision.json
    output/pv_pipeline/round72/round72_safe_blend_weights.csv
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round72"


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def compute_city_nrmse(df, pred_col):
    cap_sum = float(df.drop_duplicates("site_id")["capacity_mw"].sum())
    agg = df.groupby("time", as_index=False).agg(
        a=("power_mw", "sum"), p=(pred_col, "sum"))
    return rmse(agg["a"].values, agg["p"].values) / cap_sum * 100 if cap_sum > 0 else np.nan


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


def count_bad_sites(df, base_col, pred_col, threshold=1.0):
    n = 0
    for _, sdf in df[df["hour"].between(6, 19)].groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        b_r = rmse(sdf["power_mw"].values, sdf[base_col].values)
        c_r = rmse(sdf["power_mw"].values, sdf[pred_col].values)
        if (c_r - b_r) / cap * 100 > threshold:
            n += 1
    return n


def main():
    parser = argparse.ArgumentParser(description="Round72 多窗口选择")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    if args.config is None:
        args.config = str(PROJECT_ROOT / "configs" / "round72_consistent_base.yaml")
    cfg = yaml.safe_load(open(args.config))

    OUT.mkdir(parents=True, exist_ok=True)

    cand_path = OUT / "round72_residual_candidates.pkl"
    print(f"[INFO] 读取: {cand_path}")
    df = pd.read_pickle(cand_path)
    df["time"] = pd.to_datetime(df["time"])
    df["month"] = df["time"].dt.month

    bl_col = cfg["baseline_final_col"]
    focus_hours = cfg.get("focus_hours", [10, 11, 12, 13, 14])
    guards = cfg.get("candidate_guards", {})

    # ── 构建多窗口 ───────────────────────────────────────────────────
    train_df = df[df["split"] == "train"].copy()
    valid_df_orig = df[df["split"] == "valid"].copy()

    # window_early: 5-6 月（或 train 最后两个月）
    w_early = train_df[train_df["month"].isin([5, 6])].copy()
    if len(w_early) < 100:
        avail_months = sorted(train_df["month"].unique())
        w_early = train_df[train_df["month"].isin(avail_months[-2:])].copy()

    w_late = valid_df_orig.copy()
    print(f"\n[Step 1] 窗口: window_early={len(w_early):,}行  "
          f"window_late={len(w_late):,}行")

    # ── 候选列 ──────────────────────────────────────────────────────
    candidate_cols = [c for c in df.columns
                     if c.startswith("power_pred_round72_")]
    print(f"[INFO] 候选: {candidate_cols}")

    # ── Step 2: 多窗口门控 ──────────────────────────────────────────
    print("\n[Step 2] 多窗口门控评估...")
    window_rows = []

    for col in candidate_cols:
        if col not in df.columns:
            continue
        for win_name, win_df in [("window_early", w_early), ("window_late", w_late)]:
            if len(win_df) == 0:
                continue

            city_nrmse_b = compute_city_nrmse(win_df, bl_col)
            city_nrmse_c = compute_city_nrmse(win_df, col)
            site_nrmse_b = compute_site_mean_nrmse(win_df, bl_col)
            site_nrmse_c = compute_site_mean_nrmse(win_df, col)
            bias_b = compute_city_bias(win_df, bl_col)
            bias_c = compute_city_bias(win_df, col)
            bad_s = count_bad_sites(win_df, bl_col, col)

            passes = (
                bad_s <= guards.get("bad_site_gt_1pp_max", 0) and
                (city_nrmse_c - city_nrmse_b) <= guards.get("city_nrmse_6_19_max_worse_pp", 0.05)
            )

            window_rows.append({
                "candidate": col, "window": win_name,
                "city_nrmse_b": round(city_nrmse_b, 4),
                "city_nrmse_c": round(city_nrmse_c, 4),
                "city_nrmse_delta": round(city_nrmse_c - city_nrmse_b, 4),
                "site_nrmse_b": round(site_nrmse_b, 4),
                "site_nrmse_c": round(site_nrmse_c, 4),
                "site_nrmse_delta": round(site_nrmse_c - site_nrmse_b, 4),
                "bias_b": round(bias_b, 4), "bias_c": round(bias_c, 4),
                "bias_delta": round(bias_c - bias_b, 4),
                "bad_sites": bad_s,
                "passes_guard": passes,
            })

    win_df_out = pd.DataFrame(window_rows)
    # 保存原始窗口结果（blend 循环会覆盖 win_df_out）
    window_compare_df = win_df_out.copy()
    win_df_out.to_csv(OUT / "round72_valid_window_compare.csv",
                      index=False, encoding="utf-8-sig")
    print(f"[OK] {OUT / 'round72_valid_window_compare.csv'}")
    if len(win_df_out):
        print(win_df_out.to_string(index=False))

    # ── Step 3: Safe Blend ───────────────────────────────────────────
    print("\n[Step 3] Safe Blend 权重搜索...")
    BLEND_COL = "power_pred_round72_safe_blend"
    weights_grid = [0.0, 0.25, 0.50, 0.75, 1.0]

    blend_rows = []
    bl_nrmse_late = compute_city_nrmse(w_late, bl_col)

    for w1 in weights_grid:
        for w2 in weights_grid:
            for w3 in weights_grid:
                w_sum = w1 + w2 + w3
                if w_sum == 0:
                    continue
                w1n, w2n, w3n = w1 / w_sum, w2 / w_sum, w3 / w_sum

                for win_name, win_df in [("window_early", w_early), ("window_late", w_late)]:
                    blend = win_df[bl_col].values.astype(float).copy()
                    for i, c in enumerate(candidate_cols):
                        if c in win_df.columns:
                            ww = [w1n, w2n, w3n][i] if i < 3 else 0.0
                            blend = blend + ww * (win_df[c].values.astype(float) - win_df[bl_col].values.astype(float))

                    win_df_out = win_df.copy()
                    win_df_out[BLEND_COL] = blend
                    city_nrmse = compute_city_nrmse(win_df_out, BLEND_COL)
                    bad_s = count_bad_sites(win_df_out, bl_col, BLEND_COL)
                    nrmse_b = compute_city_nrmse(win_df_out, bl_col)

                    passes = (
                        bad_s <= guards.get("bad_site_gt_1pp_max", 0) and
                        (city_nrmse - nrmse_b) <= guards.get("city_nrmse_6_19_max_worse_pp", 0.05)
                    )

                    blend_rows.append({
                        "candidate": f"blend_w1={w1}_w2={w2}_w3={w3}",
                        "w_season": w1, "w_noon": w2, "w_he": w3,
                        "window": win_name,
                        "city_nrmse": round(city_nrmse, 4),
                        "delta": round(city_nrmse - nrmse_b, 4),
                        "bad_sites": bad_s,
                        "passes": passes,
                    })

    pd.DataFrame(blend_rows).to_csv(OUT / "round72_safe_blend_weights.csv",
                                    index=False, encoding="utf-8-sig")

    # 最优 safe blend（两个窗口都通过门控）
    passing_blends = [r for r in blend_rows if r["passes"]]
    best_blend = None
    best_blend_nrmse = float("inf")
    best_weights = {}

    for r in passing_blends:
        if r["city_nrmse"] < best_blend_nrmse:
            best_blend_nrmse = r["city_nrmse"]
            best_blend = r
            best_weights = {"w_season": r["w_season"],
                           "w_noon": r["w_noon"], "w_he": r["w_he"]}

    if best_blend:
        print(f"  最优 blend: {best_weights}  city_nrmse={best_blend_nrmse:.4f}%  "
              f"Δ={best_blend_nrmse-bl_nrmse_late:+.4f}pp")
    else:
        print("  无通过门控的 blend")

    # ── Step 4: 决策 ─────────────────────────────────────────────────
    print("\n[Step 4] 最终决策...")

    passing_cands = window_compare_df[window_compare_df["passes_guard"]]["candidate"].unique().tolist()
    baseline_nrmse = compute_city_nrmse(w_late, bl_col)
    baseline_site = compute_site_mean_nrmse(w_late, bl_col)

    decision = {
        "recommend_adopt": False,
        "adopted_col": bl_col,
        "baseline_city_nrmse": round(baseline_nrmse, 4),
        "baseline_site_nrmse": round(baseline_site, 4),
        "passing_candidates": passing_cands,
        "best_blend_weights": best_weights,
        "best_blend_delta": round(best_blend_nrmse - bl_nrmse_late, 4) if best_blend else None,
        "reason": "no candidate passed all guards in both windows",
    }

    # 如果有最优 blend 且有改善，采用
    if best_blend and best_blend_nrmse < bl_nrmse_late - 0.01:
        decision.update({
            "recommend_adopt": True,
            "adopted_col": BLEND_COL,
            "reason": f"safe_blend improves city_nrmse by {bl_nrmse_late-best_blend_nrmse:.3f}pp "
                      f"(w_season={best_weights['w_season']}, w_noon={best_weights['w_noon']})",
        })
    elif best_blend:
        decision["reason"] = f"best blend Δ={best_blend_nrmse-bl_nrmse_late:.3f}pp (no significant improvement)"

    with open(OUT / "round72_candidate_decision.json", "w", encoding="utf-8") as f:
        json.dump(decision, f, ensure_ascii=False, indent=2)

    print(f"[OK] 决策: {OUT / 'round72_candidate_decision.json'}")
    print(f"  采用: {decision['adopted_col']}")
    print(f"  原因: {decision['reason']}")

    print("\n[OK] select_round72 完成!")


if __name__ == "__main__":
    main()
