# Cursor 修改方案 Round12：样本量口径改为“单站点全量历史样本数”

## 0. 修改目标

当前可视化页面中的样本量散点图和分箱表默认使用：

```text
训练+验证正功率样本数
```

这会导致 15000 以上样本区间显示为 0 个站点，和之前讨论的“部分站点约 26000 条历史数据”口径不一致。

本轮修改目标：

```text
将页面主样本量口径改为“单站点全量历史样本数”
```

也就是：

```text
该站点在 distributed_predictions_final_full.pkl 中的全部记录数
```

不限制：

- split；
- 6-19 点；
- 是否正功率；
- train / valid / test / future。

但注意：

```text
模型效果 NRMSE 仍然只使用 test 集 6-19 点计算。
```

最终页面含义应变成：

```text
横轴：单站点全量历史样本数（行）
纵轴：测试集站点 NRMSE（%）
```

---

## 1. 需要修改的文件

修改：

```text
scripts/export_interactive_dashboard_data.py
stages/05_visualization/interactive_forecast_dashboard.html
stages/05_visualization/README.md
```

不要修改：

```text
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
output/pv_pipeline/tables/best_predictions_eval.pkl
output/pv_pipeline/tables/best_predictions_full.pkl
```

不要重新训练模型。

---

## 2. 数据导出脚本修改

修改：

```text
scripts/export_interactive_dashboard_data.py
```

### 2.1 新增全量样本统计字段

在生成 `scatter_site_sample_nrmse.json` 时，新增以下字段：

```text
full_history_rows
full_history_non_null_rows
full_history_positive_rows
full_history_zero_rows
full_history_zero_ratio_pct
full_history_start_date
full_history_end_date
```

字段含义：

| 字段 | 含义 |
|---|---|
| `full_history_rows` | 该站点在 full 预测表中的全部记录数 |
| `full_history_non_null_rows` | `power_mw` 非空记录数 |
| `full_history_positive_rows` | `power_mw > 0` 的记录数 |
| `full_history_zero_rows` | `power_mw == 0` 的记录数 |
| `full_history_zero_ratio_pct` | 0 值占全量记录比例 |
| `full_history_start_date` | 该站点最早记录日期 |
| `full_history_end_date` | 该站点最晚记录日期 |

### 2.2 全量统计代码

在读取 full 表后，先保留一个不经过 6-19、split、正功率筛选的原始副本：

```python
full_df_raw = df.copy()
full_df_raw["time"] = pd.to_datetime(full_df_raw["time"], errors="coerce")
full_df_raw["date"] = full_df_raw["time"].dt.strftime("%Y-%m-%d")
```

然后按站点统计：

```python
full_hist = full_df_raw.groupby("site_id").agg(
    full_history_rows=("site_id", "size"),
    full_history_non_null_rows=("power_mw", lambda s: int(s.notna().sum())),
    full_history_positive_rows=("power_mw", lambda s: int((s.fillna(0) > 0).sum())),
    full_history_zero_rows=("power_mw", lambda s: int((s.fillna(0) == 0).sum())),
    full_history_start_date=("time", "min"),
    full_history_end_date=("time", "max"),
).reset_index()

full_hist["full_history_zero_ratio_pct"] = (
    full_hist["full_history_zero_rows"] /
    full_hist["full_history_rows"].clip(lower=1) * 100
)

full_hist["full_history_start_date"] = full_hist["full_history_start_date"].dt.strftime("%Y-%m-%d")
full_hist["full_history_end_date"] = full_hist["full_history_end_date"].dt.strftime("%Y-%m-%d")
```

合并到站点散点数据：

```python
site_df = site_df.merge(full_hist, on="site_id", how="left")
```

### 2.3 保留原字段作为辅助

保留现有字段：

```text
train_rows
valid_rows
train_valid_rows
train_valid_positive_rows
train_valid_zero_ratio_pct
```

但不再作为页面默认横轴和默认分箱口径。

---

## 3. 修改样本量阈值表

当前：

```text
sample_requirement_summary.json
```

默认统计的是正功率样本量。

本轮改为默认统计：

```text
full_history_rows
```

### 3.1 字段调整

输出字段改为：

```text
threshold_pct
qualified_sites
total_sites
qualified_ratio_pct
min_full_history_rows
p25_full_history_rows
median_full_history_rows
p75_full_history_rows
max_full_history_rows
median_train_valid_positive_rows
median_full_history_positive_rows
note
```

保留 `median_train_valid_positive_rows` 作为辅助对照。

### 3.2 统计逻辑

对每个 NRMSE 阈值：

```python
qualified = site_df[site_df["test_nrmse_pct"] <= threshold]
```

统计全量样本：

```python
vals = qualified["full_history_rows"].dropna().astype(float)
```

如果 `qualified` 为空，则各样本量字段填 `None`。

### 3.3 页面显示表头改为

```text
NRMSE阈值
达标站点数
总站点数
达标比例
全量样本最小值
全量样本25分位
全量样本中位数
全量样本75分位
全量样本最大值
正功率样本中位数
说明
```

---

## 4. 修改样本量分箱

当前：

```text
sample_requirement_bins.json
```

按 `train_valid_positive_rows` 分箱。

本轮改为按：

```text
full_history_rows
```

分箱。

### 4.1 新分箱

建议使用：

```text
0-5000
5000-10000
10000-15000
15000-20000
20000-26000
26000-28000
28000+
```

原因：

- 页面需要能看到 26000 左右站点。
- 当前 full 表里可能存在 future 数据，因此部分站点可能超过 26000。

### 4.2 输出字段

```text
sample_bin
site_count
median_full_history_rows
median_full_history_positive_rows
median_train_valid_positive_rows
mean_nrmse_pct
median_nrmse_pct
p25_nrmse_pct
p75_nrmse_pct
best_nrmse_pct
worst_nrmse_pct
```

### 4.3 表格标题改为

```text
按单站点全量历史样本数分箱的 NRMSE 分布
```

---

## 5. 修改 HTML 页面

修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

### 5.1 散点图默认横轴

当前默认横轴如果是：

```text
train_valid_positive_rows
```

改为：

```text
full_history_rows
```

横轴标题改为：

```text
单站点全量历史样本数（行）
```

纵轴保持：

```text
测试集站点 NRMSE（%）
```

### 5.2 横轴口径切换

如果页面已有“样本量口径”切换，改为三个选项：

```text
全量历史样本数
训练+验证总样本数
训练+验证正功率样本数
```

对应字段：

```javascript
const sampleAxisOptions = {
  full_history_rows: "单站点全量历史样本数（行）",
  train_valid_rows: "训练+验证总样本数（行）",
  train_valid_positive_rows: "训练+验证正功率样本数（行）"
};
```

默认：

```javascript
let sampleAxisField = "full_history_rows";
```

### 5.3 tooltip 增加字段

散点图 tooltip 增加：

```text
全量历史样本数
全量正功率样本数
全量0值占比
记录日期范围
训练+验证正功率样本数
测试 NRMSE
```

示例：

```javascript
tooltip.innerHTML = `
  <b>${d.site_id} ${d.site_name || ""}</b><br>
  全量历史样本数：${formatInt(d.full_history_rows)} 行<br>
  全量正功率样本数：${formatInt(d.full_history_positive_rows)} 行<br>
  全量0值占比：${formatNumber(d.full_history_zero_ratio_pct, 2)}%<br>
  日期范围：${d.full_history_start_date || "-"} ~ ${d.full_history_end_date || "-"}<br>
  训练+验证正功率样本数：${formatInt(d.train_valid_positive_rows)} 行<br>
  测试 NRMSE：${formatNumber(d.test_nrmse_pct, 2)}%<br>
`;
```

### 5.4 阈值表文案调整

标题改为：

```text
达到不同 NRMSE 阈值的全量历史样本量分布
```

表格说明改为：

```text
说明：这里统计的是单站点在 full 预测表中的全量历史样本数，包含夜间、0值、训练集、验证集、测试集及 future 行；测试 NRMSE 仍只使用测试集 6-19 点计算。该统计用于观察当前模型精度与站点历史数据量的经验关系，不表示样本量达到该数值后必然达到对应精度。
```

### 5.5 分箱表文案调整

标题改为：

```text
按单站点全量历史样本数分箱的 NRMSE 分布
```

表头改为：

```text
样本区间
站点数
全量样本中位数
全量正功率样本中位数
训练+验证正功率样本中位数
NRMSE均值%
NRMSE中位数%
NRMSE25分位%
NRMSE75分位%
最佳NRMSE%
最差NRMSE%
```

---

## 6. 修正页面解释，避免误导

页面中如果出现：

```text
训练+验证正功率样本数越多
```

改为：

```text
全量历史样本数越多
```

但必须保留限定：

```text
样本量不是唯一决定因素，容量、站点映射、异常0值、限电、遮挡和气象插值都会影响最终 NRMSE。
```

---

## 7. README 更新

修改：

```text
stages/05_visualization/README.md
```

将相关说明改为：

```markdown
散点图默认使用“单站点全量历史样本数”作为横轴，测试集站点 NRMSE 作为纵轴。全量历史样本数来自 `distributed_predictions_final_full.pkl`，包含该站点所有小时、所有 split 的记录；测试 NRMSE 仍固定使用 test 集 6-19 点。
```

---

## 8. 重新生成数据

执行：

```bash
python scripts/export_interactive_dashboard_data.py \
  --output-root output/pv_pipeline \
  --dashboard-root output/pv_pipeline/interactive_dashboard
```

---

## 9. 验收命令

执行：

```bash
python - <<'PY'
import json
from pathlib import Path

root = Path("output/pv_pipeline/interactive_dashboard")
site_path = root / "scatter_site_sample_nrmse.json"
bins_path = root / "sample_requirement_bins.json"
summary_path = root / "sample_requirement_summary.json"

assert site_path.exists(), "scatter_site_sample_nrmse.json 不存在"
assert bins_path.exists(), "sample_requirement_bins.json 不存在"
assert summary_path.exists(), "sample_requirement_summary.json 不存在"

site = json.loads(site_path.read_text(encoding="utf-8"))
bins = json.loads(bins_path.read_text(encoding="utf-8"))
summary = json.loads(summary_path.read_text(encoding="utf-8"))

assert len(site) > 0
assert "full_history_rows" in site[0]
assert "full_history_positive_rows" in site[0]
assert "full_history_zero_ratio_pct" in site[0]
assert "full_history_start_date" in site[0]
assert "full_history_end_date" in site[0]

max_full = max(int(x.get("full_history_rows") or 0) for x in site)
print("max_full_history_rows =", max_full)
assert max_full >= 20000, "全量历史样本最大值低于 20000，可能仍在使用正功率样本口径"

bin_names = [x.get("sample_bin") for x in bins]
print("bins =", bin_names)
assert any("20000" in str(x) or "26000" in str(x) for x in bin_names), "分箱中未出现 20000/26000 区间"

for row in summary:
    assert "median_full_history_rows" in row

print("[OK] full-history sample axis exported")
PY
```

---

## 10. 页面验收

启动页面：

```bash
python -m http.server 8060
```

打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

检查：

1. 散点图横轴默认为：

```text
单站点全量历史样本数（行）
```

2. 下方分箱表标题为：

```text
按单站点全量历史样本数分箱的 NRMSE 分布
```

3. 分箱中应能看到：

```text
20000-26000
26000-28000
28000+
```

4. 如果 full 表中确实有 26000 条左右站点，这些站点应进入对应分箱。

5. tooltip 中能看到：

```text
全量历史样本数
全量正功率样本数
全量0值占比
日期范围
```

6. 页面原有功能不受影响：

```text
全市/单站点曲线
典型站点选择
四季代表日
逐小时预测结果
阈值表
```

---

## 11. 提交说明建议

```text
Round12: switch sample-size dashboard axis to full site history rows

- add full-history sample fields to dashboard export
- use full_history_rows as default scatter x-axis
- update sample threshold and bin tables to full-history rows
- keep train/valid positive rows as auxiliary diagnostics
- keep test NRMSE calculation unchanged
```

