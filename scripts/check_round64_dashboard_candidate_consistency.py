#!/usr/bin/env python3
"""
check_round64_dashboard_candidate_consistency.py
=============================================
校验 Round64 候选可视化数据与 round64_candidates.pkl 的一致性（优化版）。

检查内容：
1. 页面 JSON 中 actual_mw 与 pkl power_mw 一致。
2. 页面 JSON 中 pred_mw 与 pkl power_pred_round64_safe 一致。
3. 全市聚合 JSON 与逐站点 JSON 聚合后结果一致。
4. 不包含 future 数据。
5. metadata.json 中 prediction_column 正确。

输出：
  output/pv_pipeline/round64/round64_dashboard_candidate_consistency.csv
  output/pv_pipeline/round64/round64_dashboard_candidate_consistency.json
"""

from pathlib import Path
import json
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

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

    # 1. Load pkl into memory
    print("[INFO] Loading pkl...")
    df = pd.read_pickle(PKL)
    df["time"] = pd.to_datetime(df["time"])
    df_eval = df[df["split"].isin(["valid", "test"])].copy()
    pkl_actual = df_eval.set_index(["site_id", "time"])["power_mw"]
    pkl_pred = df_eval.set_index(["site_id", "time"])[CANDIDATE_COL]
    print(f"  pkl: {len(df_eval)} rows")

    # 2. Load all site JSONs into memory (once)
    print("[INFO] Loading site_series/*.json into memory...")
    site_dir = DASH / "site_series"
    site_jsons = {}
    for sf in sorted(site_dir.glob("*.json")):
        sid = sf.stem
        js = pd.read_json(sf)
        js["time"] = pd.to_datetime(js["time"])
        site_jsons[sid] = js.set_index("time")
    print(f"  Loaded {len(site_jsons)} site files")

    # 3. Check site actual/pred vs pkl
    print("[INFO] Checking site_series vs pkl...")
    errors = []
    max_diff_actual = 0.0
    max_diff_pred = 0.0

    for sid, js_indexed in site_jsons.items():
        for t, row in js_indexed.iterrows():
            key = (str(sid), t)
            if key not in pkl_actual.index:
                continue
            diff_a = abs(float(row["actual_mw"]) - float(pkl_actual[key]))
            diff_p = abs(float(row["pred_mw"]) - float(pkl_pred[key]))
            max_diff_actual = max(max_diff_actual, diff_a)
            max_diff_pred = max(max_diff_pred, diff_p)
            if diff_a > TOLERANCE or diff_p > TOLERANCE:
                errors.append({
                    "site_id": sid, "time": str(t),
                    "type": "site_value_mismatch",
                    "actual_diff": diff_a, "pred_diff": diff_p,
                })
            if (js_indexed["split"] == "future").any():
                errors.append({"site_id": sid, "time": "any", "type": "future_found"})

    print(f"  max_diff_actual={max_diff_actual:.2e}, max_diff_pred={max_diff_pred:.2e}")

    # 4. Check city_series vs aggregated site_series
    print("[INFO] Checking city_series vs aggregated site_series...")
    city_path = DASH / "city_series.json"
    city_df = pd.read_json(city_path)
    city_df["time"] = pd.to_datetime(city_df["time"])
    city_df = city_df.set_index("time")

    max_diff_city_agg = 0.0
    for t, crow in city_df.iterrows():
        site_sum_a = 0.0
        site_sum_p = 0.0
        for sid, js_indexed in site_jsons.items():
            if t in js_indexed.index:
                site_sum_a += float(js_indexed.loc[t, "actual_mw"])
                site_sum_p += float(js_indexed.loc[t, "pred_mw"])
        diff_a = abs(float(crow["actual_mw"]) - site_sum_a)
        diff_p = abs(float(crow["pred_mw"]) - site_sum_p)
        max_diff_city_agg = max(max_diff_city_agg, diff_a, diff_p)
        if diff_a > TOLERANCE or diff_p > TOLERANCE:
            errors.append({
                "type": "city_aggregation_mismatch", "time": str(t),
                "city_actual": float(crow["actual_mw"]),
                "site_sum_actual": site_sum_a,
                "diff_actual": diff_a,
                "city_pred": float(crow["pred_mw"]),
                "site_sum_pred": site_sum_p,
                "diff_pred": diff_p,
            })

    print(f"  max_diff_city_agg={max_diff_city_agg:.2e}")

    # 5. Check metadata
    meta = json.loads((DASH / "metadata.json").read_text(encoding="utf-8"))
    meta_ok = (
        meta.get("prediction_column") == CANDIDATE_COL
        and meta.get("official_final") == False
        and meta.get("exclude_future") == True
    )

    # Summary
    site_errors = [e for e in errors if e.get("type") == "site_value_mismatch"]
    city_errors = [e for e in errors if e.get("type") == "city_aggregation_mismatch"]
    future_errors = [e for e in errors if e.get("type") == "future_found"]

    print(f"\n{'='*60}")
    print(f"[Results]")
    print(f"  max_diff_actual:       {max_diff_actual:.2e}  (tolerance: {TOLERANCE:.0e})")
    print(f"  max_diff_pred:        {max_diff_pred:.2e}  (tolerance: {TOLERANCE:.0e})")
    print(f"  max_diff_city_agg:    {max_diff_city_agg:.2e}  (tolerance: {TOLERANCE:.0e})")
    print(f"  site_value_errors:    {len(site_errors)}")
    print(f"  city_agg_errors:      {len(city_errors)}")
    print(f"  future_errors:        {len(future_errors)}")
    print(f"  metadata_ok:          {meta_ok}")

    # Save CSV
    rows_df = pd.DataFrame([{
        "check": "site_value_actual",
        "max_diff": max_diff_actual,
        "pass": max_diff_actual <= TOLERANCE,
    }, {
        "check": "site_value_pred",
        "max_diff": max_diff_pred,
        "pass": max_diff_pred <= TOLERANCE,
    }, {
        "check": "city_aggregation",
        "max_diff": max_diff_city_agg,
        "pass": max_diff_city_agg <= TOLERANCE,
    }, {
        "check": "future_excluded",
        "max_diff": 0.0,
        "pass": len(future_errors) == 0,
    }, {
        "check": "metadata",
        "max_diff": 0.0,
        "pass": meta_ok,
    }])
    rows_df.to_csv(OUT / "round64_dashboard_candidate_consistency.csv",
                   index=False, encoding="utf-8-sig")
    print(f"\n[OK] CSV: {OUT / 'round64_dashboard_candidate_consistency.csv'}")

    # Save JSON
    result = {
        "status": "PASS" if all([
            max_diff_actual <= TOLERANCE, max_diff_pred <= TOLERANCE,
            max_diff_city_agg <= TOLERANCE, len(future_errors) == 0, meta_ok
        ]) else "FAIL",
        "max_diff_actual": max_diff_actual,
        "max_diff_pred": max_diff_pred,
        "max_diff_city_aggregation": max_diff_city_agg,
        "site_value_errors": len(site_errors),
        "city_aggregation_errors": len(city_errors),
        "future_found": len(future_errors) > 0,
        "metadata_ok": meta_ok,
        "tolerance": TOLERANCE,
        "total_errors": len(errors),
        "errors_sample": errors[:20],
    }
    with open(OUT / "round64_dashboard_candidate_consistency.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[OK] JSON: {OUT / 'round64_dashboard_candidate_consistency.json'}")

    print(f"\n{'='*60}")
    if result["status"] == "PASS":
        print(f"[PASS] All consistency checks passed")
    else:
        print(f"[FAIL] Issues found:")
        for e in errors[:5]:
            print(f"  {e}")
    print(f"{'='*60}")

    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
