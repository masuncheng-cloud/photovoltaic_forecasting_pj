# Round36 训练前数据审计报告
**生成时间**: 2026-05-28 21:58

## 审计结果
| 状态 | 数量 |
|------|------|
| PASS | 6 |
| FAIL | 1 |
| WARN | 4 |

## 逐项结果
| # | 状态 | 检查项 | 说明 |
|---|------|--------|------|
| 1 | ✓ PASS | power_clean 无重复 | 2,874,864 行无重复（power_alias+time） |
| 2 | ⚠ WARN | power_long_raw 存在 | 文件不存在，跳过 |
| 3 | ✓ PASS | 无负功率 | 全部 >= 0 |
| 4 | ⚠ WARN | 无严重超容量 | 187 行 (0.0065%), max_ratio=1.020, max_diff=0.160MW （功率取整浮点微小偏差，可接受） |
| 5 | ✓ PASS | capacity_mw > 0 | 118 个站点全部 > 0 |
| 6 | ✓ PASS | 站点名非空 | 118 个站点全部有名称 |
| 7 | ✗ FAIL | 经纬度完整 | lat 缺 5 个, lon 缺 5 个 |
| 8 | ✓ PASS | 站点容量唯一 | 118 个站点各只有一个容量 |
| 9 | ⚠ WARN | 时间划分检查 | distributed_train_table_v159.pkl 不存在 |
| 10 | ⚠ WARN | 特征泄漏检查 | distributed_train_table_v159.pkl 尚不存在，将在训练后检查 |
| 11 | ✓ PASS | final 预测文件 | final: 1,172,180 行, eval: 116,144 行，字段完整 |

## 结论
**1 项 FAIL，必须修复后才能继续训练。**
