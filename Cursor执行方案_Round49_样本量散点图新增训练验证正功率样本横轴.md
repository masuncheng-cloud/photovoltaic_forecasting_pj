# Cursor执行方案 Round49：样本量散点图新增“训练+验证阶段 6-19 点正功率样本量”横轴

## 目标

当前可视化页面中“单站点全量历史样本数与测试集 NRMSE 关系”的横轴口径只有：

```text
全量历史样本数
```

但根据 Round48 分析，判断模型需要多少有效数据量时，更有价值的是：

```text
训练+验证阶段 6-19 点正功率样本量
```

本轮目标是在该图的“横轴口径”中新增这个选项，并让散点图、tooltip、下方阈值表和分箱表都能随口径切换。

---

## 一、需要新增的横轴选项

在页面“横轴口径”按钮区域新增：

```text
训练+验证6-19点正功率样本量
```

建议按钮文案不要太长，可显示为：

```text
训练验证正功率样本
```

鼠标悬浮说明：

```text
统计 train + valid 阶段、6-19 点、真实功率 power_mw > 0 的样本数，更接近模型实际可学习的有效发电样本量。
```

---

## 二、数据字段

优先使用 Round48 生成的字段：

```text
train_valid_positive_samples_6_19
```

该字段来自：

```text
output/pv_pipeline/metrics/round48_station_data_requirement_analysis.csv
```

如果当前 dashboard 导出数据中还没有该字段，需要在导出脚本中加入。

---

## 三、修改导出脚本

修改：

```text
scripts/export_interactive_dashboard_data.py
```

### 1. 读取 Round48 站点级数据

在导出 `sample_nrmse_relationship` 或类似数据时，优先读取：

```text
output/pv_pipeline/metrics/round48_station_data_requirement_analysis.csv
```

如果该文件存在，则把以下字段 merge 到站点散点数据中：

```text
site_id
train_valid_positive_samples_6_19
train_valid_samples_6_19
train_valid_zero_ratio_6_19
test_zero_ratio_6_19
test_10_14_nrmse_pct
```

要求：

- 以 `site_id` 左连接。
- 不得改变现有 `test_nrmse_pct` 计算口径。
- 如果 Round48 文件不存在，则降级使用现有字段，但页面要隐藏新增横轴选项或给出空值提示。

### 2. 导出 JSON 时保留新增字段

确认以下 dashboard JSON 中，每个站点对象都包含：

```json
{
  "train_valid_positive_samples_6_19": 6848
}
```

可能涉及文件：

```text
output/pv_pipeline/interactive_dashboard/sample_nrmse_relationship.json
output/pv_pipeline/interactive_dashboard/site_metrics.json
output/pv_pipeline/interactive_dashboard/typical_sites.json
```

以页面实际读取的数据文件为准。

---

## 四、修改前端页面

修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

### 1. 新增横轴状态

找到当前散点图横轴口径状态，例如：

```js
sampleXAxisMode = "history_samples_total"
```

新增枚举：

```js
history_samples_total
train_valid_positive_samples_6_19
```

推荐配置写成对象，避免到处硬编码：

```js
const SAMPLE_X_AXIS_CONFIG = {
  history_samples_total: {
    label: "全量历史样本数",
    field: "history_samples_total",
    axisLabel: "单站点全量历史样本数（行）",
    description: "train/valid/test，不包含 future。"
  },
  train_valid_positive_samples_6_19: {
    label: "训练验证正功率样本",
    field: "train_valid_positive_samples_6_19",
    axisLabel: "训练+验证阶段6-19点正功率样本量（行）",
    description: "train + valid 阶段、6-19点、power_mw > 0 的样本数。"
  }
};
```

### 2. 新增按钮

在“横轴口径”按钮区域新增按钮：

```html
<button class="axis-mode-btn" data-axis-mode="train_valid_positive_samples_6_19" title="统计 train + valid 阶段、6-19 点、真实功率 power_mw > 0 的样本数，更接近模型实际可学习的有效发电样本量。">
  训练验证正功率样本
</button>
```

要求：

- 与现有按钮样式一致。
- 选中后高亮。
- 切换后立即重绘散点图、阈值表和分箱表。

### 3. 修改散点图横轴取值

当前可能写死：

```js
const x = d.history_samples_total;
```

改为：

```js
const axisCfg = SAMPLE_X_AXIS_CONFIG[state.sampleXAxisMode];
const x = Number(d[axisCfg.field] || 0);
```

过滤无效点：

```js
const validPoints = points.filter(d => Number.isFinite(Number(d[axisCfg.field])) && Number(d[axisCfg.field]) > 0);
```

### 4. 修改横轴标题

从写死：

```text
单站点全量历史样本数（行）
```

改为：

```js
axisCfg.axisLabel
```

### 5. 修改 tooltip

tooltip 中保留：

```text
全量历史样本数
全量正功率样本数
训练+验证6-19点正功率样本数
测试集6-19点0值占比
测试集站点NRMSE
```

新增显示：

```js
训练+验证6-19点正功率样本数：${formatInteger(d.train_valid_positive_samples_6_19)} 行
```

注意：即使当前横轴不是这个字段，tooltip 里也可以展示该字段，方便对比。

---

## 五、修改阈值表

当前“达到不同 NRMSE 阈值的全量历史样本量分布”表格需要随横轴口径切换。

### 1. 表标题动态变化

如果横轴为 `history_samples_total`：

```text
达到不同 NRMSE 阈值的全量历史样本量分布
```

如果横轴为 `train_valid_positive_samples_6_19`：

```text
达到不同 NRMSE 阈值的训练验证正功率样本量分布
```

### 2. 表头动态变化

原表头：

```text
全量样本最小值
全量样本25分位
全量样本中位数
全量样本75分位
全量样本最大值
```

切换后改为：

```text
训练验证正功率样本最小值
训练验证正功率样本25分位
训练验证正功率样本中位数
训练验证正功率样本75分位
训练验证正功率样本最大值
```

如果表头过长，可以使用短表头：

```text
样本最小值
样本25分位
样本中位数
样本75分位
样本最大值
```

并在表下说明当前口径。

### 3. 分位数计算字段

表格中的分位数必须使用当前横轴字段：

```js
const sampleField = SAMPLE_X_AXIS_CONFIG[state.sampleXAxisMode].field;
```

不要继续写死 `history_samples_total`。

---

## 六、修改分箱表

当前“按单站点全量历史样本数分箱的 NRMSE 分布”也需要支持新口径。

### 1. 标题动态变化

全量历史样本：

```text
按单站点全量历史样本数分箱的 NRMSE 分布
```

训练验证正功率样本：

```text
按训练验证6-19点正功率样本量分箱的 NRMSE 分布
```

### 2. 分箱边界

全量历史样本继续使用当前分箱，例如：

```js
[0, 5000, 10000, 15000, 20000, 26000, 28000, Infinity]
```

新增口径建议使用：

```js
[0, 1000, 2000, 3000, 5000, 8000, 11000, Infinity]
```

对应标签：

```text
0-1000
1000-2000
2000-3000
3000-5000
5000-8000
8000-11000
11000+
```

### 3. 表内样本统计字段

当前表中的：

```text
全量样本中位数
全量正功率样本中位数
训练验证正功率样本中位数
```

可以保留，但分箱依据必须随当前口径变化。

---

## 七、页面说明文字

在散点图说明文字中加入：

```text
横轴可切换为“全量历史样本数”或“训练验证正功率样本”。判断模型需要多少有效数据量时，训练+验证阶段 6-19 点正功率样本量更接近模型实际可学习的数据规模。
```

不要写成“达到某个样本数一定准确”。建议写：

```text
样本量只是经验参考，容量映射、异常0值、限电、遮挡和气象匹配仍会影响最终 NRMSE。
```

---

## 八、执行命令

修改完成后执行：

```bash
python scripts/export_interactive_dashboard_data.py
python scripts/update_dashboard_after_training.py
python scripts/check_dashboard_data_freshness.py
python scripts/check_dashboard_auto_update_stamp.py
```

如果存在 dashboard 回归检查脚本，也执行：

```bash
python scripts/round44_dashboard_regression_check.py
```

---

## 九、验收标准

打开页面：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

强制刷新：

```text
Ctrl + Shift + R
```

检查：

1. “横轴口径”区域出现新按钮：

```text
训练验证正功率样本
```

2. 点击后散点图横轴标题变为：

```text
训练+验证阶段6-19点正功率样本量（行）
```

3. tooltip 中出现：

```text
训练+验证6-19点正功率样本数
```

4. 阈值表标题和分位数字段随横轴口径变化。

5. 分箱表标题和分箱区间随横轴口径变化。

6. 页面仍能正常显示：

- 全市曲线；
- 单站点曲线；
- 典型站点；
- 逐小时预测结果；
- 样本量与 NRMSE 散点图。

7. 所有检查脚本 PASS。

---

## 十、注意事项

1. 不要删除原有“全量历史样本数”口径。
2. 不要改变 NRMSE 计算公式。
3. 不要重新训练模型。
4. 如果 Round48 CSV 不存在，页面应保持可用，不应报错白屏。
5. 如果字段缺失，tooltip 和表格中显示 `-`，不要显示 `undefined` 或 `NaN`。

