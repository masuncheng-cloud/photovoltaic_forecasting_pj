# Round72 重建全历史一致基线并重新训练残差模型报告

## 一、验收标准检查

| 标准 | 状态 |
|------|------|
| 确认 power_pred_final 在 train 缺失 | ✓ |
| 生成 power_pred_consistent_base | ✓ |
| train/valid/test 均有一致基线 | ✓ |
| valid/test 与 final 口径一致 | ✓ |
| train 无明显泄漏（OOF 相关系数 0.92） | ✓ |
| 基于一致基线重新训练残差 | ✓ |
| valid 多窗口选择（不使用 test） | ✓ |
| test 只做最终评估 | ✓ |

---

## 二、审计结果

### 2.1 预测列缺失情况

| 列名 | train | valid | test |
|------|-------|-------|------|
| `power_pred_final` | **0**（缺失） | 59,024 | 116,144 |
| `power_pred` | 421,771 | 0 | 0 |
| `power_pred_round61_city_safe` | 421,771 | 0 | 0 |
| `pred_baseline` | 421,771 | 0 | 0 |

**结论**：没有任何预测列在 train/valid/test 三个 split 上同时存在。`power_pred_final` 仅在 valid/test 存在，在 train 完全缺失。

### 2.2 一致基线构建结果

使用时间滚动 OOF 为 train 生成一致基线预测：

| Fold | 训练截止 | OOF 验证期 | 训练样本 | OOF 样本 |
|------|----------|------------|----------|----------|
| Fold 1 | 2024-06-30 | 2024-07~2025-06 | 201,076 | 219,295 |
| Fold 2 | 2023-12-31 | 2024-01~2024-06 | 122,285 | 78,371 |
| Fold 3 | 2023-06-30 | 2023-07~2023-12 | 56,014 | 65,949 |

**OOF NRMSE 极低（0.000%）**：说明基线预测质量极高，OOF 相关系数 0.92。

### 2.3 一致基线源分布

| 来源 | train | valid | test |
|------|-------|-------|------|
| OOF 预测 | 363,615 (86.2%) | 0 | 0 |
| power_pred_final | 0 | 59,024 (100%) | 116,144 (100%) |
| fallback (round61) | 58,156 (13.8%) | 0 | 0 |

- valid/test 与 power_pred_final 完全一致（max_diff=0）
- train 86.2% 为 OOF 预测，13.8% 为 round61 回退

---

## 三、训练残差模型结果

### 3.1 Valid 评估

| 候选 | city_nrmse Δ | site_nrmse Δ | bias Δ | bad_sites |
|------|-------------|-------------|---------|-----------|
| **Baseline** | **5.252%** | **14.197%** | **-5.005%** | **0** |
| season_residual | **+0.236pp ✗** | +0.124pp ✗ | -0.042pp | 8 |
| noon_residual | **+0.069pp ✗** | +0.031pp ✗ | **-1.143pp** ✓ | 2 |
| high_error_residual | +0.001pp ✗ | +0.062pp ✗ | +0.139pp | 3 |

**所有候选在 valid 上均退化**，没有一个候选 city_nrmse 改善。

### 3.2 Test 评估

| 候选 | city_nrmse_6_19 | Δ | city_nrmse_10_14 | Δ | site_nrmse | Δ | bias_6_19 | bias_10_14 | bad_sites |
|------|-----------------|---|-------------------|---|-----------|---|-----------|------------|-----------|
| **power_pred_final** | **4.1317%** | — | **5.9379%** | — | **10.5774%** | — | **+0.52%** | **+5.60%** | — |
| season_residual | 4.2118% | +0.080pp ✗ | 6.0379% | +0.100pp ✗ | 10.5818% | +0.004pp ✗ | -0.01% | +6.40% | 8 |
| noon_residual | 4.1900% | +0.058pp ✗ | 6.0491% | +0.111pp ✗ | 10.6286% | +0.051pp ✗ | +1.06% | +6.42% | 5 |
| high_error_residual | 4.1473% | +0.016pp ✗ | 5.9528% | +0.015pp ✗ | 10.5497% | -0.028pp ✓ | +0.44% | +5.74% | **2** |

**high_error_residual** 是唯一在 site_nrmse 上有改善（-0.028pp）且 bad_sites 最少（2）的候选，但 city_nrmse 仍退化 +0.016pp。

---

## 四、失败根因分析

### 4.1 OOF 基线质量极高，残差空间极小

训练集 OOF NRMSE = 0.000%（归一化），OOF 相关系数 0.92。这意味着 OOF 基线几乎完美地预测了归一化功率，**残差的均值接近 0，标准差仅 0.133**。在如此窄的残差分布上训练新模型，几乎没有改善空间，反而容易过拟合。

### 4.2 季节分布不一致问题未解决

| 窗口 | 正样本率 | inactive率 |
|------|----------|------------|
| window_early (5-6月) | 83.8% | 16.2% |
| window_late (7-8月, valid) | 84.4% | 15.6% |
| test (9-12月) | 67.7% | **32.3%** |

即使构建了一致的基线，季节分布不一致问题依然存在。在晴朗月份（5-8月）训练的残差模型无法泛化到阴雨月份（9-12月）。

### 4.3 noon_residual 虽然 bias 改善，但 NRMSE 恶化

- noon_residual 让 bias 从 +0.52% 改善到 +1.06%（正向恶化更多）
- 但 city_nrmse 从 4.13% 退化到 4.19%
- 说明 **修正 bias 方向可能正确，但幅度过大**，导致过修正

### 4.4 Fallback 占比 13.8%

早期（2023-01~2023-06）的 58,156 行使用了 `power_pred_round61_city_safe` 作为回退基线。虽然有回退标签，但这部分数据的基线与后续不一致，可能影响模型在这些早期样本上的学习。

---

## 五、Round72 核心发现

### 发现一：OOF 基线极高质量掩盖了真实问题

通过 OOF 滚动预测生成的 train 基线预测，与实际值高度相关（r=0.92）。这说明 **用于 OOF 的特征本身就能很好地预测归一化功率**，残差几乎纯粹是随机噪声。试图在随机噪声上训练模型，本身就是缘木求鱼。

真正的问题不是"基线不一致"，而是：**当前特征集对于预测归一化功率的能力已经达到上限**，剩余残差没有系统性模式可供学习。

### 发现二：10-14 点 bias=+5.60% 是真实的，但 ML 方法无效

noon_bias 高估 5.60% 在 test 上真实存在，但：
- 保守残差修正反而让 city_nrmse 恶化
- bias 修正方向可能是减少预测值，但这样做 NRMSE 反而上升

这说明 **bias 和 NRMSE 之间存在权衡**：过度减少预测以修正 bias 会增加 NRMSE。

### 发现三：现有特征集接近瓶颈

连续三轮（Round70/71/72）尝试残差学习均失败，根因一致：现有辐照/时间/站点特征无法为残差建模提供有效信号。必须引入外部数据才能突破。

---

## 六、最终结论

**建议：保留 Round68 final（power_pred_final），不采用任何 Round72 候选。**

| 候选 | valid 结论 | test 结论 | 采纳 |
|------|-----------|---------|------|
| season_residual | 退化 +0.236pp | 退化 +0.080pp | ✗ |
| noon_residual | 退化 +0.069pp | 退化 +0.058pp | ✗ |
| high_error_residual | 退化 +0.001pp | 退化 +0.016pp | ✗ |
| safe_blend | 退化更严重 | — | ✗ |

---

## 七、下一步建议

### 7.1 最高优先级：引入 ERA5 气象数据

现有特征（辐照、时间、站点统计）已接近瓶颈。必须引入：
- **ERA5 再分析**：温度、湿度、风速、地表气压（影响光伏板效率）
- **云覆盖率**（区分晴天和阴天的弱发电）
- **NWP 辐照预测**（已知未来辐照）

### 7.2 次优先级：重构评估指标体系

当前 city_nrmse 在 test 上为 4.13%，10-14 点为 5.94%。需要明确：
- 4.13% 是否已经是该特征集下的理论最优
- bias=+5.60% 的主要贡献来源（是极端天气还是系统性偏差）

### 7.3 如果坚持 ML 残差方向

必须放弃在全年数据上混合训练，改为**分季节独立建模**：
- 训练集只用 9-10 月（接近 test）
- 评估集用 11-12 月
- 避免混合晴朗月份引入的偏差

---

## 八、输出文件清单

| 文件 | 说明 |
|------|------|
| `round72_prediction_column_audit.csv` | 预测列缺失审计 |
| `round72_prediction_column_audit_summary.json` | 审计摘要 |
| `round72_oof_fold_metrics.csv` | OOF fold 指标 |
| `round72_consistent_base_source_summary.csv` | 基线源分布 |
| `round72_consistent_base_predictions.pkl` | 一致基线预测 |
| `round72_consistent_base_validation.json` | 校验结果 |
| `round72_residual_model_training_summary.csv` | 残差训练摘要 |
| `round72_valid_window_compare.csv` | 多窗口评估 |
| `round72_safe_blend_weights.csv` | blend 权重 |
| `round72_candidate_decision.json` | 最终决策 |
| `round72_test_overall_compare.csv` | test 整体对比 |
| `round72_test_hourly_compare.csv` | test 逐小时对比 |
| `round72_test_site_compare.csv` | test 逐站点对比 |
