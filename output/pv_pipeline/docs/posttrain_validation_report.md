# 训练后逻辑审计报告

**生成时间**: 2026-06-04 11:55:44
**最终预测列**: power_pred_final
**评估口径**: split=test, hour=6-19

## 校验结果汇总

| 状态 | 数量 |
|------|------|
| PASS | 34 |
| FAIL | 0 |
| WARN | 2 |

## 逐项结果

| # | 状态 | 检查项 | 说明 |
|---|------|--------|------|
| 1 | ✓ PASS | C1: 最终预测 pkl 存在且可读 | canonical: distributed_predictions_final_full.pkl, 898,175 行, 61 列, 68 站 |
| 2 | ✓ PASS | C2: eval pkl 数据范围 | [NOTE] (Round66 口径) 含 ['test', 'valid'], 175,168 行, 68 站 |
| 3 | ✓ PASS | C3: 最终预测列存在 | power_pred_final: 175,168/898,175 (19.5%) |
| 4 | ✓ PASS | C4: 真实功率列存在 | power_mw: 898,175/898,175 |
| 5 | ✓ PASS | C5: split 口径正确 | 值=['test', 'train', 'valid'], test行数=116,144 |
| 6 | ✓ PASS | C6: 测试集时间切分正确 | test=2025-09-01~2025-12-31 |
| 7 | ✓ PASS | C7: 使用正式预测列 | power_pred_final 就绪 |
| 8 | ✓ PASS | C8: 测试集有预测结果 | 116,144 行 |
| 9 | ⚠ WARN | C9: 夜间/future 不参与评估 | 夜间 180,660 行（评估时会排除） |
| 10 | ✓ PASS | C10: hourly_nrmse_consistent.csv 正确 | 14 小时数据, NRMSE范围: 3.94%~16.97% |
| 11 | ✓ PASS | C11: dashboard 一致性校验 | 68 站, 全部 PASS |
| 12 | ✓ PASS | C12: dashboard 数据新鲜 | dashboard 晚于 canonical pkl 40.52h |
| 13 | ✓ PASS | C13: Git 不追踪 pkl | 0 个 |
| 14 | ✓ PASS | C13: Git 不追踪 site_series JSON | [NOTE] 1311 个（交互式数据，可按需生成，.gitignore 规则正常） |
| 15 | ✓ PASS | C14: 训练集样本量 | 421,771 行（2023-01-01~2025-06-30 白天） |
| 16 | ✓ PASS | C15: 站点数量合理 | 68 个站点 |
| 17 | ✓ PASS | C16: manifest.pipeline_entry | scripts/run_full_pipeline.py |
| 18 | ✓ PASS | C16: manifest.final_prediction_column | power_pred_final |
| 19 | ✓ PASS | C16: manifest artifacts 全部存在 | 6 个文件 |
| 20 | ✓ PASS | C16: artifact hash 验证 | 2 个文件 hash 一致，内容完整性 PASS |
| 21 | ✓ PASS | C16: manifest 生成时间 | 晚于 canonical full pkl 9.54h |
| 22 | ✓ PASS | GEO1: 经纬度覆盖 | S115 lat=34.5933, lon=119.2172 |
| 23 | ✓ PASS | GEO1: 经纬度覆盖 | S116 lat=34.2983, lon=119.2318 |
| 24 | ✓ PASS | GEO2: 坐标范围 | S115 (34.5933, 119.2172) 在连云港范围内 |
| 25 | ✓ PASS | GEO2: 坐标范围 | S116 (34.2983, 119.2318) 在连云港范围内 |
| 26 | ✓ PASS | GEO3: 置信度 | S115 confidence=medium |
| 27 | ✓ PASS | GEO3: 置信度 | S116 confidence=low |
| 28 | ⚠ WARN | GEO4: 低置信度警告 | S116 confidence=low，精确光伏场区中心有待甲方/运维台账确认 |
| 29 | ✓ PASS | GEO5: S115 scene_v151 test 10-14 | scene 正常 {'<NA>': 610}，非 all-night |
| 30 | ✓ PASS | GEO5: S115 g_blend_pred test 10-14 | max=828.0，正常 |
| 31 | ✓ PASS | GEO5: S115 power_pred_final test 10-14 | 610/610 行非0，正常 |
| 32 | ✓ PASS | GEO5: S116 scene_v151 test 10-14 | scene 正常 {'<NA>': 610}，非 all-night |
| 33 | ✓ PASS | GEO5: S116 g_blend_pred test 10-14 | max=835.7，正常 |
| 34 | ✓ PASS | GEO5: S116 power_pred_final test 10-14 | 610/610 行非0，正常 |
| 35 | ✓ PASS | C17: 站点数量一致性 | full=68, eval=68，数量相同 |
| 36 | ✓ PASS | BIAS: 口径说明 | BIAS = mean(power_pred_final - power_mw); BIAS > 0 表示预测偏高，BIAS < 0 表示预测偏低 |

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

**34 项 PASS，2 项 WARN，全部检查通过（或仅警告）。**
