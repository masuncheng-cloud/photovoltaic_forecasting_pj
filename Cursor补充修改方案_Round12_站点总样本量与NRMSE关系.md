# Cursor 补充修改方案 Round12：散点图改为“站点总样本量 vs 站点最终 NRMSE”

## 0. 修改原因

上一版页面中的散点图使用的是：

```text
站点-小时样本数
```

也就是一个点代表：

```text
某个站点 + 某一个小时
```

这个口径只能说明“某站点在某小时有多少条记录”，不能回答当前真正关心的问题：

```text
一个单站点到底需要多少历史训练数据，模型预测精度才能稳定达到 5%、10%、15% 等 NRMSE 水平？
```

因此本轮需要把散点图改为：

```text
单个站点累计训练样本量 vs 单站点最终测试集 NRMSE
```

每个点代表一个站点，而不是一个站点-小时组合。

---

## 1. 核心口径调整

### 1.1 原错误口径

不要继续使用：

```text
site_id + hour
```

作为散点图点位。

不要继续输出或展示：

```text
scatter_site_hour.json
```

作为主要散点图数据。

### 1.2 新口径

新增：

```text
scatter_site_sample_nrmse.json
```

每一行代表一个站点：

```text
site_id
site_name
capacity_mw
train_rows
valid_rows
train_valid_rows
train_valid_positive_rows
train_valid_zero_ratio_pct
test_rows
test_positive_rows
test_nrmse_pct
test_mae_mw
test_rmse_mw
test_bias_pct
test_pred_actual_ratio
category_label
```

页面散点图：

```text
横轴：train_valid_rows 或 train_valid_positive_rows
纵轴：test_nrmse_pct
点：单个站点
```

推荐默认横轴使用：

```text
train_valid_positive_rows
```

原因：

```text
光伏夜间和无效 0 值样本很多，正功率样本更能代表模型真正学到的发电规律。
```

页面可以增加一个切换：

```text
样本量口径：
1. 训练+验证总样本数
2. 训练+验证正功率样本数
```

---

## 2. 重要说明：不要写成严格因果

这个页面可以估算：

```text
当前数据和当前模型下，不同样本量站点通常对应的 NRMSE 水平。
```

但不能写成：

```text
只要有 N 条数据，NRMSE 一定能达到 10%。
```

因为站点精度还受以下因素影响：

```text
1. 站点容量是否准确
2. 站点映射是否准确
3. 站点是否有遮挡、限电、停机
4. 0 值和异常值比例
5. 天气插值误差
6. 屋顶光伏和地面光伏差异
7. 测试集天气分布是否和训练集一致
```

因此页面和表格统一使用以下表述：

```text
经验估计：在当前数据和当前模型下，达到指定 NRMSE 阈值的站点通常具备的训练样本量分布。
```

---

## 3. 修改数据导出脚本

修改：

```text
scripts/export_interactive_dashboard_data.py
```

### 3.1 保留原有输出

继续保留：

```text
index.json
city_series.json
site_metrics.json
season_days.json
midday_city_by_date.json
site_series/
```

### 3.2 废弃或降级原站点-小时散点图

原：

```text
scatter_site_hour.json
error_threshold_summary.json
```

不要作为主散点图使用。

可以保留文件，但页面默认不展示。更推荐新增替代文件：

```text
scatter_site_sample_nrmse.json
sample_requirement_summary.json
sample_requirement_bins.json
```

---

## 4. 新增站点样本量与 NRMSE 数据

### 4.1 数据来源

读取：

```text
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
```

如果读取失败，再读取：

```text
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
```

必须使用 `split` 区分训练、验证、测试：

```python
train_valid = df[df["split"].isin(["train", "valid"])].copy()
test = df[df["split"].eq("test")].copy()
```

注意：

```text
横轴样本量只允许来自 train + valid。
纵轴 NRMSE 只允许来自 test。
```

这样可以避免用测试集样本数解释测试集效果。

### 4.2 样本量统计

按站点统计训练/验证样本量：

```python
tv = train_valid.groupby("site_id").agg(
    train_valid_rows=("power_mw", "size"),
    train_valid_non_null_rows=("power_mw", lambda s: s.notna().sum()),
    train_valid_positive_rows=("power_mw", lambda s: (s.fillna(0) > 0).sum()),
    train_valid_zero_rows=("power_mw", lambda s: (s.fillna(0) == 0).sum()),
    capacity_mw=("capacity_mw", "mean"),
).reset_index()

tv["train_valid_zero_ratio_pct"] = (
    tv["train_valid_zero_rows"] / tv["train_valid_rows"].clip(lower=1) * 100
)
```

如果需要分开 train 和 valid：

```python
train_rows = df[df["split"].eq("train")].groupby("site_id").size()
valid_rows = df[df["split"].eq("valid")].groupby("site_id").size()
```

### 4.3 测试集站点 NRMSE

测试集只使用 6-19 点：

```python
test_eval = test[test["hour"].between(6, 19)].copy()
test_eval = test_eval[test_eval["power_mw"].notna() & test_eval["power_pred"].notna()]
```

按站点计算：

```python
def rmse(y, p):
    return np.sqrt(np.mean((p - y) ** 2))

rows = []
for site_id, g in test_eval.groupby("site_id"):
    y = g["power_mw"].astype(float).values
    p = g["power_pred"].astype(float).values
    c = max(float(g["capacity_mw"].mean()), 1e-9)
    actual_sum = float(np.sum(y))
    pred_sum = float(np.sum(p))
    rmse_mw = rmse(y, p)
    rows.append({
        "site_id": site_id,
        "test_rows": int(len(g)),
        "test_positive_rows": int((g["power_mw"].fillna(0) > 0).sum()),
        "test_mae_mw": float(np.mean(np.abs(p - y))),
        "test_rmse_mw": float(rmse_mw),
        "test_nrmse_pct": float(rmse_mw / c * 100),
        "test_bias_pct": float((pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100),
        "test_pred_actual_ratio": float(pred_sum / max(actual_sum, 1e-9)),
    })
```

### 4.4 合并站点名称

从 `site_master.csv` 补充：

```text
site_id
site_short_name
site_full_name
county
capacity_mw
```

优先显示：

```python
site_name = site_short_name if not null else site_full_name
```

### 4.5 输出 scatter_site_sample_nrmse.json

最终输出：

```text
output/pv_pipeline/interactive_dashboard/scatter_site_sample_nrmse.json
```

字段：

```text
site_id
site_name
county
capacity_mw
train_rows
valid_rows
train_valid_rows
train_valid_positive_rows
train_valid_zero_ratio_pct
test_rows
test_positive_rows
test_mae_mw
test_rmse_mw
test_nrmse_pct
test_bias_pct
test_pred_actual_ratio
category_label
```

---

## 5. 新增“达到误差阈值需要多少数据”的经验估计表

新增：

```text
sample_requirement_summary.json
```

### 5.1 阈值

阈值设为：

```text
5%, 10%, 15%, 20%, 25%
```

### 5.2 统计逻辑

对每个阈值 `T`：

```python
qualified = site_df[site_df["test_nrmse_pct"] <= T]
```

统计：

```text
threshold_pct
qualified_sites
total_sites
qualified_ratio_pct
min_train_valid_positive_rows
p25_train_valid_positive_rows
median_train_valid_positive_rows
p75_train_valid_positive_rows
max_train_valid_positive_rows
min_train_valid_rows
p25_train_valid_rows
median_train_valid_rows
p75_train_valid_rows
max_train_valid_rows
note
```

说明：

```text
qualified_sites：测试集 NRMSE 不高于该阈值的站点数量。
median_train_valid_positive_rows：这些达标站点在训练+验证集中通常拥有的正功率样本量中位数。
```

### 5.3 页面显示名称

表格标题：

```text
达到不同 NRMSE 阈值的站点样本量分布
```

列名：

```text
NRMSE阈值
达标站点数
总站点数
达标比例
正功率样本最小值
正功率样本25分位
正功率样本中位数
正功率样本75分位
总样本中位数
说明
```

### 5.4 必须加说明

表格下面加：

```text
说明：这里统计的是单站点累计训练+验证样本量，而不是站点-小时样本量。该结果是当前数据和当前模型下的经验统计，不代表样本量达到该数值后必然达到对应精度。
```

---

## 6. 新增样本量分箱统计

新增：

```text
sample_requirement_bins.json
```

用于回答：

```text
样本越多，站点 NRMSE 是否确实更低？
```

### 6.1 分箱方式

按 `train_valid_positive_rows` 分箱：

```text
0-1000
1000-3000
3000-6000
6000-10000
10000-15000
15000-20000
20000-26000
26000+
```

每个分箱统计：

```text
sample_bin
site_count
median_train_valid_positive_rows
mean_nrmse_pct
median_nrmse_pct
p25_nrmse_pct
p75_nrmse_pct
best_nrmse_pct
worst_nrmse_pct
```

页面可显示成表格，或在散点图下方展示。

---

## 7. 修改 HTML 页面

修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

### 7.1 散点图区改名

原标题如果是：

```text
误差-样本量散点图
```

改为：

```text
单站点样本量与最终 NRMSE 关系
```

### 7.2 横轴改为站点累计样本量

默认：

```text
横轴：训练+验证正功率样本数（行）
```

可切换：

```text
训练+验证总样本数（行）
训练+验证正功率样本数（行）
```

纵轴：

```text
测试集站点 NRMSE（%）
```

### 7.3 一个点代表一个站点

tooltip 必须显示：

```text
站点ID
站点名称
容量 MW
训练+验证总样本数
训练+验证正功率样本数
测试样本数
测试 NRMSE %
测试 MAE MW
测试 RMSE MW
pred/actual ratio
类别
```

### 7.4 参考线

保留水平参考线：

```text
5%
10%
15%
20%
25%
```

不要把这些线解释为“样本量线”，它们是误差阈值线。

### 7.5 删除或隐藏旧表格说明

如果页面中还有：

```text
站点-小时组合
某站点在某小时
```

这些说明必须删除或移动到高级诊断区，默认不要展示。

---

## 8. 页面文案建议

在散点图区下方添加：

```text
本图每个点代表一个站点。横轴为该站点在训练+验证阶段可用于学习的累计样本量，纵轴为该站点在测试集上的最终 NRMSE。点越靠右表示历史数据越多，点越靠下表示预测精度越高。
```

在阈值表下方添加：

```text
“需要多少数据”在这里表示经验样本量分布：例如 NRMSE≤10% 的站点，其训练+验证正功率样本数的中位数是多少。该统计不能证明样本量是唯一原因，但可用于判断当前模型对单站点数据量的依赖程度。
```

---

## 9. 验收标准

运行：

```bash
python scripts/export_interactive_dashboard_data.py \
  --output-root output/pv_pipeline \
  --dashboard-root output/pv_pipeline/interactive_dashboard
```

必须生成：

```text
output/pv_pipeline/interactive_dashboard/scatter_site_sample_nrmse.json
output/pv_pipeline/interactive_dashboard/sample_requirement_summary.json
output/pv_pipeline/interactive_dashboard/sample_requirement_bins.json
```

检查 JSON：

```python
import json
from pathlib import Path

root = Path("output/pv_pipeline/interactive_dashboard")
site = json.loads((root / "scatter_site_sample_nrmse.json").read_text(encoding="utf-8"))
summary = json.loads((root / "sample_requirement_summary.json").read_text(encoding="utf-8"))
bins = json.loads((root / "sample_requirement_bins.json").read_text(encoding="utf-8"))

assert len(site) > 0
assert len(summary) == 5
assert len(bins) > 0
assert "train_valid_positive_rows" in site[0]
assert "test_nrmse_pct" in site[0]
```

页面验收：

1. 散点图每个点代表一个站点，而不是站点-小时。
2. 横轴名称显示为“训练+验证正功率样本数（行）”。
3. 纵轴名称显示为“测试集站点 NRMSE（%）”。
4. 阈值表标题显示为“达到不同 NRMSE 阈值的站点样本量分布”。
5. 表格说明中明确写出“不是站点-小时样本量”。
6. 典型站点选择、全市/单站点折线图功能保持正常。

---

## 10. 不要修改的内容

本轮仍然不要修改：

```text
distributed_predictions_final_eval.pkl
distributed_predictions_final_full.pkl
best_predictions_eval.pkl
best_predictions_full.pkl
```

不要重新训练模型。

不要让页面数据影响模型晋级逻辑。

