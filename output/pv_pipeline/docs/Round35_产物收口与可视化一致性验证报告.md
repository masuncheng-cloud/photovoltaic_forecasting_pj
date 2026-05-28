# Round35 产物收口与可视化一致性验证报告
**生成时间**: 2026-05-28 21:35

## 校验结果
| 状态 | 数量 |
|------|------|
| PASS | 14 |
| FAIL | 0 |
| WARN | 0 |

## 逐项检查结果
| # | 状态 | 检查项 | 说明 |
|---|------|--------|------|
| 1 | ✓ PASS | C1: Round34 预测文件存在且可读 | 1,172,180 行, 28 列 |
| 2 | ✓ PASS | C2: power_pred_final 存在 | 1,172,180 个非空值 |
| 3 | ✓ PASS | C3: Round34 指标文件存在 | 8 个文件全部存在 |
| 4 | ✓ PASS | C4: city_hourly_nrmse 使用城市总出力口径 | 14 行, NRMSE=0.55%~6.66% |
| 5 | ✓ PASS | C5: typical_sites 无站点重复 | 14 行, {'预测最好': np.int64(5), '预测最差': np.int64(5), '相对正确': np.int64(4)} |
| 6 | ✓ PASS | C6: dashboard pred/actual 一致 | 68/68 PASS, max_pred=0.00e+00, max_actual=0.00e+00 |
| 7 | ✓ PASS | C7: 报告路径统一 | Markdown 报告统一输出到 output/pv_pipeline/docs/ |
| 8 | ✓ PASS | C8: 项目报告含 118/68/14/50 说明 | 全部登记站点118 / 有test结果68 / 正常可排名14 / 无测试预测结果50 |
| 9 | ✓ PASS | C9: 历史口径 NRMSE 不作核心指标 | 未在正文中发现 0.3365% |
| 10 | ✓ PASS | C10: Git 不追踪 pkl/joblib/parquet | 0 个 |
| 11 | ✓ PASS | C10: Git 不追踪 site_series/city_series JSON | 0 个（已从 git 移除并写入 .gitignore） |
| 12 | ✓ PASS | C10: Git 不追踪 tables/ 输出 | 0 个 |
| 13 | ✓ PASS | C11: 可视化默认不含 future | 已检查 3 个文件，无 future 数据 |
| 14 | ✓ PASS | C12: 站点数量自洽 | 全部=118 = 有test=68+无test=50 |

## 结论
**全部检查通过**：Round35 产物收口与可视化一致性验证合格。
