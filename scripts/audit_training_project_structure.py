#!/usr/bin/env python3
"""
Audit training project structure.
Checks that all required directories and files exist before a full training run.

Usage:
    python scripts/audit_training_project_structure.py
    python scripts/audit_training_project_structure.py --output-root output/pv_pipeline
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_STRUCTURES = [
    ("data/", "dir", True, "数据根目录"),
    ("data/power_data/", "dir", True, "功率数据目录"),
    ("data/2023/", "dir", True, "2023 年数据"),
    ("data/2023/data_stream-oper_stepType-instant.nc", "file", True, "2023 瞬时气象文件"),
    ("data/2023/data_stream-oper_stepType-accum.nc", "file", True, "2023 累积气象文件"),
    ("data/2024/", "dir", True, "2024 年数据"),
    ("data/2024/data_stream-oper_stepType-instant.nc", "file", True, "2024 瞬时气象文件"),
    ("data/2024/data_stream-oper_stepType-accum.nc", "file", True, "2024 累积气象文件"),
    ("data/2025/", "dir", True, "2025 年数据"),
    ("data/2025/data_stream-oper_stepType-instant.nc", "file", True, "2025 瞬时气象文件"),
    ("data/2025/data_stream-oper_stepType-accum.nc", "file", True, "2025 累积气象文件"),
    ("scripts/run_full_pipeline.py", "file", True, "主流程入口"),
    ("scripts/export_interactive_dashboard_data.py", "file", True, "Dashboard 导出脚本"),
    ("scripts/dashboard_regression_check.py", "file", True, "Dashboard 回归检查"),
    ("scripts/check_dashboard_prediction_values.py", "file", True, "Dashboard 预测值校验"),
    ("scripts/posttrain_validation.py", "file", True, "训练后审计"),
    ("src/pv_forecasting/", "dir", False, "源码目录（可选）"),
    ("stages/", "dir", False, "Stages 目录（可选）"),
    ("configs/pipeline.yaml", "file", False, "Pipeline 配置（可选）"),
]


def audit(output_root: Path) -> list[tuple[str, str, str, bool, str, str]]:
    results = []
    data_root = PROJECT_ROOT / "data"
    for rel_path, kind, required, desc in REQUIRED_STRUCTURES:
        p = PROJECT_ROOT / rel_path
        exists = p.exists()
        if kind == "dir":
            correct = exists and p.is_dir()
        else:
            correct = exists and p.is_file()
        status = "PASS" if correct else ("WARN" if not required else "FAIL")
        note = ""
        if not exists:
            note = "文件/目录不存在"
        elif kind == "dir" and not p.is_dir():
            note = "路径存在但不是目录"
        elif kind == "file" and not p.is_file():
            note = "路径存在但不是文件"
        else:
            note = "OK"
        results.append((desc, rel_path, kind, required, status, note))
    return results


def main():
    parser = argparse.ArgumentParser(description="训练项目结构审计")
    parser.add_argument(
        "--output-root",
        type=str,
        default="output/pv_pipeline",
        help="Output root (default: output/pv_pipeline)",
    )
    args = parser.parse_args()

    output_root = PROJECT_ROOT / args.output_root
    val_dir = output_root / "validation"
    val_dir.mkdir(parents=True, exist_ok=True)

    results = audit(output_root)

    # Console output
    all_pass = True
    print("=" * 60)
    print("Project Structure Audit")
    print("=" * 60)
    for desc, rel_path, kind, required, status, note in results:
        icon = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL"}[status]
        if status == "FAIL":
            all_pass = False
        print(f"[{icon:4s}] {desc}")
        print(f"       {rel_path} — {note}")

    # CSV
    csv_path = val_dir / "project_structure_audit.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["description", "path", "kind", "required", "status", "note"])
        w.writerows(results)
    print(f"\n[OK] CSV → {csv_path}")

    # Markdown
    md_path = val_dir / "project_structure_audit.md"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# 项目结构审计报告\n\n生成时间: {now}\n\n",
        "| 描述 | 路径 | 类型 | 必需 | 状态 | 说明 |\n",
        "|------|------|------|------|------|------|\n",
    ]
    for desc, rel_path, kind, required, status, note in results:
        req_str = "是" if required else "否"
        lines.append(f"| {desc} | `{rel_path}` | {kind} | {req_str} | {status} | {note} |\n")
    total = len(results)
    passed = sum(1 for r in results if r[4] == "PASS")
    warned = sum(1 for r in results if r[4] == "WARN")
    failed = sum(1 for r in results if r[4] == "FAIL")
    lines.append(f"\n汇总: {passed} PASS / {warned} WARN / {failed} FAIL\n")
    md_path.write_text("".join(lines), encoding="utf-8")
    print(f"[OK] MD  → {md_path}")

    print()
    print("=" * 60)
    if failed > 0:
        print(f"[FAIL] {failed} required items missing — please fix before training")
    elif warned > 0:
        print(f"[WARN] {warned} optional items missing — OK to proceed")
    else:
        print(f"[PASS] All structure checks passed")
    print("=" * 60)

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
