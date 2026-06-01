#!/usr/bin/env python3
"""
check_round64_dashboard_candidate_consistency.py
=============================================
校验 Round64 候选可视化数据与 round64_candidates.pkl 的一致性。

检查内容：
1. 页面 JSON 中 actual_mw 与 round64_candidates.pkl 的 power_mw 一致。
2. 页面 JSON 中 pred_mw 与 power_pred_round64_safe 一致。
3. 全市聚合 JSON 与逐站点 JSON 聚合后结果一致。
4. 不包含 future 数据。


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

    # Load pkl
    print(f"[INFO] Loading: {PKL}")
    df = pd.read_pickle(PKL)
    df["time"] = pd.to_datetime(df["time"])
    df = df[df["split"].isin(["valid", "test"])].copy()
    print(f"[INFO] Data: {len(df)} rows")

    # Load city_series
    city_path = DASH / "city_series.json"
    city_df = pd.read_json(city_path)
    city_df["time"] = pd.to_datetime(city_df["time"])
    print(f"[INFO] City series: {len(city_df)} rows")

    # Load site_series
    site_dir = DASH / "site_series"
    site_files = sorted(site_dir.glob("*.json"))
    print(f"[INFO] Site series: {len(site_files)} files")

    rows = []
    errors = []
    max_diff_actual = 0.0
    max_diff_pred = 0.0
    max_diff_city_agg = 0.0
    future_found = False

    # 1. Check each site JSON vs pkl
    print(f"\n[1] Checking site_series/*.json vs pkl...")
    for sf in site_files:
        site_id = sf.stem
        js = pd.read_json(sf)
        js["time"] = pd.to_datetime(js["time"])

        # Check for future
        if (js["split"] == "future").any():
            future_found = True

        # Merge with pkl
        merged = js.merge(
            df[df["site_id"].astype(str) == site_id][["time", "power_mw", CANDIDATE_COL]],
            on="time", how="left", suffixes=("", "_pkl")
        )

        for _, r in merged.iterrows():
            if pd.isna(r.get("power_mw_pkl")):
                continue
            diff_a = float(abs(r.get("actual_mw", 0) - r.get("power_mw_pkl", 0)))
            diff_p = float(abs(r.get("pred_mw", 0) - r.get(CANDIDATE_COL, 0)))
            max_diff_actual = max(max_diff_actual, diff_a)
            max_diff_pred = max(max_diff_pred, diff_p)
            if diff_a > TOLERANCE or diff_p > TOLERANCE:
                errors.append({
                    "site_id": site_id,
                    "time": str(r["time"]),
                    "type": "site_value_mismatch",
                    "actual_diff": diff_a,
                    "pred_diff": diff_p,
                })

        rows.append({
            "site_id": site_id,
            "json_rows": len(js),
            "merged_rows": len(merged),
            "actual_max_diff": round(max_diff_actual, 15),
            "pred_max_diff": round(max_diff_pred, 15),
            "status": "OK" if not errors or not any(e["site_id"] == site_id for e in errors) else "FAIL",
        })

    # 2. Check city_series vs aggregated site_series
    print(f"\n[2] Checking city_series vs aggregated site_series...")
    for _, cr in city_df.iterrows():
        t = cr["time"]
        site_sum_actual = 0.0
        site_sum_pred = 0.0
        for sf in site_files:
            js = pd.read_json(sf)
            js["time"] = pd.to_datetime(js["time"])
            row = js[js["time"] == t]
            if not row.empty:
                site_sum_actual += float(row["actual_mw"].iloc[0])
                site_sum_pred += float(row["pred_mw"].iloc[0])

        diff_a = abs(float(cr["actual_mw"]) - site_sum_actual)
        diff_p = abs(float(cr["pred_mw"]) - site_sum_pred)
        max_diff_city_agg = max(max_diff_city_agg, diff_a, diff_p)
        if diff_a > TOLERANCE or diff_p > TOLERANCE:
            errors.append({
                "type": "city_aggregation_mismatch",
                "time": str(t),
                "city_actual": float(cr["actual_mw"]),
                "site_sum_actual": site_sum_actual,
                "diff_actual": diff_a,
                "city_pred": float(cr["pred_mw"]),
                "site_sum_pred": site_sum_pred,
                "diff_pred": diff_p,
            })

    # 3. Check metadata
    meta_path = DASH / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta_ok = (
        meta.get("prediction_column") == CANDIDATE_COL
        and meta.get("official_final") == False
        and meta.get("exclude_future") == True
    )

    # Summary
    print(f"\n{'='*60}")
    print(f"[Results]")
    print(f"  max_diff_actual:       {max_diff_actual:.2e}  (tolerance: {TOLERANCE:.0e})")
    print(f"  max_diff_pred:        {max_diff_pred:.2e}  (tolerance: {TOLERANCE:.0e})")
    print(f"  max_diff_city_agg:    {max_diff_city_agg:.2e}  (tolerance: {TOLERANCE:.0e})")
    print(f"  future_in_data:       {future_found}")
    print(f"  metadata_ok:         {meta_ok}")
    print(f"  total_errors:         {len(errors)}")

    # Save CSV
    rows_df = pd.DataFrame(rows)
    rows_df.to_csv(OUT / "round64_dashboard_candidate_consistency.csv",
                   index=False, encoding="utf-8-sig")
    print(f"\n[OK] CSV: {OUT / 'round64_dashboard_candidate_consistency.csv'}")

    # Save JSON
    result = {
        "status": "PASS" if len(errors) == 0 and not future_found and meta_ok else "FAIL",
        "max_diff_actual": max_diff_actual,
        "max_diff_pred": max_diff_pred,
        "max_diff_city_aggregation": max_diff_city_agg,
        "future_found": future_found,
        "metadata_ok": meta_ok,
        "tolerance": TOLERANCE,
        "total_errors": len(errors),
        "errors": errors[:20],  # limit errors in JSON
    }
    with open(OUT / "round64_dashboard_candidate_consistency.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[OK] JSON: {OUT / 'round64_dashboard_candidate_consistency.json'}")

    print(f"\n{'='*60}")
    if result["status"] == "PASS":
        print(f"[PASS] All consistency checks passed")
    else:
        print(f"[FAIL] Consistency issues found:")
        for e in errors:
            print(f"  {e}")
    print(f"{'='*60}")

    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
