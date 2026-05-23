#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round8 脚本一：清理最终摘要中的误导性段落
===========================================
1. 删除 Round5 选择性修正参数段落（已在 archive）
2. 增加历史候选说明，明确 final 有效版本
3. 确保 final_eval 来源声明存在
"""
from __future__ import annotations

from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC = PROJECT_ROOT / "output" / "pv_pipeline" / "docs" / "当前最终结果摘要.md"


def main():
    if not DOC.exists():
        raise FileNotFoundError(str(DOC))

    text = DOC.read_text(encoding="utf-8")

    # 删除 Round5 选择性修正参数段落
    text = re.sub(
        r"\n## 选择性站点修正参数（Round5，共 225 个站点小时对）\n\n"
        r"- k 范围:.*?\n"
        r"- k 均值:.*?\n"
        r"- alpha 分布:.*?\n",
        "\n",
        text,
        flags=re.S,
    )

    history_note = """
## 历史候选说明

Round5 的 `MiddaySiteSelectiveCorrected` 和 Round6 的 `Round6StableBias` 均属于历史诊断候选：

- Round5 选择性站点修正在 valid 上改善，但 test 上变差，未进入 final。
- Round6 稳定偏差修正在 valid 上改善，但 test 上轻微变差，已被安全阈值拦截。
- 当前 final 未采用上述两个历史候选。

最终生效版本以 `metrics/final_version_selection_by_hour.csv` 为准。
"""

    if "## 历史候选说明" not in text:
        if "## Round7 工程闭环" in text:
            text = text.replace("## Round7 工程闭环", history_note + "\n## Round7 工程闭环")
        else:
            text += "\n" + history_note

    source_line = "> **本报告所有最终预测指标均来自 `output/pv_pipeline/tables/distributed_predictions_final_eval.pkl`。**"
    if source_line not in text:
        text += "\n\n" + source_line + "\n"

    DOC.write_text(text, encoding="utf-8")
    print(f"已清理: {DOC}")


if __name__ == "__main__":
    main()
