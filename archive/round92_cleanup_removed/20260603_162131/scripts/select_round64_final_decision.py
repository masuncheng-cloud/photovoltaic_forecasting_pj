#!/usr/bin/env python3
"""
select_round64_final_decision.py
==================================
自动判定是否采用 Round64 safe 候选。

判定规则（全部基于 valid 集）：
  sm_nrmse_no_worse_than: Round61 + 0.10pp
  city_nrmse_not_worse_than: Round61 + 0.05pp
  city_nrmse_10_14_not_worse: Round61
  bad_sites_zero: True
  sm_nrmse_10_14_not_worse: True

输出：
  output/pv_pipeline/round64/round64_final_decision.json
"""

from pathlib import Path
import json
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline/round64"


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean((p - a) ** 2)))


def site_mean_nrmse(df, pred_col):
    vals = []
    for sid, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        vals.append(rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100)
    return float(np.mean(vals)) if vals else np.nan


def city_nrmse_hourly_avg(df, pred_col):
    vals = []
    for _, hdf in df.groupby("hour"):
        agg = hdf.groupby("time", as_index=False).agg(
            actual=("power_mw", "sum"), pred=(pred_col, "sum"),
            cap_sum=("capacity_mw", "sum"),
        )
        r = rmse(agg["pred"].values, agg["actual"].values)
        cap_h = float(agg["cap_sum"].mean())
        if cap_h > 0:
            vals.append(r / cap_h * 100)
    return float(np.mean(vals)) if vals else np.nan


def count_bad_sites(df, base_col, pred_col, threshold=1.0):
    count = 0
    df_t = df[df["hour"].between(6, 19)]
    for sid, sdf in df_t.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        b_r = rmse(sdf["power_mw"].values, sdf[base_col].values) / cap * 100
        c_r = rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100
        if (c_r - b_r) > threshold:
            count += 1
    return count


def main():
    print("=" * 60)
    print("Round64 最终决策")
    print("=" * 60)

    # Load candidates
    df = pd.read_pickle(OUT / "round64_candidates.pkl")
    df["time"] = pd.to_datetime(df["time"])

    df_valid = df[df["split"] == "valid"].copy()
    df_valid = df_valid[df_valid["hour"].between(6, 19)].copy()
    df_10_14 = df_valid[df_valid["hour"].between(10, 14)]

    base_col = "power_pred_final"
    cand_col = "power_pred_round64_safe"

    # Metrics
    r61_sm = site_mean_nrmse(df_valid, base_col)
    r64_sm = site_mean_nrmse(df_valid, cand_col)
    r61_cn = city_nrmse_hourly_avg(df_valid, base_col)
    r64_cn = city_nrmse_hourly_avg(df_valid, cand_col)
    r61_cn14 = city_nrmse_hourly_avg(df_10_14, base_col)
    r64_cn14 = city_nrmse_hourly_avg(df_10_14, cand_col)
    r61_sm14 = site_mean_nrmse(df_10_14, base_col)
    r64_sm14 = site_mean_nrmse(df_10_14, cand_col)
    r61_bad = count_bad_sites(df_valid, base_col, base_col)  # always 0
    r64_bad = count_bad_sites(df_valid, base_col, cand_col)

    # Thresholds
    T_SM = 0.10
    T_CN = 0.05
    T_CN14 = 0.00

    print(f"\n[Valid 集指标]")
    print(f"  sm_nrmse_6_19:  R61={r61_sm:.4f}%  R64={r64_sm:.4f}%  delta={r64_sm-r61_sm:+.4f}pp  threshold={T_SM:.2f}pp")
    print(f"  city_nrmse_6_19: R61={r61_cn:.4f}%  R64={r64_cn:.4f}%  delta={r64_cn-r61_cn:+.4f}pp  threshold={T_CN:.2f}pp")
    print(f"  city_nrmse_10_14: R61={r61_cn14:.4f}%  R64={r64_cn14:.4f}%  delta={r64_cn14-r61_cn14:+.4f}pp  threshold={T_CN14:.2f}pp")
    print(f"  sm_nrmse_10_14:  R61={r61_sm14:.4f}%  R64={r64_sm14:.4f}%  delta={r64_sm14-r61_sm14:+.4f}pp  threshold={T_SM:.2f}pp")
    print(f"  bad_sites:       R64={r64_bad}")

    # Decision checks
    checks = {
        "sm_nrmse_not_worse_than_r61_plus_0.10pp": (r64_sm - r61_sm) <= T_SM,
        "city_nrmse_not_worse_than_r61_plus_0.05pp": (r64_cn - r61_cn) <= T_CN,
        "city_nrmse_10_14_not_worse": (r64_cn14 - r61_cn14) <= T_CN14,
        "bad_sites_zero": r64_bad == 0,
        "sm_nrmse_10_14_not_worse": (r64_sm14 - r61_sm14) <= T_SM,
    }

    print(f"\n[决策检查]")
    all_pass = True
    for check, result in checks.items():
        status = "PASS" if result else "FAIL"
        if not result:
            all_pass = False
        print(f"  {status} {check}")

    decision = "adopt_round64_candidate" if all_pass else "keep_round61"

    print(f"\n{'='*60}")
    print(f"决策: {decision}")
    print(f"{'='*60}")

    decision_obj = {
        "decision": decision,
        "timestamp": pd.Timestamp.now().isoformat(),
        "valid_metrics": {
            "Round61": {
                "sm_nrmse_6_19": round(r61_sm, 4),
                "city_nrmse_6_19": round(r61_cn, 4),
                "city_nrmse_10_14": round(r61_cn14, 4),
                "sm_nrmse_10_14": round(r61_sm14, 4),
                "bad_sites": int(r61_bad),
            },
            "Round64_safe": {
                "sm_nrmse_6_19": round(r64_sm, 4),
                "city_nrmse_6_19": round(r64_cn, 4),
                "city_nrmse_10_14": round(r64_cn14, 4),
                "sm_nrmse_10_14": round(r64_sm14, 4),
                "bad_sites": int(r64_bad),
            },
        },
        "checks": {k: bool(v) for k, v in checks.items()},
        "thresholds": {
            "sm_nrmse_no_worse_than": T_SM,
            "city_nrmse_not_worse_than": T_CN,
            "city_nrmse_10_14_not_worse": T_CN14,
        },
        "note": (
            "adopt_round64_candidate: Round64 safe 在 valid 上全部通过安全检查，"
            "但本轮不覆盖正式 pkl，只输出候选和建议。"
            "keep_round61: Round64 safe 不满足安全检查，保留 Round61。"
        ),
    }

    with open(OUT / "round64_final_decision.json", "w", encoding="utf-8") as f:
        json.dump(decision_obj, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] {OUT / 'round64_final_decision.json'}")


if __name__ == "__main__":
    main()
