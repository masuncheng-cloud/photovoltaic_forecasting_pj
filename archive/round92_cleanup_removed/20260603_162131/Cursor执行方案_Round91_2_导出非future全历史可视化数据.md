# Cursor执行方案 Round91_2：导出所有非 future 的全历史可视化数据

## 目标

修复可视化页面中“日期框显示全年，但春季按钮仍不可用”的根因。

当前问题不是前端四季定义错，而是：

```text
output/pv_pipeline/interactive_dashboard 中导出的 city_series / site_series 只覆盖部分历史时间段，
例如页面实际横轴从 2025-07-01 开始，因此即使日期框选择 2025-01-01 ~ 2025-12-31，
页面数据中也没有 3-5 月，春季按钮自然不可用。
```

本轮要求：

- 可视化数据导出时使用所有非 `future` 的全历史预测数据；
- 不导出 future 数据；
- city_series、site_series、site_metrics、typical_sites、hourly metrics 等都基于同一份非 future 全历史数据；
- 测试集 NRMSE 仍然可以按测试集口径统计，但页面折线图和四季按钮的数据范围必须来自非 future 全历史；
- 导出完成后验证 2025 年 3-5 月是否真实存在数据；
- 如果真实没有春季数据，则春季按钮灰掉是正确的；如果有数据，春季必须可点击。

本轮不改模型、不重训，只改导出与验证逻辑。

---

## 一、备份

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

mkdir -p archive/round91_2_export_non_future_full_history/current_state

cp -a scripts/export_interactive_dashboard_data.py \
  archive/round91_2_export_non_future_full_history/current_state/export_interactive_dashboard_data.before_round91_2.py

cp -a stages/05_visualization/interactive_forecast_dashboard.html \
  archive/round91_2_export_non_future_full_history/current_state/interactive_forecast_dashboard.before_round91_2.html

cp -a output/pv_pipeline/interactive_dashboard \
  archive/round91_2_export_non_future_full_history/current_state/interactive_dashboard.before_round91_2
```

---

## 二、检查当前导出数据覆盖范围

先确认现在导出的数据到底覆盖哪些日期。

```bash
python - <<'PY'
import json
from pathlib import Path

base = Path("output/pv_pipeline/interactive_dashboard")

for name in ["city_series.json"]:
    p = base / name
    rows = json.loads(p.read_text(encoding="utf-8"))
    dates = sorted({str(r.get("date") or r.get("datetime") or r.get("time", ""))[:10] for r in rows if r})
    print(name, "rows=", len(rows), "min=", dates[0] if dates else None, "max=", dates[-1] if dates else None)
    print("has spring 2025:", any("2025-03-01" <= d <= "2025-05-31" for d in dates))

site_dir = base / "site_series"
files = sorted(site_dir.glob("*.json"))
print("site_series files:", len(files))
if files:
    p = files[0]
    rows = json.loads(p.read_text(encoding="utf-8"))
    dates = sorted({str(r.get("date") or r.get("datetime") or r.get("time", ""))[:10] for r in rows if r})
    print(p.name, "rows=", len(rows), "min=", dates[0] if dates else None, "max=", dates[-1] if dates else None)
    print("has spring 2025:", any("2025-03-01" <= d <= "2025-05-31" for d in dates))
PY
```

如果输出显示最早日期是 `2025-07-01` 或 `2025-09-01`，说明当前导出确实没有春季数据。

---

## 三、修改导出脚本：统一非 future 全历史口径

修改文件：

```text
scripts/export_interactive_dashboard_data.py
```

### 3.1 定义最终预测列

在导出脚本里统一使用最终预测列：

```python
PRED_COL_PRIORITY = [
    "power_pred_final",
    "power_pred",
    "pred_mw",
    "prediction_mw",
]
```

新增函数：

```python
def resolve_prediction_column(df):
    for col in PRED_COL_PRIORITY:
        if col in df.columns:
            return col
    raise KeyError(f"Cannot find prediction column. Available columns: {list(df.columns)}")
```

要求：

- 优先使用 `power_pred_final`；
- 不允许静默回退到明显旧列；
- 如果没有最终预测列，直接报错。

### 3.2 新增 build_full_history_frame()

在读取最终预测结果之后，统一构造可视化全历史数据：

```python
def build_full_history_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    if "split" in out.columns:
        out = out[out["split"].astype(str).str.lower() != "future"].copy()

    if "is_future" in out.columns:
        out = out[~out["is_future"].fillna(False).astype(bool)].copy()

    pred_col = resolve_prediction_column(out)

    rename_map = {
        pred_col: "pred_mw",
        "power_mw": "actual_mw",
    }
    out = out.rename(columns={k: v for k, v in rename_map.items() if k in out.columns})

    required = ["datetime", "site_id", "actual_mw", "pred_mw"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise KeyError(f"Missing required dashboard columns: {missing}")

    out["datetime"] = pd.to_datetime(out["datetime"])
    out["date"] = out["datetime"].dt.strftime("%Y-%m-%d")
    out["hour"] = out["datetime"].dt.hour

    out = out.sort_values(["datetime", "site_id"]).reset_index(drop=True)
    return out
```

如果项目中时间列不是 `datetime`，按实际列名兼容：

```python
for c in ["datetime", "time", "timestamp", "date_time"]:
    if c in out.columns:
        out = out.rename(columns={c: "datetime"})
        break
```

### 3.3 所有可视化导出都使用 full_history_df

导出脚本里凡是生成以下产物的地方：

```text
city_series.json
site_series/*.json
site_metrics.json
typical_sites.json
hourly_relative_error / hourly_nrmse
sample_nrmse_relation
metadata.json
```

必须用：

```python
full_history_df = build_full_history_frame(pred_df)
```

不要继续用只包含测试集或某个窗口的数据。

注意：

- 折线图展示数据：用 `full_history_df`
- 四季按钮数据：用 `full_history_df`
- 典型日期选择：用 `full_history_df`
- 页面全量样本数：用 `full_history_df`
- 测试集 NRMSE：仍可在 `full_history_df` 上按 `split == "test"` 或测试日期范围过滤后计算

### 3.4 city_series 导出逻辑

city_series 必须按全历史非 future 聚合：

```python
def export_city_series(full_history_df, out_dir):
    g = (
        full_history_df
        .groupby("datetime", as_index=False)
        .agg(
            actual_mw=("actual_mw", "sum"),
            pred_mw=("pred_mw", "sum"),
            sample_count=("site_id", "nunique"),
        )
    )
    g["date"] = g["datetime"].dt.strftime("%Y-%m-%d")
    g["hour"] = g["datetime"].dt.hour
    g["datetime"] = g["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    write_json_records(g, out_dir / "city_series.json")
```

要求：

- 不要只导出 test；
- 不要只导出 `2025-07-01` 之后；
- 不要包含 future。

### 3.5 site_series 导出逻辑

site_series 每个站点必须导出非 future 全历史：

```python
def export_site_series(full_history_df, out_dir):
    site_dir = out_dir / "site_series"
    site_dir.mkdir(parents=True, exist_ok=True)

    for site_id, s in full_history_df.groupby("site_id"):
        s = s.sort_values("datetime").copy()
        s["datetime"] = s["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
        keep_cols = [
            "datetime", "date", "hour", "site_id",
            "actual_mw", "pred_mw",
        ]
        extra_cols = [c for c in ["site_name", "capacity_mw", "split"] if c in s.columns]
        write_json_records(s[keep_cols + extra_cols], site_dir / f"{site_id}.json")
```

### 3.6 metadata 写入覆盖范围

metadata 中写入实际导出范围：

```python
metadata.update({
    "dashboard_data_scope": "non_future_full_history",
    "include_future": False,
    "min_date": full_history_df["date"].min(),
    "max_date": full_history_df["date"].max(),
    "row_count": int(len(full_history_df)),
    "site_count": int(full_history_df["site_id"].nunique()),
    "has_2025_spring": bool(
        ((full_history_df["date"] >= "2025-03-01") & (full_history_df["date"] <= "2025-05-31")).any()
    ),
})
```

---

## 四、增加导出后数据覆盖校验

在 `scripts/export_interactive_dashboard_data.py` 末尾新增校验函数：

```python
def validate_dashboard_full_history(out_dir: Path):
    city_path = out_dir / "city_series.json"
    if not city_path.exists():
        raise FileNotFoundError(city_path)

    city = pd.read_json(city_path)
    if city.empty:
        raise ValueError("city_series.json is empty")

    city["date"] = pd.to_datetime(city["datetime"]).dt.strftime("%Y-%m-%d")

    min_date = city["date"].min()
    max_date = city["date"].max()
    has_future = False

    spring_2025 = city[(city["date"] >= "2025-03-01") & (city["date"] <= "2025-05-31")]

    report = {
        "status": "PASS",
        "scope": "non_future_full_history",
        "city_rows": int(len(city)),
        "min_date": min_date,
        "max_date": max_date,
        "has_2025_spring": bool(len(spring_2025) > 0),
        "spring_2025_rows": int(len(spring_2025)),
    }

    (out_dir / "full_history_coverage_check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("[dashboard coverage]", report)
```

在 main 末尾调用：

```python
validate_dashboard_full_history(out_dir)
```

不要强制要求一定有春季数据。

原因：

```text
如果最终预测结果本身没有 2025-03~05，那么春季按钮灰掉是正确的；
但必须把这个事实写入 full_history_coverage_check.json，不能让用户误以为页面有全年数据。
```

---

## 五、前端读取 metadata 与覆盖检查

修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

### 5.1 页面默认日期使用 metadata 范围

页面初始化日期时，不要硬编码：

```text
2025-01-01 ~ 2025-12-31
```

改为使用：

```javascript
metadata.min_date
metadata.max_date
```

如果仍想默认展示测试期，可以只用于日期框默认值，但必须有提示。为了避免混乱，本轮建议默认使用全历史范围：

```javascript
setDateControls(gMetadata.min_date, gMetadata.max_date);
```

### 5.2 四季按钮仍根据真实数据判断

保留 Round91_1 的逻辑：

```text
四季按钮是否可用 = 当前手动日期范围内是否真实存在该季节数据
```

不要硬编码全年时春季可点击。

### 5.3 增加轻量说明

如果 `metadata.has_2025_spring === false`，可在控制台输出：

```javascript
console.warn("当前导出的非future全历史可视化数据不包含2025年3-5月，春季按钮不可用是正常结果。");
```

页面不需要增加红色警告，避免影响展示。

---

## 六、重新导出数据

执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/export_interactive_dashboard_data.py
```

导出后检查：

```bash
cat output/pv_pipeline/interactive_dashboard/full_history_coverage_check.json
cat output/pv_pipeline/interactive_dashboard/metadata.json | head -80
```

重点看：

```text
scope / dashboard_data_scope = non_future_full_history
include_future = false
min_date
max_date
has_2025_spring
spring_2025_rows
```

---

## 七、手动验证 city_series 是否包含春季

执行：

```bash
python - <<'PY'
import json
from pathlib import Path

base = Path("output/pv_pipeline/interactive_dashboard")
rows = json.loads((base / "city_series.json").read_text(encoding="utf-8"))
dates = sorted({str(r.get("date") or r.get("datetime") or r.get("time", ""))[:10] for r in rows})

print("city_series rows:", len(rows))
print("min:", dates[0] if dates else None)
print("max:", dates[-1] if dates else None)
for name, months in {
    "spring": {"03","04","05"},
    "summer": {"06","07","08"},
    "autumn": {"09","10","11"},
    "winter": {"12","01","02"},
}.items():
    cnt = sum(1 for d in dates if d[5:7] in months)
    print(name, cnt)
PY
```

如果输出：

```text
spring 0
```

说明最终预测结果本身没有春季数据，前端不能凭空显示春季。

如果输出：

```text
spring > 0
```

则页面中日期范围覆盖春季时，春季按钮必须可点击。

---

## 八、启动可视化页面

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
python -m http.server 8070
```

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round91_2
```

强制刷新：

```text
Ctrl + Shift + R
```

Safari：

```text
Option + Command + R
```

---

## 九、验收标准

### 9.1 导出数据口径

必须满足：

- `metadata.json` 中 `dashboard_data_scope = non_future_full_history`
- `metadata.json` 中 `include_future = false`
- `city_series.json` 覆盖范围等于非 future 最终预测结果覆盖范围
- `site_series/*.json` 覆盖范围等于各站点非 future 最终预测结果覆盖范围

### 9.2 春季按钮

如果 `full_history_coverage_check.json` 中：

```json
"has_2025_spring": true
```

那么页面日期范围覆盖 `2025-03-01 ~ 2025-05-31` 时：

```text
春季按钮必须可点击
```

如果：

```json
"has_2025_spring": false
```

那么春季按钮灰掉是正确行为。

### 9.3 页面默认日期

页面默认日期范围应来自：

```text
metadata.min_date ~ metadata.max_date
```

不要让日期框显示一个数据实际不存在的全年范围。

### 9.4 future 排除

检查导出的 JSON 不包含 future：

```bash
grep -R "\"future\"" output/pv_pipeline/interactive_dashboard | head
```

如果存在 future 行，要回到导出脚本修正。

---

## 十、失败回退

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

cp -a archive/round91_2_export_non_future_full_history/current_state/export_interactive_dashboard_data.before_round91_2.py \
  scripts/export_interactive_dashboard_data.py

cp -a archive/round91_2_export_non_future_full_history/current_state/interactive_forecast_dashboard.before_round91_2.html \
  stages/05_visualization/interactive_forecast_dashboard.html

rm -rf output/pv_pipeline/interactive_dashboard
cp -a archive/round91_2_export_non_future_full_history/current_state/interactive_dashboard.before_round91_2 \
  output/pv_pipeline/interactive_dashboard
```

---

## 十一、执行报告

新建：

```text
docs/Round91_2_导出非future全历史可视化数据报告.md
```

内容模板：

```markdown
# Round91_2 导出非 future 全历史可视化数据报告

## 1. 问题

日期框显示全年，但 city_series / site_series 实际只包含部分历史时间段，导致春季按钮不可用。

## 2. 修改

- export_interactive_dashboard_data.py 改为导出所有非 future 的全历史预测数据。
- city_series、site_series 统一基于 full_history_df。
- metadata 写入 min_date、max_date、dashboard_data_scope、has_2025_spring。
- 新增 full_history_coverage_check.json。

## 3. 导出覆盖范围

- min_date:
- max_date:
- city_rows:
- site_count:
- has_2025_spring:
- spring_2025_rows:

## 4. 验证

- future 数据已排除。
- city_series 覆盖范围与 metadata 一致。
- site_series 覆盖范围与 metadata 一致。
- 如果 has_2025_spring=true，页面春季按钮可点击。

## 5. 影响

本轮只修改可视化数据导出口径和页面默认日期，不改变训练结果、不重训。
```

---

## 十二、注意事项

1. 不要通过前端硬编码强行启用春季按钮。
2. 春季按钮是否可用必须由真实导出的数据决定。
3. 不要导出 future 数据。
4. 不要把测试集 NRMSE 的口径改成全历史；测试指标仍然保持测试集口径。
5. 折线图展示数据可以是非 future 全历史，评估指标可以继续按测试集或当前窗口分别计算，两者不要混淆。
