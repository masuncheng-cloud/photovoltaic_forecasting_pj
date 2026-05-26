#!/usr/bin/env python3
"""
Step 1: Backup Current Grade A Verified State
=============================================
将当前已验证为 Grade A 的核心产物备份到：
    output/pv_pipeline/verified_backup_round14/

执行：
    python scripts/backup_current_verified_state_round14.py
"""

import csv
import hashlib
import shutil
import time
from datetime import datetime
from pathlib import Path

ROOT = Path("output/pv_pipeline")
BACKUP = ROOT / "verified_backup_round14"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_with_manifest(src: Path, dst: Path) -> dict:
    """Copy file and return manifest row."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return {
        "source_path": str(src),
        "backup_path": str(dst),
        "exists": dst.exists(),
        "size_bytes": dst.stat().st_size if dst.exists() else 0,
        "sha256": sha256(dst) if dst.exists() else "",
        "copied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def main():
    backup_root = BACKUP
    backup_root.mkdir(parents=True, exist_ok=True)

    # Core prediction tables
    tables_dir = ROOT / "tables"
    core_tables = [
        "distributed_predictions_final_eval.pkl",
        "distributed_predictions_final_full.pkl",
        "best_predictions_eval.pkl",
        "best_predictions_full.pkl",
    ]

    # Core metrics
    metrics_dir = ROOT / "metrics"
    core_metrics = [
        "round10_overall_nrmse_summary.csv",
        "round10_hour_overall_nrmse.csv",
        "round10_site_hour_nrmse.csv",
        "分布式光伏预测_逐小时平均NRMSE.csv",
        "round11_candidate_leaderboard.csv",
    ]

    # Dashboard
    dashboard_dir = ROOT / "interactive_dashboard"
    dashboard_files = []
    if dashboard_dir.exists():
        dashboard_files = list(dashboard_dir.glob("*"))

    # Reports
    report_files = [
        ROOT.parent / "docs" / "训练过程与结果严谨性验证报告.md",
        ROOT.parent / "光伏功率预测项目.md",
    ]

    manifest_rows = []
    all_ok = True

    # Tables
    for fname in core_tables:
        src = tables_dir / fname
        dst = backup_root / "tables" / fname
        row = copy_with_manifest(src, dst)
        manifest_rows.append(row)
        status = "OK" if row["exists"] else "FAIL"
        print(f"  [{status}] tables/{fname} ({row['size_bytes']:,} bytes)")
        if not row["exists"]:
            all_ok = False

    # Metrics
    for fname in core_metrics:
        src = metrics_dir / fname
        dst = backup_root / "metrics" / fname
        row = copy_with_manifest(src, dst)
        manifest_rows.append(row)
        status = "OK" if row["exists"] else "FAIL"
        print(f"  [{status}] metrics/{fname} ({row['size_bytes']:,} bytes)")
        if not row["exists"]:
            all_ok = False

    # Dashboard
    dashboard_subdir = backup_root / "interactive_dashboard"
    for src in dashboard_files:
        if src.is_file():
            dst = dashboard_subdir / src.name
            row = copy_with_manifest(src, dst)
            manifest_rows.append(row)
            status = "OK" if row["exists"] else "FAIL"
            print(f"  [{status}] interactive_dashboard/{src.name} ({row['size_bytes']:,} bytes)")

    # Reports
    for src in report_files:
        if src.exists():
            dst = backup_root / src.name
            row = copy_with_manifest(src, dst)
            manifest_rows.append(row)
            status = "OK" if row["exists"] else "FAIL"
            print(f"  [{status}] {src.name} ({row['size_bytes']:,} bytes)")

    # Write manifest
    manifest_path = backup_root / "backup_manifest.csv"
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["source_path", "backup_path", "exists",
                                                 "size_bytes", "sha256", "copied_at"])
        writer.writeheader()
        writer.writerows(manifest_rows)
    print(f"\n  Manifest written: {manifest_path}")

    # Verification
    print("\n=== Verification ===")
    import pandas as pd
    import numpy as np
    verify_df = pd.read_pickle(backup_root / "tables" / "distributed_predictions_final_eval.pkl")
    verify_test = verify_df[
        verify_df["split"].eq("test") &
        verify_df["hour"].between(6, 19) &
        verify_df["power_mw"].notna() &
        verify_df["power_pred"].notna()
    ]
    y = verify_test["power_mw"].astype(float).values
    p = verify_test["power_pred"].astype(float).values
    rmse = float(np.sqrt(np.mean((p - y) ** 2)))
    cap_mean = float(verify_test["capacity_mw"].mean())
    nrmse = rmse / cap_mean * 100
    print(f"  Backup rows: {len(verify_test):,}")
    print(f"  Backup NRMSE: {nrmse:.4f}% (expected ~19.7105%)")
    if abs(nrmse - 19.7105) > 0.1:
        print("  [WARN] NRMSE differs significantly from expected 19.7105%")
        all_ok = False
    else:
        print("  [OK] NRMSE matches expected value")

    if all_ok:
        print(f"\n[OK] Backup complete: {backup_root}")
    else:
        print(f"\n[FAIL] Backup incomplete — stop here, do NOT proceed")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
