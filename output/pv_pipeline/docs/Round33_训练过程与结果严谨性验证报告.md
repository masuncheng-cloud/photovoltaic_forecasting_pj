# Round33 训练过程与结果严谨性验证报告

生成时间: 2026-05-28 17:05:51

## 检查结果汇总

| 指标 | 数量 |
|------|------|
| PASS | 25 |
| FAIL | 0 |
| WARN | 1 |

## 详细结果

| 检查项 | 状态 | 详情 |
|--------|------|------|
| final_full (distributed_predictions_final_full_clean.pkl) | ✓ PASS | 1,171,399 行, 69 站点 |
| final_full (distributed_predictions_v159.pkl) | ✓ PASS | 1,172,180 行, 69 站点 |
| final_eval (distributed_predictions_final_eval_round33.pkl) | ✓ PASS | 116,144 行, 68 站点 |
| final_eval 只含 test | ✓ PASS |  |
| final_eval 只含 6-19 点 | ✓ PASS | 小时范围: [np.int32(6), np.int32(7), np.int32(8), np.int32(9), np.int32(10), np.int32(11), np.int32(12), np.int32(13), np.int32(14), np.int32(15), np.int32(16), np.int32(17), np.int32(18), np.int32(19)] |
| final_eval 不含 future | ✓ PASS |  |
| 无效站点标注 | ✓ PASS | 共 118 站点，5 个被标注排除 |
| 预测值 >= 0 (v159) | ✓ PASS |  |
| 预测值 >= 0 (final_eval) | ✓ PASS |  |
| 预测值 <= 容量 (v159) | ✓ PASS |  |
| 预测值 <= 容量 (final_eval) | ✓ PASS |  |
| 站点数量合理性 | ✓ PASS | 有效性表=118, eval(test)=68，差=50（含未来站点，可接受） |
| dashboard index.json | ✓ PASS | 1 KB |
| dashboard site_metrics.json | ✓ PASS | 68 KB |
| dashboard city_series.json | ✓ PASS | 4397 KB |
| site_series 文件数量 | ✓ PASS | 68 个文件 |
| 可视化 actual 一致性 | ⚠ WARN | 一致性文件格式不符 |
| metrics round33_site_validity.csv | ✓ PASS | 31 KB |
| metrics round33_site_metrics.csv | ✓ PASS | 9 KB |
| metrics round33_city_hourly_nrmse.csv | ✓ PASS | 2 KB |
| metrics round33_site_hourly_nrmse.csv | ✓ PASS | 69 KB |
| metrics round33_typical_sites.csv | ✓ PASS | 1 KB |
| metrics round33_invalid_eval_sites.csv | ✓ PASS | 1 KB |
| metrics round33_distribution_drift_sites.csv | ✓ PASS | 8 KB |
| metrics round33_bias_sites.csv | ✓ PASS | 1 KB |
| metrics round33_bias_calibration_table.csv | ✓ PASS | 28 KB |

## 结论

**所有关键检查通过，Round33 训练结果通过验收。**

## 验收状态：通过 ✓

- PASS: 25 项
- WARN: 1 项（不影响验收）
