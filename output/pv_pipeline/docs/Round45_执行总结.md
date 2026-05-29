# Round45 执行总结：单站点逐小时 NRMSE 专项诊断与稳健校准

> **执行时间**: 2026-05-29 21:20 ~ 22:00（UTC+8）
> **执行人**: Cursor AI Agent
> **执行方式**: 手动分步执行（3 个新增脚本 + 6 个已有脚本）

---

## 一、执行目标

Round44 收口后，发现单站点逐小时 NRMSE 偏高（10-13点站点均值 13.8-16.1%，城市仅 4.77%），本轮目标：
1. 诊断单站点逐小时 NRMSE 高的来源
2. 探索站点-小时收缩校准是否有效
3. 不破坏已有守门结果

---

## 二、Round44 修正确认（Round45 第一件事）

`round41_42_unified_daytime_and_site_calibration.py` 删除了 `verify_and_maybe_override` 函数，`TEST_FALLBACK_DELTA = None`，彻底消除任何 test 集 snooping 风险。`round41_42_selection_info.json` 明确标注 `selection_split=valid`、`test_used_for_selection=false`。

---

## 三、Round45 诊断结果

### 逐小时站点平均 NRMSE（test 集 6-19h）

| 时段 | 小时 | 站点均值 NRMSE | 活跃NRMSE | 零值比例 | 高NRMSE站点(>30%) |
|---|---|---|---|---|---|
| 边缘 | 6 | 3.72% | 8.60% | 84.8% | 2 |
| 边缘 | 7 | 5.72% | 8.31% | 38.3% | 2 |
| 日间 | 8 | 7.42% | 7.21% | 12.5% | 1 |
| 日间 | 9 | 10.75% | 10.00% | 11.0% | 0 |
| 聚焦 | 10 | 13.79% | 12.60% | 10.5% | 1 |
| 聚焦 | 11 | 15.30% | 13.95% | 10.4% | 2 |
| 聚焦 | 12 | **16.14%** | 14.79% | 10.2% | 2 |
| 聚焦 | 13 | 15.86% | 14.64% | 10.3% | 2 |
| 聚焦 | 14 | 13.82% | 12.83% | 10.4% | 0 |
| 日间 | 15 | 9.97% | 9.33% | 10.6% | 0 |
| 日间 | 16 | 6.61% | 6.39% | 12.4% | 0 |
| 日间 | 17 | 4.17% | 6.42% | 54.7% | 2 |
| 边缘 | 18 | 3.82% | 7.21% | 84.4% | 2 |
| 边缘 | 19 | 3.50% | 16.92% | 91.6% | 2 |

**关键发现**：
- 10-14点（聚焦时段）站点 NRMSE 高，主要因为：
  1. **零值放大**：即使零值时刻 RMSE 为 0，小容量站点分母（capacity）很小，放大 NRMSE
  2. **小容量站点偏差大**：低容量站点的预测偏差占容量比更高
  3. **活跃样本均值（去除零值）** 在 12.6-14.8%，远低于含零值指标，差距来自零值比例约 10%
  4. 16:00 后零值比例跳升至 54.7%，17:00 达 54.7%，说明日落前后功率快速下降段预测困难

---

## 四、站点-小时收缩校准结果

### 校准参数

- K = 300（收缩强度）
- alpha 范围：[0.75, 1.25]
- 拟合数据：train+valid 中 active 样本（actual > max(2% cap, 0.05 MW））

### alpha_hour（全局小时系数）

| 小时 | alpha_hour | 拟合样本数 |
|---|---|---|
| 6 | 1.250（截断） | 6,753 |
| 7 | 1.086 | 17,645 |
| 8-9 | ~1.015 | ~30,000 |
| 10-14 | 0.955-0.968 | ~31,000 |
| 15-17 | 0.982-0.996 | ~30,000 |
| 18 | 1.161 | 13,205 |
| 19 | 1.250（截断） | 1,550 |

解读：模型在早晚（6-7h, 18-19h）倾向低估（alpha > 1），10-14h 倾向高估（alpha ~0.96），符合物理直觉。

### alpha_final 分布

- min = 0.8009, max = 1.2500, mean = 1.0576, median = 1.0394

---

## 五、守门决策（valid 集）

| 条件 | 阈值 | 实际值 | 状态 |
|---|---|---|---|
| 站点平均 NRMSE 改善 | >= 0.2pp | **-0.087pp（变差）** | FAIL |
| 全市 NRMSE 变化 | <= 0.3pp | -0.106pp（改善） | PASS |
| 10-14 全市 NRMSE 变化 | <= 0.3pp | -0.072pp（改善） | PASS |
| 全市 \|bias\| | <= 15% | 2.95% | PASS |
| Edge 可疑 0 值数 | == 0 | 0 | PASS |

**[RESTORE] 候选被拒绝**（1/5 条件不满足）

原因分析：valid 集上候选站点 NRMSE 反而恶化 0.09pp（15.49% → 15.58%），说明站点-小时校准在 valid 集上过拟合，未能泛化。最终恢复 base prediction（无校准）。

---

## 六、最终 test 集指标

| 指标 | 数值 |
|---|---|
| 全市 NRMSE | 4.77% |
| 全市 BIAS | +6.66% |
| 全市 10-14 NRMSE | 6.88% |
| 站点平均 NRMSE | 10.94% |
| 站点中位 NRMSE | 9.67% |
| 活跃站点平均 NRMSE | 12.08% |

---

## 七、守门结果（所有已有检查）

### round41_42_guard（6/6 PASS）

| 检查项 | 阈值 | 实际值 | 状态 |
|---|---|---|---|
| edge_suspicious_city_zero_count | 0 | 0 | PASS |
| focus_10_14_city_hourly_nrmse | 7.0% | 6.88% | PASS |
| city_nrmse_under_10 | 10.0% | 4.77% | PASS |
| city_abs_bias_under_15 | 15.0% | 6.66% | PASS |
| full_site_mean_nrmse_under_35 | 35.0% | 10.94% | PASS |
| active_site_mean_nrmse_under_25 | 25.0% | 12.08% | PASS |

### dashboard 刷新检查（3/3 PASS）

| 检查项 | 状态 |
|---|---|
| refresh_detected | True |
| city_series_consistency | PASS |
| site_series_consistency | PASS |

### dashboard 回归检查（27/27 PASS）

全部通过，包括 metadata、city_series、typical_sites、四季 best days、site_series、stamp 等。

---

## 八、产出文件清单

```
output/pv_pipeline/metrics/
├── round45_site_hour_nrmse_diagnosis.csv      ✓
├── round45_hourly_site_nrmse_summary.csv       ✓
├── round45_site_hour_nrmse_top_outliers.csv   ✓
├── round45_site_hour_alpha.csv                ✓
├── round45_hour_alpha.csv                     ✓
├── round45_guard_decision.csv                 ✓
├── round44_site_calibration_decision.csv      ✓（Round44 重写后）
└── round41_42_selection_info.json             ✓（Round44 修正确认）
```

---

## 九、本轮结论与后续建议

### 结论

1. **站点-小时校准对 valid 集无效**：候选在 valid 集上反而使站点 NRMSE 恶化 0.09pp，守门正确拒绝。说明简单的收缩校准在站点-小时粒度过拟合。
2. **全市指标不受影响**：候选使全市 NRMSE 改善 0.11pp（因为 alpha_hour 修正了 10-14h 高估），但站点层面无改善。
3. **Round44 守门全部通过**：所有 6 项检查 PASS，无退化。
4. **Round45 未改变任何指标**：因候选被拒绝，test 集指标与 Round44 末完全一致。

### 后续建议

1. **分层校准思路**：与其对每个 (site, hour) 单独校准，不如按**容量分组**（大/中/小站）再按小时校准，减少过拟合风险。

2. **分析站点 NRMSE 异常来源**：通过 `round45_site_hour_nrmse_top_outliers.csv` 找出具体哪些站点-小时组合拉高均值，重点检查小容量站点或数据质量存疑的站点。

3. **零值处理**：10-14 点约 10% 零值比例是否合理？部分可能是数据采集缺失而非真实 0 发电。建议分析 `round45_site_hour_nrmse_diagnosis.csv` 中 `zero_actual_ratio_pct > 30%` 的站点-小时组合。

4. **考虑改进主模型**：站点 NRMSE 与城市 NRMSE 的差距（16% vs 4.77%）反映的是预测在单站点粒度的固有误差，可能需要改进特征或模型结构，而非后处理校准。

---

*本总结由 Cursor AI Agent 执行生成，执行时间 2026-05-29 21:20~22:00 UTC+8*
