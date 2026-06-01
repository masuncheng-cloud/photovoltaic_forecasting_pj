# Cursor 执行方案 Round60：复核 Round59 对比口径与保守回退校准

## 目标

Round59 已经开始提升预测结果，但报告中存在两个风险：

1. Round59 对比报告中的城市 NRMSE 数值与 Round58 口径不一致。
   - Round58 修正后：城市 NRMSE 6-19 约 4.44%，10-14 约 6.24%
   - Round59 报告：城市 NRMSE 6-19 约 0.2398%，10-14 约 0.3086%
   - 量级差异过大，必须先复核。

2. Round59 的 site-only 校准虽然整体 bias 有改善，但部分站点明显恶化。
   - 8 个站点 site NRMSE 恶化超过 +1.0pp
   - S022、S050 恶化超过 +2pp
   - S019/S053 低估加剧
   - 18-19 点轻微变差

本轮目标：

- 不完整重训。
- 不修改指标公式。
- 先复核 Round59 对比指标是否和 Round58 公式一致。
- 加入站点级/小时级安全回退。
- 训练更保守的 site 校准器。
- 如果保守版不如 Round58，则自动回退 Round58。

---

## 一、进入项目目录

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
mkdir -p output/pv_pipeline/baselines/round59
mkdir -p output/pv_pipeline/calibration
mkdir -p output/pv_pipeline/validation
mkdir -p output/pv_pipeline/logs
```

---

## 二、备份 Round59 当前产物

```bash
cp output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
   output/pv_pipeline/baselines/round59/distributed_predictions_final_full.pkl

cp output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl \
   output/pv_pipeline/baselines/round59/distributed_predictions_final_eval.pkl

cp output/pv_pipeline/metrics/hourly_nrmse_consistent.csv \
   output/pv_pipeline/baselines/round59/hourly_nrmse_consistent.csv

cp output/pv_pipeline/metrics/site_metrics_consistent.csv \
   output/pv_pipeline/baselines/round59/site_metrics_consistent.csv
```

确认 Round58 baseline 仍存在：

```bash
ls -lh output/pv_pipeline/baselines/round58/
```

如果 Round58 baseline 不存在，不要继续，先恢复 Round58 baseline。

---

## 三、独立复核 Round59 对比口径

新增：

```text
scripts/recheck_round59_compare_metrics.py
```

功能：

- 读取 Round58 baseline eval pkl。
- 读取当前 Round59 eval pkl。
- 使用 Round58 确认后的公式从零计算：
  - site_mean_nrmse_6_19
  - city_nrmse_6_19
  - site_mean_nrmse_10_14
  - city_nrmse_10_14
  - bias_6_19
  - bias_10_14
  - MAE
  - RMSE
- 对比 Round59 报告/CSV 中的值。

输出：

```text
output/pv_pipeline/validation/round60_recheck_round59_compare.csv
output/pv_pipeline/validation/round60_recheck_round59_hourly.csv
output/pv_pipeline/validation/round60_recheck_round59_site.csv
output/pv_pipeline/validation/round60_recheck_round59_report.md
```

核心公式必须是：

```python
def rmse(a, p):
    return np.sqrt(np.mean((np.asarray(p) - np.asarray(a)) ** 2))

def site_mean_nrmse(df, pred_col):
    vals = []
    for sid, sdf in df.groupby("station_id"):
        cap = sdf["capacity_mw"].dropna().iloc[0]
        if cap > 0:
            vals.append(rmse(sdf["power_mw"], sdf[pred_col]) / cap * 100)
    return np.nanmean(vals)

def city_nrmse(df, pred_col):
    cap_sum = df[["station_id", "capacity_mw"]].drop_duplicates("station_id")["capacity_mw"].sum()
    agg = df.groupby("timestamp", as_index=False).agg(
        actual=("power_mw", "sum"),
        pred=(pred_col, "sum"),
    )
    return rmse(agg["actual"], agg["pred"]) / cap_sum * 100

def bias_pct(df, pred_col):
    a = df["power_mw"].sum()
    p = df[pred_col].sum()
    return (p - a) / a * 100 if abs(a) > 1e-12 else np.nan
```

执行：

```bash
python scripts/recheck_round59_compare_metrics.py 2>&1 | tee output/pv_pipeline/logs/round60_recheck_round59_compare.log
```

判断：

- 如果复核结果显示 Round59 的 city NRMSE 实际仍是 4%-6% 量级，说明 Round59 报告/compare 脚本有口径错误，必须修 compare 脚本。
- 如果复核结果确认 Round59 真的是 0.2%-0.3%，需要解释为什么与 Round58 可视化不同，否则不可采信。

---

## 四、修正 compare_round58_round59_metrics.py

如果上一步确认 Round59 compare 口径错误，修改：

```text
scripts/compare_round58_round59_metrics.py
```

要求：

- 直接复用 Round58 的公共指标函数，或复制同一套公式。
- 不允许使用 `mean(capacity_mw)` 作为城市 NRMSE 分母。
- 城市 NRMSE 必须按 timestamp 聚合全市功率后再计算。
- 输出 CSV 中明确写：

```text
site_mean_nrmse_percent
city_nrmse_percent
```

不要使用模糊字段名：

```text
sm_nrmse
c_nrmse
```

修复后重新运行：

```bash
python scripts/compare_round58_round59_metrics.py 2>&1 | tee output/pv_pipeline/logs/round60_compare_after_fix.log
```

---

## 五、训练保守版 site 校准器

Round59 的 `k=1000` 和 factor 范围 `[0.70, 1.40]` 可能过于激进。

新增：

```text
scripts/train_site_bias_calibrator_conservative.py
```

基于原 `train_site_bias_calibrator.py` 修改：

```text
shrinkage_k = 3000
factor_min = 0.85
factor_max = 1.20
min_samples = 500
min_positive_actual_sum = 20
```

对低光小时不使用 site factor：

```text
apply_hours = 8-16
exclude_hours = 6,7,17,18,19
```

原因：

- Round59 在 18-19 点变差；
- 低光时段更适合单独 hour/scene 校准，不适合站点总量 factor。

输出：

```text
output/pv_pipeline/calibration/site_bias_calibrator_conservative.csv
```

---

## 六、训练保守版 hour-scene 校准器

新增：

```text
scripts/train_hour_scene_calibrator_conservative.py
```

目标：

- 修 10-14 高估；
- 修 7/17 低估；
- 不让整体 bias 变差。

参数：

```text
factor_min = 0.85
factor_max = 1.20
shrinkage_k = 1000
min_samples = 300
```

特殊约束：

```text
10-14 clear_peak/mid：允许 factor <= 1，用于抑制高估
7/17/18/19 low/night-like：允许 factor >= 1，用于缓解低估
如果 valid bias_abs 变差超过 1pp，该 hour-scene factor 回退为 1
```

输出：

```text
output/pv_pipeline/calibration/hour_scene_calibrator_conservative.csv
```

---

## 七、应用保守校准并加入站点/小时级回退

新增：

```text
scripts/apply_round60_conservative_calibration.py
```

输入：

```text
output/pv_pipeline/baselines/round58/distributed_predictions_final_full.pkl
output/pv_pipeline/calibration/site_bias_calibrator_conservative.csv
output/pv_pipeline/calibration/hour_scene_calibrator_conservative.csv
```

生成候选列：

```text
power_pred_round60_hour_scene
power_pred_round60_site_conservative
power_pred_round60_combined_conservative
power_pred_round60_safe
```

应用顺序：

```text
base = Round58 power_pred_final
hour_scene_pred = base * hour_scene_factor
site_pred = base * site_factor，仅 8-16 点应用
combined = hour_scene_pred * site_factor，仅 8-16 点应用
clip [0, capacity_mw]
```

### 站点级回退

只用 valid 判断站点是否回退：

```text
如果某站点 valid site_nrmse 恶化 > 0.5pp，回退该站点到 baseline
如果某站点 valid bias_abs 恶化 > 5pp，回退该站点到 baseline
```

输出：

```text
output/pv_pipeline/calibration/round60_site_level_guard.csv
```

字段：

```text
station_id
candidate
valid_baseline_nrmse
valid_candidate_nrmse
valid_delta_nrmse
valid_baseline_bias
valid_candidate_bias
fallback_applied
fallback_reason
```

### 小时级回退

只用 valid 判断小时是否回退：

```text
如果某小时 valid site_mean_nrmse 恶化 > 0.3pp，回退该小时到 baseline
如果某小时 valid city_nrmse 恶化 > 0.2pp，回退该小时到 baseline
如果某小时 valid bias_abs 恶化 > 3pp，回退该小时到 baseline
```

输出：

```text
output/pv_pipeline/calibration/round60_hour_level_guard.csv
```

最终候选：

```text
power_pred_round60_safe
```

---

## 八、valid 选择最终候选

新增：

```text
scripts/select_round60_final_prediction.py
```

候选：

```text
Round58 baseline
Round59 current
power_pred_round60_hour_scene
power_pred_round60_site_conservative
power_pred_round60_combined_conservative
power_pred_round60_safe
```

选择只用 valid。

score：

```text
score =
    0.35 * site_mean_nrmse_6_19
  + 0.25 * city_nrmse_6_19
  + 0.25 * site_mean_nrmse_10_14
  + 0.15 * abs(bias_6_19)
```

强制安全约束：

```text
site_mean_nrmse_6_19 <= Round58 + 0.2pp
city_nrmse_6_19 <= Round58 + 0.2pp
site_mean_nrmse_10_14 <= Round58 + 0.2pp
city_nrmse_10_14 <= Round58 + 0.2pp
abs(bias_6_19) <= Round58 + 1pp
```

如果没有候选满足，选择 Round58 baseline。

输出：

```text
output/pv_pipeline/calibration/round60_model_selection_valid.csv
```

---

## 九、重新生成 final/eval/metrics/dashboard

执行：

```bash
python scripts/train_site_bias_calibrator_conservative.py 2>&1 | tee output/pv_pipeline/logs/round60_train_site_conservative.log

python scripts/train_hour_scene_calibrator_conservative.py 2>&1 | tee output/pv_pipeline/logs/round60_train_hour_scene_conservative.log

python scripts/apply_round60_conservative_calibration.py 2>&1 | tee output/pv_pipeline/logs/round60_apply_conservative.log

python scripts/select_round60_final_prediction.py 2>&1 | tee output/pv_pipeline/logs/round60_select_final.log
```

然后：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode eval-only --force 2>&1 | tee output/pv_pipeline/logs/round60_eval_only.log

python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode dashboard-only --force 2>&1 | tee output/pv_pipeline/logs/round60_dashboard_only.log

python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode audit-only 2>&1 | tee output/pv_pipeline/logs/round60_audit_only.log
```

如果 `eval-only` 覆盖了 Round60 结果，必须修 `run_full_pipeline.py`，使它优先使用 `power_pred_round60_final`。

---

## 十、最终对比报告

新增或修改：

```text
scripts/compare_round58_round60_metrics.py
```

输出：

```text
output/pv_pipeline/metrics/round60_compare_summary.csv
output/pv_pipeline/metrics/round60_compare_hourly.csv
output/pv_pipeline/metrics/round60_compare_site.csv
docs/Round60_保守校准与安全回退执行报告.md
```

必须对比：

```text
Round58 baseline
Round59 current
Round60 selected
```

重点检查：

- 6-19 site_mean NRMSE
- 6-19 city NRMSE
- 10-14 site_mean NRMSE
- 10-14 city NRMSE
- 7h bias
- 17h bias
- 18-19h site_mean NRMSE
- 变差超过 +1pp 的站点数量
- S012/S019/S032/S053/S071/S115/S116/S022/S050

---

## 十一、验收标准

```text
[PASS] Round59 对比口径完成独立复核
[PASS] compare 脚本城市 NRMSE 与 Round58 公式一致
[PASS] 不完整重训
[PASS] 不使用 test 选择候选
[PASS] 有站点级 guard
[PASS] 有小时级 guard
[PASS] 变差超过 +1pp 的站点数量少于 Round59
[PASS] 10-14 city NRMSE 不高于 Round58
[PASS] 10-14 site_mean NRMSE 不高于 Round58 + 0.2pp
[PASS] 6-19 site_mean NRMSE 不高于 Round58 + 0.2pp
[PASS] 6-19 city NRMSE 不高于 Round58 + 0.2pp
[PASS] 7h bias_abs 下降或不明显变差
[PASS] 17h bias_abs 下降或不明显变差
[PASS] dashboard check 无 FAIL
[PASS] posttrain_validation 无 FAIL
```

如果 Round60 不如 Round58，则最终保持 Round58 baseline，并在报告中说明：

```text
保守校准未稳定超过 Round58，当前正式版本回退 Round58。
```

---

## 十二、生成 Round60 报告

新增：

```text
docs/Round60_保守校准与安全回退执行报告.md
```

模板：

```markdown
# Round60 保守校准与安全回退执行报告

## 1. 本轮目标

## 2. Round59 对比口径复核

## 3. 保守校准设置

## 4. 站点级回退结果

## 5. 小时级回退结果

## 6. valid 集选择结果

## 7. test 集最终对比

| 指标 | Round58 | Round59 | Round60 | 结论 |
|---|---:|---:|---:|---|

## 8. 重点小时对比

## 9. 重点站点对比

## 10. 是否采用 Round60

采用 / 回退 Round58。

## 11. 下一步建议
```

