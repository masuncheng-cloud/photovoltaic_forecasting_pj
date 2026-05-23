# 任务书完成情况 Round7

> 本文件由 `scripts/generate_taskbook_compliance_round7.py` 自动生成。

| 任务书要求方向 | 当前证据 | 关键文件 | 完成状态 | 遗留问题 |
|---|---|---|---|---|
| 汇聚气象、辐照、功率、站点台账等多源数据 | 已形成原始功率长表、站点映射、气象插值与特征表；报告列出集中式/分布式映射数量 | `output/pv_pipeline/docs/当前最终结果摘要.md` | 基本满足 | S012/S055/S050/S032 需人工核查功率列映射 |
| 利用集中式光伏功率反演光伏资源/辐照 | 测试集辐照 Corr 0.99987，辐照 NRMSE 0.387% | `光伏功率预测项目.md` | 满足 | 需在正式报告中说明辐照 NRMSE 归一化基准 |
| 将集中式信息扩展到分布式站点 | IDW/ERA5/反演融合，测试集融合 RMSE 3.016 W/m² | `光伏功率预测项目.md` | 满足 | 高误差站点需核查映射，而非继续调融合参数 |
| 实现分布式光伏功率预测 | final_full/final_eval 已生成；68,888 条测试评估样本，53 个站点 | `output/pv_pipeline/tables/distributed_predictions_final_eval.pkl` | 基本满足 | 小容量和异常映射站点误差偏高 |
| 输出站点级和全市级预测结果 | 逐小时 NRMSE、站点诊断、城市统计、版本选择表均已生成 | `output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv` | 满足 | 需清理过期候选结果，避免交付混乱 |
| 评估模型预测能力 | MAE=0.5893 MW，RMSE=1.2047 MW，pred_actual_ratio=0.9859，逐小时 NRMSE 完整 | `output/pv_pipeline/metrics/round7_final_overall_metrics.csv` | 满足 | 统一禁止使用旧 MAPE/WAPE 作为主指标 |
| 逐小时误差诊断 | 6-19 点站点平均 NRMSE 和城市 NRMSE 已输出；10-14 点安全版本固定 | `output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv` | 满足 | 6/18/19 城市 NRMSE 仍偏高，但本阶段暂不优化早晚 |
| 结果闭环和可复现检查 | Round7 end-to-end 检查和 metrics 一致性检查通过 | `output/pv_pipeline/metrics/round7_end_to_end_deliverables_check.csv` | 满足 | 需归档过期产物，输出最终交付清单 |
| 工程化交付 | 核心 pkl/csv/docs 齐全；Round7 已统一 metrics 来源 | `output/pv_pipeline/` | 部分满足 | 需 archive 过期产物，输出最终交付清单 |

## 总体判断

当前项目在既有数据集上的模型能力评估、分布式功率预测、逐小时 NRMSE 诊断、站点级与城市级输出方面基本满足任务书实现要求。
当前主要未闭环问题不是模型流程缺失，而是少数高误差站点的数据映射/别名字典/功率列来源需要人工核查。