# Cursor 修复方案 Round19：恢复网页启动，并合并 Round18 日期控件优化

## 0. 当前问题

当前交互式可视化网页无法正常启动，同时上一轮 Round18 的修改没有进行。

本轮目标：

```text
先修复网页能正常打开
再合并 Round18 的年月日日期选择和控件样式优化
最后保留折线图缩放功能
```

本轮不修改任何训练结果，不重新导出模型，不改 pkl/csv/json 数据。

---

## 1. 严禁修改

不要修改：

```text
output/pv_pipeline/tables/*.pkl
output/pv_pipeline/metrics/*.csv
output/pv_pipeline/interactive_dashboard/*.json
```

不要运行：

```bash
python scripts/train_fixed.py
python scripts/run_full_retrain_round14.py
```

本轮只修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

如需记录，可新增：

```text
docs/Round19_可视化网页启动修复与日期控件优化.md
```

---

## 2. 第一步：备份当前坏页面

先执行：

```bash
cp stages/05_visualization/interactive_forecast_dashboard.html \
   stages/05_visualization/interactive_forecast_dashboard_round19_broken_backup.html
```

如果后续修复失败，可以回滚分析。

---

## 3. 第二步：先做静态语法检查

执行：

```bash
python - <<'PY'
from pathlib import Path
import re

p = Path("stages/05_visualization/interactive_forecast_dashboard.html")
text = p.read_text(encoding="utf-8")
scripts = re.findall(r"<script[^>]*>(.*?)</script>", text, flags=re.S | re.I)
Path("/tmp/interactive_dashboard_script.js").write_text("\n".join(scripts), encoding="utf-8")
print("scripts:", len(scripts), "html_size:", len(text))
PY

node --check /tmp/interactive_dashboard_script.js
```

### 3.1 如果 node 报语法错误

先修语法错误，不要继续做 UI。

常见错误：

```text
Unexpected token
Missing ) after argument list
Identifier has already been declared
drawMainLineChart is not defined
mainLineChart is null
```

注意当前页面真实 ID / 函数名应为：

```text
SVG ID: line-chart
绘图函数: drawLineChart(rows)
刷新函数: refreshAll()
```

不要使用：

```text
mainLineChart
drawMainLineChart
resetLineZoomBtn
```

---

## 4. 第三步：确认页面启动方式

网页不能直接双击 HTML 打开，因为页面使用 `fetch()` 读取 JSON。

必须在项目根目录执行：

```bash
python -m http.server 8060
```

然后访问：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

如果用户直接双击打开，浏览器会拦截本地 JSON 读取，页面会卡在加载状态。

---

## 5. 第四步：在页面中加入 file:// 启动提示

在：

```javascript
document.addEventListener("DOMContentLoaded", () => {
```

内部最前面加入：

```javascript
if (window.location.protocol === "file:") {
  const loading = document.getElementById("loading");
  if (loading) {
    loading.innerHTML = `
      <div style="line-height:1.8">
        <b>页面不能直接双击打开。</b><br>
        请在项目根目录运行：<br>
        <code>python -m http.server 8060</code><br>
        然后访问：<br>
        <code>http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html</code>
      </div>
    `;
  }
  return;
}
```

同时把 `catch(err => {...})` 改成更明确的报错：

```javascript
}).catch(err => {
  const loading = document.getElementById("loading");
  if (loading) {
    loading.innerHTML = `
      <div style="line-height:1.8">
        <b>加载失败：</b>${err.message}<br>
        请确认：<br>
        1. 已在项目根目录运行 <code>python -m http.server 8060</code><br>
        2. 当前地址是 <code>/stages/05_visualization/interactive_forecast_dashboard.html</code><br>
        3. <code>output/pv_pipeline/interactive_dashboard/index.json</code> 存在
      </div>
    `;
  }
  console.error(err);
});
```

---

## 6. 第五步：恢复折线图最小可用

如果页面能加载指标卡但图不显示，先不要处理日期控件，先修折线图。

### 6.1 确认 HTML 结构

图表区域必须类似：

```html
<div id="chart-container">
  <div class="chart-title-row">
    <div id="chart-title">全市总出力折线图</div>
    <button id="reset-line-zoom" type="button">重置缩放</button>
  </div>
  <div id="line-zoom-info" class="zoom-info">滚轮缩放，拖拽平移，双击复位</div>
  <svg id="line-chart"></svg>
</div>
```

如果没有 `reset-line-zoom` 和 `line-zoom-info`，添加。

### 6.2 确认 CSS

必须有：

```css
#line-chart {
  width: 100%;
  height: 340px;
  display: block;
  cursor: grab;
  user-select: none;
  touch-action: none;
}
```

不能有：

```css
#line-chart { display: none; }
#line-chart { height: 0; }
```

### 6.3 确认 refreshAll

`refreshAll()` 必须按这个结构：

```javascript
async function refreshAll() {
  const rows = await getFilteredRows();
  const isSite = state.scope === "site";
  const m = computeMetrics(rows, isSite);
  updateMetricsCards(m, rows);

  setLineRows(rows);
  resetLineZoom();

  drawHourlyNrmseChart();
  if (!isSite) drawScatterChart(gScatterSite);
}
```

如果当前仍是：

```javascript
drawLineChart(rows);
```

也可以临时保留，但缩放功能会不同步。最终必须改成上面结构。

### 6.4 drawLineChart 要能兜底

`drawLineChart(rows)` 开头必须有：

```javascript
function drawLineChart(rows) {
  const svg = document.getElementById("line-chart");
  const title = document.getElementById("chart-title");
  const isSite = state.scope === "site";

  if (!svg) {
    console.error("line-chart svg not found");
    return;
  }

  if (title) {
    title.textContent = isSite
      ? "站点 " + (state.siteId || "") + " 功率曲线"
      : "全市总出力折线图";
  }

  svg.innerHTML = "";

  rows = Array.isArray(rows) ? rows.filter(Boolean) : [];

  if (!rows.length) {
    svg.setAttribute("viewBox", "0 0 1000 160");
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "160");
    const empty = svgNS("text", {
      x: 24,
      y: 48,
      fill: "#94a3b8",
      "font-size": "14",
    });
    empty.textContent = "当前筛选条件下暂无折线图数据";
    svg.appendChild(empty);
    return;
  }

  rows = [...rows].sort((a, b) => String(a.time || "").localeCompare(String(b.time || "")));
```

宽度计算必须有兜底：

```javascript
const parentWidth = svg.parentElement
  ? svg.parentElement.getBoundingClientRect().width
  : 1200;

const W = Math.max(720, Math.floor(parentWidth - 28));
const H = 340;
```

字段读取必须兼容：

```javascript
function getActualValue(r) {
  const v = r.actual_mw ?? r.power_mw ?? r.actual ?? r.y_true ?? 0;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function getPredValue(r) {
  const v = r.pred_mw ?? r.power_pred ?? r.pred ?? r.y_pred ?? 0;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

const actuals = rows.map(getActualValue);
const preds = rows.map(getPredValue);
```

---

## 7. 第六步：接入滚轮缩放

确认全局有：

```javascript
let gLineRowsFull = [];

let lineZoom = {
  startIndex: 0,
  endIndex: -1,
  isDragging: false,
  dragStartX: 0,
  dragStartStartIndex: 0,
  dragStartEndIndex: -1,
  bound: false,
};
```

确认函数存在：

```javascript
setLineRows
getVisibleLineRows
redrawLineChartFromZoom
resetLineZoom
handleLineWheel
handleLineMouseDown
handleLineMouseMove
handleLineMouseUp
bindLineZoomEvents
updateLineZoomInfo
```

事件绑定必须使用真实 ID：

```javascript
const svg = document.getElementById("line-chart");
```

不要使用：

```javascript
document.getElementById("mainLineChart")
```

初始化成功后调用：

```javascript
loadAll().then(() => {
  buildSitesTable();
  onScopeChange();
  bindLineZoomEvents();
  bindDateComboEvents();
  refreshAll();
})
```

如果 Round18 尚未做，`bindDateComboEvents()` 先不要调用；等第 8 步完成后再调用。

---

## 8. 第七步：合并 Round18 日期控件

当前 Round18 没有进行，本轮一起加入。

### 8.1 把原日期输入改成年月日下拉

找到：

```html
<input type="date" id="start-date">
...
<input type="date" id="end-date">
```

改为：

```html
<div class="date-combo" data-role="start">
  <select id="start-year" class="select-control date-year"></select><span class="date-unit">年</span>
  <select id="start-month" class="select-control date-month"></select><span class="date-unit">月</span>
  <select id="start-day" class="select-control date-day"></select><span class="date-unit">日</span>
</div>

<input type="date" id="start-date" class="hidden-date-input">

<span class="ctrl-label">至</span>

<div class="date-combo" data-role="end">
  <select id="end-year" class="select-control date-year"></select><span class="date-unit">年</span>
  <select id="end-month" class="select-control date-month"></select><span class="date-unit">月</span>
  <select id="end-day" class="select-control date-day"></select><span class="date-unit">日</span>
</div>

<input type="date" id="end-date" class="hidden-date-input">
```

### 8.2 加入日期函数

加入：

```javascript
let dateComboBound = false;

function parseDateParts(dateStr) {
  const [y, m, d] = String(dateStr || "").split("-").map(x => parseInt(x, 10));
  return {
    year: Number.isFinite(y) ? y : 2025,
    month: Number.isFinite(m) ? m : 1,
    day: Number.isFinite(d) ? d : 1,
  };
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

function daysInMonth(year, month) {
  return new Date(year, month, 0).getDate();
}

function buildDateString(year, month, day) {
  return `${year}-${pad2(month)}-${pad2(day)}`;
}
```

加入：

```javascript
function populateDayOptions(prefix, year, month, selectedDay) {
  const dayEl = document.getElementById(`${prefix}-day`);
  if (!dayEl) return;

  const maxDay = daysInMonth(year, month);
  const safeDay = Math.min(Math.max(1, selectedDay || 1), maxDay);

  dayEl.innerHTML = "";
  for (let d = 1; d <= maxDay; d++) {
    const opt = document.createElement("option");
    opt.value = d;
    opt.textContent = pad2(d);
    dayEl.appendChild(opt);
  }
  dayEl.value = safeDay;
}
```

加入：

```javascript
function populateDateCombo(prefix, dateStr, minDate, maxDate) {
  const yearEl = document.getElementById(`${prefix}-year`);
  const monthEl = document.getElementById(`${prefix}-month`);
  const dayEl = document.getElementById(`${prefix}-day`);
  if (!yearEl || !monthEl || !dayEl) return;

  const minParts = parseDateParts(minDate);
  const maxParts = parseDateParts(maxDate);
  const cur = parseDateParts(dateStr);

  yearEl.innerHTML = "";
  for (let y = minParts.year; y <= maxParts.year; y++) {
    const opt = document.createElement("option");
    opt.value = y;
    opt.textContent = y;
    yearEl.appendChild(opt);
  }
  yearEl.value = cur.year;

  monthEl.innerHTML = "";
  for (let m = 1; m <= 12; m++) {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = pad2(m);
    monthEl.appendChild(opt);
  }
  monthEl.value = cur.month;

  populateDayOptions(prefix, cur.year, cur.month, cur.day);
}
```

加入：

```javascript
function getDateComboValue(prefix) {
  const year = parseInt(document.getElementById(`${prefix}-year`)?.value, 10);
  const month = parseInt(document.getElementById(`${prefix}-month`)?.value, 10);
  const day = parseInt(document.getElementById(`${prefix}-day`)?.value, 10);
  return buildDateString(year, month, day);
}

function setDateComboValue(prefix, dateStr) {
  const parts = parseDateParts(dateStr);
  const yearEl = document.getElementById(`${prefix}-year`);
  const monthEl = document.getElementById(`${prefix}-month`);
  const dayEl = document.getElementById(`${prefix}-day`);
  if (!yearEl || !monthEl || !dayEl) return;

  yearEl.value = parts.year;
  monthEl.value = parts.month;
  populateDayOptions(prefix, parts.year, parts.month, parts.day);
}
```

加入：

```javascript
function bindDateComboEvents() {
  if (dateComboBound) return;
  dateComboBound = true;

  ["start", "end"].forEach(prefix => {
    const yearEl = document.getElementById(`${prefix}-year`);
    const monthEl = document.getElementById(`${prefix}-month`);
    const dayEl = document.getElementById(`${prefix}-day`);
    if (!yearEl || !monthEl || !dayEl) return;

    function applyDateChange() {
      state.startDate = getDateComboValue("start");
      state.endDate = getDateComboValue("end");

      if (state.startDate > state.endDate) {
        if (prefix === "start") {
          state.endDate = state.startDate;
          setDateComboValue("end", state.endDate);
        } else {
          state.startDate = state.endDate;
          setDateComboValue("start", state.startDate);
        }
      }

      const startInput = document.getElementById("start-date");
      const endInput = document.getElementById("end-date");
      if (startInput) startInput.value = state.startDate;
      if (endInput) endInput.value = state.endDate;

      refreshAll();
    }

    function onYearMonthChange() {
      const year = parseInt(yearEl.value, 10);
      const month = parseInt(monthEl.value, 10);
      const oldDay = parseInt(dayEl.value, 10);
      populateDayOptions(prefix, year, month, oldDay);
      applyDateChange();
    }

    yearEl.addEventListener("change", onYearMonthChange);
    monthEl.addEventListener("change", onYearMonthChange);
    dayEl.addEventListener("change", applyDateChange);
  });
}
```

### 8.3 loadAll 初始化日期控件

当前：

```javascript
state.startDate = idx.default_start_date || idx.min_date;
state.endDate = idx.default_end_date || idx.max_date;
document.getElementById("start-date").value = state.startDate;
document.getElementById("end-date").value = state.endDate;
```

改为：

```javascript
state.startDate = idx.default_start_date || idx.min_date;
state.endDate = idx.default_end_date || idx.max_date;

const startInput = document.getElementById("start-date");
const endInput = document.getElementById("end-date");
if (startInput) startInput.value = state.startDate;
if (endInput) endInput.value = state.endDate;

populateDateCombo("start", state.startDate, idx.min_date, idx.max_date);
populateDateCombo("end", state.endDate, idx.min_date, idx.max_date);
```

### 8.4 快捷按钮同步年月日

凡是代码里有：

```javascript
document.getElementById("start-date").value = state.startDate;
document.getElementById("end-date").value = state.endDate;
```

后面都加：

```javascript
setDateComboValue("start", state.startDate);
setDateComboValue("end", state.endDate);
```

尤其是：

```text
连云港全市10-14
春季/夏季/秋季/冬季
```

---

## 9. 控件样式优化

加入 CSS：

```css
.select-control,
#site-select,
#start-hour,
#end-hour {
  height: 36px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #ffffff;
  color: #1f2937;
  padding: 0 10px;
  font-size: 13px;
  font-weight: 500;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}

.select-control:focus,
#site-select:focus,
#start-hour:focus,
#end-hour:focus {
  border-color: #3182ce;
  box-shadow: 0 0 0 3px rgba(49, 130, 206, 0.16);
}

.date-combo {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.date-year { width: 82px; }
.date-month,
.date-day { width: 62px; }

.date-unit {
  font-size: 12px;
  color: #64748b;
  margin-right: 2px;
}

.hidden-date-input {
  display: none;
}

.btn,
.btn-seas {
  height: 36px;
  border: 1px solid #2f80d1;
  border-radius: 6px;
  background: linear-gradient(180deg, #3b8ed8 0%, #2f80d1 100%);
  color: #ffffff;
  padding: 0 14px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.08s ease, box-shadow 0.15s ease, background 0.15s ease;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
}

.btn:hover,
.btn-seas:hover:not(:disabled) {
  background: linear-gradient(180deg, #4699e2 0%, #2b75be 100%);
  box-shadow: 0 3px 8px rgba(49, 130, 206, 0.22);
}

.btn:active,
.btn-seas:active:not(:disabled) {
  transform: translateY(1px);
}

.btn:disabled,
.btn-seas:disabled {
  background: #e2e8f0;
  border-color: #cbd5e1;
  color: #94a3b8;
  cursor: not-allowed;
  box-shadow: none;
}
```

---

## 10. 移除旧 date input 事件

如果有：

```javascript
document.getElementById("start-date").addEventListener("change", ...)
document.getElementById("end-date").addEventListener("change", ...)
```

删除或禁用。

因为现在由：

```javascript
bindDateComboEvents()
```

管理日期变化。

---

## 11. 最终初始化顺序

`DOMContentLoaded` 中最终结构应类似：

```javascript
document.addEventListener("DOMContentLoaded", () => {
  if (window.location.protocol === "file:") {
    ...
    return;
  }

  loadAll().then(() => {
    buildSitesTable();
    onScopeChange();
    bindLineZoomEvents();
    bindDateComboEvents();
    refreshAll();
  }).catch(err => {
    ...
  });

  ...
});
```

注意：

```text
bindDateComboEvents 必须在 loadAll 之后，因为 loadAll 会先 populateDateCombo。
```

---

## 12. 自动验收

执行：

```bash
python - <<'PY'
from pathlib import Path
import re

p = Path("stages/05_visualization/interactive_forecast_dashboard.html")
text = p.read_text(encoding="utf-8")

required = [
    "line-chart",
    "setLineRows",
    "resetLineZoom",
    "bindLineZoomEvents",
    "start-year",
    "start-month",
    "start-day",
    "end-year",
    "end-month",
    "end-day",
    "populateDateCombo",
    "bindDateComboEvents",
    "setDateComboValue",
    "date-combo",
    "select-control",
]

missing = [x for x in required if x not in text]
assert not missing, "缺少: " + ", ".join(missing)

assert "mainLineChart" not in text
assert "drawMainLineChart" not in text

scripts = re.findall(r"<script[^>]*>(.*?)</script>", text, flags=re.S | re.I)
Path("/tmp/interactive_dashboard_script.js").write_text("\\n".join(scripts), encoding="utf-8")
print("[OK] HTML static check passed")
PY

node --check /tmp/interactive_dashboard_script.js
```

---

## 13. 页面验收

启动：

```bash
python -m http.server 8060
```

访问：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

检查：

1. 页面能正常启动。
2. 指标卡正常显示。
3. 折线图正常显示。
4. 日期区域为 年/月/日 下拉框。
5. 可以直接选择年份和月份。
6. 切换月份后日选项正确。
7. 点击四季按钮后日期下拉框同步变化。
8. 点击 10-14 按钮后日期下拉框同步变化。
9. 鼠标滚轮可以缩放折线图。
10. 拖拽可以平移折线图。
11. 双击和重置按钮可以恢复全范围。
12. 控制台没有红色 JS 报错。

---

## 14. 如果仍不能启动

请打开浏览器控制台，优先修第一条红色错误。

常见错误：

### 14.1 Failed to fetch

说明启动目录不对或直接双击了 HTML。

正确方式：

```bash
cd 项目根目录
python -m http.server 8060
```

### 14.2 Cannot read properties of null

说明某个 ID 不存在。

重点检查：

```text
line-chart
reset-line-zoom
line-zoom-info
start-year / start-month / start-day
end-year / end-month / end-day
```

### 14.3 Identifier has already been declared

说明重复插入了函数或变量。

删除重复的：

```text
dateComboBound
gLineRowsFull
lineZoom
parseDateParts
populateDateCombo
bindDateComboEvents
```

每个只保留一份。

