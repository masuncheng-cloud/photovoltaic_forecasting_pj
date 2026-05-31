#!/usr/bin/env python3
"""
archive_legacy_round_files.py
=============================
归档历史残留的 round 临时脚本和过期产物。

本脚本不删除文件，只移动到 archive 目录。
主流程不得依赖 archive 内文件。

用法：
    # 预览（不实际移动）
    python scripts/archive_legacy_round_files.py --dry-run

    # 执行归档
    python scripts/archive_legacy_round_files.py --apply

归档目录结构：
    archive/
        round_scripts/      ← roundXX 临时脚本
        round_docs/        ← Round*.md 文档
        old_outputs/       ← 过期产物（roundXX CSV, *before*.pkl 等）

受保护文件（不归档）：
    scripts/run_full_pipeline.py
    scripts/posttrain_validation.py
    scripts/check_dashboard_prediction_values.py
    scripts/export_interactive_dashboard_data.py
    scripts/update_dashboard_after_training.py
    scripts/compute_hourly_nrmse_consistent.py
    scripts/common_paths.py
    scripts/metrics_common.py
    scripts/archive_legacy_round_files.py
"""

import argparse
import os
import re
import shutil
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = PROJECT_ROOT / "archive"

SUBDIRS = {
    "scripts": ARCHIVE_ROOT / "round_scripts",
    "docs": ARCHIVE_ROOT / "round_docs",
    "output": ARCHIVE_ROOT / "old_outputs",
}

# ─── 归档规则 ────────────────────────────────────────────────────────────────

def scripts_to_archive(name: str) -> bool:
    """判断 scripts/ 下的文件是否应归档。"""
    protected = {
        "run_full_pipeline.py",
        "posttrain_validation.py",
        "check_dashboard_prediction_values.py",
        "export_interactive_dashboard_data.py",
        "update_dashboard_after_training.py",
        "compute_hourly_nrmse_consistent.py",
        "common_paths.py",
        "metrics_common.py",
        "archive_legacy_round_files.py",
        "__init__.py",
    }
    if name in protected:
        return False
    # RoundXX 临时脚本
    if re.search(r"round\d+", name, re.IGNORECASE):
        return True
    # v15/v2/v3 版本文件
    if re.search(r"(v15|v2|v3|backup|backup_)", name, re.IGNORECASE):
        return True
    return False


def docs_to_archive(name: str) -> bool:
    """判断 docs/ 下的文件是否应归档（Round48 之前的总结）。"""
    # Round48 之前的总结文档归档
    legacy_pattern = re.compile(r"^Round([0-9]{1,2})_", re.IGNORECASE)
    m = legacy_pattern.match(name)
    if m:
        num = int(m.group(1))
        if num < 48:
            return True
    # Round46_执行报告.md 等也归档
    if re.search(r"^Round\d+", name):
        return True
    if name in ("README.md", "__init__.py"):
        return False
    return False


def output_to_archive(rel_path: str) -> bool:
    """判断 output/pv_pipeline/ 下文件是否应归档。"""
    path_str = str(rel_path)

    # ── 当前活跃文件（不归档）─────────────────────────────
    protected_paths = [
        "output/pv_pipeline/tables/distributed_predictions_final_round36.pkl",
        "output/pv_pipeline/tables/distributed_predictions_final_eval_round36.pkl",
        "output/pv_pipeline/tables/distributed_predictions_final_full.pkl",
        "output/pv_pipeline/metrics/round46_hourly_nrmse_consistent.csv",
        "output/pv_pipeline/metrics/round46_site_hour_nrmse_consistent.csv",
        "output/pv_pipeline/metrics/round48_station_data_requirement_analysis.csv",
        "output/pv_pipeline/metrics/dashboard_prediction_consistency.csv",
        "output/pv_pipeline/metrics/site_test_daytime_zero_ratio_summary.csv",
        "output/pv_pipeline/metrics/audit_data_integrity.csv",
        "output/pv_pipeline/metrics/audit_metric_overall.csv",
        "output/pv_pipeline/metrics/audit_metric_recompute.csv",
        "output/pv_pipeline/metrics/audit_site_mapping.csv",
        "output/pv_pipeline/metrics/audit_split_integrity.csv",
        "output/pv_pipeline/metrics/calibration_ablation_by_site.csv",
        "output/pv_pipeline/metrics/data_quality_metrics.csv",
        "output/pv_pipeline/metrics/distributed_metrics_by_county_fixed.csv",
        "output/pv_pipeline/metrics/distributed_metrics_by_site_fixed.csv",
        "output/pv_pipeline/metrics/distributed_metrics_fixed.csv",
        "output/pv_pipeline/metrics/pr_month_comparison.csv",
        "output/pv_pipeline/metrics/power_on_metrics_v159.csv",
        "output/pv_pipeline/metrics/power_scene_summary_v159.csv",
        "output/pv_pipeline/metrics/top_day_zero_sites.csv",
        "output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv",
        "output/pv_pipeline/metrics/分布式光伏预测_逐小时平均相对误差.csv",
        "output/pv_pipeline/docs/Round48_样本量需求分析数据说明.md",
        "output/pv_pipeline/docs/Round49_执行报告_样本量散点图新增训练验证正功率样本横轴.md",
        "output/pv_pipeline/docs/Round50_工程收口与训练逻辑审计执行报告.md",
    ]
    for p in protected_paths:
        if path_str == p or path_str.endswith(p):
            return False

    # ── output/pv_pipeline/docs/ 下的 Round 文档────────────────
    # Round47 及之前归档，Round48+ 保留
    docs_round_match = re.match(
        r"output/pv_pipeline/docs/Round(\d+)_", path_str
    )
    if docs_round_match:
        num = int(docs_round_match.group(1))
        return num < 48  # Round47 及之前归档

    # ── 排除 docs 目录本身 ──────────────────────────────
    # 跳过 output/pv_pipeline/docs/ 下的非 Round 文件（当前没有）
    if path_str.startswith("output/pv_pipeline/docs/"):
        return False

    # ── archive_before_round36（已经是旧归档目录，归档）────
    if "archive_before_round36" in path_str:
        return True

    # ── 历史 round 产物（归档）──────────────────────────
    legacy_rounds = [
        "round34", "round35", "round40",
        "round41_42", "round44", "round45",
    ]
    for r in legacy_rounds:
        if r in path_str.lower():
            return True

    # ── *before* 文件（归档）────────────────────────────
    if "before" in path_str.lower():
        return True

    # ── *backup* 文件（归档）────────────────────────────
    if "backup" in path_str.lower():
        return True

    return False


# ─── 扫描与归档 ──────────────────────────────────────────────────────────────

def scan_files():
    """返回待归档文件列表。"""
    to_archive = []

    # scripts/
    scripts_dir = PROJECT_ROOT / "scripts"
    if scripts_dir.exists():
        for f in scripts_dir.glob("*"):
            if f.is_file() and scripts_to_archive(f.name):
                to_archive.append((f, SUBDIRS["scripts"], f.name))

    # docs/
    docs_dir = PROJECT_ROOT / "docs"
    if docs_dir.exists():
        for f in docs_dir.glob("*"):
            if f.is_file() and docs_to_archive(f.name):
                to_archive.append((f, SUBDIRS["docs"], f.name))

    # output/pv_pipeline/**/* - 按模式匹配
    output_root = PROJECT_ROOT / "output" / "pv_pipeline"
    if output_root.exists():
        for f in output_root.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(PROJECT_ROOT)
            if output_to_archive(str(rel)):
                # 放到 old_outputs/ 并保持相对路径
                subdir = SUBDIRS["output"] / f.relative_to(output_root).parent.name
                to_archive.append((f, subdir, f.name))

    return to_archive


def archive_files(to_archive: list, dry_run: bool = True) -> dict:
    """执行归档操作。返回统计。"""
    stats = {"scripts": 0, "docs": 0, "output": 0, "errors": []}

    for src, dest_dir, _ in to_archive:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name

        if dry_run:
            print(f"  [DRY] {src.relative_to(PROJECT_ROOT)}")
            print(f"       → {dest.relative_to(PROJECT_ROOT)}")
        else:
            try:
                shutil.move(str(src), str(dest))
                print(f"  [MOVE] {src.relative_to(PROJECT_ROOT)}")
                print(f"       → {dest.relative_to(PROJECT_ROOT)}")
                # 分类统计
                if "round_scripts" in dest_dir.name:
                    stats["scripts"] += 1
                elif "round_docs" in dest_dir.name:
                    stats["docs"] += 1
                else:
                    stats["output"] += 1
            except Exception as e:
                stats["errors"].append(f"{src.name}: {e}")
                print(f"  [ERROR] {src.name}: {e}")

    return stats


# ─── 预览归档内容 ───────────────────────────────────────────────────────────

def preview():
    """Dry-run：预览将归档的文件。"""
    to_archive = scan_files()

    print()
    print("=" * 60)
    print("归档预览（--dry-run）")
    print("=" * 60)
    print(f"\n归档目录: {ARCHIVE_ROOT.relative_to(PROJECT_ROOT)}")
    print(f"\n将归档 {len(to_archive)} 个文件：\n")

    by_dest = {}
    for src, dest_dir, _ in to_archive:
        key = dest_dir.relative_to(ARCHIVE_ROOT)
        by_dest.setdefault(key, []).append(src)

    total_scripts = 0
    total_docs = 0
    total_output = 0

    for dest_rel, files in sorted(by_dest.items()):
        print(f"  {dest_rel}/ ({len(files)} 个)")
        for f in sorted(files)[:5]:
            print(f"    - {f.relative_to(PROJECT_ROOT)}")
        if len(files) > 5:
            print(f"    ... 还有 {len(files)-5} 个")
        print()

        if "round_scripts" in str(dest_rel):
            total_scripts += len(files)
        elif "round_docs" in str(dest_rel):
            total_docs += len(files)
        else:
            total_output += len(files)

    print("-" * 40)
    print(f"  scripts/round_scripts: {total_scripts} 个")
    print(f"  docs/round_docs:      {total_docs} 个")
    print(f"  old_outputs:           {total_output} 个")
    print(f"  总计:                 {len(to_archive)} 个")
    print()
    print("使用 --apply 执行实际归档。")
    print()

    return to_archive


def main():
    parser = argparse.ArgumentParser(
        description="归档历史 round 临时脚本和过期产物（不删除，只移动）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="预览归档内容（不实际移动文件）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="执行实际归档",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("请指定 --dry-run（预览）或 --apply（执行归档）")
        parser.print_help()
        return

    to_archive = scan_files()

    if args.dry_run:
        preview()

    if args.apply:
        # 写一个归档记录
        ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = ARCHIVE_ROOT / f"archive_log_{stamp}.txt"

        print()
        print("=" * 60)
        print("执行归档（--apply）")
        print("=" * 60)
        print(f"\n归档目录: {ARCHIVE_ROOT.relative_to(PROJECT_ROOT)}")

        # 重定向 print 到文件
        import io, contextlib
        buf = io.StringIO()

        stats = archive_files(to_archive, dry_run=False)

        log_lines = [
            f"归档时间: {datetime.now().isoformat()}\n",
            f"归档统计:\n",
            f"  round_scripts: {stats['scripts']} 个\n",
            f"  round_docs:    {stats['docs']} 个\n",
            f"  old_outputs:   {stats['output']} 个\n",
            f"  错误:          {len(stats['errors'])} 个\n",
            f"\n已归档文件列表:\n",
        ]
        for src, dest_dir, _ in to_archive:
            log_lines.append(f"  {src.relative_to(PROJECT_ROOT)} → {dest_dir.relative_to(PROJECT_ROOT)}\n")

        log_path.write_text("".join(log_lines), encoding="utf-8")
        print(f"\n[OK] 归档记录 → {log_path.relative_to(PROJECT_ROOT)}")

        print()
        print("=" * 60)
        print("归档完成")
        print("=" * 60)
        print(f"  round_scripts: {stats['scripts']} 个")
        print(f"  round_docs:    {stats['docs']} 个")
        print(f"  old_outputs:  {stats['output']} 个")
        if stats["errors"]:
            print(f"  错误: {len(stats['errors'])} 个")
            for e in stats["errors"]:
                print(f"    - {e}")


if __name__ == "__main__":
    main()
