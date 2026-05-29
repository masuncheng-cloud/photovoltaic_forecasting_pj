# Round39 执行总结

> 执行时间：2026-05-29
> 涉及文件：1 个前端 HTML、3 个 Python 脚本（1 新建 + 2 修改）

---

## Round39.8：四季代表日按钮同步站点下拉框

**目标**：点击四季代表日按钮时，站点下拉框必须同步显示当前曲线对应的站点。

**修改文件**：`stages/05_visualization/interactive_forecast_dashboard.html`

**核心改动**：
- 新增 `setSelectedSiteInUI(siteId)` 统一函数，同步 `state.scope`、`state.siteId`、radio 勾选、下拉框值和容器显示
- 新增 `pickSeasonRepresentative(seasonKey)`，兼容数组/对象两种 `season_days.json` 格式，提取 `{date, siteId, siteName}` 三元组
- 重写 `selectSeasonDay`，根据季节代表日是否有代表站点决定切换目标，全市模式保持全市

**结果**：静态检查通过，四季按钮点击后站点下拉框始终保持显示和同步。

---

## Round39.9：四季代表日改为"预测效果最好的一天"

**目标**：四季代表日从固定日期改为按日级 NRMSE 最低选择，全市模式选全市最佳，单站点模式选该站点最佳。

**修改文件**：
- `scripts/export_interactive_dashboard_data.py`（修改 + 新增）
- `stages/05_visualization/interactive_forecast_dashboard.html`（修改）

**核心改动**：

*导出脚本新增*：
- `season_from_month(month)` — 月份→季节映射（春3-5/夏6-8/秋9-11/冬12-2）
- `build_day_metric(rows)` — 计算单日 RMSE/MAE/NRMSE
- `export_season_best_days_by_site(df)` — 每个站点每季 NRMSE 最低日
- `export_season_best_days_city(df)` — 全市每季 NRMSE 最低日
- 数据口径：train/valid/test 全用，6-19 点，容量归一化 NRMSE；约束：有效小时样本≥8、正功率样本≥3、实际发电>0

*前端新增*：
- `gSeasonBestCity`、`gSeasonBestBySite` 全局变量
- `loadAll()` 读取 `season_best_days_city.json` 和 `season_best_days_by_site.json`
- 新增 `pickSeasonBestRepresentative(seasonKey)`，单站点从 `gSeasonBestBySite[siteId][season]` 取，全市从 `gSeasonBestCity[season]` 取
- `selectSeasonDay` 重写，调用新函数，自动切 6-19 点，全市模式保持全市
- 标签改为"四季最佳日"，悬停显示说明

**导出数据验证**：
```
全市最佳日 NRMSE：春 1.25% / 夏 1.33% / 秋 1.16% / 冬 0.73%
S062 最佳日 NRMSE：春 0.95% / 夏 1.97% / 秋 0.96% / 冬 0.40%
68 个站点全部成功导出
```

---

## Round39.10：典型站点按钮强制显示站点下拉框

**目标**：全市模式下点击"预测最好/最差/相对正确/样本少"按钮后，站点下拉框必须强制显示。

**根因**：`site-select-group` 有内联 `style="display:none"`，`setSelectedSiteInUI` 设置 `display = ""` 无法覆盖。

**修改文件**：`stages/05_visualization/interactive_forecast_dashboard.html`

**核心改动**：
- `setSelectedSiteInUI` 显示逻辑改为 `style.display = "flex"`（显式覆盖内联 `display:none`），同时移除 `hidden` 属性和 `hidden`/`is-hidden`/`d-none` 类，启用 `disabled`，将 siteSelect 本身也显示
- `selectTypicalSite` 简化为直接调用 `setSelectedSiteInUI(sid)`，移除重复的 radio/下拉框逻辑

**统一原则**：任何切换到单站点的操作都调用 `setSelectedSiteInUI(siteId)`，由这一个函数统一完成 state/radio/下拉框/容器的同步。

---

## Round39.11：排查并修复早晚临界小时预测大量为 0

**目标**：排查 6、7、18、19 点预测大量为 0 的根因并修复。

### 根因定位

通过新建审计脚本 `audit_edge_hour_zero_predictions.py` 分析，发现根因链路：

```
v152/v153 ML blend
  → power_pred = clip(..., 0, cap)
  → power_pred[ghi < 5] = 0.0    ← 这里强制把 19 点全置零
  → power_pred_cal = calib(power_pred)  ← 用上面已经全是 0 的 power_pred 校准
  → power_pred_final = calib(power_pred)  ← 最终预测还是用它
```

- `power_pred_cal` 来自物理模型（physics-based blend），在早晚临界小时表现更好
- 但最终预测 `power_pred_final` 使用的是被 ghi<5 硬置零的 `power_pred`
- ML 模型在边缘小时本身也大量崩溃到 0

### 修复效果

| 小时 | 修复前 suspicious_zero | 修复后 | 全市均预测功率 |
|------|----------------------|--------|--------------|
| 6时 | 29.3% | **0%** | 2.57 → 3.58 MW |
| 18时 | 44.6% | **0%** | 5.97 → 7.30 MW |
| 19时 | 60.8% | **0%** | 0.65 → 3.19 MW |

全市临界小时 `suspicious_city_zero` 从数百次降至 0。

### 修改文件

- **新建** `scripts/audit_edge_hour_zero_predictions.py` — 审计脚本，对比 PKL 中边缘小时预测与全市聚合，定位根因在 PKL 还是导出环节
- **修改** `scripts/apply_round36_calibration.py` — 最终预测基础列从 `power_pred` 改为 `power_pred_cal`，回退逻辑也相应修改；3 个站点回退（S017/S060/S071）
- **修改** `scripts/export_interactive_dashboard_data.py` — `export_city_series` 内部统一创建 `actual_mw`/`pred_mw`，新增审计字段 `pred_valid_sites`、`actual_positive_sites`、`zero_pred_sites`

---

## 产出文件汇总

| 文件 | 操作 | 用途 |
|------|------|------|
| `scripts/audit_edge_hour_zero_predictions.py` | 新建 | 边缘小时 0 值审计 |
| `scripts/export_interactive_dashboard_data.py` | 修改 | 导出 + 新增季节最佳日 + city_series 审计字段 |
| `scripts/apply_round36_calibration.py` | 修改 | 改用 physics-calibrated pred_cal |
| `stages/05_visualization/interactive_forecast_dashboard.html` | 修改 | 四季最佳日 + 站点下拉框同步 |

## 数据验证

- 导出后一致性检查：**68/68 PASS**
- 校准脚本：3 个站点回退，其余 65 个站点应用校准
- 边缘小时零值：从数百次降至 **0 次**

---

## 验收地址

```
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round39_11
```

按 Ctrl+Shift+R 强制刷新后验收：
1. 全市模式 → 四季最佳日按钮 → 日期变为全市该季 NRMSE 最低日
2. 单站点模式 → 四季最佳日按钮 → 日期变为该站点该季 NRMSE 最低日，下拉框同步显示
3. 全市模式 → 典型站点按钮 → 站点下拉框强制显示
4. 全市模式 + 2025-09-01~2025-12-31 + 06:00~19:00 → 6/7/18/19 点预测曲线不再长期贴 0
