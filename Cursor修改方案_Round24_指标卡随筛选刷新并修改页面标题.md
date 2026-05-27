# Cursor 修改方案 Round24：指标卡随筛选刷新，并修改页面标题

## 一、修改目标

当前可视化页面中，切换日期、小时、全市/单站点、典型站点按钮后，折线图会变化，但上方指标卡中的：

- 样本数
- 站点数
- 实际总电量
- 预测总电量
- PRED/ACTUAL
- MAE
- RMSE
- NRMSE
- BIAS

可能仍然使用固定汇总值，导致“样本数”和“站点数”始终不变。

本轮目标：

1. 指标卡必须基于当前筛选后的折线图数据实时重算。
2. 全市模式和单站点模式分别使用正确口径。
3. 点击“当前日期10-14”“典型日10-14”、四季按钮、日期变化、小时变化、站点变化后，指标卡必须同步变化。
4. 将页面标题和相关文案：

```text
光伏功率预测交互式结果页面
```

改为：

```text
光伏功率预测交互式结果展示
```

本轮不重新训练模型，不修改预测 pkl，只修改前端逻辑和可视化导出元数据。

## 二、涉及文件

主要修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
scripts/export_interactive_dashboard_data.py
```

如果 JS/CSS 已拆分，则同步修改：

```text
stages/05_visualization/*.js
stages/05_visualization/*.css
```

## 三、问题原因

现在指标卡很可能使用了：

```js
site_metrics.json 中某个站点的固定指标
index.json 中的固定总数
默认站点的 rows
```

而不是使用当前图表已经筛选后的 `rows` 重算。

正确逻辑必须是：

```text
用户筛选条件变化
  -> 得到当前 rows
  -> 用 rows 画折线图
  -> 用同一批 rows 重算指标卡
```

不要让指标卡再单独读取固定汇总。

## 四、统一指标卡刷新入口

在 `interactive_forecast_dashboard.html` 中搜索：

```text
updateMetricCards
renderMetricCards
summary-card
sample_count
n_sites
actual_mw
pred_mw
refreshAll
drawLineChart
```

将指标卡更新统一为一个函数。

### 4.1 新增工具函数

```js
function toNumber(v, fallback = 0) {
  const x = Number(v);
  return Number.isFinite(x) ? x : fallback;
}

function sumBy(rows, key) {
  return rows.reduce((acc, r) => acc + toNumber(r[key], 0), 0);
}

function maxBy(rows, key) {
  if (!rows.length) return 0;
  return Math.max(...rows.map(r => toNumber(r[key], 0)));
}

function meanBy(rows, key) {
  const vals = rows.map(r => toNumber(r[key], NaN)).filter(Number.isFinite);
  if (!vals.length) return 0;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function formatRatio(v) {
  const x = Number(v);
  if (!Number.isFinite(x) || Math.abs(x) > 99) return "-";
  return x.toFixed(2);
}
```

### 4.2 新增当前 rows 指标计算函数

```js
function computeCurrentMetrics(rows, scope) {
  if (!rows || !rows.length) {
    return {
      sampleCount: 0,
      siteCount: 0,
      actualMwh: 0,
      predMwh: 0,
      predActualRatio: null,
      maeMw: 0,
      rmseMw: 0,
      nrmsePct: 0,
      biasPct: 0,
    };
  }

  const actual = sumBy(rows, "actual_mw");
  const pred = sumBy(rows, "pred_mw");
  const actualSafe = Math.abs(actual) > 1e-9 ? actual : null;

  // 说明：
  // city_series 每行是一个时间点的城市聚合值，sample_count 表示该时间点参与聚合的站点样本数。
  // site_series 每行是一个站点一个时间点，rows.length 就是样本数。
  const sampleCount = scope === "city"
    ? Math.round(sumBy(rows, "sample_count"))
    : rows.length;

  const siteCount = scope === "city"
    ? Math.round(maxBy(rows, "n_sites"))
    : 1;

  const errors = rows.map(r => toNumber(r.pred_mw) - toNumber(r.actual_mw));
  const absErrors = errors.map(Math.abs);
  const mae = absErrors.length
    ? absErrors.reduce((a, b) => a + b, 0) / absErrors.length
    : 0;
  const rmse = errors.length
    ? Math.sqrt(errors.reduce((a, b) => a + b * b, 0) / errors.length)
    : 0;

  // NRMSE 分母：
  // city 模式使用当前时间点城市总容量均值；
  // station 模式使用当前站点容量均值。
  const capacityDenom = scope === "city"
    ? meanBy(rows, "capacity_sum_mw")
    : meanBy(rows, "capacity_mw");

  const nrmsePct = capacityDenom > 0 ? rmse / capacityDenom * 100 : 0;
  const predActualRatio = actualSafe ? pred / actualSafe : null;
  const biasPct = actualSafe ? (pred - actual) / actualSafe * 100 : null;

  return {
    sampleCount,
    siteCount,
    actualMwh: actual,
    predMwh: pred,
    predActualRatio,
    maeMw: mae,
    rmseMw: rmse,
    nrmsePct,
    biasPct,
  };
}
```

注意：

- `actual_mw`、`pred_mw` 是小时功率值。按小时数据直接求和时，数值可解释为近似 MWh，因为时间间隔为 1 小时。
- 全市模式的样本数不要用 `rows.length`，而应使用 `sum(sample_count)`。
- 全市模式的站点数不要固定为 1，应使用 `max(n_sites)`。
- 单站点模式站点数为 1。

## 五、修改指标卡渲染函数

找到当前渲染指标卡的函数，替换为：

```js
function updateMetricCards(rows) {
  const metrics = computeCurrentMetrics(rows, state.scope);

  setCardValue("sample-count", formatInteger(metrics.sampleCount));
  setCardValue("site-count", formatInteger(metrics.siteCount));
  setCardValue("actual-total", `${formatNumber(metrics.actualMwh, 2)} MWh`);
  setCardValue("pred-total", `${formatNumber(metrics.predMwh, 2)} MWh`);
  setCardValue("pred-actual-ratio", formatRatio(metrics.predActualRatio));
  setCardValue("mae", `${formatNumber(metrics.maeMw, 2)} MW`);
  setCardValue("rmse", `${formatNumber(metrics.rmseMw, 2)} MW`);
  setCardValue("nrmse", `${formatNumber(metrics.nrmsePct, 2)}%`);
  setCardValue("bias", metrics.biasPct === null ? "-" : `${formatNumber(metrics.biasPct, 2)}%`);
}
```

如果当前页面卡片 ID 不一致，请按实际 ID 对应修改。建议统一为：

```html
<div id="sample-count"></div>
<div id="site-count"></div>
<div id="actual-total"></div>
<div id="pred-total"></div>
<div id="pred-actual-ratio"></div>
<div id="mae"></div>
<div id="rmse"></div>
<div id="nrmse"></div>
<div id="bias"></div>
```

辅助函数：

```js
function setCardValue(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}
```

## 六、修改 `refreshAll`

找到 `refreshAll()`，确保它的核心流程是：

```js
function refreshAll() {
  if (!validateDateRange(true)) {
    return;
  }

  const rows = getCurrentFilteredRows();

  drawLineChart(rows);
  updateMetricCards(rows);
  renderHourlyTable?.(rows);
  renderOtherViews?.();
}
```

如果当前没有 `getCurrentFilteredRows()`，就把原来筛选并传给 `drawLineChart(rows)` 的那批 rows 直接传给 `updateMetricCards(rows)`。

重点：

```js
drawLineChart(rows);
updateMetricCards(rows);
```

必须使用同一个 `rows`。

## 七、确认筛选函数正确

当前 rows 必须同时受这些条件影响：

- 展示对象：全市 / 单站点
- 单站点 ID
- 开始日期
- 结束日期
- 开始小时
- 结束小时
- 当前日期10-14
- 典型日10-14
- 四季按钮

推荐筛选逻辑：

```js
function getCurrentFilteredRows() {
  const source = state.scope === "city"
    ? gCitySeries
    : (gSiteSeriesById[state.stationId] || []);

  return source.filter(r => {
    const date = String(r.date || "").slice(0, 10);
    const hour = Number(r.hour);
    return date >= state.startDate
      && date <= state.endDate
      && hour >= Number(state.startHour)
      && hour <= Number(state.endHour);
  });
}
```

如果页面还需要排除 `future`，可以加：

```js
&& r.split !== "future"
```

但 Round23 后 JSON 已经不应包含 `future`。

## 八、修改按钮逻辑后必须刷新指标卡

这些事件触发后都必须走 `refreshAll()`：

```text
日期年月日变化
小时变化
刷新按钮
展示对象 radio 变化
站点下拉框变化
预测最好/预测最差/相对正确/样本少
当前日期10-14
典型日10-14
春季/夏季/秋季/冬季
```

不要只调用 `drawLineChart()`。

错误写法：

```js
drawLineChart(rows);
```

正确写法：

```js
drawLineChart(rows);
updateMetricCards(rows);
```

或统一：

```js
refreshAll();
```

## 九、标题文案修改

### 9.1 修改 HTML 标题

搜索：

```text
光伏功率预测交互式结果页面
```

全部替换为：

```text
光伏功率预测交互式结果展示
```

包括：

```html
<title>光伏功率预测交互式结果展示</title>
<h1>光伏功率预测交互式结果展示</h1>
```

### 9.2 修改导出脚本 `index.json`

在 `scripts/export_interactive_dashboard_data.py` 中搜索：

```python
"title": "光伏功率预测交互式结果页面"
```

改为：

```python
"title": "光伏功率预测交互式结果展示"
```

如有 description 也同步改：

```python
"description": "展示连云港光伏电站真实功率与预测功率对比"
```

description 可以保持不变。

## 十、重新生成可视化 JSON

执行：

```bash
cd /path/to/photovoltaic_forecasting_pj
python scripts/export_interactive_dashboard_data.py \
  --output-root output/pv_pipeline \
  --dashboard-root output/pv_pipeline/interactive_dashboard
```

不需要重新训练。

## 十一、启动验证

```bash
cd /path/to/photovoltaic_forecasting_pj
python -m http.server 8060
```

打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

## 十二、验收步骤

### 12.1 全市模式

1. 选择“全市”。
2. 日期选 `2023-01-01` 至 `2023-01-10`。
3. 小时选 `6` 至 `19`。
4. 记录样本数和站点数。
5. 改为 `2023-01-01` 至 `2023-01-02`。
6. 样本数必须明显减少。
7. 站点数应显示当前时间范围内参与聚合的站点数量，不应固定为 1。

### 12.2 当前日期10-14

1. 日期选 `2023-09-01` 至 `2023-09-20`。
2. 点击“当前日期10-14”。
3. 样本数应约等于：

```text
日期天数 × 5小时 × 当期可用站点数
```

4. 站点数应为全市聚合参与站点数，不应为 1。

### 12.3 单站点模式

1. 选择“单站点”。
2. 默认站点自动出现。
3. 样本数应等于当前筛选后该站点的时间点数量。
4. 站点数应为 1。
5. 切换站点后，指标卡变化。

### 12.4 日期变化

1. 改开始日期，指标卡刷新。
2. 改结束日期，指标卡刷新。
3. 改小时范围，指标卡刷新。

### 12.5 页面标题

确认浏览器标签页、页面主标题、`index.json` 中标题均为：

```text
光伏功率预测交互式结果展示
```

## 十三、验收标准

本轮通过标准：

- 指标卡不再固定不变。
- 样本数随日期、小时、站点、全市/单站点切换变化。
- 全市模式站点数不再显示为 1。
- 当前日期10-14 后，样本数和站点数符合筛选口径。
- 单站点模式站点数显示为 1。
- 页面标题已改为“光伏功率预测交互式结果展示”。
- 页面正常打开，折线图正常显示。
- 不重新训练，不改模型结果。

