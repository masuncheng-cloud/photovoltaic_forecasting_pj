# 训练指标口径审计报告

生成时间: 2026-06-04 11:55:36

| 状态 | 检查项 | 说明 |
|------|--------|------|
| PASS | Final pkl exists | /home/ac/data16t/msc/photovoltaic_forecasting_pj/output/pv_pipeline/predictions/distributed_predictions_final_full.pkl |
| PASS | Final pkl readable |  |
| PASS | Has 'split' column |  |
| PASS | Has 'test' split | unique values: ['test', 'train', 'valid'] |
| PASS | No 'future' in split column |  |
| PASS | Has time/hour column |  |
| PASS | Hour range includes canonical 6..19 | actual range: 0..23 |
| PASS | Has canonical 'power_pred_final' |  |
| INFO | 禁止列 'power_pred_cal' 在 pkl 中存在 | 中间列，未在 dashboard/metrics 中使用，审计通过 |
| INFO | 禁止列 'power_pred_raw' 在 pkl 中存在 | 中间列，未在 dashboard/metrics 中使用，审计通过 |
| PASS | Dashboard uses power_pred_final | dashboard prediction_column='power_pred_final' |
| PASS | Dashboard exclude_future=True | include_future=False |
| PASS | Site capacities are positive |  |

汇总: 11 PASS / 0 FAIL
