# Cursor 修改方案 Round23：可视化排除 future，并剔除 0 值占比 100% 站点统计

## 一、修改目标

当前可视化页面中：

1. `full_history_rows`、`full_history_zero_ratio_pct` 等“全量历史样本”口径可能包含 `future` 行。
2. 0 值占比 100%、正功率样本数为 0 的站点仍出现在样本量-NRMSE 散点图和阈值统计中，容易误导为“无训练数据也能计算正常预测精度”。
3. 部分站点级指标使用了 `train + valid + test`，不利于和“测试集 NRMSE”口径统一。

本轮目标：

- 可视化页面展示数据不再包含 `future`。
- 样本量统计只使用历史可观测数据：`train + valid + test`。
- 站点 NRMSE、MAE、RMSE 只使用 `test` 集 6-19 点。
- `full_history_positive_rows == 0` 或 `full_history_zero_ratio_pct >= 100%` 的站点不参与普通散点图、阈值统计、样本量分箱统计。
- 全 0 站点单独导出到异常列表，页面单独说明。
- 不重新训练模型，不修改预测 pkl，只重新生成可视化 JSON。

## 二、涉及文件

主要修改：

```text
scripts/export_interactive_dashboard_data.py
stages/05_visualization/interactive_forecast_dashboard.html
```

如页面 JS/CSS 已拆分，则同步修改：

```text
stages/05_visualization/*.js
stages/05_visualization/*.css
```

## 三、统一可视化数据口径

在 `scripts/export_interactive_dashboard_data.py` 中新增公共过滤函数。

```python
HISTORY_SPLITS = ["train", "valid", "test"]
EVAL_SPLIT = "test"
EVAL_HOURS = list(range(6, 20))


def build_history_frame(df: pd.DataFrame) -> pd.DataFrame:
    """可视化历史展示口径：只保留 train/valid/test，不包含 future。"""
    out = df[df["split"].isin(HISTORY_SPLITS)].copy()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour
    if "date" not in out.columns:
        out["date"] = out["time"].dt.strftime("%Y-%m-%d")
    return out


def build_eval_frame_for_dashboard(df: pd.DataFrame) -> pd.DataFrame:
    """可视化评估口径：只用 test 集 6-19 点，有真实值和预测值。"""
    out = build_history_frame(df)
    out = out[
        out["split"].eq(EVAL_SPLIT)
        & out["hour"].isin(EVAL_HOURS)
        & out["power_mw"].notna()
        & out["power_pred"].notna()
        & out["capacity_mw"].notna()
        & (out["capacity_mw"] > 0)
    ].copy()
    return out
```

要求：

- 所有用于页面展示的时间序列、站点指标、散点图、阈值统计，都优先调用这两个函数。
- 除了明确说明的“模型未来预测展示”功能外，当前页面不要使用 `future`。
- 本项目当前页面没有必要展示 `future`，因此一律排除。

## 四、修改 `export_index`

当前 `index.json` 的日期范围不要再从完整 `df` 取，应从 `history_df` 取。

修改为：

```python
def export_index(df, site_names, dashboard_root):
    history_df = build_history_frame(df)
    dates = pd.to_datetime(history_df["date"]).dropna().unique()
    min_date = pd.to_datetime(dates).min().strftime("%Y-%m-%d")
    max_date = pd.to_datetime(dates).max().strftime("%Y-%m-%d")

    index_data = {
        "title": "光伏功率预测交互式结果页面",
        "description": "展示连云港光伏电站真实功率与预测功率对比",
        "data_scope": "train/valid/test only; future excluded",
        "min_date": min_date,
        "max_date": max_date,
        "default_start_date": min_date,
        "default_end_date": max_date,
        "total_rows": int(len(history_df)),
        "total_sites": int(history_df["site_id"].nunique()),
        "date_range": f"{min_date} ~ {max_date}",
        "hourly_prediction_summary": "hourly_prediction_summary.json",
        "invalid_zero_sites": "invalid_zero_sites.json",
    }
```

验收：

- `index.json` 的最大日期不应超过 `2025-12-31`。
- 不应再显示到 `2026-03-31`。

## 五、修改城市和站点时间序列导出

### 5.1 `export_city_series`

将原来的：

```python
df_f = df[
    df["split"].isin(["train", "valid", "test"])
    & df["hour"].between(6, 19)
    ...
]
```

改成：

```python
df_f = build_history_frame(df)
df_f = df_f[
    df_f["hour"].between(6, 19)
    & df_f["power_mw"].notna()
    & df_f["power_pred"].notna()
].copy()
```

这样仍展示 train/valid/test 的历史曲线，但不包含 future。

### 5.2 `export_site_series`

同样改成：

```python
df_f = build_history_frame(df)
df_f = df_f[
    df_f["hour"].between(6, 19)
    & df_f["power_mw"].notna()
    & df_f["power_pred"].notna()
].copy()
```

验收：

- `city_series.json` 不含 `split == "future"`。
- `site_series/*.json` 不含 `split == "future"`。
- 页面日期选择的最大日期不超过 `2025-12-31`。

## 六、修改站点指标 `export_site_metrics`

### 6.1 历史样本统计排除 future

将：

```python
full_df = df.copy()
```

改成：

```python
full_df = build_history_frame(df)
```

字段名建议同步调整，避免“full history”让人误解包含 future：

保留兼容字段：

```python
full_history_rows
full_history_positive_rows
full_history_zero_rows
full_history_zero_ratio_pct
```

但页面说明中解释为：

```text
历史样本数 = train + valid + test，不包含 future。
```

### 6.2 MAE/RMSE/NRMSE 改为纯 test

当前 `export_site_metrics` 中站点指标使用了：

```python
df["split"].isin(["train", "valid", "test"])
```

必须改为：

```python
df_f = build_eval_frame_for_dashboard(df)
```

然后用 `df_f` 计算：

```python
rows
positive_rows
zero_rows
zero_ratio_pct
mae_mw
rmse_mw
nrmse_pct
bias_pct
pred_actual_ratio
```

这些字段都必须表示：

```text
测试集 6-19 点
```

不是 train/valid/test 混合。

### 6.3 全 0 站点不参与典型分类

新增有效站点判断：

```python
metrics_df["is_all_zero_history"] = (
    (metrics_df["full_history_positive_rows"].fillna(0) <= 0)
    | (metrics_df["full_history_zero_ratio_pct"].fillna(0) >= 99.999)
)

valid_metrics_df = metrics_df[~metrics_df["is_all_zero_history"]].copy()
```

典型分类必须基于 `valid_metrics_df`：

```python
best_candidates = valid_metrics_df[
    (valid_metrics_df["rows"] >= min_rows)
    & (valid_metrics_df["positive_rows"] >= 100)
].copy()
```

全 0 站点的 `category_label` 统一设为：

```text
无有效发电样本
```

示例：

```python
metrics_df.loc[metrics_df["is_all_zero_history"], "category"] = "invalid_zero"
metrics_df.loc[metrics_df["is_all_zero_history"], "category_label"] = "无有效发电样本"
```

## 七、新增 `invalid_zero_sites.json`

在 `export_interactive_dashboard_data.py` 新增函数：

```python
def export_invalid_zero_sites(metrics_df, dashboard_root):
    invalid = metrics_df[
        (metrics_df["full_history_positive_rows"].fillna(0) <= 0)
        | (metrics_df["full_history_zero_ratio_pct"].fillna(0) >= 99.999)
    ].copy()

    cols = [
        "site_id", "site_name", "county", "capacity_mw",
        "full_history_rows", "full_history_positive_rows",
        "full_history_zero_rows", "full_history_zero_ratio_pct",
        "full_history_start_date", "full_history_end_date",
        "test_rows", "test_positive_rows",
        "test_mae_mw", "test_rmse_mw", "test_nrmse_pct",
        "test_pred_actual_ratio",
    ]
    cols = [c for c in cols if c in invalid.columns]

    records = invalid[cols].to_dict(orient="records")
    out_path = Path(dashboard_root) / "invalid_zero_sites.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  [OK] invalid_zero_sites.json ({len(records)} sites)")
    return records
```

在 `main()` 中，在 `metrics_df = export_site_metrics(...)` 后调用：

```python
invalid_zero_sites = export_invalid_zero_sites(metrics_df, dashboard_root)
```

并在 validation 中加：

```python
assert invalid_zero_sites is not None
```

## 八、修改散点图导出 `export_scatter_site_sample_nrmse`

### 8.1 历史样本统计排除 future

将：

```python
full_hist = df.copy()
```

改成：

```python
full_hist = build_history_frame(df)
```

### 8.2 测试 NRMSE 保持 test 6-19

保留或改成：

```python
test_eval = build_eval_frame_for_dashboard(df)
```

### 8.3 合并后剔除全 0 站点

在 `merged` 生成后加入：

```python
merged["is_all_zero_history"] = (
    (merged["full_history_positive_rows"].fillna(0) <= 0)
    | (merged["full_history_zero_ratio_pct"].fillna(0) >= 99.999)
)

invalid_merged = merged[merged["is_all_zero_history"]].copy()
merged = merged[~merged["is_all_zero_history"]].copy()
```

`scatter_site_sample_nrmse.json` 只写 `merged`，不写全 0 站点。

要求：

- S069 这类全 0 站点不得出现在样本量-NRMSE 散点图中。
- S069 可以出现在 `invalid_zero_sites.json`。

## 九、修改样本量阈值统计

`export_sample_requirement_summary(scatter_data, dashboard_root)` 和 `export_sample_requirement_bins(scatter_data, dashboard_root)` 已经使用 `scatter_data`。

只要上一节剔除了全 0 站点，这两个统计就自然不会包含全 0 站点。

同时修改 `note` 文案：

```python
notes_base = (
    "经验估计：在当前数据和当前模型下，达到指定NRMSE阈值的站点通常具备的历史样本量分布。"
    "历史样本量仅包含train/valid/test，不包含future；"
    "0值占比100%或无正功率样本的站点已从统计中剔除。"
    "样本量不是唯一决定因素，容量、站点映射、异常0值、限电、遮挡和气象插值都会影响最终NRMSE。"
)
```

## 十、修改前端页面说明

在 `interactive_forecast_dashboard.html` 中，将散点图说明改为：

```text
本图每个点代表一个具备有效发电样本的站点。
横轴为该站点历史样本数（train/valid/test，不包含 future），纵轴为测试集 6-19 点 NRMSE。
0 值占比 100% 或无正功率样本的站点不参与本图统计，单独列入“无有效发电样本站点”。
```

样本量阈值表下方说明改为：

```text
这里统计的是已达到不同 NRMSE 阈值的有效发电站点的历史样本量分布；
历史样本量不包含 future；无正功率样本或 0 值占比 100% 的站点已剔除。
```

## 十一、前端新增“无有效发电样本站点”展示

页面加载时新增读取：

```js
const invalidZeroSites = await fetchJson(`${DATA_ROOT}/invalid_zero_sites.json`);
```

新增一个小表格或折叠区：

```html
<section class="panel">
  <h3>无有效发电样本站点</h3>
  <p class="hint-text">
    以下站点历史功率几乎全为0，不参与样本量-NRMSE关系统计和阈值统计。
  </p>
  <div id="invalid-zero-sites-table"></div>
</section>
```

JS 渲染：

```js
function renderInvalidZeroSites(rows) {
  const el = document.getElementById("invalid-zero-sites-table");
  if (!el) return;

  if (!rows || !rows.length) {
    el.innerHTML = '<div class="empty-note">暂无无有效发电样本站点</div>';
    return;
  }

  const html = `
    <table class="metric-table compact-table">
      <thead>
        <tr>
          <th>站点ID</th>
          <th>站点名称</th>
          <th>容量（MW）</th>
          <th>历史样本数（行）</th>
          <th>正功率样本数（行）</th>
          <th>0值占比（%）</th>
          <th>说明</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(r => `
          <tr>
            <td>${r.site_id ?? "-"}</td>
            <td>${r.site_name ?? "-"}</td>
            <td>${formatNumber(r.capacity_mw, 2)}</td>
            <td>${formatInteger(r.full_history_rows)}</td>
            <td>${formatInteger(r.full_history_positive_rows)}</td>
            <td>${formatNumber(r.full_history_zero_ratio_pct, 2)}</td>
            <td>无有效正功率样本，不参与正常精度统计</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;

  el.innerHTML = html;
}
```

页面初始化后调用：

```js
renderInvalidZeroSites(invalidZeroSites);
```

## 十二、修正 tooltip 中的异常 ratio

如果 `actual_sum` 近似 0，`pred/actual` 不要显示巨大数字。

前端格式化函数：

```js
function formatRatio(v) {
  const x = Number(v);
  if (!Number.isFinite(x) || Math.abs(x) > 99) return "-";
  return x.toFixed(2);
}
```

tooltip 中：

```js
pred/actual: ${formatRatio(d.test_pred_actual_ratio)}
```

## 十三、重新生成可视化 JSON

在 Cursor 终端执行：

```bash
cd /path/to/photovoltaic_forecasting_pj
python scripts/export_interactive_dashboard_data.py \
  --output-root output/pv_pipeline \
  --dashboard-root output/pv_pipeline/interactive_dashboard
```

不要重新训练。

## 十四、验证脚本

在 Cursor 中临时运行以下检查：

```bash
python - <<'PY'
import json
from pathlib import Path

root = Path("output/pv_pipeline/interactive_dashboard")

def load(name):
    with open(root / name, encoding="utf-8") as f:
        return json.load(f)

index = load("index.json")
city = load("city_series.json")
scatter = load("scatter_site_sample_nrmse.json")
sample_summary = load("sample_requirement_summary.json")
invalid = load("invalid_zero_sites.json")

print("index date:", index.get("min_date"), index.get("max_date"))
assert index.get("max_date") <= "2025-12-31", "index max_date still includes future"

assert all(r.get("split") != "future" for r in city), "city_series contains future"

bad_scatter = [
    r for r in scatter
    if (r.get("full_history_positive_rows") or 0) <= 0
    or (r.get("full_history_zero_ratio_pct") or 0) >= 99.999
]
assert not bad_scatter, f"scatter contains all-zero sites: {[r.get('site_id') for r in bad_scatter]}"

assert isinstance(invalid, list), "invalid_zero_sites.json not valid"
print("invalid_zero_sites:", len(invalid))

for row in sample_summary:
    note = row.get("note", "")
    assert "不包含future" in note or "不包含 future" in note, "sample summary note missing future exclusion"

print("[OK] Round23 visualization data checks passed")
PY
```

## 十五、页面验收

启动网页：

```bash
cd /path/to/photovoltaic_forecasting_pj
python -m http.server 8060
```

打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

逐项确认：

1. 日期选择最大日期不超过 `2025-12-31`。
2. 折线图不展示 `future` 数据。
3. 样本量-NRMSE 散点图中不再出现 0 值占比 100%、正功率样本数 0 的站点。
4. S069 这类站点出现在“无有效发电样本站点”列表，而不是普通散点图。
5. 阈值表“达到 10%、15%、20% NRMSE 的样本量分布”不包含全 0 站点。
6. tooltip 中 `pred/actual` 如果实际值为 0，不显示巨大异常数字，而显示 `-`。
7. 页面说明明确写出：历史样本不包含 `future`，测试 NRMSE 只使用 test 6-19 点。

## 十六、验收标准

本轮修改通过标准：

- 可视化页面不展示 `future`。
- 可视化样本量统计不包含 `future`。
- 正式误差指标只使用 `test` 集 6-19 点。
- 0 值占比 100% 或正功率样本数为 0 的站点不参与普通统计。
- 全 0 站点有单独列表和说明。
- 页面可以正常启动，折线图、散点图、阈值表、逐小时表均正常显示。
- 不重新训练，不修改模型结果 pkl。

