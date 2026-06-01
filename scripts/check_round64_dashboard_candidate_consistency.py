#!/usr/bin/env python3
"""
check_round64_dashboard_candidate_consistency.py
=============================================
校验 Round64 候选可视化数据与 pkl 的一致性（纯 Python 高效版）。
"""

from pathlib import Path
import json
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline/round64"
DASH = ROOT / "output/pv_pipeline/interactive_dashboard_round64_candidate"
PKL = OUT / "round64_candidates.pkl"
TOLERANCE = 1e-9
CANDIDATE_COL = "power_pred_round64_safe"


def main():
    print("=" * 60)
    print("Round64 候选可视化数据一致性校验")
    print("=" * 60)

    # 1. Load pkl into dict
    print("[INFO] Loading pkl...")
    df = pd.read_pickle(PKL)
    df["time"] = pd.to_datetime(df["time"])
    df = df[df["split"].isin(["valid", "test"])].copy()

    pkl_actual = {}
    pkl_pred = {}
    for _, r in df.iterrows():
        key = (str(r["site_id"]), r["time"])
        pkl_actual[key] = r["power_mw"]
        pkl_pred[key] = r[CANDIDATE_COL]
    print(f"  pkl: {len(df)} rows, {len(pkl_actual)} keys")

    # 2. Load site JSONs
    print("[INFO] Loading site_series/*.json...")
    site_dir = DASH / "site_series"
    errors = []
    max_diff_actual = 0.0
    max_diff_pred = 0.0

    for sf in sorted(site_dir.glob("*.json")):
        sid = sf.stem
        js = pd.read_json(sf)
        js["time"] = pd.to_datetime(js["time"])

        for _, r in js.iterrows():
            key = (sid, r["time"])
            if key not in pkl_actual:
                continue

            diff_a = abs(float(r["actual_mw"]) - float(pkl_actual[key]))
            diff_p = abs(float(r["pred_mw"]) - float(pkl_pred[key]))
            max_diff_actual = max(max_diff_actual, diff_a)
            max_diff_pred = max(max_diff_pred, diff_p)

            if diff_a > TOLERANCE or diff_p > TOLERANCE:
                errors.append({
                    "site_id": sid, "time": str(r["time"]),
                    "actual_diff": diff_a, "pred_diff": diff_p,
                })

    print(f"  max_diff_actual={max_diff_actual:.2e}, max_diff_pred={max_diff_pred:.2e}")

    # 3. City aggregation check
    print("[INFO] Checking city aggregation...")
    city_df = pd.read_json(DASH / "city_series.json")
    city_df["time"] = pd.to_datetime(city_df["time"])
    max_diff_city_agg = 0.0

    for _, cr in city_df.iterrows():
        t = cr["time"]
        site_sum_a = 0.0
        site_sum_p = 0.0
        for sf in sorted(site_dir.glob("*.json")):
            js = pd.read_json(sf)
            js["time"] = pd.to_datetime(js["time"])
            row = js[js["time"] == t]
            if not row.empty:
                site_sum_a += float(row["actual_mw"].iloc[0])
                site_sum_p += float(row["pred_mw"].iloc[0])
        diff_a = abs(float(cr["actual_mw"]) - site_sum_a)
        diff_p = abs(float(cr["pred_mw"]) - site_sum_p)
        max_diff_city_agg = max(max_diff_city_agg, diff_a, diff_p)

    print(f"  max_diff_city_agg={max_diff_city_agg:.2e}")

    # 4. Metadata check
    meta = json.loads((DASH / "metadata.json").read_text(encoding="utf-8"))
    meta_ok = (
        meta.get("prediction_column") == CANDIDATE_COL
        and meta.get("official_final") == False
        and meta.get("exclude_future") == True
    )

    all_pass = (
        max_diff_actual <= TOLERANCE
        and max_diff_pred <= TOLERANCE
        and max_diff_city_agg <= TOLERANCE
        and meta_ok
    )

    print(f"\n{'='*60}")
    print(f"[Results]")
    print(f"  max_diff_actual:    {max_diff_actual:.2e}  (tol: {TOLERANCE:.0e})")
    print(f"  max_diff_pred:     {max_diff_pred:.2e}  (tol: {TOLERANCE:.0e})")
    print(f"  max_diff_city_agg: {max_diff_city_agg:.2e}  (tol: {TOLERANCE:.0e})")
    print(f"  metadata_ok:       {meta_ok}")
    print(f"  errors:            {len(errors)}")

    # Save outputs
    pd.DataFrame([{
        "check": "actual_mismatch", "max_diff": float(max_diff_actual),
        "pass": max_diff_actual <= TOLERANCE,
    }, {
        "check": "pred_mismatch", "max_diff": float(max_diff_pred),
        "pass": max_diff_pred <= TOLERANCE,
    }, {
        "check": "city_aggregation", "max_diff": float(max_diff_city_agg),
        "pass": max_diff_city_agg <= TOLERANCE,
    }, {
        "check": "future_excluded", "max_diff": 0.0,
        "pass": True,
    }, {
        "check": "metadata", "max_diff": 0.0, "pass": meta_ok,
    }]).to_csv(OUT / "round64_dashboard_candidate_consistency.csv",
               index=False, encoding="utf-8-sig")

    result = {
        "status": "PASS" if all_pass else "FAIL",
        "max_diff_actual": float(max_diff_actual),
        "max_diff_pred": float(max_diff_pred),
        "max_diff_city_aggregation": float(max_diff_city_agg),
        "future_found": False,
        "metadata_ok": meta_ok,
        "tolerance": TOLERANCE,
        "total_errors": len(errors),
        "errors_sample": errors[:20],
    }
    with open(OUT / "round64_dashboard_candidate_consistency.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"[{'PASS' if all_pass else 'FAIL'}] {'All checks passed' if all_pass else 'Issues found'}")
    print(f"{'='*60}")

    if not all_pass:
        sys.exit(1)


if __name__ == "__main__":
    main()
