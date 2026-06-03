# Cursor执行方案 Round91_1：典型日期与四季最佳日交互修复

## 目标

本轮继续修改可视化页面交互，不改模型、不重训、不改变预测结果。

需要修复的问题：

1. 当前日期范围是 `2025-01-01 ~ 2025-12-31`，但“春季”按钮仍不可用。
2. 顶部按钮组名称从 `表现日` 改为 `典型日期`。
3. 去掉 `样本最少日` 按钮。
4. 点击 `典型日期` 里的 `最佳日 / 最差日 / 典型日` 时，图表和指标应切换到对应日期，但日期选择框里的年月日不能被改写。
5. 点击 `四季最佳日` 里的 `春季 / 夏季 / 秋季 / 冬季` 时，图表和指标应切换到对应季节最佳日，但日期选择框里的年月日不能被改写。
6. 四季定义固定为：
   - 春季：3、4、5 月
   - 夏季：6、7、8 月
   - 秋季：9、10、11 月
   - 冬季：12、1、2 月

本轮命名规则：

```text
Round91_1
```

之后如果仍是样式或可视化交互微调，继续使用：

```text
Round91_2
Round91_3
...
```

---

## 一、备份

在项目根目录执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

mkdir -p archive/round91_1_visual_interaction_fix/current_state

cp -a stages/05_visualization/interactive_forecast_dashboard.html \
  archive/round91_1_visual_interaction_fix/current_state/interactive_forecast_dashboard.before_round91_1.html

cp -a scripts/export_interactive_dashboard_data.py \
  archive/round91_1_visual_interaction_fix/current_state/export_interactive_dashboard_data.before_round91_1.py

cp -a output/pv_pipeline/interactive_dashboard \
  archive/round91_1_visual_interaction_fix/current_state/interactive_dashboard.before_round91_1
```

---

## 二、修改按钮组名称与按钮数量

修改文件：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

### 2.1 将“表现日”改为“典型日期”

搜索：

```bash
grep -n "表现日\\|典型日期\\|最佳日\\|最差日\\|样本最少" \
  stages/05_visualization/interactive_forecast_dashboard.html
```

将：

```html
<span class="ctrl-label" id="performance-group-label">表现日：</span>
```

改为：

```html
<span class="ctrl-label" id="performance-group-label">典型日期：</span>
```

如果 JS 里有动态设置：

```javascript
groupLabel.textContent = "表现日：";
```

同步改为：

```javascript
groupLabel.textContent = "典型日期：";
```

### 2.2 去掉“样本最少日”按钮

删除或注释 HTML 中的按钮：

```html
<button ... id="btn-low">样本最少日</button>
```

同时删除或禁用对应事件绑定：

```javascript
document.getElementById("btn-low")...
```

删除相关 label 和 tooltip：

```javascript
"btn-low": ...
```

最终 `典型日期` 下只保留：

```text
最佳日
最差日
典型日
```

### 2.3 更新 tooltip

将 tooltip 修改为：

```javascript
function updatePerformanceButtonTooltips() {
  const scopeName = state.scope === "site" ? "当前站点" : "全市";

  const tips = {
    "btn-best": `${scopeName}日级 NRMSE 最低的一天；只切换图表展示，不改写日期选择框`,
    "btn-worst": `${scopeName}日级 NRMSE 最高的一天；只切换图表展示，不改写日期选择框`,
    "btn-normal": `${scopeName}日级 NRMSE 接近中位数且总量偏差较小的一天；只切换图表展示，不改写日期选择框`,
  };

  Object.entries(tips).forEach(([id, title]) => {
    const btn = document.getElementById(id);
    if (btn) btn.title = title;
  });
}
```

---

## 三、核心修复：快捷按钮不改写日期选择框

现在的问题本质是：快捷按钮直接调用了 `setDateRange(day, day)`，所以会把顶部日期选择框也改掉。

本轮要把“用户手动选择的日期范围”和“快捷按钮临时展示的日期范围”分开。

### 3.1 在 state 中新增 quickRange

搜索 `const state = {` 或 `let state = {`。

加入字段：

```javascript
quickRange: null,
quickLabel: "",
```

含义：

- `state.quickRange = null`：使用日期选择框中的范围。
- `state.quickRange = { startDate: "2025-04-15", endDate: "2025-04-15" }`：图表临时展示该日期，但不改写日期选择框。
- `state.quickLabel`：用于说明当前图表为什么切到了某一天。

### 3.2 新增获取有效筛选范围函数

新增函数：

```javascript
function getActiveDateRange() {
  if (state.quickRange && state.quickRange.startDate && state.quickRange.endDate) {
    return {
      startDate: state.quickRange.startDate,
      endDate: state.quickRange.endDate,
    };
  }

  return {
    startDate: getDateInputValue("start"),
    endDate: getDateInputValue("end"),
  };
}
```

如果当前项目没有 `getDateInputValue()`，就按现有读取年月日选择框的函数替换。重点是：

```text
图表筛选用 getActiveDateRange()
日期框显示仍由日期输入控件自己决定
```

### 3.3 修改过滤逻辑使用 active range

搜索所有直接读取日期选择框的过滤逻辑，例如：

```javascript
const startDate = ...
const endDate = ...
rows.filter(...)
```

把用于图表和指标计算的日期范围改为：

```javascript
const { startDate, endDate } = getActiveDateRange();
```

重点函数通常包括：

```text
filterCitySeries()
filterSiteSeries()
refreshAll()
computeMetrics()
renderLineChart()
```

确保这些函数筛选数据时使用 `getActiveDateRange()`。

### 3.4 快捷按钮只设置 quickRange，不改日期框

找到 `最佳日 / 最差日 / 典型日` 的点击逻辑。

不要再调用：

```javascript
setDateRange(day.date, day.date);
```

改成：

```javascript
function applyQuickDate(date, label) {
  if (!date) {
    alert("当前范围内没有可用的典型日期数据。");
    return;
  }

  state.quickRange = {
    startDate: date,
    endDate: date,
  };
  state.quickLabel = label || "";
  refreshAll();
}
```

按钮事件示例：

```javascript
document.getElementById("btn-best").addEventListener("click", () => {
  const day = findPerformanceDay("best");
  applyQuickDate(day?.date, "已切换到最佳日");
});

document.getElementById("btn-worst").addEventListener("click", () => {
  const day = findPerformanceDay("worst");
  applyQuickDate(day?.date, "已切换到最差日");
});

document.getElementById("btn-normal").addEventListener("click", () => {
  const day = findPerformanceDay("normal");
  applyQuickDate(day?.date, "已切换到典型日");
});
```

### 3.5 用户手动改日期时清空 quickRange

给所有日期选择框的 change 事件加入：

```javascript
function clearQuickRange() {
  state.quickRange = null;
  state.quickLabel = "";
}
```

日期选择框 change 时：

```javascript
clearQuickRange();
refreshAll();
```

刷新按钮点击时也建议清空：

```javascript
clearQuickRange();
refreshAll();
```

这样逻辑清楚：

- 用户选日期：用用户日期；
- 用户点快捷按钮：临时看某一天；
- 用户再改日期：回到手动日期。

---

## 四、修复四季最佳日可用性

### 4.1 固定四季月份映射

新增或替换季节判断函数：

```javascript
function getSeasonByMonth(month) {
  const m = Number(month);
  if ([3, 4, 5].includes(m)) return "spring";
  if ([6, 7, 8].includes(m)) return "summer";
  if ([9, 10, 11].includes(m)) return "autumn";
  if ([12, 1, 2].includes(m)) return "winter";
  return null;
}
```

中文名称：

```javascript
const seasonNames = {
  spring: "春季",
  summer: "夏季",
  autumn: "秋季",
  winter: "冬季",
};
```

### 4.2 不要用当前起止月份简单判断季节是否可用

春季不可用的常见原因是：代码只看当前日期范围的起止月，或者冬季跨年逻辑把 1、2 月处理错。

本轮要求：季节按钮是否可用，应根据“当前日期范围内实际是否存在该季节数据”判断，而不是只看起止月。

实现函数：

```javascript
function hasSeasonData(rows, season) {
  const arr = Array.isArray(rows) ? rows : [];
  const { startDate, endDate } = getManualDateRange();

  return arr.some((r) => {
    const dateStr = String(r.date || r.datetime || r.time || "").slice(0, 10);
    if (!dateStr) return false;
    if (dateStr < startDate || dateStr > endDate) return false;

    const month = Number(dateStr.slice(5, 7));
    return getSeasonByMonth(month) === season;
  });
}
```

注意这里用 `getManualDateRange()`，不是 `getActiveDateRange()`。

原因：

- 四季按钮是否可用，应由用户日期框中的大范围决定；
- 点击四季按钮后会产生 `quickRange`，不能因为 quickRange 是某一天就把其他季节按钮变灰。

如果当前没有 `getManualDateRange()`，新增：

```javascript
function getManualDateRange() {
  return {
    startDate: getDateInputValue("start"),
    endDate: getDateInputValue("end"),
  };
}
```

### 4.3 四季按钮选择逻辑

点击四季按钮时：

1. 取当前手动日期范围；
2. 在该范围内筛选对应季节；
3. 按当前 scope 选择该季节里日级 NRMSE 最低的一天；
4. 调用 `applyQuickDate()`；
5. 不改写日期选择框。

示例：

```javascript
function applySeasonBestDay(season) {
  const day = findSeasonBestDay(season, {
    scope: state.scope,
    siteId: state.scope === "site" ? state.siteId : null,
    dateRange: getManualDateRange(),
  });

  if (!day || !day.date) {
    alert(`当前日期范围内没有可用的${seasonNames[season]}最佳日数据。`);
    return;
  }

  applyQuickDate(day.date, `已切换到${seasonNames[season]}最佳日`);
}
```

### 4.4 修复春季按钮灰色问题

更新按钮可用性函数：

```javascript
function updateSeasonButtonsAvailability() {
  const rows = state.scope === "site"
    ? (Array.isArray(gCurrentSiteRows) ? gCurrentSiteRows : [])
    : (Array.isArray(gCitySeries) ? gCitySeries : []);

  ["spring", "summer", "autumn", "winter"].forEach((season) => {
    const btn = document.getElementById(`btn-season-${season}`);
    if (!btn) return;

    const available = hasSeasonData(rows, season);
    btn.disabled = !available;
    btn.classList.toggle("is-disabled", !available);
    btn.title = available
      ? `切换到当前日期范围内${seasonNames[season]}日级 NRMSE 最低的一天；不改写日期选择框`
      : `当前日期范围内没有${seasonNames[season]}可用数据`;
  });
}
```

如果按钮 id 不是 `btn-season-spring` 这种，请按现有 id 替换。

验收点：

```text
日期框为 2025-01-01 ~ 2025-12-31 时：
春季、夏季、秋季、冬季都应该可点击。
```

---

## 五、说明文字同步修改

将页面上方说明从类似：

```text
"当前日期10-14"只筛选当前日期范围内的全市10-14点数据；"四季最佳日"会选择该季节日级 NRMSE 最低的一天。
```

改为：

```text
"当前日期10-14"只按日期框范围筛选10-14点数据；"典型日期"和"四季最佳日"只临时切换图表展示日期，不改写日期选择框。
```

如果内容太长，可以更短：

```text
典型日期和四季最佳日只切换图表展示，不改写日期选择框。
```

---

## 六、检查是否还有样本最少相关残留

执行：

```bash
grep -R "样本最少\\|btn-low\\|low-sample\\|sample-low" \
  stages/05_visualization/interactive_forecast_dashboard.html \
  scripts/export_interactive_dashboard_data.py
```

要求：

- 页面按钮不再出现 `样本最少日`。
- 如果导出脚本仍生成样本少分类表，可以保留，因为下方典型站点表可能还需要。
- 但顶部快捷按钮不应再引用 `btn-low`。

---

## 七、重新导出可视化数据

本轮理论上只改前端，不需要重训。

但为了避免旧数据缓存，重新导出一次：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/export_interactive_dashboard_data.py
```

如果导出脚本没有变化，也要执行一次，确保 `metadata.json` 时间更新。

---

## 八、启动与强制刷新

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
python -m http.server 8070
```

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round91_1
```

浏览器强制刷新：

```text
Ctrl + Shift + R
```

Safari 建议：

```text
Option + Command + R
```

---

## 九、验收清单

### 9.1 顶部按钮

必须满足：

- `表现日` 已改为 `典型日期`。
- 顶部只显示：

```text
典型日期：最佳日 最差日 典型日
```

- 不再显示：

```text
样本最少日
```

### 9.2 四季按钮

设置日期范围：

```text
2025-01-01 ~ 2025-12-31
```

必须满足：

- 春季可点击；
- 夏季可点击；
- 秋季可点击；
- 冬季可点击。

季节口径：

```text
春季 = 3-5月
夏季 = 6-8月
秋季 = 9-11月
冬季 = 12-2月
```

### 9.3 点击典型日期按钮

在日期框保持：

```text
2025-01-01 ~ 2025-12-31
```

点击：

```text
最佳日
最差日
典型日
```

必须满足：

- 图表和指标切换到对应日期；
- 日期选择框仍显示 `2025-01-01 ~ 2025-12-31`；
- 样本数变为对应临时展示日期的样本数；
- 全量样本数不变。

### 9.4 点击四季最佳日按钮

在日期框保持：

```text
2025-01-01 ~ 2025-12-31
```

点击：

```text
春季
夏季
秋季
冬季
```

必须满足：

- 图表和指标切换到对应季节最佳日；
- 日期选择框仍显示 `2025-01-01 ~ 2025-12-31`；
- 春季按钮不能灰掉；
- 如果某季确实无数据，才允许灰掉并显示 tooltip 说明。

### 9.5 手动修改日期

手动把日期改成：

```text
2025-09-01 ~ 2025-12-31
```

必须满足：

- 清空快捷日期状态；
- 图表重新显示手动日期范围；
- 春季按钮灰掉是合理的，因为当前手动范围不含 3-5 月。

---

## 十、失败回退

如果页面卡死、一直加载、图表不显示，执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

cp -a archive/round91_1_visual_interaction_fix/current_state/interactive_forecast_dashboard.before_round91_1.html \
  stages/05_visualization/interactive_forecast_dashboard.html

cp -a archive/round91_1_visual_interaction_fix/current_state/export_interactive_dashboard_data.before_round91_1.py \
  scripts/export_interactive_dashboard_data.py

rm -rf output/pv_pipeline/interactive_dashboard
cp -a archive/round91_1_visual_interaction_fix/current_state/interactive_dashboard.before_round91_1 \
  output/pv_pipeline/interactive_dashboard
```

---

## 十一、执行报告

新建：

```text
docs/Round91_1_典型日期与四季最佳日交互修复报告.md
```

内容模板：

```markdown
# Round91_1 典型日期与四季最佳日交互修复报告

## 1. 修改原因

- 日期范围覆盖全年时春季按钮仍不可用。
- “表现日”命名不够准确。
- “样本最少日”按钮当前使用价值低，且容易增加解释成本。
- 快捷按钮会改写日期选择框，导致用户分不清是手动筛选还是临时查看。

## 2. 修改内容

- “表现日”改为“典型日期”。
- 删除“样本最少日”按钮。
- 四季固定为春 3-5、夏 6-8、秋 9-11、冬 12-2。
- 新增 quickRange 状态，快捷按钮只切换图表，不改写日期选择框。
- 手动修改日期时自动清空 quickRange。

## 3. 验证结果

- 2025-01-01 ~ 2025-12-31 下，春夏秋冬均可点击。
- 点击最佳日、最差日、典型日后，日期框不变，图表切换。
- 点击春夏秋冬后，日期框不变，图表切换。
- 手动修改日期后，图表回到手动日期范围。

## 4. 影响范围

本轮只修改可视化页面交互逻辑，不改变训练结果、不改变预测文件、不重训。
```

---

## 十二、注意事项

1. 不要为了让春季可点击而硬编码按钮永远 enabled，必须根据当前手动日期范围内是否存在对应季节数据判断。
2. 不要让快捷按钮继续调用会改写日期选择框的 `setDateRange()`。
3. 不要删除下方典型站点表里的“样本少”分类，本轮只删除顶部快捷按钮。
4. 不要重训。
5. 如果页面出现“正在加载数据，请稍候...”不消失，优先回滚本轮 HTML，再分小步排查 JS 语法错误。
