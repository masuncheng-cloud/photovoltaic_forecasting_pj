#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round7 脚本四：任务书对照验收
=============================
输出任务书完成情况_Round7.md 和 round7_taskbook_compliance.csv。
"""
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"
METRICS.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)


def main():
    rows = [
        {
            "任务书要求方向": "汇聚气象、辐照、功率、站点台账等多源数据",
            "当前证据": "已形成原始功率长表、站点映射、气象插值与特征表；报告列出集中式/分布式映射数量",
            "关键文件": "output/pv_pipeline/docs/当前最终结果摘要.md",
            "完成状态": "基本满足",
            "遗留问题": "S012/S055/S050/S032 需人工核查功率列映射",
        },
        {
            "任务书要求方向": "利用集中式光伏功率反演光伏资源/辐照",
            "当前证据": "测试集辐照 Corr 0.99987，辐照 NRMSE 0.387%",
            "关键文件": "光伏功率预测项目.md",
            "完成状态": "满足",
            "遗留问题": "需在正式报告中说明辐照 NRMSE 归一化基准",
        },
        {
            "任务书要求方向": "将集中式信息扩展到分布式站点",
            "当前证据": "IDW/ERA5/反演融合，测试集融合 RMSE 3.016 W/m²",
            "关键文件": "光伏功率预测项目.md",
            "完成状态": "满足",
            "遗留问题": "高误差站点需核查映射，而非继续调融合参数",
        },
        {
            "任务书要求方向": "实现分布式光伏功率预测",
            "当前证据": "final_full/final_eval 已生成；68,888 条测试评估样本，53 个站点",
            "关键文件": "output/pv_pipeline/tables/distributed_predictions_final_eval.pkl",
            "完成状态": "基本满足",
            "遗留问题": "小容量和异常映射站点误差偏高",
        },
        {
            "任务书要求方向": "输出站点级和全市级预测结果",
            "当前证据": "逐小时 NRMSE、站点诊断、城市统计、版本选择表均已生成",
            "关键文件": "output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv",
            "完成状态": "满足",
            "遗留问题": "需清理过期候选结果，避免交付混乱",
        },
        {
            "任务书要求方向": "评估模型预测能力",
            "当前证据": "MAE=0.5893 MW，RMSE=1.2047 MW，pred_actual_ratio=0.9859，逐小时 NRMSE 完整",
            "关键文件": "output/pv_pipeline/metrics/round7_final_overall_metrics.csv",
            "完成状态": "满足",
            "遗留问题": "统一禁止使用旧 MAPE/WAPE 作为主指标",
        },
        {
            "任务书要求方向": "逐小时误差诊断",
            "当前证据": "6-19 点站点平均 NRMSE 和城市 NRMSE 已输出；10-14 点安全版本固定",
            "关键文件": "output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv",
            "完成状态": "满足",
            "遗留问题": "6/18/19 城市 NRMSE 仍偏高，但本阶段暂不优化早晚",
        },
        {
            "任务书要求方向": "结果闭环和可复现检查",
            "当前证据": "Round7 end-to-end 检查和 metrics 一致性检查通过",
            "关键文件": "output/pv_pipeline/metrics/round7_end_to_end_deliverables_check.csv",
            "完成状态": "满足",
            "遗留问题": "需归档过期产物，输出最终交付清单",
        },
        {
            "任务书要求方向": "工程化交付",
            "当前证据": "核心 pkl/csv/docs 齐全；Round7 已统一 metrics 来源",
            "关键文件": "output/pv_pipeline/",
            "完成状态": "部分满足",
            "遗留问题": "需 archive 过期产物，输出最终交付清单",
        },
    ]

    df = pd.DataFrame(rows)
    out_csv = METRICS / "round7_taskbook_compliance.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    md = ["# 任务书完成情况 Round7", ""]
    md.append("> 本文件由 `scripts/generate_taskbook_compliance_round7.py` 自动生成。")
    md.append("")
    md.append("| 任务书要求方向 | 当前证据 | 关键文件 | 完成状态 | 遗留问题 |")
    md.append("|---|---|---|---|---|")
    for _, r in df.iterrows():
        md.append(
            f"| {r['任务书要求方向']} | {r['当前证据']} | `{r['关键文件']}` | {r['完成状态']} | {r['遗留问题']} |"
        )
    md.append("")
    md.append("## 总体判断")
    md.append("")
    md.append("当前项目在既有数据集上的模型能力评估、分布式功率预测、逐小时 NRMSE 诊断、站点级与城市级输出方面基本满足任务书实现要求。")
    md.append("当前主要未闭环问题不是模型流程缺失，而是少数高误差站点的数据映射/别名字典/功率列来源需要人工核查。")

    (DOCS / "任务书完成情况_Round7.md").write_text("\n".join(md), encoding="utf-8")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
