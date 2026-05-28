# Cursor 修改方案 Round28：单站点模式样本数显示全量历史样本数

## 一、修改目标

当前可视化页面选择“展示对象：单站点”时，指标卡中的“样本数”显示的是当前筛选后的曲线点数，例如：

```text
15,344
```

现在要求改为：

```text
单站点模式下，样本数显示该站点的全量历史样本数。
```

这里“全量历史样本数”按 Round23 后的口径：

```text
train + valid + test，不包含 future
```

本轮只修改前端指标卡显示逻辑，不重新训练，不修改预测结果。

## 二、涉及文件

主要修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

如 JS/CSS 已拆分，则同步修改：

```text
stages/05_visualization/*.js
stages/05_visualization/*.css
```

## 三、口径定义

### 3.1 全市模式

展示对象为“全市”时，样本数仍显示当前筛选范围内参与城市聚合的样本数：

```js
sampleCount = sum(rows.map(r => r.sample_count))
```

即：

```text
当前日期范围 × 当前小时范围 × 当前可用站点
```

### 3.2 单站点模式

展示对象为“单站点”时，样本数不再显示当前筛选曲线点数，而显示当前站点的历史全量样本数：

```text
site_metrics.json 中当前站点的 full_history_rows
```

如果当前字段已按 Round23 修正，则含义为：

```text
train + valid + test，不包含 future
```

如果 `full_history_rows` 缺失，则兜底使用：

```js
rows.length
```

## 四、确认数据字段

检查：

```text
output/pv_pipeline/interactive_dashboard/site_metrics.json
```

确认每个站点有字段：

```json
{
  "site_id": "S017",
  "full_history_rows": 26304,
  "full_history_positive_rows": 5982,
  "full_history_zero_ratio_pct": 77.26
}
```

如果字段存在，前端直接读取。

如果字段不存在，需要先运行：

```bash
python scripts/export_interactive_dashboard_data.py \
  --output-root output/pv_pipeline \
  --dashboard-root output/pv_pipeline/interactive_dashboard
```

## 五、前端新增站点指标查询函数

在 `interactive_forecast_dashboard.html` 的 JS 中新增：

```js
function getSelectedSiteMetric() {
  if (!Array.isArray(gSiteMetrics)) return null;
  const sid = state.stationId || state.selectedStation;
  if (!sid) return null;
  return gSiteMetrics.find(r => String(r.site_id) === String(sid)) || null;
}
```

如果当前全局变量不叫 `gSiteMetrics`，请替换为真实变量名，例如：

```text
siteMetrics
gStationMetrics
gSites
```

## 六、修改 `computeCurrentMetrics`

找到 Round24 中新增或已有的函数：

```js
function computeCurrentMetrics(rows, scope) {
  ...
}
```

将其中样本数计算部分改为：

```js
let sampleCount;

if (scope === "city") {
  sampleCount = Math.round(sumBy(rows, "sample_count"));
} else {
  const siteMetric = getSelectedSiteMetric();
  sampleCount = Number(siteMetric?.full_history_rows);

  if (!Number.isFinite(sampleCount) || sampleCount <= 0) {
    sampleCount = rows.length;
  }
}
```

站点数保持：

```js
const siteCount = scope === "city"
  ? Math.round(maxBy(rows, "n_sites"))
  : 1;
```

完整示例片段：

```js
function computeCurrentMetrics(rows, scope) {
  if (!rows || !rows.length) {
    return {
      sampleCount: 0,
      siteCount: scope === "station" ? 1 : 0,
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

  let sampleCount;
  if (scope === "city") {
    sampleCount = Math.round(sumBy(rows, "sample_count"));
  } else {
    const siteMetric = getSelectedSiteMetric();
    sampleCount = Number(siteMetric?.full_history_rows);
    if (!Number.isFinite(sampleCount) || sampleCount <= 0) {
      sampleCount = rows.length;
    }
  }

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

## 七、修改样本数卡片标题或 tooltip

为了避免误解，建议给样本数卡片加说明。

如果卡片结构支持 `title`，改为：

```html
<div class="metric-card" title="全市模式：当前筛选范围样本数；单站点模式：该站点历史全量样本数（train/valid/test，不含future）。">
  <div class="metric-label">样本数</div>
  <div id="sample-count" class="metric-value"></div>
</div>
```

如果不方便改 HTML，可在 JS 初始化时添加：

```js
const sampleCard = document.getElementById("sample-count")?.closest(".metric-card");
if (sampleCard) {
  sampleCard.title = "全市模式：当前筛选范围样本数；单站点模式：该站点历史全量样本数（train/valid/test，不含future）。";
}
```

## 八、可选：单站点模式显示“当前筛选点数”

如果希望同时保留当前筛选曲线点数，可以在样本数卡片下方加小字：

```text
当前筛选点数：15,344
```

但本轮用户要求只改样本数展示为全量样本数，因此这一步可选，不强制。

如要加：

```js
function updateMetricCards(rows) {
  const metrics = computeCurrentMetrics(rows, state.scope);
  setCardValue("sample-count", formatInteger(metrics.sampleCount));

  const sampleSub = document.getElementById("sample-count-sub");
  if (sampleSub) {
    sampleSub.textContent = state.scope === "station"
      ? `当前筛选点数：${formatInteger(rows.length)}`
      : "";
  }
}
```

## 九、验证步骤

启动页面：

```bash
cd /path/to/photovoltaic_forecasting_pj
python3 -m http.server 8060
```

打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

强制刷新：

```text
Ctrl + Shift + R
```

## 十、验收标准

### 10.1 单站点模式

1. 选择“单站点”。
2. 选择 `S017 富云四队光伏`。
3. 日期任意切换，例如：

```text
2023-01-01 至 2025-12-31
2025-09-01 至 2025-12-31
2025-09-01 至 2025-09-30
```

4. 样本数应始终显示该站点的 `full_history_rows`，例如表中为 `26,304`，而不是当前曲线点数 `15,344`。
5. 切换到其他站点后，样本数应变为对应站点的 `full_history_rows`。

### 10.2 全市模式

1. 选择“全市”。
2. 改变日期范围和小时范围。
3. 样本数应继续随当前筛选范围变化。
4. 全市模式不要显示某个单站点的 `full_history_rows`。

### 10.3 10-14 按钮

1. 单站点模式下点击“当前日期10-14”如果按钮禁用则无影响。
2. 全市模式下点击“当前日期10-14”，样本数仍按全市当前筛选范围计算。

## 十一、验收结论

本轮修改通过后：

- 单站点模式样本数 = 当前站点全量历史样本数。
- 全市模式样本数 = 当前筛选范围聚合样本数。
- 指标卡其他指标仍按当前筛选曲线实时计算。
- 不重新训练，不修改模型结果。

