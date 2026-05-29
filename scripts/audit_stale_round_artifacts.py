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
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pv_pipeline"
DOCS_DIR = OUT / "docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

# 必须保留的核心文件（相对于 ROOT）
KEEP_CORE_PATTERNS = [
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
    # 核心可视化
    "scripts/export_interactive_dashboard_data.py",
    "scripts/update_dashboard_after_training.py",
    "scripts/check_dashboard_prediction_values_round36.py",
    "scripts/check_dashboard_prediction_values_round35.py",
    # Round47 统一收口
    "scripts/post_training_finalize_outputs.py",
    "scripts/check_post_training_auto_finalize.py",
    "scripts/compute_hourly_nrmse_consistent.py",
    "scripts/round46_recompute_hourly_nrmse_consistent.py",
    # Dashboard 验证
    "scripts/check_dashboard_auto_update_stamp.py",
    "scripts/round44_dashboard_regression_check.py",
    # 训练逻辑修正
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
    "scripts/check_pipeline_consistency.py",
    # 图表和截图
    "scripts/plot_map_visualization.py",
    "take_dashboard_screenshots.py",
    # 可视化页面
    "stages/05_visualization/interactive_forecast_dashboard.html",
]

# 建议归档的文件（round编号脚本中旧轮次的）
ARCHIVE_PATTERNS = [
    # 旧轮次的完整归档脚本
    "archive_stale_outputs_round7.py",
    "archive_stale_artifacts_round14.py",
    "archive_remaining_stale_artifacts_round15.py",
    # 旧轮次临时诊断脚本（round1-39）
    # 实验性 dawn/dusk 修复脚本
    "fix_dawn_dusk_conservative.py",
    "fix_dawn_dusk_relative_error.py",
    "fix_hourly_bias.py",
    "apply_dd_on_v1.py",
    "apply_dawn_dusk_floor.py",
    "combine_p1_and_dawn_dusk.py",
    # midday 实验
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
    "check_midday_nrmse_improvement.py",
    # 早期偏差校准
    "apply_bias_calibration_round34.py",
    # 早期版本验证和报告
    "build_site_validity_round33.py",
    "build_site_validity_round34.py",
    "regenerate_round33_metrics.py",
    "posttrain_validation_round33.py",
    "posttrain_validation_round34.py",
    "posttrain_validation_round35.py",
    "pretrain_data_audit_round33.py",
    "compute_round34_metrics.py",
    # 旧对比和守门
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
    "compute_hourly_relative_error_robust.py",
    "compute_city_hourly_error.py",
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
    # 旧存档
    "archive_rejected_candidates_round11.py",
    "archive_current_best_round33.py",
    "backup_current_verified_state_round14.py",
]

# 需人工确认的文件
MANUAL_REVIEW_PATTERNS = [
    "scripts/generate_final_delivery_manifest_round8.py",
    "scripts/check_round8_final_package.py",
    "scripts/check_final_is_best_round10.py",
    "scripts/save_current_best_round10.py",
    "scripts/promote_candidate_if_better_round10.py",
    "scripts/summarize_candidate_decisions_round11.py",
    "scripts/clean_final_summary_round8.py",
    "scripts/run_round10_best_guard_pipeline.py",
    "scripts/run_round33_full_retrain.py",
    "scripts/run_full_retrain_round14.py",
    "scripts/round45_guard_and_commit.py",
    "scripts/round45_apply_site_hour_shrinkage_calibration.py",
    "scripts/round45_site_hour_nrmse_diagnosis.py",
    "scripts/round45_hourly_site_nrmse_summary.py",
]


def is_round_script(path_str):
    """判断是否为旧轮次 round1-39 编号的脚本。"""
    m = re.search(r"round(\d+)", path_str)
    if m:
        rn = int(m.group(1))
        return rn <= 39
    return False


def classify(path_str, rel_path):
    """返回文件分类。"""
    # 白名单精确匹配
    if rel_path in KEEP_CORE_PATTERNS:
        return "keep_core"
    # 最新报告
    if rel_path in (
        "output/pv_pipeline/docs/Round46_执行总结.md",
        "output/pv_pipeline/docs/Round45_执行总结.md",
        "output/pv_pipeline/docs/Round44_执行总结.md",
        "光伏功率预测项目.md",
        "光伏功率预测项目.md",
        "光伏功率预测项目.md",
    ):
        return "keep_latest"
    # Round46/45/44 执行报告保留
    if ".md" in path_str and any(x in path_str for x in ["Round46", "Round45", "Round44"]):
        return "keep_latest"
    # 任务书
    if "任务书" in path_str or "taskbook" in path_str.lower():
        return "keep_core"
    # 项目文档
    if path_str in ("光伏功率预测项目.md", "README.md", "CHANGELOG.md"):
        return "keep_core"
    # 仪表盘截图
    if "round40" in path_str and ".png" in path_str:
        return "keep_latest"
    # 缓存
    if "__pycache__" in path_str or ".pyc" in path_str:
        return "delete_cache"
    # Round47 归档脚本本身
    if rel_path in (
        "scripts/audit_stale_round_artifacts.py",
        "scripts/archive_stale_round_artifacts.py",
    ):
        return "keep_core"
    # archive 目录
    if "/archive/" in path_str or path_str.startswith("archive/"):
        return "archive_artifact"
    # 归档模式匹配
    for pat in ARCHIVE_PATTERNS:
        if pat in path_str:
            return "archive_artifact"
    # 旧轮次 round1-39 脚本
    if is_round_script(path_str):
        return "archive_artifact"
    # 人工确认模式
    for pat in MANUAL_REVIEW_PATTERNS:
        if pat in path_str:
            return "manual_review"
    return "manual_review"


def main():
    print("=" * 60)
    print("audit_stale_round_artifacts")
    print("=" * 60)
    print("Project root:", ROOT)
    print()

    all_files = []

    scan_dirs = [
        ROOT / "scripts",
        OUT / "metrics",
        OUT / "docs",
        OUT / "interactive_dashboard",
        ROOT / "stages" / "05_visualization",
        ROOT,
    ]

    for base_dir in scan_dirs:
        if not base_dir.exists():
            continue
        for p in sorted(base_dir.rglob("*")):
            if not p.is_file():
                continue
            try:
                rel = str(p.relative_to(ROOT))
            except ValueError:
                continue
            if "__pycache__" in rel or rel.endswith(".pyc"):
                continue
            stat = p.stat()
            all_files.append({
                "path": rel,
                "full_path": str(p),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "mtime_str": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })

    print("Scanned", len(all_files), "files")
    print()

    # Classify
    for f in all_files:
        f["category"] = classify(f["path"], f["path"])

    # Counts
    counts = {}
    for f in all_files:
        counts[f["category"]] = counts.get(f["category"], 0) + 1
    print("Category breakdown:")
    for cat in sorted(counts):
        print(f"  {cat:20s}: {counts[cat]:5d} files")
    print()

    # Write CSV
    csv_path = DOCS_DIR / "stale_artifacts_audit.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["category", "path", "size", "mtime_str"])
        writer.writeheader()
        for f2 in sorted(all_files, key=lambda x: (x["category"], x["path"])):
            writer.writerow({
                "category": f2["category"],
                "path": f2["path"],
                "size": f2["size"],
                "mtime_str": f2["mtime_str"],
            })
    print("CSV:", csv_path)

    # Write Markdown
    md_path = DOCS_DIR / "stale_artifacts_audit.md"
    lines = [
        "# Round47: Stale Artifacts Audit\n",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
        f"Total files scanned: {len(all_files)}\n",
        "\n## Category Summary\n",
        "| Category | Count |\n|---|---:|\n",
    ]
    for cat in sorted(counts):
        lines.append(f"| `{cat}` | {counts[cat]} |\n")

    for cat in ["keep_core", "keep_latest", "archive_artifact", "delete_cache", "manual_review"]:
        cat_files = sorted([f for f in all_files if f["category"] == cat], key=lambda x: x["path"])
        if not cat_files:
            continue
        lines.append(f"\n## {cat}\n")
        for f in cat_files:
            size_kb = f["size"] / 1024
            lines.append(
                f"- `{f['path']}` ({size_kb:.1f}KB, {f['mtime_str']})\n"
            )

    md_path.write_text("".join(lines), encoding="utf-8")
    print("Markdown:", md_path)
    print()
    archive_count = counts.get("archive_artifact", 0)
    manual_count = counts.get("manual_review", 0)
    print(f"Suggest archiving: {archive_count} files")
    print(f"Manual review: {manual_count} files")
    print()
    print("Next step:")
    print("  python scripts/archive_stale_round_artifacts.py        # dry-run")
    print("  python scripts/archive_stale_round_artifacts.py --apply  # actually move files")


if __name__ == "__main__":
    main()
