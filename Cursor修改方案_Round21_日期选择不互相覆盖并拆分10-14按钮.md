# Cursor 修改方案 Round21：修复日期选择互相覆盖，并拆分“连云港全市10-14”逻辑

## 一、修改目标

当前可视化页面存在两个问题：

1. 选择开始日期后，再选择结束日期时，开始日期会被自动改掉；或者选择结束日期后，再改开始日期时，结束日期会被自动改掉。这个交互不合理，用户已经选好的日期不应该被程序偷偷修改。
2. “连云港全市10-14”按钮含义不够清楚。它看起来像只是筛选小时，但实际可能还会切换全市、设置 10-14 点、甚至自动选择典型日期，容易导致用户误解当前图上的数据来源。

本轮只修复可视化前端逻辑，不重新训练模型，不修改预测结果文件。

## 二、涉及文件

主要修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

如项目中还有独立的 JS/CSS 文件，则按实际拆分位置同步修改：

```text
stages/05_visualization/*.js
stages/05_visualization/*.css
```

## 三、修复日期选择逻辑

### 3.1 问题原因

当前代码里大概率存在类似逻辑：

```js
if (state.startDate > state.endDate) {
  if (prefix === "start") {
    state.endDate = state.startDate;
    setDateComboValue("end", state.endDate);
  } else {
    state.startDate = state.endDate;
    setDateComboValue("start", state.startDate);
  }
}
```

这段逻辑会在用户改一个日期时，自动覆盖另一个日期。必须删除。

### 3.2 正确逻辑

日期控件应遵守：

- 用户修改开始日期，只更新 `state.startDate`。
- 用户修改结束日期，只更新 `state.endDate`。
- 如果 `startDate > endDate`，页面提示错误，但不要自动改另一个日期。
- 日期非法时，不刷新图表。
- 日期恢复合法后，再正常刷新图表。

### 3.3 新增日期校验函数

在页面 JS 中加入：

```js
function validateDateRange(showMessage = true) {
  const msg = document.getElementById("date-range-message");
  const valid = state.startDate <= state.endDate;

  if (msg) {
    msg.textContent = valid ? "" : "开始日期不能晚于结束日期";
    msg.style.display = valid ? "none" : "inline-flex";
  }

  return valid;
}
```

### 3.4 保留隐藏 date 输入同步函数

如果页面中还有隐藏的原生 `input[type="date"]`，保留同步，但不能反向覆盖用户选择。

```js
function syncHiddenDateInputs() {
  const startInput = document.getElementById("start-date");
  const endInput = document.getElementById("end-date");

  if (startInput) startInput.value = state.startDate;
  if (endInput) endInput.value = state.endDate;
}
```

### 3.5 重写日期变更函数

找到当前处理年月日下拉框变化的函数，例如：

```js
applyDateChange(prefix)
onDateComboChange(prefix)
handleDateSelect(prefix)
```

将核心逻辑改为：

```js
function applyDateChange(prefix) {
  if (prefix === "start") {
    state.startDate = getDateComboValue("start");
  } else {
    state.endDate = getDateComboValue("end");
  }

  syncHiddenDateInputs();

  if (!validateDateRange(true)) {
    return;
  }

  refreshAll();
}
```

重点：这里绝对不要调用 `setDateComboValue("start", state.endDate)` 或 `setDateComboValue("end", state.startDate)`。

### 3.6 页面增加错误提示位置

在日期控件附近加入：

```html
<span id="date-range-message" class="date-error" style="display:none;"></span>
```

CSS：

```css
.date-error {
  align-items: center;
  height: 34px;
  padding: 0 10px;
  border: 1px solid #fecaca;
  border-radius: 6px;
  background: #fef2f2;
  color: #b91c1c;
  font-size: 13px;
  font-weight: 600;
}
```

## 四、拆分“连云港全市10-14”按钮

### 4.1 当前问题

“连云港全市10-14”这个按钮不应该只保留一个，因为它混合了多个动作：

- 切换展示对象为全市；
- 筛选小时为 10-14 点；
- 可能自动选择某个典型日期；
- 刷新主折线图和指标卡。

用户看到这个按钮时，不容易判断它是否会修改日期范围。

### 4.2 修改为两个按钮

把原来的：

```html
<button id="btn-midday">连云港全市10-14</button>
```

改成两个按钮：

```html
<button
  id="btn-current-midday"
  class="btn btn-purple"
  title="保持当前日期范围不变，仅切换为全市视角并筛选10-14点。"
>
  当前日期10-14
</button>

<button
  id="btn-typical-midday"
  class="btn btn-indigo"
  title="自动选择一个10-14点表现接近中位数的典型日期，并切换为全市10-14点。"
>
  典型日10-14
</button>
```

页面上不要再保留旧的 `btn-midday`，避免重复绑定。

## 五、“当前日期10-14”逻辑

这个按钮只改展示范围，不改日期。

```js
const btnCurrentMidday = document.getElementById("btn-current-midday");

if (btnCurrentMidday) {
  btnCurrentMidday.addEventListener("click", () => {
    state.scope = "city";
    state.startHour = 10;
    state.endHour = 14;

    const cityRadio = document.querySelector('input[name="scope"][value="city"]');
    if (cityRadio) cityRadio.checked = true;

    const startHourInput = document.getElementById("start-hour");
    const endHourInput = document.getElementById("end-hour");
    if (startHourInput) startHourInput.value = 10;
    if (endHourInput) endHourInput.value = 14;

    if (typeof onScopeChange === "function") {
      onScopeChange();
    }

    if (!validateDateRange(true)) {
      return;
    }

    refreshAll();
  });
}
```

验收点：

- 点击后开始日期不变。
- 点击后结束日期不变。
- 展示对象切为全市。
- 小时范围变成 10-14。
- 图表展示当前日期范围内的全市 10-14 点数据。

## 六、“典型日10-14”逻辑

这个按钮可以自动改日期，但必须明确它是“典型日”。

### 6.1 典型日选择逻辑

使用 `midday_city_by_date.json` 或当前项目中等价的数据。

推荐逻辑：

1. 读取所有有 10-14 点城市 NRMSE 的日期。
2. 计算这些日期的 NRMSE 中位数。
3. 找到 NRMSE 最接近中位数的日期。
4. 设置开始日期 = 结束日期 = 这个典型日期。
5. 设置展示对象 = 全市。
6. 设置小时 = 10-14。

### 6.2 示例代码

```js
const btnTypicalMidday = document.getElementById("btn-typical-midday");

if (btnTypicalMidday) {
  btnTypicalMidday.addEventListener("click", () => {
    const validDays = (gMiddayByDate || []).filter((d) => {
      const v = Number(d.nrmse_pct);
      return d.date && Number.isFinite(v);
    });

    if (!validDays.length) {
      alert("没有可用的全市10-14典型日数据");
      return;
    }

    const sortedVals = validDays
      .map((d) => Number(d.nrmse_pct))
      .sort((a, b) => a - b);

    const median = sortedVals[Math.floor(sortedVals.length / 2)];

    const closest = validDays
      .slice()
      .sort((a, b) => {
        return Math.abs(Number(a.nrmse_pct) - median) - Math.abs(Number(b.nrmse_pct) - median);
      })[0];

    state.scope = "city";
    state.startDate = closest.date;
    state.endDate = closest.date;
    state.startHour = 10;
    state.endHour = 14;

    const cityRadio = document.querySelector('input[name="scope"][value="city"]');
    if (cityRadio) cityRadio.checked = true;

    setDateComboValue("start", state.startDate);
    setDateComboValue("end", state.endDate);
    syncHiddenDateInputs();

    const startHourInput = document.getElementById("start-hour");
    const endHourInput = document.getElementById("end-hour");
    if (startHourInput) startHourInput.value = 10;
    if (endHourInput) endHourInput.value = 14;

    if (typeof onScopeChange === "function") {
      onScopeChange();
    }

    validateDateRange(false);
    refreshAll();
  });
}
```

## 七、按钮样式建议

保持按钮高度和现有控件一致，不要过高。

```css
.btn {
  height: 34px;
  min-width: 96px;
  padding: 0 14px;
  border-radius: 7px;
  border: 1px solid #cbd5e1;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
}

.btn-purple {
  background: #f5f3ff;
  border-color: #c4b5fd;
  color: #6d28d9;
}

.btn-purple:hover {
  background: #ede9fe;
  border-color: #8b5cf6;
}

.btn-indigo {
  background: #eef2ff;
  border-color: #a5b4fc;
  color: #4338ca;
}

.btn-indigo:hover {
  background: #e0e7ff;
  border-color: #6366f1;
}
```

## 八、说明文案

在按钮附近或图表下方补充一句说明：

```html
<div class="hint-text">
  “当前日期10-14”只筛选当前日期范围内的全市10-14点数据；“典型日10-14”会自动选择一个10-14点表现接近中位数的代表日期。
</div>
```

CSS：

```css
.hint-text {
  margin-top: 6px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}
```

## 九、必须删除或替换的旧逻辑

请全局搜索：

```text
btn-midday
连云港全市10-14
state.endDate = state.startDate
state.startDate = state.endDate
setDateComboValue("end", state.startDate)
setDateComboValue("start", state.endDate)
```

要求：

- 删除旧的 `btn-midday` 绑定。
- 删除日期互相覆盖逻辑。
- 不允许在普通日期选择时自动改另一个日期。
- 只有“典型日10-14”按钮可以主动同时修改开始日期和结束日期。

## 十、验证步骤

启动页面：

```bash
cd /path/to/photovoltaic_forecasting_pj
python -m http.server 8060
```

浏览器打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

逐项验证：

1. 先选开始日期为 `2025-01-12`，再修改结束日期，开始日期必须保持 `2025-01-12`。
2. 先选结束日期为 `2025-02-20`，再修改开始日期，结束日期必须保持 `2025-02-20`。
3. 设置开始日期晚于结束日期时，页面提示“开始日期不能晚于结束日期”，图表不刷新，另一个日期不被自动修改。
4. 点击“当前日期10-14”，日期范围不变，只切换为全市和 10-14 点。
5. 点击“典型日10-14”，日期范围可以被改为某个典型日，并且小时为 10-14。
6. 鼠标悬浮在两个 10-14 按钮上时，能看到不同说明。
7. 主折线图、指标卡、逐小时表、散点图都能正常显示。

## 十一、验收标准

本轮修改通过的标准：

- 日期选择不再互相覆盖。
- 非法日期只提示，不自动改值。
- “当前日期10-14”和“典型日10-14”逻辑分开。
- 用户能明确知道哪个按钮会改日期，哪个按钮不会改日期。
- 页面可以正常打开，图表可以正常显示。
- 不修改训练结果，不重新训练模型，不改动预测 pkl/csv/json 数据。

