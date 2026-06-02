# Cursor执行方案 Round77：修复可视化页面样本量表格字段缺失显示

## 问题现象

当前可视化页面中，以下两个表有部分数据无法显示：

1. `达到不同 NRMSE 阈值的全量历史样本量分布`
   - `达标站点数`、`总站点数`、`达标比例` 能显示。
   - 但 `全量样本最小值`、`全量样本25分位`、`全量样本中位数`、`全量样本75分位`、`全量样本最大值`、`正功率样本中位数` 显示为 `-`。

2. `按全量历史样本数分箱的 NRMSE 分布`
   - `全量样本中位数`、`NRMSE均值%` 等能显示。
   - 但 `全量正功率样本中位数` 显示为 `-`。

## 初步判断

这不是训练结果本身损坏，而是**可视化导出数据字段名与前端读取字段不一致**。

页面能算出站点数和 NRMSE，说明 `site_metrics` 或相关 JSON 已加载成功；但样本量分位数显示为 `-`，说明前端用于计算分位数的字段是 `undefined/null`，常见原因包括：

- 导出脚本字段叫 `positive_samples`，前端读取 `positive_sample_count`。
- 导出脚本字段叫 `train_valid_daylight_positive_count`，前端读取 `train_valid_positive_samples`。
- Round76 清理后部分历史字段被移除，但前端仍按旧字段名取值。
- 阈值表使用了错误的横轴字段，没有回退到 `full_history_sample_count`。

本轮不改模型、不重训，只修复数据导出和前端字段读取一致性。

---

## 一、执行前备份

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
mkdir -p archive/round77_dashboard_table_fix
cp -a scripts/export_interactive_dashboard_data.py archive/round77_dashboard_table_fix/export_interactive_dashboard_data.before_round77.py
cp -a stages/05_visualization/interactive_forecast_dashboard.html archive/round77_dashboard_table_fix/interactive_forecast_dashboard.before_round77.html
cp -a output/pv_pipeline/interactive_dashboard archive/round77_dashboard_table_fix/interactive_dashboard.before_round77
```

---

## 二、先检查当前 JSON 字段

执行：

```bash
python - <<'PY'
import json
from pathlib import Path

root = Path("output/pv_pipeline/interactive_dashboard")

for name in [
    "site_metrics.json",
    "sample_nrmse_relation.json",
    "sample_threshold_summary.json",
    "sample_bin_summary.json",
]:
    p = root / name
    print("\n==", name, "==")
    if not p.exists():
        print("MISSING")
        continue
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        print("dict keys:", list(data.keys())[:30])
        rows = None
        for k in ["rows", "data", "items", "records"]:
            if isinstance(data.get(k), list):
                rows = data[k]
                print("row key:", k)
                break
    elif isinstance(data, list):
        rows = data
    else:
        rows = None
    if rows:
        print("rows:", len(rows))
        print("first row keys:", list(rows[0].keys()))
        print("first row:", rows[0])
PY
```

记录输出，重点看是否存在以下字段：

- `full_history_sample_count`
- `full_history_positive_count`
- `train_valid_daylight_positive_count`
- `test_daylight_zero_ratio`
- `nrmse_pct`
- `category`

如果不存在，就需要在导出脚本中补齐。

---

## 三、修复导出脚本：统一站点样本字段

修改：

`scripts/export_interactive_dashboard_data.py`

找到生成站点指标、样本量关系、典型站点表的地方，确保每个站点记录至少包含以下字段：

```python
full_history_sample_count
full_history_positive_count
full_history_zero_ratio_pct
train_valid_sample_count
train_valid_daylight_sample_count
train_valid_daylight_positive_count
train_valid_daylight_zero_ratio_pct
test_daylight_sample_count
test_daylight_positive_count
test_daylight_zero_ratio_pct
nrmse_pct
mae_mw
rmse_mw
pred_actual_ratio
```

如果当前字段名不同，请在导出前统一做一次 normalize，建议新增函数：

```python
def normalize_site_metric_fields(row: dict) -> dict:
    """统一可视化页面使用的站点级字段名，避免前端字段缺失显示 '-'。"""

    def first_number(*keys, default=0):
        for k in keys:
            v = row.get(k)
            if v is None:
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return default

    def first_int(*keys, default=0):
        return int(round(first_number(*keys, default=default)))

    out = dict(row)

    out["full_history_sample_count"] = first_int(
        "full_history_sample_count",
        "history_sample_count",
        "all_history_sample_count",
        "sample_count",
        "total_samples",
    )
    out["full_history_positive_count"] = first_int(
        "full_history_positive_count",
        "full_positive_sample_count",
        "history_positive_count",
        "positive_sample_count",
        "positive_samples",
    )
    out["train_valid_daylight_positive_count"] = first_int(
        "train_valid_daylight_positive_count",
        "train_valid_positive_sample_count",
        "train_valid_positive_samples",
        "train_valid_6_19_positive_count",
    )
    out["test_daylight_sample_count"] = first_int(
        "test_daylight_sample_count",
        "test_6_19_sample_count",
        "test_sample_count",
    )
    out["test_daylight_positive_count"] = first_int(
        "test_daylight_positive_count",
        "test_6_19_positive_count",
        "test_positive_sample_count",
        "test_positive_samples",
    )

    full_n = out["full_history_sample_count"]
    full_pos = out["full_history_positive_count"]
    test_n = out["test_daylight_sample_count"]
    test_pos = out["test_daylight_positive_count"]

    out["full_history_zero_ratio_pct"] = (
        round((1 - full_pos / full_n) * 100, 2) if full_n > 0 else None
    )
    out["test_daylight_zero_ratio_pct"] = (
        round((1 - test_pos / test_n) * 100, 2) if test_n > 0 else None
    )

    out["nrmse_pct"] = first_number(
        "nrmse_pct",
        "NRMSE %",
        "nrmse",
        default=None,
    )

    return out
```

然后在写出 `site_metrics.json`、`sample_nrmse_relation.json`、`typical_sites.json` 前，对每条站点记录执行：

```python
rows = [normalize_site_metric_fields(r) for r in rows]
```

---

## 四、修复样本量阈值表生成逻辑

在导出脚本中找到生成：

- `sample_threshold_summary.json`
- 或页面中 `达到不同 NRMSE 阈值的全量历史样本量分布` 对应的数据

确保使用的样本量字段是：

```python
sample_col = "full_history_sample_count"
positive_col = "full_history_positive_count"
```

阈值表逻辑应类似：

```python
import numpy as np


def percentile(values, q):
    arr = [float(v) for v in values if v is not None and float(v) >= 0]
    if not arr:
        return None
    return float(np.percentile(arr, q))


def build_sample_threshold_summary(site_rows):
    valid_rows = [
        r for r in site_rows
        if r.get("nrmse_pct") is not None
        and r.get("full_history_sample_count", 0) > 0
        and r.get("full_history_positive_count", 0) > 0
    ]

    rows = []
    for threshold in [5, 10, 15, 20, 25]:
        passed = [r for r in valid_rows if float(r["nrmse_pct"]) <= threshold]
        samples = [r["full_history_sample_count"] for r in passed]
        positives = [r["full_history_positive_count"] for r in passed]
        total = len(valid_rows)

        rows.append({
            "nrmse_threshold_pct": threshold,
            "passed_site_count": len(passed),
            "total_site_count": total,
            "passed_ratio_pct": round(len(passed) / total * 100, 2) if total else 0,
            "full_sample_min": percentile(samples, 0),
            "full_sample_p25": percentile(samples, 25),
            "full_sample_median": percentile(samples, 50),
            "full_sample_p75": percentile(samples, 75),
            "full_sample_max": percentile(samples, 100),
            "positive_sample_median": percentile(positives, 50),
        })

    return rows
```

注意：

- 如果 `passed_site_count > 0`，这些分位数字段不允许为 `None`。
- 如果阈值下没有达标站点，例如 5%，可以显示 `-`。

---

## 五、修复样本分箱表逻辑

在导出脚本中找到生成：

- `sample_bin_summary.json`
- 或页面中 `按全量历史样本数分箱的 NRMSE 分布` 对应的数据

确保每个分箱同时计算：

```python
full_sample_median
full_positive_sample_median
train_valid_daylight_positive_sample_median
nrmse_mean_pct
nrmse_median_pct
nrmse_p25_pct
nrmse_p75_pct
nrmse_best_pct
nrmse_worst_pct
```

示例逻辑：

```python
def build_sample_bin_summary(site_rows):
    bins = [
        (0, 5000, "0-5000"),
        (5000, 10000, "5000-10000"),
        (10000, 15000, "10000-15000"),
        (15000, 20000, "15000-20000"),
        (20000, 26000, "20000-26000"),
        (26000, 28000, "26000-28000"),
        (28000, float("inf"), "28000+"),
    ]

    valid_rows = [
        r for r in site_rows
        if r.get("nrmse_pct") is not None
        and r.get("full_history_sample_count", 0) > 0
        and r.get("full_history_positive_count", 0) > 0
    ]

    out = []
    for lo, hi, label in bins:
        group = [
            r for r in valid_rows
            if lo <= r["full_history_sample_count"] < hi
        ]
        nrmse = [r["nrmse_pct"] for r in group]
        full_samples = [r["full_history_sample_count"] for r in group]
        full_pos = [r["full_history_positive_count"] for r in group]
        tv_pos = [r["train_valid_daylight_positive_count"] for r in group]

        out.append({
            "sample_bin": label,
            "site_count": len(group),
            "full_sample_median": percentile(full_samples, 50),
            "full_positive_sample_median": percentile(full_pos, 50),
            "train_valid_daylight_positive_sample_median": percentile(tv_pos, 50),
            "nrmse_mean_pct": round(float(np.mean(nrmse)), 2) if nrmse else None,
            "nrmse_median_pct": percentile(nrmse, 50),
            "nrmse_p25_pct": percentile(nrmse, 25),
            "nrmse_p75_pct": percentile(nrmse, 75),
            "nrmse_best_pct": percentile(nrmse, 0),
            "nrmse_worst_pct": percentile(nrmse, 100),
        })

    return out
```

---

## 六、修复前端字段读取兼容

修改：

`stages/05_visualization/interactive_forecast_dashboard.html`

找到渲染两个表格的函数，增加字段兼容函数：

```javascript
function firstValue(row, keys, fallback = null) {
  for (const key of keys) {
    if (row && row[key] !== undefined && row[key] !== null && row[key] !== '') {
      return row[key];
    }
  }
  return fallback;
}

function fmtIntDash(v) {
  if (v === null || v === undefined || v === '' || Number.isNaN(Number(v))) return '-';
  return Math.round(Number(v)).toLocaleString('zh-CN');
}

function fmtPctDash(v) {
  if (v === null || v === undefined || v === '' || Number.isNaN(Number(v))) return '-';
  return `${Number(v).toFixed(2).replace(/\.00$/, '')}%`;
}
```

### 6.1 阈值表字段读取

阈值表中的字段应按以下兼容方式读取：

```javascript
const sampleMin = firstValue(row, ['full_sample_min', 'sample_min', 'min_sample_count']);
const sampleP25 = firstValue(row, ['full_sample_p25', 'sample_p25', 'p25_sample_count']);
const sampleMedian = firstValue(row, ['full_sample_median', 'sample_median', 'median_sample_count']);
const sampleP75 = firstValue(row, ['full_sample_p75', 'sample_p75', 'p75_sample_count']);
const sampleMax = firstValue(row, ['full_sample_max', 'sample_max', 'max_sample_count']);
const positiveMedian = firstValue(row, ['positive_sample_median', 'full_positive_sample_median']);
```

### 6.2 分箱表字段读取

分箱表中的字段应按以下兼容方式读取：

```javascript
const fullMedian = firstValue(row, ['full_sample_median', 'sample_median']);
const fullPositiveMedian = firstValue(row, ['full_positive_sample_median', 'positive_sample_median']);
const trainValidPositiveMedian = firstValue(row, [
  'train_valid_daylight_positive_sample_median',
  'train_valid_positive_sample_median'
]);
```

这样即使旧 JSON 还没完全更新，也不会出现不必要的空值。

---

## 七、增加导出后强校验

在 `scripts/export_interactive_dashboard_data.py` 的最后，写完 JSON 后增加校验函数：

```python
def validate_sample_summary_outputs(dashboard_dir: Path) -> None:
    import json

    threshold_path = dashboard_dir / "sample_threshold_summary.json"
    bin_path = dashboard_dir / "sample_bin_summary.json"

    if threshold_path.exists():
        rows = json.loads(threshold_path.read_text(encoding="utf-8"))
        if isinstance(rows, dict):
            rows = rows.get("rows") or rows.get("data") or []
        for r in rows:
            passed = int(r.get("passed_site_count", r.get("达标站点数", 0)) or 0)
            threshold = r.get("nrmse_threshold_pct", r.get("NRMSE阈值"))
            if passed > 0:
                required = [
                    "full_sample_min",
                    "full_sample_p25",
                    "full_sample_median",
                    "full_sample_p75",
                    "full_sample_max",
                    "positive_sample_median",
                ]
                missing = [k for k in required if r.get(k) is None]
                if missing:
                    raise RuntimeError(
                        f"sample threshold summary missing fields at threshold={threshold}: {missing}"
                    )

    if bin_path.exists():
        rows = json.loads(bin_path.read_text(encoding="utf-8"))
        if isinstance(rows, dict):
            rows = rows.get("rows") or rows.get("data") or []
        for r in rows:
            site_count = int(r.get("site_count", r.get("站点数", 0)) or 0)
            if site_count > 0:
                required = [
                    "full_sample_median",
                    "full_positive_sample_median",
                    "train_valid_daylight_positive_sample_median",
                    "nrmse_mean_pct",
                    "nrmse_median_pct",
                ]
                missing = [k for k in required if r.get(k) is None]
                if missing:
                    raise RuntimeError(
                        f"sample bin summary missing fields at bin={r.get('sample_bin')}: {missing}"
                    )

    print("[OK] sample summary outputs have required fields")
```

在 `main()` 写出所有 dashboard JSON 后调用：

```python
validate_sample_summary_outputs(dashboard_dir)
```

---

## 八、重新导出可视化数据

执行：

```bash
python scripts/export_interactive_dashboard_data.py
```

如果导出失败，不要绕过校验。根据报错字段回到第三、四、五步补齐字段。

---

## 九、验证修复结果

执行：

```bash
python - <<'PY'
import json
from pathlib import Path

root = Path("output/pv_pipeline/interactive_dashboard")

threshold = json.loads((root / "sample_threshold_summary.json").read_text(encoding="utf-8"))
if isinstance(threshold, dict):
    threshold = threshold.get("rows") or threshold.get("data") or []

for r in threshold:
    passed = int(r.get("passed_site_count", 0) or 0)
    if passed > 0:
        for k in [
            "full_sample_min",
            "full_sample_p25",
            "full_sample_median",
            "full_sample_p75",
            "full_sample_max",
            "positive_sample_median",
        ]:
            assert r.get(k) is not None, (r, k)

bins = json.loads((root / "sample_bin_summary.json").read_text(encoding="utf-8"))
if isinstance(bins, dict):
    bins = bins.get("rows") or bins.get("data") or []

for r in bins:
    site_count = int(r.get("site_count", 0) or 0)
    if site_count > 0:
        for k in [
            "full_sample_median",
            "full_positive_sample_median",
            "train_valid_daylight_positive_sample_median",
            "nrmse_mean_pct",
            "nrmse_median_pct",
        ]:
            assert r.get(k) is not None, (r, k)

print("[OK] dashboard sample tables no longer contain missing numeric fields")
PY
```

再执行：

```bash
python scripts/check_dashboard_prediction_values.py
python scripts/posttrain_validation.py
```

---

## 十、浏览器检查

启动服务：

```bash
python -m http.server 8070
```

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round77
```

强制刷新：

```text
Ctrl + Shift + R
```

检查以下位置：

1. `达到不同 NRMSE 阈值的全量历史样本量分布`
   - 当 `达标站点数 > 0` 时，样本最小值、25分位、中位数、75分位、最大值不应为 `-`。

2. `按全量历史样本数分箱的 NRMSE 分布`
   - 当 `站点数 > 0` 时，`全量正功率样本中位数` 不应为 `-`。

---

## 十一、生成执行报告

新建：

`docs/Round77_可视化样本量表格缺失显示修复报告.md`

内容包括：

```markdown
# Round77 可视化样本量表格缺失显示修复报告

## 1. 问题

可视化页面中样本量阈值表和样本分箱表部分列显示为 "-"。

## 2. 根因

说明是导出 JSON 字段名与前端读取字段不一致，还是导出阶段未生成对应字段。

## 3. 修改内容

- 统一站点样本量字段。
- 修复阈值表分位数计算。
- 修复分箱表正功率样本中位数计算。
- 前端增加字段兼容读取。
- 导出脚本增加强校验，避免以后静默显示空值。

## 4. 验证结果

填写：

- export_interactive_dashboard_data.py 是否通过
- check_dashboard_prediction_values.py 是否通过
- posttrain_validation.py 是否通过
- 页面表格是否仍存在异常 "-"

## 5. 是否影响模型

本轮不改变模型、不重训、不改变 power_pred_final，只修复可视化统计字段。
```

---

## 十二、验收标准

本轮完成标准：

- `python scripts/export_interactive_dashboard_data.py` 通过。
- `python scripts/check_dashboard_prediction_values.py` 通过。
- `python scripts/posttrain_validation.py` 通过。
- 页面两个样本量表格在有站点数据的行不再显示异常 `-`。
- `power_pred_final` 不发生变化。

