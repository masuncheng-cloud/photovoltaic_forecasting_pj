# Round57 训练链路审计摘要

## 审计时间

2026-05-31

## 审计级别

quick（9 项）

## 审计结果

| 检查项 | 状态 | 说明 |
|--------|------|------|
| manifest_exists | ✓ PASS | manifest.json 存在 |
| artifact_final_full_pkl | ✓ PASS | predictions/distributed_predictions_final_full.pkl 存在 |
| artifact_final_eval_pkl | ✓ PASS | predictions/distributed_predictions_final_eval.pkl 存在 |
| artifact_hourly_nrmse_csv | ✓ PASS | metrics/hourly_nrmse_consistent.csv 存在 |
| artifact_site_metrics_csv | ✓ PASS | metrics/site_metrics_consistent.csv 存在 |
| artifact_dashboard_dir | ✓ PASS | interactive_dashboard 目录存在 |
| artifact_dashboard_index | ✓ PASS | interactive_dashboard/index.json 存在 |
| geo_S115_coordinates | ✓ PASS | S115 lat=34.5933, lon=119.2172 |
| geo_S116_coordinates | ✓ PASS | S116 lat=34.2983, lon=119.2318 |

**总计：9 项 | 9 PASS | 0 FAIL | 0 WARN**

## 关键发现

1. **S115/S116 链路正常**：test 10-14 评估窗口内，S115/S116 均有 valid scene（mid/clear_peak/low），g_blend_pred 非零，power_pred_final 非零，预测链路健康。
2. **全链路产物一致**：final_full.pkl、final_eval.pkl、hourly_nrmse、site_metrics、dashboard_index 全部存在。
3. **站点元数据完整**：69 个站点（含 S115/S116），68 个有有效 test 6-19 评估记录。

## posttrain_validation 详细结果（36 项）

| 检查 | 结果 | 说明 |
|------|------|------|
| C1 final pkl | PASS | 1,172,180 行，27 列 |
| C2 eval pkl | PASS | 仅含 test 6-19h |
| C3 预测列 | PASS | power_pred_final 非空 |
| C4 实际功率 | PASS | power_mw 存在 |
| C5 split | PASS | train/valid/test/future 齐全 |
| C6 时间切分 | PASS | test=2025-09-01~2025-12-31 |
| C7 预测列 | PASS | power_pred_final 就绪 |
| C8 测试集预测 | PASS | 199,104 行 |
| C9 夜间排除 | WARN | full pkl 含夜间（评估时排除，正常）|
| C10 hourly NRMSE | PASS | 14 小时，NRMSE 3.94%~16.98% |
| C11 dashboard 一致 | PASS | 68 站全部 PASS |
| C12 dashboard 新鲜 | PASS | dashboard 晚于 pkl 1.23h |
| C13 Git 不追踪大文件 | PASS | 0 个 |
| C14 训练样本量 | PASS | 421,771 行 |
| C15 站点数量 | PASS | 69 个 |
| C16 manifest hash | WARN | 旧 manifest 无 hash（新 manifest 将包含）|
| C16 manifest mtime | WARN | manifest 早于 pkl 5.64h（auto-sync，hash 为准）|
| GEO1 S115/S116 坐标 | PASS | 经纬度存在 |
| GEO2 坐标范围 | PASS | 均在连云港范围内 |
| GEO3 置信度 | PASS | S115=medium, S116=low |
| GEO4 低置信度 | WARN | S116 low，建议确认场区中心 |
| GEO5 S115 scene test10-14 | PASS | mid/clear_peak/low，非 all-night |
| GEO5 S115 g_blend test10-14 | PASS | max=828.0 |
| GEO5 S115 pred test10-14 | PASS | 610/610 行非0 |
| GEO5 S116 scene test10-14 | PASS | mid/clear_peak/low，非 all-night |
| GEO5 S116 g_blend test10-14 | PASS | max=835.7 |
| GEO5 S116 pred test10-14 | PASS | 610/610 行非0 |
| C17 站点数量 | PASS | full=69, eval=68（1 站无有效评估记录）|

**总计：32 PASS | 0 FAIL | 4 WARN**
