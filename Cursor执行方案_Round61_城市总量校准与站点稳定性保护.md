# Cursor 执行方案 Round61：城市总量校准与站点稳定性保护

## 目标

Round60 的价值是站点级更稳：

- 站点平均 NRMSE 轻微改善；
- 变差超过 +1pp 的站点从 8 个降到 0 个；
- 17-19 点不再被 site factor 拖差。

但 Round60 的问题是城市总量略差：

- city_nrmse_6_19：Round58 3.9533% → Round60 3.9775%
- city_nrmse_10_14：Round58 6.2356% → Round60 6.3159%
- bias_6_19：Round58 +1.39% → Round60 +1.93%
- bias_10_14：Round58 +8.40% → Round60 +8.98%

本轮目标：

1. 保留 Round60 的站点稳定性和站点级回退机制。
2. 增加一个轻量的“城市总量校准层”，重点修正 10-14 点城市高估。
3. 不完整重训。
4. 不修改指标公式。
5. 只用 valid 选择参数，test 只做最终评估。
6. 如果城市改善会导致站点明显恶化，则回退。

---

## 一、进入项目目录

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
mkdir -p output/pv_pipeline/calibration
mkdir -p output/pv_pipeline/baselines/round60
mkdir -p output/pv_pipeline/logs
mkdir -p output/pv_pipeline/metrics
```

---

## 二、备份 Round60 当前产物

```bash
cp output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
   output/pv_pipeline/baselines/round60/distributed_predictions_final_full.pkl

cp output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl \
   output/pv_pipeline/baselines/round60/distributed_predictions_final_eval.pkl

cp output/pv_pipeline/metrics/hourly_nrmse_consistent.csv \
   output/pv_pipeline/baselines/round60/hourly_nrmse_consistent.csv

cp output/pv_pipeline/metrics/site_metrics_consistent.csv \
   output/pv_pipeline/baselines/round60/site_metrics_consistent.csv
```

确认 Round58 baseline 仍存在：

```bash
ls -lh output/pv_pipeline/baselines/round58/
```

---

## 三、新增城市总量校准器

新增：

```text
scripts/train_city_total_calibrator.py
```

输入：

```text
output/pv_pipeline/baselines/round60/distributed_predictions_final_full.pkl
```

使用数据：

```text
split == valid
hour 6-19
prediction column = power_pred_final
```

校准目标：

按小时学习城市总量校准因子：

```text
city_factor_hour = sum_city_actual / sum_city_pred
```

其中：

```text
sum_city_actual = valid 集中该小时所有站点实际功率总和
sum_city_pred = valid 集中该小时所有站点预测功率总和
```

只重点允许 10-14 点较强校准：

```text
10-14: factor_min=0.94, factor_max=1.04
6-9, 15-19: factor_min=0.97, factor_max=1.03
```

收缩：

```text
final_factor = shrink * raw_factor + (1 - shrink) * 1.0
shrink = n / (n + 3000)
```

约束：

- 如果某小时 valid city_nrmse 变差，factor 回退为 1.0。
- 如果某小时 valid bias_abs 变差超过 1pp，factor 回退为 1.0。
- 如果某小时 valid site_mean_nrmse 变差超过 0.15pp，factor 回退为 1.0。

输出：

```text
output/pv_pipeline/calibration/city_total_hour_calibrator.csv
```

字段：

```text
hour
n
actual_sum
pred_sum
raw_factor
final_factor
factor_clipped
valid_city_nrmse_before
valid_city_nrmse_after
valid_site_mean_nrmse_before
valid_site_mean_nrmse_after
valid_bias_before
valid_bias_after
status
rollback_reason
```

---

## 四、应用城市总量校准

新增：

```text
scripts/apply_round61_city_calibration.py
```

输入：

```text
output/pv_pipeline/baselines/round60/distributed_predictions_final_full.pkl
output/pv_pipeline/calibration/city_total_hour_calibrator.csv
```

生成候选：

```text
power_pred_round61_city
power_pred_round61_city_safe
```

应用：

```text
pred_city = round60_pred * city_factor_hour
clip to [0, capacity_mw]
```

安全保护：

1. **站点级保护**

只用 valid：

```text
如果某站点 valid NRMSE 恶化 > 0.3pp，则该站点回退 Round60。
如果某站点 valid bias_abs 恶化 > 3pp，则该站点回退 Round60。
```

2. **小时级保护**

只用 valid：

```text
如果某小时 valid site_mean_nrmse 恶化 > 0.15pp，则该小时回退 Round60。
如果某小时 valid city_nrmse 恶化 > 0.1pp，则该小时回退 Round60。
```

3. **重点小时保护**

10-14 点允许小幅城市校准，但不允许：

```text
site_mean_nrmse_10_14 比 Round60 高 > 0.1pp
```

输出：

```text
output/pv_pipeline/predictions/distributed_predictions_round61_candidates.pkl
output/pv_pipeline/calibration/round61_site_guard.csv
output/pv_pipeline/calibration/round61_hour_guard.csv
```

---

## 五、valid 选择最终版本

新增：

```text
scripts/select_round61_final_prediction.py
```

候选：

```text
Round58 baseline
Round59 current
Round60 baseline
Round61 city
Round61 city_safe
```

选择只用 valid。

score：

```text
score =
    0.30 * site_mean_nrmse_6_19
  + 0.30 * city_nrmse_6_19
  + 0.25 * city_nrmse_10_14
  + 0.15 * abs(bias_10_14)
```

必须满足安全约束：

```text
site_mean_nrmse_6_19 <= Round60 + 0.10pp
site_mean_nrmse_10_14 <= Round60 + 0.10pp
city_nrmse_6_19 <= Round58 + 0.05pp
city_nrmse_10_14 <= Round58 + 0.05pp
abs(bias_6_19) <= Round58 + 0.5pp
abs(bias_10_14) <= Round58 + 0.5pp
变差 > +1pp 的站点数 == 0
```

如果无候选满足，则保留 Round60。

输出：

```text
output/pv_pipeline/calibration/round61_model_selection_valid.csv
```

最终列：

```text
power_pred_round61_final
```

并同步为：

```text
power_pred_final
```

---

## 六、执行 Round61 校准

```bash
python scripts/train_city_total_calibrator.py 2>&1 | tee output/pv_pipeline/logs/round61_train_city_total_calibrator.log

python scripts/apply_round61_city_calibration.py 2>&1 | tee output/pv_pipeline/logs/round61_apply_city_calibration.log

python scripts/select_round61_final_prediction.py 2>&1 | tee output/pv_pipeline/logs/round61_select_final.log
```

然后重新生成指标和可视化：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode eval-only --force 2>&1 | tee output/pv_pipeline/logs/round61_eval_only.log

python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode dashboard-only --force 2>&1 | tee output/pv_pipeline/logs/round61_dashboard_only.log

python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode audit-only 2>&1 | tee output/pv_pipeline/logs/round61_audit_only.log
```

如果 `eval-only` 覆盖了 `power_pred_round61_final`，修改 `run_full_pipeline.py`：

- 检测到 Round61 candidates 时，优先使用 `power_pred_round61_final`；
- 不允许重新从 Round58/Round60 baseline 覆盖。

---

## 七、对比 Round58/Round59/Round60/Round61

新增：

```text
scripts/compare_round58_59_60_61_metrics.py
```

输出：

```text
output/pv_pipeline/metrics/round61_compare_summary.csv
output/pv_pipeline/metrics/round61_compare_hourly.csv
output/pv_pipeline/metrics/round61_compare_site.csv
docs/Round61_城市总量校准与站点稳定性保护报告.md
```

必须比较：

```text
Round58 baseline
Round59
Round60
Round61
```

重点指标：

```text
site_mean_nrmse_6_19
city_nrmse_6_19
site_mean_nrmse_10_14
city_nrmse_10_14
bias_6_19
bias_10_14
MAE
RMSE
变差 > +1pp 的站点数
```

重点小时：

```text
7
10
11
12
13
14
17
18
19
```

重点站点：

```text
S012
S019
S032
S053
S071
S115
S116
S022
S050
S004
```

---

## 八、验收标准

Round61 只有满足以下条件才采用：

```text
[PASS] 不完整重训
[PASS] 不修改指标公式
[PASS] 不使用 test 选择校准参数
[PASS] valid 集选择记录完整
[PASS] 变差 > +1pp 的站点数为 0
[PASS] site_mean_nrmse_6_19 不高于 Round60 + 0.10pp
[PASS] site_mean_nrmse_10_14 不高于 Round60 + 0.10pp
[PASS] city_nrmse_6_19 不高于 Round58 + 0.05pp
[PASS] city_nrmse_10_14 不高于 Round58 + 0.05pp
[PASS] bias_6_19 绝对值不高于 Round58 + 0.5pp
[PASS] bias_10_14 绝对值不高于 Round58 + 0.5pp
[PASS] dashboard check 无 FAIL
[PASS] posttrain_validation 无 FAIL
```

如果不满足：

```text
保留 Round60 作为正式版本。
```

---

## 九、生成 Round61 报告

新增：

```text
docs/Round61_城市总量校准与站点稳定性保护报告.md
```

模板：

```markdown
# Round61 城市总量校准与站点稳定性保护报告

## 1. 本轮目标

## 2. 为什么需要 Round61

Round60 提升了站点稳定性，但城市 NRMSE 和 bias 略差。

## 3. 城市总量校准器

## 4. valid 集选择结果

## 5. test 集最终对比

| 指标 | Round58 | Round59 | Round60 | Round61 | 结论 |
|---|---:|---:|---:|---:|---|

## 6. 逐小时对比

## 7. 重点站点对比

## 8. 是否采用 Round61

采用 Round61 / 回退 Round60。

## 9. 当前仍存在的问题

## 10. 下一步建议
```

---

## 十、注意事项

1. 不要用 test 选择 city factor。
2. 不要为了城市 NRMSE 牺牲站点稳定性。
3. 不要对所有小时大幅校准，只做轻量校准。
4. 如果 Round61 未通过验收，必须回退 Round60。
5. 不需要完整重训。

