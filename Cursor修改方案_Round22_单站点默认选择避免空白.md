# Cursor 修改方案 Round22：单站点模式增加默认站点，避免初始空白

## 一、修改目标

当前可视化页面在选择“展示对象：单站点”时，如果站点下拉框没有默认值，图表区域会出现空白，用户需要手动再选一次站点才能显示数据。

本轮目标：

- 切换到“单站点”时自动选择一个可用默认站点。
- 页面初始化时如果默认就是单站点，也必须自动选中默认站点。
- 默认站点优先选择“预测最好”里的第一个站点；如果没有，则选择全部站点列表中的第一个有效站点。
- 自动选择后立即刷新图表、指标卡、逐小时表。
- 不修改训练结果，不修改数据文件。

## 二、涉及文件

主要修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

如果项目已经拆分出 JS/CSS 文件，则同步修改对应文件：

```text
stages/05_visualization/*.js
stages/05_visualization/*.css
```

## 三、问题定位

请在页面 JS 中搜索：

```text
scope
station-select
selectedStation
stationId
onScopeChange
refreshAll
renderStationOptions
typical
```

重点检查这些逻辑：

- 单站点 radio 切换时，是否只是显示站点下拉框，但没有设置默认站点。
- `state.stationId` 或 `state.selectedStation` 是否为空。
- `refreshAll()` 是否在站点为空时直接返回，导致图表空白。

## 四、新增默认站点选择函数

在 JS 中加入以下函数。字段名请根据当前数据实际情况微调，常见字段可能是 `station_id`、`site_id`、`id`。

```js
function getStationId(row) {
  return row?.station_id || row?.site_id || row?.id || row?.stationId || row?.siteId || "";
}

function getStationCategory(row) {
  return row?.category || row?.类别 || row?.type || "";
}

function getDefaultStationId() {
  const stationList = Array.isArray(gStationSummary) ? gStationSummary : [];

  const best = stationList.find((row) => {
    const category = String(getStationCategory(row));
    return category.includes("预测最好") && getStationId(row);
  });

  if (best) {
    return getStationId(best);
  }

  const firstValid = stationList.find((row) => getStationId(row));
  return firstValid ? getStationId(firstValid) : "";
}
```

如果当前项目里站点汇总数据变量不叫 `gStationSummary`，请改成真实变量名，例如：

```text
gSites
gStationRows
gSiteSummary
stationSummary
```

## 五、新增确保单站点默认值函数

```js
function ensureDefaultStationSelected() {
  const stationSelect = document.getElementById("station-select");
  if (!stationSelect) return false;

  const currentValue = stationSelect.value || state.stationId || state.selectedStation || "";

  if (currentValue) {
    state.stationId = currentValue;
    state.selectedStation = currentValue;
    return true;
  }

  const defaultStationId = getDefaultStationId();
  if (!defaultStationId) {
    return false;
  }

  stationSelect.value = defaultStationId;
  state.stationId = defaultStationId;
  state.selectedStation = defaultStationId;

  return true;
}
```

说明：

- 同时写入 `state.stationId` 和 `state.selectedStation`，是为了兼容当前代码里可能使用不同字段名。
- 如果当前项目只有一个字段，请保留实际使用的字段即可。

## 六、修改单站点切换逻辑

找到当前展示对象 radio 的事件绑定，通常类似：

```js
document.querySelectorAll('input[name="scope"]').forEach(...)
```

或：

```js
function onScopeChange() { ... }
```

将单站点分支改为：

```js
function onScopeChange() {
  const checked = document.querySelector('input[name="scope"]:checked');
  state.scope = checked ? checked.value : state.scope;

  const stationWrap = document.getElementById("station-select-wrap");
  if (stationWrap) {
    stationWrap.style.display = state.scope === "station" ? "inline-flex" : "none";
  }

  if (state.scope === "station") {
    const ok = ensureDefaultStationSelected();
    if (!ok) {
      showStatusMessage("没有可用站点数据，无法展示单站点曲线");
      return;
    }
  }

  if (!validateDateRange(true)) {
    return;
  }

  refreshAll();
}
```

如果当前代码没有 `showStatusMessage`，可以临时用：

```js
alert("没有可用站点数据，无法展示单站点曲线");
```

但更推荐使用页面内提示，不要频繁弹窗。

## 七、修改站点下拉框初始化逻辑

找到渲染站点下拉框的函数，例如：

```js
renderStationOptions()
populateStationSelect()
initStationSelect()
```

在填充 option 后增加：

```js
if (state.scope === "station") {
  ensureDefaultStationSelected();
}
```

完整示例：

```js
function renderStationOptions() {
  const stationSelect = document.getElementById("station-select");
  if (!stationSelect) return;

  stationSelect.innerHTML = "";

  const stationList = Array.isArray(gStationSummary) ? gStationSummary : [];

  stationList.forEach((row) => {
    const id = getStationId(row);
    if (!id) return;

    const name = row.station_name || row.site_name || row.name || row["站点名称"] || id;

    const option = document.createElement("option");
    option.value = id;
    option.textContent = `${id} ${name}`;
    stationSelect.appendChild(option);
  });

  if (state.scope === "station") {
    ensureDefaultStationSelected();
  }
}
```

## 八、修改站点下拉框变化逻辑

确保用户手动选择站点后，状态被正确写入并刷新。

```js
const stationSelect = document.getElementById("station-select");

if (stationSelect) {
  stationSelect.addEventListener("change", () => {
    state.stationId = stationSelect.value;
    state.selectedStation = stationSelect.value;

    if (!validateDateRange(true)) {
      return;
    }

    refreshAll();
  });
}
```

## 九、修改刷新前兜底

在 `refreshAll()` 开头加兜底，防止任何路径进入单站点时站点为空。

```js
function refreshAll() {
  if (state.scope === "station") {
    const ok = ensureDefaultStationSelected();
    if (!ok) {
      clearChartsAndCards("没有可用站点数据");
      return;
    }
  }

  if (!validateDateRange(true)) {
    return;
  }

  // 保留原来的刷新逻辑
}
```

如果没有 `clearChartsAndCards`，不要强行新增复杂逻辑，可以只 `return`，但建议至少在页面显示一行提示。

## 十、页面初始化时也要兜底

在数据加载完成、站点列表渲染完成之后，加入：

```js
renderStationOptions();

if (state.scope === "station") {
  ensureDefaultStationSelected();
}

refreshAll();
```

注意顺序必须是：

```text
先加载数据 -> 再渲染站点下拉框 -> 再确保默认站点 -> 最后刷新图表
```

否则站点 option 还没生成时，默认值会设置失败。

## 十一、默认站点选择规则

默认站点按以下优先级：

1. `类别` 或 `category` 包含 `预测最好` 的第一个站点。
2. 如果没有“预测最好”，选择站点列表第一个有效站点。
3. 如果站点列表为空，显示提示，不刷新空图。

这样做的原因：

- “预测最好”站点通常数据质量更稳定，第一次展示效果更直观。
- 如果没有分类数据，也能保证页面不是空白。

## 十二、验证步骤

启动网页：

```bash
cd /path/to/photovoltaic_forecasting_pj
python -m http.server 8060
```

打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

验证：

1. 页面初始展示“全市”时正常。
2. 点击“单站点”后，站点下拉框自动出现。
3. 下拉框自动选中一个站点，不为空。
4. 图表立即显示该站点真实功率和预测功率。
5. 指标卡同步变为该站点指标。
6. 再手动切换其他站点，图表和指标正常刷新。
7. 切回“全市”，站点下拉框隐藏或不影响全市结果。
8. 再切回“单站点”，保留上一次选择的站点；如果上一次站点不可用，则重新选择默认站点。

## 十三、验收标准

- 选择“单站点”后页面不再空白。
- 站点下拉框默认有值。
- 默认站点优先来自“预测最好”分类。
- 用户手动选择站点后不被自动覆盖。
- 页面初始化、切换展示对象、刷新按钮、日期变化后都不会因为站点为空导致图表空白。
- 不改训练数据、不改预测数据、不重新训练。

