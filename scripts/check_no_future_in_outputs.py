#!/usr/bin/env python3
"""
check_no_future_in_outputs.py
==================================
检查给定 pkl / csv / json-dir 是否包含 future 数据。

用法：
  python scripts/check_no_future_in_outputs.py \
    --pkl-path output/pv_pipeline/round64/round64_candidates.pkl \
    --name round64_candidate \
    --fail-on-future

  python scripts/check_no_future_in_outputs.py \
    --csv-path output/pv_pipeline/metrics/hourly_nrmse.csv \
    --name hourly_nrmse \
    --fail-on-future

  python scripts/check_no_future_in_outputs.py \
    --json-dir output/pv_pipeline/interactive_dashboard_round64_candidate \
    --name round64_dashboard \
    --fail-on-future
"""

from pathlib import Path
import json
import argparse
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def check_pkl(pkl_path: Path, name: str, fail_on_future: bool):
    df = pd.read_pickle(pkl_path)
    df["time"] = pd.to_datetime(df["time"], errors="coerce")

    total = len(df)
    future_rows = 0
    split_dist = {}
    if "split" in df.columns:
        split_dist = df["split"].value_counts().to_dict()
        future_rows = int((df["split"] == "future").sum())
    else:
        # Try to infer from time
        TRAIN_END = pd.Timestamp("2025-07-01")
        VALID_END = pd.Timestamp("2025-09-01")
        TEST_END = pd.Timestamp("2026-01-01")
        df["_inferred"] = "unknown"
        df.loc[df["time"] < TRAIN_END, "_inferred"] = "train"
        df.loc[(df["time"] >= TRAIN_END) & (df["time"] < VALID_END), "_inferred"] = "valid"
        df.loc[(df["time"] >= VALID_END) & (df["time"] < TEST_END), "_inferred"] = "test"
        df.loc[df["time"] >= TEST_END, "_inferred"] = "future"
        split_dist = df["_inferred"].value_counts().to_dict()
        future_rows = int((df["_inferred"] == "future").sum())

    status = "FAIL" if future_rows > 0 else "PASS"
    print(f"[{status}] {name}: total={total}, future={future_rows}, splits={split_dist}")

    result = {
        "name": name, "type": "pkl",
        "file": str(pkl_path),
        "total_rows": total,
        "future_rows": future_rows,
        "split_distribution": split_dist,
        "status": status,
        "fail_on_future": fail_on_future,
    }

    if fail_on_future and future_rows > 0:
        print(f"[FAIL] {name} contains {future_rows} future rows — exiting")
        sys.exit(1)

    return result


def check_csv(csv_path: Path, name: str, fail_on_future: bool):
    df = pd.read_csv(csv_path)

    total = len(df)
    if "split" not in df.columns:
        print(f"[INFO] {name}: CSV has no 'split' column — skipping future check")
        result = {
            "name": name, "type": "csv",
            "file": str(csv_path),
            "total_rows": total,
            "future_rows": 0,
            "status": "NO_SPLIT_COLUMN",
            "fail_on_future": fail_on_future,
        }
        return result

    split_dist = df["split"].value_counts().to_dict()
    future_rows = int((df["split"] == "future").sum())
    status = "FAIL" if future_rows > 0 else "PASS"
    print(f"[{status}] {name}: total={total}, future={future_rows}, splits={split_dist}")

    result = {
        "name": name, "type": "csv",
        "file": str(csv_path),
        "total_rows": total,
        "future_rows": future_rows,
        "split_distribution": split_dist,
        "status": status,
        "fail_on_future": fail_on_future,
    }

    if fail_on_future and future_rows > 0:
        print(f"[FAIL] {name} contains {future_rows} future rows — exiting")
        sys.exit(1)

    return result


def check_json_dir(json_dir: Path, name: str, fail_on_future: bool):
    meta_path = json_dir / "metadata.json"
    if not meta_path.exists():
        print(f"[WARN] {name}: no metadata.json found")
        return {"name": name, "type": "json_dir", "status": "NO_METADATA"}

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    exclude_future = meta.get("exclude_future", False)

    errors = []
    # Spot-check city_series.json
    city_path = json_dir / "city_series.json"
    if city_path.exists():
        city_df = pd.read_json(city_path)
        if "split" in city_df.columns:
            future_in_city = int((city_df["split"] == "future").sum())
            if future_in_city > 0:
                errors.append(f"city_series has {future_in_city} future rows")

    # Check site_series sample
    site_dir = json_dir / "site_series"
    future_in_sites = 0
    checked = 0
    if site_dir.exists():
        for sf in sorted(site_dir.glob("*.json"))[:5]:  # Sample first 5
            js = pd.read_json(sf)
            if "split" in js.columns:
                future_in_sites += int((js["split"] == "future").sum())
            checked += 1

    status = "PASS" if exclude_future and len(errors) == 0 else "FAIL"
    if exclude_future:
        print(f"[PASS] {name}: metadata.exclude_future={exclude_future}, errors={len(errors)}")
    else:
        print(f"[FAIL] {name}: metadata.exclude_future={exclude_future}, errors={len(errors)}")

    result = {
        "name": name, "type": "json_dir",
        "dir": str(json_dir),
        "metadata_exclude_future": exclude_future,
        "city_future_rows": int(future_in_city) if "future_in_city" in dir() else 0,
        "site_sample_future_rows": future_in_sites,
        "errors": errors,
        "status": status,
        "fail_on_future": fail_on_future,
    }

    if fail_on_future and status == "FAIL":
        print(f"[FAIL] {name} failed future check — exiting")
        sys.exit(1)

    return result


def main():
    parser = argparse.ArgumentParser(description="Check for future data in outputs")
    parser.add_argument("--pkl-path", type=str, default=None)
    parser.add_argument("--csv-path", type=str, default=None)
    parser.add_argument("--json-dir", type=str, default=None)
    parser.add_argument("--name", type=str, required=True)
    parser.add_argument("--fail-on-future", action="store_true")
    args = parser.parse_args()

    results = []
    if args.pkl_path:
        r = check_pkl(Path(args.pkl_path), args.name, args.fail_on_future)
        results.append(r)
    if args.csv_path:
        r = check_csv(Path(args.csv_path), args.name, args.fail_on_future)
        results.append(r)
    if args.json_dir:
        r = check_json_dir(Path(args.json_dir), args.name, args.fail_on_future)
        results.append(r)

    if not results:
        print("[ERROR] No input specified. Use --pkl-path, --csv-path, or --json-dir")
        sys.exit(1)

    # Save results
    out_dir = ROOT / "output/pv_pipeline/round66"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = args.name.replace("/", "_").replace(" ", "_")
    csv_path = out_dir / f"no_future_check_{safe_name}.csv"
    json_path = out_dir / f"no_future_check_{safe_name}.json"

    pd.DataFrame(results).to_csv(csv_path, index=False, encoding="utf-8-sig")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] Results saved:")
    print(f"  CSV: {csv_path}")
    print(f"  JSON: {json_path}")


if __name__ == "__main__":
    main()
