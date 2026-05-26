# Cursor 修改方案 Round20：控件高度压缩、按钮按功能分色、10-14 悬浮说明

## 0. 修改目标

当前可视化页面顶部控件存在：

1. 按钮和日期选择框竖向高度偏高。
2. 所有按钮都是同一种蓝色，功能层级不清晰。
3. `连云港全市10-14` 按钮缺少说明，用户不知道点击后会做什么。

本轮目标：

```text
压缩控件高度 + 按功能分类配色 + 给 10-14 按钮增加鼠标悬浮说明。
```

只修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

不修改任何数据文件、训练结果、JSON、CSV、PKL。

---

## 1. 控件整体高度压缩

将按钮、下拉框、小时输入框统一压缩到：

```text
32px 高
```

### 1.1 修改输入框/下拉框高度

找到 CSS 中类似：

```css
.select-control,
#site-select,
#start-hour,
#end-hour {
  height: 36px;
  ...
}
```

改为：

```css
.select-control,
#site-select,
#start-hour,
#end-hour {
  height: 32px;
  min-height: 32px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #ffffff;
  color: #1f2937;
  padding: 0 8px;
  font-size: 13px;
  font-weight: 500;
  line-height: 30px;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
```

### 1.2 压缩日期组合控件

找到：

```css
.date-combo { ... }
.date-year { ... }
.date-month, .date-day { ... }
```

改为：

```css
.date-combo {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 4px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  height: 38px;
}

.date-year {
  width: 76px;
}

.date-month,
.date-day {
  width: 56px;
}

.date-unit {
  font-size: 12px;
  color: #64748b;
  margin-right: 1px;
  line-height: 1;
}
```

说明：

```text
单个 select 高度 32px，外层 date-combo 高度 38px，视觉会比现在明显低。
```

### 1.3 压缩按钮高度

找到 `.btn, .btn-seas`：

```css
.btn,
.btn-seas {
  height: 36px;
  ...
}
```

改为：

```css
.btn,
.btn-seas {
  height: 32px;
  min-height: 32px;
  border-radius: 6px;
  padding: 0 12px;
  font-size: 13px;
  font-weight: 600;
  line-height: 30px;
  cursor: pointer;
  transition: transform 0.08s ease, box-shadow 0.15s ease, background 0.15s ease, border-color 0.15s ease;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.10);
}
```

---

## 2. 按钮按功能分类分色

不要所有按钮都用蓝色。

建议分为 4 类：

| 功能 | 按钮 | 颜色 |
|---|---|---|
| 典型站点 | 预测最好、预测最差、相对正确、样本少 | 蓝色系，但不同深浅或描边 |
| 专题分析 | 连云港全市10-14 | 紫色 |
| 四季代表日 | 春季、夏季、秋季、冬季 | 绿色/橙色/金色/青色 |
| 常规操作 | 刷新、重置缩放 | 灰蓝色 |

### 2.1 给按钮增加 class

修改 HTML：

```html
<button class="btn btn-site btn-best" id="btn-best">预测最好</button>
<button class="btn btn-site btn-worst" id="btn-worst">预测最差</button>
<button class="btn btn-site btn-normal" id="btn-normal">相对正确</button>
<button class="btn btn-site btn-low" id="btn-low">样本少</button>

<button class="btn btn-topic" id="btn-midday" ...>连云港全市10-14</button>

<button class="btn-seas btn-season spring" id="btn-spring" disabled>春季</button>
<button class="btn-seas btn-season summer" id="btn-summer" disabled>夏季</button>
<button class="btn-seas btn-season autumn" id="btn-autumn" disabled>秋季</button>
<button class="btn-seas btn-season winter" id="btn-winter" disabled>冬季</button>

<button class="btn btn-action" id="btn-refresh">刷新</button>
```

如果有：

```html
<button id="reset-line-zoom">
```

改为：

```html
<button class="btn btn-action btn-small" id="reset-line-zoom" type="button">重置缩放</button>
```

### 2.2 基础按钮样式

替换现有 `.btn, .btn-seas` 的背景色逻辑：

```css
.btn,
.btn-seas {
  height: 32px;
  min-height: 32px;
  border-radius: 6px;
  padding: 0 12px;
  font-size: 13px;
  font-weight: 600;
  line-height: 30px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: transform 0.08s ease, box-shadow 0.15s ease, background 0.15s ease, border-color 0.15s ease;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.10);
}

.btn:hover,
.btn-seas:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 3px 8px rgba(15, 23, 42, 0.16);
}

.btn:active,
.btn-seas:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.10);
}

.btn:disabled,
.btn-seas:disabled {
  background: #e2e8f0 !important;
  border-color: #cbd5e1 !important;
  color: #94a3b8 !important;
  cursor: not-allowed;
  box-shadow: none;
}
```

### 2.3 典型站点按钮颜色

```css
.btn-site {
  background: #edf5ff;
  border-color: #bfdbfe;
  color: #1d4ed8;
}

.btn-site:hover {
  background: #dbeafe;
  border-color: #93c5fd;
}

.btn-best {
  background: #ecfdf5;
  border-color: #a7f3d0;
  color: #047857;
}

.btn-best:hover {
  background: #d1fae5;
}

.btn-worst {
  background: #fef2f2;
  border-color: #fecaca;
  color: #b91c1c;
}

.btn-worst:hover {
  background: #fee2e2;
}

.btn-normal {
  background: #eff6ff;
  border-color: #bfdbfe;
  color: #1d4ed8;
}

.btn-normal:hover {
  background: #dbeafe;
}

.btn-low {
  background: #f8fafc;
  border-color: #cbd5e1;
  color: #475569;
}

.btn-low:hover {
  background: #f1f5f9;
}
```

### 2.4 10-14 专题按钮颜色

```css
.btn-topic {
  background: #f5f3ff;
  border-color: #c4b5fd;
  color: #6d28d9;
}

.btn-topic:hover {
  background: #ede9fe;
  border-color: #a78bfa;
}
```

### 2.5 四季按钮颜色

```css
.btn-season.spring {
  background: #ecfdf5;
  border-color: #86efac;
  color: #15803d;
}

.btn-season.summer {
  background: #fff7ed;
  border-color: #fdba74;
  color: #c2410c;
}

.btn-season.autumn {
  background: #fefce8;
  border-color: #fde68a;
  color: #a16207;
}

.btn-season.winter {
  background: #ecfeff;
  border-color: #67e8f9;
  color: #0e7490;
}
```

### 2.6 刷新/重置按钮颜色

```css
.btn-action,
#reset-line-zoom {
  background: #f8fafc;
  border-color: #cbd5e1;
  color: #334155;
}

.btn-action:hover,
#reset-line-zoom:hover {
  background: #f1f5f9;
  border-color: #94a3b8;
}

.btn-small {
  height: 28px;
  min-height: 28px;
  line-height: 26px;
  padding: 0 10px;
  font-size: 12px;
}
```

---

## 3. 给“连云港全市10-14”增加悬浮说明

### 3.1 简单方案：使用 title

给按钮增加：

```html
title="切换到全市视角，并聚焦典型日期的10-14点正午高出力时段，用于查看峰值时段真实功率与预测功率的贴合情况。"
```

例如：

```html
<button
  class="btn btn-topic"
  id="btn-midday"
  title="切换到全市视角，并聚焦典型日期的10-14点正午高出力时段，用于查看峰值时段真实功率与预测功率的贴合情况。"
>
  连云港全市10-14
</button>
```

### 3.2 更美观方案：自定义 tooltip

如果页面已有 `#tooltip`，可以复用。

给按钮增加：

```html
data-help="切换到全市视角，并聚焦典型日期的10-14点正午高出力时段，用于查看峰值时段真实功率与预测功率的贴合情况。"
```

JS 加：

```javascript
function bindHelpTooltips() {
  document.querySelectorAll("[data-help]").forEach(el => {
    el.addEventListener("mouseenter", e => {
      const tip = document.getElementById("tooltip");
      if (!tip) return;
      tip.innerHTML = `<div style="max-width:260px;line-height:1.6">${el.dataset.help}</div>`;
      tip.style.display = "block";
      moveTooltip(e);
    });
    el.addEventListener("mousemove", moveTooltip);
    el.addEventListener("mouseleave", hideTooltip);
  });
}
```

在初始化成功后调用：

```javascript
bindHelpTooltips();
```

如果不想改 JS，用 `title` 即可；推荐同时保留 `title`，自定义 tooltip 作为增强。

---

## 4. 控制区布局稍微压缩

把 `#controls` 的 padding / gap 调小：

```css
#controls {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 12px;
  align-items: center;
  background: #ffffff;
  border: 1px solid #d8e2ee;
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 14px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.ctrl-group {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}

.ctrl-label {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  line-height: 32px;
}

.divider {
  width: 1px;
  height: 24px;
  background: #e2e8f0;
}
```

---

## 5. 避免控件换行过高

如果顶部控件太长，可以让日期控件独占较宽区域但不拉高：

```css
.date-combo {
  flex-shrink: 0;
}

#typical-group,
#site-select-group {
  flex-shrink: 0;
}
```

如果屏幕宽度不够，允许换行，但每一行高度控制在 38px 左右。

---

## 6. 自动检查

执行：

```bash
python - <<'PY'
from pathlib import Path
import re

p = Path("stages/05_visualization/interactive_forecast_dashboard.html")
text = p.read_text(encoding="utf-8")

required = [
    "btn-site",
    "btn-best",
    "btn-worst",
    "btn-normal",
    "btn-low",
    "btn-topic",
    "btn-season",
    "btn-action",
    "data-help",
    "连云港全市10-14",
    "height: 32px",
]

missing = [x for x in required if x not in text]
assert not missing, "缺少样式或属性: " + ", ".join(missing)

scripts = re.findall(r"<script[^>]*>(.*?)</script>", text, flags=re.S | re.I)
Path("/tmp/interactive_dashboard_script.js").write_text("\\n".join(scripts), encoding="utf-8")
print("[OK] style/static check passed")
PY

node --check /tmp/interactive_dashboard_script.js
```

---

## 7. 页面人工验收

启动：

```bash
python -m http.server 8060
```

打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

检查：

1. 年/月/日选择框整体高度明显变低。
2. 按钮高度明显变低。
3. “预测最好”偏绿色。
4. “预测最差”偏红色。
5. “相对正确”偏蓝色。
6. “样本少”偏灰色。
7. “连云港全市10-14”偏紫色。
8. 春夏秋冬按钮有不同颜色。
9. “刷新”和“重置缩放”是灰蓝色操作按钮。
10. 鼠标悬浮到“连云港全市10-14”时，有简要解释。
11. 页面图表和筛选功能不受影响。

---

## 8. 提交说明建议

```text
Round20: compact controls and add functional button colors

- reduce height of date selectors, number inputs and buttons
- color buttons by function group
- add hover help for Lianyungang city 10-14 shortcut
- keep chart interactions and data unchanged
```

