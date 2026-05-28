# Round34 修复 Round33 指标口径与最终产物一致性方案

## 一、目标

Round33 已经完成了异常站点、分布漂移、系统性偏差的识别，但本次检查发现最终指标和报告仍存在口径不一致问题。因此 Round34 的目标不是继续盲目调参，而是修复以下关键问题：

1. 修正全市逐小时 NRMSE 的计算方法。
2. 统一“全部登记站点”“有 test 结果站点”“正常可排名站点”的定义。
3. 修复 `site_validity` 中无评估数据站点被标为“正常评价”的问题。
4. 将 valid 学到的校准真正写入最终预测结果。
5. 重新生成站点指标、全市指标、典型站点、可视化数据和 `光伏功率预测项目.md`。
6. 保证可视化网页、CSV 指标、Markdown 报告三者口径一致。

## 二、当前 Round33 发现的问题

### 2.1 全市逐小时 NRMSE 计算错误

当前 `round33_city_hourly_nrmse.csv` 的逻辑是：

```text
对站点行逐行计算 RMSE，然后除以全市容量和
```

这不是“全市总出力 NRMSE”。

正确逻辑应为：

```text
每个时间点：
city_actual_t = sum(site_actual_t)
city_pred_t   = sum(site_pred_t)

city_RMSE = sqrt(mean((city_pred_t - city_actual_t)^2))

city_NRMSE = city_RMSE / city_capacity_sum * 100%
```

即必须先按 `time` 聚合全市功率，再计算 RMSE。

### 2.2 有效站点定义混乱

当前报告中写：

```text
有效评价站点数 = 68
```

但 `round33_site_metrics.csv` 中：

```text
exclude_from_ranking == 否
```

实际只有 18 个站点。

因此必须拆分三个概念：

| 概念 | 含义 |
|---|---|
| 全部登记站点 | 站点清单中的全部站点，例如 118 个 |
| 有 test 结果站点 | final eval 中实际有 test 6-19 点预测结果的站点，例如 68 个 |
| 正常可排名站点 | 有 test 结果，且不是无有效发电、分布漂移、系统性偏差的站点 |

后续报告中不得再把这三个概念混用。

### 2.3 无评估数据站点被误标为正常评价

例如 S001、S005 在 `site_validity` 中多项指标为 NaN，但 `site_status` 被标成“正常评价”。这会污染站点数量统计。

这些站点应标为：

```text
无测试预测结果
```

并且：

```text
exclude_from_ranking = 是
```

### 2.4 校准没有真正进入最终指标

`round33_site_metrics.csv` 和 `round33_bias_calibration_effect_test.csv` 中的 `before_nrmse` 基本一致，说明站点指标仍使用校准前 `power_pred`。

Round34 必须把校准后的预测写入最终字段：

```text
power_pred_final
```

所有最终指标、可视化、报告默认使用：

```text
power_pred_final
```

而不是原始 `power_pred`。

### 2.5 典型站点表重复

当前典型站点表里同一个站点可能同时出现在：

```text
预测最差
相对正确
```

Round34 要求一个站点只能属于一个典型类别，优先级：

```text
预测最好 > 预测最差 > 相对正确 > 样本少/异常说明
```

### 2.6 报告中 NRMSE 百分比存在放大 100 倍问题

CSV 中如果已经是百分数，例如：

```text
1.9652
```

报告应显示：

```text
1.97%
```

不能再乘 100 后显示为：

```text
196.52%
```

## 三、Cursor 修改步骤

### Step 1：新增统一预测字段选择函数

新增或修改：

```text
src/pv_forecasting/core/eval_frame.py
```

加入函数：

```python
def resolve_prediction_column(df: pd.DataFrame) -> str:
    for col in ["power_pred_final", "pred_calibrated", "power_pred_cal", "power_pred"]:
        if col in df.columns:
            return col
    raise KeyError("未找到预测功率列：power_pred_final/pred_calibrated/power_pred_cal/power_pred")
```

所有评估脚本中禁止直接写死 `power_pred`，必须使用：

```python
pred_col = resolve_prediction_column(df)
```

### Step 2：修复站点有效性表

修改：

```text
scripts/build_site_validity_round33.py
```

或新建：

```text
scripts/build_site_validity_round34.py
```

修复规则：

1. 先读取站点清单，得到全部登记站点。
2. 再读取 final eval，得到有 test 结果站点。
3. 对没有 test 结果的站点：

```python
site_status = "无测试预测结果"
exclude_from_ranking = "是"
exclude_reason = "final_eval 中无 test 6-19 点预测结果"
```

4. 对有 test 结果的站点再判断：

```python
if test_positive_rows_6_19 < 100 or test_actual_sum_mwh <= 1e-6:
    site_status = "测试期无有效发电"
elif abs(cf_mean_shift) >= 0.10 or abs(cf_p95_shift) >= 0.20:
    site_status = "测试期分布漂移"
elif pred_actual_ratio < 0.80 or pred_actual_ratio > 1.20:
    site_status = "系统性偏差"
else:
    site_status = "正常评价"
```

5. 输出：

```text
output/pv_pipeline/metrics/round34_site_validity.csv
```

6. 额外输出站点数量摘要：

```text
output/pv_pipeline/metrics/round34_site_count_summary.csv
```

字段：

```text
category,count,description
```

必须包含：

```text
全部登记站点
有test结果站点
正常可排名站点
测试期无有效发电站点
测试期分布漂移站点
系统性偏差站点
无测试预测结果站点
```

### Step 3：将校准真正写入 final 预测文件

修改：

```text
scripts/calibrate_station_bias_round33.py
```

或新建：

```text
scripts/apply_bias_calibration_round34.py
```

要求：

1. 读取：

```text
output/pv_pipeline/tables/distributed_predictions_v159.pkl
output/pv_pipeline/metrics/round33_bias_calibration_table.csv
```

2. 对 `train/valid/test` 都合并校准系数，但校准系数只能来源于 valid 学习结果。
3. 新增字段：

```text
power_pred_raw
power_pred_final
calibrated_ratio
calibration_applied
```

4. 计算：

```python
df["power_pred_raw"] = df["power_pred"]
df["power_pred_final"] = df["power_pred"] * df["calibrated_ratio"]
df["power_pred_final"] = df["power_pred_final"].clip(lower=0)
df["power_pred_final"] = np.minimum(df["power_pred_final"], df["capacity_mw"])
```

5. 如果某站点校准后 test NRMSE 比校准前差超过 1 个百分点，则该站点自动回退：

```python
if after_nrmse > before_nrmse + 1.0:
    power_pred_final = power_pred_raw
    calibration_applied = False
```

6. 输出：

```text
output/pv_pipeline/tables/distributed_predictions_final_round34.pkl
output/pv_pipeline/tables/distributed_predictions_final_eval_round34.pkl
output/pv_pipeline/metrics/round34_calibration_selection.csv
```

`final_eval_round34.pkl` 必须只包含：

```text
split == "test"
hour in 6..19
```

### Step 4：重写全市逐小时 NRMSE

新建：

```text
scripts/compute_round34_metrics.py
```

必须实现两个不同指标：

#### 4.1 全市总出力逐小时 NRMSE

按小时 `h`：

```python
sub = df_eval[df_eval["hour"] == h]

city_ts = sub.groupby("time").agg(
    actual_city_mw=("power_mw", "sum"),
    pred_city_mw=(pred_col, "sum"),
)

rmse = sqrt(mean((pred_city_mw - actual_city_mw) ** 2))
mae = mean(abs(pred_city_mw - actual_city_mw))
capacity_sum = sub.groupby("site_id")["capacity_mw"].first().sum()
nrmse = rmse / capacity_sum * 100
```

输出：

```text
output/pv_pipeline/metrics/round34_city_hourly_nrmse.csv
```

字段：

```text
hour
n_sites
n_timestamps
capacity_sum_MW
actual_sum_MWh
pred_sum_MWh
mae_city_MW
rmse_city_MW
nrmse_city_pct
bias_city_MW
pred_actual_ratio
scope
```

注意：

这里的 `MAE/RMSE` 是全市总出力误差，不是站点平均误差。

#### 4.2 站点平均逐小时 NRMSE

先对每个站点、每个小时算 NRMSE，再对站点取平均：

```python
site_hour_nrmse = rmse(site,hour) / capacity_mw(site) * 100
site_avg_hour_nrmse = mean(site_hour_nrmse)
```

输出：

```text
output/pv_pipeline/metrics/round34_site_hourly_nrmse.csv
output/pv_pipeline/metrics/round34_site_avg_hourly_nrmse.csv
```

报告中必须明确区分：

| 指标 | 含义 |
|---|---|
| 全市总出力 NRMSE | 先按时间把所有站点加总，再算城市总出力误差 |
| 站点平均 NRMSE | 先算单站点误差，再对站点平均 |

### Step 5：重算站点级指标

在 `scripts/compute_round34_metrics.py` 中同时输出：

```text
output/pv_pipeline/metrics/round34_site_metrics.csv
```

要求：

1. 默认使用 `power_pred_final`。
2. 站点级 NRMSE：

```text
NRMSE_site = RMSE_site / capacity_mw * 100%
```

3. 字段至少包含：

```text
site_id
site_name
county
install_group
capacity_MW
n_rows
test_positive_rows_6_19
test_zero_ratio_6_19_pct
mae_MW
rmse_MW
nrmse_pct
bias_MW
pred_actual_ratio
site_status
exclude_from_ranking
exclude_reason
```

### Step 6：修复典型站点表

在 `scripts/compute_round34_metrics.py` 中输出：

```text
output/pv_pipeline/metrics/round34_typical_sites.csv
```

规则：

1. 只从：

```python
exclude_from_ranking == "否"
```

的站点里选。

2. 一个站点只能属于一个类别。

3. 选择逻辑：

```python
best = nrmse 最低的 5 个
worst = 剩余站点中 nrmse 最高的 5 个
relative_correct = 剩余站点中 abs(pred_actual_ratio - 1) 最小的 5 个
```

4. 输出字段：

```text
类型
site_id
site_name
county
capacity_MW
n_rows
test_zero_ratio_6_19_pct
mae_MW
rmse_MW
nrmse_pct
pred_actual_ratio
```

### Step 7：修复项目报告生成逻辑

修改：

```text
scripts/regenerate_chinese_metrics.py
```

或新建：

```text
scripts/regenerate_project_report_round34.py
```

要求：

1. 只读取 Round34 文件：

```text
round34_site_count_summary.csv
round34_city_hourly_nrmse.csv
round34_site_avg_hourly_nrmse.csv
round34_site_metrics.csv
round34_typical_sites.csv
round34_site_validity.csv
round34_invalid_eval_sites.csv
round34_distribution_drift_sites.csv
round34_bias_sites.csv
```

2. 如果 Round34 文件不存在，直接报错，不允许回退到 Round33。

3. 报告中所有 NRMSE 已经是百分数，不允许再乘 100。

4. 报告中必须把站点数写清楚：

```text
全部登记站点：xxx
有 test 结果站点：xxx
正常可排名站点：xxx
测试期无有效发电：xxx
测试期分布漂移：xxx
系统性偏差：xxx
无测试预测结果：xxx
```

5. 删除“有效评价站点=68”这种模糊写法。

6. 训练结果中必须同时给出：

```text
全市总出力逐小时 NRMSE
站点平均逐小时 NRMSE
```

### Step 8：修复可视化导出

修改：

```text
scripts/export_interactive_dashboard_data.py
```

要求：

1. 默认读取：

```text
distributed_predictions_final_round34.pkl
```

2. 默认预测列使用：

```text
power_pred_final
```

3. 默认排除 future：

```python
df_vis = df[df["split"].isin(["train", "valid", "test"])]
```

4. 所有站点状态来自：

```text
round34_site_validity.csv
```

5. 典型站点来自：

```text
round34_typical_sites.csv
```

6. 页面中所有指标卡必须显示当前口径：

```text
当前统计：train/valid/test，不含 future；最终评价使用 test 2025-09-01~2025-12-31 6-19 点。
```

7. 可视化中“单站点全量历史样本数与测试集 NRMSE 关系”：
   - 横轴只保留全量历史样本数；
   - 不含 future；
   - 不含测试期无有效发电站点；
   - tooltip 中显示 `test_zero_ratio_6_19_pct`。

### Step 9：更新后验校验脚本

新建：

```text
scripts/posttrain_validation_round34.py
```

必须检查：

1. `distributed_predictions_final_round34.pkl` 存在且可读。
2. `distributed_predictions_final_eval_round34.pkl` 只包含 test 6-19。
3. `power_pred_final` 存在。
4. `power_pred_final >= 0`。
5. `power_pred_final <= capacity_mw`。
6. `round34_site_validity.csv` 中无 test 数据站点不允许标为正常评价。
7. `round34_site_metrics.csv` 中所有指标使用 `power_pred_final`。
8. `round34_city_hourly_nrmse.csv` 是按 time 聚合城市总出力后计算。
9. `round34_typical_sites.csv` 中 `site_id + 类型` 不重复，且 `site_id` 不跨类别重复。
10. Markdown 报告中的逐小时 NRMSE 与 CSV 一致。
11. 可视化 JSON 中 `pred_mw` 与 `power_pred_final` 一致。
12. 可视化 JSON 中 `actual_mw` 与 `power_mw` 一致。

输出：

```text
output/pv_pipeline/docs/Round34_指标口径与最终产物一致性验证报告.md
```

只要出现 FAIL，不允许生成最终项目报告。

## 四、执行顺序

在 Cursor 中按顺序执行：

```bash
python scripts/build_site_validity_round34.py
python scripts/apply_bias_calibration_round34.py
python scripts/compute_round34_metrics.py
python scripts/regenerate_project_report_round34.py
python scripts/export_interactive_dashboard_data.py
python scripts/posttrain_validation_round34.py
```

如果项目当前没有这些脚本，请按本方案新增。

## 五、验收标准

Round34 通过必须满足：

1. `posttrain_validation_round34.py` 全部 PASS。
2. `round34_site_count_summary.csv` 中站点分类数量自洽：

```text
全部登记站点 = 有test结果站点 + 无测试预测结果站点
有test结果站点 = 正常可排名站点 + 测试期无有效发电 + 测试期分布漂移 + 系统性偏差
```

3. `round34_city_hourly_nrmse.csv` 中城市 NRMSE 使用城市总出力聚合算法。
4. `round34_site_metrics.csv` 使用 `power_pred_final`。
5. `round34_typical_sites.csv` 无站点重复跨类别。
6. `光伏功率预测项目.md` 中不再出现 Round33 的错误数值。
7. 报告中 NRMSE 不再出现 100 倍放大问题。
8. 可视化页面默认不展示 future。
9. 可视化页面中的预测值来自 `power_pred_final`。

## 六、特别注意

本轮不要重新盲目训练模型。  
先修正 Round33 的最终产物链路：

```text
校准结果落盘 → 指标重算 → 报告重写 → 可视化同步 → 后验校验
```

只有在 Round34 口径完全修正后，才判断是否需要重新训练模型。
