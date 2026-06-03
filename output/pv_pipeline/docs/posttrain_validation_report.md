# 训练后逻辑审计报告

**生成时间**: 2026-06-03 19:27:14
**最终预测列**: power_pred_final
**评估口径**: split=test, hour=6-19

## 校验结果汇总

| 状态 | 数量 |
|------|------|
| PASS | 32 |
| FAIL | 0 |
| WARN | 3 |

## 逐项结果

| # | 状态 | 检查项 | 说明 |
|---|------|--------|------|
| 1 | ✓ PASS | C1: 最终预测 pkl 存在且可读 | canonical: distributed_predictions_final_full.pkl, 1,172,180 行, 23 列, 69 站 |
| 2 | ✓ PASS | C2: eval pkl 数据范围 | [NOTE] (Round66 口径) 含 ['test'], 116,144 行, 68 站 |
| 3 | ✓ PASS | C3: 最终预测列存在 | power_pred_final: 1,172,180/1,172,180 (100.0%) |
| 4 | ✓ PASS | C4: 真实功率列存在 | power_mw: 1,172,180/1,172,180 |
| 5 | ✓ PASS | C5: split 口径正确 | 值=['future', 'test', 'train', 'valid'], test行数=199,104 |
| 6 | ✓ PASS | C6: 测试集时间切分正确 | test=2025-09-01~2025-12-31 |
| 7 | ✓ PASS | C7: 使用正式预测列 | power_pred_final 就绪 |
| 8 | ✓ PASS | C8: 测试集有预测结果 | 199,104 行 |
| 9 | ⚠ WARN | C9: 夜间/future 不参与评估 | pkl 中存在夜间和 future 记录（评估时会排除） |
| 10 | ✓ PASS | C10: hourly_nrmse_consistent.csv 正确 | 14 小时数据, NRMSE范围: 2.20%~18.16% |
| 11 | ⚠ WARN | C11: dashboard_consistency.csv 存在 | 文件不存在（可能未执行导出） |
| 12 | ✓ PASS | C12: dashboard 数据新鲜 | dashboard 晚于 canonical pkl 0.13h |
| 13 | ✓ PASS | C13: Git 不追踪 pkl | 0 个 |
| 14 | ✓ PASS | C13: Git 不追踪 site_series JSON | [NOTE] 138 个（交互式数据，可按需生成，.gitignore 规则正常） |
| 15 | ✓ PASS | C14: 训练集样本量 | 421,771 行（2023-01-01~2025-06-30 白天） |
| 16 | ✓ PASS | C15: 站点数量合理 | 69 个站点 |
| 17 | ✓ PASS | C16: manifest.pipeline_entry | scripts/run_full_pipeline.py |
| 18 | ✓ PASS | C16: manifest.final_prediction_column | power_pred_final |
| 19 | ✓ PASS | C16: manifest artifacts 全部存在 | 6 个文件 |
| 20 | ✓ PASS | C16: manifest 生成时间 | 晚于 canonical full pkl 0.18h |
| 21 | ✓ PASS | GEO1: 经纬度覆盖 | S115 lat=34.5933, lon=119.2172 |
| 22 | ✓ PASS | GEO1: 经纬度覆盖 | S116 lat=34.2983, lon=119.2318 |
| 23 | ✓ PASS | GEO2: 坐标范围 | S115 (34.5933, 119.2172) 在连云港范围内 |
| 24 | ✓ PASS | GEO2: 坐标范围 | S116 (34.2983, 119.2318) 在连云港范围内 |
| 25 | ✓ PASS | GEO3: 置信度 | S115 confidence=medium |
| 26 | ✓ PASS | GEO3: 置信度 | S116 confidence=low |
| 27 | ⚠ WARN | GEO4: 低置信度警告 | S116 confidence=low，精确光伏场区中心有待甲方/运维台账确认 |
| 28 | ✓ PASS | GEO5: S115 scene_v151 test 10-14 | scene 正常 {'mid': 378, 'clear_peak': 183, 'low': 49}，非 all-night |
| 29 | ✓ PASS | GEO5: S115 g_blend_pred test 10-14 | max=828.0，正常 |
| 30 | ✓ PASS | GEO5: S115 power_pred_final test 10-14 | 610/610 行非0，正常 |
| 31 | ✓ PASS | GEO5: S116 scene_v151 test 10-14 | scene 正常 {'mid': 370, 'clear_peak': 186, 'low': 54}，非 all-night |
| 32 | ✓ PASS | GEO5: S116 g_blend_pred test 10-14 | max=835.7，正常 |
| 33 | ✓ PASS | GEO5: S116 power_pred_final test 10-14 | 610/610 行非0，正常 |
| 34 | ✓ PASS | C17: 站点数量一致性 | full=69, eval=68，相差1站 |
| 35 | ✓ PASS | BIAS: 口径说明 | BIAS = mean(power_pred_final - power_mw); BIAS > 0 表示预测偏高，BIAS < 0 表示预测偏低 |

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

**32 项 PASS，3 项 WARN，全部检查通过（或仅警告）。**
