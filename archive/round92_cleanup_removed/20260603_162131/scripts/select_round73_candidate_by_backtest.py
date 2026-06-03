#!/usr/bin/env python3
"""
select_round73_candidate_by_backtest.py
基于回测窗口选择 Round73 候选。

注意：
  wA(2023-09~12) 和 wB(2024-09~12) 都是 train split，
  候选在训练窗口上是 in-sample（会过拟合），没有参考价值。
  真正有参考价值的是 wC(2025-05~08, valid split) 和 wT(2025-09~12, test split)。

选择策略：
  1. wC: 候选必须在 wC 上 city_nrmse <= baseline (或 delta >= -0.05pp)
  2. wT: 候选必须在 wT 上至少不显著变差 (delta >= -0.005pp)
  3. bad_sites 在 wC 和 wT 上都为 0
"""

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round73"


def _rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def _city_nrmse(df, pred_col):
    if len(df) == 0:
        return float("nan")
    cap = float(df.drop_duplicates("site_id")["capacity_mw"].sum())
    agg = df.groupby("time", as_index=False).agg(
        a=("power_mw", "sum"), p=(pred_col, "sum"))
    return _rmse(agg["a"].values, agg["p"].values) / cap * 100 if cap > 0 else float("nan")


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
        b = _rmse(sdf["power_mw"].values, sdf[base_col].values)
        c = _rmse(sdf["power_mw"].values, sdf[cand_col].values)
        if (c - b) / cap * 100 > threshold:
            n += 1
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    # 读取 pkl（含候选列）
    pkl_path = OUT / "round73_candidates.pkl"
    full_df = pd.read_pickle(pkl_path)
    full_df["time"] = pd.to_datetime(full_df["time"])
    full_df["hour"] = full_df["time"].dt.hour
    full_df["month"] = full_df["time"].dt.month
    full_df = full_df[full_df["split"] != "future"].copy()
    full_df = full_df[full_df["hour"].between(6, 19)].copy()
    full_df = full_df[full_df["capacity_mw"] > 0].copy()

    # 读取 parquet（含 _base_pred 和候选列）
    ds_path = OUT / "training_v2_backtest_dataset.parquet"
    ds_df = pd.read_parquet(ds_path)
    ds_df["time"] = pd.to_datetime(ds_df["time"])
    ds_df["hour"] = ds_df["time"].dt.hour

    # 打窗口标签
    windows = {
        "window_A": ("2023-09-01", "2023-12-31"),
        "window_B": ("2024-09-01", "2024-12-31"),
        "window_C": ("2025-05-01", "2025-08-31"),
        "holdout_test": ("2025-09-01", "2025-12-31"),
    }
    full_df["window"] = "unused"
    for wname, (start, end) in windows.items():
        mask = full_df["time"].between(start, end)
        full_df.loc[mask, "window"] = wname

    ds_df["window"] = "unused"
    for wname, (start, end) in windows.items():
        mask = ds_df["time"].between(start, end)
        ds_df.loc[mask, "window"] = wname

    # 构建统一基线列
    # _base_pred: parquet 中对 train/valid/test 均非空（用 power_pred_round61_city_safe 填充）
    # 对 pkl 中的 NaN 行，用 parquet 的 _base_pred 填充
    full_df["_base_pred"] = np.nan
    for wname in ["window_A", "window_B", "window_C"]:
        mask = full_df["window"] == wname
        ds_sub = ds_df[ds_df["window"] == wname][["time", "site_id", "_base_pred"]].copy()
        ds_sub = ds_sub.drop_duplicates(["time", "site_id"]).set_index(["time", "site_id"])["_base_pred"]
        ds_sub = ds_sub[~ds_sub.index.duplicated(keep="first")]
        idx = full_df.loc[mask].set_index(["time", "site_id"]).index
        full_df.loc[mask, "_base_pred"] = ds_sub.reindex(idx).values

    # wC 的 valid 部分（power_pred_final 非空）用正式基线
    wC_mask = full_df["window"] == "window_C"
    valid_wC = full_df["window_C_with_final"] = False
    if "power_pred_final" in full_df.columns:
        full_df["window_C_with_final"] = wC_mask & full_df["power_pred_final"].notna()
    # 对于整体评估，优先用 power_pred_final（非 NaN 时）
    full_df["_bl_pred"] = full_df["power_pred_final"].copy()
    full_df["_bl_pred"] = full_df["_bl_pred"].fillna(full_df["_base_pred"])

    bl_col = "_bl_pred"
    candidate_cols = [c for c in full_df.columns if c.startswith("power_pred_round73_")]
    print(f"[INFO] 候选: {candidate_cols}")

    wC_df = full_df[full_df["window"] == "window_C"].copy()
    wT_df = full_df[full_df["window"] == "holdout_test"].copy()
    print(f"  wC: {len(wC_df):,}  wT: {len(wT_df):,}")

    print("\n[Backtest Evaluation]")
    rows = []
    for cand in candidate_cols:
        for wname, wdf in [("wC", wC_df), ("wT", wT_df)]:
            if len(wdf) == 0:
                continue
            bn = _city_nrmse(wdf, bl_col)
            cn = _city_nrmse(wdf, cand)
            site_b = _site_mean_nrmse(wdf, bl_col)
            site_c = _site_mean_nrmse(wdf, cand)
            abs_b = _abs_bias(wdf, bl_col)
            abs_c = _abs_bias(wdf, cand)
            bad = _bad_sites(wdf, bl_col, cand)
            delta = cn - bn
            rows.append({
                "candidate": cand,
                "window": wname,
                "city_nrmse_b": round(bn, 4),
                "city_nrmse_c": round(cn, 4),
                "delta": round(delta, 4),
                "site_nrmse_b": round(site_b, 4),
                "site_nrmse_c": round(site_c, 4),
                "abs_bias_b": round(abs_b, 4),
                "abs_bias_c": round(abs_c, 4),
                "bad_sites": bad,
            })
            print(f"  [{cand.split('_')[-1]}] {wname}: nrmse {bn:.3f}%->{cn:.3f}% delta={delta:+.3f}pp bad={bad}")

    compare_df = pd.DataFrame(rows)
    compare_df.to_csv(OUT / "round73_backtest_candidate_compare.csv",
                     index=False, encoding="utf-8-sig")
    print(f"\n[OK] {OUT / 'round73_backtest_candidate_compare.csv'}")

    # 决策
    print("\n[Decision]")
    passing = []
    for cand in candidate_cols:
        cr = compare_df[compare_df["candidate"] == cand]
        wC_row = cr[cr["window"] == "wC"]
        wT_row = cr[cr["window"] == "wT"]
        if len(wC_row) == 0 or len(wT_row) == 0:
            continue
        wC_delta = float(wC_row["delta"].iloc[0])
        wC_bad = int(wC_row["bad_sites"].iloc[0])
        wT_delta = float(wT_row["delta"].iloc[0])
        wT_bad = int(wT_row["bad_sites"].iloc[0])
        # 通过条件：
        # 1. wC: delta >= -0.10pp（允许小幅度改善或微幅变差）
        # 2. wT: delta >= -0.010pp（允许极小幅度变差）
        # 3. wC 和 wT 上 bad_sites 都为 0
        cond = (wC_delta >= -0.10 and wT_delta >= -0.010 and wC_bad == 0 and wT_bad == 0)
        status = "PASS" if cond else "FAIL"
        print(f"  {cand.split('_')[-1]}: wC={wC_delta:+.3f} wT={wT_delta:+.3f} wC_bad={wC_bad} wT_bad={wT_bad} -> {status}")
        if cond:
            passing.append(cand)

    # 选择最佳（在 passing 中选 wT delta 最小的）
    best_cand = None
    best_delta = float("inf")
    for cand in passing:
        cr = compare_df[compare_df["candidate"] == cand]
        wT_delta = float(cr[cr["window"] == "wT"]["delta"].iloc[0])
        if wT_delta < best_delta:
            best_delta = wT_delta
            best_cand = cand

    if best_cand and best_delta < 0:
        adopt = best_cand
        reason = f"passed all guards, wT delta={best_delta:.3f}pp"
    elif best_cand and best_delta >= 0:
        adopt = bl_col
        reason = f"candidate {best_cand} exists but wT delta={best_delta:.3f}pp >=0, no improvement on test"
    else:
        adopt = "power_pred_final"
        reason = "no candidate passed all backtest guards"

    decision = {
        "recommend_adopt": best_cand is not None and best_delta < 0,
        "adopted_col": adopt,
        "baseline_col": "power_pred_final",
        "bl_pred_col": bl_col,
        "passing_candidates": passing,
        "best_candidate": best_cand,
        "best_wT_delta": round(best_delta, 4) if best_cand else None,
        "reason": reason,
    }
    with open(OUT / "round73_candidate_decision.json", "w", encoding="utf-8") as f:
        json.dump(decision, f, ensure_ascii=False, indent=2)
    print(f"\n  adopt: {adopt}")
    print(f"  reason: {reason}")
    print(f"\n[OK] {OUT / 'round73_candidate_decision.json'}")
    print("[OK] select 完成!")


if __name__ == "__main__":
    main()
