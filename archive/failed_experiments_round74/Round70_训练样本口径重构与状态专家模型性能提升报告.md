# Round70 训练样本口径重构与状态专家模型性能提升报告

## 一、验收标准检查

| 标准 | 状态 |
|------|------|
| 训练样本统一为 6-19 点 | ✓ |
| 候选列真实不同于 baseline | ✓ |
| active_state_lgb 完成训练并评估 | ✓ |
| noon_bias_lgb 完成训练并评估 | ✓ |
| high_error_expert 完成训练并评估 | ✓ |
| safe blend 在 valid 上完成选择 | ✓ |
| 所有候选均未通过门控，保留 Round68 final | ✓ |

---

## 二、训练样本口径重构

### 2.1 分布对比（6-19 点，排除 future）

| split | 总行数 | 正样本率 | weak率 | inactive率 | mean_power |
|-------|--------|----------|--------|------------|------------|
| train | 421,771 | 71.8% | 5.4% | 22.8% | 1.42 MW |
| valid | 59,024 | 80.0% | 4.4% | 15.6% | 1.56 MW |
| test | 116,144 | 61.6% | 6.1% | 32.3% | 0.90 MW |

**关键发现**：
- 训练集正样本率（71.8%）明显低于 valid 集（80.0%）和 test 集（61.6%）
- **test 集 inactive 率高达 32.3%**，说明测试期包含更多阴雨天气或低辐照日
- 这种分布不一致是导致所有候选在 test 上系统性退化的根本原因之一
- 早晚时段（6、7、18、19 点）inactive 占比极高（>80%），模型容易在这些时段被误导

---

## 三、候选评估结果

### 3.1 Valid 集指标对比

| 候选 | city_nrmse Δ | site_nrmse Δ | city_nrmse_10_14 Δ | bad_sites | 通过门控 |
|------|-------------|-------------|---------------------|-----------|----------|
| active_state_lgb | +1.644 pp | +2.126 pp | +2.162 pp | 62 | ✗ |
| noon_bias_lgb | +1.354 pp | +1.798 pp | +1.928 pp | 63 | ✗ |
| high_error_expert | +0.511 pp | +1.597 pp | +0.613 pp | 41 | ✗ |

**Baseline valid 指标**：city_nrmse=5.252%，site_mean_nrmse=14.197%

### 3.2 Test 集指标对比

| 候选 | city_nrmse | city_nrmse_10_14 | site_mean_nrmse | city_bias_6_19 | rmse_city |
|------|-----------|------------------|----------------|-----------------|-----------|
| **power_pred_final** | **4.13%** | **5.94%** | **10.58%** | **+0.52%** | **16.06** |
| active_state_lgb | 4.77% (+0.64) | 6.49% (+0.55) | 11.78% (+1.20) | -12.0% | 18.54 (+2.48) |
| noon_bias_lgb | 4.62% (+0.49) | 6.70% (+0.76) | 11.34% (+0.76) | -9.0% | 17.98 (+1.92) |
| high_error_expert | 4.49% (+0.36) | 6.45% (+0.52) | 11.66% (+1.09) | -9.7% | 17.46 (+1.40) |

### 3.3 逐小时对比

所有候选在 test 上全面退化，特别是早晚时段（6-8点、16-19点）退化严重：
- 6点：baseline 1.33% → 候选 1.6-2.6%（退化最严重）
- 16点：baseline 2.02% → 候选 2.3-3.2%
- 早/晚时段：新模型将大量 inactive 样本误判为 weak/active，导致系统性高估

---

## 四、失败根因分析

### 4.1 训练-评估分布不一致

**根本问题**：训练集正样本率（71.8%）与评估集（valid 80.0% / test 61.6%）均不一致。
- 训练集混合了全年数据，包含大量低辐照日
- Valid 集（7-8月）恰好是最晴朗的时段，正样本率最高
- Test 集（9-12月）包含秋季阴雨天气，inactive 率高达 32%

模型在晴朗的 valid 上优化，却在 test 上遭遇分布偏移，导致系统性负偏（city_bias 退化 -9% 到 -12%）。

### 4.2 发电状态分类误差传播

- active_recall=86.7%，inactive_recall=68.3%，weak_recall=73.2%
- inactive→active 误分类导致大量弱发电被高估
- 分类误差在专家回归中被放大（inactive 状态下预测残差极大）

### 4.3 特征不足

当前特征仅包含：
- 时间：hour, month, dayofyear
- 地理：latitude, longitude, capacity_mw
- 辐照：g_blend_pred, clear_sky_ghi, clear_sky_index
- 站点统计：site_zero_ratio, pr_median, quality_score

**缺少关键气象特征**：无温度、湿度、风速、NWP 数据、无云图特征，模型难以区分真实阴天和晴天的弱发电。

### 4.4 高误差站点未充分归因

高误差站点（S003, S021, S022, S004 等）可能是：
- 地理位置偏僻，气象数据代表性差
- 设备老化或遮挡
- 气象不可预报的极端天气

仅靠历史辐照特征无法有效建模。

---

## 五、最终建议

### 5.1 Round70 结论

**不建议采用 Round70 任何候选，保留 Round68 final（power_pred_final）。**

### 5.2 下一轮（Round71）建议

基于 Round70 的教训，建议下一轮优先：

1. **引入气象/NWP 数据**（最高优先级）
   - ERA5 再分析数据：温度、湿度、风速、地表气压
   - 卫星云图特征：葵花/风云卫星云覆盖率
   - 数值天气预报辐照度预测
   - 这些特征能有效区分真实阴天和晴天的弱发电状态

2. **解决训练-评估分布不一致**
   - 仅用 7-8 月（与 valid 同分布期间）作为训练集
   - 或对训练集做时间加权，越接近 valid/test 时间权重越高
   - 或分层采样，保证训练集各月份分布与评估集一致

3. **简化模型结构，避免过度复杂化**
   - 当前 baseline（Round68 final）已是一个经过多轮优化的成熟模型
   - 新模型的系统性退化说明训练链路本身有问题，而非模型容量不足

4. **如果仍聚焦机器学习方案**
   - 在 valid/test 同期数据上训练（避免时序泄漏）
   - 使用更鲁棒的目标函数（如 Huber loss）
   - 对极端弱发电时段单独建模，但需要更丰富的气象特征

---

## 六、输出文件清单

| 文件 | 说明 |
|------|------|
| `round70_training_distribution_by_split.csv` | 各 split 分布统计 |
| `round70_training_distribution_by_hour.csv` | 各小时分布统计 |
| `round70_training_distribution_by_site.csv` | 各站点分布统计 |
| `round70_candidate_diff_check.csv` | 候选列差异检查 |
| `round70_active_state_valid_metrics.csv` | 状态分类器 valid 指标 |
| `round70_active_state_test_metrics.csv` | 状态分类器 test 指标 |
| `round70_state_expert_training_summary.csv` | 专家回归器训练摘要 |
| `round70_noon_bias_valid_compare.csv` | noon_bias valid 对比 |
| `round70_high_error_site_list.csv` | 高误差站点列表 |
| `round70_high_error_expert_valid_compare.csv` | 高误差专家 valid 对比 |
| `round70_valid_candidate_compare.csv` | 所有候选 valid 门控评估 |
| `round70_stacked_blend_weights.csv` | blend 权重搜索结果 |
| `round70_candidate_decision.json` | 最终决策结果 |
| `round70_test_overall_compare.csv` | test 整体对比 |
| `round70_test_hourly_compare.csv` | test 逐小时对比 |
| `round70_test_site_compare.csv` | test 逐站点对比 |
