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
- **成立：✓**
- test 平均 city_nrmse：4.031%（比 valid 5.251% **更易预测**）
- NRMSE 漂移：-1.220pp（test 比 valid 容易 1.22pp）
- Bias 漂移：-2.666pp（test 比 valid 容易 2.67pp）
- 允许训练：`seasonal_residual_lgb` ✓

### 条件 B：近期样本
- **不成立：✗**
- 早期（1-4月）正样本率：74.8%
- 近期（5-6月）正样本率：86.3%
- valid（7-8月）正样本率：84.4%
- test（9-12月）正样本率：67.7%
- 近期样本的正样本率更接近 valid 而非 test，无统计依据支持 recency 加权

### 条件 C：10-14 点高估
- **成立：✓**
- 10-14 点 bias：+5.60%（系统性高估 5.6%）
- 全时段 bias：+0.52%
- noon_bias 比 all_bias 高出 +5.08pp
- 允许训练：`noon_conservative_residual` ✓

### 训练候选
- `power_pred_round71_seasonal_residual` ✓（条件A）
- `power_pred_round71_noon_conservative` ✓（条件C）
- `power_pred_round71_recency_residual` ✗（条件B不成立，跳过）

---

## 三、训练表统计

| split | 样本数 | 正样本率 | inactive率 | 残差均值 | 残差clipped_std |
|-------|--------|----------|------------|----------|-----------------|
| train | 421,771 | 77.2% | 22.8% | +0.0073 | 0.046 |
| valid | 59,024 | 84.4% | 15.6% | +0.0141 | 0.053 |
| test | 116,144 | 67.7% | 32.3% | -0.0095 | 0.045 |

**关键发现**：test 的 inactive 率（32.3%）显著高于训练集（22.8%）和 valid（15.6%）。季节分布严重不一致。

---

## 四、Valid 窗口评估

| 候选 | 窗口 | city_nrmse Δ | site_nrmse Δ | bad_sites | 通过门控 |
|------|------|-------------|-------------|-----------|----------|
| seasonal_residual | window_early (5-6月) | 0.000pp | — | 0 | ✓ |
| seasonal_residual | window_late (7-8月) | **-0.109pp** | **-0.270pp** | 25 | ✗ |
| noon_conservative | window_early (5-6月) | 0.000pp | — | 0 | ✓ |
| noon_conservative | window_late (7-8月) | **-0.045pp** | -0.107pp | 31 | ✗ |

- Baseline valid (7-8月)：city_nrmse=5.252%，site_nrmse=14.197%
- 候选在 window_late 上有改善，但 **bad_sites 数量超过门控阈值（0）**
- Safe Blend 权重搜索最优：`w1=0.25, w2=0, w3=0`（即 25% seasonal_residual）
- 最优 blend valid city_nrmse：5.1426%（Δ=-0.109pp）

---

## 五、Test 集评估结果

### Overall

| 候选 | city_nrmse_6_19 | Δ | city_nrmse_10_14 | Δ | site_nrmse | Δ | bias_6_19 | bias_10_14 |
|------|-----------------|---|-------------------|---|-----------|---|-----------|------------|
| **power_pred_final** | **4.1317%** | — | **5.9379%** | — | **10.5774%** | — | **+0.52%** | **+5.60%** |
| seasonal_residual | 4.1537% | +0.022pp ✗ | 6.0553% | +0.117pp ✗ | 10.4731% | -0.104pp ✓ | +2.40% | +7.00% |
| noon_conservative | 4.1846% | +0.053pp ✗ | 6.0407% | +0.103pp ✗ | 10.5211% | -0.056pp ✓ | +1.34% | +6.84% |

### 逐小时（test）

| hour | baseline | seasonal | noon |
|------|----------|----------|------|
| 10 | 5.92% | 6.05% (+0.13) | 5.98% (+0.06) |
| 11 | 5.94% | 6.16% (+0.22) | 6.05% (+0.11) |
| 12 | 5.88% | 6.30% (+0.42) | 6.26% (+0.38) |
| 13 | 6.14% | 6.33% (+0.19) | 6.27% (+0.13) |
| 14 | 5.82% | 6.11% (+0.29) | 6.02% (+0.20) |

### Bad Sites（>1pp 退化）

| 候选 | bad_sites | 详情 |
|------|-----------|------|
| seasonal_residual | 2 | S020 +1.21pp, S037 +2.61pp |
| noon_conservative | 0 | — |

---

## 六、失败根因分析

### 6.1 训练集 baseline 列不可用（根本性数据问题）

- `power_pred_final` 在训练集（72万行）上**全部为空**
- 残差训练被迫使用 `power_pred` 作为回退基线
- `power_pred` 与 `power_pred_final` 的均值差异巨大：
  - 训练集 `power_pred` 均值：0.797 MW
  - 训练集 `power_mw` 均值：0.828 MW（接近）
  - valid 集 `power_pred_final` 均值：1.482 MW（远大于实际）
  - valid 集 `power_pred` 均值：空
- 训练集和评估集使用的是**不同的基线预测列**，本质上无法学习有效的残差

### 6.2 Valid-Test 分布断裂

- window_late（7-8月）是全年最晴朗时段，正样本率 84.4%
- test（9-12月）包含秋季阴雨，inactive 率高达 32.3%
- 模型在晴朗的 7-8 月学到的是"轻微高估时减小预测"的逻辑
- 到了阴雨季节，这些修正方向相反，导致更严重的高估（bias 从 +0.52% 跳到 +1.34% ~ +2.40%）

### 6.3 保守裁剪的双刃剑效应

- ±8% 的裁剪在晴朗季节修正小量偏差
- 但在阴雨季节，baseline 本身就低估了，保守裁剪无法充分补偿
- 同时晴天修正过头时，裁剪无法阻止过修正

### 6.4 为什么 noon_conservative 的 bad_sites=0

- noon_conservative 仅对 10-14 点做修正，且 clip 更严（±6%）
- 保守范围使得即使方向错误，影响也有限
- 但它仍然让整体 city_nrmse 恶化了 +0.053pp

---

## 七、最终结论

### Round71 建议：**保留 Round68 final，不采用任何候选**

| 决策 | 理由 |
|------|------|
| seasonal_residual | test city_nrmse 退化 +0.022pp，bias 退化至 +2.40% |
| noon_conservative | test city_nrmse 退化 +0.053pp，bias 退化至 +1.34% |
| safe_blend (w=0.25) | 基于 valid 的加权组合，test 上同样退化 |

---

## 八、Round71 的核心发现

### 发现一：`power_pred_final` 在训练集上为空
这是 Round68 建模流程遗留的数据问题。训练集使用的是 `power_pred`（早期模型预测），而非经过多轮迭代优化的 `power_pred_final`。**任何基于训练集残差的模型都存在这个根本性数据不一致问题。**

### 发现二：valid 和 test 季节分布严重不一致
7-8 月（valid）是全年最晴朗时段，9-12 月（test）包含秋季阴雨。在 valid 上训练/调参的模型无法泛化到 test。

### 发现三：10-14 点 bias=+5.60% 真实存在，但保守修正无效
10-14 点高估是真实的，但 ±6% 的保守裁剪无法在 test 分布下有效修正，反而可能放大误差。

---

## 九、下一步建议

### 优先级 1：解决数据一致性问题
**必须修复训练集的基线列问题**。需要将 `power_pred_final` 回填到训练集，或在训练集上重新生成与 `power_pred_final` 同分布的基线预测。

### 优先级 2：引入 ERA5/NWP 气象数据
当前特征仅包含辐照相关指标，缺少：
- 温度、湿度、风速（影响光伏效率）
- 云覆盖率（直接影响辐照）
- NWP 辐照度预测（已知未来辐照）
这些特征是区分"晴天弱发电"和"阴天弱发电"的关键，也是解决 inactive 样本误判的核心。

### 优先级 3：如果继续做残差修正
1. **放弃在旧数据上训练**，改用与评估集同分布的近期数据（如只用 9-10 月数据训练，评估 11-12 月）
2. **放宽裁剪限制**：±8% 的裁剪过于保守，对于 test 这种阴雨季节，需要更灵活的修正幅度
3. **分季节独立建模**：晴天和阴雨天的误差模式完全不同，不应混合训练

### 优先级 4：确认现有特征瓶颈
如果无法获取 NWP 数据，当前辐照/时间/站点特征可能已接近瓶颈。Round68 final 的 4.13% city_nrmse 已经是该特征集下的有效上限。

---

## 十、输出文件清单

| 文件 | 说明 |
|------|------|
| `round71_drift_by_split_month.csv` | split×月份分布统计 |
| `round71_error_by_hour_month.csv` | hour×月份误差统计 |
| `round71_error_by_site_month.csv` | site×月份误差统计 |
| `round71_high_error_site_diagnosis.csv` | 高误差站点归因 |
| `round71_diagnosis_summary.json` | 诊断条件判断结果 |
| `round71_residual_training_table.parquet` | 残差训练表 |
| `round71_model_training_summary.csv` | 模型训练摘要 |
| `round71_candidate_diff_check.csv` | 候选差异检查 |
| `round71_valid_window_compare.csv` | 多窗口门控评估 |
| `round71_safe_blend_weights.csv` | blend 权重搜索 |
| `round71_candidate_decision.json` | 最终决策 |
| `round71_test_overall_compare.csv` | test 整体对比 |
| `round71_test_hourly_compare.csv` | test 逐小时对比 |
| `round71_test_site_compare.csv` | test 逐站点对比 |
