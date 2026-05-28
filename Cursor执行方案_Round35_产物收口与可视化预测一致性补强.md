# Round35 产物收口与可视化预测一致性补强方案

## 一、目标

Round34 已经修正了主要指标口径，本轮 Round35 不再修改训练模型主体，重点做最终产物收口：

1. 全量校验可视化 `pred_mw` 是否与 `power_pred_final` 完全一致。
2. 修正报告输出路径中的 `metrics/docs` 笔误。
3. 在项目报告中明确区分 118、68、14 三类站点数量。
4. 弱化或移除历史口径 `0.3365%`，避免误导。
5. 检查 Git 提交内容，避免把大体积 pkl/json 错误提交。
6. 重新生成最终报告和可视化数据。

## 二、当前 Round34 仍需补强的问题

### 2.1 可视化只确认了 actual 一致，pred 还需要全量确认

Round34 已确认：

```text
dashboard actual_mw 与 power_clean 一致
```

但还需要确认：

```text
dashboard pred_mw 与 distributed_predictions_final_round34.pkl 中 power_pred_final 一致
```

不能只抽查 5 个 JSON，要全量检查全部 `site_series/*.json`。

### 2.2 报告路径疑似错误

当前报告中出现：

```text
output/pv_pipeline/metrics/docs/Round34_指标口径与最终产物一致性验证报告.md
```

建议统一改为：

```text
output/pv_pipeline/docs/Round35_产物收口与可视化一致性验证报告.md
```

所有 Markdown 报告统一放在：

```text
output/pv_pipeline/docs/
```

### 2.3 站点数量容易被误读

正式项目报告中必须明确：

| 数量 | 含义 |
|---|---|
| 118 | 全部登记站点 |
| 68 | 当前最终预测文件中有 test 6-19 点结果的站点 |
| 14 | 严格正常可排名站点，不含无有效发电、分布漂移、系统性偏差 |

不要再使用含糊说法：

```text
有效评价站点 68
```

建议替换为：

```text
有 test 结果站点 68
正常可排名站点 14
```

### 2.4 历史口径 NRMSE 容易误导

Round34 反馈中出现：

```text
全市 test NRMSE 0.3365%
```

这属于历史口径，不是最终正式口径。正式报告中不应把它作为核心结果展示。

正式保留：

```text
全市总出力 10-14 点 NRMSE = 5.78%
```

如果必须保留历史口径，只能放到附录，并明确写：

```text
该值为旧版站点行级归一化口径，不作为最终验收指标。
```

### 2.5 Git 提交内容可能过大

Round34 提交了 101 个文件，需要检查是否包含：

```text
*.pkl
*.json
site_series/*.json
city_series.json
大体积 output 文件
```

如果包含，需要从 Git 追踪中移除，但保留本地文件。

## 三、Cursor 修改步骤

### Step 1：新增全量可视化预测一致性检查

新建脚本：

```text
scripts/check_dashboard_prediction_values_round35.py
```

功能：

1. 读取：

```text
output/pv_pipeline/tables/distributed_predictions_final_round34.pkl
```

2. 读取可视化数据目录：

```text
stages/05_visualization/data/site_series/
```

3. 对每个站点 JSON：

```text
site_series/Sxxx.json
```

逐行对比：

```text
json.time        == pkl.time
json.actual_mw   == pkl.power_mw
json.pred_mw     == pkl.power_pred_final
json.capacity_mw == pkl.capacity_mw
```

4. 默认排除：

```text
split == "future"
```

5. 缺失值规则：

```text
NaN 和 null 视为一致
数值误差容忍 1e-9
```

6. 输出：

```text
output/pv_pipeline/metrics/round35_dashboard_prediction_consistency.csv
output/pv_pipeline/docs/Round35_可视化预测值一致性检查报告.md
```

CSV 字段：

```text
site_id
n_json
n_pkl
n_matched
max_abs_diff_actual
max_abs_diff_pred
max_abs_diff_capacity
status
message
```

验收要求：

```text
所有站点 status == PASS
max_abs_diff_pred <= 1e-9
```

### Step 2：修正报告路径

检查并修改以下脚本：

```text
scripts/posttrain_validation_round34.py
scripts/regenerate_project_report_round34.py
scripts/compute_round34_metrics.py
```

确保所有 Markdown 报告写到：

```text
output/pv_pipeline/docs/
```

不要写到：

```text
output/pv_pipeline/metrics/docs/
```

新增 Round35 验证报告路径：

```text
output/pv_pipeline/docs/Round35_产物收口与可视化一致性验证报告.md
```

### Step 3：修正项目报告中的站点数量表述

修改：

```text
光伏功率预测项目.md
```

或重新运行报告生成脚本。

要求报告中明确写：

```text
全部登记站点：118
有 test 结果站点：68
正常可排名站点：14
测试期无有效发电：5
测试期分布漂移：37
系统性偏差：12
无测试预测结果：50
```

同时加入说明：

```text
“有 test 结果站点”表示最终预测文件中存在 2025-09-01 至 2025-12-31、6-19 点预测结果的站点；
“正常可排名站点”表示剔除了测试期无有效发电、分布漂移和系统性偏差后的站点，只用于典型站点排名；
全市总出力指标仍基于有 test 结果站点统计。
```

### Step 4：弱化历史口径 NRMSE

在以下文件中搜索：

```text
0.3365
0.3420
历史口径
站点容量均值
```

处理规则：

1. 正式项目报告中删除这类核心展示。
2. 如果执行反馈或附录保留，则加注：

```text
该值为旧版站点行级归一化口径，仅用于对比校准前后方向，不作为最终验收指标。
```

3. 正式核心结果只展示：

```text
全市总出力逐小时 NRMSE
站点平均逐小时 NRMSE
站点级 MAE/RMSE/NRMSE
```

### Step 5：检查 Git 提交内容和 .gitignore

在 Cursor 终端执行：

```bash
git status --short
git ls-files | grep -E '\\.(pkl|joblib|parquet)$|site_series/|city_series\\.json|output/pv_pipeline/tables/'
```

如果发现大体积结果文件已经被 Git 追踪，执行：

```bash
git rm --cached <file>
```

注意：

```text
只从 Git 追踪中移除，不删除本地文件。
```

检查 `.gitignore`，确保包含：

```text
*.pkl
*.joblib
*.parquet
output/pv_pipeline/tables/
stages/05_visualization/data/site_series/
stages/05_visualization/data/city_series.json
__pycache__/
.DS_Store
```

可以保留提交：

```text
核心脚本
核心 CSV 指标
Markdown 报告
HTML 页面
小体积 index/site_metrics 类 JSON
```

### Step 6：重新导出可视化数据

执行：

```bash
python scripts/export_interactive_dashboard_data.py
python scripts/check_dashboard_prediction_values_round35.py
```

要求：

1. 可视化 `pred_mw` 使用 `power_pred_final`。
2. 可视化默认不含 future。
3. actual 和 pred 都全量校验通过。

### Step 7：新增 Round35 总体验证脚本

新建：

```text
scripts/posttrain_validation_round35.py
```

整合检查：

1. Round34 预测文件可读。
2. `power_pred_final` 存在。
3. Round34 指标文件存在。
4. `round34_city_hourly_nrmse.csv` 使用城市总出力口径。
5. `round34_typical_sites.csv` 无跨类重复。
6. `round35_dashboard_prediction_consistency.csv` 全部 PASS。
7. 报告路径均在 `output/pv_pipeline/docs/`。
8. `光伏功率预测项目.md` 中包含 118、68、14 三类站点说明。
9. 项目报告中不把 0.3365% 作为正式核心指标。
10. Git 未追踪大体积 pkl 和 site_series JSON。

输出：

```text
output/pv_pipeline/docs/Round35_产物收口与可视化一致性验证报告.md
```

## 四、执行顺序

在 Cursor 中依次执行：

```bash
python scripts/export_interactive_dashboard_data.py
python scripts/check_dashboard_prediction_values_round35.py
python scripts/posttrain_validation_round35.py
```

如果修改了报告生成脚本，再执行：

```bash
python scripts/regenerate_project_report_round34.py
python scripts/posttrain_validation_round35.py
```

最后检查 Git：

```bash
git status --short
git ls-files | grep -E '\\.(pkl|joblib|parquet)$|site_series/|city_series\\.json|output/pv_pipeline/tables/'
```

## 五、验收标准

Round35 通过必须满足：

1. `round35_dashboard_prediction_consistency.csv` 所有站点 `PASS`。
2. `max_abs_diff_actual <= 1e-9`。
3. `max_abs_diff_pred <= 1e-9`。
4. `光伏功率预测项目.md` 明确说明：
   - 全部登记站点 118；
   - 有 test 结果站点 68；
   - 正常可排名站点 14。
5. 正式报告不把历史口径 `0.3365%` 作为核心结果。
6. 所有 Markdown 报告位于 `output/pv_pipeline/docs/`。
7. Git 不追踪大体积 pkl、site_series JSON 和 tables 输出。
8. 可视化页面默认不展示 future。

## 六、完成后需要回传的文件

请回传：

```text
output/pv_pipeline/docs/Round35_产物收口与可视化一致性验证报告.md
output/pv_pipeline/docs/Round35_可视化预测值一致性检查报告.md
output/pv_pipeline/metrics/round35_dashboard_prediction_consistency.csv
光伏功率预测项目.md
```

如果 Git 追踪内容有调整，也请回传：

```text
git status --short 的输出
```
