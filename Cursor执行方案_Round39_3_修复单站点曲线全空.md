# Round39.3 修复单站点功率曲线全空方案

## 一、当前现象

页面已经显示：

```text
数据版本：Round36
预测列：power_pred_final
默认不含 future
```

说明页面已经读到了新 `metadata.json`。

但所有单站点切换后仍显示：

```text
样本数 0
站点数 0
当前筛选条件下暂无折线图数据
```

这说明问题已经不是训练数据版本，而是**单站点前端数据读取或筛选逻辑错误**。

最可能原因：

1. `site_series/Sxxx.json` 文件路径不对；
2. `site_series` JSON 结构和前端解析逻辑不一致；
3. JSON 中站点字段不是前端使用的 `site_id`；
4. JSON 中时间字段格式无法被前端日期筛选识别；
5. JSON 中小时字段缺失，前端用 `row.hour` 筛选导致全空；
6. 单站点模式仍套用了“当前日期10-14”的全市筛选逻辑；
7. 前端选择站点 ID 与 JSON 文件名不一致；
8. HTML 中仍有旧的 `gSiteSeries` / `siteDataMap` 结构引用。

本轮不需要重新训练，只修单站点可视化读取和筛选。

## 二、目标

修复后：

1. 任意有 test/train/valid 数据的单站点都能显示功率曲线；
2. 单站点指标卡不再全为 0；
3. 默认单站点选择一个有数据站点；
4. 单站点模式下禁用或正确处理“当前日期10-14”“典型日10-14”；
5. `site_series/Sxxx.json` 与前端字段完全匹配；
6. `check_dashboard_prediction_values_round36.py` 仍全部 PASS。

## 三、Cursor 执行步骤

### Step 1：检查 site_series 文件是否存在且有数据

在项目根目录执行：

```bash
ls output/pv_pipeline/interactive_dashboard/site_series | head
ls -lh output/pv_pipeline/interactive_dashboard/site_series/S017.json
ls -lh output/pv_pipeline/interactive_dashboard/site_series/S062.json
ls -lh output/pv_pipeline/interactive_dashboard/site_series/S072.json
```

然后检查 JSON 结构：

```bash
python - <<'PY'
import json
from pathlib import Path
for sid in ["S017", "S062", "S072"]:
    p = Path(f"output/pv_pipeline/interactive_dashboard/site_series/{sid}.json")
    print("\\n==", sid, p.exists(), p.stat().st_size if p.exists() else None)
    if p.exists():
        data = json.load(open(p, encoding="utf-8"))
        print("type:", type(data), "len:", len(data) if isinstance(data, list) else "not-list")
        rows = data[:3] if isinstance(data, list) else []
        for r in rows:
            print(r)
PY
```

确认每行至少有：

```text
time
actual_mw
pred_mw
capacity_mw
split
hour
site_id
```

如果没有 `site_id` 或 `hour`，需要在导出脚本补上。

### Step 2：修复导出脚本，保证 site_series 字段完整

修改：

```text
scripts/export_interactive_dashboard_data.py
```

导出每个站点 JSON 时，每行必须包含：

```python
{
    "site_id": str(row["site_id"]),
    "site_name": str(row.get("site_name", "")),
    "time": pd.to_datetime(row["time"]).strftime("%Y-%m-%d %H:%M:%S"),
    "date": pd.to_datetime(row["time"]).strftime("%Y-%m-%d"),
    "hour": int(pd.to_datetime(row["time"]).hour),
    "split": str(row["split"]),
    "actual_mw": round(float(row["power_mw"]), 4) if pd.notna(row["power_mw"]) else None,
    "pred_mw": round(float(row[pred_col]), 4) if pd.notna(row[pred_col]) else None,
    "capacity_mw": round(float(row["capacity_mw"]), 4) if pd.notna(row["capacity_mw"]) else None,
}
```

确保导出前过滤：

```python
df_vis = df[
    (df["split"].isin(["train", "valid", "test"])) &
    (df["hour"].between(6, 19))
].copy()
```

不要只导出 test，也不要导出 future。

### Step 3：检查前端读取的 site_series 路径

在 HTML 中搜索：

```bash
grep -n "site_series\\|loadSite\\|selectedSite\\|siteId\\|site_id" stages/05_visualization/interactive_forecast_dashboard.html | head -200
```

前端加载单站点时，应使用：

```javascript
const rows = await fetchJSON(`site_series/${siteId}.json`);
```

不能写成：

```javascript
fetch(`data/site_series/${siteId}.json`)
fetch(`site_series/${siteName}.json`)
fetch(`${siteId}.json`)
```

如果站点选择框 option 的 value 是站点名称，而不是站点 ID，要改成：

```javascript
option.value = site.site_id;
option.textContent = `${site.site_id} ${site.site_name}`;
```

### Step 4：修复单站点筛选逻辑

在 HTML 中找到过滤函数，通常类似：

```javascript
function getFilteredRows()
function filterRows()
function applyFilters()
function renderChart()
```

单站点模式下应使用：

```javascript
let rows = currentSiteRows || [];
```

而不是继续使用全市数据：

```javascript
citySeries
allRows
gCityRows
```

正确逻辑：

```javascript
function getFilteredRows() {
  const isSiteMode = document.querySelector('input[name="displayMode"]:checked').value === "site";
  let rows = isSiteMode ? (window.currentSiteRows || []) : (window.cityRows || []);

  const startDate = getStartDateString(); // YYYY-MM-DD
  const endDate = getEndDateString();
  const startHour = parseInt(document.getElementById("startHour").value, 10);
  const endHour = parseInt(document.getElementById("endHour").value, 10);

  rows = rows.filter(r => {
    const d = (r.date || String(r.time).slice(0, 10));
    const h = Number.isFinite(+r.hour) ? +r.hour : new Date(r.time.replace(" ", "T")).getHours();
    return d >= startDate && d <= endDate && h >= startHour && h <= endHour;
  });

  return rows;
}
```

注意：

1. `r.date` 优先；
2. 没有 `r.hour` 时再从 `time` 解析；
3. 日期比较使用 `YYYY-MM-DD` 字符串；
4. 不要用本地时区把 `2023-01-01 06:00:00` 解析偏移成前一天。

### Step 5：单站点切换时必须异步加载并渲染

站点下拉框变化时：

```javascript
async function onSiteChange() {
  const siteId = document.getElementById("siteSelect").value;
  window.currentSiteRows = await fetchJSON(`site_series/${siteId}.json`);
  renderAll();
}
```

展示模式切换到单站点时：

```javascript
async function onDisplayModeChange() {
  if (isSiteMode()) {
    const siteId = document.getElementById("siteSelect").value || getDefaultSiteId();
    document.getElementById("siteSelect").value = siteId;
    window.currentSiteRows = await fetchJSON(`site_series/${siteId}.json`);
  }
  renderAll();
}
```

不要只改 radio 状态而不加载站点 JSON。

### Step 6：默认单站点选择有数据站点

加载站点列表时，默认选：

```text
S062
```

如果 S062 不存在，则选择第一个 `site_series` 存在且行数 > 0 的站点。

实现：

```javascript
function getDefaultSiteId() {
  const preferred = ["S062", "S023", "S049", "S047", "S056"];
  const siteIds = Array.from(document.getElementById("siteSelect").options).map(o => o.value);
  return preferred.find(x => siteIds.includes(x)) || siteIds[0];
}
```

### Step 7：单站点模式下处理 10-14 按钮

当前页面提示：

```text
"当前日期10-14"只筛选当前日期范围内的全市10-14点数据
```

在单站点模式下这个逻辑容易误导。

修改为：

1. 如果选择单站点，则按钮文案改为：

```text
当前站点10-14
典型站点日10-14
```

或：

2. 直接禁用这两个按钮：

```javascript
button.disabled = isSiteMode;
```

推荐第一种：让它按当前站点数据筛选 10-14。

按钮逻辑应使用 `getFilteredRows()`，不要固定用全市数据。

### Step 8：增加单站点调试信息

临时在控制台输出：

```javascript
console.log("[site]", siteId, "loaded rows", window.currentSiteRows?.length);
console.log("[site]", siteId, "filtered rows", getFilteredRows().length);
console.log("[site sample]", window.currentSiteRows?.[0]);
```

确认：

```text
loaded rows > 0
filtered rows > 0
```

修复后可以保留简短日志，也可以删除。

### Step 9：重新导出并验证

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

### Step 10：浏览器验证

打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html?v=site_fix
```

强制刷新：

```text
Ctrl + Shift + R
```

验证：

1. 选择单站点 `S062`，有曲线；
2. 选择单站点 `S023`，有曲线；
3. 选择单站点 `S072`，有曲线；
4. 指标卡样本数不为 0；
5. 图表标题显示正确站点；
6. 日期范围 `2023-01-01 ~ 2025-12-31`、小时 `06:00 ~ 19:00` 下有数据；
7. 点击预测最好按钮后自动切到对应站点并显示曲线。

## 四、验收标准

Round39.3 通过必须满足：

1. 所有 `site_series/Sxxx.json` 存在且非空。
2. `site_series` 每行包含 `site_id/date/hour/time/actual_mw/pred_mw/capacity_mw/split`。
3. 单站点模式下 `S062/S023/S072` 均能显示功率曲线。
4. 单站点指标卡样本数不为 0。
5. 单站点曲线使用 `pred_mw = power_pred_final`。
6. 全市模式仍正常。
7. `check_dashboard_prediction_values_round36.py` 全部 PASS。
8. `posttrain_validation_round36.py` 0 FAIL / 0 WARN。

## 五、完成后回传

请回传：

```bash
python scripts/check_dashboard_prediction_values_round36.py
python scripts/posttrain_validation_round36.py
python - <<'PY'
import json
from pathlib import Path
for sid in ["S062", "S023", "S072"]:
    p = Path(f"output/pv_pipeline/interactive_dashboard/site_series/{sid}.json")
    data = json.load(open(p, encoding="utf-8"))
    print(sid, len(data), data[0] if data else None)
PY
```

以及单站点 `S062` 和 `S072` 的页面截图。
