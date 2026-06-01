# Cursor执行方案 Round72：重建全历史一致基线，并重新训练残差模型

## 一、目标

Round71 发现一个根本问题：

```text
power_pred_final 在训练集 train 上为空。
```

这导致所有基于训练集学习残差的模型存在口径错位：

```text
训练阶段：残差 = power_mw - power_pred
评估阶段：残差 = power_mw - power_pred_final
```

也就是说，训练和评估使用的基线预测列不是同一个东西。这个问题不解决，继续做 seasonal residual、noon residual、高误差站点 residual 都会学偏。

Round72 的目标是：

1. 为 train / valid / test 全部生成同口径的基线预测列。
2. 避免用 test 信息回填 train，防止泄漏。
3. 在一致基线之上重新训练残差模型。
4. 重点优化 10-14 点、高误差站点、季节分布差异。
5. 若新候选不优于 Round68 final，则继续保留 Round68 final。

本轮不是小修，而是修复训练残差模型的基础数据链路。

---

## 二、当前正式基线

当前正式结果：

```text
Round68 final
prediction column: power_pred_final
```

当前指标：

```text
site_mean_nrmse_6_19 = 10.58%
city_nrmse_6_19 = 4.13%
city_nrmse_10_14 = 5.94%
bias_6_19 = +0.52%
bias_10_14 = +5.60%
bad_sites_gt_1pp = 0
```

Round72 的候选必须与 Round68 final 比较。

---

## 三、硬性原则

- 不使用 test 集调参。
- 不修改指标公式。
- 不包含 future 数据。
- 不直接覆盖 Round68 final。
- 不允许用 test 信息构造 train 的基线预测。
- 不允许训练集残差基线列和评估基线列不一致。
- 所有候选必须真实不同于 baseline。
- 若 Round72 不优于 Round68 final，自动保留 Round68 final。

---

## 四、Round72 总体路线

本轮分四步：

```text
Step 1：构造全历史一致基线预测列
Step 2：验证一致基线无泄漏、无空值、与 final 口径一致
Step 3：基于一致基线训练保守残差候选
Step 4：valid 多窗口选择，test 最终评估
```

核心新增列：

```text
power_pred_consistent_base
```

这列必须在 train / valid / test 全部存在。

---

## 五、第一步：诊断当前预测列缺失和口径错位

### 5.1 新建脚本

新建：

```text
scripts/audit_prediction_column_consistency.py
```

输入：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
```

检查列：

```text
power_pred
power_pred_final
power_pred_round68_lgb_safe_blend
power_pred_round64_safe
```

如果某些列不存在，记录为 missing。

输出：

```text
output/pv_pipeline/round72/round72_prediction_column_audit.csv
output/pv_pipeline/round72/round72_prediction_column_audit_summary.json
```

检查内容：

```text
split
column
row_count
non_null_count
null_count
null_ratio
mean_pred
mean_actual
mae
rmse
nrmse
bias
```

必须明确回答：

```text
power_pred_final 是否在 train 为空？
train/valid/test 使用的可用预测列是否一致？
如果不一致，当前残差训练是否不可用？
```

---

## 六、第二步：构造全历史一致基线预测

### 6.1 新建配置文件

新建：

```text
configs/round72_consistent_base.yaml
```

建议内容：

```yaml
input_pkl: output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
output_dir: output/pv_pipeline/round72

baseline_final_col: power_pred_final
consistent_base_col: power_pred_consistent_base

target_col: power_mw
capacity_col: capacity_mw
split_col: split
site_col: site_id
time_col: datetime

exclude_future: true
eval_hours: [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]

oof:
  enabled: true
  time_folds:
    - train_end: "2023-06-30"
      valid_start: "2023-07-01"
      valid_end: "2023-12-31"
    - train_end: "2023-12-31"
      valid_start: "2024-01-01"
      valid_end: "2024-06-30"
    - train_end: "2024-06-30"
      valid_start: "2024-07-01"
      valid_end: "2024-12-31"
    - train_end: "2024-12-31"
      valid_start: "2025-01-01"
      valid_end: "2025-06-30"

model:
  type: lgb
  fallback_type: hgb
  target: capacity_normalized_power

guards:
  no_test_in_train_base: true
  no_future: true
  no_null_consistent_base: true
```

如果数据时间范围与上述 fold 不一致，脚本自动按时间分位构造 4 个 rolling folds，但必须保证：

```text
每个 fold 只用更早时间训练，预测更晚时间。
```

---

### 6.2 新建脚本

新建：

```text
scripts/build_round72_consistent_base_prediction.py
```

功能：

#### 对 train 段

使用时间滚动 out-of-fold 方式生成预测：

```text
只用历史数据训练，预测后续 train 时间片。
```

不能用同一行的真实值训练后再预测自己。

输出到：

```text
power_pred_consistent_base
```

#### 对 valid/test 段

优先使用当前正式：

```text
power_pred_final
```

但要确保列存在且非空。

#### 对缺失行

如果某些早期 train 行无法用 OOF 预测：

- 优先用最早可训练 fold 的模型预测；
- 如果仍失败，用 `power_pred` 作为 fallback；
- fallback 行必须打标：

```text
consistent_base_source = "fallback_power_pred"
```

不能静默填充。

#### 输出文件

```text
output/pv_pipeline/round72/round72_consistent_base_predictions.pkl
output/pv_pipeline/round72/round72_consistent_base_source_summary.csv
output/pv_pipeline/round72/round72_oof_fold_metrics.csv
output/pv_pipeline/round72/round72_consistent_base_quality.csv
```

---

## 七、第三步：一致基线质量校验

### 7.1 新建脚本

新建：

```text
scripts/validate_round72_consistent_base.py
```

输入：

```text
output/pv_pipeline/round72/round72_consistent_base_predictions.pkl
```

检查：

1. `power_pred_consistent_base` 在 train/valid/test 均非空。
2. 不包含 future。
3. valid/test 的 `power_pred_consistent_base` 与 `power_pred_final` 差异应为 0 或接近 0。
4. train 的 `power_pred_consistent_base` 不应全等于 `power_mw`，防止泄漏。
5. train 的 OOF 指标不应异常好。若 train OOF NRMSE 远低于 valid/test，必须警告。
6. fallback 行比例不能过高。

输出：

```text
output/pv_pipeline/round72/round72_consistent_base_validation.csv
output/pv_pipeline/round72/round72_consistent_base_validation.json
```

硬性通过条件：

```text
future_rows = 0
consistent_base_null_rows = 0
valid_test_diff_to_power_pred_final_max <= 1e-6
train_leakage_suspect = false
```

如果不通过，停止本轮，不训练残差模型。

---

## 八、第四步：基于一致基线训练残差模型

### 8.1 新建残差训练脚本

新建：

```text
scripts/train_round72_residual_on_consistent_base.py
```

输入：

```text
output/pv_pipeline/round72/round72_consistent_base_predictions.pkl
```

目标：

```text
y_true_norm = power_mw / capacity_mw
y_base_norm = power_pred_consistent_base / capacity_mw
residual_norm = y_true_norm - y_base_norm
```

残差裁剪：

```text
global: [-0.10, 0.10]
10-14: [-0.08, 0.08]
```

候选：

| 候选 | 说明 |
|---|---|
| `round72_season_residual` | 月份/季节残差 |
| `round72_noon_residual` | 10-14 点残差 |
| `round72_high_error_residual` | 高误差站点残差 |
| `round72_safe_blend` | valid 多窗口安全融合 |

候选列：

```text
power_pred_round72_season_residual
power_pred_round72_noon_residual
power_pred_round72_high_error_residual
power_pred_round72_safe_blend
```

注意：

```text
power_pred_round72_* = power_pred_final + residual_correction
```

最终候选必须仍然基于当前正式 `power_pred_final` 修正，而不是把 OOF train base 直接用于 test。

输出：

```text
output/pv_pipeline/round72/round72_residual_candidates.pkl
output/pv_pipeline/round72/round72_residual_model_training_summary.csv
output/pv_pipeline/round72/round72_residual_feature_importance.csv
```

---

## 九、第五步：valid 多窗口选择

新建：

```text
scripts/select_round72_candidate_multi_window.py
```

必须至少使用两个非 test 窗口：

```text
window_early
window_late
```

如果数据允许，建议：

```text
2025-05~2025-06
2025-07~2025-08
```

如果时间范围不支持，则从 train/valid 中按时间分段生成。

门控：

```text
bad_site_gt_1pp == 0
site_mean_nrmse_6_19 <= baseline - 0.10pp
city_nrmse_6_19 <= baseline + 0.05pp
city_nrmse_10_14 <= baseline
abs_bias_6_19 <= baseline + 0.20pp
abs_bias_10_14 <= baseline
candidate_diff_valid = true
```

输出：

```text
output/pv_pipeline/round72/round72_valid_window_compare.csv
output/pv_pipeline/round72/round72_candidate_decision.json
output/pv_pipeline/round72/round72_safe_blend_weights.csv
```

---

## 十、第六步：test 最终评估

新建：

```text
scripts/evaluate_round72_candidate_on_test.py
```

输出：

```text
output/pv_pipeline/round72/round72_test_overall_compare.csv
output/pv_pipeline/round72/round72_test_hourly_compare.csv
output/pv_pipeline/round72/round72_test_site_compare.csv
output/pv_pipeline/round72/round72_high_error_site_test_compare.csv
docs/Round72_重建全历史一致基线并重新训练残差模型报告.md
```

报告必须回答：

1. `power_pred_final` 在 train 为空的问题是否确认？
2. 是否成功生成 `power_pred_consistent_base`？
3. OOF train 预测是否存在泄漏？
4. valid/test 的 consistent base 是否与 final 口径一致？
5. 基于一致基线训练的残差模型是否优于 Round68 final？
6. 10-14 点是否改善？
7. 高误差站点是否改善？
8. 是否建议正式采用 Round72？
9. 如果仍无提升，是否可以认为现有特征下残差学习已接近瓶颈？

---

## 十一、统一入口

修改：

```text
scripts/run_full_pipeline.py
```

新增模式：

```bash
python scripts/run_full_pipeline.py --mode round72-consistent-base-residual
```

执行顺序：

```text
audit_prediction_column_consistency
build_round72_consistent_base_prediction
validate_round72_consistent_base
train_round72_residual_on_consistent_base
select_round72_candidate_multi_window
evaluate_round72_candidate_on_test
write Round72 report
```

---

## 十二、执行命令

优先执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/run_full_pipeline.py --mode round72-consistent-base-residual
```

如果统一入口尚未接好：

```bash
mkdir -p output/pv_pipeline/round72

python scripts/audit_prediction_column_consistency.py \
  --config configs/round72_consistent_base.yaml

python scripts/build_round72_consistent_base_prediction.py \
  --config configs/round72_consistent_base.yaml

python scripts/validate_round72_consistent_base.py \
  --config configs/round72_consistent_base.yaml

python scripts/train_round72_residual_on_consistent_base.py \
  --config configs/round72_consistent_base.yaml

python scripts/select_round72_candidate_multi_window.py \
  --config configs/round72_consistent_base.yaml

python scripts/evaluate_round72_candidate_on_test.py \
  --config configs/round72_consistent_base.yaml
```

---

## 十三、Git 提交

执行通过后提交：

```bash
git status

git add configs/round72_consistent_base.yaml
git add scripts/audit_prediction_column_consistency.py
git add scripts/build_round72_consistent_base_prediction.py
git add scripts/validate_round72_consistent_base.py
git add scripts/train_round72_residual_on_consistent_base.py
git add scripts/select_round72_candidate_multi_window.py
git add scripts/evaluate_round72_candidate_on_test.py
git add scripts/run_full_pipeline.py
git add docs/Round72_重建全历史一致基线并重新训练残差模型报告.md
git add output/pv_pipeline/round72/*.csv
git add output/pv_pipeline/round72/*.json

git commit -m "experiment: add round72 consistent baseline residual training"
git push origin HEAD
```

不要提交：

```text
*.pkl
*.parquet
*.joblib
```

---

## 十四、验收标准

Round72 通过标准：

1. 已确认并记录 `power_pred_final` 在 train 的缺失情况。
2. 已生成 `power_pred_consistent_base`。
3. train/valid/test 均有一致基线预测。
4. valid/test 的一致基线与当前 final 口径一致。
5. train 的一致基线无明显泄漏。
6. 基于一致基线重新训练残差候选。
7. valid 多窗口选择不使用 test。
8. test 只做最终评估。
9. 若 Round72 不如 Round68 final，继续保留 Round68 final。
10. 报告明确说明是否解决了残差训练基线错位问题。

---

## 十五、执行完成后发回

请发回：

```text
docs/Round72_重建全历史一致基线并重新训练残差模型报告.md
output/pv_pipeline/round72/round72_prediction_column_audit.csv
output/pv_pipeline/round72/round72_prediction_column_audit_summary.json
output/pv_pipeline/round72/round72_consistent_base_source_summary.csv
output/pv_pipeline/round72/round72_oof_fold_metrics.csv
output/pv_pipeline/round72/round72_consistent_base_validation.json
output/pv_pipeline/round72/round72_residual_model_training_summary.csv
output/pv_pipeline/round72/round72_valid_window_compare.csv
output/pv_pipeline/round72/round72_candidate_decision.json
output/pv_pipeline/round72/round72_test_overall_compare.csv
output/pv_pipeline/round72/round72_test_hourly_compare.csv
output/pv_pipeline/round72/round72_test_site_compare.csv
```

我会重点判断：

- 训练残差的基线错位是否彻底解决；
- 一致基线是否可靠；
- 残差模型是否真正提升；
- 是否值得进入 Round73 正式采用；
- 如果仍无提升，是否需要转向新增气象/NWP 数据。

