# Cursor 修改方案 Round18：日期支持年月快速选择，并优化下拉框与按钮样式

## 0. 修改目标

当前可视化页面存在两个体验问题：

1. 日期选择只能通过原生 `input type="date"` 慢慢点，不方便直接选择年份和月份。
2. 下拉框、按钮、数字输入框样式不够统一，视觉上略粗糙。

本轮目标：

```text
优化日期选择体验 + 统一控件样式
```

要求：

1. 支持直接选择开始年、开始月、开始日。
2. 支持直接选择结束年、结束月、结束日。
3. 保留原有筛选逻辑：最终仍更新 `state.startDate` 和 `state.endDate`。
4. 优化站点下拉框、按钮、小时输入框、日期控件样式。
5. 不修改任何训练结果、JSON 数据、pkl、csv。

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

## 2. 日期控件改造方案

当前大概率是：

```html
<input type="date" id="start-date">
<input type="date" id="end-date">
```

请改成“年月日组合下拉框”，例如：

```html
<div class="date-combo" data-role="start">
  <select id="start-year" class="select-control date-year"></select>
  <span class="date-unit">年</span>
  <select id="start-month" class="select-control date-month"></select>
  <span class="date-unit">月</span>
  <select id="start-day" class="select-control date-day"></select>
  <span class="date-unit">日</span>
</div>

<span class="ctrl-label">至</span>

<div class="date-combo" data-role="end">
  <select id="end-year" class="select-control date-year"></select>
  <span class="date-unit">年</span>
  <select id="end-month" class="select-control date-month"></select>
  <span class="date-unit">月</span>
  <select id="end-day" class="select-control date-day"></select>
  <span class="date-unit">日</span>
</div>
```

如果你想保留原生 date 输入作为兜底，可以隐藏：

```html
<input type="date" id="start-date" class="hidden-date-input">
<input type="date" id="end-date" class="hidden-date-input">
```

但页面上主要展示年月日下拉框。

---

## 3. 日期下拉框初始化逻辑

新增函数：

```javascript
function parseDateParts(dateStr) {
  const [y, m, d] = String(dateStr || "").split("-").map(x => parseInt(x, 10));
  return {
    year: Number.isFinite(y) ? y : 2025,
    month: Number.isFinite(m) ? m : 1,
    day: Number.isFinite(d) ? d : 1,
  };
}
```

```javascript
function pad2(n) {
  return String(n).padStart(2, "0");
}
```

```javascript
function daysInMonth(year, month) {
  return new Date(year, month, 0).getDate();
}
```

```javascript
function buildDateString(year, month, day) {
  return `${year}-${pad2(month)}-${pad2(day)}`;
}
```

---

## 4. 生成年/月/日选项

新增：

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

---

## 5. 读取日期组合控件

新增：

```javascript
function getDateComboValue(prefix) {
  const year = parseInt(document.getElementById(`${prefix}-year`)?.value, 10);
  const month = parseInt(document.getElementById(`${prefix}-month`)?.value, 10);
  const day = parseInt(document.getElementById(`${prefix}-day`)?.value, 10);
  return buildDateString(year, month, day);
}
```

---

## 6. 日期变化事件

新增：

```javascript
function bindDateComboEvents() {
  ["start", "end"].forEach(prefix => {
    const yearEl = document.getElementById(`${prefix}-year`);
    const monthEl = document.getElementById(`${prefix}-month`);
    const dayEl = document.getElementById(`${prefix}-day`);

    if (!yearEl || !monthEl || !dayEl) return;

    function onYearMonthChange() {
      const year = parseInt(yearEl.value, 10);
      const month = parseInt(monthEl.value, 10);
      const oldDay = parseInt(dayEl.value, 10);
      populateDayOptions(prefix, year, month, oldDay);
      onDateComboChange();
    }

    function onDateComboChange() {
      state.startDate = getDateComboValue("start");
      state.endDate = getDateComboValue("end");

      // 如果开始日期晚于结束日期，自动拉齐
      if (state.startDate > state.endDate) {
        if (prefix === "start") {
          state.endDate = state.startDate;
          setDateComboValue("end", state.endDate);
        } else {
          state.startDate = state.endDate;
          setDateComboValue("start", state.startDate);
        }
      }

      // 同步隐藏 date input，兼容旧逻辑
      const startInput = document.getElementById("start-date");
      const endInput = document.getElementById("end-date");
      if (startInput) startInput.value = state.startDate;
      if (endInput) endInput.value = state.endDate;

      refreshAll();
    }

    yearEl.addEventListener("change", onYearMonthChange);
    monthEl.addEventListener("change", onYearMonthChange);
    dayEl.addEventListener("change", onDateComboChange);
  });
}
```

新增：

```javascript
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

---

## 7. 在 loadAll 中初始化日期控件

当前 `loadAll()` 里有：

```javascript
state.startDate = idx.default_start_date || idx.min_date;
state.endDate = idx.default_end_date || idx.max_date;
document.getElementById("start-date").value = state.startDate;
document.getElementById("end-date").value = state.endDate;
```

改成：

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

在 `DOMContentLoaded` 初始化中，`loadAll().then(...)` 后调用：

```javascript
bindDateComboEvents();
```

注意：不要重复绑定。可以加：

```javascript
let dateComboBound = false;
function bindDateComboEvents() {
  if (dateComboBound) return;
  dateComboBound = true;
  ...
}
```

---

## 8. 修改快捷按钮逻辑

页面里有：

```javascript
document.getElementById("start-date").value = state.startDate;
document.getElementById("end-date").value = state.endDate;
```

例如：

```text
连云港全市10-14
春季/夏季/秋季/冬季
```

这些地方必须同步改为：

```javascript
setDateComboValue("start", state.startDate);
setDateComboValue("end", state.endDate);

const startInput = document.getElementById("start-date");
const endInput = document.getElementById("end-date");
if (startInput) startInput.value = state.startDate;
if (endInput) endInput.value = state.endDate;
```

不要只更新隐藏 input，否则页面上的年月日下拉框不会变。

---

## 9. 删除或停用旧 date input 事件

如果保留隐藏：

```html
<input type="date" id="start-date" class="hidden-date-input">
<input type="date" id="end-date" class="hidden-date-input">
```

则原来的事件：

```javascript
document.getElementById("start-date").addEventListener("change", ...)
document.getElementById("end-date").addEventListener("change", ...)
```

可以删除，或加保护：

```javascript
const startDateInput = document.getElementById("start-date");
if (startDateInput && !startDateInput.classList.contains("hidden-date-input")) {
  startDateInput.addEventListener("change", ...);
}
```

推荐删除旧 date input 的 change 事件，避免重复刷新。

---

## 10. 控件样式优化

在 CSS 中加入统一控件样式。

### 10.1 下拉框样式

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
  padding: 0 34px 0 10px;
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
```

### 10.2 日期组合样式

```css
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
```

### 10.3 按钮样式

将 `.btn`、`.btn-seas` 统一优化：

```css
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
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
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

### 10.4 四季按钮不要是绿色粗边

如果当前 `.btn-seas` 是绿色按钮，改为和 `.btn` 一致。

如果想区分四季，可以只用小色条，不要整块绿色：

```css
.btn-seas {
  position: relative;
}

.btn-seas::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  border-radius: 6px 0 0 6px;
  background: rgba(255, 255, 255, 0.55);
}
```

### 10.5 控制区布局优化

```css
#controls {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 14px;
  align-items: center;
  background: #ffffff;
  border: 1px solid #d8e2ee;
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 14px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.ctrl-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.ctrl-label {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.divider {
  width: 1px;
  height: 28px;
  background: #e2e8f0;
}
```

---

## 11. 移动端适配

加入：

```css
@media (max-width: 900px) {
  .date-combo {
    width: 100%;
    justify-content: flex-start;
  }

  .divider {
    display: none;
  }

  #controls {
    align-items: stretch;
  }

  .ctrl-group {
    width: 100%;
  }
}
```

---

## 12. 验收检查

### 12.1 静态检查

```bash
python - <<'PY'
from pathlib import Path

p = Path("stages/05_visualization/interactive_forecast_dashboard.html")
text = p.read_text(encoding="utf-8")

required = [
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
assert not missing, "缺少日期组合控件相关代码: " + ", ".join(missing)

print("[OK] date combo controls exist")
PY
```

### 12.2 JS 语法检查

```bash
python - <<'PY'
from pathlib import Path
import re

html = Path("stages/05_visualization/interactive_forecast_dashboard.html").read_text(encoding="utf-8")
scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.S | re.I)
Path("/tmp/interactive_dashboard_script.js").write_text("\\n".join(scripts), encoding="utf-8")
print("[OK] extracted scripts:", len(scripts))
PY

node --check /tmp/interactive_dashboard_script.js
```

---

## 13. 页面人工验收

启动服务：

```bash
python -m http.server 8060
```

打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

检查：

1. 日期区域显示为 年 / 月 / 日 三个下拉框。
2. 可以直接选择年份。
3. 可以直接选择月份。
4. 切换月份后，日选项自动变成正确天数，例如 2 月不是 31 天。
5. 选择开始日期后图表自动刷新。
6. 选择结束日期后图表自动刷新。
7. 如果开始日期晚于结束日期，自动拉齐，页面不报错。
8. 四季按钮点击后，年月日下拉框同步更新。
9. “连云港全市10-14”点击后，年月日下拉框同步更新。
10. 站点下拉框、小时输入框、按钮样式统一、清晰、没有挤压。

---

## 14. 注意事项

1. 不要引入外部 UI 库。
2. 不要使用 CDN。
3. 不要改变数据筛选口径。
4. 不要修改图表计算逻辑。
5. 日期最终仍必须是 `YYYY-MM-DD` 字符串。
6. 页面原有滚轮缩放功能必须保留。

---

## 15. 提交说明建议

```text
Round18: improve date selection and control styling

- replace date inputs with year/month/day combo selectors
- sync date combo with state.startDate and state.endDate
- update quick date buttons to sync combo controls
- polish select, number input, and button styling
- keep chart data and metrics unchanged
```

