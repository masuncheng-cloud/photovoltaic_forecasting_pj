"""
audit_stale_round_artifacts.py
=============================
审计并生成过期文件清单（不清除，只列出）。

扫描 scripts/、output/pv_pipeline/、docs/，识别：
- 旧轮次的临时诊断脚本
- 旧备份、临时结果文件
- 已被新脚本替代的重复脚本
- 缓存文件（可重复生成）

输出：
  output/pv_pipeline/docs/stale_artifacts_audit.csv
  output/pv_pipeline/docs/stale_artifacts_audit.md

文件分类：
  keep_core        — 核心训练、导出、评估、可视化文件，必须保留
  keep_latest     — 最新报告和最终技术文档，保留
  archive_artifact — 旧轮次诊断/报告/临时结果，建议归档
  delete_cache    — 可重复生成的缓存文件，可删除
  manual_review   — 不确定是否仍被引用，需人工确认

用法：
  python scripts/audit_stale_round_artifacts.py
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pv_pipeline"
DOCS_DIR = OUT / "docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

PYTHON = sys.executable

# ── 白名单：必须保留 ────────────────────────────────────────────────────────────
KEEP_CORE = {
    # 核心训练和评估
    "scripts/train_distributed_model_v159.py",
    "scripts/train_fixed.py",
    "scripts/apply_round36_calibration.py",
    "scripts/compute_round36_metrics.py",
    "scripts/build_round36_predictions.py",
    "scripts/build_site_validity_round36.py",
    "scripts/pretrain_audit_round36.py",
    "scripts/regenerate_project_report_round36.py",
    "scripts/posttrain_validation_round36.py",
    # 核心可视化导出
    "scripts/export_interactive_dashboard_data.py",
    "scripts/update_dashboard_after_training.py",
    "scripts/check_dashboard_prediction_values_round36.py",
    "scripts/check_dashboard_prediction_values_round35.py",
    # 统一收口链路（Round47 新增）
    "scripts/post_training_finalize_outputs.py",
    "scripts/check_post_training_auto_finalize.py",
    "scripts/compute_hourly_nrmse_consistent.py",
    "scripts/round46_recompute_hourly_nrmse_consistent.py",
    # Dashboard 验证
    "scripts/check_dashboard_auto_update_stamp.py",
    "scripts/round44_dashboard_regression_check.py",
    # Daytime/site 校准
    "scripts/round41_42_unified_daytime_and_site_calibration.py",
    "scripts/round41_42_guard.py",
    "scripts/round40_compare_final_prediction_metrics.py",
    # 最终预测列选择
    "scripts/select_final_prediction_by_guard.py",
    "scripts/select_final_prediction_v3.py",
    # 站点元数据
    "scripts/annotate_sites.py",
    "scripts/generate_site_parameters.py",
    "scripts/apply_site_metadata_overrides.py",
    # 入口脚本
    "scripts/run_round36_full_retrain.py",
    "scripts/run_round44_training_logic_fix.py",
    # 核心诊断工具
    "scripts/diagnose_hourly_bias.py",
    "scripts/baseline_diagnostic.py",
    "scripts/evaluate_dawn_dusk.py",
    # 训练流程检查
    "scripts/check_pipeline_consistency.py",
    # 图表生成
    "scripts/plot_map_visualization.py",
    # 仪表盘截图
    "take_dashboard_screenshots.py",
}

# ── 最新报告：保留 ─────────────────────────────────────────────────────────────
KEEP_LATEST_REPORTS = {
    "output/pv_pipeline/docs/Round46_执行总结.md",
    "output/pv_pipeline/docs/Round45_执行总结.md",
    "output/pv_pipeline/docs/Round44_执行总结.md",
    "光伏功率预测项目.md",
    "光伏功率预测项目.md",
}

# ── 可安全删除的缓存 ────────────────────────────────────────────────────────────
CACHE_PATTERNS = [
    "__pycache__",
    ".pyc",
    ".pyo",
]

# ── 归档分类规则 ────────────────────────────────────────────────────────────────
ARCHIVE_SCRIPT_PATTERNS = [
    # Round 1-44 临时诊断/报告脚本
    ("round1", "round2", "round3", "round4", "round5",
     "round6", "round7", "round8", "round9", "round10",
     "round11", "round12", "round13", "round14", "round15",
     "round16", "round17", "round18", "round19", "round20",
     "round21", "round22", "round23", "round24", "round25",
     "round26", "round27", "round28", "round29", "round30",
     "round31", "round32", "round33", "round34", "round35",
     "round36", "round37", "round38", "round39",
     "round40", "round41", "round42", "round43", "round44", "round45"),
    # 旧归档脚本（已被新的替代）
    "archive_stale_outputs_round7.py",
    "archive_stale_artifacts_round14.py",
    "archive_remaining_stale_artifacts_round15.py",
    # 实验性脚本（早期版本）
    "compute_hourly_relative_error_robust.py",
    "fix_hourly_bias.py",
    "fix_dawn_dusk_conservative.py",
    "fix_dawn_dusk_relative_error.py",
    "apply_dd_on_v1.py",
    "apply_dawn_dusk_floor.py",
    "combine_p1_and_dawn_dusk.py",
    "apply_midday_selective_site_correction.py",
    "apply_midday_stable_bias_correction_round6.py",
    "apply_midday_residual_specialist.py",
    "train_midday_specialist_model_round9.py",
    "blend_midday_specialist_round9.py",
    "check_midday_next_step_gain.py",
    "check_midday_nrmse_improvement.py",
    "analyze_midday_nrmse_contribution_round9.py",
    "diagnose_midday_bias_stability_round6.py",
    "diagnose_midday_worst_site_hours.py",
    "export_watch_site_midday_curves_round9.py",
    "compute_midday_nrmse.py",
    "compute_city_hourly_error.py",
    # 早期版本
    "apply_bias_calibration_round34.py",
    "build_site_validity_round33.py",
    "build_site_validity_round34.py",
    "regenerate_round33_metrics.py",
    "posttrain_validation_round33.py",
    "posttrain_validation_round34.py",
    "posttrain_validation_round35.py",
    "pretrain_data_audit_round33.py",
    "compute_round34_metrics.py",
    # 旧守门/对比
    "check_round36_vs_round34_metrics.py",
    "check_round14_final_delivery.py",
    "check_round15_final_delivery.py",
    "compare_with_week2_reference.py",
    "compare_retrain_with_verified_best_round14.py",
    "generate_taskbook_compliance_round7.py",
    "update_taskbook_compliance_round8.py",
    "end_to_end_deliverables_round7.py",
    "check_gblend_time_alignment.py",
    # 旧预测构建
    "rebuild_fixed_predictions.py",
    "evaluate_fixed_predictions.py",
    "clean_prediction_table_round33.py",
    "apply_power_alias_overrides_round9.py",
    "diagnose_power_alias_mapping_round9.py",
    # 早期 MAE/MAPE 实验
    "compute_multi_metric.py",
    "compute_nrmse_reports_round10.py",
    "compute_hourly_site_outliers.py",
    # 旧典型站点分析
    "diagnose_high_sample_bad_sites_round32.py",
    "diagnose_training_effect_factors_round31.py",
    # 旧校准
    "apply_midday_site_nrmse_calibration.py",
    "apply_round41_42_unified_daytime_and_site_calibration.py",
    # 其他已废弃
    "before_after_comparison.py",
    "regenerate_chinese_metrics.py",
    "generate_model_capability_report.py",
    "final_comprehensive_report.py",
    "generate_calibration_report.py",
    "regenerate_final_metrics_round7.py",
    "diagnose_site_capacity_mapping_round6.py",
    "check_round6_midday_gain.py",
    "generate_round36_training_log.py",
    "update_project_md_metrics.py",
    "generate_round36_training_log.py",
    # 旧存档脚本
    "archive_rejected_candidates_round11.py",
    "archive_current_best_round33.py",
    "backup_current_verified_state_round14.py",
}

# ── 需人工确认的文件 ───────────────────────────────────────────────────────────
MANUAL_REVIEW_SCRIPTS = {
    # 这些脚本可能在 pipeline 中被引用，需人工确认
    "scripts/generate_final_delivery_manifest_round8.py",
    "scripts/check_round8_final_package.py",
    "scripts/check_final_is_best_round10.py",
    "scripts/save_current_best_round10.py",
    "scripts/promote_candidate_if_better_round10.py",
    "scripts/summarize_candidate_decisions_round11.py",
    "scripts/clean_final_summary_round8.py",
    "scripts/apply_round36_calibration.py",  # 核心但有 round 编号
    "scripts/apply_round41_42_unified_daytime_and_site_calibration.py",  # 核心但有 round 编号
    "scripts/round45_guard_and_commit.py",
    "scripts/round45_apply_site_hour_shrinkage_calibration.py",
    "scripts/round45_site_hour_nrmse_diagnosis.py",
}


def classify(path: Path, rel: str) -> str:
    """Return classification for a file given its relative path."""
    # Core whitelist
    if rel in KEEP_CORE:
        return "keep_core"
    # Latest reports
    if str(rel) in KEEP_LATEST_REPORTS:
        return "keep_latest"
    if rel.endswith(".md") and any(x in rel for x in ["Round46", "Round45", "Round44"]):
        return "keep_latest"
    # Cache files
    for pat in CACHE_PATTERNS:
        if pat in rel:
            return "delete_cache"
    # 任务书不删
    if "任务书" in rel or "taskbook" in rel.lower():
        return "keep_core"
    # 项目文档
    if rel in ("光伏功率预测项目.md", "README.md", "CHANGELOG.md"):
        return "keep_core"
    # 训练主入口
    if "run_round36_full_retrain.py" in rel or "run_round44_training_logic_fix.py" in rel:
        return "keep_core"
    # 可视化页面
    if "interactive_forecast_dashboard.html" in rel:
        return "keep_core"
    # Archive scripts (Round47 new)
    if rel in ("scripts/audit_stale_round_artifacts.py",
               "scripts/archive_stale_round_artifacts.py"):
        return "keep_core"
    # Check scripts
    if "check_dashboard" in rel or "check_round" in rel or "guard" in rel:
        if rel not in KEEP_CORE and "manual_review" not in str(path):
            # 判断是否被 KEEP_CORE 覆盖
            pass
    # Archive patterns
    for pat in ARCHIVE_SCRIPT_PATTERNS:
        if pat in rel:
            return "archive_artifact"
    # Manual review
    if rel in MANUAL_REVIEW_SCRIPTS:
        return "manual_review"
    # Round 34 及之前的早期脚本（保守策略）
    if rel.startswith("scripts/round") and rel.endswith(".py"):
        # Extract round number
        import re
        m = re.search(r"round(\d+)", rel)
        if m:
            rn = int(m.group(1))
            if rn <= 39:
                return "archive_artifact"
    return "manual_review"


def scan_directory(base: Path, relative_to: Path) -> list:
    """Recursively scan base directory, return list of (rel_path, size, mtime)."""
    results = []
    if not base.exists():
        return results
    for p in sorted(base.rglob("*")):
        if p.is_file():
            try:
                stat = p.stat()
                rel = str(p.relative_to(relative_to))
                results.append((rel, str(p), stat.st_size, stat.st_mtime))
            except ValueError:
                pass
    return results


def main():
    print("=" * 60)
    print("audit_stale_round_artifacts")
    print("=" * 60)
    print(f"项目根目录: {ROOT}")
    print()

    all_files = []

    # Scan directories
    scan_configs = [
        (ROOT / "scripts", ROOT, "scripts/"),
        (OUT / "metrics", OUT, "metrics/"),
        (OUT / "docs", OUT, "docs/"),
        (OUT / "interactive_dashboard", OUT, "interactive_dashboard/"),
        (ROOT / "stages" / "05_visualization", ROOT, "stages/05_visualization/"),
        (ROOT, ROOT, ""),
    ]

    for base, rel_base, prefix in scan_configs:
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            try:
                stat = p.stat()
                full_rel = str(p.relative_to(rel_base))
                if full_rel.startswith("__pycache__") or ".pyc" in full_rel:
                    continue
                all_files.append({
                    "path": full_rel,
                    "full_path": str(p),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "mtime_str": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
            except ValueError:
                pass

    print(f"扫描到 {len(all_files)} 个文件")
    print()

    # Classify each file
    for f in all_files:
        f["category"] = classify(ROOT / f["path"], f["path"])

    # Count by category
    counts = {}
    for f in all_files:
        counts[f["category"]] = counts.get(f["category"], 0) + 1
    print("分类统计：")
    for cat in sorted(counts):
        print(f"  {cat:20s}: {counts[cat]:5d} 个文件")
    print()

    # Write CSV
    csv_path = DOCS_DIR / "stale_artifacts_audit.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["category", "path", "size", "mtime_str"])
        writer.writeheader()
        for f in sorted(all_files, key=lambda x: (x["category"], x["path"])):
            writer.writerow({
                "category": f["category"],
                "path": f["path"],
                "size": f["size"],
                "mtime_str": f["mtime_str"],
            })
    print(f"CSV 清单: {csv_path}")

    # Write Markdown report
    md_path = DOCS_DIR / "stale_artifacts_audit.md"
    lines = [
        "# 过期文件审计清单\n",
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
        f"扫描文件总数: {len(all_files)}\n",
        "\n## 分类统计\n",
        "| 分类 | 文件数 |\n|---|---:|\n",
    ]
    for cat in sorted(counts):
        lines.append(f"| `{cat}` | {counts[cat]} |\n")

    lines.append("\n## keep_core（必须保留）\n")
    keep_core = [f for f in all_files if f["category"] == "keep_core"]
    for f in sorted(keep_core, key=lambda x: x["path"]):
        lines.append(f"- `{f['path']}` ({f['size']:,} bytes)\n")

    lines.append("\n## keep_latest（最新报告，保留）\n")
    keep_latest = [f for f in all_files if f["category"] == "keep_latest"]
    for f in sorted(keep_latest, key=lambda x: x["path"]):
        lines.append(f"- `{f['path']}` ({f['size']:,} bytes)\n")

    lines.append("\n## archive_artifact（建议归档）\n")
    archive = [f for f in all_files if f["category"] == "archive_artifact"]
    for f in sorted(archive, key=lambda x: x["path"]):
        lines.append(f"- `{f['path']}` ({f['size']:,} bytes)\n")

    lines.append("\n## delete_cache（可删除缓存）\n")
    cache = [f for f in all_files if f["category"] == "delete_cache"]
    for f in sorted(cache, key=lambda x: x["path"]):
        lines.append(f"- `{f['path']}` ({f['size']:,} bytes)\n")

    lines.append("\n## manual_review（需人工确认）\n")
    manual = [f for f in all_files if f["category"] == "manual_review"]
    for f in sorted(manual, key=lambda x: x["path"]):
        lines.append(f"- `{f['path']}` ({f['size']:,} bytes)\n")

    md_path.write_text("".join(lines), encoding="utf-8")
    print(f"Markdown 清单: {md_path}")
    print()
    print(f"共 {len(archive)} 个文件建议归档，{len(manual)} 个需人工确认")
    print(f"下一步: python scripts/archive_stale_round_artifacts.py  # dry-run")
    print(f"        python scripts/archive_stale_round_artifacts.py --apply  # 真正移动")


if __name__ == "__main__":
    main()
