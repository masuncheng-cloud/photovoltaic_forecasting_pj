#!/usr/bin/env python3
"""
ERA5 input file pre-check.
Validates the structure, variables, time coverage, and spatial extent of ERA5 files
before a training run. Does NOT modify or replace any files.

Usage:
    python scripts/check_era5_inputs.py
    python scripts/check_era5_inputs.py --data-root data --output-root output/pv_pipeline
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]

YEARS = [2023, 2024, 2025]
EXPECTED_HOURS = {2023: 8760, 2024: 8784, 2025: 8760}

REQUIRED_INSTANT_VARS = {"t2m"}  # stepType=instant, units=K
REQUIRED_ACCUM_VARS = {"ssrd"}  # stepType=accum, units=J m**-2

RECOMMENDED_EXTENT = dict(
    north=35.75,
    west=118.00,
    south=33.50,
    east=120.50,
)

WARN_SITES = {
    "S032": dict(
        lat=32.488611,
        note="经纬度疑似异常（不在连云港常规范围），需人工核对。",
    ),
}


def check_instant_file(nc_path: Path) -> dict:
    import netCDF4 as nc

    results = {}
    ds = nc.Dataset(str(nc_path), "r")
    try:
        results["variables"] = list(ds.variables.keys())

        for var in REQUIRED_INSTANT_VARS:
            if var in ds.variables:
                v = ds.variables[var]
                results[f"has_{var}"] = True
                results[f"{var}_units"] = getattr(v, "units", "unknown")
                results[f"{var}_shape"] = v.shape
            else:
                results[f"has_{var}"] = False
                results[f"{var}_missing_reason"] = f"variable '{var}' not found"

        for coord in ["latitude", "longitude"]:
            if coord in ds.variables:
                c = ds.variables[coord][:]
                results[f"lat_range"] = (float(c.min()), float(c.max())) if coord == "latitude" else results.get("lat_range")
                results[f"lon_range"] = (float(c.min()), float(c.max())) if coord == "longitude" else results.get("lon_range")

        time_var = "valid_time" if "valid_time" in ds.variables else ("time" if "time" in ds.variables else None)
        if time_var:
            t = ds.variables[time_var][:]
            results["time_var"] = time_var
            results["time_units"] = getattr(ds.variables[time_var], "units", "unknown")
            results["n_times"] = len(t)
        else:
            results["time_var"] = None
    finally:
        ds.close()
    return results


def check_accum_file(nc_path: Path) -> dict:
    import netCDF4 as nc

    results = {}
    ds = nc.Dataset(str(nc_path), "r")
    try:
        results["variables"] = list(ds.variables.keys())

        for var in REQUIRED_ACCUM_VARS:
            if var in ds.variables:
                v = ds.variables[var]
                results[f"has_{var}"] = True
                results[f"{var}_units"] = getattr(v, "units", "unknown")
                results[f"{var}_shape"] = v.shape
            else:
                results[f"has_{var}"] = False

        for coord in ["latitude", "longitude"]:
            if coord in ds.variables:
                c = ds.variables[coord][:]
                results[f"lat_range"] = (float(c.min()), float(c.max())) if coord == "latitude" else results.get("lat_range")
                results[f"lon_range"] = (float(c.min()), float(c.max())) if coord == "longitude" else results.get("lon_range")

        time_var = "valid_time" if "valid_time" in ds.variables else ("time" if "time" in ds.variables else None)
        if time_var:
            t = ds.variables[time_var][:]
            results["time_n_times"] = len(t)
            results["time_var"] = time_var
        else:
            results["time_var"] = None
    finally:
        ds.close()
    return results


def check_site_extent(output_root: Path, rec_extent: dict) -> list[dict]:
    site_master = output_root / "tables" / "site_master.csv"
    if not site_master.exists():
        return [{"status": "WARN", "note": "site_master.csv not found, skipping extent check"}]

    import pandas as pd
    df = pd.read_csv(site_master)
    issues = []
    for _, row in df.iterrows():
        sid = row.get("site_id", row.get("site_id", "?"))
        lat = float(row.get("latitude", row.get("lat", 0)))
        lon = float(row.get("longitude", row.get("lon", 0)))
        name = row.get("site_name", row.get("name", sid))

        in_north = lat <= rec_extent["north"]
        in_south = lat >= rec_extent["south"]
        in_west = lon >= rec_extent["west"]
        in_east = lon <= rec_extent["east"]

        if not (in_north and in_south and in_west and in_east):
            issues.append({
                "site_id": sid,
                "site_name": name,
                "lat": lat,
                "lon": lon,
                "status": "WARN",
                "note": f"站点落在推荐 ERA5 范围外 (北={in_north}, 南={in_south}, 西={in_west}, 东={in_east})",
            })
            if sid in WARN_SITES:
                issues[-1]["note"] += f" 【{WARN_SITES[sid]['note']}】"
    return issues


def main():
    parser = argparse.ArgumentParser(description="ERA5 输入文件预检")
    parser.add_argument(
        "--data-root",
        type=str,
        default="data",
        help="数据根目录 (default: data)",
    )
    parser.add_argument(
        "--output-root",
        type=str,
        default="output/pv_pipeline",
        help="Output root (default: output/pv_pipeline)",
    )
    args = parser.parse_args()

    data_root = PROJECT_ROOT / args.data_root
    output_root = PROJECT_ROOT / args.output_root
    val_dir = output_root / "validation"
    val_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("ERA5 Input Pre-Check")
    print("=" * 60)

    all_pass = True
    csv_rows = []
    md_lines = [
        "# ERA5 输入文件预检报告\n\n",
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n",
        "## 1. 文件结构检查\n\n",
        "| 年份 | 文件 | 状态 | 说明 |\n",
        "|------|------|------|------|\n",
    ]

    # Check each year
    for year in YEARS:
        year_dir = data_root / str(year)
        instant_path = year_dir / "data_stream-oper_stepType-instant.nc"
        accum_path = year_dir / "data_stream-oper_stepType-accum.nc"

        for nc_path, kind in [(instant_path, "instant"), (accum_path, "accum")]:
            file_desc = f"{year} {kind}"
            if not nc_path.exists():
                print(f"[FAIL] {file_desc}: 文件不存在 — {nc_path}")
                all_pass = False
                md_lines.append(f"| {year} | {kind} | FAIL | 文件不存在 |\n")
                csv_rows.append([year, kind, "FAIL", "file not found", "", ""])
                continue

            try:
                if kind == "instant":
                    res = check_instant_file(nc_path)
                else:
                    res = check_accum_file(nc_path)

                # Variable check
                if kind == "instant":
                    var_ok = res.get("has_t2m", False)
                    units = res.get("t2m_units", "unknown")
                    var_note = f"t2m units={units}" if var_ok else "t2m missing"
                else:
                    var_ok = res.get("has_ssrd", False)
                    units = res.get("ssrd_units", "unknown")
                    var_note = f"ssrd units={units}" if var_ok else "ssrd missing"

                # Time check
                n_times = res.get("n_times") or res.get("time_n_times")
                if n_times is not None:
                    expected = EXPECTED_HOURS.get(year, 8760)
                    time_ok = n_times == expected
                    time_note = f"{n_times}h (expected {expected})"
                    if not time_ok:
                        all_pass = False
                else:
                    time_ok = False
                    time_note = "无法读取时间维度"

                # Spatial check
                lat_range = res.get("lat_range")
                lon_range = res.get("lon_range")
                if lat_range and lon_range:
                    extent_note = f"lat={lat_range}, lon={lon_range}"
                else:
                    extent_note = "无法读取空间维度"

                status = "PASS" if (var_ok and time_ok) else ("FAIL" if not var_ok else "WARN")
                if status == "FAIL":
                    all_pass = False

                print(f"[{status:4s}] {file_desc}: {var_note}, {time_note}, {extent_note}")
                md_lines.append(f"| {year} | {kind} | {status} | {var_note}, {time_note}, {extent_note} |\n")
                csv_rows.append([year, kind, status, var_note, time_note, extent_note])

            except Exception as e:
                print(f"[FAIL] {file_desc}: 读取失败 — {e}")
                all_pass = False
                md_lines.append(f"| {year} | {kind} | FAIL | 读取失败: {e} |\n")
                csv_rows.append([year, kind, "FAIL", str(e), "", ""])

    # Spatial extent check
    print()
    md_lines.append("\n## 2. 空间范围检查\n\n")
    md_lines.append(f"| 站点 | 名称 | 纬度 | 经度 | 状态 | 说明 |\n")
    md_lines.append("|------|------|------|------|------|------|\n")

    extent_issues = check_site_extent(output_root, RECOMMENDED_EXTENT)
    for issue in extent_issues:
        status = issue["status"]
        if status == "WARN":
            all_pass = False
        print(f"[{status:4s}] {issue['site_id']} ({issue.get('site_name','')}): lat={issue.get('lat','?')}, lon={issue.get('lon','?')} — {issue['note']}")
        md_lines.append(f"| {issue['site_id']} | {issue.get('site_name','')} | {issue.get('lat','')} | {issue.get('lon','')} | {status} | {issue['note']} |\n")
        csv_rows.append([issue["site_id"], "extent", status, issue.get("site_name",""), issue.get("lat",""), issue.get("lon","")])

    # S032 special warning
    if any(r.get("site_id") == "S032" for r in extent_issues):
        print()
        print("[WARN] S032 经纬度异常 (lat=32.49)：不在连云港常规范围。")
        print("       建议人工核对座标，不要为了 S032 扩大 ERA5 南界。")

    # Write outputs
    csv_path = val_dir / "era5_input_audit.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["year_or_site", "kind", "status", "var_info", "time_info", "extent_info"])
        w.writerows(csv_rows)
    print(f"\n[OK] CSV → {csv_path}")

    md_path = val_dir / "era5_input_audit.md"
    md_lines.append(f"\n## 3. 推荐 ERA5 空间范围\n\n")
    md_lines.append(f"- North: {RECOMMENDED_EXTENT['north']}\n")
    md_lines.append(f"- West:  {RECOMMENDED_EXTENT['west']}\n")
    md_lines.append(f"- South: {RECOMMENDED_EXTENT['south']}\n")
    md_lines.append(f"- East:  {RECOMMENDED_EXTENT['east']}\n")
    md_lines.append(f"\n## 4. 替换 ERA5 前的通过条件\n\n")
    md_lines.append("1. 变量仍为 t2m 和 ssrd\n")
    md_lines.append("2. instant/accum 文件结构不变\n")
    md_lines.append("3. 时间逐小时完整（2023:8760h, 2024:8784h, 2025:8760h）\n")
    md_lines.append("4. 空间范围覆盖连云港站点（不含 S032 异常座标）\n")
    md_path.write_text("".join(md_lines), encoding="utf-8")
    print(f"[OK] MD  → {md_path}")

    print()
    print("=" * 60)
    if all_pass:
        print("[PASS] All ERA5 pre-checks passed")
    else:
        print("[WARN] Some checks failed — see above for details")
        print("       This is expected for old ERA5 files with small spatial extent")
    print("=" * 60)

    sys.exit(0)  # Always exit 0; this is a pre-check, not a gate


if __name__ == "__main__":
    main()
