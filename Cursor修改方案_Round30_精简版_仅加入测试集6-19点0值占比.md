# Cursor 修改方案 Round30 精简版：仅加入测试集 6-19 点 0 值占比

## 一、修改目标

本轮只做三个改动：

1. 在“典型站点”表中只新增一列：

```text
测试集6-19点0值占比%
```

2. 在“单站点全量历史样本数与测试集 NRMSE 关系”散点图中，横轴口径只保留：

```text
全量历史样本数
```

去掉或隐藏：

```text
训练+验证总样本数
训练+验证正功率样本数
```

3. 在每个站点的信息卡片 / tooltip 中加入：

```text
测试集6-19点0值占比
```

不要新增 `6-19点0值占比`、`训练+验证6-19点0值占比` 等其他字段到前端展示。

本轮不重新训练模型，只重新导出 dashboard JSON 和 metrics。

## 二、涉及文件

主要修改：

```text
scripts/export_interactive_dashboard_data.py
stages/05_visualization/interactive_forecast_dashboard.html
```

输出文件：

```text
output/pv_pipeline/metrics/site_test_daytime_zero_ratio_summary.csv
output/pv_pipeline/interactive_dashboard/site_metrics.json
output/pv_pipeline/interactive_dashboard/scatter_site_sample_nrmse.json
```

## 三、后端新增测试集 6-19 点 0 值占比

在 `scripts/export_interactive_dashboard_data.py` 中新增函数：

```python
def compute_site_test_daytime_zero_stats(df: pd.DataFrame) -> pd.DataFrame:
    """计算站点级测试集 6-19 点 0值占比。

    统计口径：
    - split == test
    - hour in 6..19
    - power_mw notna
    """
    out = df.copy()

    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], errors="coerce")

    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour

    out = out[
        out["split"].eq("test")
        & out["hour"].between(6, 19)
        & out["power_mw"].notna()
    ].copy()

    if out.empty:
        return pd.DataFrame(columns=[
            "site_id",
            "test_daytime_rows_6_19",
            "test_daytime_positive_rows_6_19",
            "test_daytime_zero_rows_6_19",
            "test_daytime_zero_ratio_6_19_pct",
        ])

    stats = out.groupby("site_id").agg(
        test_daytime_rows_6_19=("power_mw", "size"),
        test_daytime_positive_rows_6_19=("power_mw", lambda s: int((s.fillna(0) > 0).sum())),
        test_daytime_zero_rows_6_19=("power_mw", lambda s: int((s.fillna(0) == 0).sum())),
    ).reset_index()

    stats["test_daytime_zero_ratio_6_19_pct"] = (
        stats["test_daytime_zero_rows_6_19"]
        / stats["test_daytime_rows_6_19"].clip(lower=1)
        * 100
    ).round(4)

    return stats
```

## 四、导出 CSV

在 `main()` 中加载 `df` 后、导出 `site_metrics` 前增加：

```python
print("\n[2b] Computing test 6-19 zero ratio stats...")
test_daytime_zero_stats = compute_site_test_daytime_zero_stats(df)
metrics_path = Path(output_root) / "metrics" / "site_test_daytime_zero_ratio_summary.csv"
metrics_path.parent.mkdir(parents=True, exist_ok=True)
test_daytime_zero_stats.to_csv(metrics_path, index=False, encoding="utf-8-sig")
print(f"  [OK] site_test_daytime_zero_ratio_summary.csv ({len(test_daytime_zero_stats)} sites)")
```

## 五、合并到 `site_metrics.json`

修改 `export_site_metrics` 函数签名：

```python
def export_site_metrics(df, site_names, dashboard_root, test_daytime_zero_stats=None):
```

在 `metrics_df` 生成后合并：

```python
if test_daytime_zero_stats is not None and not test_daytime_zero_stats.empty:
    metrics_df = metrics_df.merge(test_daytime_zero_stats, on="site_id", how="left")
```

填充空值：

```python
for c in [
    "test_daytime_rows_6_19",
    "test_daytime_positive_rows_6_19",
    "test_daytime_zero_rows_6_19",
]:
    if c in metrics_df.columns:
        metrics_df[c] = metrics_df[c].fillna(0).astype(int)

if "test_daytime_zero_ratio_6_19_pct" in metrics_df.columns:
    metrics_df["test_daytime_zero_ratio_6_19_pct"] = (
        metrics_df["test_daytime_zero_ratio_6_19_pct"].fillna(0).round(4)
    )
```

在 `out_cols` 中只加入以下字段：

```python
"test_daytime_rows_6_19",
"test_daytime_positive_rows_6_19",
"test_daytime_zero_rows_6_19",
"test_daytime_zero_ratio_6_19_pct",
```

调用处改为：

```python
metrics_df = export_site_metrics(df, site_names, dashboard_root, test_daytime_zero_stats)
```

## 六、合并到 `scatter_site_sample_nrmse.json`

修改 `export_scatter_site_sample_nrmse` 函数签名：

```python
def export_scatter_site_sample_nrmse(
    df, site_names, sm_df, metrics_df, dashboard_root, test_daytime_zero_stats=None
):
```

在 `merged` 生成后合并：

```python
if test_daytime_zero_stats is not None and not test_daytime_zero_stats.empty:
    merged = merged.merge(test_daytime_zero_stats, on="site_id", how="left")
```

填充空值：

```python
for c in [
    "test_daytime_rows_6_19",
    "test_daytime_positive_rows_6_19",
    "test_daytime_zero_rows_6_19",
]:
    if c in merged.columns:
        merged[c] = merged[c].fillna(0).astype(int)

if "test_daytime_zero_ratio_6_19_pct" in merged.columns:
    merged["test_daytime_zero_ratio_6_19_pct"] = (
        merged["test_daytime_zero_ratio_6_19_pct"].fillna(0).round(4)
    )
```

调用处改为：

```python
scatter_site = export_scatter_site_sample_nrmse(
    df, site_names, sm_df, metrics_df, dashboard_root, test_daytime_zero_stats
)
```

## 七、前端：典型站点表只新增一列

在 `interactive_forecast_dashboard.html` 中找到“典型站点”表。

表头新增一列，放在 `全量0值占比%` 后、`MAE MW` 前：

```html
<th>测试集6-19点0值占比%</th>
```

行数据新增：

```js
<td>${fmt2(s.test_daytime_zero_ratio_6_19_pct || 0)}</td>
```

不要在表中加入：

```text
6-19点0值占比
训练+验证6-19点0值占比
```

## 八、前端：站点信息卡片 / tooltip 新增一项

在散点图 tooltip 中，当前已有类似：

```text
全量0值占比
测试集站点 NRMSE
测试 MAE
测试 RMSE
```

只新增：

```js
<div class="tip-label">测试集6-19点0值占比</div>
<div class="tip-val">${fmt2(p.test_daytime_zero_ratio_6_19_pct || 0)}%</div>
```

建议放在：

```text
全量0值占比
```

后面。

如果页面还有单站点信息卡片，也同步加入：

```js
测试集6-19点0值占比：xx%
```

## 九、前端：散点图横轴只保留“全量历史样本数”

在“单站点全量历史样本数与测试集 NRMSE 关系”区域，当前有三个横轴按钮：

```text
全量历史样本数
训练+验证总样本数
训练+验证正功率样本数
```

修改为只保留：

```text
全量历史样本数
```

HTML 中删除或隐藏另外两个按钮：

```html
<!-- 删除或注释 -->
<button data-x-field="train_valid_rows">训练+验证总样本数</button>
<button data-x-field="train_valid_positive_rows">训练+验证正功率样本数</button>
```

保留：

```html
<button data-x-field="full_history_rows" class="active">全量历史样本数</button>
```

JS 中固定：

```js
state.scatterXField = "full_history_rows";
```

如果有 `xFieldButtons` 事件绑定，保留也可以，但页面只剩一个按钮。

如果有横轴 label 映射：

```js
const xAxisLabels = {
  full_history_rows: "单站点全量历史样本数（行）",
};
```

删除或不再使用：

```js
train_valid_rows
train_valid_positive_rows
```

## 十、前端说明更新

将散点图说明改为：

```text
本图每个点代表一个具备有效发电样本的站点。横轴为该站点历史样本数（train/valid/test，不包含 future），纵轴为测试集 6-19 点 NRMSE。全量 0 值占比包含夜间正常 0 值；测试集 6-19 点 0 值占比更适合解释最终测试误差是否受白天 0 值影响。
```

阈值表说明改为：

```text
这里统计的是达到不同 NRMSE 阈值的有效发电站点的全量历史样本量分布；需结合测试集 6-19 点 0 值占比、容量、站点映射和气象匹配共同判断。
```

典型站点表说明改为：

```text
历史样本数 = train + valid + test，不包含 future；MAE、RMSE、NRMSE、pred/actual 与测试集6-19点0值占比均按测试集 6-19 点计算。
```

## 十一、重新生成可视化数据

执行：

```bash
cd /path/to/photovoltaic_forecasting_pj
python scripts/export_interactive_dashboard_data.py \
  --output-root output/pv_pipeline \
  --dashboard-root output/pv_pipeline/interactive_dashboard
```

不需要重新训练。

## 十二、验证脚本

执行：

```bash
python - <<'PY'
import json
import pandas as pd
from pathlib import Path

root = Path("output/pv_pipeline")
csv_path = root / "metrics" / "site_test_daytime_zero_ratio_summary.csv"
assert csv_path.exists(), "missing site_test_daytime_zero_ratio_summary.csv"

df = pd.read_csv(csv_path)
required = [
    "site_id",
    "test_daytime_rows_6_19",
    "test_daytime_positive_rows_6_19",
    "test_daytime_zero_rows_6_19",
    "test_daytime_zero_ratio_6_19_pct",
]
for c in required:
    assert c in df.columns, f"missing {c}"

dash = root / "interactive_dashboard"
site_metrics = json.loads((dash / "site_metrics.json").read_text(encoding="utf-8"))
scatter = json.loads((dash / "scatter_site_sample_nrmse.json").read_text(encoding="utf-8"))

for name, rows in [("site_metrics", site_metrics), ("scatter", scatter)]:
    assert rows, f"{name} empty"
    assert "test_daytime_zero_ratio_6_19_pct" in rows[0], f"{name} missing test_daytime_zero_ratio_6_19_pct"

print("[OK] test 6-19 zero ratio exported")
print(df[required].head().to_string(index=False))
PY
```

## 十三、页面验收

启动：

```bash
cd /path/to/photovoltaic_forecasting_pj
python3 -m http.server 8060
```

打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

强制刷新：

```text
Ctrl + Shift + R
```

验收：

1. “典型站点”表只新增了：

```text
测试集6-19点0值占比%
```

2. “典型站点”表中没有新增：

```text
6-19点0值占比
训练+验证6-19点0值占比
```

3. “单站点全量历史样本数与测试集 NRMSE 关系”横轴按钮只剩：

```text
全量历史样本数
```

4. 散点图每个站点 tooltip / 信息卡片中包含：

```text
测试集6-19点0值占比
```

5. 页面说明已明确：

```text
全量0值占比包含夜间，测试集6-19点0值占比更适合解释最终测试误差。
```

## 十四、验收标准

本轮通过标准：

- 后端只新增测试集 6-19 点 0 值占比相关字段。
- 前端典型站点表只新增一列“测试集6-19点0值占比%”。
- 散点图横轴口径只保留“全量历史样本数”。
- 每个站点 tooltip / 信息卡片展示“测试集6-19点0值占比”。
- 不重新训练，不修改预测 pkl。

