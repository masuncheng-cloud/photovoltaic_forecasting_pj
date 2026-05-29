# Cursor执行方案 Round47.1：验证可视化数据是否为最新训练数据，并确保训练后自动更新

## 目标

本轮不改模型、不重新定义指标，专门检查并修复两个问题：

1. 当前可视化页面中的数据是否来自最新一次训练产物。
2. 后续重新训练后，可视化页面数据是否会自动随训练结果更新。

同时保留 Round46 的正确逐小时 NRMSE 口径，并保留 Round47 中计划接入的训练后自动收口链路。

---

## 一、需要验证的数据链路

当前页面应使用以下链路：

```text
训练输出 final pkl
  -> power_pred_final
  -> round46_hourly_nrmse_consistent.csv
  -> export_interactive_dashboard_data.py
  -> output/pv_pipeline/interactive_dashboard/*.json
  -> interactive_forecast_dashboard.html
```

需要确认页面没有读取旧文件、缓存文件、旧 round 结果或 `power_pred_cal`。

---

## 二、新增可视化数据新鲜度检查脚本

新增脚本：

```text
scripts/check_dashboard_data_freshness.py
```

### 1. 检查内容

脚本必须检查：

- 最新 final pkl 是否存在。
- final pkl 中是否存在 `power_pred_final`。
- `round46_hourly_nrmse_consistent.csv` 是否存在。
- `interactive_dashboard/metadata.json` 是否存在。
- `interactive_dashboard/city_series.json` 是否存在。
- `interactive_dashboard/site_series/*.json` 是否存在。
- `interactive_dashboard/hourly_prediction_summary.json` 是否存在。
- dashboard JSON 修改时间是否晚于 final pkl 或晚于训练结束 stamp。
- metadata 中 `prediction_column` 是否为 `power_pred_final`。
- dashboard 中样本数、时间范围是否与 final pkl 一致。
- dashboard 中不包含 `split == "future"` 数据。
- 页面用的逐小时 NRMSE 是否来自 consistent CSV，而不是旧错误口径。

### 2. 推荐实现

```python
from pathlib import Path
import json
import pandas as pd
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pv_pipeline"
DASH = OUT / "interactive_dashboard"
METRICS = OUT / "metrics"
DOCS = OUT / "docs"


def fail(msg):
    print(f"[FAIL] {msg}")
    raise SystemExit(1)


def ok(msg):
    print(f"[PASS] {msg}")


def find_final_pkl():
    candidates = [
        OUT / "distributed_predictions_final_full.pkl",
        OUT / "distributed_predictions_final_eval.pkl",
        OUT / "predictions" / "distributed_predictions_final_full.pkl",
        OUT / "predictions" / "distributed_predictions_final_eval.pkl",
    ]
    existing = [p for p in candidates if p.exists()]
    if not existing:
        # 兜底搜索，但只在 output/pv_pipeline 内找
        existing = list(OUT.rglob("*final*.pkl"))
    if not existing:
        fail("找不到 final pkl")
    return max(existing, key=lambda p: p.stat().st_mtime)


def main():
    final_pkl = find_final_pkl()
    ok(f"latest final pkl: {final_pkl}")

    final_df = pd.read_pickle(final_pkl)
    required_cols = {"timestamp", "site_id", "power_mw", "power_pred_final"}
    missing = required_cols - set(final_df.columns)
    if missing:
        fail(f"final pkl 缺少字段: {missing}")
    ok("final pkl contains power_pred_final")

    if "split" in final_df.columns:
        future_rows = int((final_df["split"] == "future").sum())
        print(f"[INFO] final pkl future rows: {future_rows}")

    required_files = [
        DASH / "metadata.json",
        DASH / "city_series.json",
        DASH / "hourly_prediction_summary.json",
        METRICS / "round46_hourly_nrmse_consistent.csv",
    ]
    for p in required_files:
        if not p.exists():
            fail(f"缺少 dashboard/metrics 文件: {p}")
        ok(f"exists: {p}")

    site_files = list((DASH / "site_series").glob("*.json"))
    if len(site_files) < 60:
        fail(f"site_series 文件数量异常: {len(site_files)}")
    ok(f"site_series files: {len(site_files)}")

    metadata = json.loads((DASH / "metadata.json").read_text(encoding="utf-8"))
    pred_col = metadata.get("prediction_column")
    if pred_col != "power_pred_final":
        fail(f"metadata prediction_column 不是 power_pred_final: {pred_col}")
    ok("metadata prediction_column == power_pred_final")

    final_mtime = final_pkl.stat().st_mtime
    dash_files = [
        DASH / "metadata.json",
        DASH / "city_series.json",
        DASH / "hourly_prediction_summary.json",
    ]
    stale = [p for p in dash_files if p.stat().st_mtime < final_mtime]
    if stale:
        fail("dashboard 文件早于 final pkl，可能不是最新训练数据: " + ", ".join(str(p) for p in stale))
    ok("dashboard key files are newer than or equal to final pkl")

    hourly_json = json.loads((DASH / "hourly_prediction_summary.json").read_text(encoding="utf-8"))
    hourly_csv = pd.read_csv(METRICS / "round46_hourly_nrmse_consistent.csv")

    # 兼容 list 或 dict 包装结构
    if isinstance(hourly_json, dict):
        rows = hourly_json.get("rows") or hourly_json.get("data") or hourly_json.get("hourly") or []
    else:
        rows = hourly_json

    if len(rows) != 14:
        fail(f"hourly_prediction_summary.json 行数不是 14: {len(rows)}")

    json_df = pd.DataFrame(rows)
    for h in range(10, 15):
        j = json_df[json_df["hour"] == h]
        c = hourly_csv[hourly_csv["hour"] == h]
        if j.empty or c.empty:
            fail(f"缺少小时 {h} 的逐小时数据")
        diff = abs(float(j.iloc[0]["site_avg_nrmse_pct"]) - float(c.iloc[0]["site_avg_nrmse_pct"]))
        if diff > 1e-6:
            fail(f"小时 {h} dashboard JSON 与 consistent CSV 不一致: diff={diff}")
    ok("hourly dashboard JSON matches round46 consistent CSV")

    # 检查旧错误口径
    focus = hourly_csv[hourly_csv["hour"].between(10, 14)]
    if focus["site_avg_nrmse_pct"].max() > 25:
        fail("10-14 点站点平均 NRMSE 超过 25%，疑似回到旧错误口径")
    ok("hourly NRMSE口径正常，未回到旧错误口径")

    print("\n[PASS] dashboard data freshness check passed")


if __name__ == "__main__":
    main()
```

---

## 三、确保训练结束后自动刷新

### 1. 检查训练主入口

查找当前完整训练入口：

```bash
grep -R "post_training_finalize_outputs\|export_interactive_dashboard_data\|update_dashboard_after_training\|distributed_predictions_final" -n scripts *.py
```

确认完整训练入口中，在最终预测文件写出后必须调用：

```bash
python scripts/post_training_finalize_outputs.py
```

如果没有接入，则补上。

### 2. 收口脚本必须包含这些步骤

检查：

```text
scripts/post_training_finalize_outputs.py
```

必须按顺序执行：

```text
1. python scripts/round46_recompute_hourly_nrmse_consistent.py
2. python scripts/export_interactive_dashboard_data.py
3. python scripts/update_dashboard_after_training.py
4. python scripts/check_dashboard_auto_update_stamp.py
5. python scripts/check_dashboard_data_freshness.py
6. dashboard regression check
```

如果第 5 步不存在，就把本轮新增脚本接进去。

推荐在 `post_training_finalize_outputs.py` 的 steps 中加入：

```python
("check_dashboard_data_freshness", [sys.executable, "scripts/check_dashboard_data_freshness.py"])
```

放在：

```text
update_dashboard_after_training
check_dashboard_auto_update_stamp
```

之后。

---

## 四、给 dashboard 加轻量防缓存

检查前端：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

确认读取 JSON 时已经带 cache bust：

```js
fetch(url + '?v=' + Date.now(), { cache: 'no-store' })
```

如果没有，则统一修改所有 dashboard JSON 加载函数，避免浏览器读旧 JSON。

不要在页面上展示训练版本信息；只需要保证读取的是最新 JSON。

---

## 五、执行顺序

### Step 1：新增检查脚本

创建：

```text
scripts/check_dashboard_data_freshness.py
```

### Step 2：接入 post training finalize

修改：

```text
scripts/post_training_finalize_outputs.py
```

在 dashboard 导出和 stamp 检查之后，加入：

```bash
python scripts/check_dashboard_data_freshness.py
```

### Step 3：非训练验证

先不重新训练，直接执行：

```bash
python scripts/post_training_finalize_outputs.py
python scripts/check_dashboard_data_freshness.py
python scripts/check_dashboard_auto_update_stamp.py
```

全部必须 PASS。

### Step 4：完整训练验证

执行当前项目的完整训练命令。

训练结束后日志必须自动出现：

```text
[PASS] post training finalize completed
[PASS] dashboard data freshness check passed
```

然后手动再执行一次：

```bash
python scripts/check_dashboard_data_freshness.py
```

确认页面数据已经是最新训练数据。

---

## 六、验收标准

### 1. 数据新鲜度

以下文件修改时间必须晚于或等于最新 final pkl：

```text
output/pv_pipeline/interactive_dashboard/metadata.json
output/pv_pipeline/interactive_dashboard/city_series.json
output/pv_pipeline/interactive_dashboard/hourly_prediction_summary.json
output/pv_pipeline/metrics/round46_hourly_nrmse_consistent.csv
```

### 2. 预测列

`metadata.json` 中必须是：

```json
{
  "prediction_column": "power_pred_final"
}
```

### 3. 逐小时结果

`hourly_prediction_summary.json` 中 10-14 点的：

```text
site_avg_nrmse_pct
```

必须与：

```text
round46_hourly_nrmse_consistent.csv
```

完全一致。

### 4. 页面缓存

浏览器强制刷新后：

```text
Ctrl + Shift + R
```

页面不应继续显示旧数据。

### 5. 自动更新

重新训练后，不需要手动运行：

```bash
python scripts/export_interactive_dashboard_data.py
```

训练主流程会自动完成：

```text
consistent 指标重算 -> dashboard JSON 导出 -> 新鲜度检查
```

---

## 七、如果检查失败，如何定位

### 1. dashboard 文件旧于 final pkl

说明训练后没有自动执行 dashboard 导出。

处理：

```bash
python scripts/post_training_finalize_outputs.py
```

并检查训练入口是否接入该脚本。

### 2. metadata 不是 power_pred_final

说明导出脚本又回退到了旧预测列。

处理：

在 `export_interactive_dashboard_data.py` 中禁止静默回退：

```python
if "power_pred_final" not in df.columns:
    raise ValueError("missing power_pred_final; do not fallback to old prediction columns")
```

### 3. 逐小时 JSON 与 CSV 不一致

说明页面 JSON 不是从 consistent CSV 生成。

处理：

检查 `export_hourly_prediction_summary()`，要求优先读取：

```text
output/pv_pipeline/metrics/round46_hourly_nrmse_consistent.csv
```

### 4. 页面仍显示旧数据

说明浏览器缓存或服务目录不对。

处理：

```bash
pwd
python -m http.server 8070
```

访问：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

并强制刷新。

