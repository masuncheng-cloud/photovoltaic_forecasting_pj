# Round39.8：四季代表日按钮同步站点下拉框

## 一、当前问题

点击：

```text
春季 / 夏季 / 秋季 / 冬季
```

页面会切换日期并刷新曲线，但“选择站点”下拉框没有同步显示当前曲线对应的站点名，导致用户不知道当前展示的是哪个站点的数据。

本轮目标：

```text
点击四季代表日按钮时：
1. 日期切换为对应季节代表日；
2. 如果当前是单站点模式，选择站点框必须继续显示；
3. 选择站点框必须显示当前曲线对应的站点；
4. 如果四季代表日逻辑内部指定了代表站点，则下拉框同步为该代表站点；
5. 如果四季代表日只指定日期，没有指定站点，则保持点击前的站点，并在下拉框中显示该站点。
```

不重新训练，不修改预测结果。

---

## 二、只修改文件

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

如果项目拆分了 JS/CSS，也同步修改实际文件：

```text
stages/05_visualization/*.js
stages/05_visualization/*.css
```

---

## 三、先检查 season_days.json 的格式

执行：

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path("output/pv_pipeline/interactive_dashboard/season_days.json")
data = json.load(open(p, encoding="utf-8"))
print(type(data))
print(json.dumps(data, ensure_ascii=False, indent=2)[:5000])
PY
```

重点看每个季节代表日里是否包含站点字段，例如：

```text
site_id
station_id
id
site_name
station_name
date
representative_date
```

---

## 四、新增统一站点同步函数

在前端 JS 中加入：

```javascript
function setSelectedSiteInUI(siteId) {
  if (!siteId) return;

  state.scope = "site";
  state.siteId = siteId;

  const siteRadio = document.querySelector('input[name="scope"][value="site"]');
  const cityRadio = document.querySelector('input[name="scope"][value="city"]');
  if (siteRadio) siteRadio.checked = true;
  if (cityRadio) cityRadio.checked = false;

  const siteSelect =
    document.getElementById("site-select") ||
    document.getElementById("siteSelect");

  if (siteSelect) {
    const options = Array.from(siteSelect.options);
    const matched = options.find(opt => opt.value === siteId);
    if (matched) {
      siteSelect.value = siteId;
    } else {
      console.warn("[setSelectedSiteInUI] site option not found:", siteId);
    }
  }

  const siteSelectWrap =
    document.getElementById("site-select-wrap") ||
    document.getElementById("siteSelectWrap") ||
    document.querySelector(".site-select-wrap");

  if (siteSelectWrap) {
    siteSelectWrap.style.display = "";
    siteSelectWrap.hidden = false;
  }
}
```

用途：

```text
任何按钮只要切换到单站点，都必须调用这个函数。
```

---

## 五、增强四季代表日解析函数

找到当前：

```javascript
function pickSeasonDate(seasonKey) { ... }
```

新增一个更完整的函数：

```javascript
function pickSeasonRepresentative(seasonKey) {
  const data = gSeasonDays || {};

  function normalizeItem(item) {
    if (!item) return null;

    if (typeof item === "string") {
      return {
        date: item,
        siteId: null,
        siteName: null,
      };
    }

    if (typeof item === "object") {
      return {
        date:
          item.date ||
          item.day ||
          item.representative_date ||
          item.start_date ||
          null,
        siteId:
          item.site_id ||
          item.station_id ||
          item.id ||
          item.representative_site_id ||
          null,
        siteName:
          item.site_name ||
          item.station_name ||
          item.name ||
          item.representative_site_name ||
          null,
      };
    }

    return null;
  }

  if (Array.isArray(data)) {
    const row = data.find(x => {
      const s = String(x.season || x.season_key || x.name || x.label || "").toLowerCase();
      return s === seasonKey || s.includes(seasonKey);
    });
    return normalizeItem(row);
  }

  const item =
    data[seasonKey] ||
    data[`${seasonKey}_date`] ||
    data[`${seasonKey}_day`] ||
    data[`${seasonKey}_representative`];

  return normalizeItem(item);
}
```

保留原 `pickSeasonDate` 也可以，但 `selectSeasonDay` 必须改用 `pickSeasonRepresentative`。

---

## 六、重写四季按钮逻辑

找到当前：

```javascript
async function selectSeasonDay(seasonKey) { ... }
```

整体替换为：

```javascript
async function selectSeasonDay(seasonKey) {
  syncStateFromControls();

  const beforeScope = state.scope;
  const beforeSiteId = state.siteId;

  const rep = pickSeasonRepresentative(seasonKey);
  if (!rep || !rep.date) {
    console.warn("[selectSeasonDay] no representative day for season", seasonKey, rep);
    return;
  }

  state.startDate = rep.date;
  state.endDate = rep.date;
  setDateComboValue("start", rep.date);
  setDateComboValue("end", rep.date);

  // 如果 season_days.json 明确给了代表站点，用代表站点；
  // 如果没有给代表站点，则保持点击按钮前的站点。
  const targetSiteId = rep.siteId || beforeSiteId;

  if (beforeScope === "site" || targetSiteId) {
    setSelectedSiteInUI(targetSiteId);
    await ensureSiteRows(targetSiteId);
  } else {
    state.scope = "city";
    const cityRadio = document.querySelector('input[name="scope"][value="city"]');
    const siteRadio = document.querySelector('input[name="scope"][value="site"]');
    if (cityRadio) cityRadio.checked = true;
    if (siteRadio) siteRadio.checked = false;
  }

  console.info("[selectSeasonDay]", {
    seasonKey,
    date: rep.date,
    representativeSiteId: rep.siteId,
    representativeSiteName: rep.siteName,
    targetSiteId: state.siteId,
    scope: state.scope,
  });

  await refreshAll();
}
```

关键要求：

```text
四季代表日如果有代表站点：下拉框显示代表站点；
四季代表日如果没有代表站点：下拉框显示点击前站点；
下拉框不能空、不能隐藏。
```

---

## 七、如果 season_days.json 没有站点字段

如果 `season_days.json` 只有日期，没有站点，例如：

```json
{
  "spring": "2024-04-01",
  "summer": "2024-07-01"
}
```

那么四季按钮没有“对应站点”这个信息。

此时按下面规则：

```text
当前是单站点：保持当前站点，选择站点框显示当前站点名；
当前是全市：继续展示全市，不强制选择站点。
```

如果你希望每个季节都有固定代表站点，需要在导出脚本中补充 `season_days.json`：

```json
{
  "spring": {
    "date": "2024-04-01",
    "site_id": "S062",
    "site_name": "韩华大浦光伏电站"
  },
  "summer": {
    "date": "2024-07-01",
    "site_id": "S023",
    "site_name": "连洋徐圩光伏"
  }
}
```

本轮前端先做兼容，不强制修改导出脚本。

---

## 八、按钮绑定确认

检查四季按钮绑定，确保调用的是新的 `selectSeasonDay`：

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

如果实际 ID 不一致，按页面实际 ID 替换。

---

## 九、静态检查

执行：

```bash
python - <<'PY'
from pathlib import Path

p = Path("stages/05_visualization/interactive_forecast_dashboard.html")
text = p.read_text(encoding="utf-8")

required = [
    "setSelectedSiteInUI",
    "pickSeasonRepresentative",
    "selectSeasonDay",
    "representativeSiteId",
    "targetSiteId",
]

missing = [x for x in required if x not in text]
assert not missing, "缺少关键逻辑: " + ", ".join(missing)

print("[OK] Round39.8 static check passed")
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

## 十、页面验收

启动服务：

```bash
python -m http.server 8070
```

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round39_8
```

强制刷新：

```text
Ctrl + Shift + R
```

### 验收 1：单站点模式

先选择：

```text
展示对象：单站点
选择站点：S062 韩华大浦光伏电站
```

依次点击：

```text
春季
夏季
秋季
冬季
```

每次必须满足：

```text
展示对象仍为单站点；
选择站点框仍显示；
选择站点框显示 S062 韩华大浦光伏电站，或者显示 season_days.json 指定的代表站点；
日期变为对应季节代表日；
曲线正常刷新。
```

### 验收 2：控制台日志

控制台应显示：

```text
[selectSeasonDay] {
  seasonKey: "...",
  date: "...",
  representativeSiteId: "...",
  representativeSiteName: "...",
  targetSiteId: "...",
  scope: "site"
}
```

其中：

```text
targetSiteId 必须和选择站点框一致。
```

### 验收 3：全市模式

切换到：

```text
展示对象：全市
```

点击四季按钮：

```text
可以继续展示全市代表日；
如果 season_days.json 没有代表站点，不强制显示站点；
如果 season_days.json 有代表站点并希望展示单站点，则需要明确按钮文案，否则不建议自动切单站点。
```

---

## 十一、如果仍不同步，回传这些输出

浏览器控制台执行：

```javascript
console.log("state", state);
console.log("siteSelect", document.getElementById("site-select")?.value || document.getElementById("siteSelect")?.value);
console.log("siteSelectText", document.getElementById("site-select")?.selectedOptions?.[0]?.text || document.getElementById("siteSelect")?.selectedOptions?.[0]?.text);
console.log("gSeasonDays", gSeasonDays);
```

并回传点击四季按钮时的：

```text
[selectSeasonDay]
```

日志。

