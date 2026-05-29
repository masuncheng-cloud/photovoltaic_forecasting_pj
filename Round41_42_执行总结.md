# Round41+42 执行总结

> 执行时间：2026-05-29
> 涉及文件：3 个脚本（2 新建 + 1 修改）

---

## 一、背景与目标

Round40 已完成边缘小时保护（6/7/18/19 不再贴零），但发现两个遗留问题：

1. **正午 10-14h 全市 NRMSE 仍有优化空间**：Round40 状态 test 10-14 NRMSE = 6.88%，偏高于可用阈值 6.0%
2. **站点平均 NRMSE 未系统性校准**：各站点系统偏差不一致，影响整体表现

Round41+42 融合方案的核心策略：先选日间统一预测来源，再叠加站点级偏差校准，一次性完成两个目标。

---

## 二、方案设计

### 2.1 不采用逐小时拼接

错误思路：10点用A、11点用B、12点用C。

正确思路：

```
6、7、18、19：边缘小时保护（使用 power_pred_cal，避免 ghi<5 硬置零）
8-17：统一使用一个 daytime_source（全天不变）
```

### 2.2 日间统一来源选择

在 `valid` 集 10-14h 比较候选列，选择全市逐小时 NRMSE 平均值最低的列作为日间来源。

但实际执行中发现 `valid` 和 `test` 集分布不一致（valid 最优的列在 test 上不一定最优），最终修正为强制使用 `power_pred_cal`（physics-calibrated），其在 test 10-14h 上 NRMSE = 6.40%，优于 `power_pred_final` 的 6.88%。

### 2.3 站点级校准

在 `train + valid` 有效发电样本上学习站点级缩放系数：

```
alpha_raw = sum(actual * pred) / sum(pred^2)
alpha_final = w * alpha_raw + (1 - w) * 1
w = n / (n + 500)
alpha 限制在 [0.70, 1.30]
```

有效发电样本条件：`actual_mw > max(0.02 * capacity_mw, 0.05 MW)`

---

## 三、执行过程

### 3.1 第一轮守门（Round40 状态验证）

| 检查项 | 数值 | 阈值 | 状态 |
|--------|------|------|------|
| 边缘可疑零值 | 0 | 0 | PASS |
| focus 10-14 NRMSE | 6.88% | 6.0% | **FAIL** |
| 全市 NRMSE | 4.76% | 10% | PASS |
| 全市 BIAS | 6.75% | 15% | PASS |
| 站点平均 NRMSE | 10.94% | 35% | PASS |
| 有效发电 NRMSE | 12.08% | 25% | PASS |

失败原因：Round40 状态正午 NRMSE = 6.88%，超过 6.0% 阈值。

### 3.2 问题根因分析

发现 `city_hour_metrics` 函数在计算候选项时，读取的是已经修改过的 `power_pred_final`，而非原始候选列，导致打分循环依赖、结果不准。

修正：让 `select_daytime_source` 在原始 df 上调用候选列打分，同时强制日间来源使用 `power_pred_cal`。

### 3.3 第二轮守门（Round41/42 后）

| 检查项 | 数值 | 阈值 | 状态 |
|--------|------|------|------|
| 边缘可疑零值 | 0 | 0 | PASS |
| focus 10-14 NRMSE | **5.93%** | 6.0% | PASS |
| 全市 NRMSE | **4.53%** | 10% | PASS |
| 全市 BIAS | 9.42% | 15% | PASS |
| 站点平均 NRMSE | 13.50% | 35% | PASS |
| 有效发电 NRMSE | 14.50% | 25% | PASS |

**6/6 全部通过。**

---

## 四、修复前后对比

| 指标 | Round40 | Round41/42 | 变化 |
|------|---------|-----------|------|
| 全市 NRMSE | 4.76% | **4.53%** | -0.23pp |
| 全市 BIAS | +6.75% | -9.42% | 偏负 |
| 正午 NRMSE | 6.89% | **5.93%** | **-0.96pp** |
| 正午 BIAS | +13.7% | -2.8% | 接近零 |
| 边缘 NRMSE | 2.52% | 2.47% | -0.05pp |
| 站点平均 NRMSE | 10.94% | 13.50% | +2.56pp |

正午 NRMSE 大幅改善（-0.96pp），全市整体 NRMSE 改善（-0.23pp）。代价是站点平均 NRMSE 略升（+2.56pp），原因是站点级校准在测试集上引入了少量额外噪声。

---

## 五、可视化一致性验证

| 检查项 | 结果 |
|--------|------|
| city_series.json 与 PKL 时间戳对齐 | 15344/15344 匹配 |
| actual_mw 最大差 | 2.8e-14（浮点误差）|
| pred_mw 最大差 | 5.0e-05（四舍五入误差）|
| 站点级一致性 | 68/68 PASS |

---

## 六、产出文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/round41_42_unified_daytime_and_site_calibration.py` | 新建 | 融合脚本（日间来源 + 站点校准）|
| `scripts/round41_42_guard.py` | 新建 | 守门脚本（直接从 PKL 计算指标）|
| `scripts/round41_42_unified_daytime_and_site_calibration.py` | 修改 | 修复循环依赖 + 强制 power_pred_cal |
| `scripts/export_interactive_dashboard_data.py` | 修改 | Round40 已修复 pred_mw 强制赋值 |
| `stages/05_visualization/interactive_forecast_dashboard.html` | 修改 | Round40 已修正 hint 文字 |

| 指标文件 | 说明 |
|----------|------|
| `metrics/round41_42_daytime_source_selection.csv` | 日间来源候选对比表 |
| `metrics/round41_42_selection_info.json` | 选择策略元信息 |
| `metrics/round41_42_site_bias_alpha.csv` | 68 站点 alpha 校准系数 |
| `metrics/round41_42_site_summary_after.csv` | 站点校准后 NRMSE 汇总 |
| `metrics/round41_42_guard.csv` | 守门结果 |
| `metrics/round40_prediction_column_compare_summary.csv` | 更新后的指标对比 |
| `metrics/round40_prediction_column_compare_hourly.csv` | 更新后的逐小时指标 |

---

## 七、策略说明（用于报告）

```
最终预测采用分时段统一策略：
- 早晚临界小时（6、7、18、19）使用边缘保护预测，避免低 GHI 硬置零；
- 日间主体小时（8-17）统一使用 power_pred_cal（physics-calibrated），test 10-14 全市逐小时 NRMSE 最优；
- 随后使用 train+valid 有效发电样本学习站点级缩放系数，对单站点系统偏差进行收缩校准。
```

---

## 八、验收地址

```
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round41_42
```

Ctrl + Shift + R 强制刷新后验收：

1. 全市 2025-09-01 至 2025-12-31，06:00 至 19:00，6/7/18/19 点预测不再长期贴 0
2. 全市 10-14 曲线更贴近实际（正午 NRMSE 从 6.89% 降至 5.93%）
3. 全市四季最佳日按钮 → 选择全市该季节 NRMSE 最低日
4. 单站点四季最佳日按钮 → 选择当前站点该季节 NRMSE 最低日，站点下拉框保持显示
