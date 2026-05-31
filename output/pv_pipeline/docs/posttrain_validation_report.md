# 训练后逻辑审计报告

**生成时间**: 2026-05-31 20:31:05
**最终预测列**: power_pred_final
**评估口径**: split=test, hour=6-19

## 校验结果汇总

| 状态 | 数量 |
|------|------|
| PASS | 21 |
| FAIL | 5 |
| WARN | 2 |

## 逐项结果

| # | 状态 | 检查项 | 说明 |
|---|------|--------|------|
| 1 | ✓ PASS | C1: 最终预测 pkl 存在且可读 | canonical: distributed_predictions_final_full.pkl, 1,172,180 行, 23 列, 69 站 |
| 2 | ✓ PASS | C2: eval pkl 数据范围正确 | (canonical) 仅含 test 6-19h, 116,144 行, 68 站 |
| 3 | ✓ PASS | C3: 最终预测列存在 | power_pred_final: 1,172,180/1,172,180 (100.0%) |
| 4 | ✓ PASS | C4: 真实功率列存在 | power_mw: 1,172,180/1,172,180 |
| 5 | ✓ PASS | C5: split 口径正确 | 值=['future', 'test', 'train', 'valid'], test行数=199,104 |
| 6 | ✓ PASS | C6: 测试集时间切分正确 | test=2025-09-01~2025-12-31 |
| 7 | ✓ PASS | C7: 使用正式预测列 | power_pred_final 就绪 |
| 8 | ✓ PASS | C8: 测试集有预测结果 | 199,104 行 |
| 9 | ⚠ WARN | C9: 夜间/future 不参与评估 | pkl 中存在夜间和 future 记录（评估时会排除） |
| 10 | ✓ PASS | C10: hourly_nrmse_consistent.csv 正确 | 14 小时数据, NRMSE范围: 2.20%~19.00% |
| 11 | ✓ PASS | C11: dashboard 一致性校验 | 68 站, 全部 PASS |
| 12 | ✓ PASS | C12: dashboard 数据新鲜 | dashboard 晚于 canonical pkl 0.01h |
| 13 | ✓ PASS | C13: Git 不追踪 pkl | 0 个 |
| 14 | ✓ PASS | C13: Git 不追踪 site_series JSON | 0 个 |
| 15 | ✓ PASS | C14: 训练集样本量 | 421,771 行（2023-01-01~2025-06-30 白天） |
| 16 | ✓ PASS | C15: 站点数量合理 | 69 个站点 |
| 17 | ✓ PASS | C16: manifest.pipeline_entry | scripts/run_full_pipeline.py |
| 18 | ✓ PASS | C16: manifest.final_prediction_column | power_pred_final |
| 19 | ✓ PASS | C16: manifest artifacts 全部存在 | 6 个文件 |
| 20 | ✗ FAIL | C16: manifest 生成时间 | 早于 canonical full pkl 4.60h |
| 21 | ✗ FAIL | GEO1: 经纬度覆盖 | S115 lat/lon 仍为空 |
| 22 | ✗ FAIL | GEO1: 经纬度覆盖 | S116 lat/lon 仍为空 |
| 23 | ✗ FAIL | GEO2: 坐标范围 | S115 (nan, nan) 不在连云港 [33.9-35.2N, 118.4-119.9E] |
| 24 | ✗ FAIL | GEO2: 坐标范围 | S116 (nan, nan) 不在连云港 [33.9-35.2N, 118.4-119.9E] |
| 25 | ⚠ WARN | GEO3: 置信度检查 | "None of [Index([114], dtype='int64')] are in the [index]" |
| 26 | ✓ PASS | GEO4: 低置信度警告 | 无站点为 low 置信度 |
| 27 | ✓ PASS | C17: 站点数量一致性 | full=69, eval=68，相差1站 |
| 28 | ✓ PASS | BIAS: 口径说明 | BIAS = mean(power_pred_final - power_mw); BIAS > 0 表示预测偏高，BIAS < 0 表示预测偏低 |

## 训练切分

- train_start: 2023-01-01
- train_end: 2025-06-30
- valid_start: 2025-07-01
- valid_end: 2025-08-31
- test_start: 2025-09-01
- test_end: 2025-12-31
- future_start: 2026-01-01
- future_end: 2026-03-31

## 结论

**5 项 FAIL，不合格。请修复后重新运行训练流程。**
