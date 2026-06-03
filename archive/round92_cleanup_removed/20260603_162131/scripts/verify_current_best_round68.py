#!/usr/bin/env python3
"""
verify_current_best_round68.py
===========================
确认当前正式结果是否仍为 Round68 final，并校验指标。

输出：
    output/pv_pipeline/round73/round73_current_best_verify.json
    output/pv_pipeline/round73/round73_current_best_verify.csv
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round73"


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def compute_metrics(df, pred_col):
    d = df[df["hour"].between(6, 19)].copy()
    cap_sum = float(d.drop_duplicates("site_id")["capacity_mw"].sum())
    agg = d.groupby("time", as_index=False).agg(
        a=("power_mw", "sum"), p=(pred_col, "sum"))
    nrmse = rmse(agg["a"].values, agg["p"].values) / cap_sum * 100 if cap_sum > 0 else np.nan
    a_sum = float(d["power_mw"].sum())
    p_sum = float(d[pred_col].sum())
    bias = (p_sum - a_sum) / a_sum * 100 if abs(a_sum) > 1e-9 else np.nan

    site_nrmse_vals = []
    for _, sdf in d.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        site_nrmse_vals.append(rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100)

    return {
        "city_nrmse_6_19": round(nrmse, 4),
        "abs_bias_6_19": round(abs(bias), 4),
        "city_bias_6_19": round(bias, 4),
        "site_mean_nrmse_6_19": round(float(np.mean(site_nrmse_vals)), 4) if site_nrmse_vals else np.nan,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)

    input_pkl = PROJECT_ROOT / "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl"
    print(f"[INFO] 读取: {input_pkl}")
    df = pd.read_pickle(input_pkl)
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    print(f"  总行数: {len(df):,}")

    test_df = df[df["split"] == "test"].copy()
    valid_df = df[df["split"] == "valid"].copy()

    future_rows = int((df["split"] == "future").sum())
    bl_col = "power_pred_final"
    nn_test = int(test_df[bl_col].notna().sum())
    nn_valid = int(valid_df[bl_col].notna().sum())

    result = {
        "future_rows": future_rows,
        "power_pred_final_in_test": nn_test,
        "power_pred_final_in_valid": nn_valid,
        "current_is_round68_final": future_rows == 0 and nn_test == len(test_df) and nn_valid == len(valid_df),
    }

    if nn_test > 0:
        metrics = compute_metrics(test_df, bl_col)
        result.update(metrics)

    round68_targets = {
        "city_nrmse_6_19": 4.13,
        "abs_bias_6_19": 0.52,
        "site_mean_nrmse_6_19": 10.58,
    }
    tolerance = {"city_nrmse_6_19": 0.02, "abs_bias_6_19": 0.05, "site_mean_nrmse_6_19": 0.02}

    checks = {}
    for k, target in round68_targets.items():
        if k in result and result[k] is not None:
            delta = abs(result[k] - target)
            checks[k] = {"actual": result[k], "target": target,
                         "delta": round(delta, 4), "tolerance": tolerance[k],
                         "pass": delta <= tolerance[k]}

    result["round68_target_checks"] = checks
    all_pass = all(c["pass"] for c in checks.values())
    result["all_targets_match"] = all_pass

    with open(OUT / "round73_current_best_verify.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    rows = [{"metric": k, "value": v} for k, v in result.items() if k != "round68_target_checks"]
    for k, v in checks.items():
        rows += [{"metric": f"check_{k}", "value": v["pass"]},
                 {"metric": f"{k}_actual", "value": v["actual"]}]
    pd.DataFrame(rows).to_csv(OUT / "round73_current_best_verify.csv", index=False, encoding="utf-8-sig")

    print(f"\n[Result]")
    print(f"  future_rows: {future_rows}")
    print(f"  power_pred_final in test: {nn_test}/{len(test_df)}")
    print(f"  current_is_round68_final: {result['current_is_round68_final']}")
    for k, c in checks.items():
        print(f"  {k}: actual={c['actual']:.4f}  target={c['target']}  "
              f"delta={c['delta']:.4f} (tol={c['tolerance']})  {'✓' if c['pass'] else '✗'}")
    print(f"  all_targets_match: {all_pass}")
    print(f"\n[OK] {OUT / 'round73_current_best_verify.json'}")
    print("[OK] verify 完成!")


if __name__ == "__main__":
    main()
