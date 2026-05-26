#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round14 Step 2: 归档清理历史残留。

归档目录：
  output/pv_pipeline/archive_round14/

原则：只归档不硬删，保护清单之外的才归档。
"""
from __future__ import annotations

import shutil
import hashlib
import csv
import fnmatch
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output" / "pv_pipeline"
ARCHIVE_DIR = OUT / "archive_round14"


# 无论如何都保护的模式
KEEP_PATTERNS = [
    # 核心交付物
    "distributed_predictions_final_eval.pkl",
    "distributed_predictions_final_full.pkl",
    "best_predictions_eval.pkl",
    "best_predictions_full.pkl",
    # round10/11 核心指标
    "round10_overall_nrmse_summary.csv",
    "round10_hour_overall_nrmse.csv",
    "round10_site_hour_nrmse.csv",
    "round11_candidate_leaderboard.csv",
    # 审计
    "audit_metric_overall.csv",
    "audit_metric_recompute.csv",
    "audit_data_integrity.csv",
    "audit_site_mapping.csv",
    "audit_split_integrity.csv",
    # 逐小时NRMSE（主表）
    "分布式光伏预测_逐小时平均NRMSE.csv",
    "分布式光伏预测_周报_整体统计.csv",
    "分布式光伏预测_周报_按周汇总.csv",
    "分布式光伏预测_逐小时NRMSE_对比.csv",
    "分布式光伏预测_逐小时NRMSE_MAPE.csv",
    "分布式光伏预测_城市总出力逐小时统计.csv",
    "分布式光伏预测_城市总出力逐日平均相对误差.csv",
    "分布式光伏预测_城市总出力逐日逐时相对误差.csv",
    "分布式光伏预测_各站点逐日逐时相对误差.csv",
    "分布式光伏预测_各站点逐小时统计.csv",
    "分布式光伏预测_各站点平均相对误差统计.csv",
    "分布式光伏预测_各站点相对误差统计_已标注.csv",
    "分布式光伏预测_前38座_已标注.csv",
    "分布式光伏预测_前38座_真实预测对照.csv",
    "分布式光伏预测_前38座_指标汇总.csv",
    "分布式光伏预测_后40座_已标注.csv",
    "分布式光伏预测_后40座_真实预测对照.csv",
    "分布式光伏预测_后40座_指标汇总.csv",
    "分布式光伏预测_去异常天后_逐小时NRMSE_MAPE.csv",
    "final_version_selection_by_hour.csv",
    "final_guard_reject_reasons.csv",
    "blend_oracle_on_test_diagnostic_only.csv",
    "midday_nrmse_current_vs_fixed.csv",
    "midday_nrmse_acceptance.csv",
    "midday_site_calibration_params.csv",
    "midday_site_calibration_valid_ablation.csv",
    "midday_worst_site_hours_final.csv",
    "midday_worst_site_hours_top30.csv",
    "midday_selective_site_correction_params.csv",
    "midday_selective_site_correction_valid_ablation.csv",
    "midday_next_step_gain_vs_site_calibrated.csv",
    "当前结果_vs_周二基准_整体对比.csv",
    "当前结果_vs_周二基准_逐小时NRMSE对比.csv",
    "before_after_comparison.csv",
    "combined_fix_ablation.csv",
    "hourly_nrmse_compare_v2_v3.csv",
    "hourly_relative_error_robust.csv",
    "hourly_relative_error_robust_detail.csv",
    "hourly_relative_error_compare_v2_v3.csv",
    "hourly_bias_decomposition.csv",
    "hourly_bias_decomposition_city_daily.csv",
    "hourly_bias_decomposition_scene.csv",
    "hourly_bias_decomposition_site_mean.csv",
    "hourly_bias_test_results.csv",
    "dawn_dusk_conservative_ablation.csv",
    "dawn_dusk_error_before_after.csv",
    "dawn_dusk_fix_ablation.csv",
    "city_hourly_period_error_fixed.csv",
    "city_hourly_total_error_before_after.csv",
    "city_hourly_total_error_fixed.csv",
    "city_hourly_total_error_summary_fixed.csv",
    "calibration_ablation_by_site.csv",
    "data_quality_metrics.csv",
    "distributed_governance_summary.csv",
    "distributed_metrics_by_county.csv",
    "distributed_metrics_by_scene.csv",
    # Round5 训练记录（保留最新一轮）
    "训练记录_Round5_选择性修正与安全选择器_20260523.md",
]


# 需要归档的模式
ARCHIVE_PATTERNS = [
    # 旧候选 specialist 产物
    "*specialist*",
    "*round6*",
    "*round9*",
    # 旧版临时指标
    "*MAPE*",
    "*相对误差*",
    "v3_*",
    "v4_*",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def should_keep(rel_path: str) -> bool:
    for pattern in KEEP_PATTERNS:
        if fnmatch.fnmatch(Path(rel_path).name, pattern):
            return True
    return False


def should_archive(rel_path: str) -> bool:
    name = Path(rel_path).name
    for pattern in ARCHIVE_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def main():
    print("=" * 70)
    print("Round14 Step 2: 归档清理历史残留")
    print("=" * 70)

    if ARCHIVE_DIR.exists():
        print(f"[WARN] 归档目录已存在，重新创建…")
        shutil.rmtree(ARCHIVE_DIR)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    manifest = []

    # ── 遍历 output 目录 ─────────────────────────────────────
    scan_dirs = [
        OUT / "tables",
        OUT / "metrics",
        OUT / "models",
        OUT / "figures",
        OUT / "figures_dashboard",
        OUT / "docs",
        PROJECT_ROOT / "docs",
    ]

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue

        for src_path in scan_dir.rglob("*"):
            if not src_path.is_file():
                continue

            rel = src_path.relative_to(PROJECT_ROOT)
            rel_str = str(rel)

            if should_keep(rel_str):
                print(f"  [KEEP] {rel}")
                continue

            if not should_archive(rel_str):
                continue

            # 归档
            dest = ARCHIVE_DIR / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest)

            size = dest.stat().st_size
            digest = sha256(dest)

            # 确定归档原因
            name = src_path.name
            reason = ""
            for pattern in ARCHIVE_PATTERNS:
                if fnmatch.fnmatch(name, pattern):
                    reason = f"match:{pattern}"
                    break

            manifest.append({
                "source_path": str(src_path),
                "archive_path": str(dest),
                "size_bytes": size,
                "sha256": digest,
                "reason": reason,
                "archived_at": datetime.now().isoformat(),
            })
            print(f"  [ARCHIVE] {rel} ({size / 1024:.0f} KB)")

    # ── 归档 manifest ───────────────────────────────────────
    manifest_path = ARCHIVE_DIR / "archive_manifest.csv"
    if manifest:
        df = __import__('pandas').DataFrame(manifest)
        df.to_csv(manifest_path, index=False, encoding="utf-8-sig")
        total = sum(r["size_bytes"] for r in manifest)
        print(f"\n[OK] 归档完成: {len(manifest)} 个文件，{total / 1024 / 1024:.1f} MB")
        print(f"     清单已保存: {manifest_path}")
    else:
        print("\n[OK] 没有需要归档的文件")

    # ── 打印保护清单 ────────────────────────────────────────
    kept_count = 0
    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for src_path in scan_dir.rglob("*"):
            if not src_path.is_file():
                continue
            rel = src_path.relative_to(PROJECT_ROOT)
            if should_keep(str(rel)):
                kept_count += 1
    print(f"\n[INFO] 共保护 {kept_count} 个文件不被归档")

    print("\n[OK] 归档清理完成")


if __name__ == "__main__":
    main()
