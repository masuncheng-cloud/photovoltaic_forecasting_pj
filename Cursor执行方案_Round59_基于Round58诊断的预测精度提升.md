# Cursor 执行方案 Round59：基于 Round58 诊断的预测精度提升

## 目标

当前指标计算方式已经确认可行，本轮不再修改指标公式。

本轮开始真正提升模型预测精度和预测效果，重点解决 Round58 确认的真实问题：

1. 10-14 点系统性高估。
2. 7 点、17 点低估明显。
3. low 场景系统性低估，clear_peak/mid 场景偏高。
4. 22 个站点存在明显系统性偏差。
5. S032 等站点存在辐照特征异常。
6. S003/S044/S069/S076/S077 等零功率站点不应污染普通模型。

核心原则：

- 不改指标公式。
- 不使用 test 集调参。
- 所有校准参数只用 train/valid，优先用 valid 选择。
- test 只做最终评估。
- 新版本如果不如旧版本，自动回退。
- 每个改动都要输出改动前后对比。

---

## 一、进入项目目录

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
mkdir -p output/pv_pipeline/models
mkdir -p output/pv_pipeline/calibration
mkdir -p output/pv_pipeline/diagnostics
mkdir -p output/pv_pipeline/logs
```

---

## 二、先备份当前最优结果

本轮修改预测结果生成逻辑，必须先保存当前 Round58 后的结果作为 baseline。

```bash
mkdir -p output/pv_pipeline/baselines/round58

cp output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
   output/pv_pipeline/baselines/round58/distributed_predictions_final_full.pkl

cp output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl \
   output/pv_pipeline/baselines/round58/distributed_predictions_final_eval.pkl

cp output/pv_pipeline/metrics/hourly_nrmse_consistent.csv \
   output/pv_pipeline/baselines/round58/hourly_nrmse_consistent.csv

cp output/pv_pipeline/metrics/site_metrics_consistent.csv \
   output/pv_pipeline/baselines/round58/site_metrics_consistent.csv

cp output/pv_pipeline/diagnostics/round57_error_by_site.csv \
   output/pv_pipeline/baselines/round58/round57_error_by_site.csv || true

cp output/pv_pipeline/diagnostics/round57_error_by_site_hour.csv \
   output/pv_pipeline/baselines/round58/round57_error_by_site_hour.csv || true
```

---

## 三、建立异常站点处理清单

新增配置：

```text
configs/site_quality_policy.yaml
```

内容：

```yaml
zero_actual_sites:
  # 实际测试期 6-19 长期为 0 或实际总量为 0，不参与普通模型校准
  - S003
  - S044
  - S069
  - S076
  - S077

low_confidence_geo_sites:
  - S116

capacity_mapping_review_sites:
  - S053
  - S012
  - S023

irradiance_review_sites:
  - S032
  - S046
  - S020
  - S019

calibration_exclude_sites:
  # 不参与站点级校准参数学习，避免用异常站点污染校准器
  - S003
  - S044
  - S069
  - S076
  - S077
```

要求：

- `zero_actual_sites` 不用于学习 bias 校准系数。
- 这些站点仍可保留在 final_full 中，但在普通精度对比中单独标记。
- 不要直接删除原始数据。

---

## 四、新增 valid 集校准数据构建脚本

新增：

```text
scripts/build_calibration_dataset.py
```

功能：

1. 读取当前 full prediction pkl。
2. 取 `split in ["train", "valid"]`。
3. 保留 6-19 点。
4. 排除 `site_quality_policy.yaml` 中的 `calibration_exclude_sites`。
5. 生成校准训练表。

输出：

```text
output/pv_pipeline/calibration/calibration_train_valid.pkl
output/pv_pipeline/calibration/calibration_valid.pkl
```

字段至少包括：

```text
timestamp
station_id
station_name
capacity_mw
split
hour
month
scene_v151
power_mw
power_pred_final
residual_mw = power_mw - power_pred_final
ratio = power_mw / max(power_pred_final, eps)
actual_norm = power_mw / capacity_mw
pred_norm = power_pred_final / capacity_mw
residual_norm = actual_norm - pred_norm
```

注意：

- 校准器学习时不能读取 test。
- 如果 full pkl 中 train/valid 没有 `power_pred_final`，则使用模型输出列，但必须明确记录。

---

## 五、新增 hour × scene 全局校准器

新增：

```text
scripts/train_hour_scene_calibrator.py
```

目标：

解决 Round58 发现的系统性偏差：

```text
7 点低估
10-14 点高估
17 点低估
low 场景低估
clear_peak/mid 场景高估
```

校准方式建议：

对每个 `(hour, scene_v151)` 学习一个缩放系数：

```text
factor = sum(actual_mw) / sum(pred_mw)
```

应用：

```text
pred_calibrated = pred * factor
```

但必须加入约束：

```text
factor_min = 0.75
factor_max = 1.35
min_samples = 100
shrinkage_k = 500
```

收缩公式：

```text
final_factor =
    (n / (n + k)) * raw_factor
    +
    (k / (n + k)) * global_factor
```

输出：

```text
output/pv_pipeline/calibration/hour_scene_calibrator.csv
```

字段：

```text
hour
scene_v151
n
actual_sum
pred_sum
raw_factor
global_factor
final_factor
factor_clipped
valid_before_nrmse
valid_after_nrmse
```

要求：

- 用 valid 集评估校准前后。
- 如果某个 `(hour, scene)` 在 valid 上变差，则该组 factor 回退为 1.0。

---

## 六、新增站点级 shrinkage 校准器

新增：

```text
scripts/train_site_bias_calibrator.py
```

目标：

解决 22 个站点系统性偏差。

对每个站点学习：

```text
site_factor = sum(actual_mw) / sum(pred_mw)
```

约束：

```text
factor_min = 0.70
factor_max = 1.40
min_positive_actual_sum = 10
min_samples = 300
shrinkage_k = 1000
```

收缩到全局或容量分组：

```text
final_factor =
    weight * raw_site_factor
    +
    (1 - weight) * group_factor

weight = n / (n + shrinkage_k)
```

容量分组：

```text
small: capacity < 3MW
medium: 3MW <= capacity < 10MW
large: capacity >= 10MW
```

输出：

```text
output/pv_pipeline/calibration/site_bias_calibrator.csv
```

字段：

```text
station_id
station_name
capacity_mw
capacity_bucket
n
actual_sum
pred_sum
raw_factor
group_factor
final_factor
factor_clipped
valid_before_nrmse
valid_after_nrmse
status
```

规则：

- `zero_actual_sites` 不训练 site factor。
- valid 后如果站点 NRMSE 变差超过 0.5 个百分点，则该站点 factor 回退为 1.0。
- S116 因坐标 low confidence，可参与但必须在输出中标记。

---

## 七、新增分段残差校准组合器

新增：

```text
scripts/apply_round59_calibration.py
```

读取：

```text
output/pv_pipeline/baselines/round58/distributed_predictions_final_full.pkl
output/pv_pipeline/calibration/hour_scene_calibrator.csv
output/pv_pipeline/calibration/site_bias_calibrator.csv
configs/site_quality_policy.yaml
```

生成候选预测列：

```text
power_pred_round59_hour_scene
power_pred_round59_site
power_pred_round59_combined
```

组合顺序：

```text
base_pred = power_pred_final
after_hour_scene = base_pred * hour_scene_factor
after_site = after_hour_scene * site_factor
clip to [0, capacity_mw]
```

物理裁剪：

```text
pred = max(pred, 0)
pred = min(pred, capacity_mw)
```

对 `zero_actual_sites`：

- 不参与校准训练。
- 应用时只使用 hour_scene factor，不使用 site factor。
- 如果 valid/test 实际长期为 0，可增加 `quality_flag`，但不要硬置 0，除非有停运确认。

输出：

```text
output/pv_pipeline/predictions/distributed_predictions_round59_candidates.pkl
```

---

## 八、valid 集选择与安全回退

新增：

```text
scripts/select_round59_final_prediction.py
```

候选列：

```text
power_pred_final                         # baseline Round58
power_pred_round59_hour_scene
power_pred_round59_site
power_pred_round59_combined
```

选择只使用 valid 集。

评价指标：

```text
score =
    0.40 * valid_site_mean_nrmse_6_19
  + 0.25 * valid_city_nrmse_6_19
  + 0.20 * valid_site_mean_nrmse_10_14
  + 0.15 * abs(valid_bias_6_19)
```

安全约束：

```text
valid_city_nrmse_6_19 不得比 baseline 高 0.5 个百分点以上
valid_site_mean_nrmse_6_19 不得比 baseline 高 0.5 个百分点以上
valid_10_14_city_nrmse 不得比 baseline 高 0.5 个百分点以上
valid_bias_abs 不得比 baseline 高 2 个百分点以上
```

如果候选不满足安全约束，回退 baseline。

输出：

```text
output/pv_pipeline/calibration/round59_model_selection_valid.csv
```

最终写入：

```text
power_pred_final_round59
```

并将选中的候选同步为正式：

```text
power_pred_final = power_pred_final_round59
```

注意：

- test 集不能参与选择。
- test 只用于最终报告。

---

## 九、重新生成 final/eval/metrics/dashboard

只做 eval/dashboard，不完整重训模型：

```bash
python scripts/build_calibration_dataset.py 2>&1 | tee output/pv_pipeline/logs/round59_build_calibration_dataset.log

python scripts/train_hour_scene_calibrator.py 2>&1 | tee output/pv_pipeline/logs/round59_train_hour_scene_calibrator.log

python scripts/train_site_bias_calibrator.py 2>&1 | tee output/pv_pipeline/logs/round59_train_site_bias_calibrator.log

python scripts/apply_round59_calibration.py 2>&1 | tee output/pv_pipeline/logs/round59_apply_calibration.log

python scripts/select_round59_final_prediction.py 2>&1 | tee output/pv_pipeline/logs/round59_select_final.log
```

然后重算正式结果：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode eval-only --force 2>&1 | tee output/pv_pipeline/logs/round59_eval_only.log

python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode dashboard-only --force 2>&1 | tee output/pv_pipeline/logs/round59_dashboard_only.log

python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode audit-only 2>&1 | tee output/pv_pipeline/logs/round59_audit_only.log
```

如果 `eval-only` 会覆盖 `power_pred_final` 回 baseline，需要修改 `run_full_pipeline.py`：

- 检测到 `distributed_predictions_round59_candidates.pkl` 和 `power_pred_final_round59` 时，优先使用 Round59 final。
- 不允许 eval-only 重新从旧 baseline 构建 final。

---

## 十、生成对比报告

新增：

```text
scripts/compare_round58_round59_metrics.py
```

对比：

```text
baseline: output/pv_pipeline/baselines/round58/distributed_predictions_final_eval.pkl
round59: output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl
```

输出：

```text
output/pv_pipeline/metrics/round59_compare_summary.csv
output/pv_pipeline/metrics/round59_compare_hourly.csv
output/pv_pipeline/metrics/round59_compare_site.csv
output/pv_pipeline/docs/Round59_预测精度提升执行报告.md
```

必须包含：

### 1. 总体对比

```text
site_mean_nrmse_6_19
city_nrmse_6_19
site_mean_nrmse_10_14
city_nrmse_10_14
bias_6_19
MAE
RMSE
```

### 2. 小时对比

重点看：

```text
7h
10h
11h
12h
13h
14h
17h
```

### 3. 站点对比

重点看：

```text
S012
S019
S032
S053
S071
S115
S116
S023
```

### 4. 变差保护

列出所有变差超过阈值的站点/小时。

---

## 十一、验收标准

本轮是否有效，不看单个数字好不好看，要看整体是否稳定提升。

必须满足：

```text
[PASS] 不使用 test 集选择校准参数
[PASS] valid 集选择结果有记录
[PASS] 10-14 city NRMSE 不高于 Round58
[PASS] 10-14 site_mean NRMSE 不高于 Round58，或最多上升 0.3 个百分点
[PASS] 7h bias 绝对值下降
[PASS] 17h bias 绝对值下降
[PASS] 6-19 city NRMSE 不高于 Round58 + 0.3 个百分点
[PASS] 6-19 site_mean NRMSE 不高于 Round58 + 0.3 个百分点
[PASS] overall bias 绝对值不高于 Round58 + 1 个百分点
[PASS] 如果候选变差，自动回退 baseline
[PASS] dashboard check 无 FAIL
[PASS] posttrain_validation 无 FAIL
```

如果所有候选都不如 baseline，则本轮应输出：

```text
Round59 未采用新校准，保持 Round58 baseline。
```

这也算正确结果，不能强行采用变差版本。

---

## 十二、生成 Round59 报告

新增：

```text
docs/Round59_预测精度提升执行报告.md
```

模板：

```markdown
# Round59 预测精度提升执行报告

## 1. 本轮目标

## 2. 本轮是否修改指标公式

未修改。沿用 Round58 确认口径。

## 3. 使用的数据

校准参数仅使用 train/valid，test 仅最终评估。

## 4. 新增校准器

### 4.1 hour × scene 校准器

### 4.2 site shrinkage 校准器

### 4.3 combined 校准

## 5. valid 集模型选择结果

## 6. test 集最终效果对比

### 6.1 总体指标

### 6.2 逐小时对比

### 6.3 重点站点对比

## 7. 是否采用 Round59

采用 / 回退 Round58。

## 8. 仍存在的问题

## 9. 下一步建议
```

---

## 十三、注意事项

1. 不要用 test 集调校准系数。
2. 不要为了改善 10-14 点让 6-19 整体明显变差。
3. 不要对零实际功率站点硬置 0，除非有停运确认。
4. 不要删除 Round58 baseline。
5. 不要再修改指标公式。
6. 如果校准器没有提升，必须回退。

