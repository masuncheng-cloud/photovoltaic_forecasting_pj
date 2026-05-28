# Round39 可视化数据源自动跟随最新训练方案

## 一、目标

把可视化页面的数据来源改成：

```text
训练结果更新 → 自动导出最新可视化 JSON → 页面固定读取最新 JSON
```

以后不再让页面读取旧的：

```text
stages/05_visualization/data/
stages/05_visualization/*.json
旧 output JSON
```

而是统一读取：

```text
output/pv_pipeline/interactive_dashboard/
```

这样只要完整训练脚本完成，自动刷新可视化数据，浏览器强制刷新后就是最新训练结果。

## 二、总体数据链路

目标链路：

```text
完整训练脚本
  ↓
distributed_predictions_final_roundXX.pkl
distributed_predictions_final_eval_roundXX.pkl
  ↓
scripts/export_interactive_dashboard_data.py
  ↓
output/pv_pipeline/interactive_dashboard/
  ├── metadata.json
  ├── site_metrics.json
  ├── typical_sites.json
  ├── city_hourly_nrmse.json
  ├── site_avg_hourly_nrmse.json
  ├── site_series/
  └── ...
  ↓
stages/05_visualization/interactive_forecast_dashboard.html
```

页面只读 `output/pv_pipeline/interactive_dashboard/`。

## 三、Cursor 修改步骤

### Step 1：修改可视化导出脚本，自动寻找最新训练结果

修改：

```text
scripts/export_interactive_dashboard_data.py
```

新增函数：

```python
def find_latest_prediction_file():
    candidates = []
    tables = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"

    # 优先显式 round 文件，编号越大越新
    for p in tables.glob("distributed_predictions_final_round*.pkl"):
        # 提取 round 数字
        import re
        m = re.search(r"round(\\d+)", p.name)
        if m:
            candidates.append((int(m.group(1)), p))

    if candidates:
        candidates.sort(reverse=True, key=lambda x: x[0])
        return candidates[0][1], f"Round{candidates[0][0]}"

    fallback = [
        tables / "distributed_predictions_final.pkl",
        tables / "distributed_predictions_final_full.pkl",
        tables / "distributed_predictions_v159.pkl",
    ]
    for p in fallback:
        if p.exists():
            return p, "unknown"

    raise FileNotFoundError("找不到 distributed_predictions_final_roundXX.pkl 或 fallback 预测文件")
```

然后导出脚本默认使用：

```python
PRED_PATH, ROUND_NAME = find_latest_prediction_file()
```

不要再写死：

```text
round34
round35
round36
```

### Step 2：统一预测列解析

在导出脚本里使用：

```python
from pv_forecasting.core.eval_frame import resolve_prediction_column
pred_col = resolve_prediction_column(df)
```

优先级应为：

```text
power_pred_final
pred_calibrated
power_pred_cal
power_pred
```

导出的前端字段统一为：

```text
pred_mw = df[pred_col]
actual_mw = df["power_mw"]
```

### Step 3：固定导出目录

导出脚本只写到：

```text
output/pv_pipeline/interactive_dashboard/
```

不要再写到：

```text
stages/05_visualization/data/
```

导出前先清理旧 JSON：

```python
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "interactive_dashboard"
if OUT_DIR.exists():
    # 只删除 json/csv 数据，不删除 html
    for p in OUT_DIR.rglob("*"):
        if p.is_file() and p.suffix.lower() in [".json", ".csv"]:
            p.unlink()
OUT_DIR.mkdir(parents=True, exist_ok=True)
```

### Step 4：写入 metadata.json

每次导出时写：

```text
output/pv_pipeline/interactive_dashboard/metadata.json
```

内容：

```python
metadata = {
    "round": ROUND_NAME,
    "source_file": str(PRED_PATH.relative_to(PROJECT_ROOT)),
    "prediction_column": pred_col,
    "actual_column": "power_mw",
    "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    "test_period": "2025-09-01~2025-12-31",
    "hours": "6-19",
    "exclude_future": True,
    "data_root": "output/pv_pipeline/interactive_dashboard",
}
```

前端必须显示：

```text
数据版本：Round36
预测列：power_pred_final
生成时间：xxxx
默认不含 future
```

### Step 5：导出 RoundXX 对应指标 JSON

导出脚本应自动选择与 `ROUND_NAME` 对应的指标文件。

例如如果 `ROUND_NAME == "Round36"`：

读取：

```text
output/pv_pipeline/metrics/round36_site_metrics.csv
output/pv_pipeline/metrics/round36_typical_sites.csv
output/pv_pipeline/metrics/round36_city_hourly_nrmse.csv
output/pv_pipeline/metrics/round36_site_avg_hourly_nrmse.csv
output/pv_pipeline/metrics/round36_site_validity.csv
```

如果 `ROUND_NAME == "Round37"`，就读 `round37_*.csv`。

实现：

```python
round_lower = ROUND_NAME.lower()
site_metrics_csv = METRICS / f"{round_lower}_site_metrics.csv"
typical_csv = METRICS / f"{round_lower}_typical_sites.csv"
city_hourly_csv = METRICS / f"{round_lower}_city_hourly_nrmse.csv"
site_avg_hourly_csv = METRICS / f"{round_lower}_site_avg_hourly_nrmse.csv"
site_validity_csv = METRICS / f"{round_lower}_site_validity.csv"
```

如果对应 round 的 metrics 不存在：

```python
raise FileNotFoundError("找到了最新预测文件，但缺少同 round 的 metrics，请先运行 compute_roundXX_metrics.py")
```

不要静默回退到旧 metrics。

### Step 6：修改 HTML 数据根路径

修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

将所有静态数据路径统一为：

```javascript
const DATA_ROOT = "../../output/pv_pipeline/interactive_dashboard";
```

如果页面也会从 `output/pv_pipeline/interactive_dashboard/index.html` 打开，则用自动判断：

```javascript
const DATA_ROOT = (() => {
  const path = window.location.pathname;
  if (path.includes("/stages/05_visualization/")) {
    return "../../output/pv_pipeline/interactive_dashboard";
  }
  return ".";
})();
```

所有 fetch 必须通过统一函数：

```javascript
async function fetchJSON(path) {
  const sep = path.includes("?") ? "&" : "?";
  const url = `${DATA_ROOT}/${path}${sep}v=${Date.now()}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`加载数据失败: ${url} (${res.status})`);
  }
  return await res.json();
}
```

禁止再出现：

```javascript
fetch("data/...")
fetch("./data/...")
fetch("stages/05_visualization/data/...")
```

### Step 7：页面显示数据版本

HTML 加载：

```javascript
const metadata = await fetchJSON("metadata.json");
```

页面顶部显示：

```text
数据版本：Round36 | 预测列：power_pred_final | 生成时间：xxxx | 默认不含 future
```

如果 `metadata.round` 不是最新 round，页面顶部用红色提示：

```text
警告：当前页面数据版本不是最新训练结果，请重新运行 export_interactive_dashboard_data.py
```

### Step 8：页面自检典型站点

导出脚本在 metadata 中加入：

```python
"typical_best_site_ids": [...],
"typical_worst_site_ids": [...],
```

HTML 读取后显示：

```text
预测最好：S062, S023, S049, S047, S056
预测最差：S007, S063, S065, S041, S072
```

如果仍读到旧的：

```text
S017
S012
S019
S045
S053
S115
```

页面必须显示红色警告：

```text
当前页面疑似读取旧数据，请检查 DATA_ROOT。
```

### Step 9：训练脚本末尾自动刷新可视化

修改：

```text
scripts/run_round36_full_retrain.py
```

在完整训练、指标重算、报告生成后，自动执行：

```python
run_step("导出最新可视化数据", PROJECT_ROOT / "scripts" / "export_interactive_dashboard_data.py")
run_step("校验可视化 actual/pred 一致性", PROJECT_ROOT / "scripts" / "check_dashboard_prediction_values_round36.py")
```

如果以后有 Round37/Round38，建议进一步改成：

```text
scripts/check_dashboard_prediction_values_latest.py
```

本轮先保证 Round36 可用。

### Step 10：清理旧数据目录

确认 HTML 不再读取旧目录后，归档旧数据：

```bash
mkdir -p output/pv_pipeline/archive_old_visualization_data_round39
mv stages/05_visualization/data output/pv_pipeline/archive_old_visualization_data_round39/stages_data_old 2>/dev/null || true
```

如果 `stages/05_visualization/data` 还被代码引用，先修引用，不能直接删。

### Step 11：重新导出并验证

执行：

```bash
python scripts/export_interactive_dashboard_data.py
python scripts/check_dashboard_prediction_values_round36.py
python scripts/posttrain_validation_round36.py
```

然后检查：

```bash
cat output/pv_pipeline/interactive_dashboard/metadata.json
grep -R "data/\\|median(capacity_sum_mw)\\|S017\\|S012" -n stages/05_visualization/interactive_forecast_dashboard.html output/pv_pipeline/interactive_dashboard --include="*.html" --include="*.json" --include="*.js" | head -100
```

预期：

```text
metadata.round = Round36
metadata.prediction_column = power_pred_final
不出现 median(capacity_sum_mw)
不出现旧典型站点组合
```

### Step 12：浏览器刷新

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=latest
```

强制刷新：

```text
Ctrl + Shift + R
```

页面应显示：

```text
数据版本：Round36
预测列：power_pred_final
默认不含 future
```

并显示 Round36 典型站点。

## 四、验收标准

Round39 通过必须满足：

1. `export_interactive_dashboard_data.py` 自动选择最新 `distributed_predictions_final_roundXX.pkl`。
2. 页面只读取 `output/pv_pipeline/interactive_dashboard/`。
3. 页面不再读取 `stages/05_visualization/data/`。
4. `metadata.json` 存在并显示 Round36。
5. 页面显示数据版本、预测列、生成时间。
6. 页面典型站点与 Round36 一致。
7. 页面公式不再出现 `median(capacity_sum_mw)`。
8. 可视化 pred 与 `power_pred_final` 一致。
9. 可视化 actual 与 `power_mw` 一致。
10. `check_dashboard_prediction_values_round36.py` 全部 PASS。
11. `posttrain_validation_round36.py` 0 FAIL / 0 WARN。
12. 完整训练脚本结束后会自动刷新可视化数据。

## 五、完成后回传

请回传：

```text
output/pv_pipeline/interactive_dashboard/metadata.json
页面截图
python scripts/check_dashboard_prediction_values_round36.py 输出
python scripts/posttrain_validation_round36.py 输出
grep -n "DATA_ROOT\\|fetchJSON" stages/05_visualization/interactive_forecast_dashboard.html 输出
grep -R "median(capacity_sum_mw)\\|S017\\|S012" -n stages/05_visualization output/pv_pipeline/interactive_dashboard --include="*.html" --include="*.json" --include="*.js" | head -100 输出
```

## 六、注意

本轮不需要重新训练。  
只有以后训练数据或模型变化时，完整训练脚本会自动刷新可视化 JSON。
