#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round7/8 归档脚本（扩展版）：
将无效候选和过期中间结果移动到 archive_round7/。
同时扫描 metrics / tables / docs 目录。
"""
from __future__ import annotations

from pathlib import Path
import shutil
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output" / "pv_pipeline"
METRICS = OUT / "metrics"
TABLES = OUT / "tables"
DOCS = OUT / "docs"
ARCHIVE = OUT / "archive_round7"
ARCHIVE.mkdir(parents=True, exist_ok=True)

# 永久保留的文件模式（不被归档）
KEEP_PATTERNS = [
    "distributed_predictions_final",
    "distributed_predictions_midday_site_calibrated",
    "分布式光伏预测_逐小时平均NRMSE",
    "final_version_selection_by_hour",
    "round6_watch_site_diagnosis",
    "round6_flagged_site_diagnosis",
    "round6_site_capacity_mapping_diagnosis",
    "round6_midday_bias_stability",
    "round6_stable_extreme_bias_candidates",
    "round7_",
    "当前最终结果摘要",
    "任务书完成情况",
    "最终交付文件清单",
    "midday_site_calibration_params",
    "midday_site_calibration_valid_ablation",
    "midday_worst_site_hours",
]

# 需要归档的文件模式
STALE_PATTERNS = [
    "midday_residual_specialist",
    "midday_selective_site_correction",
    "distributed_predictions_midday_residual_specialist",
    "distributed_predictions_midday_selective_site_corrected",
    "distributed_predictions_round6_stable_bias",
    "round6_stable_bias_test_hourly_nrmse",
    "round6_stable_bias_correction_params",
    "round6_stable_bias_valid_ablation",
    "midday_nrmse_acceptance",
    "midday_next_step_gain_vs_site_calibrated",
    "当前结果_vs_周二基准",
]


def should_keep(path: Path) -> bool:
    name = path.name
    return any(p in name for p in KEEP_PATTERNS)


def should_archive(path: Path) -> bool:
    name = path.name
    if should_keep(path):
        return False
    return any(p in name for p in STALE_PATTERNS)


def main():
    rows = []
    for base in [METRICS, TABLES, DOCS]:
        if not base.exists():
            continue
        for path in base.iterdir():
            if not path.is_file():
                continue
            if should_archive(path):
                rel_parent = path.parent.relative_to(OUT)
                dest_dir = ARCHIVE / rel_parent
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / path.name
                shutil.move(str(path), str(dest))
                rows.append({
                    "original_path": str(path.relative_to(PROJECT_ROOT)),
                    "archived_path": str(dest.relative_to(PROJECT_ROOT)),
                    "size_mb": round(dest.stat().st_size / 1024 / 1024, 3),
                    "reason": "stale_candidate_or_old_baseline",
                })

    manifest = pd.DataFrame(rows)
    manifest_path = ARCHIVE / "archive_round7_manifest.csv"
    manifest.to_csv(manifest_path, index=False, encoding="utf-8-sig")
    print(f"Archived {len(rows)} stale files.")
    if not manifest.empty:
        print(manifest.to_string(index=False))


if __name__ == "__main__":
    main()
