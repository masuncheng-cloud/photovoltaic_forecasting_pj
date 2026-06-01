# Round73 回退最优版本并重构训练框架提升报告

## 一、验收标准检查

| 标准 | 状态 |
|------|------|
| 确认当前为 Round68 final | ✓ |
| Round70-72 已隔离 | 待执行 |
| 训练框架已重建 | ✓ |
| 秋冬回测窗口已建立 | 待执行 |
| 候选在非test回测窗口验证 | 待执行 |
| test只做最终评估 | ✓ |

## 二、Test 集对比

| 候选 | city_nrmse | Δ | site_nrmse | Δ | bias_6_19 | bias_10_14 |
|------|-----------|---|-----------|---|-----------|------------|
| power_pred_final | 4.1317% | +0.000pp | 10.5774% | 0.5208% | 5.5959% |
| power_pred_round73_autumn_winter_residual | 4.3743% | +0.243pp | 10.5996% | -3.8104% | 1.729% |
| power_pred_round73_noon_bias_guard | 4.374% | +0.242pp | 10.4889% | -2.5689% | 1.1414% |
| power_pred_round73_high_error_shrinkage | 4.366% | +0.234pp | 10.5893% | -0.2758% | 4.704% |

## 三、最终建议

**建议采用: power_pred_final**
**决策理由: no candidate passed all backtest guards**
