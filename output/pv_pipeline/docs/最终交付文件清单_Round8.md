# 最终交付文件清单 Round8

> 本清单用于区分正式交付文件、诊断保留文件和历史归档文件。

| 类别 | 文件 | 用途 | 是否必须 | 是否存在 | 大小MB |
|---|---|---|---|---|---:|
| 正式交付-预测表 | `output/pv_pipeline/tables/distributed_predictions_final_eval.pkl` | 最终测试集评估表，所有最终指标唯一来源 | 是 | 是 | 11.763 |
| 正式交付-预测表 | `output/pv_pipeline/tables/distributed_predictions_final_full.pkl` | 最终全量预测表，包含 train/valid/test/future | 是 | 是 | 192.121 |
| 正式交付-安全基准 | `output/pv_pipeline/tables/distributed_predictions_midday_site_calibrated_eval.pkl` | 10-14 点安全基准 eval | 是 | 是 | 11.763 |
| 正式交付-安全基准 | `output/pv_pipeline/tables/distributed_predictions_midday_site_calibrated_full.pkl` | 10-14 点安全基准 full | 是 | 是 | 192.121 |
| 正式交付-指标 | `output/pv_pipeline/metrics/round7_final_overall_metrics.csv` | 最终整体指标 | 是 | 是 | 0.0 |
| 正式交付-指标 | `output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv` | 6-19 点逐小时站点/城市 NRMSE | 是 | 是 | 0.0 |
| 正式交付-指标 | `output/pv_pipeline/metrics/final_version_selection_by_hour.csv` | 逐小时最终版本选择表 | 是 | 是 | 0.002 |
| 正式交付-指标 | `output/pv_pipeline/metrics/round7_final_metrics_manifest.csv` | final metrics 来源与 hash 清单 | 是 | 是 | 0.001 |
| 正式交付-指标 | `output/pv_pipeline/metrics/round7_final_metrics_summary.json` | final metrics JSON 摘要 | 是 | 是 | 0.001 |
| 正式交付-报告 | `output/pv_pipeline/docs/当前最终结果摘要.md` | 最终结果摘要 | 是 | 是 | 0.008 |
| 正式交付-报告 | `output/pv_pipeline/docs/任务书完成情况_Round7.md` | 任务书对照验收 | 是 | 是 | 0.003 |
| 正式交付-报告 | `output/pv_pipeline/docs/最终交付文件清单_Round8.md` | 最终交付文件说明 | 否 | 是 | 0.003 |
| 诊断保留 | `output/pv_pipeline/metrics/round6_watch_site_diagnosis.csv` | 高误差重点站点诊断（S012/S055/S050/S032） | 是 | 是 | 0.001 |
| 诊断保留 | `output/pv_pipeline/metrics/round6_site_capacity_mapping_diagnosis.csv` | 容量/映射诊断 | 是 | 是 | 0.007 |
| 诊断保留 | `output/pv_pipeline/metrics/round6_midday_bias_stability_summary.csv` | 正午偏差稳定性诊断 | 是 | 是 | 0.067 |
| 诊断保留 | `output/pv_pipeline/metrics/round6_stable_extreme_bias_candidates.csv` | 稳定极端偏差候选（仅诊断，不参与 final） | 是 | 是 | 0.001 |
| 诊断保留 | `output/pv_pipeline/metrics/round6_flagged_site_diagnosis.csv` | 高误差站点标记诊断 | 是 | 是 | 0.002 |
| 诊断保留 | `output/pv_pipeline/metrics/midday_site_calibration_params.csv` | MiddaySiteCalibrated 校准参数 | 是 | 是 | 0.023 |
| 诊断保留 | `output/pv_pipeline/metrics/midday_worst_site_hours_final.csv` | 最差站点小时诊断 | 是 | 是 | 0.02 |
| 流程验收 | `output/pv_pipeline/metrics/round7_end_to_end_deliverables_check.csv` | 端到端交付物检查 | 是 | 是 | 0.001 |
| 流程验收 | `output/pv_pipeline/metrics/round7_taskbook_compliance.csv` | 任务书对照 CSV | 是 | 是 | 0.002 |

## 交付说明

1. 正式指标以 `distributed_predictions_final_eval.pkl` 为唯一来源。
2. `archive_round7/` 中的文件仅用于历史追溯，不作为最终结果。
3. Round5/Round6 的历史候选未进入 final，不应在正式汇报中作为有效模型结果。
4. 后续提升精度应优先核查 S012/S055/S050/S032 的功率列映射和别名字典。