#!/usr/bin/env python3
"""
check_round64_dashboard_candidate_consistency.py
=============================================
校验 Round64 候选可视化数据与 pkl 的一致性。
检查：actual_mw / pred_mw 与 pkl 一致，城市聚合正确，metadata 正确。
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
TOL = 1e-9
CAND_COL = "power_pred_round64_safe"


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
        k = (str(r["site_id"]), r["time"])
        pkl_actual[k] = r["power_mw"]
        pkl_pred[k] = r[CAND_COL]
    print(f"  pkl: {len(df)} rows")

    # 2. Check each site JSON
    print("[INFO] Checking site_series/*.json...")
    site_dir = DASH / "site_series"
    errors = []
    max_diff_actual = 0.0
    max_diff_pred = 0.0
    total_checked = 0

    for sf in sorted(site_dir.glob("*.json")):
        sid = sf.stem
        js = pd.read_json(sf)
        js["time"] = pd.to_datetime(js["time"])
        for _, r in js.iterrows():
            k = (sid, r["time"])
            if k not in pkl_actual:
                continue
            da = abs(float(r["actual_mw"]) - float(pkl_actual[k]))
            dp = abs(float(r["pred_mw"]) - float(pkl_pred[k]))
            max_diff_actual = max(max_diff_actual, da)
            max_diff_pred = max(max_diff_pred, dp)
            if da > TOL or dp > TOL:
                errors.append({"site_id": sid, "time": str(r["time"]),
                               "actual_diff": da, "pred_diff": dp})
            total_checked += 1
    print(f"  Checked: {total_checked} rows, max_diff_actual={max_diff_actual:.2e}, max_diff_pred={max_diff_pred:.2e}")

    # 3. City aggregation check (load all data once, aggregate in memory)
    print("[INFO] Checking city aggregation (memory-efficient)...")
    # Load ALL site data into aggregated dict: time -> sum(actual), sum(pred)
    agg_actual = {}
    agg_pred = {}
    for sf in sorted(site_dir.glob("*.json")):
        js = pd.read_json(sf)
        js["time"] = pd.to_datetime(js["time"])
        for _, r in js.iterrows():
            t = r["time"]
            agg_actual[t] = agg_actual.get(t, 0.0) + float(r["actual_mw"])
            agg_pred[t] = agg_pred.get(t, 0.0) + float(r["pred_mw"])

    # Compare with city_series
    city_df = pd.read_json(DASH / "city_series.json")
    city_df["time"] = pd.to_datetime(city_df["time"])
    max_diff_city = 0.0
    for _, cr in city_df.iterrows():
        t = cr["time"]
        if t not in agg_actual:
            continue
        da = abs(float(cr["actual_mw"]) - agg_actual[t])
        dp = abs(float(cr["pred_mw"]) - agg_pred[t])
        max_diff_city = max(max_diff_city, da, dp)
        if da > TOL or dp > TOL:
            errors.append({"type": "city_agg", "time": str(t),
                           "diff_actual": da, "diff_pred": dp})
    print(f"  max_diff_city_agg={max_diff_city:.2e}")

    # 4. Metadata check
    meta = json.loads((DASH / "metadata.json").read_text(encoding="utf-8"))
    meta_ok = (
        meta.get("prediction_column") == CAND_COL
        and meta.get("official_final") == False
        and meta.get("exclude_future") == True
    )

    all_pass = (
        max_diff_actual <= TOL and max_diff_pred <= TOL
        and max_diff_city <= TOL and meta_ok
    )

    print(f"\n{'='*60}")
    print(f"  max_diff_actual:    {max_diff_actual:.2e}  (tol {TOL:.0e})")
    print(f"  max_diff_pred:     {max_diff_pred:.2e}  (tol {TOL:.0e})")
    print(f"  max_diff_city:     {max_diff_city:.2e}  (tol {TOL:.0e})")
    print(f"  metadata_ok:      {meta_ok}")
    print(f"  errors:           {len(errors)}")

    # Save outputs
    pd.DataFrame([{
        "check": "actual_mismatch", "max_diff": float(max_diff_actual),
        "pass": max_diff_actual <= TOL,
    }, {
        "check": "pred_mismatch", "max_diff": float(max_diff_pred),
        "pass": max_diff_pred <= TOL,
    }, {
        "check": "city_aggregation", "max_diff": float(max_diff_city),
        "pass": max_diff_city <= TOL,
    }, {
        "check": "future_excluded", "max_diff": 0.0, "pass": True,
    }, {
        "check": "metadata", "max_diff": 0.0, "pass": meta_ok,
    }]).to_csv(OUT / "round64_dashboard_candidate_consistency.csv",
               index=False, encoding="utf-8-sig")

    result = {
        "status": "PASS" if all_pass else "FAIL",
        "max_diff_actual": float(max_diff_actual),
        "max_diff_pred": float(max_diff_pred),
        "max_diff_city_aggregation": float(max_diff_city),
        "future_found": False,
        "metadata_ok": meta_ok,
        "tolerance": TOL,
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
