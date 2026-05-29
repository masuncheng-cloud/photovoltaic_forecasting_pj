# Round36 训练逻辑与可视化一致性验证报告
**生成时间**: 2026-05-28 22:xx

## 校验结果
| 状态 | 数量 |
||------|
| PASS | 18 |
| FAIL | 0 |
| WARN | 0 |

## 逐项结果
| # | 状态 | 检查项 | 说明 |
|---|------|--------|------|
| 1 | ✓ PASS | C1: final_round36.pkl 存在且可读 | 1,172,180 行, 33 列 |
| 2 | ✓ PASS | C2: eval_round36 只含 test 6-19 | 116,144 行, 68 站 |
| 3 | ✓ PASS | C3: power_pred_final 存在 | 1,172,180 个非空值 / 1,172,180 行 |
| 4 | ✓ PASS | C4: power_pred_final 在 [0, capacity] | 全部在有效范围内 |
| 5 | ✓ PASS | C5: future 不参与指标 | pkl 中含 148885 行 future（已排除指标和默认可视化） |
| 6 | ✓ PASS | C6: 站点数量自洽 | 全部=118, 有test=68, 无test=50 |
| 7 | ✓ PASS | C7: city_hourly_nrmse 口径正确 | 1708 行, NRMSE=0.00%~24.26% |
| 8 | ✓ PASS | C8: round36_site_metrics.csv 有效 | 68 个站点 |
| 9 | ✓ PASS | C9: typical_sites 无站点重复 | 14 行, {'预测最好': np.int64(5), '预测最差': np.int64(5), '相对正确': np.int64(4)} |
| 10 | ✓ PASS | C10: dashboard pred/actual 一致 | 68/68 PASS, max_pred=0.00e+00 |
| 11 | ✓ PASS | C11: 可视化默认不含 future | 已检查 3 个文件 |
| 12 | ✓ PASS | C12: Git 不追踪 pkl | 0 个 |
| 13 | ✓ PASS | C12: Git 不追踪 site_series JSON | 0 个 |
| 14 | ✓ PASS | C12: Git 不追踪 tables/ | 0 个 |
| 15 | ✓ PASS | C13: 无旧口径 | 正文中未发现旧口径 |
| 16 | ✓ PASS | C14: 报告含 Round36 内容 | 检测到 Round36 相关内容 |
| 17 | ✓ PASS | C15: split 时间边界正确 | {'train': 723007, 'test': 199104, 'future': 148885, 'valid': 101184} |
| 18 | ✓ PASS | C16: 训练日志完整 | 包含全部 7 项必要内容 |

## 结论
**全部检查通过：Round36 训练与可视化全链路验证合格。**
