#!/usr/bin/env python3
"""
select_round73_candidate_by_backtest.py
基于回测窗口选择 Round73 候选。
"""

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round73"


def _rmse(a, p):
    a = np.asarray(a, dtype=float)
    p = np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def _city_nrmse(df, pred_col):
    cap_sum = float(df.drop_duplicates("site_id")["capacity_mw"].sum())
    agg = df.groupby("time", as_index=False).agg(
        a=("power_mw", "sum"),
        p=(pred_col, "sum")
    )
    return _rmse(agg["a"].values, agg["p"].values) / cap_sum * 100 if cap_sum > 0 else float("nan")


def _abs_bias(df, pred_col):
    a = float(df["power_mw"].sum())
    p = float(df[pred_col].sum())
    return abs((p - a) / a * 100) if abs(a) > 1e-9 else float("nan")


def _site_mean_nrmse(df, pred_col):
    vals = []
    for _, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        vals.append(_rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100)
    return float(np.mean(vals)) if vals else float("nan")


def _bad_sites(df, base_col, cand_col, threshold=1.0):
    n = 0
    for _, sdf in df[df["hour"].between(6, 19)].groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        b_r = _rmse(sdf["power_mw"].values, sdf[base_col].values)
        c_r = _rmse(sdf["power_mw"].values, sdf[cand_col].values)
        if (c_r - b_r) / cap * 100 > threshold:
            n += 1
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    # 读取回测数据集（包含候选预测）
    ds_path = OUT / "training_v2_backtest_dataset.parquet"
    backtest_df = pd.read_parquet(ds_path)
    print(f"[INFO] 回测数据: {len(backtest_df):,}")

    # 读取完整 pkl（包含候选预测）
    pkl_path = OUT / "round73_candidates.pkl"
    full_df = pd.read_pickle(pkl_path)
    full_df["time"] = pd.to_datetime(full_df["time"])
    full_df["hour"] = full_df["time"].dt.hour
    test_df = full_df[full_df["split"] == "test"].copy()
    test_df = test_df[test_df["hour"].between(6, 19)]
    print(f"[INFO] test: {len(test_df):,}")

    bl_col = "power_pred_final"
    candidate_cols = [c for c in full_df.columns if c.startswith("power_pred_round73_")]
    print(f"[INFO] 候选: {candidate_cols}")

    # 回测窗口评估（只用非 test 窗口）
    # wA=2023-09~12, wB=2024-09~12, wC=2025-05~08
    windows = {
        "window_A": backtest_df[backtest_df["window"] == "window_A"],
        "window_B": backtest_df[backtest_df["window"] == "window_B"],
        "window_C": backtest_df[backtest_df["window"] == "window_C"],
    }
    # wC 对应 2025-05~08，与 valid 时间范围相同，作为 valid 模拟窗口
    # wA 和 wB 是历史回测窗口

    print("\n[Backtest Evaluation]")
    rows = []
    for cand in candidate_cols:
        if cand not in backtest_df.columns:
            continue
        for wname, wdf in windows.items():
            if len(wdf) == 0:
                continue
            bn = _city_nrmse(wdf, bl_col)
            cn = _city_nrmse(wdf, cand)
            site_b = _site_mean_nrmse(wdf, bl_col)
            site_c = _site_mean_nrmse(wdf, cand)
            abs_b = _abs_bias(wdf, bl_col)
            abs_c = _abs_bias(wdf, cand)
            bad = _bad_sites(wdf, bl_col, cand)
            rows.append({
                "candidate": cand,
                "window": wname,
                "city_nrmse_b": round(bn, 4),
                "city_nrmse_c": round(cn, 4),
                "delta": round(cn - bn, 4),
                "site_nrmse_b": round(site_b, 4),
                "site_nrmse_c": round(site_c, 4),
                "site_delta": round(site_c - site_b, 4),
                "abs_bias_b": round(abs_b, 4),
                "abs_bias_c": round(abs_c, 4),
                "abs_bias_delta": round(abs_c - abs_b, 4),
                "bad_sites": bad,
            })

    compare_df = pd.DataFrame(rows)
    compare_df.to_csv(OUT / "round73_backtest_candidate_compare.csv",
                     index=False, encoding="utf-8-sig")
    print(f"[OK] {OUT / 'round73_backtest_candidate_compare.csv'}")
    if len(compare_df) > 0:
        print(compare_df.to_string(index=False))

    # 决策
    print("\n[Decision]")
    # 通过条件：至少2个回测窗口，且秋冬(wA/wB)上满足
    guards_pass = {}
    for cand in candidate_cols:
        if cand not in compare_df["candidate"].values:
            guards_pass[cand] = False
            continue
        cand_rows = compare_df[compare_df["candidate"] == cand]
        n_pass = int((cand_rows["bad_sites"] == 0).sum())
        n_autumn_pass = int(
            cand_rows[cand_rows["window"].isin(["window_A", "window_B"])]["bad_sites"].eq(0).sum()
        )
        guards_pass[cand] = n_pass >= 2 and n_autumn_pass >= 1

    passing = [c for c, v in guards_pass.items() if v]
    print(f"  通过门控: {passing}")

    # test 最终评估（只用 wC 作为 valid 代理）
    wC_df = windows["window_C"]
    best_cand = None
    best_delta = float("inf")
    for cand in passing:
        bn = _city_nrmse(wC_df, bl_col)
        cn = _city_nrmse(wC_df, cand)
        if cn < bn and (bn - cn) > best_delta:
            best_delta = bn - cn
            best_cand = cand

    if best_cand and best_delta > 0.005:
        recommend = best_cand
        reason = f"backtest pass, wC delta={best_delta:.3f}pp"
    else:
        recommend = bl_col
        reason = "no candidate passed all backtest guards"

    decision = {
        "recommend_adopt": best_cand is not None,
        "adopted_col": recommend if best_cand else bl_col,
        "baseline_col": bl_col,
        "passing_candidates": passing,
        "best_backtest_delta": round(best_delta, 4) if best_cand else None,
        "reason": reason,
    }
    with open(OUT / "round73_candidate_decision.json", "w", encoding="utf-8") as f:
        json.dump(decision, f, ensure_ascii=False, indent=2)
    print(f"  adopt: {decision['adopted_col']}")
    print(f"  reason: {reason}")
    print(f"\n[OK] {OUT / 'round73_candidate_decision.json'}")
    print("[OK] select 完成!")


if __name__ == "__main__":
    main()
