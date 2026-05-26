# Cursor 修改方案 Round17：折线图增加鼠标滚轮缩放与拖拽平移

## 0. 修改目标

当前交互式页面中的全市/单站点功率折线图时间跨度较长，点位过密，局部误差不容易查看。

本轮目标：

```text
为功率折线图增加鼠标滚轮缩放、拖拽平移、双击复位和重置按钮。
```

要求：

1. 鼠标滚轮在图表区域内缩放横轴时间范围。
2. 鼠标左键拖拽可以左右平移。
3. 双击图表恢复全范围。
4. 增加“重置缩放”按钮。
5. 缩放只作用于当前筛选后的折线图数据。
6. 切换站点、切换全市/单站点、改变日期或小时筛选时，自动重置缩放。
7. 不修改任何训练脚本、pkl、csv、json 结果文件。

---

## 1. 修改文件

只修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

不要修改：

```text
output/pv_pipeline/tables/*.pkl
output/pv_pipeline/metrics/*.csv
output/pv_pipeline/interactive_dashboard/*.json
```

---

## 2. 找到主折线图相关代码

在 HTML 中查找：

```text
全市总出力折线图
真实功率 MW
预测功率 MW
drawLineChart
drawMainLineChart
lineChart
```

确认当前主折线图 SVG 的 ID。

如果当前 SVG 没有固定 ID，请设置为：

```html
<svg id="mainLineChart"></svg>
```

如果已有其他 ID，例如：

```text
powerLineChart
cityLineChart
```

可以保留原 ID，但下面代码中的 `mainLineChart` 要统一替换为实际 ID。

---

## 3. 新增缩放状态

在全局变量区域新增：

```javascript
let gCurrentLineRows = [];

let lineChartView = {
  startIndex: null,
  endIndex: null,
  isDragging: false,
  dragStartX: 0,
  dragStartStartIndex: null,
  dragStartEndIndex: null
};
```

含义：

| 字段 | 含义 |
|---|---|
| `gCurrentLineRows` | 当前筛选后的完整折线图数据 |
| `startIndex` | 当前可见窗口起点 |
| `endIndex` | 当前可见窗口终点 |
| `isDragging` | 是否正在拖拽 |
| `dragStartX` | 拖拽开始时鼠标 X 坐标 |
| `dragStartStartIndex` | 拖拽开始时窗口起点 |
| `dragStartEndIndex` | 拖拽开始时窗口终点 |

---

## 4. 新增缩放工具函数

加入以下函数：

```javascript
function resetLineChartZoom() {
  if (!gCurrentLineRows || !gCurrentLineRows.length) {
    lineChartView.startIndex = null;
    lineChartView.endIndex = null;
    updateLineChartZoomInfo();
    return;
  }

  lineChartView.startIndex = 0;
  lineChartView.endIndex = gCurrentLineRows.length - 1;
  drawMainLineChart();
  updateLineChartZoomInfo();
}
```

如果页面中的主绘图函数不叫 `drawMainLineChart()`，请改成当前实际函数名。

新增：

```javascript
function getVisibleLineRows() {
  if (!gCurrentLineRows || !gCurrentLineRows.length) return [];

  const n = gCurrentLineRows.length;

  if (lineChartView.startIndex === null || lineChartView.endIndex === null) {
    lineChartView.startIndex = 0;
    lineChartView.endIndex = n - 1;
  }

  const start = Math.max(0, Math.min(n - 1, lineChartView.startIndex));
  const end = Math.max(start, Math.min(n - 1, lineChartView.endIndex));

  return gCurrentLineRows.slice(start, end + 1);
}
```

---

## 5. 修改主绘图函数

找到当前主折线图绘制函数，通常类似：

```javascript
function drawMainLineChart(rows) {
  ...
}
```

或：

```javascript
function drawLineChart(rows) {
  ...
}
```

调整为：

```javascript
function drawMainLineChart() {
  const rows = getVisibleLineRows();
  ...
}
```

如果原函数依赖外部传参，则改成：

```javascript
gCurrentLineRows = filteredRows;
resetLineChartZoom();
```

但注意：不要在 `drawMainLineChart()` 内部每次都重置缩放，否则滚轮缩放会失效。

正确逻辑是：

```javascript
// 筛选条件变化时：
gCurrentLineRows = filteredRows;
resetLineChartZoom();

// 滚轮/拖拽时：
drawMainLineChart();
```

### 5.1 纵轴按可见数据自动缩放

绘图函数计算 y 轴最大值时，必须用：

```javascript
const rows = getVisibleLineRows();
```

而不是全部数据。

示例：

```javascript
const maxY = Math.max(
  1,
  ...rows.map(d => Number(d.actual_mw || d.power_mw || 0)),
  ...rows.map(d => Number(d.pred_mw || d.power_pred || 0))
);
```

这样放大局部后，纵轴会自动适应当前可见范围。

---

## 6. 新增滚轮缩放函数

加入：

```javascript
function handleLineChartWheel(event) {
  if (!gCurrentLineRows || gCurrentLineRows.length < 2) return;

  event.preventDefault();

  const n = gCurrentLineRows.length;

  if (lineChartView.startIndex === null || lineChartView.endIndex === null) {
    lineChartView.startIndex = 0;
    lineChartView.endIndex = n - 1;
  }

  const rect = event.currentTarget.getBoundingClientRect();
  const mouseRatio = Math.min(
    1,
    Math.max(0, (event.clientX - rect.left) / Math.max(rect.width, 1))
  );

  const start = lineChartView.startIndex;
  const end = lineChartView.endIndex;
  const currentWindow = end - start + 1;

  const zoomFactor = event.deltaY < 0 ? 0.8 : 1.25;
  let newWindow = Math.round(currentWindow * zoomFactor);

  const minWindow = Math.min(12, n);
  const maxWindow = n;
  newWindow = Math.max(minWindow, Math.min(maxWindow, newWindow));

  const anchorIndex = start + Math.round(mouseRatio * (currentWindow - 1));

  let newStart = Math.round(anchorIndex - mouseRatio * (newWindow - 1));
  let newEnd = newStart + newWindow - 1;

  if (newStart < 0) {
    newStart = 0;
    newEnd = newWindow - 1;
  }

  if (newEnd >= n) {
    newEnd = n - 1;
    newStart = n - newWindow;
  }

  lineChartView.startIndex = newStart;
  lineChartView.endIndex = newEnd;

  drawMainLineChart();
  updateLineChartZoomInfo();
}
```

---

## 7. 新增拖拽平移函数

加入：

```javascript
function handleLineChartMouseDown(event) {
  if (!gCurrentLineRows || gCurrentLineRows.length < 2) return;

  if (lineChartView.startIndex === null || lineChartView.endIndex === null) {
    lineChartView.startIndex = 0;
    lineChartView.endIndex = gCurrentLineRows.length - 1;
  }

  lineChartView.isDragging = true;
  lineChartView.dragStartX = event.clientX;
  lineChartView.dragStartStartIndex = lineChartView.startIndex;
  lineChartView.dragStartEndIndex = lineChartView.endIndex;

  const chartEl = document.getElementById("mainLineChart");
  if (chartEl) chartEl.style.cursor = "grabbing";
}
```

```javascript
function handleLineChartMouseMove(event) {
  if (!lineChartView.isDragging) return;
  if (!gCurrentLineRows || !gCurrentLineRows.length) return;

  const chartEl = document.getElementById("mainLineChart");
  if (!chartEl) return;

  const n = gCurrentLineRows.length;
  const start = lineChartView.dragStartStartIndex;
  const end = lineChartView.dragStartEndIndex;
  const windowSize = end - start + 1;

  const rect = chartEl.getBoundingClientRect();
  const dx = event.clientX - lineChartView.dragStartX;
  const pointsPerPixel = windowSize / Math.max(rect.width, 1);
  const shift = Math.round(-dx * pointsPerPixel);

  let newStart = start + shift;
  let newEnd = end + shift;

  if (newStart < 0) {
    newStart = 0;
    newEnd = windowSize - 1;
  }

  if (newEnd >= n) {
    newEnd = n - 1;
    newStart = n - windowSize;
  }

  lineChartView.startIndex = newStart;
  lineChartView.endIndex = newEnd;

  drawMainLineChart();
  updateLineChartZoomInfo();
}
```

```javascript
function handleLineChartMouseUp() {
  lineChartView.isDragging = false;
  const chartEl = document.getElementById("mainLineChart");
  if (chartEl) chartEl.style.cursor = "grab";
}
```

---

## 8. 新增缩放提示

在折线图标题区域加：

```html
<div class="chart-actions">
  <button id="resetLineZoomBtn" type="button">重置缩放</button>
  <span id="lineChartZoomInfo" class="zoom-info">滚轮缩放，拖拽平移，双击复位</span>
</div>
```

新增函数：

```javascript
function updateLineChartZoomInfo() {
  const el = document.getElementById("lineChartZoomInfo");
  if (!el) return;

  if (!gCurrentLineRows || !gCurrentLineRows.length) {
    el.textContent = "暂无数据";
    return;
  }

  const n = gCurrentLineRows.length;
  const start = lineChartView.startIndex ?? 0;
  const end = lineChartView.endIndex ?? (n - 1);
  const a = gCurrentLineRows[start];
  const b = gCurrentLineRows[end];

  const startTime = a.time || a.date || "";
  const endTime = b.time || b.date || "";

  el.textContent = `当前显示 ${start + 1}-${end + 1} / ${n} 点，${startTime} ~ ${endTime}；滚轮缩放，拖拽平移，双击复位`;
}
```

---

## 9. 绑定事件

页面初始化完成后绑定：

```javascript
function bindLineChartZoomEvents() {
  const chartEl = document.getElementById("mainLineChart");
  if (!chartEl) return;

  chartEl.addEventListener("wheel", handleLineChartWheel, { passive: false });
  chartEl.addEventListener("mousedown", handleLineChartMouseDown);
  chartEl.addEventListener("dblclick", resetLineChartZoom);

  window.addEventListener("mousemove", handleLineChartMouseMove);
  window.addEventListener("mouseup", handleLineChartMouseUp);

  const resetBtn = document.getElementById("resetLineZoomBtn");
  if (resetBtn) {
    resetBtn.addEventListener("click", resetLineChartZoom);
  }
}
```

确保只绑定一次。

如果页面初始化函数叫：

```javascript
init()
loadAll()
main()
```

在里面加：

```javascript
bindLineChartZoomEvents();
```

如果担心重复绑定，使用：

```javascript
let lineChartZoomBound = false;

function bindLineChartZoomEvents() {
  if (lineChartZoomBound) return;
  lineChartZoomBound = true;
  ...
}
```

---

## 10. 筛选变化时重置缩放

找到这些事件：

```text
全市/单站点切换
站点选择
日期开始/结束变化
小时开始/结束变化
快捷按钮：10-14
快捷按钮：四季代表日
刷新按钮
```

在重新生成折线图数据后调用：

```javascript
gCurrentLineRows = filteredRows;
resetLineChartZoom();
```

不要只调用：

```javascript
drawMainLineChart();
```

否则切换筛选条件后可能沿用旧缩放窗口。

---

## 11. 样式

新增 CSS：

```css
#mainLineChart {
  cursor: grab;
  user-select: none;
  touch-action: none;
}

.chart-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 8px;
}

#resetLineZoomBtn {
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #334155;
  border-radius: 6px;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 13px;
}

#resetLineZoomBtn:hover {
  background: #f8fafc;
}

.zoom-info {
  font-size: 12px;
  color: #64748b;
}
```

---

## 12. 性能优化建议

如果可见点数很多，SVG path 可以继续画全部可见点。

如果浏览器卡顿，再加入抽样：

```javascript
function downsampleRows(rows, maxPoints = 2500) {
  if (!rows || rows.length <= maxPoints) return rows;
  const step = Math.ceil(rows.length / maxPoints);
  return rows.filter((_, i) => i % step === 0);
}
```

绘制 path 时用：

```javascript
const drawRows = downsampleRows(rows);
```

但指标卡片仍然应该基于完整 `rows` 计算，不要基于抽样数据。

---

## 13. 验收

启动页面：

```bash
python -m http.server 8060
```

打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

人工检查：

1. 鼠标滚轮向上，时间范围缩小，曲线局部放大。
2. 鼠标滚轮向下，时间范围扩大。
3. 鼠标拖拽可以左右平移时间窗口。
4. 双击图表恢复全范围。
5. 点击“重置缩放”恢复全范围。
6. 切换全市/单站点后，缩放状态自动重置。
7. 改变日期范围后，缩放状态自动重置。
8. 改变小时范围后，缩放状态自动重置。
9. 页面控制台无 JS 报错。

---

## 14. 自动检查

运行：

```bash
python - <<'PY'
from pathlib import Path

p = Path("stages/05_visualization/interactive_forecast_dashboard.html")
text = p.read_text(encoding="utf-8")

required = [
    "lineChartView",
    "gCurrentLineRows",
    "handleLineChartWheel",
    "handleLineChartMouseDown",
    "handleLineChartMouseMove",
    "handleLineChartMouseUp",
    "resetLineChartZoom",
    "updateLineChartZoomInfo",
    "resetLineZoomBtn",
    "wheel",
    "dblclick",
]

missing = [x for x in required if x not in text]
assert not missing, "缺少缩放相关代码: " + ", ".join(missing)

print("[OK] line chart zoom code exists")
PY
```

---

## 15. 提交说明建议

```text
Round17: add wheel zoom and drag pan to forecast line chart

- add x-axis zoom state for main forecast chart
- support mouse wheel zoom, drag pan, double-click reset
- add reset zoom button and visible range hint
- auto-reset zoom when filters change
- keep prediction data and metrics unchanged
```

