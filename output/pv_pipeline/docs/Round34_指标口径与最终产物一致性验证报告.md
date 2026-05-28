# Round34 指标口径与最终产物一致性验证报告
生成时间: 2026-05-28
## 校验结果
| 状态 | 数量 |
|------|------|
| PASS | 12 |
| FAIL | 0 |
| WARN | 0 |

## 逐项检查结果
| # | 状态 | 检查项 | 说明 |
|---|------|--------|------|
| 1 | ✓ PASS | C1: final pkl 存在且可读 | 1,172,180 行, 25 列 |
| 2 | ✓ PASS | C2: eval pkl 只含 test 6-19 | 行数=116,144, 站点=68, 小时=[np.int32(6), np.int32(7), np.int32(8), np.int32(9), np.int32(10), np.int32(11), np.int32(12), np.int32(13), np.int32(14), np.int32(15), np.int32(16), np.int32(17), np.int32(18), np.int32(19)] |
| 3 | ✓ PASS | C3: power_pred_final 存在 | 共 1,172,180 个非空值 |
| 4 | ✓ PASS | C4: power_pred_final 范围 [0, capacity_mw] | 无违规 |
| 5 | ✓ PASS | C5: 无test数据站点不标为正常评价 | 共 50 个无test数据站点均已正确标记 |
| 6 | ✓ PASS | C6: site_metrics 站点与 eval pkl 一致 | 68 个站点 |
| 7 | ✓ PASS | C7: city_hourly_nrmse 必要字段与数值合理 | 14 行, NRMSE 范围 2.42%~5.95% |
| 8 | ✓ PASS | C8: typical_sites 无站点重复 | 14 行, {'预测最好': 5, '预测最差': 5, '相对正确': 4} |
| 9 | ✓ PASS | C9: 全市 NRMSE 口径一致 | 10-14 点平均 NRMSE = 5.78%（CSV 已是%，不乘100） |
| 10 | ✓ PASS | C10: 可视化 site_series JSON 可读 | 已检查 5 个文件 |
| 11 | ✓ PASS | C11: dashboard actual 与 power_clean 一致 | max_diff=8.88e-16 |
| 12 | ✓ PASS | C12: 站点数量自洽 | 全部=118 = 有test=68+无test=50, 有效分类和=68 |

## 结论
**全部检查通过**：Round34 口径一致性验证合格。
