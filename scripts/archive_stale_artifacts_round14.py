#!/usr/bin/env python3
"""
Step 2: Archive Stale Artifacts
================================
将历史残留文件归档到：
    output/pv_pipeline/archive_round14/

只归档，不硬删。保留保护清单中的文件。
KEEP_PATTERNS 中包含的文件绝对不会被归档。

执行：
    python scripts/archive_stale_artifacts_round14.py
"""

import csv
import hashlib
import shutil
import time
from datetime import datetime
from pathlib import Path

ROOT = Path("output/pv_pipeline")
ARCHIVE = ROOT / "archive_round14"

# Files that must NEVER be archived
KEEP_BASENAMES = {
    # Core prediction outputs
    "distributed_predictions_final_eval.pkl",
    "distributed_predictions_final_full.pkl",
    "best_predictions_eval.pkl",
    "best_predictions_full.pkl",
    # Core metrics
    "round10_overall_nrmse_summary.csv",
    "round10_hour_overall_nrmse.csv",
    "round10_site_hour_nrmse.csv",
    "round10_final_vs_best_nrmse.csv",
    "round10_final_is_best_check.csv",
    "round11_candidate_leaderboard.csv",
    "final_guard_reject_reasons.csv",
    "final_version_selection_by_hour.csv",
    "分布式光伏预测_逐小时平均NRMSE.csv",
    # Audit outputs
    "audit_summary.json",
    "audit_metric_recompute.csv",
    "audit_metric_overall.csv",
    "audit_data_integrity.csv",
    "audit_site_mapping.csv",
    "audit_split_integrity.csv",
    "audit_final_best_consistency.json",
    "audit_physical_range.json",
    "audit_report_page_consistency.json",
    # Other live metrics we want to keep
    "midday_site_calibration_params.csv",
    "midday_nrmse_current_vs_fixed.csv",
    "分布式_governance_summary.csv",
}

# Patterns that suggest the file is stale candidate/intermediate
ARCHIVE_PATTERNS = [
    # Old candidate models
    ("tables", "*specialist*"),
    ("tables", "*round6*"),
    ("tables", "*round7*"),
    ("tables", "*round8*"),
    ("tables", "*round9*"),
    ("tables", "*baseline*"),
    ("tables", "*v0*"),
    ("tables", "*v1*"),
    ("tables", "*v2*"),
    ("tables", "*v3*"),
    ("tables", "*v4*"),
    ("tables", "*inverse*"),
    ("models", "*specialist*"),
    ("models", "*round6*"),
    ("models", "*round9*"),
    ("models", "*midday*"),
    ("models", "*guard*"),
    ("models", "*blend*"),
    # Old metrics with old naming
    ("metrics", "*MAPE*"),
    ("metrics", "*WAPE*"),
    ("metrics", "*相对误差*"),
    ("metrics", "v3_*"),
    ("metrics", "v4_*"),
    ("metrics", "round6_*"),
    ("metrics", "round7_*"),
    ("metrics", "round8_*"),
    ("metrics", "round9_*"),
    ("metrics", "*_baseline*"),
    ("metrics", "*_before_after*"),
    ("metrics", "top_day_zero*"),
    ("metrics", "*scene*"),
    ("metrics", "*county*"),
    ("metrics", "*v159*"),
    # Old charts
    ("metrics", "分布式光伏预测_前38座*"),
    ("metrics", "分布式光伏预测_后40座*"),
    ("metrics", "分布式光伏预测_后2座*"),
    ("metrics", "分布式光伏预测_周报*"),
    # Old eval/diagnostic tables
    ("metrics", "*黎明*"),
    ("metrics", "*黄昏*"),
    ("metrics", "*晨昏*"),
    ("metrics", "*午间*"),
    ("metrics", "*日平均*"),
    ("metrics", "*双周*"),
]

# Subdirs in docs to archive
ARCHIVE_DOCS_PATTERNS = [
    "docs/Round5_*",
    "docs/Round6_*",
    "docs/Round7_*",
    "docs/Round8_*",
    "docs/Round9_*",
    "docs/Round10_*",
    "docs/Round11_*",
    "docs/Round12_*",
    "docs/*对比*",
    "docs/*诊断*",
    "docs/next_step*",
    "docs/time_convention*",
    "docs/model_capability*",
    "docs/fixed_pipeline*",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def should_keep(path: Path) -> bool:
    """Return True if this file must NOT be archived."""
    if path.name in KEEP_BASENAMES:
        return True
    # Also protect verified_backup and current archive dir
    if "verified_backup" in str(path) or "archive_round14" in str(path):
        return True
    return False


def glob_archive(patterns: list[tuple[str, str]]) -> list[Path]:
    """Find all files matching (subdir, glob) patterns."""
    found = []
    for subdir, pattern in patterns:
        dir_path = ROOT / subdir
        if dir_path.exists():
            for p in dir_path.glob(pattern):
                if p.is_file() and not should_keep(p):
                    found.append(p)
    return found


def main():
    archive_root = ARCHIVE
    archive_root.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    archived_count = 0
    skipped_count = 0

    # --- Archive tables ---
    table_files = glob_archive([(d, p) for d, p in ARCHIVE_PATTERNS if d == "tables"])
    print(f"Found {len(table_files)} stale table files to archive")
    tables_archive = archive_root / "tables"
    for src in table_files:
        dst = tables_archive / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        manifest_rows.append({
            "source_path": str(src),
            "archive_path": str(dst),
            "size_bytes": dst.stat().st_size,
            "sha256": sha256(dst),
            "reason": "stale_intermediate_table",
            "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        archived_count += 1

    # --- Archive metrics ---
    metric_files = glob_archive([(d, p) for d, p in ARCHIVE_PATTERNS if d == "metrics"])
    print(f"Found {len(metric_files)} stale metric files to archive")
    metrics_archive = archive_root / "metrics"
    for src in metric_files:
        dst = metrics_archive / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        manifest_rows.append({
            "source_path": str(src),
            "archive_path": str(dst),
            "size_bytes": dst.stat().st_size,
            "sha256": sha256(dst),
            "reason": "stale_metric",
            "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        archived_count += 1

    # --- Archive models ---
    model_files = glob_archive([(d, p) for d, p in ARCHIVE_PATTERNS if d == "models"])
    print(f"Found {len(model_files)} stale model files to archive")
    models_archive = archive_root / "models"
    for src in model_files:
        dst = models_archive / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        manifest_rows.append({
            "source_path": str(src),
            "archive_path": str(dst),
            "size_bytes": dst.stat().st_size,
            "sha256": sha256(dst),
            "reason": "stale_model",
            "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        archived_count += 1

    # --- Archive docs ---
    docs_root = ROOT.parent / "docs"
    doc_files = []
    for pattern in ARCHIVE_DOCS_PATTERNS:
        # pattern like "docs/Round6_*"
        p = Path(pattern.replace("docs/", ""))
        if (docs_root / p.name).exists():
            for fp in docs_root.glob(p.name):
                if fp.is_file():
                    doc_files.append(fp)
    print(f"Found {len(doc_files)} stale doc files to archive")
    docs_archive = archive_root / "docs"
    for src in doc_files:
        dst = docs_archive / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        manifest_rows.append({
            "source_path": str(src),
            "archive_path": str(dst),
            "size_bytes": dst.stat().st_size,
            "sha256": sha256(dst),
            "reason": "stale_doc",
            "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        archived_count += 1

    # --- Write manifest ---
    manifest_path = archive_root / "archive_manifest.csv"
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["source_path", "archive_path",
                                                 "size_bytes", "sha256", "reason", "archived_at"])
        writer.writeheader()
        writer.writerows(manifest_rows)

    # --- Summary ---
    total_size = sum(r["size_bytes"] for r in manifest_rows)
    print(f"\n=== Archive Summary ===")
    print(f"  Archived: {archived_count} files ({total_size / 1024 / 1024:.1f} MB)")
    print(f"  Manifest: {manifest_path}")
    print(f"\n[OK] Archive complete: {archive_root}")
    return archived_count


if __name__ == "__main__":
    main()
