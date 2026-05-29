# Round39.10：典型站点按钮强制显示“选择站点”下拉框

## 一、当前问题

当前页面中，当“展示对象”原本是：

```text
全市
```

此时点击：

```text
预测最好 / 预测最差 / 相对正确 / 样本少
```

页面曲线已经切到了对应单站点，例如：

```text
站点 S062 功率曲线
```

但顶部“选择站点”下拉框没有显示。

这说明典型站点按钮已经把数据切成单站点了，但 UI 控件状态没有完全同步：

```text
state.scope / radio / siteSelect / siteSelectWrap 没有同时更新
```

本轮只修前端交互，不重新训练，不修改导出数据。

---

## 二、只修改文件

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

如果 JS/CSS 已拆分，也同步修改实际文件：

```text
stages/05_visualization/*.js
stages/05_visualization/*.css
```

---

## 三、核心修复原则

任何按钮只要会切换到某个单站点，都必须调用同一个函数：

```text
setSelectedSiteInUI(siteId)
```

这个函数必须同时做 5 件事：

```text
1. state.scope = "site"
2. state.siteId = siteId
3. 勾选“单站点”radio
4. 取消“全市”radio
5. 显示“选择站点”下拉框，并把下拉框值设为 siteId
```

---

## 四、替换或新增 `setSelectedSiteInUI`

在前端 JS 中找到：

```javascript
function setSelectedSiteInUI(siteId) { ... }
```

如果没有，就新增；如果已有，整体替换为：

```javascript
function setSelectedSiteInUI(siteId) {
  if (!siteId) {
    console.warn("[setSelectedSiteInUI] empty siteId");
    return;
  }

  siteId = String(siteId).trim();

  state.scope = "site";
  state.siteId = siteId;

  // 1. 同步 radio
  const siteRadio =
    document.querySelector('input[name="scope"][value="site"]') ||
    document.querySelector('input[name="display-scope"][value="site"]');
  const cityRadio =
    document.querySelector('input[name="scope"][value="city"]') ||
    document.querySelector('input[name="display-scope"][value="city"]');

  if (siteRadio) siteRadio.checked = true;
  if (cityRadio) cityRadio.checked = false;

  // 2. 找到站点下拉框
  const siteSelect =
    document.getElementById("site-select") ||
    document.getElementById("siteSelect") ||
    document.querySelector('select[name="site_id"]') ||
    document.querySelector('select[name="siteId"]');

  // 3. 显示站点下拉框所在容器
  const siteSelectWrap =
    document.getElementById("site-select-wrap") ||
    document.getElementById("siteSelectWrap") ||
    document.querySelector(".site-select-wrap") ||
    document.querySelector(".station-select-wrap") ||
    siteSelect?.closest(".control-group") ||
    siteSelect?.parentElement;

  if (siteSelectWrap) {
    siteSelectWrap.style.display = "";
    siteSelectWrap.hidden = false;
    siteSelectWrap.classList.remove("hidden", "is-hidden", "d-none");
  }

  // 4. 同步下拉框值
  if (siteSelect) {
    const options = Array.from(siteSelect.options || []);
    const hasOption = options.some(opt => opt.value === siteId);
    if (hasOption) {
      siteSelect.value = siteId;
    } else {
      console.warn("[setSelectedSiteInUI] site option not found:", siteId, options.slice(0, 5).map(o => o.value));
    }

    siteSelect.disabled = false;
    siteSelect.style.display = "";
    siteSelect.hidden = false;
  } else {
    console.warn("[setSelectedSiteInUI] site select element not found");
  }

  console.info("[setSelectedSiteInUI]", {
    siteId,
    scope: state.scope,
    selectValue: siteSelect?.value,
    wrapDisplay: siteSelectWrap?.style?.display,
    wrapHidden: siteSelectWrap?.hidden,
  });
}
```

---

## 五、修复典型站点按钮逻辑

找到：

```javascript
async function selectTypicalSite(category) { ... }
```

整体替换为：

```javascript
async function selectTypicalSite(category) {
  const sid = pickTypicalSite(category);
  if (!sid) {
    console.warn("[selectTypicalSite] no site for category", category, gTypicalSites);
    return;
  }

  setSelectedSiteInUI(sid);

  await ensureSiteRows(sid);
  await refreshAll();

  console.info("[selectTypicalSite]", {
    category,
    sid,
    scope: state.scope,
    siteId: state.siteId,
  });
}
```

关键点：

```text
不要在 selectTypicalSite 内部只改 state.siteId；
必须调用 setSelectedSiteInUI(sid)。
```

---

## 六、修复按钮绑定

确认按钮事件绑定如下。

如果页面 ID 不同，按实际 ID 替换，但必须调用 `selectTypicalSite(...)`：

```javascript
document.getElementById("btn-best")?.addEventListener("click", () => {
  selectTypicalSite("best").catch(console.error);
});

document.getElementById("btn-worst")?.addEventListener("click", () => {
  selectTypicalSite("worst").catch(console.error);
});

document.getElementById("btn-normal")?.addEventListener("click", () => {
  selectTypicalSite("normal").catch(console.error);
});

document.getElementById("btn-small")?.addEventListener("click", () => {
  selectTypicalSite("small").catch(console.error);
});
```

如果当前按钮是通过 `data-category` 绑定，也可以：

```javascript
document.querySelectorAll("[data-typical-category]").forEach(btn => {
  btn.addEventListener("click", () => {
    selectTypicalSite(btn.dataset.typicalCategory).catch(console.error);
  });
});
```

---

## 七、修复 `onScopeChange` 不要覆盖刚刚显示的站点下拉框

如果 `selectTypicalSite` 内部或 `refreshAll` 之前会调用 `onScopeChange()`，确保 `onScopeChange()` 不会把站点框又隐藏。

建议 `onScopeChange()` 中只根据当前 radio 控件切换，而不要在典型按钮之后反向判断。

替换为：

```javascript
async function onScopeChange() {
  syncStateFromControls();

  const siteSelect =
    document.getElementById("site-select") ||
    document.getElementById("siteSelect") ||
    document.querySelector('select[name="site_id"]') ||
    document.querySelector('select[name="siteId"]');

  const siteSelectWrap =
    document.getElementById("site-select-wrap") ||
    document.getElementById("siteSelectWrap") ||
    document.querySelector(".site-select-wrap") ||
    document.querySelector(".station-select-wrap") ||
    siteSelect?.closest(".control-group") ||
    siteSelect?.parentElement;

  if (state.scope === "site") {
    if (!state.siteId && siteSelect && siteSelect.value) {
      state.siteId = siteSelect.value;
    }
    if (state.siteId) {
      setSelectedSiteInUI(state.siteId);
      await ensureSiteRows(state.siteId);
    } else if (siteSelectWrap) {
      siteSelectWrap.style.display = "";
      siteSelectWrap.hidden = false;
    }
  } else {
    // 全市模式正常隐藏或保持原样均可。
    // 如果项目希望全市模式隐藏站点选择，就保留隐藏。
    if (siteSelectWrap) {
      siteSelectWrap.style.display = "none";
    }
  }

  await refreshAll();
}
```

重点：

```text
state.scope === "site" 时，siteSelectWrap 绝不能隐藏。
```

---

## 八、如果 CSS 强制隐藏，也要修

搜索：

```bash
grep -n "site-select\\|siteSelect\\|station-select\\|hidden\\|d-none\\|display: none" \
  stages/05_visualization/interactive_forecast_dashboard.html | head -200
```

如果发现类似：

```css
.site-mode-only { display: none; }
.hidden { display: none; }
```

不要删除全局规则，但 `setSelectedSiteInUI` 里必须移除这些隐藏类：

```javascript
siteSelectWrap.classList.remove("hidden", "is-hidden", "d-none");
```

如果站点下拉框有 `disabled`，也要：

```javascript
siteSelect.disabled = false;
```

---

## 九、静态检查

执行：

```bash
python - <<'PY'
from pathlib import Path
import re

p = Path("stages/05_visualization/interactive_forecast_dashboard.html")
text = p.read_text(encoding="utf-8")

required = [
    "setSelectedSiteInUI",
    "selectTypicalSite",
    "setSelectedSiteInUI(sid)",
    "siteSelectWrap.classList.remove",
]

missing = [x for x in required if x not in text]
assert not missing, "缺少关键逻辑: " + ", ".join(missing)

scripts = re.findall(r"<script[^>]*>(.*?)</script>", text, flags=re.S | re.I)
Path("/tmp/interactive_dashboard_script.js").write_text("\\n".join(scripts), encoding="utf-8")
print("[OK] static text check passed")
PY

node --check /tmp/interactive_dashboard_script.js
```

---

## 十、页面验收

启动服务：

```bash
python -m http.server 8070
```

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round39_10
```

强制刷新：

```text
Ctrl + Shift + R
```

### 验收 1：从全市切典型站点

先选择：

```text
展示对象：全市
```

然后点击：

```text
预测最好
```

必须看到：

```text
展示对象变为：单站点
选择站点下拉框显示
选择站点下拉框显示对应站点，例如 S062 韩华大浦光伏电站
曲线标题为：站点 S062 功率曲线
```

### 验收 2：四个典型按钮都检查

依次点击：

```text
预测最好
预测最差
相对正确
样本少
```

每次必须：

```text
显示选择站点下拉框
下拉框站点与曲线标题一致
指标卡样本数不为 0
曲线正常显示
```

### 验收 3：控制台日志

控制台应出现：

```text
[setSelectedSiteInUI] { siteId: "...", scope: "site", selectValue: "...", ... }
[selectTypicalSite] { category: "...", sid: "...", scope: "site", siteId: "..." }
```

其中：

```text
selectValue 必须等于 siteId
scope 必须等于 site
```

---

## 十一、如果仍不显示，回传这些控制台输出

在点击“预测最好”后，在浏览器控制台执行：

```javascript
console.log("state", state);
console.log("siteRadio", document.querySelector('input[name="scope"][value="site"]')?.checked);
console.log("cityRadio", document.querySelector('input[name="scope"][value="city"]')?.checked);
console.log("siteSelect", document.getElementById("site-select") || document.getElementById("siteSelect") || document.querySelector('select[name="site_id"]') || document.querySelector('select[name="siteId"]'));
console.log("siteSelectValue", (document.getElementById("site-select") || document.getElementById("siteSelect") || document.querySelector('select[name="site_id"]') || document.querySelector('select[name="siteId"]'))?.value);
console.log("siteSelectParent", (document.getElementById("site-select") || document.getElementById("siteSelect") || document.querySelector('select[name="site_id"]') || document.querySelector('select[name="siteId"]'))?.parentElement);
console.log("siteSelectParentStyle", (document.getElementById("site-select") || document.getElementById("siteSelect") || document.querySelector('select[name="site_id"]') || document.querySelector('select[name="siteId"]'))?.parentElement?.getAttribute("style"));
```

并回传：

```text
[setSelectedSiteInUI]
[selectTypicalSite]
```

日志。

