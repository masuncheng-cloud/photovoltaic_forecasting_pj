#!/usr/bin/env python3
"""
Step 1: Archive Remaining Stale Artifacts (Round15)
===================================================
将剩余历史残留文件归档到：
    output/pv_pipeline/archive_round15/

只归档，不硬删。
KEEP_FILES 中包含的文件绝对不会被归档。

执行：
    python scripts/archive_remaining_stale_artifacts_round15.py
"""

import csv
import hashlib
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path("output/pv_pipeline")
ARCHIVE = ROOT / "archive_round15"

# Files that must NEVER be archived
KEEP_FILES = {
    # Core prediction outputs
    "distributed_predictions_final_eval.pkl",
    "distributed_predictions_final_full.pkl",
    "best_predictions_eval.pkl",
    "best_predictions_full.pkl",
    # Core metrics
    "round10_overall_nrmse_summary.csv",
    "round10_hour_overall_nrmse.csv",
    "round10_site_hour_nrmse.csv",
    "round10_final_is_best_check.csv",
    "round10_final_vs_best_nrmse.csv",
    "round11_candidate_leaderboard.csv",
    "round14_retrain_decision.json",
    "round14_retrain_vs_verified_best.csv",
    "round14_final_delivery_check.csv",
    "分布式光伏预测_逐小时平均NRMSE.csv",
    # Audit outputs
    "audit_summary.json",
    "audit_metric_recompute.csv",
    "audit_metric_overall.csv",
    "audit_data_integrity.csv",
    "audit_split_integrity.csv",
    "audit_site_mapping.csv",
    "audit_report_page_consistency.json",
    "audit_final_best_consistency.json",
    "audit_physical_range.json",
    # Round14 train tables (new training output)
    "power_long_raw.pkl",
    "power_clean.pkl",
    "site_meteo.pkl",
    "site_master.csv",
    "site_irradiance.pkl",
    "inverse_train_table.pkl",
    "inverse_predictions.pkl",
    "blend_train_table.pkl",
    "blend_validation_predictions.pkl",
    "distributed_train_table_v159.pkl",
    "distributed_predictions_v159.pkl",
    "distributed_predictions_v159_fix.pkl",
    "distributed_predictions_midday_site_calibrated_eval.pkl",
    "distributed_predictions_midday_site_calibrated_full.pkl",
    # Other mid-process artifacts we keep
    "distributed_predictions_fixed_eval.pkl",
    "distributed_predictions_fixed_full.pkl",
    "distributed_predictions_fixed.pkl",
    "distributed_metrics_fixed.csv",
    "distributed_metrics_by_scene_fixed.csv",
    "distributed_metrics_by_hour_fixed.csv",
    "final_guard_reject_reasons.csv",
    "final_version_selection_by_hour.csv",
    "midday_nrmse_current_vs_fixed.csv",
    "分布式_governance_summary.csv",
    "midday_selective_site_correction_params.csv",
    "midday_selective_site_correction_valid_ablation.csv",
    "midday_next_step_gain_vs_site_calibrated.csv",
}

# Patterns to archive in metrics/
STALE_METRIC_PATTERNS = [
    "round6_*",
    "round9_*",
    "v3_*",
    "v4_*",
    "*MAPE*",
    "*相对误差*",
    "hourly_relative_error*",
    "hourly_nrmse_compare_v2_v3.csv",
    "final_comparison_V0_V1_V2.csv",
    "final_comparison_V0_V1_V3.csv",
    "v159_fix_逐小时NRMSE_MAPE.csv",
]

# Patterns to archive in tables/
STALE_TABLE_PATTERNS = [
    "distributed_predictions_midday_residual_specialist_*.pkl",
    "distributed_predictions_round6_stable_bias_*.pkl",
    "distributed_predictions_midday_selective_site_corrected_*.pkl",
    "distributed_predictions_metadata_overridden_full.pkl",
    "power_mapping_round9_corrected.csv",
]

# Patterns to archive in docs/
STALE_DOC_PATTERNS = [
    "Round6_*",
    "Round7_*",
    "Round8_*",
    "Round9_*",
    "Round10_*",
    "Round11_*",
]

# Files in project root to archive
STALE_ROOT_FILES = [
    "auto_push_test.txt",
    "test_auto_push.txt",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def should_keep(path: Path) -> bool:
    if path.name in KEEP_FILES:
        return True
    if "verified_backup" in str(path) or "archive_round14" in str(path) or "archive_round15" in str(path):
        return True
    return False


def glob_archive(patterns: list, base: Path) -> list[Path]:
    found = []
    for p in patterns:
        if "/" in p:
            subdir, glob_p = p.split("/", 1)
            dir_path = base / subdir
        else:
            dir_path = base
            glob_p = p
        if dir_path.exists():
            for fp in dir_path.glob(glob_p):
                if fp.is_file() and not should_keep(fp):
                    found.append(fp)
    return found


def copy_with_manifest(src: Path, dst: Path) -> dict:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return {
        "source_path": str(src),
        "archive_path": str(dst),
        "file_type": dst.suffix or "file",
        "reason": "stale_artifact",
        "size_bytes": dst.stat().st_size,
        "sha256": sha256(dst),
        "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def main():
    archive_root = ARCHIVE
    archive_root.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    archived_count = 0

    # --- metrics ---
    print("Scanning metrics/ ...")
    metric_files = glob_archive(STALE_METRIC_PATTERNS, ROOT / "metrics")
    print(f"  Found {len(metric_files)} stale metric files")
    metrics_archive = archive_root / "metrics"
    for src in metric_files:
        dst = metrics_archive / src.name
        row = copy_with_manifest(src, dst)
        manifest_rows.append(row)
        archived_count += 1

    # --- tables ---
    print("Scanning tables/ ...")
    table_files = glob_archive(STALE_TABLE_PATTERNS, ROOT / "tables")
    print(f"  Found {len(table_files)} stale table files")
    tables_archive = archive_root / "tables"
    for src in table_files:
        dst = tables_archive / src.name
        row = copy_with_manifest(src, dst)
        manifest_rows.append(row)
        archived_count += 1

    # --- docs ---
    print("Scanning docs/ ...")
    docs_root = ROOT.parent / "docs"
    doc_files = []
    for p in STALE_DOC_PATTERNS:
        for fp in docs_root.glob(p):
            if fp.is_file() and fp.name not in {
                "训练过程与结果严谨性验证报告.md",
                "光伏功率预测项目.md",
            }:
                doc_files.append(fp)
    print(f"  Found {len(doc_files)} stale doc files")
    docs_archive = archive_root / "docs"
    for src in doc_files:
        dst = docs_archive / src.name
        row = copy_with_manifest(src, dst)
        manifest_rows.append(row)
        archived_count += 1

    # --- root stale txt files ---
    print("Scanning project root ...")
    project_root = ROOT.parent
    root_files = []
    for fn in STALE_ROOT_FILES:
        fp = project_root / fn
        if fp.exists() and not should_keep(fp):
            root_files.append(fp)
    print(f"  Found {len(root_files)} stale root files")
    root_archive = archive_root / "root"
    for src in root_files:
        dst = root_archive / src.name
        row = copy_with_manifest(src, dst)
        manifest_rows.append(row)
        archived_count += 1

    # --- Write manifest ---
    manifest_path = archive_root / "archive_manifest.csv"
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["source_path", "archive_path",
                                                 "file_type", "reason", "size_bytes",
                                                 "sha256", "archived_at"])
        writer.writeheader()
        writer.writerows(manifest_rows)

    total_size = sum(r["size_bytes"] for r in manifest_rows)
    print(f"\n=== Archive Summary (Round15) ===")
    print(f"  Archived: {archived_count} files ({total_size / 1024 / 1024:.1f} MB)")
    print(f"  Manifest: {manifest_path}")
    print(f"\n[OK] Archive complete: {archive_root}")
    return archived_count


if __name__ == "__main__":
    main()
