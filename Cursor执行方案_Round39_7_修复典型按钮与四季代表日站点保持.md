# Round39.7：修复典型站点按钮与四季代表日站点保持

## 一、当前问题

现在单站点功率曲线已经修好，但页面交互还有两个问题：

1. 点击“样本少”按钮没有反应。
2. 点击“春季 / 夏季 / 秋季 / 冬季”代表日按钮时，“选择站点”这一项不应消失；如果当前是单站点模式，应该继续展示当前站点，并用该站点画对应季节代表日的曲线。

本轮只修复前端交互逻辑，不重新训练，不修改模型结果。

---

## 二、只修改文件

优先只修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

如果项目已拆分 JS/CSS，则同步修改实际文件：

```text
stages/05_visualization/*.js
stages/05_visualization/*.css
```

不修改：

```text
output/pv_pipeline/tables/*.pkl
output/pv_pipeline/interactive_dashboard/*.json
output/pv_pipeline/metrics/*.csv
```

---

## 三、修复“样本少”按钮没有反应

### 3.1 先检查 typical_sites.json 中样本少字段

执行：

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path("output/pv_pipeline/interactive_dashboard/typical_sites.json")
data = json.load(open(p, encoding="utf-8"))
print(type(data))
print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])
PY
```

重点看里面“样本少”可能对应哪些写法，例如：

```text
small
sample_small
low_sample
少样本
样本少
数据少
```

### 3.2 扩展 `normalizeTypicalSites`

找到前端函数：

```javascript
function normalizeTypicalSites(raw) { ... }
```

将类别识别扩展为下面这种兜底写法。

```javascript
function normalizeTypicalSites(raw) {
  const result = {
    best: [],
    worst: [],
    normal: [],
    small: [],
  };

  const pushUnique = (key, sid) => {
    if (!sid) return;
    sid = String(sid).trim();
    if (!sid) return;
    if (!result[key].includes(sid)) result[key].push(sid);
  };

  if (!raw) return result;

  if (!Array.isArray(raw) && typeof raw === "object") {
    const pickArray = (...keys) => {
      for (const k of keys) {
        if (Array.isArray(raw[k])) return raw[k];
      }
      return [];
    };

    for (const x of pickArray("best", "预测最好", "typical_best_site_ids", "best_site_ids")) {
      pushUnique("best", typeof x === "string" ? x : x.site_id);
    }
    for (const x of pickArray("worst", "预测最差", "typical_worst_site_ids", "worst_site_ids")) {
      pushUnique("worst", typeof x === "string" ? x : x.site_id);
    }
    for (const x of pickArray("normal", "relative_correct", "相对正确", "typical_normal_site_ids", "correct_site_ids")) {
      pushUnique("normal", typeof x === "string" ? x : x.site_id);
    }
    for (const x of pickArray("small", "sample_small", "low_sample", "few_sample", "样本少", "少样本", "数据少", "typical_small_site_ids", "small_site_ids")) {
      pushUnique("small", typeof x === "string" ? x : x.site_id);
    }

    return result;
  }

  if (Array.isArray(raw)) {
    for (const item of raw) {
      const sid = item.site_id || item.station_id || item.id;
      const label = String(item.category || item.category_label || item.type || item.label || "");
      const labelLower = label.toLowerCase();

      if (!sid) continue;

      if (label.includes("最好") || labelLower === "best") {
        pushUnique("best", sid);
      } else if (label.includes("最差") || labelLower === "worst") {
        pushUnique("worst", sid);
      } else if (label.includes("正确") || label.includes("相对") || labelLower === "normal" || labelLower.includes("correct")) {
        pushUnique("normal", sid);
      } else if (
        label.includes("样本少") ||
        label.includes("少样本") ||
        label.includes("数据少") ||
        labelLower.includes("small") ||
        labelLower.includes("low_sample") ||
        labelLower.includes("few_sample") ||
        labelLower.includes("sample_small")
      ) {
        pushUnique("small", sid);
      }
    }
  }

  return result;
}
```

### 3.3 给“样本少”增加 fallback

如果 `typical_sites.json` 里确实没有 `small`，不要让按钮没反应。增加一个兜底函数：

```javascript
function getFallbackSmallSampleSites() {
  const rows = Array.isArray(gSiteMetrics) ? gSiteMetrics : [];
  return rows
    .filter(r => {
      const sid = r.site_id || r.station_id || r.id;
      const rowsCount = Number(r.full_rows ?? r.rows ?? r.sample_count ?? 0);
      const posRows = Number(r.full_positive_rows ?? r.positive_rows ?? r.positive_count ?? 0);
      return sid && rowsCount > 0 && posRows > 0;
    })
    .sort((a, b) => {
      const ar = Number(a.full_rows ?? a.rows ?? a.sample_count ?? 0);
      const br = Number(b.full_rows ?? b.rows ?? b.sample_count ?? 0);
      return ar - br;
    })
    .slice(0, 5)
    .map(r => r.site_id || r.station_id || r.id);
}
```

修改 `pickTypicalSite`：

```javascript
function pickTypicalSite(category) {
  let list = gTypicalSites?.[category] || [];

  if ((!list || list.length === 0) && category === "small") {
    list = getFallbackSmallSampleSites();
    console.warn("[pickTypicalSite] small category missing, fallback to site_metrics", list);
  }

  if (!list || list.length === 0) {
    console.warn("[pickTypicalSite] empty category", category, gTypicalSites);
    return null;
  }

  return list[0];
}
```

---

## 四、修复典型站点按钮点击后下拉框显示

找到 `selectTypicalSite(category)`，替换为：

```javascript
async function selectTypicalSite(category) {
  const sid = pickTypicalSite(category);
  if (!sid) return;

  state.scope = "site";
  state.siteId = sid;

  const siteRadio = document.querySelector('input[name="scope"][value="site"]');
  if (siteRadio) siteRadio.checked = true;

  const cityRadio = document.querySelector('input[name="scope"][value="city"]');
  if (cityRadio) cityRadio.checked = false;

  const siteSelectWrap =
    document.getElementById("site-select-wrap") ||
    document.getElementById("siteSelectWrap") ||
    document.querySelector(".site-select-wrap");

  if (siteSelectWrap) siteSelectWrap.style.display = "";

  const siteSelect = document.getElementById("site-select") || document.getElementById("siteSelect");
  if (siteSelect) {
    const hasOption = Array.from(siteSelect.options).some(opt => opt.value === sid);
    if (hasOption) {
      siteSelect.value = sid;
    } else {
      console.warn("[selectTypicalSite] site option not found", sid);
    }
  }

  await ensureSiteRows(sid);
  await refreshAll();
}
```

重点：

```text
点击预测最好 / 预测最差 / 相对正确 / 样本少后：
展示对象必须变为单站点；
选择站点下拉框必须显示；
下拉框的值必须等于按钮对应的站点。
```

---

## 五、修复四季代表日按钮

### 5.1 正确逻辑

点击：

```text
春季 / 夏季 / 秋季 / 冬季
```

只应该修改日期范围。

不应该：

```javascript
state.scope = "city";
```

不应该：

```javascript
hide site select
```

如果当前是单站点模式：

```text
继续保持当前站点；
选择站点下拉框继续显示；
曲线展示该站点在对应季节代表日的数据。
```

如果当前是全市模式：

```text
继续保持全市；
选择站点下拉框可以隐藏或禁用，按原页面规则即可。
```

### 5.2 增加保持站点选择的函数

```javascript
function preserveSiteSelectionIfNeeded() {
  const isSite = state.scope === "site";
  const siteSelect =
    document.getElementById("site-select") ||
    document.getElementById("siteSelect");

  if (isSite && siteSelect) {
    if (!state.siteId && siteSelect.value) {
      state.siteId = siteSelect.value;
    }
    if (state.siteId) {
      siteSelect.value = state.siteId;
    }
  }

  const siteSelectWrap =
    document.getElementById("site-select-wrap") ||
    document.getElementById("siteSelectWrap") ||
    document.querySelector(".site-select-wrap");

  if (siteSelectWrap) {
    siteSelectWrap.style.display = isSite ? "" : "none";
  }
}
```

如果页面原来在全市模式也想显示站点下拉框，可以把最后一行改成：

```javascript
siteSelectWrap.style.display = "";
```

但本轮关键是：

```text
单站点模式不能消失。
```

### 5.3 替换四季按钮事件

找到四季按钮绑定逻辑，例如：

```javascript
btnSpring.addEventListener(...)
btnSummer.addEventListener(...)
btnAutumn.addEventListener(...)
btnWinter.addEventListener(...)
```

统一改为：

```javascript
async function selectSeasonDay(seasonKey) {
  syncStateFromControls();

  const currentScope = state.scope;
  const currentSiteId = state.siteId;

  const date = pickSeasonDate(seasonKey);
  if (!date) {
    console.warn("[selectSeasonDay] no date for season", seasonKey);
    return;
  }

  state.startDate = date;
  state.endDate = date;
  setDateComboValue("start", date);
  setDateComboValue("end", date);

  // 保持点击前的展示对象与站点
  state.scope = currentScope;
  state.siteId = currentSiteId;

  const siteRadio = document.querySelector('input[name="scope"][value="site"]');
  const cityRadio = document.querySelector('input[name="scope"][value="city"]');
  if (state.scope === "site") {
    if (siteRadio) siteRadio.checked = true;
    if (cityRadio) cityRadio.checked = false;
    preserveSiteSelectionIfNeeded();
    if (state.siteId) await ensureSiteRows(state.siteId);
  } else {
    if (cityRadio) cityRadio.checked = true;
    if (siteRadio) siteRadio.checked = false;
  }

  await refreshAll();
}
```

绑定：

```javascript
document.getElementById("btn-season-spring")?.addEventListener("click", () => {
  selectSeasonDay("spring").catch(console.error);
});

document.getElementById("btn-season-summer")?.addEventListener("click", () => {
  selectSeasonDay("summer").catch(console.error);
});

document.getElementById("btn-season-autumn")?.addEventListener("click", () => {
  selectSeasonDay("autumn").catch(console.error);
});

document.getElementById("btn-season-winter")?.addEventListener("click", () => {
  selectSeasonDay("winter").catch(console.error);
});
```

如果实际按钮 ID 不是这些，按实际 ID 替换。

### 5.4 如果没有 `pickSeasonDate`

如果页面已有 `gSeasonDays`，可以这样写：

```javascript
function pickSeasonDate(seasonKey) {
  const data = gSeasonDays || {};
  const item = data[seasonKey] || data[seasonKey + "_date"];

  if (typeof item === "string") return item;
  if (item && typeof item === "object") {
    return item.date || item.day || item.representative_date || null;
  }

  return null;
}
```

如果 `season_days.json` 是数组：

```javascript
function pickSeasonDate(seasonKey) {
  const data = gSeasonDays || {};

  if (Array.isArray(data)) {
    const row = data.find(x => {
      const s = String(x.season || x.season_key || x.name || "").toLowerCase();
      return s === seasonKey || s.includes(seasonKey);
    });
    return row ? (row.date || row.day || row.representative_date) : null;
  }

  const item = data[seasonKey] || data[seasonKey + "_date"];
  if (typeof item === "string") return item;
  if (item && typeof item === "object") {
    return item.date || item.day || item.representative_date || null;
  }

  return null;
}
```

---

## 六、修复 `onScopeChange`

找到 `onScopeChange()`，确保它只在展示对象切换时控制站点下拉框。

建议改为：

```javascript
async function onScopeChange() {
  syncStateFromControls();

  const siteSelectWrap =
    document.getElementById("site-select-wrap") ||
    document.getElementById("siteSelectWrap") ||
    document.querySelector(".site-select-wrap");

  if (state.scope === "site") {
    if (siteSelectWrap) siteSelectWrap.style.display = "";

    const siteSelect = document.getElementById("site-select") || document.getElementById("siteSelect");
    if (!state.siteId && siteSelect && siteSelect.value) {
      state.siteId = siteSelect.value;
    }
    if (siteSelect && state.siteId) {
      siteSelect.value = state.siteId;
    }
    if (state.siteId) await ensureSiteRows(state.siteId);
  } else {
    if (siteSelectWrap) siteSelectWrap.style.display = "none";
  }

  await refreshAll();
}
```

注意：

```text
selectSeasonDay 不应调用会强制隐藏站点选择的逻辑，除非当前 scope 是 city。
```

---

## 七、增加调试日志

在典型按钮和四季按钮里加日志：

```javascript
console.info("[selectTypicalSite]", { category, sid, scope: state.scope });
console.info("[selectSeasonDay]", { seasonKey, date, scope: state.scope, siteId: state.siteId });
```

这样可以确认：

```text
点击样本少时 sid 不是 null；
点击四季按钮后 scope 仍为 site；
点击四季按钮后 siteId 没有丢。
```

---

## 八、静态检查

执行：

```bash
python - <<'PY'
from pathlib import Path

p = Path("stages/05_visualization/interactive_forecast_dashboard.html")
text = p.read_text(encoding="utf-8")

required = [
    "getFallbackSmallSampleSites",
    "selectTypicalSite",
    "preserveSiteSelectionIfNeeded",
    "selectSeasonDay",
    "pickSeasonDate",
]
missing = [x for x in required if x not in text]
assert not missing, "缺少关键函数: " + ", ".join(missing)

print("[OK] Round39.7 static function check passed")
PY

python - <<'PY'
from pathlib import Path
import re
p = Path("stages/05_visualization/interactive_forecast_dashboard.html")
text = p.read_text(encoding="utf-8")
scripts = re.findall(r"<script[^>]*>(.*?)</script>", text, flags=re.S | re.I)
Path("/tmp/interactive_dashboard_script.js").write_text("\\n".join(scripts), encoding="utf-8")
print("[OK] extracted JS")
PY

node --check /tmp/interactive_dashboard_script.js
```

---

## 九、页面验收

启动服务：

```bash
python -m http.server 8070
```

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round39_7
```

强制刷新：

```text
Ctrl + Shift + R
```

验收 1：样本少按钮

```text
点击“样本少”
展示对象变为“单站点”
选择站点下拉框显示
下拉框中显示样本少对应站点
曲线正常显示
控制台出现 [selectTypicalSite] category=small sid=...
```

验收 2：典型站点按钮

逐个点击：

```text
预测最好
预测最差
相对正确
样本少
```

每次都必须：

```text
选择站点下拉框显示；
下拉框站点与按钮对应站点一致；
曲线正常刷新。
```

验收 3：四季代表日

先点击：

```text
单站点
选择 S062 或任意站点
```

再点击：

```text
春季 / 夏季 / 秋季 / 冬季
```

必须满足：

```text
展示对象仍为单站点；
选择站点下拉框不消失；
下拉框仍显示原来的站点；
日期变为对应季节代表日；
曲线刷新为该站点该日期的数据。
```

验收 4：全市模式

切回：

```text
全市
```

点击四季代表日，仍应显示全市曲线，不影响全市功能。

---

## 十、如果样本少仍无反应，回传这些输出

```bash
python - <<'PY'
import json
from pathlib import Path
root = Path("output/pv_pipeline/interactive_dashboard")

for name in ["typical_sites.json", "site_metrics.json"]:
    print("\\n==", name)
    data = json.load(open(root / name, encoding="utf-8"))
    print(json.dumps(data, ensure_ascii=False, indent=2)[:5000])
PY
```

同时回传浏览器控制台：

```text
[typicalSites]
[pickTypicalSite]
[selectTypicalSite]
```

---

## 十一、如果四季按钮后站点仍消失，回传这些输出

浏览器控制台执行：

```javascript
console.log("scope", state.scope);
console.log("siteId", state.siteId);
console.log("siteSelect", document.getElementById("site-select")?.value || document.getElementById("siteSelect")?.value);
console.log("siteWrap", document.getElementById("site-select-wrap")?.style.display || document.getElementById("siteSelectWrap")?.style.display);
```

并回传：

```text
[selectSeasonDay]
[refreshAll]
```

