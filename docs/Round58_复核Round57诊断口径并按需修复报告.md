# Round58 复核 Round57 诊断口径并按需修复报告

**生成时间**: 2026-05-31
**执行原则**: 先独立复核，确认问题存在后才修改

---

## 1. 本轮目标

独立复核 Round57 诊断口径的 7 个疑似问题，确认哪些真实存在，对确认存在的进行修复。

---

## 2. 是否直接修改

**先独立复核，确认问题存在后才修改。** 不基于猜测直接改。

---

## 3. 复核发现

### 复核结果汇总

| 问题编号 | 问题代码 | 严重程度 | 是否真实存在 | 证据 |
|:-------:|----------|:-------:|:------------:|------|
| F1 | `HOUR_SITE_CITY_IDENTICAL` | HIGH | **存在** | Round57 hour 表中 site_mean_nrmse_percent == city_nrmse_percent 对所有行完全相同 |
| F2 | `HOUR_CITY_NRMSE_MISMATCH` | HIGH | **存在** | Round57 city_nrmse 与独立复算最大差异 = 2670.8% |
| F3 | `HOUR_SITE_NRMSE_MISMATCH` | HIGH | **存在** | Round57 site_mean 与独立复算最大差异 = 2660.3% |
| F4 | `MONTH_CITY_NRMSE_MISMATCH` | HIGH | **存在** | Round57 月份 city_nrmse 与独立复算最大差异 = 2058.2% |
| F5 | `MONTH_CONCLUSION_MAY_BE_WRONG` | MEDIUM | **未确认** | 最差月份均为 9 月，结论一致 |
| F6 | `MAIN_BAD_HOURS_EMPTY` | MEDIUM | **存在** | main_bad_hours 列全部为空 |
| F7 | `DAYTIME_SCENE_NIGHT_OVERTRIGGER` | MEDIUM | **存在** | 68/68 站点（100%）被标记 daytime_scene_night |
| F8 | `NAN_BIAS_NEEDS_SEPARATE_CLASS` | MEDIUM | **存在** | 5 个站点 bias=NaN（S003/S044/S069/S076/S077），被误归为 over/under prediction |
| F9 | `HOUR_METRICS_SHOULD_DIFFER` | LOW | **存在** | site_mean 与 city 列差异 = 0.00%（应 > 1%）|

**结论：8/9 项问题真实存在，全部修复。**

---

## 4. 修复内容

### 4.1 NRMSE 计算口径修复（影响 F1/F2/F3/F4）

**问题根因**：Round57 中 `site_mean_nrmse_percent` 和 `city_nrmse_percent` 使用了相同的错误分母。

错误公式：
```
city_rmse = sqrt(mean((pred - actual)^2))
city_nrmse = city_rmse / (sum(capacity_per_hour / n_rows)) * 100
```

正确公式（两列独立计算）：

**site_mean_nrmse_percent**：
```
对每个站点: RMSE(站点actual, 站点pred) / 站点capacity * 100
最终: mean(所有站点的 nrmse)
```

**city_nrmse_percent**：
```
先按 timestamp 聚合: agg_actual = sum(actual), agg_pred = sum(pred)
再计算: RMSE(agg_actual, agg_pred) / 总city_capacity * 100
```

### 4.2 main_bad_hours 填充（修复 F6）

从 `round57_error_by_site_hour.csv` 取每个站点 NRMSE 最高的 3 个小时，填入 priority_sites。

### 4.3 daytime_scene_night 触发阈值修正（修复 F7）

- 旧阈值：`scene_night_ratio_6_19 > 0.2`（6-19 全时段夜间 scene 占比）
- 新口径：计算 `scene_night_ratio_10_14`（10-14 时段内夜间 scene 占比），阈值 `> 0.05`

### 4.4 NaN bias 站点单独归类（修复 F8）

- 旧行为：NaN bias 被 `abs(NaN) >= 20` 触发 `high_bias`，被 `NaN <= 0.75` 触发 `under_prediction`
- 新行为：检测到 NaN bias 时，标记 `zero_actual_sum`，不再归入 over/under prediction

### 4.5 risk_flags 逻辑重构

- NaN bias 检测：优先判断 bias 是否为 NaN
- 仅对有效 bias 值检查 `high_bias`
- 仅对有效 pred_actual_ratio 检查 `over/under_prediction`

---

## 5. 修复后复核结果

修复后重新执行独立复核：

| 问题代码 | 修复前 | 修复后 |
|----------|:------:|:------:|
| `HOUR_SITE_CITY_IDENTICAL` | 存在 | **未确认**（两列不再相同）|
| `HOUR_CITY_NRMSE_MISMATCH` | 存在（diff=2670%）| **未确认**（diff=0%）|
| `HOUR_SITE_NRMSE_MISMATCH` | 存在（diff=2660%）| **未确认**（diff=0%）|
| `MONTH_CITY_NRMSE_MISMATCH` | 存在（diff=2058%）| **未确认**（diff=0%）|
| `MONTH_CONCLUSION_MAY_BE_WRONG` | 未确认 | 未确认 |
| `MAIN_BAD_HOURS_EMPTY` | 存在 | **未确认**（main_bad_hours 已填充）|
| `DAYTIME_SCENE_NIGHT_OVERTRIGGER` | 存在（100%）| **未确认**（0% 触发）|
| `NAN_BIAS_NEEDS_SEPARATE_CLASS` | 存在 | **标注：已修复**，5 个站点正确标记为 `zero_actual_sum` |
| `HOUR_METRICS_SHOULD_DIFFER` | 存在（diff=0%）| **未确认**（diff=5.8%）|

**修复后：所有 HIGH severity 问题已解决。** NaN bias 问题已从误分类修正为正确归类，标记为 `zero_actual_sum`。

---

## 6. 修正后的关键指标

### 6.1 按小时

| 时段 | site_mean NRMSE% | city NRMSE% | Bias% | P/A |
|------|----------------:|------------:|------:|----:|
| 6h | 4.20 | **1.03** | -33.5 | 0.67 |
| 7h | 5.62 | **4.04** | -61.3 | 0.39 |
| 8h | 7.84 | **4.08** | -21.3 | 0.79 |
| 9h | 11.34 | **4.66** | +1.7 | 1.02 |
| 10h | 14.52 | **5.90** | +8.2 | 1.08 |
| 11h | 16.30 | **6.42** | +8.3 | 1.08 |
| 12h | 16.98 | **6.43** | +8.9 | 1.09 |
| 13h | 16.58 | **6.55** | +10.4 | 1.10 |
| 14h | 14.24 | **5.89** | +5.8 | 1.06 |
| 15h | 10.09 | **3.58** | +1.2 | 1.01 |
| 16h | 6.68 | **2.11** | -2.3 | 0.98 |
| 17h | 4.28 | **2.11** | -43.5 | 0.57 |
| 18h | 4.19 | **1.32** | -28.8 | 0.71 |
| 19h | 3.94 | **1.24** | -27.9 | 0.72 |

**说明**：
- **city NRMSE 真实量级在 1-7%**（远低于 Round57 错误计算的 1000-2700%）
- **site_mean NRMSE 真实量级在 4-17%**（与 city 口径不同但互补）
- 误差模式：7时严重低估（bias -61%），10-13时高估（+8~+10%），17时严重低估（-43%）

### 6.2 按月份

| 月份 | site_mean NRMSE% | city NRMSE% | Bias% | P/A | 高误差站点 |
|------|----------------:|------------:|------:|----:|-----------|
| 9月 | 13.96 | **5.49** | -3.4 | 0.97 | S053/S071/S007 |
| 10月 | 10.68 | **4.53** | +1.7 | 1.02 | S071/S053/S012 |
| 11月 | 10.38 | **4.29** | +2.8 | 1.03 | S053/S071/S012 |
| 12月 | 9.00 | **3.15** | +5.4 | 1.05 | S053/S012/S032 |

**说明**：9月误差最高（city NRMSE 5.5%），12月误差最低（3.1%），与 Round57 错误结论一致。

### 6.3 按场景

| 场景 | site_mean NRMSE% | city NRMSE% | Bias% | P/A | 高误差站点 |
|------|----------------:|------------:|------:|----:|-----------|
| clear_peak | 17.66 | **6.02** | +13.8 | 1.14 | S012/S044/S073 |
| mid | 11.93 | **4.86** | +11.9 | 1.12 | S012/S007/S116 |
| low | 7.68 | **2.34** | -42.3 | 0.58 | S053/S071/S032 |
| night | 3.94 | **1.35** | -36.2 | 0.64 | S053/S071/S059 |

**说明**：clear_peak 场景误差最高（city NRMSE 6.02%），与辐照强时系统性高估一致。low 场景虽然 site_mean NRMSE 低，但 bias 严重（-42%）。

### 6.4 优先站点（修正后）

| 优先级 | 站点 | 容量(MW) | NRMSE | Bias% | 最差小时 | 建议动作 |
|:------:|------|----------:|------:|------:|:--------:|----------|
| 1 | S053 鹰游新立成 | 13.33 | 24.5% | -34.1% | 6\|7\|19 | 检查容量映射 |
| 2 | S012 泰富如意情 | 17.55 | 16.4% | +158% | 11\|12\|13 | bias 校准 |
| 3 | S071 协鑫南岗 | 20.00 | 13.4% | -31.4% | 7\|17\|19 | bias 校准 |
| 4 | S007 林洋朝阳光伏 | 22.00 | 9.8% | +6.9% | 11\|12\|13 | 监控 |
| 5 | S116 林洋伊山 | 22.00 | 9.5% | -36.8% | 11\|12\|13 | 更新精确坐标 |
| 6 | S032 华能中林 | 9.34 | 20.4% | -73.5% | 11\|12\|13 | 检查辐照链路 |
| 7 | S073 华能裕灌 | 15.00 | 9.8% | -21.8% | 11\|12\|13 | 分析偏差来源 |
| 8 | S115 鑫众墩尚 | 7.00 | 17.6% | +4.1% | 11\|12\|13 | 监控 |
| 9 | S023 连洋徐圩 | 16.37 | 6.1% | +94.4% | 11\|12\|13 | 检查容量映射 |
| 10 | S019 首耀新海 | 3.00 | 30.4% | -27.7% | 6\|7\|19 | bias 校准 |

---

## 7. 修正后的关键指标总览

> 注：city NRMSE 现在使用 city-aggregated RMSE / 总城市容量 的正确口径。

| 指标 | Round57（错误口径）| Round58（修正口径）|
|------|-------------------:|-------------------:|
| 城市 NRMSE 6-19 | 16.31% (错误分母) | **4.44%** |
| 城市 NRMSE 10-14 | 20.99% (错误分母) | **6.24%** |
| 站点平均 NRMSE | 11.41% | 11.41%（站点口径未变）|
| 整体 Bias | 1.39% | 1.39% |
| 高误差站点数（NRMSE>=20%）| 4 | 4 |
| 高偏差站点数（\|bias\|>=20%）| 22 | 22 |

---

## 8. 仍然可信的问题归因

> 以下结论经过修正口径验证，仍然成立。

1. **10-14 时段系统性高估**：city bias +6~+10%，pred/actual=1.06-1.10。clear_peak 和 mid 场景 bias > +10%。
2. **7 时严重低估**：city bias -61%，pred/actual=0.39。
3. **17 时严重低估**：city bias -43%，pred/actual=0.57。
4. **low 场景系统性低估**：bias -42%，pred/actual=0.58。
5. **S032 华能中林**：辐照特征可能缺失（g_blend_zero_ratio 高），site NRMSE=20.4%，bias=-73.5%。
6. **S053 鹰游新立成**：容量映射可能错误（长期低估 34%，但 pred/actual 0.66），site NRMSE=24.5%，早晚边界误差最大。
7. **5 个零功率站点**：S003/S044/S069/S076/S077 实际功率长期为0，正确标记为 `zero_actual_sum`，不再误归为高估/低估。
8. **S116 低置信度坐标**：confidence=low，best hours 集中在 11-13 时，需确认场区中心精确坐标。

---

## 9. 下一步是否可以进入模型改进

**可以。** 诊断口径已通过复核，以下方向可信：

1. **站点级/小时级 bias 校准**：22 个站点 bias >= 20%，方向明确
2. **辐照特征链路排查**：S032 等站点辐照异常
3. **容量映射核查**：S053/S012/S023 等容量可能错误
4. **数据质量标记**：5 个零功率站点应从评估中剔除或单独标记

---

## 10. 验收标准

| 标准 | 状态 |
|------|:----:|
| [PASS] 新增 recheck_round57_diagnostic_metrics.py | 完成 |
| [PASS] 独立复核使用 final_eval 从零计算 | 完成 |
| [PASS] 复核报告明确每个疑似问题是否真实存在 | 完成（9 项全部说明）|
| [PASS] 只有确认存在的问题才修改 | 完成 |
| [PASS] 修复后 site_mean != city_nrmse | 完成（diff=5.8%）|
| [PASS] 小时/月/场景 NRMSE 使用正确口径 | 完成 |
| [PASS] main_bad_hours 不再全空 | 完成 |
| [PASS] daytime_scene_night 不再大面积误报 | 完成（0% 触发）|
| [PASS] actual_sum=0 的站点单独归类 | 完成（zero_actual_sum）|
| [PASS] 报告结论与 CSV 一致 | 完成 |
| [PASS] 不重训模型 | 完成 |
