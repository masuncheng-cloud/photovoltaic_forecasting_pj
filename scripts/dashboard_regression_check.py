#!/usr/bin/env python3
"""
Dashboard regression check.
Validates that the interactive dashboard data is complete, consistent, and uses
the canonical prediction column (power_pred_final).

Usage:
    python scripts/dashboard_regression_check.py
    python scripts/dashboard_regression_check.py --output-root output/pv_pipeline
    python scripts/dashboard_regression_check.py --output-root output/pv_pipeline --sample-sites 10
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


TOLERANCE = 1e-2  # 0.01 MW = 10 kW tolerance for JSON precision (3 decimal places)


def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def as_list(data) -> list:
    """Normalize to list: handle both plain lists and dicts with 'data' key."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        val = data["data"]
        if isinstance(val, list):
            return val
    raise ValueError(f"Unexpected JSON structure: {path.name}")


def main():
    parser = argparse.ArgumentParser(description="Dashboard regression check")
    parser.add_argument(
        "--output-root",
        type=str,
        default="output/pv_pipeline",
        help="Root of the pv_pipeline output (default: output/pv_pipeline)",
    )
    parser.add_argument(
        "--sample-sites",
        type=int,
        default=10,
        help="Number of site JSON files to sample for detailed checks (default: 10)",
    )
    parser.add_argument(
        "--no-pkl-check",
        action="store_true",
        help="Skip cross-validation with distributed_predictions_final_full.pkl",
    )
    args = parser.parse_args()

    out = Path(args.output_root)
    dash = out / "interactive_dashboard"

    all_passed = True

    print("=" * 60)
    print("Dashboard Regression Check")
    print(f"Output root: {out}")
    print("=" * 60)

    # ── Check 1: index.json exists ──────────────────────────────────
    try:
        idx_path = dash / "index.json"
        idx = load_json(idx_path)
        print(f"\n[PASS] index.json exists")
    except Exception as e:
        print(f"\n[FAIL] index.json: {e}")
        all_passed = False

    # ── Check 2: metadata.json exists and has correct fields ────────
    try:
        meta_path = dash / "metadata.json"
        meta = load_json(meta_path)

        checks = {
            "prediction_column == power_pred_final": meta.get("prediction_column") == "power_pred_final",
            "include_future == False": meta.get("include_future") is False,
            "exclude_future == True": meta.get("exclude_future") is True,
            "dashboard_data_scope == non_future_full_history": meta.get("dashboard_data_scope") == "non_future_full_history",
        }
        for desc, ok in checks.items():
            icon = "PASS" if ok else "FAIL"
            if not ok:
                all_passed = False
            print(f"\n[{icon}] metadata.json: {desc} (got: {meta.get('prediction_column')}, {meta.get('include_future')}, {meta.get('exclude_future')}, {meta.get('dashboard_data_scope')})")
    except Exception as e:
        print(f"\n[FAIL] metadata.json: {e}")
        all_passed = False

    # ── Check 3: city_series.json exists and non-empty ─────────────
    city_candidates = [
        dash / "city_series.json",
        dash / "city_total_series.json",
    ]
    city_file = next((p for p in city_candidates if p.exists()), None)
    if city_file is None:
        print(f"\n[FAIL] city series JSON not found (checked: {[str(p) for p in city_candidates]})")
        all_passed = False
    else:
        try:
            city_data = as_list(load_json(city_file))
            if not city_data:
                print(f"\n[FAIL] {city_file.name} is empty")
                all_passed = False
            else:
                first = city_data[0]
                required = ["datetime", "actual_mw", "pred_mw"]
                missing = [c for c in required if c not in first]
                if missing:
                    print(f"\n[FAIL] {city_file.name} missing columns: {missing}")
                    all_passed = False
                else:
                    print(f"\n[PASS] {city_file.name} exists, {len(city_data)} rows")
                    # Check no future
                    future_rows = [r for r in city_data if r.get("split") == "future"]
                    if future_rows:
                        print(f"\n[FAIL] {city_file.name} contains {len(future_rows)} future rows")
                        all_passed = False
                    else:
                        print(f"[PASS] {city_file.name} contains no future rows")
        except Exception as e:
            print(f"\n[FAIL] {city_file.name if city_file else 'city_series'}: {e}")
            all_passed = False

    # ── Check 4: site_series/ exists and non-empty ─────────────────
    site_dir = dash / "site_series"
    if not site_dir.exists():
        print(f"\n[FAIL] site_series/ directory does not exist: {site_dir}")
        all_passed = False
    else:
        site_files = sorted(site_dir.glob("S*.json"))
        if not site_files:
            print(f"\n[FAIL] site_series/ is empty (no S*.json files found)")
            all_passed = False
        else:
            print(f"\n[PASS] site_series/ exists, {len(site_files)} site files")

            # Sample sites for detailed checks
            sample_files = site_files[: args.sample_sites]
            for p in sample_files:
                try:
                    data = as_list(load_json(p))
                    if not data:
                        print(f"\n[FAIL] {p.name} is empty")
                        all_passed = False
                        continue
                    first = data[0]
                    for col in ["time", "actual_mw", "pred_mw"]:
                        if col not in first:
                            print(f"\n[FAIL] {p.name} missing column: {col}")
                            all_passed = False
                            continue
                    # No future rows
                    future_rows = [r for r in data if r.get("split") == "future"]
                    if future_rows:
                        print(f"\n[FAIL] {p.name} contains {len(future_rows)} future rows")
                        all_passed = False
                except Exception as e:
                    print(f"\n[FAIL] {p.name}: {e}")
                    all_passed = False

    # ── Check 5: cross-validate with final pkl (if available) ────────
    if args.no_pkl_check:
        print(f"\n[SKIP] Cross-validation (--no-pkl-check passed)")
    else:
        pkl_path = out / "predictions" / "distributed_predictions_final_full.pkl"
        if not pkl_path.exists():
            print(f"\n[WARN] Final pkl not found ({pkl_path}), skipping cross-validation")
        else:
            try:
                print(f"\n── Cross-validation with final pkl ──")
                df = pd.read_pickle(pkl_path)
                df["time"] = pd.to_datetime(df["time"])

                site_dir = dash / "site_series"
                site_files = sorted(site_dir.glob("S*.json"))

                # Build a lookup dataframe from all site_series JSONs (vectorized)
                all_rows = []
                for p in site_files:
                    data = as_list(load_json(p))
                    for row in data:
                        t = pd.to_datetime(row["time"], errors="coerce")
                        if pd.isnull(t):
                            continue
                        all_rows.append({
                            "site_id": str(row.get("site_id", p.stem)),
                            "time": t,
                            "json_split": str(row.get("split", "")),
                            "json_actual": float(row["actual_mw"]) if row.get("actual_mw") is not None else np.nan,
                            "json_pred": float(row["pred_mw"]) if row.get("pred_mw") is not None else np.nan,
                        })
                if not all_rows:
                    print("  [WARN] No JSON rows found")
                else:
                    json_df = pd.DataFrame(all_rows)

                    # Filter pkl to non-future scope
                    if "split" in df.columns:
                        df_work = df[df["split"] != "future"].copy()
                    else:
                        df_work = df.copy()

                    # Build per-split prediction column mapping (matches build_full_history_frame logic)
                    # Priority per split: first non-null column in the candidates list
                    # test:   power_pred_final > power_pred > power_pred_cal
                    # valid:  power_pred_final > power_pred > power_pred_cal
                    # train:  power_pred_cal > power_pred > power_pred_raw
                    candidates_by_split = {
                        "test":   ["power_pred_final", "power_pred", "power_pred_cal"],
                        "valid":  ["power_pred_final", "power_pred", "power_pred_cal"],
                        "train":  ["power_pred_cal", "power_pred", "power_pred_raw"],
                    }
                    df_work["pred_for_dashboard"] = np.nan
                    for split, cols in candidates_by_split.items():
                        mask = df_work["split"] == split
                        if not mask.any():
                            continue
                        for col in cols:
                            if col in df_work.columns:
                                has_values = df_work.loc[mask, col].notna().any()
                                if has_values:
                                    df_work.loc[mask, "pred_for_dashboard"] = df_work.loc[mask, col]
                                    break

                    pkl_sub = df_work[["site_id", "time", "power_mw", "pred_for_dashboard"]].copy()
                    pkl_sub["site_id"] = pkl_sub["site_id"].astype(str)

                    # Merge on (site_id, time) - vectorized
                    merged = json_df.merge(
                        pkl_sub,
                        on=["site_id", "time"],
                        how="inner",
                        suffixes=("_json", "_pkl"),
                    )

                    if len(merged) == 0:
                        print("  [WARN] No matching rows after merge")
                    else:
                        # Compare actual: both should be exact
                        da_arr = (merged["json_actual"].round(4) - merged["power_mw"].round(4)).abs()
                        # Compare pred: use dashboard-appropriate column
                        dp_arr = (merged["json_pred"] - merged["pred_for_dashboard"].round(4)).abs()
                        max_diff_actual = float(da_arr.max())
                        max_diff_pred = float(dp_arr.max())

                        print(f"  JSON rows: {len(json_df):,}, PKL matching: {len(merged):,}")
                        print(f"  max_diff_actual: {max_diff_actual:.2e}  (tolerance: {TOLERANCE:.0e})")
                        print(f"  max_diff_pred:   {max_diff_pred:.2e}  (tolerance: {TOLERANCE:.0e})")

                        if max_diff_actual <= TOLERANCE and max_diff_pred <= TOLERANCE:
                            print(f"  [PASS] All values match pkl within tolerance")
                        else:
                            bad_actual = int((da_arr > TOLERANCE).sum())
                            bad_pred = int((dp_arr > TOLERANCE).sum())
                            print(f"  [FAIL] {bad_actual} actual mismatches, {bad_pred} pred mismatches")
                            # Show first few errors
                            bad_mask = (da_arr > TOLERANCE) | (dp_arr > TOLERANCE)
                            bad_sample = merged[bad_mask].head(5)
                            for _, r in bad_sample.iterrows():
                                print(f"    {r['site_id']} {r['time']} [{r['json_split']}]: "
                                      f"actual diff={abs(float(r['json_actual']) - float(r['power_mw'])):.2e}, "
                                      f"pred diff={abs(float(r['json_pred']) - float(r['pred_for_dashboard'])):.2e}")
                            all_passed = False
            except Exception as e:
                print(f"\n[FAIL] Cross-validation failed: {e}")
                all_passed = False

    # ── Summary ────────────────────────────────────────────────────
    print()
    print("=" * 60)
    if all_passed:
        print("[PASS] Dashboard regression check PASSED")
    else:
        print("[FAIL] Dashboard regression check FAILED")
    print("=" * 60)

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
