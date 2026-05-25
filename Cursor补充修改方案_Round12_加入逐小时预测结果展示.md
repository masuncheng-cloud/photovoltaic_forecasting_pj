# Cursor 补充修改方案 Round12：加入逐小时预测结果展示

## 0. 修改目标

在当前交互式预测结果页面中新增一个模块：

```text
逐小时预测结果
```

展示字段：

```text
小时（时）
样本数（行）
站点平均 NRMSE（%）
城市 NRMSE（%）
```

要求：

1. 不重新训练模型。
2. 不修改 final/best 预测结果。
3. 不使用 WAPE、MAPE。
4. 指标口径与当前项目报告保持一致。
5. 页面展示时所有单元格居中，单位写清楚。

---

## 1. 数据来源

优先读取已有文件：

```text
output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv
```

该文件当前字段通常为：

```text
hour
rows
site_nrmse_mean_pct
city_nrmse_pct
```

如果该文件不存在，再回退到：

```text
output/pv_pipeline/metrics/round10_site_hour_nrmse.csv
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
```

但推荐优先使用 `分布式光伏预测_逐小时平均NRMSE.csv`，因为它已经是当前报告使用的逐小时口径。

---

## 2. 修改数据导出脚本

修改：

```text
scripts/export_interactive_dashboard_data.py
```

新增输出：

```text
output/pv_pipeline/interactive_dashboard/hourly_prediction_summary.json
```

### 2.1 新增函数

请新增函数：

```python
def export_hourly_prediction_summary(output_root: Path, dashboard_root: Path, final_df: pd.DataFrame) -> list[dict]:
    ...
```

### 2.2 优先读取已有逐小时 NRMSE 文件

逻辑：

```python
hourly_path = output_root / "metrics" / "分布式光伏预测_逐小时平均NRMSE.csv"

if hourly_path.exists():
    hourly = pd.read_csv(hourly_path)
else:
    hourly = compute_hourly_summary_from_final(final_df)
```

字段统一重命名为：

```text
hour
rows
site_nrmse_mean_pct
city_nrmse_pct
```

兼容字段名：

```python
rename_map = {
    "小时": "hour",
    "小时（时）": "hour",
    "样本数": "rows",
    "样本数（行）": "rows",
    "站点平均NRMSE（%）": "site_nrmse_mean_pct",
    "站点平均 NRMSE（%）": "site_nrmse_mean_pct",
    "城市NRMSE（%）": "city_nrmse_pct",
    "城市 NRMSE（%）": "city_nrmse_pct",
}
hourly = hourly.rename(columns={k: v for k, v in rename_map.items() if k in hourly.columns})
```

### 2.3 数据清洗

只保留 6-19 点：

```python
hourly = hourly[hourly["hour"].between(6, 19)].copy()
```

排序：

```python
hourly = hourly.sort_values("hour")
```

数值格式：

```python
hourly["hour"] = hourly["hour"].astype(int)
hourly["rows"] = hourly["rows"].astype(int)
hourly["site_nrmse_mean_pct"] = hourly["site_nrmse_mean_pct"].astype(float).round(2)
hourly["city_nrmse_pct"] = hourly["city_nrmse_pct"].astype(float).round(3)
```

输出 JSON：

```python
records = hourly[[
    "hour",
    "rows",
    "site_nrmse_mean_pct",
    "city_nrmse_pct",
]].to_dict(orient="records")

(dashboard_root / "hourly_prediction_summary.json").write_text(
    json.dumps(records, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
```

### 2.4 回退计算函数

如果逐小时 CSV 不存在，则从 final eval 重新计算。

新增：

```python
def compute_hourly_summary_from_final(df: pd.DataFrame) -> pd.DataFrame:
    ...
```

计算口径：

```python
eval_df = df.copy()
eval_df["time"] = pd.to_datetime(eval_df["time"])
eval_df["hour"] = eval_df["time"].dt.hour
eval_df = eval_df[
    (eval_df["split"].eq("test")) &
    (eval_df["hour"].between(6, 19)) &
    eval_df["power_mw"].notna() &
    eval_df["power_pred"].notna()
].copy()
```

逐小时站点平均 NRMSE：

```python
site_rows = []
for (hour, site_id), g in eval_df.groupby(["hour", "site_id"]):
    y = g["power_mw"].astype(float).to_numpy()
    p = g["power_pred"].astype(float).to_numpy()
    c = max(float(g["capacity_mw"].mean()), 1e-9)
    rmse = float(np.sqrt(np.mean((p - y) ** 2)))
    site_rows.append({
        "hour": int(hour),
        "site_id": site_id,
        "site_nrmse_pct": rmse / c * 100,
    })

site_hour = pd.DataFrame(site_rows)
site_avg = site_hour.groupby("hour")["site_nrmse_pct"].mean().reset_index()
site_avg = site_avg.rename(columns={"site_nrmse_pct": "site_nrmse_mean_pct"})
```

城市 NRMSE 回退计算：

为了与当前报告保持一致，优先使用已有 CSV；只有 CSV 缺失时才使用以下近似口径：

```python
city_rows = []
for hour, g in eval_df.groupby("hour"):
    city_by_time = g.groupby("time").agg(
        actual=("power_mw", "sum"),
        pred=("power_pred", "sum"),
        capacity=("capacity_mw", "sum"),
    ).reset_index()
    y = city_by_time["actual"].astype(float).to_numpy()
    p = city_by_time["pred"].astype(float).to_numpy()
    c = max(float(city_by_time["capacity"].mean()), 1e-9)
    rmse = float(np.sqrt(np.mean((p - y) ** 2)))
    city_rows.append({
        "hour": int(hour),
        "city_nrmse_pct": rmse / c * 100,
    })

city_hour = pd.DataFrame(city_rows)
```

样本数：

```python
rows_hour = eval_df.groupby("hour").size().reset_index(name="rows")
```

合并：

```python
hourly = rows_hour.merge(site_avg, on="hour", how="left").merge(city_hour, on="hour", how="left")
```

注意：如果已有 CSV 存在，必须使用已有 CSV，不要用回退计算覆盖。

### 2.5 写入 index.json

在 `index.json` 中新增：

```json
{
  "hourly_prediction_summary": "hourly_prediction_summary.json"
}
```

### 2.6 控制台输出

脚本运行结束时增加：

```text
hourly_prediction_summary=14
```

表示 6-19 点共 14 行。

---

## 3. 修改 HTML 页面

修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

### 3.1 新增全局变量

```javascript
let gHourlySummary = [];
```

### 3.2 页面加载时读取 JSON

在初始化数据加载逻辑中新增：

```javascript
gHourlySummary = await fetchJson(`${DATA_ROOT}/hourly_prediction_summary.json`);
```

如果读取失败：

```javascript
gHourlySummary = [];
console.warn("hourly_prediction_summary.json not found");
```

### 3.3 新增页面模块

建议放在：

```text
折线图模块之后、散点图模块之前
```

新增 HTML 结构：

```html
<section class="panel hourly-panel">
  <div class="panel-header">
    <div>
      <h2>逐小时预测结果</h2>
      <p>测试集 6-19 点逐小时样本量、站点平均 NRMSE 与城市 NRMSE。</p>
    </div>
  </div>

  <div class="hourly-grid">
    <div class="chart-wrap">
      <svg id="hourlyNrmseChart"></svg>
    </div>
    <div class="table-wrap">
      <table id="hourlySummaryTable">
        <thead>
          <tr>
            <th>小时（时）</th>
            <th>样本数（行）</th>
            <th>站点平均 NRMSE（%）</th>
            <th>城市 NRMSE（%）</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

  <p class="note">
    说明：站点平均 NRMSE 表示每个站点分别计算 NRMSE 后再按小时取平均；城市 NRMSE 表示全市聚合功率在该小时的误差水平。该表使用测试集 6-19 点数据。
  </p>
</section>
```

### 3.4 表格渲染函数

新增：

```javascript
function renderHourlySummaryTable() {
  const tbody = document.querySelector("#hourlySummaryTable tbody");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (!gHourlySummary || !gHourlySummary.length) {
    tbody.innerHTML = `<tr><td colspan="4">暂无逐小时预测结果数据</td></tr>`;
    return;
  }

  for (const row of gHourlySummary) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.hour}</td>
      <td>${formatInt(row.rows)}</td>
      <td>${formatNumber(row.site_nrmse_mean_pct, 2)}%</td>
      <td>${formatNumber(row.city_nrmse_pct, 3)}%</td>
    `;
    tbody.appendChild(tr);
  }
}
```

如果页面已有 `formatInt` / `formatNumber`，直接复用；如果没有，新增：

```javascript
function formatInt(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "-";
  return Math.round(Number(v)).toLocaleString("zh-CN");
}

function formatNumber(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "-";
  return Number(v).toFixed(digits);
}
```

### 3.5 图表渲染函数

新增：

```javascript
function drawHourlyNrmseChart() {
  const svg = document.getElementById("hourlyNrmseChart");
  if (!svg) return;
  svg.innerHTML = "";

  const data = gHourlySummary || [];
  if (!data.length) {
    svg.innerHTML = `<text x="20" y="40" fill="#64748b">暂无逐小时数据</text>`;
    return;
  }

  // 使用已有 SVG 绘图风格实现即可。
  // 横轴：hour
  // 左纵轴：NRMSE %
  // 两条折线：
  // 1. 站点平均 NRMSE（%）
  // 2. 城市 NRMSE（%）
}
```

如果页面已有通用折线图函数，可以直接复用，传入：

```javascript
[
  { key: "site_nrmse_mean_pct", label: "站点平均 NRMSE（%）", color: "#2563eb" },
  { key: "city_nrmse_pct", label: "城市 NRMSE（%）", color: "#f97316" }
]
```

图表要求：

```text
横轴：小时（6-19）
纵轴：NRMSE（%）
蓝线：站点平均 NRMSE
橙线：城市 NRMSE
tooltip：小时、样本数、站点平均 NRMSE、城市 NRMSE
```

### 3.6 初始化调用

在页面初始化和刷新逻辑中加入：

```javascript
renderHourlySummaryTable();
drawHourlyNrmseChart();
```

在窗口 resize 时加入：

```javascript
drawHourlyNrmseChart();
```

### 3.7 样式要求

新增或复用样式：

```css
.hourly-grid {
  display: grid;
  grid-template-columns: minmax(360px, 1.2fr) minmax(360px, 1fr);
  gap: 16px;
  align-items: stretch;
}

#hourlyNrmseChart {
  width: 100%;
  height: 320px;
}

#hourlySummaryTable th,
#hourlySummaryTable td {
  text-align: center;
  vertical-align: middle;
  white-space: nowrap;
}

@media (max-width: 900px) {
  .hourly-grid {
    grid-template-columns: 1fr;
  }
}
```

---

## 4. 更新 README

修改：

```text
stages/05_visualization/README.md
```

在交互式页面说明里补充：

```markdown
页面还包含“逐小时预测结果”模块，展示测试集 6-19 点的样本数、站点平均 NRMSE 和城市 NRMSE，并用折线图对比站点级误差与城市级误差。
```

---

## 5. 验收命令

重新导出数据：

```bash
python scripts/export_interactive_dashboard_data.py \
  --output-root output/pv_pipeline \
  --dashboard-root output/pv_pipeline/interactive_dashboard
```

检查新增 JSON：

```bash
python - <<'PY'
import json
from pathlib import Path

p = Path("output/pv_pipeline/interactive_dashboard/hourly_prediction_summary.json")
assert p.exists(), "hourly_prediction_summary.json 不存在"
data = json.loads(p.read_text(encoding="utf-8"))
assert len(data) == 14, f"逐小时数据应为 6-19 点共 14 行，实际 {len(data)} 行"
for row in data:
    for k in ["hour", "rows", "site_nrmse_mean_pct", "city_nrmse_pct"]:
        assert k in row, f"缺少字段 {k}"
    assert 6 <= int(row["hour"]) <= 19
print("[OK] hourly prediction summary:", len(data), "rows")
PY
```

启动页面：

```bash
python -m http.server 8060
```

浏览器打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

---

## 6. 页面验收标准

页面中必须出现模块：

```text
逐小时预测结果
```

表格列必须是：

```text
小时（时）
样本数（行）
站点平均 NRMSE（%）
城市 NRMSE（%）
```

检查要求：

1. 表格显示 6-19 点共 14 行。
2. 每个单元格居中。
3. NRMSE 均带 `%`。
4. 样本数带千分位分隔。
5. 折线图能同时展示站点平均 NRMSE 与城市 NRMSE。
6. 页面原有功能不受影响：
   - 全市/单站点折线图正常；
   - 典型站点表正常；
   - 单站点样本量 vs 测试 NRMSE 散点图正常；
   - 样本量阈值表正常。

---

## 7. 不允许修改

本轮不要修改以下文件内容：

```text
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
output/pv_pipeline/tables/best_predictions_eval.pkl
output/pv_pipeline/tables/best_predictions_full.pkl
```

不要重新训练模型。

不要将逐小时页面展示结果反向写入模型选择逻辑。

