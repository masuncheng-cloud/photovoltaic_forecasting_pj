# Cursor 修复方案 Round20：四季按钮尺寸与普通按钮保持一致

## 0. 问题

当前页面中四季按钮：

```text
春季 / 夏季 / 秋季 / 冬季
```

显示得明显比其他按钮小，像小标签，不像按钮。

本轮目标：

```text
四季按钮与其他按钮保持一致的高度、内边距、字号、圆角、阴影和 hover 效果。
```

可以保留四季不同颜色，但尺寸必须和：

```text
预测最好 / 预测最差 / 相对正确 / 样本少 / 刷新
```

一致。

---

## 1. 修改文件

只修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

不修改任何数据文件。

---

## 2. HTML class 确认

确认四季按钮 HTML 是：

```html
<button class="btn btn-season spring" id="btn-spring" disabled>春季</button>
<button class="btn btn-season summer" id="btn-summer" disabled>夏季</button>
<button class="btn btn-season autumn" id="btn-autumn" disabled>秋季</button>
<button class="btn btn-season winter" id="btn-winter" disabled>冬季</button>
```

或者：

```html
<button class="btn-seas btn-season spring" id="btn-spring" disabled>春季</button>
...
```

推荐统一改成：

```html
<button class="btn btn-season spring" id="btn-spring" disabled>春季</button>
<button class="btn btn-season summer" id="btn-summer" disabled>夏季</button>
<button class="btn btn-season autumn" id="btn-autumn" disabled>秋季</button>
<button class="btn btn-season winter" id="btn-winter" disabled>冬季</button>
```

这样四季按钮直接继承 `.btn` 的尺寸。

---

## 3. 删除导致四季按钮变小的旧样式

在 CSS 中查找并删除或覆盖以下可能的规则：

```css
.btn-seas {
  height: auto;
  padding: 2px 4px;
  font-size: 12px;
}
```

```css
.btn-season {
  padding: 0 4px;
  height: 20px;
}
```

```css
.btn-seas::before { ... }
```

如果不确定是否能删除，就在 CSS 最后追加强覆盖。

---

## 4. 在 CSS 最后追加强制统一样式

请在 `<style>` 末尾、`</style>` 前追加：

```css
/* Round20 fix: season buttons should look like normal buttons */
.btn-season,
.btn-seas.btn-season,
button.btn-season {
  height: 32px !important;
  min-height: 32px !important;
  line-height: 30px !important;
  padding: 0 12px !important;
  border-radius: 6px !important;
  font-size: 13px !important;
  font-weight: 600 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.10) !important;
  cursor: pointer;
}

.btn-season:hover:not(:disabled),
.btn-seas.btn-season:hover:not(:disabled),
button.btn-season:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 3px 8px rgba(15, 23, 42, 0.16) !important;
}

.btn-season:active:not(:disabled),
.btn-seas.btn-season:active:not(:disabled),
button.btn-season:active:not(:disabled) {
  transform: translateY(0);
}

.btn-season:disabled,
.btn-seas.btn-season:disabled,
button.btn-season:disabled {
  background: #e2e8f0 !important;
  border-color: #cbd5e1 !important;
  color: #94a3b8 !important;
  cursor: not-allowed !important;
  box-shadow: none !important;
}
```

---

## 5. 保留四季颜色，但按按钮尺寸显示

在上面强制尺寸后，继续保留/追加四季颜色：

```css
.btn-season.spring:not(:disabled) {
  background: #ecfdf5 !important;
  border: 1px solid #86efac !important;
  color: #15803d !important;
}

.btn-season.spring:hover:not(:disabled) {
  background: #d1fae5 !important;
}

.btn-season.summer:not(:disabled) {
  background: #fff7ed !important;
  border: 1px solid #fdba74 !important;
  color: #c2410c !important;
}

.btn-season.summer:hover:not(:disabled) {
  background: #ffedd5 !important;
}

.btn-season.autumn:not(:disabled) {
  background: #fefce8 !important;
  border: 1px solid #fde68a !important;
  color: #a16207 !important;
}

.btn-season.autumn:hover:not(:disabled) {
  background: #fef3c7 !important;
}

.btn-season.winter:not(:disabled) {
  background: #ecfeff !important;
  border: 1px solid #67e8f9 !important;
  color: #0e7490 !important;
}

.btn-season.winter:hover:not(:disabled) {
  background: #cffafe !important;
}
```

---

## 6. 控制区间距

四季按钮变大后，如果间距太挤，可以设置：

```css
#season-group,
.season-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
```

如果 HTML 里没有 `season-group`，可以给四季所在 ctrl-group 加：

```html
<div class="ctrl-group season-group">
```

---

## 7. 验收

打开页面后检查：

1. 春季/夏季/秋季/冬季按钮高度和“刷新”按钮一致。
2. 字号和“刷新”按钮一致。
3. 圆角和其他按钮一致。
4. hover 时有轻微阴影/背景变化。
5. 四季按钮仍保留不同颜色。
6. 不再像小标签。

---

## 8. 自动检查

```bash
python - <<'PY'
from pathlib import Path

p = Path("stages/05_visualization/interactive_forecast_dashboard.html")
text = p.read_text(encoding="utf-8")

required = [
    "btn-season",
    "height: 32px !important",
    "spring:not(:disabled)",
    "summer:not(:disabled)",
    "autumn:not(:disabled)",
    "winter:not(:disabled)",
]

missing = [x for x in required if x not in text]
assert not missing, "缺少四季按钮统一样式: " + ", ".join(missing)

print("[OK] season button style fix exists")
PY
```

