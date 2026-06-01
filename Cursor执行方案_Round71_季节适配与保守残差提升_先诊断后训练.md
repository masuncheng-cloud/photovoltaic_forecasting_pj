# Cursor执行方案 Round71：季节适配与保守残差提升，先诊断后训练

## 一、目标

Round70 失败的主要经验是：不要盲目重训复杂模型。状态分类器、专家回归器虽然真实生效，但在 test 上出现系统性低估，说明直接重建全功率模型风险较高。

Round71 的目标是更克制但更有效：

1. 先诊断季节分布漂移、月份误差、站点误差是否真实存在。
2. 只在诊断支持的情况下训练候选模型。
3. 不重新预测完整功率，而是在 Round68 final 基础上做**保守残差修正**。
4. 优先解决 9-12 月 test 分布和 10-14 点高估问题。
5. 如果候选不稳定，自动保留 Round68 final。

本轮核心原则：

```text
先诊断 -> 再训练 -> valid 多窗口选择 -> test 最终评估 -> 不好就回退
```

---

## 二、当前正式基线

当前正式基线：

```text
Round68 final
prediction column: power_pred_final
```

基线指标：

```text
site_mean_nrmse_6_19 = 10.58%
city_nrmse_6_19 = 4.13%
abs_bias_6_19 = 0.52%
bad_sites_gt_1pp = 0
```

Round71 所有候选都必须与 Round68 final 比较。

---

## 三、硬性约束

- 不使用 test 集调参。
- 不修改指标公式。
- 不包含 future 数据。
- 不做全功率重训替换。
- 不允许候选列与 baseline 完全相同还被当作有效候选。
- 不允许只看 test 变好就采用。
- 若 valid 多窗口不过关，自动保留 Round68 final。
- 本轮只采用“保守残差修正”，避免产生 Round70 那种 -9% 到 -12% 的系统性低估。

---

## 四、Round71 总体路线

本轮只做 3 类候选：

| 候选 | 目的 | 风险控制 |
|---|---|---|
| `seasonal_residual_lgb` | 针对月份/季节分布漂移学习残差 | 残差幅度限幅 |
| `recency_weighted_residual_lgb` | 更重视靠近 valid/test 的近期样本 | valid 多窗口验证 |
| `noon_conservative_bias_residual` | 专门修 10-14 点高估 | 只允许小幅调整 |

最终再做：

```text
round71_conservative_blend
```

只在 valid 上证明有效的站点-月份-时段组合才采用修正。

---

## 五、第一步：先诊断，不直接训练

### 5.1 新建诊断脚本

新建：

```text
scripts/diagnose_round71_drift_and_error_sources.py
```

输入：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
```

要求：

1. 排除 future。
2. 只分析 6-19 点。
3. 按 split、month、hour、site_id、time_block 统计：

```text
sample_count
positive_rate
inactive_rate
actual_mean_mw
pred_mean_mw
bias_pct
abs_bias_pct
site_mean_nrmse_pct
city_nrmse_pct
pred_actual_ratio
```

4. 对 high error 站点做归因标签：

```text
zero_ratio_high
capacity_small
capacity_large
season_drift_high
bias_high
sample_low
geo_low_confidence
```

5. 输出：

```text
output/pv_pipeline/round71/round71_drift_by_split_month.csv
output/pv_pipeline/round71/round71_error_by_hour_month.csv
output/pv_pipeline/round71/round71_error_by_site_month.csv
output/pv_pipeline/round71/round71_high_error_site_diagnosis.csv
output/pv_pipeline/round71/round71_diagnosis_summary.json
```

### 5.2 诊断通过条件

只有满足至少一个条件，才继续训练对应候选：

#### 条件 A：季节漂移成立

```text
test 9-12 月某些月份的 abs_bias 或 NRMSE 明显高于 valid 7-8 月
且差异 >= 1.0pp
```

则允许训练：

```text
seasonal_residual_lgb
```

#### 条件 B：近期样本更接近 test 成立

比较 train 的早期样本和近期样本：

```text
近期样本的分布更接近 valid/test
```

则允许训练：

```text
recency_weighted_residual_lgb
```

#### 条件 C：10-14 点高估成立

如果：

```text
10-14 点 bias_10_14 > +1.0%
或 abs_bias_10_14 明显高于其他小时
```

则允许训练：

```text
noon_conservative_bias_residual
```

如果三个条件都不成立：

```text
停止训练；
输出报告；
保留 Round68 final。
```

---

## 六、配置文件

新建：

```text
configs/round71_conservative_residual.yaml
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
eval_hours: [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
focus_hours: [10, 11, 12, 13, 14]

residual_target: capacity_normalized

residual_clip:
  max_abs_norm: 0.08
  max_abs_mw_ratio: 0.08
  noon_max_abs_norm: 0.06

recency_weight:
  enabled: true
  half_life_days: 180
  min_weight: 0.4
  max_weight: 2.0

valid_windows:
  window_1:
    months: [5, 6]
  window_2:
    months: [7, 8]

candidate_guards:
  bad_site_gt_1pp_max: 0
  site_mean_nrmse_improve_min_pp: 0.10
  city_nrmse_6_19_max_worse_pp: 0.05
  city_nrmse_10_14_must_not_worse: true
  abs_bias_6_19_max_worse_pp: 0.20
  abs_bias_10_14_must_not_worse: true
```

说明：

- `valid_windows` 不允许使用 test。
- 如果当前数据无法自然形成 5-6、7-8 两个 valid 窗口，请脚本自动按时间从 train/valid 中构造滚动验证窗口，但不能包含 test。

---

## 七、构建 Round71 训练表

新建：

```text
scripts/build_round71_residual_training_table.py
```

输入：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
```

要求：

1. 排除 future。
2. 只保留 6-19 点。
3. 目标不是 `power_mw`，而是保守残差：

```text
y_true_norm = power_mw / capacity_mw
y_base_norm = power_pred_final / capacity_mw
residual_norm = y_true_norm - y_base_norm
```

4. 残差目标裁剪，避免极端样本主导：

```text
residual_norm_clipped = clip(residual_norm, -0.08, 0.08)
```

10-14 点可更保守：

```text
clip 到 [-0.06, 0.06]
```

5. 特征优先使用现有稳定字段：

```text
hour
month
dayofyear
capacity_mw
latitude
longitude
power_pred_final / capacity_mw
g_blend_pred
clear_sky_ghi
clear_sky_index
scene_v151
site_zero_ratio_6_19
site_pr_median
site_bias_valid
site_nrmse_valid
site_quality_score
```

6. 不存在的字段跳过，但写入 feature inventory。

输出：

```text
output/pv_pipeline/round71/round71_residual_training_table.parquet
output/pv_pipeline/round71/round71_feature_inventory.csv
output/pv_pipeline/round71/round71_training_summary.csv
```

---

## 八、训练保守残差候选

新建：

```text
scripts/train_round71_conservative_residual_candidates.py
```

### 8.1 候选一：seasonal residual

只在诊断条件 A 成立时训练。

模型：

```text
LightGBM 或 HistGradientBoosting
```

训练目标：

```text
residual_norm_clipped
```

特征重点：

```text
month
dayofyear
hour
clear_sky_index
g_blend_pred
site_bias_valid
site_nrmse_valid
```

输出列：

```text
power_pred_round71_seasonal_residual
```

### 8.2 候选二：recency weighted residual

只在诊断条件 B 成立时训练。

样本权重：

```text
weight = exp(-days_from_valid_start / half_life_days)
```

并裁剪到：

```text
[0.4, 2.0]
```

输出列：

```text
power_pred_round71_recency_residual
```

### 8.3 候选三：noon conservative bias residual

只在诊断条件 C 成立时训练。

只对 10-14 点学习小幅残差，其他小时默认 baseline。

输出列：

```text
power_pred_round71_noon_conservative
```

要求：

```text
10-14 点修正幅度不超过 capacity_mw * 0.06
```

### 8.4 候选有效性检查

训练完成后必须运行：

```text
scripts/check_candidate_prediction_diff.py
```

任何候选如果与 baseline 完全一致，则标记为 invalid，不参与选择。

输出：

```text
output/pv_pipeline/round71/round71_candidates.pkl
output/pv_pipeline/round71/round71_candidate_diff_check.csv
output/pv_pipeline/round71/round71_model_training_summary.csv
```

---

## 九、valid 多窗口选择

新建：

```text
scripts/select_round71_candidate_multi_window.py
```

### 9.1 为什么要多窗口

Round70 暴露了单一 valid 月份偏晴朗的问题。Round71 不能只在一个 valid 窗口上选模型。

至少使用两个非 test 窗口：

```text
valid_window_early
valid_window_late
```

若数据中无法按 5-6、7-8 月切分，则脚本自动按时间顺序在 train/valid 内切两个窗口。

### 9.2 门控规则

候选必须在两个 valid 窗口上都满足：

```text
bad_site_gt_1pp == 0
city_nrmse_6_19 <= baseline + 0.05pp
abs_bias_6_19 <= baseline + 0.20pp
```

并且至少一个窗口满足：

```text
site_mean_nrmse_6_19 <= baseline - 0.10pp
```

对 10-14 点：

```text
city_nrmse_10_14 <= baseline
abs_bias_10_14 <= baseline
```

### 9.3 安全融合

如果单个候选不过关，但局部有提升，则生成：

```text
power_pred_round71_safe_blend
```

融合公式：

```text
P_blend = P_base + w * (P_candidate - P_base)
```

权重：

```text
w ∈ [0, 0.25, 0.50, 0.75, 1.00]
```

选择粒度：

```text
site_id + month + time_block
```

只有 valid 两个窗口都安全的组合才允许 w > 0。

输出：

```text
output/pv_pipeline/round71/round71_valid_window_compare.csv
output/pv_pipeline/round71/round71_candidate_decision.json
output/pv_pipeline/round71/round71_safe_blend_weights.csv
```

---

## 十、test 最终评估

新建：

```text
scripts/evaluate_round71_candidate_on_test.py
```

输出：

```text
output/pv_pipeline/round71/round71_test_overall_compare.csv
output/pv_pipeline/round71/round71_test_hourly_compare.csv
output/pv_pipeline/round71/round71_test_site_compare.csv
output/pv_pipeline/round71/round71_high_error_site_test_compare.csv
docs/Round71_季节适配与保守残差提升报告.md
```

报告必须回答：

1. 季节漂移是否真实存在？
2. 10-14 点高估是否真实存在？
3. 近期样本加权是否有依据？
4. 哪些候选被训练，哪些因诊断不成立被跳过？
5. 候选是否真实不同于 baseline？
6. 多窗口 valid 是否通过？
7. test 上是否优于 Round68 final？
8. 是否建议正式采用？
9. 如果仍无提升，是否可以认为现有特征下进入瓶颈？

---

## 十一、统一入口

修改：

```text
scripts/run_full_pipeline.py
```

新增模式：

```bash
python scripts/run_full_pipeline.py --mode round71-conservative-residual
```

执行顺序：

```text
diagnose_round71_drift_and_error_sources
build_round71_residual_training_table
train_round71_conservative_residual_candidates
check_candidate_prediction_diff
select_round71_candidate_multi_window
evaluate_round71_candidate_on_test
write Round71 report
```

---

## 十二、执行命令

优先执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/run_full_pipeline.py --mode round71-conservative-residual
```

如果统一入口尚未接好：

```bash
mkdir -p output/pv_pipeline/round71

python scripts/diagnose_round71_drift_and_error_sources.py \
  --config configs/round71_conservative_residual.yaml

python scripts/build_round71_residual_training_table.py \
  --config configs/round71_conservative_residual.yaml

python scripts/train_round71_conservative_residual_candidates.py \
  --config configs/round71_conservative_residual.yaml

python scripts/check_candidate_prediction_diff.py \
  --candidate-pkl output/pv_pipeline/round71/round71_candidates.pkl \
  --baseline-col power_pred_final

python scripts/select_round71_candidate_multi_window.py \
  --config configs/round71_conservative_residual.yaml

python scripts/evaluate_round71_candidate_on_test.py \
  --config configs/round71_conservative_residual.yaml
```

---

## 十三、Git 提交

执行通过后提交：

```bash
git status

git add configs/round71_conservative_residual.yaml
git add scripts/diagnose_round71_drift_and_error_sources.py
git add scripts/build_round71_residual_training_table.py
git add scripts/train_round71_conservative_residual_candidates.py
git add scripts/select_round71_candidate_multi_window.py
git add scripts/evaluate_round71_candidate_on_test.py
git add scripts/run_full_pipeline.py
git add docs/Round71_季节适配与保守残差提升报告.md
git add output/pv_pipeline/round71/*.csv
git add output/pv_pipeline/round71/*.json

git commit -m "experiment: add round71 conservative seasonal residual modeling"
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

Round71 通过标准：

1. 先输出诊断结果，再训练候选。
2. 没有诊断依据的候选不得训练。
3. 候选只做保守残差，不重训全功率。
4. 候选预测列真实不同于 baseline。
5. valid 使用至少两个非 test 窗口。
6. test 只做最终评估。
7. 如果候选不如 Round68 final，自动保留 Round68。
8. 报告必须明确哪些误差能靠现有特征改善，哪些不能。

---

## 十五、执行完成后发回

请发回：

```text
docs/Round71_季节适配与保守残差提升报告.md
output/pv_pipeline/round71/round71_diagnosis_summary.json
output/pv_pipeline/round71/round71_drift_by_split_month.csv
output/pv_pipeline/round71/round71_error_by_hour_month.csv
output/pv_pipeline/round71/round71_high_error_site_diagnosis.csv
output/pv_pipeline/round71/round71_candidate_diff_check.csv
output/pv_pipeline/round71/round71_valid_window_compare.csv
output/pv_pipeline/round71/round71_candidate_decision.json
output/pv_pipeline/round71/round71_test_overall_compare.csv
output/pv_pipeline/round71/round71_test_hourly_compare.csv
output/pv_pipeline/round71/round71_test_site_compare.csv
```

我会重点判断：

- Round71 是否真正提升性能；
- 是否值得正式采用；
- 如果没有提升，是否可以确认现有数据特征已经接近瓶颈；
- 下一步是否必须进入新增气象/NWP 数据阶段。

