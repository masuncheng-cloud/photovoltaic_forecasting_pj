# Cursor执行方案 Round46.1：精简逐小时预测结果表

## 目标

当前 Round46 已经修正了逐小时站点 NRMSE 的计算口径，但页面中的“逐小时预测结果”表格列过多。

本轮只做展示精简，不改变训练结果、不改变最终预测列、不改变 NRMSE 计算口径。

需要删除以下三列：

- `站点中位 NRMSE（%）`
- `有效发电站点均NRMSE（%）`
- `平均0值占比（%）`

保留以下四列：

- `小时（时）`
- `样本数（行）`
- `站点平均 NRMSE（%）`
- `城市 NRMSE（%）`

---

## 修改文件

主要修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

如导出脚本里有专门给前端表格生成字段说明，也同步清理：

```text
scripts/export_interactive_dashboard_data.py
scripts/round46_recompute_hourly_nrmse_consistent.py
```

注意：导出 JSON 里可以继续保留辅助字段，方便后续诊断；但前端页面不要展示这三列。

---

## 具体修改要求

### 1. 精简逐小时预测结果表头

在 `interactive_forecast_dashboard.html` 中找到渲染逐小时预测结果表格的函数，通常可能叫：

```js
renderHourlyPredictionSummary()
renderHourlyTable()
renderHourlyNrmseTable()
```

将表头改为只包含：

```html
<th>小时（时）</th>
<th>样本数（行）</th>
<th>站点平均 NRMSE（%）</th>
<th>城市 NRMSE（%）</th>
```

删除：

```html
<th>站点中位 NRMSE（%）</th>
<th>有效发电站点均NRMSE（%）</th>
<th>平均0值占比（%）</th>
```

---

### 2. 精简逐小时预测结果表格内容

将每一行数据渲染改为：

```js
`
<tr>
  <td>${row.hour}</td>
  <td>${formatInteger(row.samples)}</td>
  <td>${formatPct(row.site_avg_nrmse_pct)}</td>
  <td>${formatPct(row.city_nrmse_pct)}</td>
</tr>
`
```

如果当前字段名仍有兼容写法，可以保留兜底：

```js
const siteAvg = row.site_avg_nrmse_pct ?? row.site_nrmse_mean_pct;
const city = row.city_nrmse_pct;
```

但页面最终只展示四列。

---

### 3. 精简表格说明文字

将逐小时预测结果表格下方说明改成：

```text
说明：站点平均 NRMSE 按“先对每个站点在该小时计算 NRMSE，再对站点取平均”的口径统计；城市 NRMSE 按全市同一小时总功率聚合后计算。样本数为测试集该小时参与统计的站点-时间记录数。
```

不要再解释：

- 站点中位 NRMSE
- 有效发电站点均 NRMSE
- 平均 0 值占比

---

### 4. 图表 Tooltip 同步精简

如果逐小时图表或表格 tooltip 中展示了以下字段，也删除：

```text
站点中位 NRMSE
有效发电站点均NRMSE
平均0值占比
```

保留：

```text
小时
样本数
站点平均 NRMSE
城市 NRMSE
```

---

### 5. 不要改动计算口径

不要改动 Round46 已修复的核心计算逻辑：

```text
每个 site_id、hour 先计算 RMSE / capacity_mw × 100%
然后按 hour 对所有站点取平均
```

也不要回退到旧的错误口径：

```text
所有站点混在一起按 hour groupby，再除以 capacity_median
```

---

## 执行命令

修改完成后在项目根目录执行：

```bash
python scripts/export_interactive_dashboard_data.py
python scripts/update_dashboard_after_training.py
python scripts/check_dashboard_auto_update_stamp.py
python scripts/round44_dashboard_regression_check.py
```

如果 `round44_dashboard_regression_check.py` 不存在，则改执行当前项目里最新的 dashboard 回归检查脚本，例如：

```bash
ls scripts/*dashboard*check*.py
```

然后执行对应脚本。

---

## 验收标准

### 页面验收

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

强制刷新：

```text
Ctrl + Shift + R
```

逐小时预测结果表格必须只显示四列：

| 小时（时） | 样本数（行） | 站点平均 NRMSE（%） | 城市 NRMSE（%） |
|---:|---:|---:|---:|

不得再出现：

- `站点中位 NRMSE（%）`
- `有效发电站点均NRMSE（%）`
- `平均0值占比（%）`

### 数据验收

10-14 点的站点平均 NRMSE 数值应仍与 Round46 结果一致，不能因为展示精简发生变化：

| 小时 | 站点平均 NRMSE（%） |
|---:|---:|
| 10 | 13.79 |
| 11 | 15.30 |
| 12 | 16.14 |
| 13 | 15.86 |
| 14 | 13.82 |

允许最后一位小数因格式化略有差异，但不能回到 31%-37% 的旧错误口径。

---

## 本轮不做

- 不重新训练模型。
- 不修改最终预测列。
- 不修改 NRMSE 计算公式。
- 不删除导出 JSON 中的诊断辅助字段，除非它们影响页面显示。

