#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round8 脚本二：修正任务书对照文案
==================================
将遗留问题中的过期文案（"需 archive"、"需清理过期候选"）改为已归档状态。
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"

CSV = METRICS / "round7_taskbook_compliance.csv"
MD = DOCS / "任务书完成情况_Round7.md"


def main():
    if not CSV.exists():
        raise FileNotFoundError(str(CSV))

    df = pd.read_csv(CSV)

    replacements = {
        "需清理过期候选结果，避免交付混乱": "Round7/Round8 已归档过期候选结果，正式交付保留 final 与诊断文件",
        "需归档过期产物，输出最终交付清单": "过期产物已归档，Round8 输出最终交付清单",
        "需 archive 过期产物，输出最终交付清单": "过期产物已归档，Round8 输出最终交付清单",
    }

    def repl(x):
        if not isinstance(x, str):
            return x
        for old, new in replacements.items():
            x = x.replace(old, new)
        return x

    df["遗留问题"] = df["遗留问题"].apply(repl)
    df.to_csv(CSV, index=False, encoding="utf-8-sig")

    lines = ["# 任务书完成情况 Round7", ""]
    lines.append("> 本文件由 Round8 更新，反映归档和最终交付清理后的状态。")
    lines.append("")
    lines.append("| 任务书要求方向 | 当前证据 | 关键文件 | 完成状态 | 遗留问题 |")
    lines.append("|---|---|---|---|---|")
    for _, r in df.iterrows():
        lines.append(
            f"| {r['任务书要求方向']} | {r['当前证据']} | `{r['关键文件']}` | {r['完成状态']} | {r['遗留问题']} |"
        )
    lines.append("")
    lines.append("## 总体判断")
    lines.append("")
    lines.append("当前项目在既有数据集上的模型能力评估、分布式功率预测、逐小时 NRMSE 诊断、站点级与城市级输出方面基本满足任务书实现要求。")
    lines.append("Round8 已完成最终交付清理：核心 final 文件保留，历史无效候选已归档。")
    lines.append("主要未闭环问题仍是少数高误差站点的数据映射/别名字典/功率列来源需要人工核查。")

    MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"已更新: {CSV}")
    print(f"已更新: {MD}")


if __name__ == "__main__":
    main()
