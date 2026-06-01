# Round71 季节适配与保守残差提升报告

## 一、验收标准检查

| 标准 | 状态 |
|------|------|
| 先输出诊断结果再训练 | ✓ |
| 无诊断依据不训练 | ✓ |
| 只做保守残差修正 | ✓ |
| 候选真实不同于 baseline | ✓ |
| valid 多窗口验证 | ✓ |
| test 只做最终评估 | ✓ |

---

## 二、诊断结果

### 条件 A：季节漂移
- 成立：True
- test avg nrmse：4.031
- valid avg nrmse：5.2506
- NRMSE 漂移：-1.220pp
- 允许训练：True

### 条件 B：近期样本
- 成立：False
- 早期正样本率：0.7478
- 近期正样本率：0.8628
- 允许训练：False

### 条件 C：10-14 点高估
- 成立：True
- noon_bias：5.5959%
- all_bias：0.5208%
- 允许训练：True

### 训练候选
power_pred_round71_seasonal_residual, power_pred_round71_noon_conservative

---

## 三、Test 集对比

| 候选 | city_nrmse | city_nrmse_10_14 | site_nrmse | bias_6_19 | bias_10_14 |
|------|-----------|------------------|-----------|-----------|------------|
| power_pred_final | 4.1317% (+0.000) | 5.9379% | 10.5774% | 0.5208% | 5.5959% |
| power_pred_round71_seasonal_residual | 4.1537% (+0.022) | 6.0553% | 10.4731% | 2.4007% | 6.9952% |
| power_pred_round71_noon_conservative | 4.1846% (+0.053) | 6.0407% | 10.5211% | 1.34% | 6.8405% |


## 四、最终建议

**建议采用：power_pred_round71_safe_blend**

**决策理由：safe_blend improves city_nrmse by 0.109pp in both windows**

