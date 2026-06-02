#!/usr/bin/env python3
"""
evaluate_round69_performance_candidate.py
==================================
在 test 上评估 Round69 候选。
"""

from pathlib import Path
import math
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
ROUND69 = OUT / "round69"


def rmse(a, p):
    a = np.asarray(a, dtype=float); p = np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.mean((p - a) ** 2))))


def bias_pct(a, p):
    a = np.asarray(a, dtype=float); p = np.asarray(p, dtype=float)
    a_sum = float(np.nansum(a)); p_sum = float(np.nansum(p))
    if abs(a_sum) < 1e-12: return 0.0
    return (p_sum - a_sum) / a_sum * 100.0


def compute_metrics(df, pred_col):
    cap_sum = float(df[["site_id", "capacity_mw"]].drop_duplicates("site_id")["capacity_mw"].sum())

    rmses = []
    for _, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0: continue
        r = rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100
        rmses.append(r)
    sm_nrmse = float(np.mean(rmses))

    sub10 = df[df["hour"].between(10, 14)]
    rmses10 = []
    for _, sdf in sub10.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0: continue
        r = rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100
        rmses10.append(r)
    sm_nrmse_10_14 = float(np.mean(rmses10)) if rmses10 else float("nan")

    agg = df.groupby("time", as_index=False).agg(a=("power_mw", "sum"), p=(pred_col, "sum"))
    city_nrmse = rmse(agg["a"].values, agg["p"].values) / cap_sum * 100

    agg10 = sub10.groupby("time", as_index=False).agg(a=("power_mw", "sum"), p=(pred_col, "sum"))
    cap10 = float(sub10[["site_id", "capacity_mw"]].drop_duplicates("site_id")["capacity_mw"].sum())
    city_nrmse_10_14 = rmse(agg10["a"].values, agg10["p"].values) / cap10 * 100

    actual = df["power_mw"].values.astype(float)
    pred = df[pred_col].values.astype(float)
    bias = bias_pct(actual, pred)

    return {
        "sm_nrmse": round(sm_nrmse, 4),
        "sm_nrmse_10_14": round(sm_nrmse_10_14, 4),
        "city_nrmse": round(city_nrmse, 4),
        "city_nrmse_10_14": round(city_nrmse_10_14, 4),
        "bias": round(bias, 4),
        "abs_bias": round(abs(bias), 4),
        "rmse_mw": round(rmse(actual, pred), 4),
        "mae_mw": round(float(np.mean(np.abs(pred - actual))), 4),
    }


def main():
    print("=" * 60)
    print("Round69 Test Evaluation")
    print("=" * 60)

    df = pd.read_pickle(ROUND69 / "round69_candidates.pkl")
    test = df[df["split"] == "test"].copy()

    candidates = [c for c in df.columns if c.startswith("power_pred_round69_")]
    base_col = "power_pred_final"

    base = compute_metrics(test, base_col)
    print(f"\n[Baseline on Test]")
    for k, v in base.items():
        print(f"  {k}: {v}")

    rows = []
    for col in candidates:
        m = compute_metrics(test, col)
        m["candidate"] = col
        m["delta_sm"] = round(m["sm_nrmse"] - base["sm_nrmse"], 4)
        m["delta_city"] = round(m["city_nrmse"] - base["city_nrmse"], 4)
        rows.append(m)
        print(f"\n  {col}:")
        print(f"    sm={m['sm_nrmse']}% ({m['delta_sm']:+.4f}), "
              f"city={m['city_nrmse']}% ({m['delta_city']:+.4f}), "
              f"bias={m['bias']}%")

    # Overall
    pd.DataFrame(rows).to_csv(ROUND69 / "round69_test_overall_compare.csv", index=False, encoding="utf-8-sig")

    # Per-site
    site_rows = []
    for _, sdf in test.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0: continue
        sid = str(sdf["site_id"].iloc[0])
        for col in [base_col] + candidates:
            r = rmse(sdf["power_mw"].values, sdf[col].values) / cap * 100
            site_rows.append({"site_id": sid, "candidate": col, "nrmse_pct": round(r, 4)})
    pd.DataFrame(site_rows).to_csv(ROUND69 / "round69_test_site_compare.csv", index=False, encoding="utf-8-sig")

    # Per-hour
    hour_rows = []
    for hour, hdf in test.groupby("hour"):
        cap_sum = float(hdf[["site_id", "capacity_mw"]].drop_duplicates("site_id")["capacity_mw"].sum())
        for col in [base_col] + candidates:
            agg = hdf.groupby("time", as_index=False).agg(
                a=("power_mw", "sum"), p=(col, "sum")
            )
            r = rmse(agg["a"].values, agg["p"].values) / cap_sum * 100
            b = bias_pct(hdf["power_mw"].values, hdf[col].values)
            hour_rows.append({
                "hour": int(hour), "candidate": col,
                "city_nrmse_pct": round(r, 4), "bias_pct": round(b, 4),
            })
    pd.DataFrame(hour_rows).to_csv(ROUND69 / "round69_test_hourly_compare.csv", index=False, encoding="utf-8-sig")

    # High-error site compare
    site_nrmse = {}
    for sid, sdf in test.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0: continue
        r = rmse(sdf["power_mw"].values, sdf[base_col].values) / cap * 100
        site_nrmse[str(sid)] = r
    he_sites = sorted(site_nrmse.items(), key=lambda x: -x[1])[:10]
    print(f"\n[Top 10 High-Error Sites on Test]")
    for sid, nrmse in he_sites:
        print(f"  {sid}: {nrmse:.4f}%")

    print(f"\n[OK] Test overall: {ROUND69 / 'round69_test_overall_compare.csv'}")
    print(f"[OK] Test per-site: {ROUND69 / 'round69_test_site_compare.csv'}")
    print(f"[OK] Test per-hour: {ROUND69 / 'round69_test_hourly_compare.csv'}")


if __name__ == "__main__":
    main()
