#!/usr/bin/env python3
"""
audit_round64_all_sites.py
==================================
对 Round64 safe 候选进行全量站点级审计，验证 bad_sites=0 是否真实成立。

输出：
  output/pv_pipeline/round64/round64_all_site_compare.csv
  output/pv_pipeline/round64/round64_bad_site_audit.csv
"""

from pathlib import Path
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline/round64"


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean((p - a) ** 2)))


def mae(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(np.mean(np.abs(p - a)))


def main():
    print("=" * 60)
    print("Round64 全量站点审计")
    print("=" * 60)

    df = pd.read_pickle(OUT / "round64_candidates.pkl")
    df["time"] = pd.to_datetime(df["time"])

    df_test = df[df["split"] == "test"].copy()
    df_test = df_test[df_test["hour"].between(6, 19)].copy()
    print(f"[INFO] Test 6-19h: {len(df_test)} rows, {df_test['site_id'].nunique()} sites")

    cols = ["power_mw", "capacity_mw", "power_pred_final",
            "power_pred_lgb_residual", "power_pred_round64_safe"]

    rows = []
    for sid, sdf in df_test.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue

        actual = sdf["power_mw"].values
        pred61 = sdf["power_pred_final"].values
        pred63 = sdf["power_pred_lgb_residual"].values
        pred64 = sdf["power_pred_round64_safe"].values

        r61 = rmse(actual, pred61) / cap * 100
        r63 = rmse(actual, pred63) / cap * 100
        r64 = rmse(actual, pred64) / cap * 100

        m64 = mae(actual, pred64)
        rm64 = rmse(actual, pred64)
        p_sum = float(pred64.sum())
        a_sum = float(actual.sum())
        pa_ratio = p_sum / a_sum if a_sum != 0 else 0.0

        n = len(sdf)
        pos = int((sdf["power_mw"] > 0).sum())
        zero_ratio = 1.0 - pos / n if n > 0 else 0.0

        rows.append({
            "site_id": str(sid),
            "capacity_mw": round(cap, 4),
            "test_samples": n,
            "test_positive_samples": pos,
            "test_zero_ratio": round(zero_ratio, 4),
            "round61_nrmse": round(r61, 4),
            "round63_lgb_nrmse": round(r63, 4),
            "round64_safe_nrmse": round(r64, 4),
            "delta_round64_vs_round61": round(r64 - r61, 4),
            "delta_round63_vs_round61": round(r63 - r61, 4),
            "mae_round64": round(m64, 4),
            "rmse_round64": round(rm64, 4),
            "pred_sum": round(p_sum, 2),
            "actual_sum": round(a_sum, 2),
            "pred_actual_ratio": round(pa_ratio, 4),
        })

    all_df = pd.DataFrame(rows)
    all_df = all_df.sort_values("delta_round64_vs_round61", ascending=False).reset_index(drop=True)
    all_df.to_csv(OUT / "round64_all_site_compare.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] All site compare: {OUT / 'round64_all_site_compare.csv'} ({len(all_df)} sites)")

    # Bad site audit
    bad_df = all_df[all_df["delta_round64_vs_round61"] > 1.0].copy()
    bad_df.to_csv(OUT / "round64_bad_site_audit.csv", index=False, encoding="utf-8-sig")

    # Summary stats
    total = len(all_df)
    bad_count = len(bad_df)
    max_delta = float(all_df["delta_round64_vs_round61"].max())
    min_delta = float(all_df["delta_round64_vs_round61"].min())
    mean_delta = float(all_df["delta_round64_vs_round61"].mean())

    print(f"\n{'='*60}")
    print(f"[Summary]")
    print(f"  total_sites:            {total}")
    print(f"  bad_sites_gt_1pp:       {bad_count}")
    print(f"  max_delta_nrmse:         {max_delta:.4f}pp")
    print(f"  min_delta_nrmse:         {min_delta:.4f}pp")
    print(f"  mean_delta_nrmse:       {mean_delta:.4f}pp")
    print(f"{'='*60}")

    if bad_count != 0:
        print(f"\n[FAIL] bad_sites_gt_1pp = {bad_count} != 0")
        print("退化站点明细：")
        for _, r in bad_df.iterrows():
            print(f"  {r['site_id']}: delta={r['delta_round64_vs_round61']:+.4f}pp")
        raise SystemExit(1)

    print(f"\n[PASS] bad_sites_gt_1pp = 0 — Round64 safe 无站点退化")


if __name__ == "__main__":
    main()
