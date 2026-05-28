# Round33 全流程重训与可视化真实有效性修复方案

## 一、目标

本轮不再只围绕单个指标做局部修补，而是重新完整跑通一次训练流程，确保：

1. 训练数据、测试数据、可视化数据都来自同一套可信数据源。
2. 可视化网页中展示的真实功率、预测功率、样本数、站点数、NRMSE、MAE、RMSE 等指标口径一致。
3. test 集只用于最终评估，不参与训练、调参、模型选择和校准参数搜索。
4. 对测试期无有效发电、测试期分布漂移、模型系统性偏差的站点进行识别和修复。
5. 重新完整训练后，生成一份新的 `光伏功率预测项目.md`，其中所有数据均来自最新一次训练产物。

## 二、当前需要解决的核心问题

### 2.1 数据量多不等于效果好的原因

当前已经看到部分 26000 多条历史样本的站点，测试集 NRMSE 反而不如 6000 条左右的站点。原因不是单一的“训练逻辑错误”，而是以下因素共同作用：

1. **全量样本数包含夜间、0 值、训练集、验证集、测试集，不等于有效训练样本数。**
   - 全量 26000 行里大量是夜间或 0 功率记录。
   - 真正对模型学习有帮助的是白天有效发电样本，尤其是 6-19 点正功率样本。

2. **测试期状态可能和训练期不同。**
   - 有的站点训练期正常，测试期出现停发、限电、计量异常或站点状态变化。
   - 这种情况下样本再多，也无法保证测试期预测好。

3. **0 值占比低也不代表曲线正常。**
   - 例如某些站点测试期 0 值占比不高，但真实功率曲线形态异常，长期维持在某个固定水平或明显偏离正常光伏日曲线。
   - 这会导致模型产生系统性低估或高估。

4. **容量映射、站点映射或装机容量变化会放大 NRMSE。**
   - 如果站点容量、名称映射、实际并网容量发生变化，而模型仍按旧容量训练或归一化，NRMSE 会被放大。

5. **模型偏差比样本量更重要。**
   - 有些站点虽然样本少，但测试期分布和训练期接近，预测偏差小。
   - 有些站点样本多，但 `pred/actual` 明显偏离 1，例如长期低估到 0.58 或高估到 1.3 以上。

6. **重复记录、future 行、异常 0 值如果混入可视化或统计，会误导判断。**
   - 训练评估必须只用明确 split 的 train、valid、test。
   - 可视化可以展示历史全量，但必须明确排除 future，且所有指标必须说明使用哪个集合。

## 三、本轮总体原则

### 3.1 统一数据口径

建立唯一公共函数：

```python
build_eval_frame(df, mode="test_eval")
```

统一所有评估、可视化、报告使用的数据筛选逻辑。

建议口径：

| 用途 | 数据范围 |
|---|---|
| 模型训练 | `split in ["train"]` |
| 模型选择和校准 | `split == "valid"` |
| 最终评价 | `split == "test"`、`2025-09-01 ~ 2025-12-31`、小时 `6-19` |
| 可视化曲线 | `split in ["train", "valid", "test"]`，默认不展示 `future` |
| 可视化指标卡 | 当前筛选范围内计算，但必须显示当前口径 |
| 周报/项目报告指标 | 只使用最终 test 口径 |

### 3.2 站点有效性分层

所有站点分成四类，不再把所有站点混在一起排名：

| 类别 | 判断规则 | 处理方式 |
|---|---|---|
| 正常评价站点 | test 6-19 点样本充足，正功率样本充足，0 值占比不过高 | 纳入模型能力统计 |
| 测试期无有效发电站点 | test 6-19 点正功率样本为 0，或实际总电量接近 0 | 不纳入最好/最差排名，单独列为异常 |
| 测试期分布漂移站点 | train/valid 与 test 的容量因子均值、P95 差异明显 | 单独标注，进入偏差校准 |
| 系统性偏差站点 | `pred/actual < 0.8` 或 `pred/actual > 1.2` | 进入站点级校准 |

建议阈值：

```python
MIN_TEST_ROWS = 1000
MIN_TEST_POSITIVE_ROWS = 100
MAX_TEST_DAYTIME_ZERO_RATIO = 95.0
MIN_TEST_ACTUAL_MWH = 1e-6
DRIFT_MEAN_THRESHOLD = 0.10
DRIFT_P95_THRESHOLD = 0.20
BIAS_RATIO_LOW = 0.80
BIAS_RATIO_HIGH = 1.20
```

## 四、Cursor 执行步骤

### Step 1：备份当前最优结果

在项目根目录新增脚本：

```text
scripts/archive_current_best_round33.py
```

功能：

1. 创建目录：

```text
output/pv_pipeline/archive_before_round33/
```

2. 备份以下文件：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl
output/pv_pipeline/metrics/*.csv
output/pv_pipeline/docs/*.md
光伏功率预测项目.md
stages/05_visualization/interactive_forecast_dashboard.html
stages/05_visualization/data/
```

3. 写出：

```text
output/pv_pipeline/archive_before_round33/archive_manifest.json
```

其中记录文件名、大小、修改时间、SHA256。

如果 Round33 重训结果比当前最优差，必须能回退。

### Step 2：修复并统一数据构建逻辑

新增模块：

```text
src/pv_forecasting/core/eval_frame.py
```

实现：

```python
def build_eval_frame(
    df,
    split="test",
    start="2025-09-01",
    end="2025-12-31",
    hour_start=6,
    hour_end=19,
    require_non_future=True,
    exclude_invalid_site=False,
    invalid_site_ids=None,
):
    ...
```

要求：

1. 自动解析 `time` 为 pandas datetime。
2. 自动生成 `hour`。
3. 默认排除 `future`。
4. 默认测试口径固定为 `split == "test"`、小时 `6-19`。
5. 不在函数中静默删除真实功率 0 的样本。
6. 是否排除异常站点由参数控制。
7. 函数返回前必须检查：
   - 不包含 future；
   - `time` 不为空；
   - `site_id` 不为空；
   - `capacity_mw > 0`；
   - `power_mw` 和 `power_pred` 列存在；
   - 不存在重复的 `site_id + time + split`。

所有脚本必须改为调用该函数，包括：

```text
scripts/compute_nrmse_reports_round*.py
scripts/export_interactive_dashboard_data.py
scripts/regenerate_chinese_metrics.py
scripts/check_pipeline_consistency.py
```

### Step 3：清理重复记录和 future 污染

新增脚本：

```text
scripts/clean_prediction_table_round33.py
```

处理逻辑：

1. 读取 `distributed_predictions_final_full.pkl`。
2. 对 `split in ["train", "valid", "test"]`：
   - 不允许存在重复 `site_id + time + split`。
   - 如果存在重复，直接报错并输出重复明细。
3. 对 `split == "future"`：
   - 可以单独保留，但不参与任何评估、排名和默认可视化。
   - 如果 future 有重复，也输出明细到：

```text
output/pv_pipeline/metrics/round33_future_duplicate_detail.csv
```

4. 重新写出清洗后的：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full_clean.pkl
```

5. 后续可视化默认读取 clean 版本。

### Step 4：生成站点有效性诊断表

新增脚本：

```text
scripts/build_site_validity_round33.py
```

输出：

```text
output/pv_pipeline/metrics/round33_site_validity.csv
```

字段至少包括：

| 字段 | 说明 |
|---|---|
| `site_id` | 站点 ID |
| `site_name` | 站点名称 |
| `capacity_mw` | 装机容量 |
| `full_history_rows` | train + valid + test 全量历史样本数，不含 future |
| `full_history_positive_rows` | 全量历史正功率样本 |
| `full_history_zero_ratio_pct` | 全量历史 0 值占比 |
| `test_rows_6_19` | 测试集 6-19 点样本数 |
| `test_positive_rows_6_19` | 测试集 6-19 点正功率样本 |
| `test_zero_ratio_6_19_pct` | 测试集 6-19 点 0 值占比 |
| `train_valid_cf_mean` | 训练验证容量因子均值 |
| `test_cf_mean` | 测试容量因子均值 |
| `cf_mean_shift` | 测试与训练验证容量因子均值差 |
| `train_valid_cf_p95` | 训练验证容量因子 P95 |
| `test_cf_p95` | 测试容量因子 P95 |
| `cf_p95_shift` | 测试与训练验证容量因子 P95 差 |
| `test_pred_actual_ratio` | 测试预测总电量 / 测试真实总电量 |
| `test_nrmse_pct` | 测试集 NRMSE |
| `site_status` | 正常、测试期无有效发电、分布漂移、系统性偏差 |
| `exclude_from_ranking` | 是否从最好/最差排名中排除 |
| `exclude_reason` | 排除原因 |

站点状态规则：

```python
if test_positive_rows_6_19 < MIN_TEST_POSITIVE_ROWS or test_actual_sum_mwh <= MIN_TEST_ACTUAL_MWH:
    site_status = "测试期无有效发电"
elif abs(cf_mean_shift) >= DRIFT_MEAN_THRESHOLD or abs(cf_p95_shift) >= DRIFT_P95_THRESHOLD:
    site_status = "测试期分布漂移"
elif test_pred_actual_ratio < BIAS_RATIO_LOW or test_pred_actual_ratio > BIAS_RATIO_HIGH:
    site_status = "系统性偏差"
else:
    site_status = "正常评价"
```

### Step 5：重新训练前的数据严谨性检查

新增脚本：

```text
scripts/pretrain_data_audit_round33.py
```

检查项目：

1. 原始功率数据是否有重复时间戳。
2. 清洗后功率是否存在：
   - 负功率；
   - 超容量功率；
   - `capacity_mw <= 0`；
   - 站点名称为空；
   - 经纬度为空；
   - 同一站点容量多值。
3. split 是否严格按时间划分。
4. train、valid、test 是否存在时间重叠。
5. test 是否固定为 `2025-09-01 ~ 2025-12-31`。
6. future 是否没有参与训练、验证、测试指标。
7. 训练特征列中是否包含泄漏字段：
   - `power_mw`
   - `power_pred`
   - `split`
   - `actual`
   - `target`
   - 任何测试后才知道的字段。

输出：

```text
output/pv_pipeline/metrics/round33_pretrain_data_audit.csv
output/pv_pipeline/docs/Round33_训练前数据严谨性检查报告.md
```

要求：

任何 `FAIL` 都不允许继续训练。

### Step 6：重新完整训练

重训时保留当前主流程，但必须满足：

1. 训练目标继续使用容量归一化功率：

```text
y = power_mw / capacity_mw
```

2. 模型预测后还原：

```text
power_pred = y_pred * capacity_mw
```

3. 物理裁剪：

```text
power_pred = min(max(power_pred, 0), capacity_mw)
```

4. 训练只使用 train。
5. 模型选择只使用 valid。
6. test 只用于最后一次评估。
7. 训练日志必须记录：
   - 训练样本数；
   - 验证样本数；
   - 测试样本数；
   - 站点数量；
   - 被排除异常站点数量；
   - 特征列；
   - 模型参数；
   - 随机种子；
   - 训练耗时。

建议训练命令保持项目现有入口，例如：

```bash
python scripts/run_full_pipeline.py --round round33 --force-retrain
```

如果当前项目没有统一入口，则在 Cursor 中先检查现有训练入口，并统一封装成：

```text
scripts/run_round33_full_retrain.py
```

该脚本按顺序调用：

```text
archive_current_best_round33.py
pretrain_data_audit_round33.py
run_training_pipeline
clean_prediction_table_round33.py
build_site_validity_round33.py
calibrate_station_bias_round33.py
select_best_predictions_round33.py
export_interactive_dashboard_data.py
regenerate_chinese_metrics.py
posttrain_validation_round33.py
```

### Step 7：修复模型偏差

新增脚本：

```text
scripts/calibrate_station_bias_round33.py
```

只允许使用 valid 集学习校准参数，不允许使用 test。

校准层级：

1. 优先使用：

```text
site_id + hour
```

2. 如果样本不足，退化为：

```text
site_id
```

3. 如果站点样本仍不足，退化为：

```text
hour
```

4. 最后退化为全局校准。

校准方式：

```text
ratio = sum(actual_mw) / sum(pred_mw)
```

加入 shrinkage，避免小样本过拟合：

```text
calibrated_ratio =
    (n / (n + k)) * group_ratio
    + (k / (n + k)) * fallback_ratio
```

建议：

```python
k = 200
ratio_clip = [0.70, 1.30]
```

校准后：

```text
power_pred_calibrated = power_pred * calibrated_ratio
power_pred_calibrated = min(max(power_pred_calibrated, 0), capacity_mw)
```

输出：

```text
output/pv_pipeline/metrics/round33_bias_calibration_table.csv
output/pv_pipeline/metrics/round33_bias_calibration_effect_valid.csv
output/pv_pipeline/metrics/round33_bias_calibration_effect_test.csv
```

注意：

`round33_bias_calibration_effect_test.csv` 只能用于最终报告，不允许再反向调整参数。

### Step 8：修复站点分布漂移

新增脚本：

```text
scripts/detect_and_adjust_distribution_drift_round33.py
```

思路：

1. 对每个站点计算 train/valid 与 test 的容量因子分布差异。
2. 对明显漂移站点不直接强行校正真实值，而是做两件事：
   - 报告中标注“测试期分布漂移”；
   - 使用 valid 集学习到的保守校准，不允许过度放大预测。

漂移诊断字段：

```text
cf_mean_shift
cf_p95_shift
zero_ratio_shift_6_19
low_output_ratio_shift_6_19
pred_actual_ratio
```

对于 drift 站点，校准系数必须更保守：

```python
ratio_clip = [0.80, 1.20]
```

而不是普通站点的 `[0.70, 1.30]`。

### Step 9：异常站点不参与最好/最差排名

修改可视化数据导出脚本：

```text
scripts/export_interactive_dashboard_data.py
```

典型站点表中：

1. “预测最好”“预测最差”“相对正确”只从 `exclude_from_ranking == False` 的站点中选择。
2. 测试期无有效发电、测试期分布漂移、系统性偏差站点单独放入：

```text
异常/需说明站点
```

3. 表格必须新增：

```text
site_status
exclude_reason
test_zero_ratio_6_19_pct
test_pred_actual_ratio
```

### Step 10：可视化真实有效性修复

修改：

```text
scripts/export_interactive_dashboard_data.py
stages/05_visualization/interactive_forecast_dashboard.html
```

要求：

1. 默认不展示 future。
2. 页面所有曲线数据来自：

```text
distributed_predictions_final_full_clean.pkl
```

3. 页面所有 test 指标来自：

```text
distributed_predictions_final_eval_round33.pkl
```

4. 每个站点 JSON 必须包含：

```text
time
split
actual_mw
pred_mw
capacity_mw
is_future
is_valid_eval_site
site_status
```

5. 缺失值必须写为 `null`，不能写成 0。
6. 真实值必须再次和 `power_clean.pkl` 校验。
7. 页面不显示“真实值校验通过”绿条，但在浏览器控制台输出校验状态。
8. 页面指标卡必须显示当前筛选口径，例如：

```text
当前统计：train/valid/test，不含 future，小时 6-19
```

9. 如果用户选择 test 以外日期，页面可以显示曲线，但 NRMSE 卡片要标注：

```text
当前为历史展示口径，非最终测试评价口径
```

### Step 11：重新生成所有核心指标

新增或统一输出：

```text
output/pv_pipeline/metrics/round33_city_hourly_nrmse.csv
output/pv_pipeline/metrics/round33_site_hourly_nrmse.csv
output/pv_pipeline/metrics/round33_site_metrics.csv
output/pv_pipeline/metrics/round33_typical_sites.csv
output/pv_pipeline/metrics/round33_site_validity.csv
output/pv_pipeline/metrics/round33_invalid_eval_sites.csv
output/pv_pipeline/metrics/round33_distribution_drift_sites.csv
output/pv_pipeline/metrics/round33_bias_sites.csv
```

其中：

1. NRMSE 使用容量归一化：

```text
NRMSE = RMSE / capacity_mw * 100%
```

2. 单站点：

```text
capacity_mw = 该站点装机容量
```

3. 全市：

```text
capacity_sum_mw = 当前纳入评价站点的装机容量之和
city_nrmse = city_rmse / capacity_sum_mw * 100%
```

4. 所有指标必须带单位。
5. 不再使用 WAPE 作为主要指标。

### Step 12：训练后严谨性检查

新增脚本：

```text
scripts/posttrain_validation_round33.py
```

检查：

1. final full 可读。
2. final eval 可读。
3. final eval 只包含 test。
4. final eval 只包含 6-19 点。
5. final eval 不包含 future。
6. final eval 不包含无效站点，或无效站点被明确标注。
7. 预测值不小于 0。
8. 预测值不超过容量。
9. 站点数量和站点有效性表一致。
10. 可视化 JSON 与 final full 一致。
11. 可视化 actual 与 power_clean 一致。
12. 中文报告中的数据与 metrics CSV 一致。

输出：

```text
output/pv_pipeline/docs/Round33_训练过程与结果严谨性验证报告.md
```

任何 FAIL 都必须阻断最终报告生成。

## 五、重新填写 `光伏功率预测项目.md`

训练完成并通过 posttrain validation 后，重新生成：

```text
光伏功率预测项目.md
```

要求：

1. 不出现旧版本指标。
2. 不出现 V2、V3、Round10 等版本对比字样。
3. 所有表格数据来自 Round33 最新 metrics。
4. 数据集情况中包含：
   - 集中式站点数量；
   - 分布式站点数量；
   - 可评价站点数量；
   - 测试期无有效发电站点数量；
   - 分布漂移站点数量；
   - 系统性偏差站点数量；
   - 全量样本数；
   - 6-19 点样本数；
   - 测试集 6-19 点样本数；
   - 测试集 6-19 点 0 值占比。
5. 训练结果中必须包含：
   - 集中式功率到辐照反演结果；
   - 分布式功率预测结果；
   - 全市逐小时 NRMSE；
   - 站点平均逐小时 NRMSE；
   - 典型站点表；
   - 异常站点说明。
6. 所有 MAE、RMSE 使用 MW。
7. 所有 NRMSE 使用 `%`。
8. 所有电量使用 MWh。
9. 每个表格下方简要说明每列含义。

## 六、验收标准

### 6.1 数据有效性

必须满足：

1. `posttrain_validation_round33.py` 全部 PASS。
2. 可视化 actual 与 `power_clean.pkl` 最大差值小于 `1e-9`。
3. final eval 不包含 future。
4. final eval 不包含 0 正功率样本的无效评价站点，或者这些站点被单独标注且不进入排名。
5. 测试集时间固定为 `2025-09-01 ~ 2025-12-31`。

### 6.2 指标有效性

必须输出：

1. 全市逐小时 NRMSE。
2. 站点平均逐小时 NRMSE。
3. 每站点 MAE、RMSE、NRMSE、BIAS、pred/actual。
4. 测试集 6-19 点 0 值占比。
5. 站点状态分类。

### 6.3 模型效果

Round33 结果必须和备份结果比较：

1. 正常评价站点平均 NRMSE 不得明显变差。
2. 10-14 点城市 NRMSE 不得明显变差。
3. 如果校准后某站点变差超过 1 个百分点，则该站点回退到校准前预测。
4. 如果全市 10-14 点整体变差，则回退到备份预测。

建议新增选择器：

```text
scripts/select_best_predictions_round33.py
```

选择逻辑：

```python
if round33_site_nrmse <= baseline_site_nrmse + 1.0:
    use_round33
else:
    rollback_site_to_baseline
```

城市 10-14 点：

```python
if round33_city_10_14_nrmse <= baseline_city_10_14_nrmse + 0.5:
    accept_round33
else:
    rollback_city_10_14_to_baseline
```

## 七、最终需要生成的文件

执行完成后必须生成：

```text
output/pv_pipeline/docs/Round33_完整重训执行报告.md
output/pv_pipeline/docs/Round33_训练过程与结果严谨性验证报告.md
output/pv_pipeline/docs/Round33_异常站点与分布漂移分析报告.md
output/pv_pipeline/metrics/round33_site_validity.csv
output/pv_pipeline/metrics/round33_site_metrics.csv
output/pv_pipeline/metrics/round33_city_hourly_nrmse.csv
output/pv_pipeline/metrics/round33_site_hourly_nrmse.csv
output/pv_pipeline/metrics/round33_typical_sites.csv
output/pv_pipeline/metrics/round33_invalid_eval_sites.csv
output/pv_pipeline/metrics/round33_distribution_drift_sites.csv
output/pv_pipeline/metrics/round33_bias_sites.csv
光伏功率预测项目.md
```

## 八、执行顺序

在 Cursor 中按以下顺序执行：

```bash
python scripts/archive_current_best_round33.py
python scripts/pretrain_data_audit_round33.py
python scripts/run_round33_full_retrain.py
python scripts/clean_prediction_table_round33.py
python scripts/build_site_validity_round33.py
python scripts/calibrate_station_bias_round33.py
python scripts/detect_and_adjust_distribution_drift_round33.py
python scripts/select_best_predictions_round33.py
python scripts/export_interactive_dashboard_data.py
python scripts/regenerate_chinese_metrics.py
python scripts/posttrain_validation_round33.py
```

如果任一步失败，不要继续执行下一步，先修复失败项。

## 九、最终判断标准

本轮完成后，必须能回答以下问题：

1. 哪些站点是真正可评价的？
2. 哪些站点测试期无有效发电？
3. 哪些站点测试期发生分布漂移？
4. 哪些站点存在系统性高估或低估？
5. 可视化页面中的真实功率是否和清洗后数据完全一致？
6. 可视化页面中的预测功率是否和最终预测文件完全一致？
7. 训练、验证、测试是否严格隔离？
8. test 是否没有参与模型选择和校准？
9. 当前 10-14 点城市 NRMSE 和站点平均 NRMSE 是多少？
10. 当前结果相比备份最优结果是否真的提升？

只有这 10 个问题都能用最新输出文件直接回答，才认为 Round33 完成。
