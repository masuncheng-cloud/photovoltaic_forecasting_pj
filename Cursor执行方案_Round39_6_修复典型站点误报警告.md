# Round39.6：修复典型站点误报警告

## 一、当前问题

单站点功率曲线已经恢复正常，但页面顶部仍显示：

```text
警告：预测最好站点不是 [S062, S023, S049, S047, S056]
当前：[S077, S023, S031, S062, S049]

预测最差站点不是 [S007, S063, S065, S041, S072]
当前：[S019, S076, S053, S044, S045]

请重新运行 export_interactive_dashboard_data.py
```

这个警告不一定代表数据过期。

根据前面 Round39.4 的排查，根因是：

```text
expectedBest / expectedWorst 来自 typical_sites.json 或 round36_typical_sites.csv
actualBest / actualWorst 却是从 site_metrics.json 按测试集 NRMSE 重新排序得到的
```

两者口径不同：

```text
typical_sites.json：典型展示站点，可能来自 full-history 或人工/规则筛选
site_metrics.json：测试集 6-19 点 NRMSE 排名
```

所以页面把不同口径的结果强行比较，会产生误报警告。

本轮不重新训练、不修改预测结果，只修复可视化页面的版本检查和典型站点按钮逻辑。

---

## 二、修复目标

1. 页面不再把 `site_metrics.json` 排名结果和 `typical_sites.json` 典型站点名单混合比较。
2. 顶部不再出现误导性的红色警告。
3. “预测最好 / 预测最差 / 相对正确 / 样本少”按钮统一使用 `typical_sites.json`。
4. 如果 `typical_sites.json` 缺失或为空，再显示真实错误。
5. 如果需要展示测试集 NRMSE 排名，单独命名为“测试集排名”，不要叫“典型站点”。

---

## 三、只修改文件

优先只修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

如果项目拆分了 JS，也同步修改实际 JS 文件：

```text
stages/05_visualization/*.js
```

不修改：

```text
output/pv_pipeline/tables/*.pkl
output/pv_pipeline/interactive_dashboard/*.json
output/pv_pipeline/metrics/*.csv
```

---

## 四、先确认数据源是否正常

在项目根目录执行：

```bash
python - <<'PY'
import json
from pathlib import Path

root = Path("output/pv_pipeline/interactive_dashboard")
for name in ["metadata.json", "typical_sites.json", "site_metrics.json"]:
    p = root / name
    print("\\n==", name, "exists=", p.exists(), "size=", p.stat().st_size if p.exists() else None)
    data = json.load(open(p, encoding="utf-8"))
    if isinstance(data, list):
        print("list len=", len(data))
        print(data[:10])
    else:
        print("keys=", list(data.keys()))
        print(str(data)[:1500])
PY
```

必须确认：

```text
metadata.json 中 prediction_column = power_pred_final
typical_sites.json 存在且非空
site_metrics.json 存在且非空
```

---

## 五、重写典型站点读取逻辑

在前端 JS 中增加统一函数：

```javascript
function normalizeTypicalSites(raw) {
  const result = {
    best: [],
    worst: [],
    normal: [],
    small: [],
  };

  if (!raw) return result;

  // 情况1：typical_sites.json 是对象格式
  if (!Array.isArray(raw) && typeof raw === "object") {
    const pick = (...keys) => {
      for (const k of keys) {
        if (Array.isArray(raw[k])) {
          return raw[k].map(x => typeof x === "string" ? x : x.site_id).filter(Boolean);
        }
      }
      return [];
    };

    result.best = pick("best", "预测最好", "typical_best_site_ids", "best_site_ids");
    result.worst = pick("worst", "预测最差", "typical_worst_site_ids", "worst_site_ids");
    result.normal = pick("normal", "relative_correct", "相对正确", "typical_normal_site_ids", "correct_site_ids");
    result.small = pick("small", "sample_small", "样本少", "typical_small_site_ids", "small_site_ids");
    return result;
  }

  // 情况2：typical_sites.json 是列表格式
  if (Array.isArray(raw)) {
    for (const item of raw) {
      const sid = item.site_id || item.station_id || item.id;
      const label = String(item.category || item.category_label || item.type || "");
      if (!sid) continue;

      if (label.includes("最好") || label === "best") result.best.push(sid);
      else if (label.includes("最差") || label === "worst") result.worst.push(sid);
      else if (label.includes("正确") || label === "normal" || label.includes("相对")) result.normal.push(sid);
      else if (label.includes("样本") || label === "small") result.small.push(sid);
    }
  }

  return result;
}
```

---

## 六、修复 `loadAll()`

找到 `loadAll()`，确保它直接读取 `typical_sites.json`：

```javascript
async function loadAll() {
  gMetadata = await fetchJSON("metadata.json");
  gIndex = await fetchJSON("index.json");
  gCityRows = await fetchJSON("city_series.json");
  gSiteMetrics = await fetchJSON("site_metrics.json");
  gTypicalSitesRaw = await fetchJSON("typical_sites.json");
  gTypicalSites = normalizeTypicalSites(gTypicalSitesRaw);

  console.info("[metadata]", gMetadata);
  console.info("[typicalSitesRaw]", gTypicalSitesRaw);
  console.info("[typicalSites]", gTypicalSites);

  // 其他已有数据继续加载
}
```

如果当前 `loadAll()` 使用 `Promise.all`，也可以保留，但必须保证：

```text
gTypicalSites = normalizeTypicalSites(typicalSitesRaw)
```

---

## 七、删除错误的版本检查

在 HTML/JS 中搜索：

```bash
grep -n "expectedBest\\|expectedWorst\\|actualBest\\|actualWorst\\|预测最好站点不是\\|预测最差站点不是" \
  stages/05_visualization/interactive_forecast_dashboard.html
```

删除或替换当前逻辑。

不要再做这种比较：

```javascript
actualBest = siteMetrics.sort((a, b) => a.nrmse_pct - b.nrmse_pct).slice(0, 5)
actualWorst = siteMetrics.sort((a, b) => b.nrmse_pct - a.nrmse_pct).slice(0, 5)
expectedBest = ["S062", "S023", "S049", "S047", "S056"]
expectedWorst = ["S007", "S063", "S065", "S041", "S072"]
```

这就是误报警告的来源。

---

## 八、替换为正确的数据完整性检查

新增或替换版本检查函数：

```javascript
function renderVersionWarning() {
  const el = document.getElementById("version-warning") || document.getElementById("data-warning");
  if (!el) return;

  const messages = [];

  if (!gMetadata) {
    messages.push("metadata.json 未加载。");
  } else {
    if (gMetadata.round && gMetadata.round !== "Round36") {
      messages.push(`当前数据版本为 ${gMetadata.round}，不是 Round36。`);
    }
    if (gMetadata.prediction_column && gMetadata.prediction_column !== "power_pred_final") {
      messages.push(`当前预测列为 ${gMetadata.prediction_column}，不是 power_pred_final。`);
    }
  }

  const best = gTypicalSites?.best || [];
  const worst = gTypicalSites?.worst || [];
  if (best.length === 0) messages.push("typical_sites.json 中缺少预测最好站点。");
  if (worst.length === 0) messages.push("typical_sites.json 中缺少预测最差站点。");

  if (messages.length) {
    el.style.display = "block";
    el.className = "data-warning";
    el.textContent = "警告：" + messages.join(" ");
  } else {
    el.style.display = "none";
    el.textContent = "";
  }
}
```

重点：

```text
这里只检查文件是否缺失、版本是否错误、预测列是否错误。
不要比较 site_metrics 排名和 typical_sites 名单。
```

在 `loadAll()` 完成后调用：

```javascript
renderVersionWarning();
```

---

## 九、修复典型站点按钮

找到 “预测最好 / 预测最差 / 相对正确 / 样本少” 按钮事件。

统一改为从 `gTypicalSites` 取站点：

```javascript
function pickTypicalSite(category) {
  const list = gTypicalSites?.[category] || [];
  if (!list.length) {
    console.warn("[pickTypicalSite] empty category", category, gTypicalSites);
    return null;
  }
  return list[0];
}

async function selectTypicalSite(category) {
  const sid = pickTypicalSite(category);
  if (!sid) return;

  state.scope = "site";
  state.siteId = sid;

  const siteRadio = document.querySelector('input[name="scope"][value="site"]');
  if (siteRadio) siteRadio.checked = true;

  const siteSelect = document.getElementById("site-select") || document.getElementById("siteSelect");
  if (siteSelect) siteSelect.value = sid;

  await ensureSiteRows(sid);
  await refreshAll();
}
```

绑定按钮：

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

按钮 ID 按页面实际情况替换，但逻辑必须统一。

---

## 十、如果还想展示测试集 NRMSE 排名前五

可以新增一个单独表格或调试区，名称必须写清楚：

```text
测试集 NRMSE 排名前五
测试集 NRMSE 后五
```

不要把它作为“典型站点”版本检查依据。

典型站点和测试集排名是两个不同概念。

---

## 十一、静态检查

执行：

```bash
python - <<'PY'
from pathlib import Path

p = Path("stages/05_visualization/interactive_forecast_dashboard.html")
text = p.read_text(encoding="utf-8")

required = [
    "normalizeTypicalSites",
    "gTypicalSites",
    "typical_sites.json",
    "renderVersionWarning",
]
missing = [x for x in required if x not in text]
assert not missing, "缺少: " + ", ".join(missing)

bad_terms = [
    "预测最好站点不是",
    "预测最差站点不是",
]
bad = [x for x in bad_terms if x in text]
assert not bad, "仍存在误报警告文案: " + ", ".join(bad)

print("[OK] Round39.6 static warning check passed")
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

## 十二、页面验收

启动服务：

```bash
python -m http.server 8070
```

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round39_6
```

强制刷新：

```text
Ctrl + Shift + R
```

验收：

1. 顶部不再显示：

```text
预测最好站点不是...
预测最差站点不是...
请重新运行 export_interactive_dashboard_data.py
```

2. 顶部仍显示：

```text
数据版本：Round36（power_pred_final）
```

3. 点击“预测最好”，应该选择 `typical_sites.json` 中的第一个 best 站点。
4. 点击“预测最差”，应该选择 `typical_sites.json` 中的第一个 worst 站点。
5. 单站点曲线仍能正常显示。
6. 全市曲线仍能正常显示。

---

## 十三、完成后回传

请回传：

```bash
python - <<'PY'
import json
from pathlib import Path
root = Path("output/pv_pipeline/interactive_dashboard")
for name in ["metadata.json", "typical_sites.json"]:
    print("\\n==", name)
    data = json.load(open(root / name, encoding="utf-8"))
    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
PY
```

以及页面顶部截图。

