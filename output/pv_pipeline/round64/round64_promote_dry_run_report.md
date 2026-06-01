# Round64 候选正式升级 Dry-Run 报告

**日期**: 2026-06-01 14:50:12
**模式**: dry-run

## 执行计划

| 步骤 | 动作 | 源文件 | 目标文件 | 是否覆盖 | 备注 |
|---|---|---|---|---|---|
| 1 | backup | output/pv_pipeline/predictions/distributed_predictions_final_full.pkl | backups/distributed_predictions_final_full_before_round64_20260601_145012.pkl | 否 | 备份当前正式 full pkl (时间戳: 20260601_145012) |
| 1 | backup | output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl | backups/distributed_predictions_final_eval_before_round64_20260601_145012.pkl | 否 | 备份当前正式 eval pkl (时间戳: 20260601_145012) |
| 2 | write | round64/round64_candidates.pkl | output/pv_pipeline/predictions/distributed_predictions_final_full.pkl | 是 | 将 power_pred_round64_safe 写入 power_pred_final，输出为 full pkl |
| 2 | write | round64/round64_candidates.pkl | output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl | 是 | 只保留 valid + test 行，写入 eval pkl |
| 3 | update_manifest | manifest.json | output/pv_pipeline/manifest.json | 是 | 更新 manifest.json 的 SHA256 hash 和 final_prediction_column |
| 4 | run_script | - | scripts/export_interactive_dashboard_data.py | 否 | 重新导出正式 interactive_dashboard |
| 5 | run_script | - | scripts/posttrain_validation.py | 否 | 重新运行 posttrain validation |

## 升级条件验证

- 候选文件存在: ✅ (output/pv_pipeline/round64/round64_candidates.pkl)
- power_pred_round64_safe 列存在: ✅
- 正式文件可备份: ✅ (output/pv_pipeline/predictions/distributed_predictions_final_full.pkl)

## 注意事项

- apply 时会直接覆盖正式 pkl，请确保已备份。
- 升级后需要重新运行 posttrain validation。
- 升级后需要重新导出 interactive_dashboard。
- 本次升级后，power_pred_final 将使用 Round64 safe 融合结果。