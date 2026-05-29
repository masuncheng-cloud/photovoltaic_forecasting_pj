#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round8 脚本四：最终交付包检查
==============================
1. 检查非 archive 区域无残留过期文件
2. 检查最终摘要无误导段落
3. 检查交付清单存在
4. 检查核心文件存在
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output" / "pv_pipeline"
METRICS = OUT / "metrics"
TABLES = OUT / "tables"
DOCS = OUT / "docs"

BAD_PATTERNS = [
    "midday_residual_specialist",
    "midday_selective_site_correction",
    "distributed_predictions_midday_residual_specialist",
    "distributed_predictions_midday_selective_site_corrected",
    "distributed_predictions_round6_stable_bias",
    "round6_stable_bias_test_hourly_nrmse",
    "round6_stable_bias_correction_params",
    "round6_stable_bias_valid_ablation",
    "当前结果_vs_周二基准",
    "midday_nrmse_acceptance",
    "midday_next_step_gain_vs_site_calibrated",
]


def main():
    errors = []

    # 1. 非 archive 区域不应残留无效候选文件
    for base in [METRICS, TABLES, DOCS]:
        if not base.exists():
            continue
        for path in base.iterdir():
            if not path.is_file():
                continue
            if any(p in path.name for p in BAD_PATTERNS):
                errors.append(f"非 archive 区域仍残留过期文件: {path.relative_to(PROJECT_ROOT)}")

    # 2. 最终摘要不应再有 Round5 参数段落
    summary = DOCS / "当前最终结果摘要.md"
    if not summary.exists():
        errors.append("缺少 当前最终结果摘要.md")
    else:
        text = summary.read_text(encoding="utf-8")
        if "选择性站点修正参数（Round5" in text:
            errors.append("当前最终结果摘要.md 仍包含 Round5 选择性修正参数段落")
        if "本报告所有最终预测指标均来自" not in text:
            errors.append("当前最终结果摘要.md 缺少 final_eval 来源声明")
        if "## 历史候选说明" not in text:
            errors.append("当前最终结果摘要.md 缺少 ## 历史候选说明 段落")

    # 3. 最终交付清单
    for fname in ["最终交付文件清单_Round8.md", "最终交付文件清单_Round8.csv"]:
        if not (DOCS / fname).exists():
            errors.append(f"缺少 {fname}")

    # 4. 核心 final 文件必须存在
    required = [
        TABLES / "distributed_predictions_final_eval.pkl",
        TABLES / "distributed_predictions_final_full.pkl",
        METRICS / "round7_final_overall_metrics.csv",
        METRICS / "分布式光伏预测_逐小时平均NRMSE.csv",
        METRICS / "final_version_selection_by_hour.csv",
        DOCS / "任务书完成情况_Round7.md",
    ]
    for p in required:
        if not p.exists():
            errors.append(f"缺少核心文件: {p.relative_to(PROJECT_ROOT)}")

    if errors:
        print("[FAIL] Round8 final package check failed:")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)

    print("[OK] Round8 final package check passed.")


if __name__ == "__main__":
    main()
