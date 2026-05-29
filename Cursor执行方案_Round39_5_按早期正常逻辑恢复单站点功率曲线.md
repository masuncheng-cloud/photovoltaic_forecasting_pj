# Round39.5：按早期正常逻辑恢复单站点功率曲线

## 一、当前判断

现在不需要重新训练。

从 Round39.4 执行报告看，后端数据已经证明：

```text
site_series/S017.json 有数据
S017 在 2024-06-15 10-14 有 5 条记录
S062、S072 也能查到有效记录
```

但页面同样选择：

```text
单站点 S017
日期 2024-06-15 至 2024-06-15
小时 10:00 至 14:00
```

仍显示：

```text
样本数 0
站点数 0
当前筛选条件下暂无折线图数据
```

这说明问题不在模型、不在 pkl、不在 JSON 导出，而在前端：

```text
控件显示值、state 状态值、filterSiteRows 实际读取值没有统一
```

或者：

```text
单站点模式下 refreshAll 没有真正使用 site_series/S017.json 的 rows
```

本轮目标是恢复早期 Round12/Round17 中稳定的数据流：

```text
refreshAll()
  -> getFilteredRows()
  -> 指标卡和折线图共用同一个 rows
  -> setLineRows(rows)
  -> resetLineZoom()
```

不要让指标卡和折线图各自重新取数据。

---

## 二、本轮只修改这些文件

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

如项目已拆分 JS，也同步修改实际 JS 文件：

```text
stages/05_visualization/*.js
```

不修改：

```text
output/pv_pipeline/tables/*.pkl
output/pv_pipeline/interactive_dashboard/*.json
output/pv_pipeline/metrics/*.csv
```

---

## 三、先做数据存在性检查

在项目根目录执行：

```bash
python - <<'PY'
import json
from pathlib import Path

root = Path("output/pv_pipeline/interactive_dashboard/site_series")
for sid in ["S017", "S062", "S072"]:
    p = root / f"{sid}.json"
    data = json.load(open(p, encoding="utf-8"))
    sub = []
    for r in data:
        d = r.get("date") or str(r.get("time", ""))[:10]
        h = r.get("hour")
        if h is None:
            h = int(str(r.get("time", ""))[11:13])
        h = int(h)
        if d == "2024-06-15" and 10 <= h <= 14:
            sub.append(r)
    print(sid, "all_rows=", len(data), "2024-06-15 10-14 rows=", len(sub))
    if sub:
        print("sample=", sub[0])
PY
```

如果这里 `S017 2024-06-15 10-14 rows` 大于 0，而网页仍为 0，继续执行下面修复。

---

## 四、彻底统一页面状态读取

### 4.1 增加统一控件读取函数

在 HTML 的 `<script>` 中加入或替换以下函数。

注意：后续所有筛选都只能调用这些函数，不要到处直接读 DOM。

```javascript
function pad2(v) {
  return String(v).padStart(2, "0");
}

function parseHourValue(v) {
  if (typeof v === "number") return v;
  const s = String(v || "").trim();
  if (!s) return 0;
  return Number.parseInt(s.split(":")[0], 10);
}

function getComboDate(prefix) {
  const y = document.getElementById(`${prefix}-year`)?.value
    || document.getElementById(`${prefix}Year`)?.value;
  const m = document.getElementById(`${prefix}-month`)?.value
    || document.getElementById(`${prefix}Month`)?.value;
  const d = document.getElementById(`${prefix}-day`)?.value
    || document.getElementById(`${prefix}Day`)?.value;

  return `${y}-${pad2(m)}-${pad2(d)}`;
}

function getStartDateString() {
  return state.startDate || getComboDate("start");
}

function getEndDateString() {
  return state.endDate || getComboDate("end");
}

function getStartHourValue() {
  return parseHourValue(
    state.startHour ?? document.getElementById("start-hour")?.value
      ?? document.getElementById("startHour")?.value
  );
}

function getEndHourValue() {
  return parseHourValue(
    state.endHour ?? document.getElementById("end-hour")?.value
      ?? document.getElementById("endHour")?.value
  );
}

function syncStateFromControls() {
  const scopeInput = document.querySelector('input[name="scope"]:checked');
  if (scopeInput) state.scope = scopeInput.value;

  const siteSelect = document.getElementById("site-select") || document.getElementById("siteSelect");
  if (siteSelect && siteSelect.value) state.siteId = siteSelect.value;

  state.startDate = getComboDate("start");
  state.endDate = getComboDate("end");
  state.startHour = getStartHourValue();
  state.endHour = getEndHourValue();
}
```

如果项目里的控件 ID 和上述不同，按实际 ID 补齐，但最终必须保证：

```text
getStartDateString() 返回 2024-06-15
getEndDateString() 返回 2024-06-15
getStartHourValue() 返回 10
getEndHourValue() 返回 14
```

---

## 五、重写单站点数据加载

### 5.1 增加站点数据缓存

```javascript
const gSiteSeriesCache = {};
let gCurrentSiteRows = [];
```

如果已有同名变量，保留一个即可。

### 5.2 新增 `ensureSiteRows`

```javascript
async function ensureSiteRows(siteId) {
  if (!siteId) return [];

  if (!gSiteSeriesCache[siteId]) {
    const rows = await fetchJSON(`site_series/${siteId}.json`);
    gSiteSeriesCache[siteId] = Array.isArray(rows) ? rows : [];
    console.info("[ensureSiteRows]", siteId, "loaded", gSiteSeriesCache[siteId].length);
  }

  gCurrentSiteRows = gSiteSeriesCache[siteId];
  return gCurrentSiteRows;
}
```

注意：不能把 `site_series` 当成字典读取，当前导出格式是每个站点一个 JSON 文件。

---

## 六、重写过滤函数

### 6.1 增加通用行日期和小时读取

```javascript
function rowDate(r) {
  return String(r.date || r.time || "").slice(0, 10);
}

function rowHour(r) {
  if (r.hour !== undefined && r.hour !== null && r.hour !== "") {
    const h = Number(r.hour);
    if (Number.isFinite(h)) return h;
  }
  const t = String(r.time || "");
  return parseHourValue(t.slice(11, 16));
}
```

### 6.2 重写 `filterRowsByCurrentControls`

```javascript
function filterRowsByCurrentControls(rows) {
  syncStateFromControls();

  const startDate = getStartDateString();
  const endDate = getEndDateString();
  const startHour = getStartHourValue();
  const endHour = getEndHourValue();

  const filtered = (Array.isArray(rows) ? rows : []).filter((r) => {
    const d = rowDate(r);
    const h = rowHour(r);
    return (
      d >= startDate &&
      d <= endDate &&
      h >= startHour &&
      h <= endHour
    );
  });

  console.info("[filterRowsByCurrentControls]", {
    scope: state.scope,
    siteId: state.siteId,
    inputRows: Array.isArray(rows) ? rows.length : 0,
    filteredRows: filtered.length,
    startDate,
    endDate,
    startHour,
    endHour,
    firstInput: Array.isArray(rows) ? rows[0] : null,
    firstFiltered: filtered[0] || null,
  });

  return filtered;
}
```

---

## 七、恢复早期正常的数据流：getFilteredRows

找到当前 `getFilteredRows()`，整体替换为：

```javascript
async function getFilteredRows() {
  syncStateFromControls();

  if (state.scope === "site") {
    const siteId = state.siteId;
    const siteRows = await ensureSiteRows(siteId);
    return filterRowsByCurrentControls(siteRows);
  }

  return filterRowsByCurrentControls(gCityRows || []);
}
```

关键要求：

```text
单站点模式只能过滤 site_series/Sxxx.json
全市模式只能过滤 city_series.json
```

不要在单站点模式过滤 `gCityRows`。

---

## 八、恢复早期正常的数据流：refreshAll

找到当前 `refreshAll()`，整体替换为：

```javascript
async function refreshAll() {
  const rows = await getFilteredRows();
  const isSite = state.scope === "site";

  console.info("[refreshAll]", {
    scope: state.scope,
    siteId: state.siteId,
    rows: rows.length,
    firstRow: rows[0] || null,
  });

  const metrics = computeMetrics(rows, isSite);
  updateMetricsCards(metrics, rows);

  setLineRows(rows);
  resetLineZoom();

  if (typeof drawHourlyNrmseChart === "function") {
    drawHourlyNrmseChart();
  }
  if (!isSite && typeof drawScatterChart === "function") {
    drawScatterChart(gScatterSite);
  }
}
```

关键要求：

```text
指标卡和折线图必须共用同一个 rows
```

如果指标卡是 0，折线图也 0；如果控制台 `rows > 0`，指标卡和折线图都必须有值。

---

## 九、修复站点切换事件

找到站点下拉框事件，替换为：

```javascript
async function onSiteChange() {
  syncStateFromControls();

  const siteSelect = document.getElementById("site-select") || document.getElementById("siteSelect");
  if (siteSelect && siteSelect.value) {
    state.siteId = siteSelect.value;
  }

  if (state.scope !== "site") {
    state.scope = "site";
    const siteRadio = document.querySelector('input[name="scope"][value="site"]');
    if (siteRadio) siteRadio.checked = true;
  }

  await ensureSiteRows(state.siteId);
  await refreshAll();
}
```

绑定事件时必须支持 async：

```javascript
const siteSelect = document.getElementById("site-select") || document.getElementById("siteSelect");
if (siteSelect) {
  siteSelect.addEventListener("change", () => {
    onSiteChange().catch(console.error);
  });
}
```

---

## 十、修复展示对象切换事件

找到 `onScopeChange()`，确保单站点模式会加载默认站点：

```javascript
async function onScopeChange() {
  syncStateFromControls();

  if (state.scope === "site") {
    const siteSelect = document.getElementById("site-select") || document.getElementById("siteSelect");
    if (!state.siteId && siteSelect && siteSelect.options.length > 0) {
      state.siteId = siteSelect.value || siteSelect.options[0].value;
      siteSelect.value = state.siteId;
    }
    await ensureSiteRows(state.siteId);
  }

  await refreshAll();
}
```

绑定 radio 时：

```javascript
document.querySelectorAll('input[name="scope"]').forEach((input) => {
  input.addEventListener("change", () => {
    onScopeChange().catch(console.error);
  });
});
```

---

## 十一、不要让 10-14 按钮破坏单站点模式

当前两个按钮：

```text
当前日期10-14
典型日10-14
```

不要无条件执行：

```javascript
state.scope = "city";
```

### 11.1 当前日期 10-14

```javascript
const btnCurrentMidday = document.getElementById("btn-current-midday");
if (btnCurrentMidday) {
  btnCurrentMidday.addEventListener("click", async () => {
    syncStateFromControls();
    state.startHour = 10;
    state.endHour = 14;
    setHourControls(10, 14);
    await refreshAll();
  });
}
```

### 11.2 典型日 10-14

如果这个按钮设计为全市典型日，可以保留切全市；如果用户当前是单站点，不要自动覆盖站点选择，除非按钮文案明确写“全市典型日”。

建议当前先改成：

```javascript
const btnTypicalMidday = document.getElementById("btn-typical-midday");
if (btnTypicalMidday) {
  btnTypicalMidday.addEventListener("click", async () => {
    syncStateFromControls();
    const typicalDate = pickTypicalMiddayDate();
    if (typicalDate) {
      state.startDate = typicalDate;
      state.endDate = typicalDate;
      setDateComboValue("start", typicalDate);
      setDateComboValue("end", typicalDate);
    }
    state.startHour = 10;
    state.endHour = 14;
    setHourControls(10, 14);
    await refreshAll();
  });
}
```

---

## 十二、补齐辅助函数

如果页面中没有以下函数，请补齐。

```javascript
function setHourControls(startHour, endHour) {
  const s1 = document.getElementById("start-hour") || document.getElementById("startHour");
  const e1 = document.getElementById("end-hour") || document.getElementById("endHour");
  if (s1) s1.value = `${pad2(startHour)}:00`;
  if (e1) e1.value = `${pad2(endHour)}:00`;
}

function setDateComboValue(prefix, dateStr) {
  const [y, m, d] = String(dateStr).split("-");
  const yEl = document.getElementById(`${prefix}-year`) || document.getElementById(`${prefix}Year`);
  const mEl = document.getElementById(`${prefix}-month`) || document.getElementById(`${prefix}Month`);
  const dEl = document.getElementById(`${prefix}-day`) || document.getElementById(`${prefix}Day`);
  if (yEl) yEl.value = y;
  if (mEl) mEl.value = m;
  if (dEl) dEl.value = d;
}
```

---

## 十三、保留 Round17 的绘图兜底

确认 `drawLineChart(rows)` 开头有防御式逻辑：

```javascript
function drawLineChart(rows) {
  const svg = document.getElementById("line-chart");
  if (!svg) {
    console.error("line-chart svg not found");
    return;
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
  // 后续绘图逻辑保持原有
}
```

字段读取必须兼容：

```javascript
function getActualValue(r) {
  const v = r.actual_mw ?? r.power_mw ?? r.actual ?? r.y_true ?? null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function getPredValue(r) {
  const v = r.pred_mw ?? r.power_pred_final ?? r.power_pred ?? r.pred ?? r.y_pred ?? null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
```

---

## 十四、静态检查

执行：

```bash
python - <<'PY'
from pathlib import Path
import re

p = Path("stages/05_visualization/interactive_forecast_dashboard.html")
text = p.read_text(encoding="utf-8")

required = [
    "syncStateFromControls",
    "ensureSiteRows",
    "filterRowsByCurrentControls",
    "async function getFilteredRows",
    "async function refreshAll",
    "setLineRows",
    "resetLineZoom",
    "site_series/${siteId}.json",
]

missing = [x for x in required if x not in text]
assert not missing, "缺少关键逻辑: " + ", ".join(missing)

assert "state.scope = \"city\";" not in text or "btnTypicalMidday" in text, "仍可能存在10-14按钮强制切全市逻辑，请人工核查"

scripts = re.findall(r"<script[^>]*>(.*?)</script>", text, flags=re.S | re.I)
Path("/tmp/interactive_dashboard_script.js").write_text("\\n".join(scripts), encoding="utf-8")
print("[OK] static text check passed")
PY

node --check /tmp/interactive_dashboard_script.js
```

---

## 十五、浏览器验收步骤

启动服务：

```bash
python -m http.server 8070
```

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round39_5
```

强制刷新：

```text
Ctrl + Shift + R
```

打开控制台，选择：

```text
单站点
S017 富云四队光伏
2024-06-15 至 2024-06-15
10:00 至 14:00
```

控制台必须看到：

```text
[ensureSiteRows] S017 loaded ...
[filterRowsByCurrentControls] filteredRows: 5
[refreshAll] rows: 5
```

页面必须看到：

```text
样本数 5
站点数 1
站点 S017 功率曲线
```

再检查：

```text
S062，日期 2024-06-15，10:00-14:00
S072，日期 2024-06-15，10:00-14:00
```

如果某个站点该日确实无数据，控制台应显示：

```text
inputRows > 0
filteredRows = 0
startDate / endDate / startHour / endHour / firstInput
```

这时根据 `firstInput` 的日期范围换一个有数据日期，不应影响其他站点。

---

## 十六、如果仍然没有曲线，必须回传这些输出

```bash
python - <<'PY'
import json
from pathlib import Path
sid = "S017"
p = Path(f"output/pv_pipeline/interactive_dashboard/site_series/{sid}.json")
data = json.load(open(p, encoding="utf-8"))
sub = [
    r for r in data
    if (r.get("date") or str(r.get("time",""))[:10]) == "2024-06-15"
    and 10 <= int(r.get("hour", str(r.get("time",""))[11:13])) <= 14
]
print("file", p)
print("all rows", len(data))
print("sub rows", len(sub))
print("first", data[0] if data else None)
print("sub sample", sub[:5])
PY
```

同时在浏览器控制台回传：

```text
[ensureSiteRows]
[filterRowsByCurrentControls]
[refreshAll]
```

这三段日志。

---

## 十七、本轮通过标准

1. 页面不再显示旧典型站点警告，或者警告逻辑改为只比较 `typical_sites.json`，不再混用 `site_metrics.json` 排名。
2. 全市模式正常显示曲线。
3. 单站点模式选择 `S017/S062/S072` 都能显示曲线。
4. 单站点指标卡样本数与折线图点数一致。
5. `当前日期10-14` 不再强制切换全市。
6. `computeMetrics(rows)` 与 `drawLineChart(rows)` 使用同一个筛选结果。
7. 不重新训练。

