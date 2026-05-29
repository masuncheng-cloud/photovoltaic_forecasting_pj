# Round39.9：四季代表日改为“预测效果最好的一天”

## 一、修改目标

当前四季代表日大概率来自 `season_days.json` 中预先写好的固定日期，或者是按某种中位表现/完整性规则选出的日期。

现在改为：

```text
单站点模式：
点击春季/夏季/秋季/冬季时，选择当前站点在该季节中预测效果最好的一天。

全市模式：
点击春季/夏季/秋季/冬季时，选择全市聚合功率在该季节中预测效果最好的一天。
```

预测效果最好统一按：

```text
日级 NRMSE 最低
```

不重新训练，只修改可视化数据导出与前端读取逻辑。

---

## 二、评价口径

### 2.1 时间范围

用于选择四季代表日的数据只使用：

```text
split in ["train", "valid", "test"]
hour between 6 and 19
不包含 future
actual_mw 和 pred_mw 均非空
```

如果页面当前小时控件不是 6-19，点击四季代表日按钮后建议自动切回：

```text
06:00 至 19:00
```

原因：四季代表日是按全天白天发电时段选出来的，如果只展示 10-14，用户会误以为代表日也是按 10-14 选的。

### 2.2 季节划分

按月份划分：

```text
春季：3、4、5 月
夏季：6、7、8 月
秋季：9、10、11 月
冬季：12、1、2 月
```

### 2.3 单站点日级 NRMSE

对每个站点、每个日期计算：

```text
RMSE_site_day
= sqrt(mean((pred_mw - actual_mw)^2))

NRMSE_site_day
= RMSE_site_day / capacity_mw * 100%
```

其中 `capacity_mw` 使用该站点容量，若同一天多行容量一致，取均值即可。

为了避免用极少样本选出“假最好日”，需要加入约束：

```text
有效小时样本数 >= 8
正功率样本数 >= 3
actual_mw 全日总和 > 0
capacity_mw > 0
```

如果某站点某季节没有满足上述条件的日期，则放宽为：

```text
有效小时样本数 >= 4
actual_mw 全日总和 > 0
```

如果仍没有，则该季节返回 null，前端提示“该站点该季节暂无可用代表日”。

### 2.4 全市日级 NRMSE

先按 `time` 聚合全市：

```text
actual_city_t = sum(actual_mw)
pred_city_t   = sum(pred_mw)
capacity_city_t = sum(capacity_mw)
```

再按日期计算：

```text
RMSE_city_day
= sqrt(mean((pred_city_t - actual_city_t)^2))

capacity_city_day
= mean(capacity_city_t)

NRMSE_city_day
= RMSE_city_day / capacity_city_day * 100%
```

全市代表日约束：

```text
有效小时样本数 >= 8
参与站点数中位数 >= 30
actual_city_t 全日总和 > 0
capacity_city_day > 0
```

每个季节取 `NRMSE_city_day` 最低的日期。

---

## 三、需要新增导出文件

在：

```text
output/pv_pipeline/interactive_dashboard/
```

新增：

```text
season_best_days_city.json
season_best_days_by_site.json
```

### 3.1 `season_best_days_city.json` 格式

```json
{
  "spring": {
    "date": "2025-04-12",
    "season": "spring",
    "scope": "city",
    "nrmse_pct": 3.21,
    "rmse_mw": 6.83,
    "mae_mw": 4.12,
    "sample_count": 14,
    "site_count_median": 68,
    "actual_mwh": 1234.56,
    "pred_mwh": 1229.44
  },
  "summer": { "...": "..." },
  "autumn": { "...": "..." },
  "winter": { "...": "..." }
}
```

### 3.2 `season_best_days_by_site.json` 格式

```json
{
  "S062": {
    "site_id": "S062",
    "site_name": "韩华大浦光伏电站",
    "capacity_mw": 4.45,
    "spring": {
      "date": "2024-04-01",
      "season": "spring",
      "scope": "site",
      "site_id": "S062",
      "site_name": "韩华大浦光伏电站",
      "nrmse_pct": 6.36,
      "rmse_mw": 0.28,
      "mae_mw": 0.23,
      "sample_count": 14,
      "positive_count": 12,
      "actual_mwh": 17.92,
      "pred_mwh": 15.82
    },
    "summer": { "...": "..." },
    "autumn": { "...": "..." },
    "winter": { "...": "..." }
  }
}
```

---

## 四、修改导出脚本

修改：

```text
scripts/export_interactive_dashboard_data.py
```

### 4.1 增加季节函数

```python
def season_from_month(month: int) -> str:
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    if month in (9, 10, 11):
        return "autumn"
    return "winter"
```

### 4.2 增加日级指标工具函数

```python
import math

def safe_float(x, default=None):
    try:
        if pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default

def build_day_metric(rows, capacity_col="capacity_mw"):
    actual = rows["actual_mw"].astype(float)
    pred = rows["pred_mw"].astype(float)
    err = pred - actual
    rmse = math.sqrt(float((err ** 2).mean()))
    mae = float(err.abs().mean())
    cap = float(rows[capacity_col].mean())
    nrmse = rmse / max(cap, 1e-9) * 100
    return rmse, mae, cap, nrmse
```

如果导出脚本内部还用 `power_mw/power_pred_final`，先统一重命名成：

```python
actual_mw
pred_mw
```

### 4.3 新增单站点四季最好日导出函数

```python
def export_season_best_days_by_site(df, dashboard_root):
    work = df.copy()
    work["time"] = pd.to_datetime(work["time"])
    work["date"] = work["time"].dt.strftime("%Y-%m-%d")
    work["hour"] = work["time"].dt.hour
    work["season"] = work["time"].dt.month.map(season_from_month)

    work = work[
        work["split"].isin(["train", "valid", "test"])
        & work["hour"].between(6, 19)
        & work["actual_mw"].notna()
        & work["pred_mw"].notna()
        & work["capacity_mw"].notna()
        & (work["capacity_mw"] > 0)
    ].copy()

    result = {}
    seasons = ["spring", "summer", "autumn", "winter"]

    for site_id, sdf in work.groupby("site_id"):
        site_name = str(sdf["site_name"].dropna().iloc[0]) if "site_name" in sdf.columns and sdf["site_name"].notna().any() else str(site_id)
        capacity = float(sdf["capacity_mw"].dropna().mean())

        item = {
            "site_id": str(site_id),
            "site_name": site_name,
            "capacity_mw": capacity,
        }

        for season in seasons:
            ss = sdf[sdf["season"] == season].copy()
            candidates = []

            for date, ddf in ss.groupby("date"):
                sample_count = int(len(ddf))
                positive_count = int((ddf["actual_mw"] > 0).sum())
                actual_mwh = float(ddf["actual_mw"].sum())
                pred_mwh = float(ddf["pred_mw"].sum())

                strict_ok = sample_count >= 8 and positive_count >= 3 and actual_mwh > 0
                loose_ok = sample_count >= 4 and actual_mwh > 0
                if not (strict_ok or loose_ok):
                    continue

                rmse, mae, cap, nrmse = build_day_metric(ddf)
                candidates.append({
                    "date": str(date),
                    "season": season,
                    "scope": "site",
                    "site_id": str(site_id),
                    "site_name": site_name,
                    "capacity_mw": round(cap, 6),
                    "nrmse_pct": round(nrmse, 6),
                    "rmse_mw": round(rmse, 6),
                    "mae_mw": round(mae, 6),
                    "sample_count": sample_count,
                    "positive_count": positive_count,
                    "actual_mwh": round(actual_mwh, 6),
                    "pred_mwh": round(pred_mwh, 6),
                    "strict_ok": bool(strict_ok),
                })

            if candidates:
                strict_candidates = [x for x in candidates if x["strict_ok"]]
                pool = strict_candidates if strict_candidates else candidates
                item[season] = sorted(pool, key=lambda x: (x["nrmse_pct"], -x["sample_count"], x["date"]))[0]
            else:
                item[season] = None

        result[str(site_id)] = item

    out = Path(dashboard_root) / "season_best_days_by_site.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] wrote {out} sites={len(result)}")
```

### 4.4 新增全市四季最好日导出函数

```python
def export_season_best_days_city(df, dashboard_root):
    work = df.copy()
    work["time"] = pd.to_datetime(work["time"])
    work["date"] = work["time"].dt.strftime("%Y-%m-%d")
    work["hour"] = work["time"].dt.hour
    work["season"] = work["time"].dt.month.map(season_from_month)

    work = work[
        work["split"].isin(["train", "valid", "test"])
        & work["hour"].between(6, 19)
        & work["actual_mw"].notna()
        & work["pred_mw"].notna()
        & work["capacity_mw"].notna()
    ].copy()

    city = (
        work.groupby(["time", "date", "hour", "season"], as_index=False)
        .agg(
            actual_mw=("actual_mw", "sum"),
            pred_mw=("pred_mw", "sum"),
            capacity_sum_mw=("capacity_mw", "sum"),
            site_count=("site_id", "nunique"),
        )
    )

    result = {}
    for season in ["spring", "summer", "autumn", "winter"]:
        ss = city[city["season"] == season].copy()
        candidates = []

        for date, ddf in ss.groupby("date"):
            sample_count = int(len(ddf))
            site_count_median = float(ddf["site_count"].median())
            actual_mwh = float(ddf["actual_mw"].sum())
            pred_mwh = float(ddf["pred_mw"].sum())
            capacity_city = float(ddf["capacity_sum_mw"].mean())

            if sample_count < 8 or site_count_median < 30 or actual_mwh <= 0 or capacity_city <= 0:
                continue

            err = ddf["pred_mw"].astype(float) - ddf["actual_mw"].astype(float)
            rmse = math.sqrt(float((err ** 2).mean()))
            mae = float(err.abs().mean())
            nrmse = rmse / max(capacity_city, 1e-9) * 100

            candidates.append({
                "date": str(date),
                "season": season,
                "scope": "city",
                "nrmse_pct": round(nrmse, 6),
                "rmse_mw": round(rmse, 6),
                "mae_mw": round(mae, 6),
                "sample_count": sample_count,
                "site_count_median": round(site_count_median, 3),
                "capacity_sum_mw": round(capacity_city, 6),
                "actual_mwh": round(actual_mwh, 6),
                "pred_mwh": round(pred_mwh, 6),
            })

        result[season] = sorted(candidates, key=lambda x: (x["nrmse_pct"], -x["sample_count"], x["date"]))[0] if candidates else None

    out = Path(dashboard_root) / "season_best_days_city.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] wrote {out}")
```

### 4.5 在 main 中调用

在导出完 `city_series.json` 和 `site_series` 后调用：

```python
export_season_best_days_city(df_export, dashboard_root)
export_season_best_days_by_site(df_export, dashboard_root)
```

这里的 `df_export` 必须已经包含：

```text
time
site_id
site_name
split
actual_mw
pred_mw
capacity_mw
```

如果脚本中原始列名是：

```text
power_mw
power_pred_final
```

先统一：

```python
df_export["actual_mw"] = df_export["power_mw"]
df_export["pred_mw"] = df_export[pred_col]
```

---

## 五、修改前端加载逻辑

修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

### 5.1 新增全局变量

```javascript
let gSeasonBestCity = {};
let gSeasonBestBySite = {};
```

### 5.2 在 `loadAll()` 中读取新文件

```javascript
gSeasonBestCity = await fetchJSON("season_best_days_city.json");
gSeasonBestBySite = await fetchJSON("season_best_days_by_site.json");
console.info("[seasonBestCity]", gSeasonBestCity);
console.info("[seasonBestBySite sample]", Object.keys(gSeasonBestBySite || {}).slice(0, 5));
```

如果当前 `loadAll()` 用 `Promise.all`，也同步加入这两个文件。

---

## 六、替换四季代表日选择逻辑

找到当前：

```javascript
pickSeasonRepresentative(seasonKey)
selectSeasonDay(seasonKey)
```

替换为下面逻辑。

### 6.1 新增 `pickSeasonBestRepresentative`

```javascript
function pickSeasonBestRepresentative(seasonKey) {
  syncStateFromControls();

  if (state.scope === "site") {
    const siteId = state.siteId;
    const siteItem = gSeasonBestBySite?.[siteId];
    const rep = siteItem?.[seasonKey];

    if (rep && rep.date) {
      return {
        ...rep,
        scope: "site",
        site_id: siteId,
        site_name: rep.site_name || siteItem.site_name || "",
      };
    }

    console.warn("[pickSeasonBestRepresentative] no site season best day", {
      seasonKey,
      siteId,
      siteItem,
    });
    return null;
  }

  const rep = gSeasonBestCity?.[seasonKey];
  if (rep && rep.date) {
    return {
      ...rep,
      scope: "city",
    };
  }

  console.warn("[pickSeasonBestRepresentative] no city season best day", {
    seasonKey,
    gSeasonBestCity,
  });
  return null;
}
```

### 6.2 重写 `selectSeasonDay`

```javascript
async function selectSeasonDay(seasonKey) {
  syncStateFromControls();

  const rep = pickSeasonBestRepresentative(seasonKey);
  if (!rep || !rep.date) {
    alert("当前范围内没有可用的四季代表日数据");
    return;
  }

  state.startDate = rep.date;
  state.endDate = rep.date;
  setDateComboValue("start", rep.date);
  setDateComboValue("end", rep.date);

  // 四季最好日按 6-19 点选出，展示也同步到 6-19 点
  state.startHour = 6;
  state.endHour = 19;
  setHourControls(6, 19);

  if (rep.scope === "site") {
    state.scope = "site";
    state.siteId = rep.site_id || state.siteId;
    setSelectedSiteInUI(state.siteId);
    await ensureSiteRows(state.siteId);
  } else {
    state.scope = "city";
    const cityRadio = document.querySelector('input[name="scope"][value="city"]');
    const siteRadio = document.querySelector('input[name="scope"][value="site"]');
    if (cityRadio) cityRadio.checked = true;
    if (siteRadio) siteRadio.checked = false;
  }

  console.info("[selectSeasonDay best]", {
    seasonKey,
    scope: rep.scope,
    date: rep.date,
    siteId: state.siteId,
    nrmse_pct: rep.nrmse_pct,
    rmse_mw: rep.rmse_mw,
    mae_mw: rep.mae_mw,
    sample_count: rep.sample_count,
  });

  await refreshAll();
}
```

---

## 七、页面提示文字更新

把原说明：

```text
四季代表日
```

附近增加一句：

```text
四季代表日按当前展示对象选择：单站点为该站点本季日级 NRMSE 最低日，全市为全市聚合日级 NRMSE 最低日。
```

如果页面空间有限，可以用按钮 `title`：

```html
title="单站点模式：选择当前站点该季节预测效果最好的一天；全市模式：选择全市该季节预测效果最好的一天。"
```

---

## 八、导出后检查

执行：

```bash
python scripts/export_interactive_dashboard_data.py
```

然后检查：

```bash
python - <<'PY'
import json
from pathlib import Path
root = Path("output/pv_pipeline/interactive_dashboard")

for name in ["season_best_days_city.json", "season_best_days_by_site.json"]:
    p = root / name
    print("\\n==", name, p.exists(), p.stat().st_size if p.exists() else None)
    data = json.load(open(p, encoding="utf-8"))
    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])

site = json.load(open(root / "season_best_days_by_site.json", encoding="utf-8"))
for sid in ["S062", "S023", "S019"]:
    print("\\nsite", sid)
    print(json.dumps(site.get(sid), ensure_ascii=False, indent=2)[:2000])
PY
```

要求：

```text
season_best_days_city.json 四个季节至少部分非空；
season_best_days_by_site.json 中当前可选站点至少部分季节非空；
每个代表日都有 date 和 nrmse_pct。
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
    "season_best_days_city.json",
    "season_best_days_by_site.json",
    "gSeasonBestCity",
    "gSeasonBestBySite",
    "pickSeasonBestRepresentative",
    "selectSeasonDay",
]
missing = [x for x in required if x not in text]
assert not missing, "缺少前端关键逻辑: " + ", ".join(missing)

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
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round39_9
```

强制刷新：

```text
Ctrl + Shift + R
```

### 10.1 单站点验收

选择：

```text
展示对象：单站点
站点：S062 韩华大浦光伏电站
```

依次点击：

```text
春季 / 夏季 / 秋季 / 冬季
```

每次必须满足：

```text
仍为单站点；
选择站点框仍显示 S062；
日期切换为 S062 该季节 NRMSE 最低的一天；
小时切换为 06:00 至 19:00；
曲线正常显示；
控制台显示 [selectSeasonDay best]，其中 scope=site，siteId=S062，nrmse_pct 有值。
```

### 10.2 全市验收

选择：

```text
展示对象：全市
```

依次点击：

```text
春季 / 夏季 / 秋季 / 冬季
```

每次必须满足：

```text
仍为全市；
日期切换为全市该季节 NRMSE 最低的一天；
小时切换为 06:00 至 19:00；
曲线正常显示；
控制台显示 [selectSeasonDay best]，其中 scope=city，nrmse_pct 有值。
```

---

## 十一、补充说明

这次“四季代表日”不再表示季节中最典型、最平均、最有代表性的天气日，而是明确表示：

```text
本季预测效果最好的一天
```

因此页面文案建议改为：

```text
四季最佳日
```

或保留“四季代表日”，但必须加说明：

```text
按日级 NRMSE 最低选择。
```

否则用户可能误解为天气代表日或季节平均日。

