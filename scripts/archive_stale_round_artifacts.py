"""
archive_stale_round_artifacts.py
================================
安全归档旧轮次脚本（不清除，只移动到归档目录）。

默认 dry-run 模式：
  python scripts/archive_stale_round_artifacts.py

真正执行归档：
  python scripts/archive_stale_round_artifacts.py --apply

归档目录：
  archive/round_artifacts_before_round47/

每个被移动的文件都会记录到：
  archive/round_artifacts_before_round47/archive_manifest.csv

安全保证：
  - 默认 dry-run，不删除任何文件
  - 移动前写出 manifest
  - 不使用永久删除（shutil.move 而非 os.remove）
"""

import csv
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_DIR = ROOT / "archive" / "round_artifacts_before_round47"

# 来自 audit_stale_round_artifacts.py 的分类结果
# archive_artifact: 明确建议归档
# keep_core, keep_latest: 不移动
# manual_review: 不移动
# delete_cache: 可安全删除（但默认也不移动）

# 要归档的脚本列表（基于 audit 结果）
ARCHIVE_SCRIPTS = [
    # 旧轮次完整归档脚本
    "scripts/archive_stale_outputs_round7.py",
    "scripts/archive_stale_artifacts_round14.py",
    "scripts/archive_remaining_stale_artifacts_round15.py",
    # dawn/dusk 实验
    "scripts/fix_dawn_dusk_conservative.py",
    "scripts/fix_dawn_dusk_relative_error.py",
    "scripts/fix_hourly_bias.py",
    "scripts/apply_dd_on_v1.py",
    "scripts/apply_dawn_dusk_floor.py",
    "scripts/combine_p1_and_dawn_dusk.py",
    # midday 实验
    "scripts/apply_midday_selective_site_correction.py",
    "scripts/apply_midday_stable_bias_correction_round6.py",
    "scripts/apply_midday_residual_specialist.py",
    "scripts/train_midday_specialist_model_round9.py",
    "scripts/blend_midday_specialist_round9.py",
    "scripts/check_midday_next_step_gain.py",
    "scripts/check_midday_nrmse_improvement.py",
    "scripts/analyze_midday_nrmse_contribution_round9.py",
    "scripts/diagnose_midday_bias_stability_round6.py",
    "scripts/diagnose_midday_worst_site_hours.py",
    "scripts/export_watch_site_midday_curves_round9.py",
    # 早期偏差校准
    "scripts/apply_bias_calibration_round34.py",
    # 早期版本验证和报告
    "scripts/build_site_validity_round33.py",
    "scripts/build_site_validity_round34.py",
    "scripts/regenerate_round33_metrics.py",
    "scripts/posttrain_validation_round33.py",
    "scripts/posttrain_validation_round34.py",
    "scripts/posttrain_validation_round35.py",
    "scripts/pretrain_data_audit_round33.py",
    "scripts/compute_round34_metrics.py",
    # 旧对比和守门
    "scripts/check_round36_vs_round34_metrics.py",
    "scripts/check_round14_final_delivery.py",
    "scripts/check_round15_final_delivery.py",
    "scripts/compare_with_week2_reference.py",
    "scripts/compare_retrain_with_verified_best_round14.py",
    "scripts/check_gblend_time_alignment.py",
    # 旧预测构建
    "scripts/rebuild_fixed_predictions.py",
    "scripts/evaluate_fixed_predictions.py",
    "scripts/clean_prediction_table_round33.py",
    "scripts/apply_power_alias_overrides_round9.py",
    "scripts/diagnose_power_alias_mapping_round9.py",
    # 早期 MAE/MAPE 实验
    "scripts/compute_multi_metric.py",
    "scripts/compute_nrmse_reports_round10.py",
    "scripts/compute_hourly_site_outliers.py",
    "scripts/compute_hourly_relative_error_robust.py",
    "scripts/compute_city_hourly_error.py",
    # 旧典型站点分析
    "scripts/diagnose_high_sample_bad_sites_round32.py",
    "scripts/diagnose_training_effect_factors_round31.py",
    # 旧校准
    "scripts/apply_midday_site_nrmse_calibration.py",
    "scripts/apply_round41_42_unified_daytime_and_site_calibration.py",
    # 其他已废弃
    "scripts/before_after_comparison.py",
    "scripts/regenerate_chinese_metrics.py",
    "scripts/generate_model_capability_report.py",
    "scripts/final_comprehensive_report.py",
    "scripts/generate_calibration_report.py",
    "scripts/regenerate_final_metrics_round7.py",
    "scripts/diagnose_site_capacity_mapping_round6.py",
    "scripts/check_round6_midday_gain.py",
    "scripts/generate_round36_training_log.py",
    "scripts/update_project_md_metrics.py",
    "scripts/generate_round36_training_log.py",
    # 旧存档
    "scripts/archive_rejected_candidates_round11.py",
    "scripts/archive_current_best_round33.py",
    "scripts/backup_current_verified_state_round14.py",
    # 旧 delivery 相关
    "scripts/generate_taskbook_compliance_round7.py",
    "scripts/update_taskbook_compliance_round8.py",
    "scripts/check_end_to_end_deliverables_round7.py",
    "scripts/generate_final_delivery_manifest_round8.py",
    "scripts/check_round8_final_package.py",
    # 旧守门/候选相关
    "scripts/check_final_is_best_round10.py",
    "scripts/save_current_best_round10.py",
    "scripts/promote_candidate_if_better_round10.py",
    "scripts/summarize_candidate_decisions_round11.py",
    "scripts/clean_final_summary_round8.py",
    # 旧入口脚本
    "scripts/run_round10_best_guard_pipeline.py",
    "scripts/run_round33_full_retrain.py",
    "scripts/run_full_retrain_round14.py",
    # Round45 脚本（已过时被 round46/47 替代）
    "scripts/round45_guard_and_commit.py",
    "scripts/round45_apply_site_hour_shrinkage_calibration.py",
    "scripts/round45_site_hour_nrmse_diagnosis.py",
    "scripts/round45_hourly_site_nrmse_summary.py",
]


def get_round_number(filename):
    import re
    m = re.search(r"round(\d+)", filename, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 999


def get_archive_subdir(path_str):
    """确定归档子目录：scripts/ 或 docs/"""
    if path_str.startswith("scripts/"):
        return "scripts"
    if path_str.startswith("docs/"):
        return "docs"
    if path_str.startswith("stages/"):
        return "stages"
    return "other"


def move_file(src, dest_dir):
    """安全移动文件到 dest_dir。返回 (src, dest, status)。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    # 防止文件名冲突
    if dest.exists():
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        dest = dest_dir / f"{src.stem}_{ts}{src.suffix}"
    shutil.move(str(src), str(dest))
    return dest


def main():
    apply = "--apply" in sys.argv
    mode = "APPLY" if apply else "DRY-RUN"

    print("=" * 60)
    print(f"archive_stale_round_artifacts.py  [{mode}]")
    print("=" * 60)
    print("Archive root:", ARCHIVE_DIR)
    print()

    manifest_rows = []

    # Process each script
    archived = []
    skipped = []
    not_found = []

    for path_str in sorted(ARCHIVE_SCRIPTS):
        src = ROOT / path_str
        if not src.exists():
            not_found.append(path_str)
            print(f"  [SKIP] {path_str} (not found)")
            continue

        subdir = get_archive_subdir(path_str)
        dest_dir = ARCHIVE_DIR / subdir

        rn = get_round_number(path_str)

        if apply:
            try:
                dest = move_file(src, dest_dir)
                archived.append((path_str, str(dest)))
                manifest_rows.append({
                    "original_path": path_str,
                    "archived_path": str(dest.relative_to(ARCHIVE_DIR)),
                    "round_number": rn,
                    "archived_at": datetime.now().isoformat(timespec="seconds"),
                    "action": "moved",
                })
                print(f"  [MOVED] {path_str} -> {dest.relative_to(ARCHIVE_DIR)}")
            except Exception as e:
                print(f"  [ERROR] {path_str}: {e}")
                skipped.append(path_str)
        else:
            archived.append((path_str, str(dest_dir / src.name)))
            manifest_rows.append({
                "original_path": path_str,
                "archived_path": str(dest_dir / src.name),
                "round_number": rn,
                "archived_at": "",
                "action": "would_move",
            })
            print(f"  [WOULD MOVE] {path_str} -> {dest_dir.relative_to(ARCHIVE_DIR)}/")

    print()
    print("Summary:")
    print(f"  Would move : {len(archived)} files")
    print(f"  Not found  : {len(not_found)} files")
    print(f"  Skipped    : {len(skipped)} files")
    print()

    if not apply:
        print("DRY-RUN: no files were actually moved.")
        print("To apply: python scripts/archive_stale_round_artifacts.py --apply")
    else:
        print("APPLY: files have been moved.")

    # Write manifest
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = ARCHIVE_DIR / "archive_manifest.csv"
    if manifest_rows:
        with open(manifest_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["original_path", "archived_path", "round_number", "archived_at", "action"])
            writer.writeheader()
            for row in sorted(manifest_rows, key=lambda x: (x["action"] != "would_move", x["original_path"])):
                writer.writerow(row)
        print()
        print("Manifest:", manifest_path)

    # Write readme in archive dir
    readme = ARCHIVE_DIR / "README.md"
    readme.write_text(
        f"""# Round47 Archive: round_artifacts_before_round47

Generated: {datetime.now().isoformat(timespec="seconds")}
Mode: {mode}
Archived: {len(archived)} files

这些文件已从项目主目录移动到这里。

## 恢复方法

如需恢复单个文件，从归档目录复制回原位置：

```bash
cp archive/round_artifacts_before_round47/scripts/<file>.py scripts/
```
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
