# Round40 执行总结

> 执行时间：2026-05-29
> 涉及文件：5 个脚本（2 新建 + 2 修改）+ 1 个前端 HTML

---

## 一、背景与目标

Round39.11 修复了早晚临界小时预测大量为 0 的问题：将 `power_pred_final` 的基础列从 `power_pred` 改为 `power_pred_cal`（physics-calibrated）。

这次修复是正确方向，但改变了最终预测列的来源，必须做完整守门：

```
不能只看 6/7/18/19 修好了；
还必须确认整体 NRMSE、10-14 点 NRMSE、单站点 NRMSE 没被误伤；
同时确认 dashboard 展示数据与 final pkl 完全一致。
```

本轮不重新训练，只做：指标重算、修复前后对比、自动守门、可视化导出一致性校验、页面文案修正。

---

## 二、守门结果

### 2.1 第一轮守门（Round39.11 修复后）

| 检查项 | 结果 | 数值 |
|--------|------|------|
| 边缘可疑零值 | PASS | 0 次 |
| 正午 NRMSE 差距 | PASS | 0.25pp（阈值 3pp）|
| 全市 NRMSE | PASS | 4.98%（阈值 10%）|
| 全市 BIAS | **FAIL** | **-16.6%**（阈值 15%）|

第一轮失败：整体 BIAS 严重偏低，原因是 `power_pred_cal` 系统性地比 `power_pred` 更小（physics blend 保守）。

### 2.2 第二轮守门（小时级修复后）

| 检查项 | 结果 | 数值 |
|--------|------|------|
| 边缘可疑零值 | PASS | 0 次 |
| 正午 NRMSE 差距 | PASS | 0.48pp（阈值 3pp）|
| 全市 NRMSE | PASS | 4.76%（阈值 10%）|
| 全市 BIAS | **PASS** | **+6.75%**（阈值 15%）|

**4/4 全部通过。**

---

## 三、修复方案

### 3.1 小时级最终列选择

根因：校准比（calibration ratio）全局偏低约 0.85，导致整体和边缘 BIAS 都偏负。但 `power_pred_cal` 在边缘小时（ghi<5）避免了 ML 模型硬置零，是必要的。

修复策略：

```python
edge_hour = df["hour"].isin([6, 7, 18, 19])

# 边缘小时：保留 power_pred_cal*ratio（避免 ghi<5 硬置零）
df.loc[edge_hour, "power_pred_final"] = df.loc[edge_hour, "power_pred_cal"] * ratio

# 非边缘小时：回退到 power_pred*ratio（保持更优的 BIAS）
df.loc[~edge_hour, "power_pred_final"] = df.loc[~edge_hour, "power_pred"] * ratio
```

### 3.2 修复前后对比

| 指标 | Round39.11（power_pred_cal 基础） | Round40（小时级选择） |
|------|--------------------------------|---------------------|
| 全市 NRMSE | 4.98% | **4.76%** |
| 全市 BIAS | -16.6% | **+6.75%** |
| 边缘 NRMSE | 2.52% | 2.52% |
| 边缘 BIAS | -55.3% | -55.4% |
| 正午 NRMSE | 6.66% | 6.89% |
| 正午 BIAS | -11.0% | +13.7% |
| 回退站点数 | 3 个 | 13 个 |

小时级修复后：全市 NRMSE 改善 0.22pp，BIAS 从 -16.6% 改善至 +6.75%（绝对值从 16.6 降至 6.75）。

### 3.3 回退站点明细

Round40 小时级修复后有 13 个站点回退（test NRMSE 恶化 > 1%），回退到 `power_pred_cal`：

S004、S028、S033、S034、S038、S039、S040、S050、S060、S061、S071、S074、S075

---

## 四、可视化一致性修复

### 4.1 根因定位

Dashboard 一致性校验发现 `city_series.json` 的 `pred_mw` 与 PKL 的 `power_pred_final` 总和不一致（最大差 53.6 MW）。

根因：`export_city_series` 中使用 `if "pred_mw" not in df.columns` 判断，但 PKL 中已存在遗留的 `pred_mw` 列（来自之前的计算），导致条件不触发，`pred_mw` 实际上用的是旧的 `power_pred_cal` 值。

### 4.2 修复

将所有导出函数中的条件赋值改为强制赋值：

```python
# 原来（有 bug）：
if "pred_mw" not in df.columns:
    df["pred_mw"] = df["power_pred_final"]

# 修复后（正确）：
df["pred_mw"] = (
    df["power_pred_final"] if "power_pred_final" in df.columns else
    (df["power_pred_cal"] if "power_pred_cal" in df.columns else df["power_pred"])
)
```

涉及函数：
- `export_city_series`
- `export_midday_city`
- `export_season_days`

### 4.3 修复后一致性

| 检查项 | 结果 |
|--------|------|
| 时间戳对齐 | 15344/15344 匹配 |
| actual_mw 最大差 | 2.8e-14（浮点误差）|
| pred_mw 最大差 | **5.0e-05**（仅四舍五入）|
| 站点一致性 | **68/68 PASS** |

---

## 五、页面文案修正

将前端 HTML 中过时的说明文字更新：

| 位置 | 旧文字 | 新文字 |
|------|--------|--------|
| hint 区块 | "典型日10-14"会自动选择一个10-14点表现接近中位数的代表日期 | "四季最佳日"会选择该季节日级 NRMSE 最低的一天 |
| 四季按钮 hover | 选择当前站点该季节预测效果最好的一天；全市模式：选择全市该季节预测效果最好的一天 | 单站点模式：选择该站点该季节日级 NRMSE 最低的一天；全市模式：选择全市该季节日级 NRMSE 最低的一天 |
| 典型日 hover | 自动选择一个10-14点表现接近中位数的典型日期 | 自动选择全市该季节日级 NRMSE 最低的一天 |

---

## 六、产出文件

| 文件 | 操作 | 用途 |
|------|------|------|
| `scripts/round40_compare_final_prediction_metrics.py` | 新建 | 指标对比（power_pred_final / power_pred_cal / power_pred）|
| `scripts/round40_guard_final_prediction.py` | 新建 | 自动守门（4 项检查）|
| `scripts/check_dashboard_city_series_consistency_round40.py` | 新建 | PKL 与 city_series.json 一致性校验 |
| `scripts/apply_round36_calibration.py` | 修改 | 新增 Round40 小时级最终列选择逻辑 |
| `scripts/export_interactive_dashboard_data.py` | 修改 | 强制使用 power_pred_final 统一导出 |
| `stages/05_visualization/interactive_forecast_dashboard.html` | 修改 | hint 文字修正 |

---

## 七、守门指标 CSV 回传

```
output/pv_pipeline/metrics/round40_prediction_column_compare_summary.csv
output/pv_pipeline/metrics/round40_prediction_column_compare_hourly.csv
output/pv_pipeline/metrics/round40_final_prediction_guard.csv
output/pv_pipeline/metrics/round40_dashboard_city_series_consistency.csv
```

---

## 八、验收地址

```
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round40
```

Ctrl + Shift + R 强制刷新后验收：

1. 全市 2025-09-01 至 2025-12-31，06:00 至 19:00，6/7/18/19 点预测不再长期贴 0
2. 全市四季最佳日按钮 → 选择全市该季节 NRMSE 最低日
3. 单站点四季最佳日按钮 → 选择当前站点该季节 NRMSE 最低日，站点下拉框保持显示
4. 从全市点击典型站点 → 站点下拉框显示，站点名和曲线标题一致
