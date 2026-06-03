# Round91_1 典型日期与四季最佳日交互修复报告

## 1. 修改原因

- 日期范围覆盖全年时春季按钮仍不可用（winter 跨年逻辑问题导致 1、2 月未被计入冬季）。
- "表现日"命名不够准确，应为"典型日期"。
- "样本最少日"按钮当前使用价值低，增加解释成本。
- 快捷按钮直接调用 `setDateRange(day.date, day.date)` 会改写日期选择框，导致用户分不清是手动筛选还是临时查看。

## 2. 修改内容

### 2.1 按钮组名称
- HTML 和 JS 中的"表现日："改为"典型日期："。

### 2.2 删除按钮
- 删除"样本最少日"按钮（含 HTML 元素、样式、JS 事件监听）。
- 保留下方典型站点表中的"样本少"分类（不做改动）。

### 2.3 四季固定定义
- 春季：3、4、5 月
- 夏季：6、7、8 月
- 秋季：9、10、11 月
- 冬季：12、1、2 月（修复跨年逻辑，1、2 月正确计入冬季）

### 2.4 新增 quickRange 机制
在 `state` 中新增字段：

```javascript
quickRange: null,   // null | { startDate, endDate }
quickLabel: "",     // 提示文字
```

新增函数：
- `getActiveDateRange()`：返回 quickRange（如有）或手动日期范围，用于图表过滤。
- `getManualDateRange()`：返回手动日期范围，用于四季按钮可用性判断。
- `clearQuickRange()`：清空快捷状态。
- `applyQuickDate(date, label)`：设置 quickRange 并刷新图表。

`filterRowsByCurrentControls` 改为使用 `getActiveDateRange()`。

### 2.5 典型日期按钮改为临时切换
`applyCityPerformanceDay` 和 `applySitePerformanceDay` 改为调用 `applyQuickDate()`，不再调用 `applyDateToControls()`。

### 2.6 四季按钮改为临时切换
`selectSeasonDay` 改为调用 `applyQuickDate()`，不再改写日期选择框。

### 2.7 四季按钮可用性修复
新增 `getSeasonByMonth()` 和 `hasSeasonData()`，四季按钮根据手动日期范围内实际存在的数据判断是否可用（使用 `getManualDateRange()`，而非 `getActiveDateRange()`，避免 quickRange 干扰）。

`setupSeasonButtons` 重写为调用 `updateSeasonButtonsAvailability()`。

### 2.8 日期变化时清空 quickRange
`bindDateComboEvents` 中每次日期变化时调用 `clearQuickRange()`，并更新四季按钮可用性。

### 2.9 刷新按钮清空 quickRange
刷新按钮点击时调用 `clearQuickRange()` 和 `updateSeasonButtonsAvailability()`。

### 2.10 说明文字更新
页面上方提示文字改为："典型日期和四季最佳日只切换图表展示，不改写日期选择框。"

### 2.11 更新调用点
`refreshAll()`、`onScopeChange()` 末尾也调用 `updateSeasonButtonsAvailability()`，确保四季按钮状态随上下文变化同步刷新。

## 3. 数据状态

- 现有数据（`metadata.json`）：生成于 2026-06-03 10:55:13，测试期间 2025-09-01 ~ 2025-12-31。
- 本轮前端修改，不需要重新导出数据（数据未过期）。
- 验收时：使用 2025-09-01 ~ 2025-12-31，夏季/秋季/冬季应可点击，春季应灰掉（因数据不含 3-5 月）。

## 4. 验证结果

（待用户在浏览器中验证）

验收清单：
- `典型日期：最佳日 最差日 典型日`（无样本最少日）。
- 日期框 2025-09-01 ~ 2025-12-31 时，夏季/秋季/冬季可点击，春季灰掉。
- 点击"最佳日/最差日/典型日"后，图表切换，日期框不变。
- 点击"春季/夏季/秋季/冬季"后，图表切换，日期框不变。
- 手动改日期后，图表回到手动日期范围。
- 刷新后图表回到手动日期范围。

## 5. 影响范围

本轮只修改可视化页面交互逻辑，不改变训练结果、不改变预测文件、不重训。

## 6. 回退方案

如遇问题，执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

cp archive/round91_1_visual_interaction_fix/current_state/interactive_forecast_dashboard.before_round91_1.html \
  stages/05_visualization/interactive_forecast_dashboard.html

cp archive/round91_1_visual_interaction_fix/current_state/export_interactive_dashboard_data.before_round91_1.py \
  scripts/export_interactive_dashboard_data.py
```

## 7. 修改文件清单

| 文件 | 操作 |
|------|------|
| `stages/05_visualization/interactive_forecast_dashboard.html` | 修改 |

## 8. 访问地址

```
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round91_1
```

（强制刷新：Ctrl+Shift+R）
