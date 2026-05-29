# Round39.4 彻底修复混读数据源和单站点无曲线

## 一、当前现象

页面顶部显示：

```text
数据版本：Round36（power_pred_final）
```

但仍提示：

```text
预测最好站点不是 [S062, S023, S049, S047, S056]
当前为 [S077, S023, S031, S062, S049]

预测最差站点不是 [S007, S063, S065, S041, S072]
当前为 [S019, S076, S053, S044, S045]
```

同时所有单站点曲线仍为空。

这说明现在不是训练问题，而是前端仍在**混读数据源**：

```text
metadata.json 是新的
typical/site_metrics/site_series 仍可能是旧的或读取路径不一致
```

也可能是：

```text
site_series JSON 有数据，但前端日期/小时筛选字段不匹配，导致过滤后全空
```

本轮不需要重新训练。

## 二、修复目标

1. 页面所有数据只允许来自同一个目录：

```text
output/pv_pipeline/interactive_dashboard/
```

2. 页面加载时必须把实际请求 URL 打印出来。
3. `metadata.json`、`typical_sites.json`、`site_metrics.json`、`site_series/Sxxx.json` 必须来自同一个 `DATA_ROOT`。
4. 单站点模式下必须能显示 `S062`、`S017`、`S072` 曲线。
5. 如果某站点某天无数据，页面必须说明“当前日期无数据”，而不是所有单站点都空。
6. 页面不再出现旧典型站点警告。

## 三、Cursor 执行步骤

### Step 1：确认浏览器实际访问路径对应的 HTML

当前访问：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

所以实际 HTML 是：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

先确认这个文件不是旧副本：

```bash
grep -n "DATA_ROOT\\|DASHBOARD_BASE\\|fetchJSON\\|typical_sites\\|site_series\\|metadata" \
  stages/05_visualization/interactive_forecast_dashboard.html | head -200
```

如果 `output/pv_pipeline/interactive_dashboard/index.html` 也存在，不要以为它会影响当前页面。当前 URL 只看 `stages/05_visualization/interactive_forecast_dashboard.html`。

### Step 2：强制统一前端数据根路径

在：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

中定义唯一数据根：

```javascript
const DATA_ROOT = "../../output/pv_pipeline/interactive_dashboard";
const DASHBOARD_BASE = DATA_ROOT; // 兼容旧引用
```

然后搜索并替换所有旧路径：

```bash
grep -n "data/\\|DASHBOARD_BASE\\|output/pv_pipeline\\|interactive_dashboard" \
  stages/05_visualization/interactive_forecast_dashboard.html | head -200
```

要求：

1. 不再出现 `fetch("data/...")`。
2. 不再出现 `fetch("./data/...")`。
3. 不再出现硬编码旧 JSON 路径。
4. 所有 JSON 请求都通过：

```javascript
fetchJSON("metadata.json")
fetchJSON("index.json")
fetchJSON("site_metrics.json")
fetchJSON("typical_sites.json")
fetchJSON("city_hourly_nrmse.json")
fetchJSON("site_avg_hourly_nrmse.json")
fetchJSON(`site_series/${siteId}.json`)
```

统一函数：

```javascript
async function fetchJSON(path) {
  const url = `${DATA_ROOT}/${path}?v=${Date.now()}`;
  console.log("[fetchJSON]", path, "=>", url);
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`加载数据失败: ${url} (${res.status})`);
  return await res.json();
}
```

### Step 3：删除或禁用前端旧数据缓存变量

在 HTML 中搜索：

```bash
grep -n "gTypical\\|typicalSites\\|siteMetrics\\|indexData\\|cached\\|localStorage\\|sessionStorage" \
  stages/05_visualization/interactive_forecast_dashboard.html | head -200
```

如果页面用 `localStorage` / `sessionStorage` 缓存旧数据，全部删除。

如果有全局变量：

```javascript
gTypicalSites
gSiteMetrics
gIndex
```

初始化时必须重新赋值：

```javascript
gMetadata = await fetchJSON("metadata.json");
gIndex = await fetchJSON("index.json");
gSiteMetrics = await fetchJSON("site_metrics.json");
gTypicalSites = await fetchJSON("typical_sites.json");
```

不要从 HTML 内嵌常量读取旧典型站点。

### Step 4：检查导出目录中的真实文件内容

执行：

```bash
cat output/pv_pipeline/interactive_dashboard/metadata.json
python - <<'PY'
import json
from pathlib import Path
for name in ["typical_sites.json", "site_metrics.json", "index.json"]:
    p = Path("output/pv_pipeline/interactive_dashboard") / name
    print("\\n==", name, p.exists(), p.stat().st_size if p.exists() else None)
    data = json.load(open(p, encoding="utf-8"))
    if isinstance(data, list):
        print("list len", len(data))
        print(data[:8])
    elif isinstance(data, dict):
        print("dict keys", data.keys())
        print(str(data)[:2000])
PY
```

必须确认 `typical_sites.json` 中：

```text
预测最好 = S062, S023, S049, S047, S056
预测最差 = S007, S063, S065, S041, S072
```

如果 `typical_sites.json` 仍是旧的，执行：

```bash
python scripts/export_interactive_dashboard_data.py
```

如果仍旧，说明导出脚本读取了旧 metrics，必须修 `scripts/export_interactive_dashboard_data.py`，强制读取：

```text
output/pv_pipeline/metrics/round36_typical_sites.csv
```

### Step 5：检查 site_series 是否有 S017/S062/S072 数据

执行：

```bash
python - <<'PY'
import json
from pathlib import Path
for sid in ["S017", "S062", "S072"]:
    p = Path(f"output/pv_pipeline/interactive_dashboard/site_series/{sid}.json")
    print("\\n==", sid, "exists", p.exists(), "size", p.stat().st_size if p.exists() else None)
    if not p.exists():
        continue
    data = json.load(open(p, encoding="utf-8"))
    print("rows", len(data))
    print("first", data[0] if data else None)
    # 检查截图日期 2024-06-15 10-14
    sub = [
        r for r in data
        if str(r.get("date", str(r.get("time", ""))[:10])) == "2024-06-15"
        and 10 <= int(r.get("hour", -1)) <= 14
    ]
    print("2024-06-15 10-14 rows", len(sub))
    print("sample", sub[:2])
PY
```

如果这里 `rows > 0` 且 `2024-06-15 10-14 rows > 0`，说明数据没问题，是前端过滤问题。

如果这里为 0，则说明这个站点这一天确实无数据或导出缺字段，要换默认日期或修导出。

### Step 6：修复日期筛选，避免输入值格式不一致

截图中日期控件是年/月/日三个 select。前端必须生成：

```javascript
function pad2(x) {
  return String(x).padStart(2, "0");
}

function getStartDateString() {
  return `${startYear.value}-${pad2(startMonth.value)}-${pad2(startDay.value)}`;
}

function getEndDateString() {
  return `${endYear.value}-${pad2(endMonth.value)}-${pad2(endDay.value)}`;
}
```

不要生成：

```text
2024-6-15
```

因为 JSON 中通常是：

```text
2024-06-15
```

字符串比较时 `2024-6-15` 会导致过滤错误。

### Step 7：修复小时筛选

小时控件值可能是：

```text
10:00
14:00
```

不能直接：

```javascript
parseInt("10:00", 10)
```

虽然通常可行，但建议明确：

```javascript
function parseHour(v) {
  if (typeof v === "number") return v;
  return parseInt(String(v).split(":")[0], 10);
}
```

过滤时：

```javascript
const h = Number.isFinite(Number(r.hour))
  ? Number(r.hour)
  : parseHour(String(r.time).slice(11, 16));
```

### Step 8：修复单站点过滤函数

在 HTML 中找到单站点过滤逻辑，改成：

```javascript
function filterSiteRows(rows) {
  const startDate = getStartDateString();
  const endDate = getEndDateString();
  const startHour = parseHour(document.getElementById("startHour").value);
  const endHour = parseHour(document.getElementById("endHour").value);

  const filtered = rows.filter(r => {
    const d = r.date || String(r.time).slice(0, 10);
    const h = Number.isFinite(Number(r.hour))
      ? Number(r.hour)
      : parseHour(String(r.time).slice(11, 16));
    return d >= startDate && d <= endDate && h >= startHour && h <= endHour;
  });

  console.log("[filterSiteRows]", {
    siteId: state.siteId,
    inputRows: rows.length,
    filteredRows: filtered.length,
    startDate,
    endDate,
    startHour,
    endHour,
    firstRow: rows[0],
    firstFiltered: filtered[0],
  });

  return filtered;
}
```

### Step 9：确认单站点模式没有使用全市 rows

渲染主图时必须类似：

```javascript
let rows;
if (state.scope === "site") {
  rows = filterSiteRows(gCurrentSiteRows || []);
} else {
  rows = filterCityRows(gCityRows || []);
}
```

不能在单站点模式下继续过滤：

```javascript
gCityRows
gAllRows
```

### Step 10：站点切换必须 await 加载

站点切换事件必须是 async：

```javascript
async function onSiteChange() {
  state.siteId = document.getElementById("siteSelect").value;
  gCurrentSiteRows = await fetchJSON(`site_series/${state.siteId}.json`);
  console.log("[siteChange]", state.siteId, gCurrentSiteRows.length, gCurrentSiteRows[0]);
  refreshAll();
}
```

如果不是 await，可能 refreshAll 在 JSON 还没加载前就渲染，导致全空。

### Step 11：刷新按钮也必须重新加载当前站点

点击“刷新”时：

```javascript
async function refreshDataAndRender() {
  gMetadata = await fetchJSON("metadata.json");
  gTypicalSites = await fetchJSON("typical_sites.json");
  gSiteMetrics = await fetchJSON("site_metrics.json");
  if (state.scope === "site" && state.siteId) {
    gCurrentSiteRows = await fetchJSON(`site_series/${state.siteId}.json`);
  }
  refreshAll();
}
```

### Step 12：修复旧典型站点警告

当前警告显示：

```text
当前 [S077, S023, S031, S062, S049]
```

这说明页面实际的 `gTypicalSites` 仍旧。

修复后检查：

```javascript
console.log("[metadata]", gMetadata);
console.log("[typicalSites]", gTypicalSites);
```

如果 `metadata` 正确但 `typicalSites` 旧，说明 `typical_sites.json` 路径不对或旧文件没覆盖。

不要从 `index.json` 或 `site_metrics.json` 推导典型站点，必须直接读取：

```text
typical_sites.json
```

或者确保推导逻辑和 `round36_typical_sites.csv` 一致。

### Step 13：重新运行导出和检查

执行：

```bash
python scripts/export_interactive_dashboard_data.py
python scripts/check_dashboard_prediction_values_round36.py
python scripts/posttrain_validation_round36.py
```

要求：

```text
68/68 PASS
0 FAIL / 0 WARN
```

### Step 14：浏览器强制刷新并检查控制台

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round39_4
```

强制刷新：

```text
Ctrl + Shift + R
```

打开控制台，查看：

```text
[fetchJSON] metadata.json => ../../output/pv_pipeline/interactive_dashboard/metadata.json
[fetchJSON] typical_sites.json => ../../output/pv_pipeline/interactive_dashboard/typical_sites.json
[fetchJSON] site_series/S017.json => ../../output/pv_pipeline/interactive_dashboard/site_series/S017.json
[siteChange] S017 ...
[filterSiteRows] filteredRows > 0
```

如果 `filteredRows = 0`，看日志里的：

```text
startDate
endDate
startHour
endHour
firstRow
```

据此修日期或小时字段。

## 四、验收标准

Round39.4 通过必须满足：

1. 页面不再显示旧典型站点警告。
2. 页面顶部仍显示：

```text
Round36 / power_pred_final / 默认不含 future
```

3. 单站点 `S017` 在 `2024-06-15 10-14` 有曲线，若该日确实无数据，则页面自动提示并可切换到有数据日期。
4. 单站点 `S062` 在任意有效日期范围有曲线。
5. 单站点 `S072` 在任意有效日期范围有曲线。
6. 单站点指标卡样本数不为 0。
7. 全市模式仍正常。
8. `check_dashboard_prediction_values_round36.py` 全部 PASS。
9. `posttrain_validation_round36.py` 0 FAIL / 0 WARN。

## 五、完成后回传

请回传：

```bash
cat output/pv_pipeline/interactive_dashboard/metadata.json
cat output/pv_pipeline/interactive_dashboard/typical_sites.json | head -80
python - <<'PY'
import json
from pathlib import Path
for sid in ["S017", "S062", "S072"]:
    p = Path(f"output/pv_pipeline/interactive_dashboard/site_series/{sid}.json")
    data = json.load(open(p, encoding="utf-8"))
    sub = [
        r for r in data
        if str(r.get("date", str(r.get("time", ""))[:10])) == "2024-06-15"
        and 10 <= int(r.get("hour", -1)) <= 14
    ]
    print(sid, "rows", len(data), "2024-06-15 10-14", len(sub), "first", data[0] if data else None)
PY
python scripts/check_dashboard_prediction_values_round36.py
python scripts/posttrain_validation_round36.py
```

以及单站点 `S017`、`S062` 的页面截图。
