# Cursor执行方案 Round69：正式采用 Round68，并启动大步模型性能提升

## 一、目标

Round68 已经证明 `round68_lgb_safe_blend` 明显优于当前 Round64 final：

| 指标 | Round64 final | Round68 lgb_safe_blend | 变化 |
|---|---:|---:|---:|
| 站点平均 NRMSE | 11.28% | 10.58% | -0.70pp |
| 城市 NRMSE | 4.31% | 4.13% | -0.18pp |
| abs_bias | 1.55% | 0.52% | -1.03pp |
| bad_sites_gt_1pp | 0 | 0 | 不变 |

本轮不再只做小修，而是一次性完成两件大事：

1. **正式采用 Round68 lgb_safe_blend 作为新的 final 基线**  
   完成备份、无 future 校验、正式 pkl 写入、正式可视化更新、manifest 更新、Git tag。

2. **在新基线之上启动下一阶段模型性能提升实验**  
   不再只做报告或可视化收口，而是训练更强的“站点分群 + 时段专家 + 偏差约束融合”候选模型，目标继续降低站点平均 NRMSE 和 10-14 点误差。

---

## 二、硬性原则

- 不使用 test 集调参。
- 不修改指标公式。
- 不包含 future 数据。
- 正式采用 Round68 前必须备份 Round64 final。
- Round69 新模型候选不得直接覆盖正式 final。
- 新模型若不优于 Round68 final，必须自动保留 Round68 final。
- 任何 promotion 都必须有 rollback 脚本和 Git tag。

---

## 三、第一部分：正式采用 Round68 lgb_safe_blend

### 3.1 修正 Round68 报告中的明显笔误

文件：

```text
docs/Round68_Round67评估口径复核与候选重新判定报告.md
```

修正“关键发现”第 1 条：

当前写法：

```text
lgb 的 city_nrmse 在 test 上比 round64_final 低 0.38pp（4.31% → 4.69%）
```

这是矛盾的，`4.69%` 比 `4.31%` 高。应改为：

```text
原始 lgb 的站点平均 NRMSE 低于 round64_final，但城市 NRMSE 高于 round64_final；经过 safe blend 后，站点平均 NRMSE、城市 NRMSE 和 abs_bias 均优于 round64_final。
```

注意：这只是修正文档事实，不影响 Round68 safe blend 的采用依据。

---

### 3.2 新增 Round68 promotion 脚本

新建：

```text
scripts/promote_round68_candidate.py
```

支持：

```bash
--dry-run
--apply
--exclude-future
```

输入：

```text
output/pv_pipeline/round68/round68_lgb_safe_blend_candidates.pkl
```

如果实际文件名不同，请自动搜索：

```text
output/pv_pipeline/round68/*safe*blend*.pkl
output/pv_pipeline/round68/*candidate*.pkl
```

候选列：

```text
power_pred_round68_lgb_safe_blend
```

如果列名不同，请自动识别包含：

```text
round68
safe
blend
```

的预测列，并在报告中写明。

升级逻辑：

1. 读取当前正式：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl
```

2. 备份当前正式：

```text
output/pv_pipeline/backups/distributed_predictions_final_full_before_round68_YYYYMMDD_HHMMSS.pkl
output/pv_pipeline/backups/distributed_predictions_final_eval_before_round68_YYYYMMDD_HHMMSS.pkl
```

3. 从 Round68 candidate 中取 valid/test，不含 future。

4. 保留当前正式 full 中 train 段。

5. 合并：

```text
final_full = train_current + valid_test_round68
final_eval = valid_test_round68
```

6. 将候选列写入：

```text
power_pred_final
```

7. 写入正式 pkl。

8. 输出：

```text
output/pv_pipeline/round69/round69_promote_round68_apply_report.md
output/pv_pipeline/round69/round69_backup_files.json
output/pv_pipeline/round69/round69_promote_file_plan.csv
```

### 3.3 正式采用前后校验

执行：

```bash
python scripts/check_no_future_in_outputs.py \
  --pkl-path output/pv_pipeline/round68/round68_lgb_safe_blend_candidates.pkl \
  --name round68_candidate \
  --fail-on-future
```

再执行 dry-run：

```bash
python scripts/promote_round68_candidate.py --dry-run --exclude-future
```

确认无误后 apply：

```bash
python scripts/promote_round68_candidate.py --apply --exclude-future
```

升级后检查：

```bash
python scripts/check_no_future_in_outputs.py \
  --pkl-path output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --name final_full_after_round68_promote \
  --fail-on-future

python scripts/check_no_future_in_outputs.py \
  --pkl-path output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl \
  --name final_eval_after_round68_promote \
  --fail-on-future
```

---

### 3.4 重新导出正式可视化

```bash
python scripts/export_interactive_dashboard_data.py \
  --prediction-pkl output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --prediction-col power_pred_final \
  --dashboard-root output/pv_pipeline/interactive_dashboard \
  --label "Round68 final" \
  --exclude-future
```

metadata 必须包含：

```json
{
  "round": "Round68 final",
  "prediction_column": "power_pred_final",
  "official_final": true,
  "exclude_future": true,
  "source_round": "Round68"
}
```

执行一致性校验：

```bash
python scripts/check_dashboard_prediction_values_round66.py \
  --prediction-pkl output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --prediction-col power_pred_final \
  --dashboard-root output/pv_pipeline/interactive_dashboard \
  --fail-on-future
```

---

### 3.5 更新 manifest 和 validation

```bash
python scripts/update_final_manifest_hashes.py
python scripts/posttrain_validation.py
```

要求：

```text
FAIL = 0
```

若仍有 WARN，报告中解释，但不能有真实 FAIL。

---

## 四、第二部分：Round69 大步模型性能提升实验

Round68 是 safe blend，仍属于“主模型 + 安全融合”。本轮继续向模型性能推进，不再只做后处理小调。

### 4.1 新建配置

新建：

```text
configs/round69_performance_model.yaml
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

time_blocks:
  dawn: [6, 7, 8]
  morning: [9, 10]
  noon: [11, 12, 13, 14]
  afternoon: [15, 16]
  dusk: [17, 18, 19]

station_groups:
  high_error:
    source: top_delta_or_high_nrmse
    top_n: 15
  high_zero:
    zero_ratio_min: 0.30
  low_capacity:
    capacity_max: 3
  high_capacity:
    capacity_min: 10
  stable:
    nrmse_max: 10

models:
  lgb_group_expert: true
  hgb_group_expert: true
  station_bias_model: true
  time_block_stack: true

sample_weight:
  base: 1.0
  focus_10_14: 2.0
  high_error_site: 1.8
  high_zero_site: 0.6
  dawn_dusk: 1.3

guards:
  bad_site_gt_1pp_max: 0
  city_nrmse_6_19_max_worse_pp: 0.05
  city_nrmse_10_14_must_not_worse: true
  site_mean_nrmse_improve_min_pp: 0.10
  abs_bias_6_19_max_worse_pp: 0.30
```

---

### 4.2 构造 Round69 训练表

新建：

```text
scripts/build_round69_performance_training_table.py
```

输入：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
```

输出：

```text
output/pv_pipeline/round69/round69_training_table.parquet
output/pv_pipeline/round69/round69_feature_inventory.csv
output/pv_pipeline/round69/round69_training_summary.csv
output/pv_pipeline/round69/round69_station_group_summary.csv
```

特征必须包含：

基础：

```text
hour
month
dayofyear
capacity_mw
latitude
longitude
power_pred_final
power_pred_final / capacity_mw
```

气象/辐照：

```text
g_blend_pred
clear_sky_ghi
clear_sky_index
ghi
temperature
humidity
wind_speed
solar_elevation
```

站点统计：

```text
site_nrmse_valid
site_bias_valid
site_zero_ratio_6_19
site_positive_count_train_valid
site_pr_median
site_quality_score
```

交互特征：

```text
hour × clear_sky_index
hour × g_blend_pred
capacity_bucket × time_block
site_group × time_block
```

目标：

```text
y_norm = power_mw / capacity_mw
residual_norm = y_norm - power_pred_final / capacity_mw
```

---

### 4.3 训练多个性能候选

新建：

```text
scripts/train_round69_performance_candidates.py
```

至少训练 4 类候选：

| 候选 | 说明 |
|---|---|
| `round68_final` | 当前正式基线 |
| `group_expert_lgb` | 按站点组 + 时段训练专家模型 |
| `noon_focus_lgb` | 10-14 点加权主模型 |
| `bias_constrained_blend` | 在 valid 上约束 abs_bias 的融合模型 |
| `high_error_site_expert` | 高误差站点专用模型 |

### 4.4 关键训练要求

1. **不是单一全局模型**  
   至少按 `time_block` 训练专家模型。

2. **不是只优化 RMSE**  
   valid 选择时同时看：

```text
site_mean_nrmse
city_nrmse
city_nrmse_10_14
abs_bias
bad_sites
```

3. **高误差站点单独处理**  
   对 valid 中 NRMSE 高的前 15 个站点训练专门候选，不能被全局模型平均掉。

4. **10-14 点单独优化**  
   训练样本权重提高，但不能导致其他小时明显恶化。

5. **输出所有候选列**：

```text
power_pred_round69_group_expert_lgb
power_pred_round69_noon_focus_lgb
power_pred_round69_bias_constrained_blend
power_pred_round69_high_error_expert
```

输出：

```text
output/pv_pipeline/round69/round69_candidates.pkl
output/pv_pipeline/round69/round69_model_training_summary.csv
output/pv_pipeline/round69/round69_feature_importance.csv
```

---

## 五、Round69 valid 选择与 test 评估

### 5.1 新建选择脚本

```text
scripts/select_round69_performance_candidate.py
```

valid 门控：

```text
bad_site_gt_1pp == 0
site_mean_nrmse_6_19 <= baseline - 0.10pp
city_nrmse_6_19 <= baseline + 0.05pp
city_nrmse_10_14 <= baseline
abs_bias_6_19 <= baseline + 0.30pp
10-14 点站点平均 NRMSE 不恶化
```

若无候选满足：

```text
decision = keep_round68_final
```

若有候选满足：

```text
decision = round69_candidate_for_review
```

输出：

```text
output/pv_pipeline/round69/round69_valid_candidate_compare.csv
output/pv_pipeline/round69/round69_candidate_decision.json
```

### 5.2 新建 test 评估脚本

```text
scripts/evaluate_round69_performance_candidate.py
```

输出：

```text
output/pv_pipeline/round69/round69_test_overall_compare.csv
output/pv_pipeline/round69/round69_test_hourly_compare.csv
output/pv_pipeline/round69/round69_test_site_compare.csv
output/pv_pipeline/round69/round69_high_error_site_compare.csv
```

---

## 六、Round69 报告

新建：

```text
docs/Round69_正式采用Round68并启动大步模型性能提升报告.md
```

报告必须回答：

1. Round68 是否已正式成为 final？
2. 是否完全排除 future？
3. Round68 final 当前指标是多少？
4. Round69 是否训练了真正的新模型候选？
5. 哪个候选在 valid 上通过？
6. test 上是否真的优于 Round68 final？
7. 10-14 点高估是否改善？
8. 高误差站点是否改善？
9. 是否建议进入 Round70 正式采用？
10. 如果无明显提升，瓶颈是特征、数据还是模型？

---

## 七、统一入口

修改：

```text
scripts/run_full_pipeline.py
```

新增：

```bash
python scripts/run_full_pipeline.py --mode round69-promote-and-performance
```

执行顺序：

```text
check round68 candidate no future
promote round68 candidate
export final dashboard
update manifest
posttrain validation
build round69 training table
train round69 performance candidates
select round69 candidate on valid
evaluate round69 candidate on test
write Round69 report
```

---

## 八、执行命令

优先执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/run_full_pipeline.py --mode round69-promote-and-performance
```

如果统一入口还没接好，按以下顺序执行：

```bash
mkdir -p output/pv_pipeline/round69

python scripts/check_no_future_in_outputs.py \
  --pkl-path output/pv_pipeline/round68/round68_lgb_safe_blend_candidates.pkl \
  --name round68_candidate \
  --fail-on-future

python scripts/promote_round68_candidate.py --apply --exclude-future

python scripts/export_interactive_dashboard_data.py \
  --prediction-pkl output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --prediction-col power_pred_final \
  --dashboard-root output/pv_pipeline/interactive_dashboard \
  --label "Round68 final" \
  --exclude-future

python scripts/update_final_manifest_hashes.py
python scripts/posttrain_validation.py

python scripts/build_round69_performance_training_table.py \
  --config configs/round69_performance_model.yaml

python scripts/train_round69_performance_candidates.py \
  --config configs/round69_performance_model.yaml

python scripts/select_round69_performance_candidate.py \
  --config configs/round69_performance_model.yaml

python scripts/evaluate_round69_performance_candidate.py \
  --config configs/round69_performance_model.yaml
```

---

## 九、Git 提交与 tag

执行成功后：

```bash
git status

git add configs/round69_performance_model.yaml
git add scripts/promote_round68_candidate.py
git add scripts/build_round69_performance_training_table.py
git add scripts/train_round69_performance_candidates.py
git add scripts/select_round69_performance_candidate.py
git add scripts/evaluate_round69_performance_candidate.py
git add scripts/run_full_pipeline.py
git add docs/Round68_Round67评估口径复核与候选重新判定报告.md
git add docs/Round69_正式采用Round68并启动大步模型性能提升报告.md
git add output/pv_pipeline/round69/*.csv
git add output/pv_pipeline/round69/*.json

git commit -m "feat: promote round68 and add round69 performance candidates"
git tag -a round68-final-20260601 -m "Round68 lgb safe blend promoted as final"
git push origin HEAD
git push origin round68-final-20260601
```

不要提交：

```text
*.pkl
*.parquet
*.joblib
interactive_dashboard/**/*.json
```

---

## 十、验收标准

本轮通过标准：

1. Round68 正式升级为 final。
2. 正式 final 不含 future。
3. 正式可视化不含 future 且与 final pkl 一致。
4. posttrain validation 无真实 FAIL。
5. Round69 至少训练 4 类性能候选。
6. valid 选择不读取 test。
7. test 只做最终评估。
8. 若 Round69 不如 Round68，保留 Round68 final。
9. 若 Round69 优于 Round68，只输出采用建议，不直接覆盖。
10. 报告必须说明模型性能是否真正提升，而不是只列指标。

---

## 十一、执行完成后发回

请发回：

```text
docs/Round69_正式采用Round68并启动大步模型性能提升报告.md
output/pv_pipeline/round69/round69_training_summary.csv
output/pv_pipeline/round69/round69_station_group_summary.csv
output/pv_pipeline/round69/round69_model_training_summary.csv
output/pv_pipeline/round69/round69_valid_candidate_compare.csv
output/pv_pipeline/round69/round69_candidate_decision.json
output/pv_pipeline/round69/round69_test_overall_compare.csv
output/pv_pipeline/round69/round69_test_hourly_compare.csv
output/pv_pipeline/round69/round69_test_site_compare.csv
output/pv_pipeline/round69/round69_high_error_site_compare.csv
```

我会重点判断：

- Round68 是否已成为新的正式基线；
- Round69 是否真正提升模型性能；
- 是否值得进入 Round70 正式采用；
- 如果仍提升有限，下一步是否必须引入 NWP/云量等新增气象特征。

