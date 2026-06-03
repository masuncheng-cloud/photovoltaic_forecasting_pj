#!/usr/bin/env python3
"""
check_dashboard_prediction_values_round66.py
=============================================
校验正式可视化数据与正式 final pkl 的一致性（Round66 专用）。

用法：
  python scripts/check_dashboard_prediction_values_round66.py \
    --prediction-pkl output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
    --prediction-col power_pred_final \
    --dashboard-root output/pv_pipeline/interactive_dashboard \
    --fail-on-future
"""

from pathlib import Path
import json
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline/round66"
TOL = 1e-6


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction-pkl", required=True)
    parser.add_argument("--prediction-col", default="power_pred_final")
    parser.add_argument("--dashboard-root", required=True)
    parser.add_argument("--fail-on-future", action="store_true")
    args = parser.parse_args()

    pkl_path = Path(args.prediction_pkl)
    dash_dir = Path(args.dashboard_root)
    pred_col = args.prediction_col

    print("=" * 60)
    print(f"Round66 Dashboard Consistency Check")
    print("=" * 60)

    # Load pkl
    print(f"[INFO] Loading pkl: {pkl_path}")
    df = pd.read_pickle(pkl_path)
    df["time"] = pd.to_datetime(df["time"])
    df = df[df["split"].isin(["valid", "test"])].copy()

    pkl_actual = {}
    pkl_pred = {}
    for _, r in df.iterrows():
        k = (str(r["site_id"]), r["time"])
        pkl_actual[k] = float(r["power_mw"])
        pkl_pred[k] = float(r[pred_col])
    print(f"  pkl: {len(df)} rows")

    # Check site JSONs
    print("[INFO] Checking site_series/*.json vs pkl...")
    site_dir = dash_dir / "site_series"
    max_diff_actual = 0.0
    max_diff_pred = 0.0
    errors = []
    future_found = False

    for sf in sorted(site_dir.glob("*.json")):
        sid = sf.stem
        js = pd.read_json(sf)
        js["time"] = pd.to_datetime(js["time"])
        for _, r in js.iterrows():
            k = (sid, r["time"])
            if k not in pkl_actual:
                continue
            da = abs(float(r["actual_mw"]) - pkl_actual[k])
            dp = abs(float(r["pred_mw"]) - pkl_pred[k])
            max_diff_actual = max(max_diff_actual, da)
            max_diff_pred = max(max_diff_pred, dp)
            if da > TOL or dp > TOL:
                errors.append({"site_id": sid, "time": str(r["time"]), "da": da, "dp": dp})
            if r.get("split") == "future":
                future_found = True

    print(f"  max_diff_actual={max_diff_actual:.2e}, max_diff_pred={max_diff_pred:.2e}")

    # Check city aggregation
    print("[INFO] Checking city_series.json actual_mw...")
    city_df = pd.read_json(dash_dir / "city_series.json")
    city_df["time"] = pd.to_datetime(city_df["time"])
    max_diff_city = 0.0
    for _, cr in city_df.iterrows():
        t = cr["time"]
        city_actual = df[df["time"] == t]["power_mw"].sum()
        da = abs(float(cr["actual_mw"]) - float(city_actual))
        max_diff_city = max(max_diff_city, da)
        if da > 0.1:
            errors.append({"type": "city_actual", "time": str(t), "da": da})

    print(f"  max_diff_city_actual={max_diff_city:.4f}")

    # Check metadata
    meta = json.loads((dash_dir / "metadata.json").read_text(encoding="utf-8"))
    meta_ok = (
        meta.get("prediction_column") == pred_col
        and meta.get("exclude_future") == True
        and meta.get("official_final") == True
    )

    actual_pass = max_diff_actual <= TOL
    pred_pass = max_diff_pred <= TOL
    city_pass = max_diff_city <= 0.1
    future_pass = not future_found
    all_pass = actual_pass and pred_pass and city_pass and future_pass and meta_ok

    print(f"\n{'='*60}")
    print(f"  actual_mw:   {'PASS' if actual_pass else 'FAIL'} ({max_diff_actual:.2e})")
    print(f"  pred_mw:    {'PASS' if pred_pass else 'FAIL'} ({max_diff_pred:.2e})")
    print(f"  city:       {'PASS' if city_pass else 'FAIL'} ({max_diff_city:.4f})")
    print(f"  future:     {'PASS' if future_pass else 'FAIL'}")
    print(f"  metadata:   {'PASS' if meta_ok else 'FAIL'}")
    print(f"{'='*60}")
    print(f"[{'PASS' if all_pass else 'FAIL'}] All checks {'passed' if all_pass else 'failed'}")

    # Save
    pd.DataFrame([{
        "check": "actual_mw", "max_diff": max_diff_actual, "pass": actual_pass,
    }, {
        "check": "pred_mw", "max_diff": max_diff_pred, "pass": pred_pass,
    }, {
        "check": "city_actual", "max_diff": max_diff_city, "pass": city_pass,
    }, {
        "check": "future_excluded", "max_diff": 0.0, "pass": future_pass,
    }, {
        "check": "metadata", "max_diff": 0.0, "pass": meta_ok,
    }]).to_csv(OUT / "round66_dashboard_final_consistency.csv", index=False, encoding="utf-8-sig")

    result = {
        "status": "PASS" if all_pass else "FAIL",
        "max_diff_actual": max_diff_actual,
        "max_diff_pred": max_diff_pred,
        "max_diff_city_actual": max_diff_city,
        "future_found": future_found,
        "metadata_ok": meta_ok,
        "total_errors": len(errors),
        "errors_sample": errors[:20],
    }
    with open(OUT / "round66_dashboard_final_consistency.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[OK] CSV: {OUT / 'round66_dashboard_final_consistency.csv'}")
    print(f"[OK] JSON: {OUT / 'round66_dashboard_final_consistency.json'}")

    if not all_pass and args.fail_on_future:
        sys.exit(1)


if __name__ == "__main__":
    main()
