# Round39.2 修复导出脚本仍输出旧数据方案

## 一、当前现象

页面已经显示：

```text
数据版本：Round36
```

但同时显示：

```text
power_pred_cal
警告：仍显示旧数据典型站点，请确认数据已刷新
```

这说明：

1. HTML 已经能读到 `metadata.json`；
2. 浏览器不是主要问题；
3. 当前 `export_interactive_dashboard_data.py` 导出的仍不是 Round36 最终口径；
4. 预测列仍是 `power_pred_cal`，没有切到 `power_pred_final`；
5. 典型站点 JSON 仍是旧列表，或者导出脚本读取了旧 metrics。

本轮不需要重新训练，只修导出脚本和可视化 JSON。

## 二、目标

修复后页面顶部必须显示：

```text
数据版本：Round36
预测列：power_pred_final
默认不含 future
```

并且不再出现：

```text
警告：仍显示旧数据典型站点
```

Round36 典型站点应为：

```text
预测最好：S062, S023, S049, S047, S056
预测最差：S007, S063, S065, S041, S072
```

## 三、Cursor 执行步骤

### Step 1：先确认当前导出的 metadata

执行：

```bash
cat output/pv_pipeline/interactive_dashboard/metadata.json
```

重点看：

```text
source_file
prediction_column
round
typical_best_site_ids
typical_worst_site_ids
```

如果看到：

```text
prediction_column = power_pred_cal
```

说明导出脚本选错预测列。

### Step 2：确认 Round36 final pkl 是否含 `power_pred_final`

执行：

```bash
python - <<'PY'
import pickle
from pathlib import Path
p = Path("output/pv_pipeline/tables/distributed_predictions_final_round36.pkl")
with open(p, "rb") as f:
    df = pickle.load(f)
print("file:", p)
print("rows:", len(df))
print("columns:", list(df.columns))
for c in ["power_pred_final", "power_pred_cal", "pred_calibrated", "power_pred", "power_pred_raw"]:
    if c in df.columns:
        print(c, "exists", "non-null:", df[c].notna().sum())
PY
```

必须确认：

```text
power_pred_final exists
```

如果不存在，说明 Round36 final 文件没有正确生成，需要先重新运行：

```bash
python scripts/build_round36_predictions.py
python scripts/apply_round36_calibration.py
```

再继续。

### Step 3：强制导出脚本优先使用 `power_pred_final`

修改：

```text
scripts/export_interactive_dashboard_data.py
```

找到预测列解析逻辑。

必须改成：

```python
def resolve_dashboard_prediction_column(df):
    for col in ["power_pred_final", "pred_calibrated", "power_pred_cal", "power_pred"]:
        if col in df.columns:
            return col
    raise KeyError("未找到预测列：power_pred_final/pred_calibrated/power_pred_cal/power_pred")
```

然后导出时必须：

```python
pred_col = resolve_dashboard_prediction_column(df)
```

并在导出前加断言：

```python
if "power_pred_final" in df.columns and pred_col != "power_pred_final":
    raise RuntimeError(f"检测到 power_pred_final 存在，但导出脚本选择了 {pred_col}，请修复预测列优先级")
```

导出字段必须是：

```python
pred_mw = row[pred_col]
```

metadata 必须写：

```python
"prediction_column": pred_col
```

### Step 4：强制导出脚本读取 Round36 metrics，不允许回退旧 metrics

在 `export_interactive_dashboard_data.py` 中确认：

```python
ROUND_NAME = "Round36"
round_lower = "round36"
```

或者由 `distributed_predictions_final_round36.pkl` 自动解析得到。

然后读取：

```text
output/pv_pipeline/metrics/round36_site_metrics.csv
output/pv_pipeline/metrics/round36_typical_sites.csv
output/pv_pipeline/metrics/round36_city_hourly_nrmse.csv
output/pv_pipeline/metrics/round36_site_avg_hourly_nrmse.csv
output/pv_pipeline/metrics/round36_site_validity.csv
```

如果这些文件不存在，必须直接报错：

```python
raise FileNotFoundError(...)
```

禁止静默读取：

```text
round34_*
round35_*
旧 site_metrics.json
旧 typical_sites.json
```

### Step 5：强制检查典型站点来源

导出 `typical_sites.json` 后，立即读取校验。

在导出脚本末尾加入：

```python
expected_best = ["S062", "S023", "S049", "S047", "S056"]
expected_worst = ["S007", "S063", "S065", "S041", "S072"]

typical = pd.read_csv(METRICS / "round36_typical_sites.csv")
best = typical[typical["类型"] == "预测最好"]["site_id"].tolist()
worst = typical[typical["类型"] == "预测最差"]["site_id"].tolist()

if best != expected_best:
    raise RuntimeError(f"Round36 预测最好站点不匹配：当前 {best}, 期望 {expected_best}")
if worst != expected_worst:
    raise RuntimeError(f"Round36 预测最差站点不匹配：当前 {worst}, 期望 {expected_worst}")
```

如果实际 `round36_typical_sites.csv` 的顺序不同，但站点集合一致，也可以用集合判断：

```python
if set(best) != set(expected_best):
    ...
```

### Step 6：导出前彻底清理旧 JSON

导出前删除旧 JSON，但不要删 HTML：

```python
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "interactive_dashboard"
for p in OUT_DIR.rglob("*"):
    if p.is_file() and p.suffix.lower() in [".json", ".csv"]:
        p.unlink()
```

尤其要确保删除：

```text
output/pv_pipeline/interactive_dashboard/metadata.json
output/pv_pipeline/interactive_dashboard/index.json
output/pv_pipeline/interactive_dashboard/typical_sites.json
output/pv_pipeline/interactive_dashboard/site_metrics.json
output/pv_pipeline/interactive_dashboard/site_series/*.json
```

### Step 7：重新导出并检查 metadata

执行：

```bash
python scripts/export_interactive_dashboard_data.py
cat output/pv_pipeline/interactive_dashboard/metadata.json
```

必须看到：

```text
"round": "Round36"
"prediction_column": "power_pred_final"
```

同时必须看到或能推导出：

```text
typical_best_site_ids 包含 S062, S023, S049, S047, S056
typical_worst_site_ids 包含 S007, S063, S065, S041, S072
```

### Step 8：检查导出的 JSON 中是否还有旧典型站点

执行：

```bash
grep -R "S017\\|S012\\|S019\\|S045\\|S053\\|S115\\|median(capacity_sum_mw)" -n \
  output/pv_pipeline/interactive_dashboard \
  --include="*.json" --include="*.html" --include="*.js" | head -100
```

说明：

如果 S017 等只是作为普通站点出现在 `site_series/S017.json`，可以接受。  
但不能出现在：

```text
typical_sites.json
metadata.json 的 typical_best_site_ids / typical_worst_site_ids
页面旧数据警告判断结果
```

重点检查：

```bash
cat output/pv_pipeline/interactive_dashboard/typical_sites.json
```

### Step 9：修复 HTML 的旧数据警告逻辑

修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

旧数据检查逻辑不要硬编码旧列表误判。

建议逻辑：

```javascript
function checkDashboardVersion(metadata, typicalSites) {
  const best = typicalSites
    .filter(x => x["类型"] === "预测最好" || x.type === "预测最好")
    .map(x => x.site_id);
  const worst = typicalSites
    .filter(x => x["类型"] === "预测最差" || x.type === "预测最差")
    .map(x => x.site_id);

  const expectedBest = metadata.typical_best_site_ids || [];
  const expectedWorst = metadata.typical_worst_site_ids || [];

  const sameSet = (a, b) =>
    a.length === b.length && a.every(x => b.includes(x));

  if (metadata.round !== "Round36") {
    showWarning("当前页面数据版本不是 Round36，请重新导出可视化数据。");
    return;
  }
  if (metadata.prediction_column !== "power_pred_final") {
    showWarning(`当前预测列为 ${metadata.prediction_column}，不是 power_pred_final，请重新导出。`);
    return;
  }
  if (expectedBest.length && !sameSet(best, expectedBest)) {
    showWarning("当前页面典型站点与 metadata 不一致，请检查数据路径。");
    return;
  }
  if (expectedWorst.length && !sameSet(worst, expectedWorst)) {
    showWarning("当前页面典型站点与 metadata 不一致，请检查数据路径。");
    return;
  }
  hideWarning();
}
```

不要只要看到 `S017` 就报警，因为 S017 作为普通站点存在是正常的。

### Step 10：重新运行一致性检查

执行：

```bash
python scripts/check_dashboard_prediction_values_round36.py
python scripts/posttrain_validation_round36.py
```

要求：

```text
68/68 PASS
0 FAIL / 0 WARN
```

### Step 11：刷新页面

打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html?v=round39_2
```

强制刷新：

```text
Ctrl + Shift + R
```

页面顶部应显示：

```text
数据版本：Round36（power_pred_final | 生成时间... | 默认不含 future）
```

且不应再显示红色旧数据警告。

## 四、验收标准

Round39.2 通过必须满足：

1. 页面顶部显示 `power_pred_final`，不是 `power_pred_cal`。
2. 页面不再显示“仍显示旧数据典型站点”警告。
3. `metadata.json` 中：

```text
round = Round36
prediction_column = power_pred_final
```

4. `typical_sites.json` 中：

```text
预测最好 = S062, S023, S049, S047, S056
预测最差 = S007, S063, S065, S041, S072
```

5. `check_dashboard_prediction_values_round36.py` 全部 PASS。
6. `posttrain_validation_round36.py` 0 FAIL / 0 WARN。
7. 页面强制刷新后仍显示最新数据。

## 五、完成后回传

请回传：

```bash
cat output/pv_pipeline/interactive_dashboard/metadata.json
cat output/pv_pipeline/interactive_dashboard/typical_sites.json | head -80
python scripts/check_dashboard_prediction_values_round36.py
python scripts/posttrain_validation_round36.py
```

以及最新页面截图。
