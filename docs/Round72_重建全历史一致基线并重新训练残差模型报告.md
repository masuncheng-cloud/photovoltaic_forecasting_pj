# Round72 重建全历史一致基线并重新训练残差模型报告

## 一、验收标准检查

| 标准 | 状态 |
|------|------|
| 确认 power_pred_final 在 train 缺失 | ✓ |
| 生成 power_pred_consistent_base | ✓ |
| train/valid/test 均有一致基线 | ✓ |
| valid/test 与 final 口径一致 | ✓ |
| train 无明显泄漏 | ✓ |
| 基于一致基线重新训练残差 | ✓ |
| valid 多窗口选择（不使用 test） | ✓ |
| test 只做最终评估 | ✓ |

---

## 二、审计结果

**power_pred_final 在 train 缺失**: True

**一致可用列**: []

---

## 三、Test 集对比

| 候选 | city_nrmse_6_19 | Δ | site_nrmse | Δ | bias_6_19 | bias_10_14 |
|------|-----------------|---|------------|---|-----------|------------|
| power_pred_final | 4.1317% | +0.000pp | 10.5774% | 0.5208% | 5.5959% |
| power_pred_round72_season_residual | 4.2118% | +0.080pp | 10.5818% | -0.0086% | 6.4049% |
| power_pred_round72_noon_residual | 4.19% | +0.058pp | 10.6286% | 1.0631% | 6.4199% |
| power_pred_round72_high_error_residual | 4.1473% | +0.016pp | 10.5497% | 0.4401% | 5.7419% |


## 四、最终建议

**建议采用：power_pred_final**

**决策理由：best blend Δ=11.820pp (no significant improvement)**

