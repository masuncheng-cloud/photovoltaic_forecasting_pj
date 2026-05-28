# Cursor 修改方案 Round27：小时改为下拉框、修正缩放按钮文字对齐、隐藏校验提示行

## 一、修改目标

当前可视化页面有三个前端展示问题：

1. 小时选择目前是数字输入框，用户体验不如日期选择一致，改为下拉框。
2. “重置缩放”按钮中文字偏下，需要垂直居中。
3. 页面中绿色提示：

```text
真实值校验通过：页面 actual_mw 与 final_full/power_mw 一致；最大差值 ...
```

这行内容不需要在页面展示。注意：只隐藏前端展示，不删除后端校验逻辑。

本轮只修改可视化前端，不重新训练，不修改预测数据。

## 二、涉及文件

主要修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

如果项目已经拆分 JS/CSS，则同步修改：

```text
stages/05_visualization/*.js
stages/05_visualization/*.css
```

## 三、小时选择改为下拉框

### 3.1 替换 HTML 控件

搜索当前小时输入框，通常类似：

```html
<input id="start-hour" type="number" min="0" max="23" value="6">
<input id="end-hour" type="number" min="0" max="23" value="19">
```

或：

```html
<input id="start-hour" type="number" ...>
<input id="end-hour" type="number" ...>
```

替换为：

```html
<select id="start-hour" class="hour-select" aria-label="开始小时"></select>
<span class="control-separator">至</span>
<select id="end-hour" class="hour-select" aria-label="结束小时"></select>
```

如果页面中已经有“至”文字，不要重复添加两个“至”。

### 3.2 初始化小时下拉框

在 JS 初始化区域新增：

```js
function initHourSelects() {
  const startHour = document.getElementById("start-hour");
  const endHour = document.getElementById("end-hour");
  if (!startHour || !endHour) return;

  const makeOptions = (selectedValue) => {
    const opts = [];
    for (let h = 0; h <= 23; h += 1) {
      const selected = h === Number(selectedValue) ? "selected" : "";
      opts.push(`<option value="${h}" ${selected}>${String(h).padStart(2, "0")}:00</option>`);
    }
    return opts.join("");
  };

  startHour.innerHTML = makeOptions(state.startHour ?? 6);
  endHour.innerHTML = makeOptions(state.endHour ?? 19);
}
```

在页面初始化时调用：

```js
initHourSelects();
```

调用顺序建议：

```text
初始化 state
初始化日期下拉框
初始化小时下拉框
加载数据
refreshAll()
```

### 3.3 小时变化事件

把原来的 `input` 事件改成 `change` 事件：

```js
function bindHourSelectEvents() {
  const startHour = document.getElementById("start-hour");
  const endHour = document.getElementById("end-hour");

  if (startHour) {
    startHour.addEventListener("change", () => {
      state.startHour = Number(startHour.value);
      validateHourRange();
      refreshAll();
    });
  }

  if (endHour) {
    endHour.addEventListener("change", () => {
      state.endHour = Number(endHour.value);
      validateHourRange();
      refreshAll();
    });
  }
}
```

初始化后调用：

```js
bindHourSelectEvents();
```

### 3.4 小时范围校验

新增：

```js
function validateHourRange() {
  const startHour = document.getElementById("start-hour");
  const endHour = document.getElementById("end-hour");

  let start = Number(state.startHour);
  let end = Number(state.endHour);

  if (!Number.isFinite(start)) start = 6;
  if (!Number.isFinite(end)) end = 19;

  // 不自动互相覆盖；只在非法时提示并阻止 refreshAll 内部继续刷新。
  state.hourRangeValid = start <= end;

  let msg = document.getElementById("hour-range-message");
  if (!msg) {
    msg = document.createElement("span");
    msg.id = "hour-range-message";
    msg.className = "hour-error";
    if (endHour && endHour.parentElement) {
      endHour.parentElement.appendChild(msg);
    }
  }

  if (!state.hourRangeValid) {
    msg.textContent = "开始小时不能晚于结束小时";
    msg.style.display = "inline-flex";
  } else {
    msg.textContent = "";
    msg.style.display = "none";
  }

  return state.hourRangeValid;
}
```

在 `refreshAll()` 开头加：

```js
if (!validateHourRange()) {
  return;
}
```

注意：不要自动把开始小时或结束小时改成另一个值，避免和日期选择出现过的同类问题。

### 3.5 其他按钮同步下拉框

如果按钮会修改小时，例如：

```text
当前日期10-14
典型日10-14
刷新
四季代表日
```

在设置 state 后同步 select：

```js
function syncHourSelects() {
  const startHour = document.getElementById("start-hour");
  const endHour = document.getElementById("end-hour");
  if (startHour) startHour.value = String(state.startHour);
  if (endHour) endHour.value = String(state.endHour);
}
```

在 10-14 按钮逻辑中：

```js
state.startHour = 10;
state.endHour = 14;
syncHourSelects();
refreshAll();
```

## 四、小时下拉框样式

新增或调整 CSS：

```css
.hour-select {
  height: 34px;
  min-width: 86px;
  padding: 0 32px 0 12px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  background: #ffffff;
  color: #1f2937;
  font-size: 14px;
  font-weight: 700;
  line-height: 34px;
  outline: none;
  box-sizing: border-box;
}

.hour-select:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.16);
}

.hour-error {
  align-items: center;
  height: 34px;
  padding: 0 8px;
  border: 1px solid #fecaca;
  border-radius: 6px;
  background: #fef2f2;
  color: #b91c1c;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}
```

要求：

- 高度与日期下拉框、按钮一致。
- 不要出现数字输入框的上下箭头。
- 显示格式为 `06:00`、`07:00`、...、`19:00`。

## 五、修正“重置缩放”按钮文字偏下

搜索按钮文本：

```text
重置缩放
```

找到对应 class，例如：

```html
<button id="reset-zoom" class="zoom-reset-btn">重置缩放</button>
```

调整 CSS：

```css
.zoom-reset-btn,
#reset-zoom {
  height: 34px;
  min-width: 86px;
  padding: 0 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  vertical-align: middle;
  box-sizing: border-box;
}
```

如果按钮当前还有 `line-height: 34px`、`padding-top`、`padding-bottom`，删除或覆盖：

```css
#reset-zoom {
  padding-top: 0;
  padding-bottom: 0;
}
```

验收：

- “重置缩放”文字在按钮内垂直居中。
- 按钮高度和其他按钮协调。

## 六、去除“真实值校验通过...”页面展示

注意：不要删除后端校验函数，不要删除 `data_integrity_check.json` 生成。

只删除或隐藏前端展示。

### 6.1 删除 HTML 容器

搜索：

```html
<div id="data-integrity-note"
```

删除该元素，或加：

```html
<div id="data-integrity-note" style="display:none;"></div>
```

推荐直接删除页面显示元素。

### 6.2 修改 JS

搜索：

```js
renderDataIntegrityNote()
```

处理方式：

- 可以保留函数，但不要调用。
- 或者函数直接 return。

推荐：

```js
function renderDataIntegrityNote() {
  return;
}
```

并删除初始化中的调用：

```js
renderDataIntegrityNote();
```

如果 `loadAll()` 仍然加载 `data_integrity_check.json`，可以保留，这样不影响后台调试。

### 6.3 删除或保留 CSS

可以保留 `.data-integrity-note` CSS，不影响页面。

如要清理，也可删除：

```css
.data-integrity-note { ... }
.data-integrity-note.ok { ... }
.data-integrity-note.bad { ... }
```

## 七、确保 footer 仍保留口径说明

虽然去掉绿色校验提示，但页脚说明仍建议保留：

```text
当前折线图真实值 actual_mw 来自 distributed_predictions_final_full.pkl 的 power_mw；
正式测试集指标来自 distributed_predictions_final_eval.pkl。
```

如果页面显得太长，可以放到折叠说明或页脚。

## 八、验证步骤

启动：

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

## 九、验收标准

1. 小时选择控件是下拉框，不再是数字输入框。
2. 开始小时和结束小时可分别选择 `00:00` 至 `23:00`。
3. 选择小时后，折线图和指标卡会刷新。
4. 点击“当前日期10-14”后，小时下拉框显示 `10:00` 至 `14:00`。
5. 点击“典型日10-14”后，小时下拉框显示 `10:00` 至 `14:00`。
6. 如果开始小时晚于结束小时，页面提示“开始小时不能晚于结束小时”，且不自动修改另一个小时。
7. “重置缩放”按钮文字垂直居中。
8. 页面不再显示绿色的“真实值校验通过...”提示行。
9. 后端 `data_integrity_check.json` 和校验 CSV 仍正常生成，不删除校验能力。
10. 折线图、指标卡、逐小时表、散点图均正常显示。

