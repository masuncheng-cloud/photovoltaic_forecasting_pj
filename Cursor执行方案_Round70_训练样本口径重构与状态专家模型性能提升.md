# Cursor执行方案 Round70：训练样本口径重构与状态专家模型性能提升

## 一、目标

Round69 已正式保留 Round68 final 作为当前最优基线，但 Round69 的新模型候选失败。失败不应简单解释为“模型已经到极限”，因为报告暴露出训练链路中几个关键问题：

1. 训练集正样本率约 45%，valid/test 分别约 84%/68%，训练分布与评估分布明显不一致。
2. 新模型出现系统性负偏，说明训练样本、权重或目标约束存在问题。
3. `residual_lgb` 和 `high_error_lgb` 完全等于 baseline，疑似候选列生成、替换或门控链路没有真实生效。
4. 高误差站点尚未做充分归因，不能直接判断为“气象不可预报”。

本轮目标是：**重新构建训练样本口径和模型训练链路，训练真正可用的状态专家模型和高误差站点模型，优先提升模型预测效果。**

---

## 二、硬性原则

- 当前正式基线：`Round68 final`，即当前 `power_pred_final`。
- 不使用 test 集调参。
- 不修改指标公式。
- 不包含 future 数据。
- 训练样本默认只使用评估一致的 6-19 点。
- 所有候选预测列必须真实不同于 baseline，否则判为无效候选。
- 如果 Round70 不优于 Round68 final，必须保留 Round68 final。
- 本轮不以可视化、报告文字为主，重点是模型性能。

---

## 三、Round70 总体技术路线

本轮一次性训练 5 类候选：

| 候选 | 目的 |
|---|---|
| `round68_final` | 当前正式基线 |
| `active_state_lgb` | 先判断有效发电状态，再回归功率 |
| `noon_bias_constrained_lgb` | 专门降低 10-14 点高估和 NRMSE |
| `high_error_site_expert` | 针对高误差站点单独建模 |
| `stacked_safe_blend` | 在 valid 上安全融合多个候选 |

核心思路：

```text
6-19 点一致训练样本
  -> 发电状态分类 active/weak/inactive
  -> 分时段专家回归
  -> 高误差站点专家模型
  -> valid 安全融合
  -> test 最终评估
```

---

## 四、配置文件

新建：

```text
configs/round70_state_expert_model.yaml
```

建议内容：

```yaml
baseline_col: power_pred_final
target_col: power_mw
capacity_col: capacity_mw
split_col: split
site_col: site_id
time_col: datetime

exclude_future: true
train_hours: [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
eval_hours: [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
focus_hours: [10, 11, 12, 13, 14]

active_threshold:
  min_mw: 0.02
  capacity_ratio: 0.02

time_blocks:
  dawn: [6, 7, 8]
  morning: [9, 10]
  noon: [11, 12, 13, 14]
  afternoon: [15, 16]
  dusk: [17, 18, 19]

sample_weight:
  base: 1.0
  focus_10_14: 2.0
  dawn_dusk: 1.3
  high_error_site: 1.8
  weak_power: 1.4
  inactive: 0.5
  max_weight: 3.0
  min_weight: 0.3

candidate_guards:
  bad_site_gt_1pp_max: 0
  site_mean_nrmse_improve_min_pp: 0.10
  city_nrmse_6_19_max_worse_pp: 0.05
  city_nrmse_10_14_must_not_worse: true
  abs_bias_6_19_max_worse_pp: 0.30
  abs_bias_10_14_max_worse_pp: 0.30
  require_candidate_diff_min_mw: 1.0e-6

models:
  classifier: lgb
  regressors: [lgb, hgb, ridge]
```

---

## 五、训练样本口径重构

### 5.1 新建训练表脚本

新建：

```text
scripts/build_round70_training_table.py
```

输入：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
```

要求：

1. 排除 future：

```python
df = df[df["split"] != "future"].copy()
```

2. 只保留 6-19 点：

```python
df = df[df["hour"].between(6, 19)].copy()
```

3. 只保留容量有效站点：

```python
capacity_mw > 0
```

4. 构造发电状态标签：

```text
active_threshold_mw = max(0.02 * capacity_mw, 0.02 MW)

inactive: power_mw <= 0
weak: 0 < power_mw < active_threshold_mw
active: power_mw >= active_threshold_mw
```

5. 构造目标：

```text
y_norm = power_mw / capacity_mw
residual_norm = y_norm - power_pred_final / capacity_mw
```

6. 构造 train/valid/test 分布统计，重点输出：

```text
每个 split 的行数
正样本率
weak 样本率
inactive 样本率
每小时样本数
每小时正样本率
每站点样本数
每站点 6-19 点 0 值占比
```

输出：

```text
output/pv_pipeline/round70/round70_training_table.parquet
output/pv_pipeline/round70/round70_training_distribution_by_split.csv
output/pv_pipeline/round70/round70_training_distribution_by_hour.csv
output/pv_pipeline/round70/round70_training_distribution_by_site.csv
output/pv_pipeline/round70/round70_feature_inventory.csv
```

如果训练集正样本率仍明显低于 valid/test，报告中必须解释原因。

---

## 六、候选有效性检查

新增公共脚本：

```text
scripts/check_candidate_prediction_diff.py
```

功能：

对任意候选列与 baseline 比较：

```text
max_abs_diff
mean_abs_diff
changed_rows
changed_ratio
changed_sites
```

输出：

```text
output/pv_pipeline/round70/round70_candidate_diff_check.csv
```

要求：

- 如果候选列与 baseline 完全相同，必须标记为 `INVALID_IDENTICAL_TO_BASELINE`。
- 这一步专门防止 Round69 中 `residual_lgb`、`high_error_lgb` 等于 baseline 却被当作候选的问题。

---

## 七、发电状态分类模型

### 7.1 新建脚本

```text
scripts/train_round70_active_state_model.py
```

目标：

```text
state_label: inactive / weak / active
```

特征：

```text
hour
month
dayofyear
capacity_mw
latitude
longitude
g_blend_pred
clear_sky_ghi
clear_sky_index
temperature
humidity
wind_speed
solar_elevation
site_zero_ratio_6_19
site_positive_count_train_valid
site_pr_median
site_quality_score
power_pred_final / capacity_mw
```

输出：

```text
output/pv_pipeline/round70/round70_active_state_valid_metrics.csv
output/pv_pipeline/round70/round70_active_state_test_metrics.csv
output/pv_pipeline/round70/round70_active_state_predictions.parquet
```

指标：

```text
accuracy
macro_f1
active_recall
weak_recall
inactive_precision
```

注意：

- 分类器只用 train 训练，valid 选择阈值。
- test 只评估。

---

## 八、状态专家回归模型

### 8.1 新建脚本

```text
scripts/train_round70_state_expert_regressors.py
```

训练逻辑：

1. 按 `time_block` 训练专家模型：

```text
dawn / morning / noon / afternoon / dusk
```

2. 按 `predicted_state` 或 `actual_state` 训练状态专家：

```text
active / weak / inactive
```

训练时可用 actual_state，预测 valid/test 时只能用 classifier 的 predicted_state。

3. 每个专家预测 `y_norm`，再还原：

```text
power_pred = clip(y_pred_norm * capacity_mw, 0, capacity_mw)
```

候选列：

```text
power_pred_round70_active_state_lgb
```

要求：

- inactive 状态不能简单全部置 0，必须允许早晚弱发电存在；
- 可以设软上限，例如 inactive 状态预测不超过历史该小时 P90 弱发电值；
- 不允许 6、7、17、18、19 点大量硬贴 0。

输出：

```text
output/pv_pipeline/round70/round70_state_expert_training_summary.csv
output/pv_pipeline/round70/round70_candidates.pkl
```

---

## 九、10-14 点 bias 约束模型

### 9.1 新建脚本

```text
scripts/train_round70_noon_bias_constrained_model.py
```

目标：

重点优化：

```text
10, 11, 12, 13, 14 点
```

但不能让其他小时明显恶化。

训练方式：

1. 对 10-14 点样本提高权重：

```text
weight = 2.0
```

2. 加入 bias 约束选择：

valid 上候选必须满足：

```text
abs_bias_10_14 <= baseline_abs_bias_10_14
city_nrmse_10_14 <= baseline_city_nrmse_10_14
site_mean_nrmse_10_14 <= baseline_site_mean_nrmse_10_14
```

3. 输出候选列：

```text
power_pred_round70_noon_bias_lgb
```

输出：

```text
output/pv_pipeline/round70/round70_noon_bias_valid_compare.csv
output/pv_pipeline/round70/round70_noon_bias_test_compare.csv
```

---

## 十、高误差站点专家模型

### 10.1 新建脚本

```text
scripts/train_round70_high_error_site_expert.py
```

高误差站点定义：

基于 valid，而不是 test：

```text
valid site_nrmse 排名前 15
或 valid site_nrmse > 12%
```

训练逻辑：

1. 对高误差站点训练专用模型。
2. 对非高误差站点保持 baseline。
3. 对每个高误差站点，在 valid 上决定是否采用专家模型。
4. 如果专家模型使该站点 valid NRMSE 下降至少 0.5pp，且不造成 city_nrmse 明显变差，则采用。

输出候选列：

```text
power_pred_round70_high_error_expert
```

输出：

```text
output/pv_pipeline/round70/round70_high_error_site_list.csv
output/pv_pipeline/round70/round70_high_error_expert_valid_compare.csv
output/pv_pipeline/round70/round70_high_error_expert_test_compare.csv
```

---

## 十一、安全融合与最终候选选择

### 11.1 新建脚本

```text
scripts/select_round70_final_candidate.py
```

候选：

```text
power_pred_final
power_pred_round70_active_state_lgb
power_pred_round70_noon_bias_lgb
power_pred_round70_high_error_expert
power_pred_round70_stacked_safe_blend
```

融合方式：

```text
P_blend = baseline + w1*(active_state - baseline)
                 + w2*(noon_bias - baseline)
                 + w3*(high_error - baseline)
```

权重在 valid 上选择：

```text
w ∈ [0, 0.25, 0.50, 0.75, 1.00]
```

选择粒度：

```text
site_id + time_block
```

### 11.2 valid 门控

候选必须满足：

```text
bad_site_gt_1pp == 0
site_mean_nrmse_6_19 <= baseline - 0.10pp
city_nrmse_6_19 <= baseline + 0.05pp
city_nrmse_10_14 <= baseline
abs_bias_6_19 <= baseline + 0.30pp
abs_bias_10_14 <= baseline + 0.30pp
candidate_diff_check != INVALID
```

输出：

```text
output/pv_pipeline/round70/round70_valid_candidate_compare.csv
output/pv_pipeline/round70/round70_candidate_decision.json
output/pv_pipeline/round70/round70_stacked_blend_weights.csv
```

---

## 十二、test 最终评估

新建：

```text
scripts/evaluate_round70_candidate_on_test.py
```

输出：

```text
output/pv_pipeline/round70/round70_test_overall_compare.csv
output/pv_pipeline/round70/round70_test_hourly_compare.csv
output/pv_pipeline/round70/round70_test_site_compare.csv
output/pv_pipeline/round70/round70_high_error_site_test_compare.csv
docs/Round70_训练样本口径重构与状态专家模型性能提升报告.md
```

报告必须回答：

1. 训练样本是否已统一为 6-19 点？
2. 训练/valid/test 正样本率差异是否仍存在？
3. 候选预测列是否真实不同于 baseline？
4. active state 模型是否有效？
5. 10-14 点 bias 是否改善？
6. 高误差站点是否改善？
7. stacked safe blend 是否优于 Round68 final？
8. 是否建议正式采用 Round70？
9. 如果仍无提升，具体瓶颈是什么？

---

## 十三、统一入口

修改：

```text
scripts/run_full_pipeline.py
```

新增模式：

```bash
python scripts/run_full_pipeline.py --mode round70-performance-upgrade
```

执行：

```text
build_round70_training_table
train_round70_active_state_model
train_round70_state_expert_regressors
train_round70_noon_bias_constrained_model
train_round70_high_error_site_expert
check_candidate_prediction_diff
select_round70_final_candidate
evaluate_round70_candidate_on_test
write Round70 report
```

---

## 十四、执行命令

优先执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/run_full_pipeline.py --mode round70-performance-upgrade
```

如果统一入口尚未接好，按顺序执行：

```bash
mkdir -p output/pv_pipeline/round70

python scripts/build_round70_training_table.py \
  --config configs/round70_state_expert_model.yaml

python scripts/train_round70_active_state_model.py \
  --config configs/round70_state_expert_model.yaml

python scripts/train_round70_state_expert_regressors.py \
  --config configs/round70_state_expert_model.yaml

python scripts/train_round70_noon_bias_constrained_model.py \
  --config configs/round70_state_expert_model.yaml

python scripts/train_round70_high_error_site_expert.py \
  --config configs/round70_state_expert_model.yaml

python scripts/check_candidate_prediction_diff.py \
  --candidate-pkl output/pv_pipeline/round70/round70_candidates.pkl \
  --baseline-col power_pred_final

python scripts/select_round70_final_candidate.py \
  --config configs/round70_state_expert_model.yaml

python scripts/evaluate_round70_candidate_on_test.py \
  --config configs/round70_state_expert_model.yaml
```

---

## 十五、Git 提交

执行通过后提交：

```bash
git status

git add configs/round70_state_expert_model.yaml
git add scripts/build_round70_training_table.py
git add scripts/check_candidate_prediction_diff.py
git add scripts/train_round70_active_state_model.py
git add scripts/train_round70_state_expert_regressors.py
git add scripts/train_round70_noon_bias_constrained_model.py
git add scripts/train_round70_high_error_site_expert.py
git add scripts/select_round70_final_candidate.py
git add scripts/evaluate_round70_candidate_on_test.py
git add scripts/run_full_pipeline.py
git add docs/Round70_训练样本口径重构与状态专家模型性能提升报告.md
git add output/pv_pipeline/round70/*.csv
git add output/pv_pipeline/round70/*.json

git commit -m "experiment: add round70 state expert performance models"
git push origin HEAD
```

不要提交：

```text
*.pkl
*.parquet
*.joblib
output/pv_pipeline/round70/*model*
```

---

## 十六、验收标准

Round70 通过标准：

1. 训练样本统一为 6-19 点，且报告给出 split 分布。
2. 候选列真实不同于 baseline。
3. active state 模型完成训练并输出 valid/test 指标。
4. 10-14 点专用模型完成训练并输出对比。
5. 高误差站点专家模型完成训练并输出对比。
6. safe blend 在 valid 上完成选择。
7. test 只做最终评估。
8. 如果 Round70 不如 Round68 final，自动保留 Round68 final。
9. 如果 Round70 更优，只输出采用建议，不直接覆盖正式 final。

---

## 十七、执行完成后发回

请打包发回：

```text
docs/Round70_训练样本口径重构与状态专家模型性能提升报告.md
output/pv_pipeline/round70/round70_training_distribution_by_split.csv
output/pv_pipeline/round70/round70_training_distribution_by_hour.csv
output/pv_pipeline/round70/round70_candidate_diff_check.csv
output/pv_pipeline/round70/round70_active_state_valid_metrics.csv
output/pv_pipeline/round70/round70_noon_bias_valid_compare.csv
output/pv_pipeline/round70/round70_high_error_expert_valid_compare.csv
output/pv_pipeline/round70/round70_valid_candidate_compare.csv
output/pv_pipeline/round70/round70_candidate_decision.json
output/pv_pipeline/round70/round70_test_overall_compare.csv
output/pv_pipeline/round70/round70_test_hourly_compare.csv
output/pv_pipeline/round70/round70_test_site_compare.csv
```

我会重点判断：

- 训练样本口径是否修正；
- 候选是否真实生效；
- 是否真正提升模型性能；
- 是否值得进入 Round71 正式采用；
- 如果仍失败，是否需要转向新增气象/NWP 数据。

