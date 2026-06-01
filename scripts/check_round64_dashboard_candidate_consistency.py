#!/usr/bin/env python3
"""
check_round64_dashboard_candidate_consistency.py
=============================================
校验 Round64 候选可视化数据与 round64_candidates.pkl 的一致性（高效版）。

检查内容：
1. 页面 JSON 中 actual_mw 与 pkl power_mw 一致。
2. 页面 JSON 中 pred_mw 与 pkl power_pred_round64_safe 一致。
3. 全市聚合 JSON 与逐站点 JSON 聚合后结果一致。
4. 不包含 future 数据。
5. metadata.json 中 prediction_column 正确。
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

    # 1. Load pkl
    print("[INFO] Loading pkl...")
    df = pd.read_pickle(PKL)
    df["time"] = pd.to_datetime(df["time"])
    df_eval = df[df["split"].isin(["valid", "test"])].copy()
    pkl_actual = df_eval.set_index(["site_id", "time"])["power_mw"]
    pkl_pred = df_eval.set_index(["site_id", "time"])[CANDIDATE_COL]
    print(f"  pkl: {len(df_eval)} rows")

    # 2. Load all site JSONs
    print("[INFO] Loading site_series/*.json...")
    site_dir = DASH / "site_series"
    site_files = sorted(site_dir.glob("*.json"))
    site_jsons = {}
    for sf in site_files:
        sid = sf.stem
        js = pd.read_json(sf)
        js["time"] = pd.to_datetime(js["time"])
        site_jsons[sid] = js
    print(f"  Loaded {len(site_jsons)} site files")

    # 3. Check per-site
    print("[INFO] Checking site_series vs pkl (vectorized)...")
    errors = []
    max_diff_actual = 0.0
    max_diff_pred = 0.0

    for sid, js in site_jsons.items():
        if len(js) == 0:
            continue
        js = js.copy()
        js = js.set_index("time")
        js = js[~js.index.duplicated(keep="first")]

        merged = js.join(
            pkl_actual.rename("pkl_actual"),
            how="inner"
        ).join(
            pkl_pred.rename("pkl_pred"),
            how="inner"
        )

        if len(merged) == 0:
            continue

        if merged["pkl_actual"].isna().all():
            continue

        diff_a = (merged["actual_mw"] - merged["pkl_actual"]).abs()
        diff_p = (merged["pred_mw"] - merged["pkl_pred"]).abs()

        max_diff_actual = max(max_diff_actual, diff_a.max())
        max_diff_pred = max(max_diff_pred, diff_p.max())

        bad_a = diff_a[diff_a > TOLERANCE]
        bad_p = diff_p[diff_p > TOLERANCE]

        for t, v in bad_a.items():
            errors.append({"site_id": sid, "time": str(t), "type": "actual_mismatch", "diff": float(v)})
        for t, v in bad_p.items():
            errors.append({"site_id": sid, "time": str(t), "type": "pred_mismatch", "diff": float(v)})

        if (js["split"] == "future").any():
            errors.append({"site_id": sid, "time": "any", "type": "future_found"})

    print(f"  max_diff_actual={max_diff_actual:.2e}, max_diff_pred={max_diff_pred:.2e}")

    # 4. Check city aggregation
    print("[INFO] Checking city_series aggregation...")
    city_df = pd.read_json(DASH / "city_series.json")
    city_df["time"] = pd.to_datetime(city_df["time"])
    city_df = city_df.set_index("time")

    # Build aggregated city from site_jsons
    # Sample at first timestamp to get column names
    sample = next(iter(site_jsons.values()))
    agg_times = city_df.index
    agg_actual = []
    agg_pred = []

    for t in agg_times:
        a_sum = 0.0
        p_sum = 0.0
        for sid, js in site_jsons.items():
            js_t = js[js["time"] == t]
            if not js_t.empty:
                a_sum += float(js_t["actual_mw"].iloc[0])
                p_sum += float(js_t["pred_mw"].iloc[0])
        agg_actual.append(a_sum)
        agg_pred.append(p_sum)

    max_diff_city_agg = 0.0
    for i, t in enumerate(agg_times):
        diff_a = abs(float(city_df.loc[t, "actual_mw"]) - agg_actual[i])
        diff_p = abs(float(city_df.loc[t, "pred_mw"]) - agg_pred[i])
        max_diff_city_agg = max(max_diff_city_agg, diff_a, diff_p)
        if diff_a > TOLERANCE or diff_p > TOLERANCE:
            errors.append({
                "type": "city_aggregation_mismatch",
                "time": str(t),
                "diff_actual": float(diff_a),
                "diff_pred": float(diff_p),
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
    print(f"\n{'='*60}")
    print(f"[Results]")
    print(f"  max_diff_actual:       {max_diff_actual:.2e}")
    print(f"  max_diff_pred:        {max_diff_pred:.2e}")
    print(f"  max_diff_city_agg:    {max_diff_city_agg:.2e}")
    print(f"  future_errors:        {sum(1 for e in errors if e.get('type')=='future_found')}")
    print(f"  metadata_ok:          {meta_ok}")

    all_pass = (
        max_diff_actual <= TOLERANCE
        and max_diff_pred <= TOLERANCE
        and max_diff_city_agg <= TOLERANCE
        and all(e.get("type") != "future_found" for e in errors)
        and meta_ok
    )

    # Save outputs
    pd.DataFrame([{
        "check": "actual_mismatch", "max_diff": max_diff_actual,
        "pass": max_diff_actual <= TOLERANCE,
    }, {
        "check": "pred_mismatch", "max_diff": max_diff_pred,
        "pass": max_diff_pred <= TOLERANCE,
    }, {
        "check": "city_aggregation", "max_diff": max_diff_city_agg,
        "pass": max_diff_city_agg <= TOLERANCE,
    }, {
        "check": "future_excluded", "max_diff": 0.0,
        "pass": all(e.get("type") != "future_found" for e in errors),
    }, {
        "check": "metadata", "max_diff": 0.0, "pass": meta_ok,
    }]).to_csv(OUT / "round64_dashboard_candidate_consistency.csv",
               index=False, encoding="utf-8-sig")

    result = {
        "status": "PASS" if all_pass else "FAIL",
        "max_diff_actual": float(max_diff_actual),
        "max_diff_pred": float(max_diff_pred),
        "max_diff_city_aggregation": float(max_diff_city_agg),
        "future_found": any(e.get("type") == "future_found" for e in errors),
        "metadata_ok": meta_ok,
        "tolerance": TOLERANCE,
        "total_errors": len(errors),
        "errors_sample": errors[:20],
    }
    with open(OUT / "round64_dashboard_candidate_consistency.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"[{'PASS' if all_pass else 'FAIL'}] {'All consistency checks passed' if all_pass else 'Issues found'}")
    print(f"{'='*60}")

    if not all_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
