# Cursor 执行方案 Round57：预测精度问题评估与流程遗留问题体检

## 目标

本轮先评估问题，不盲目修改模型。

要回答：

1. 当前预测误差主要来自哪些站点、哪些小时、哪些季节、哪些场景？
2. 误差是数据质量问题、气象/辐照特征问题、容量/映射问题、模型偏差问题，还是后处理问题？
3. 10-14 点、早晚边界、低功率样本、分布漂移站点分别表现如何？
4. S115/S116 链路是否持续正常？
5. Round56 遗留的 Step 11 耗时、manifest 时间戳 WARN、诊断口径误读问题如何一起收口？

本轮原则：

- 不修改模型训练策略。
- 不改最终预测列。
- 不重新完整训练，除非诊断发现当前产物损坏。
- 只新增评估脚本、诊断表、报告和轻量流程修正。

---

## 一、进入项目目录

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
mkdir -p output/pv_pipeline/diagnostics
mkdir -p output/pv_pipeline/validation
mkdir -p output/pv_pipeline/logs
```

---

## 二、先跑基础验证，确认当前产物可用

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode audit-only 2>&1 | tee output/pv_pipeline/logs/round57_audit_only.log

python scripts/diagnose_s115_s116_prediction_flow.py 2>&1 | tee output/pv_pipeline/logs/round57_s115_s116.log
```

如果出现 FAIL，不进入精度诊断，先修产物一致性。

检查：

```bash
grep -Ei "FAIL|ERROR|Traceback|Exception|FileNotFound|KeyError|ValueError" \
  output/pv_pipeline/logs/round57_audit_only.log \
  output/pv_pipeline/logs/round57_s115_s116.log || true
```

---

## 三、新增综合误差诊断脚本

新增：

```text
scripts/diagnose_prediction_error_drivers.py
```

输入：

```text
output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
output/pv_pipeline/metrics/site_metrics_consistent.csv
output/pv_pipeline/manifest.json
configs/manual_station_geo_overrides.csv
```

输出：

```text
output/pv_pipeline/diagnostics/round57_error_by_site.csv
output/pv_pipeline/diagnostics/round57_error_by_hour.csv
output/pv_pipeline/diagnostics/round57_error_by_site_hour.csv
output/pv_pipeline/diagnostics/round57_error_by_month.csv
output/pv_pipeline/diagnostics/round57_error_by_scene.csv
output/pv_pipeline/diagnostics/round57_error_driver_summary.csv
output/pv_pipeline/diagnostics/round57_priority_sites.csv
```

### 1. 统一评估口径

只评估：

```text
split == test
hour 6-19
exclude future
pred_col = power_pred_final
```

不要使用 MAPE/WAPE 作为主指标。

核心公式：

```text
MAE = mean(|pred - actual|)
RMSE = sqrt(mean((pred - actual)^2))
站点 NRMSE = RMSE / capacity_mw × 100%
城市 NRMSE = RMSE(sum(pred), sum(actual)) / sum(capacity_mw) × 100%
BIAS% = (sum(pred) - sum(actual)) / sum(actual) × 100%
pred/actual = sum(pred) / sum(actual)
```

### 2. 站点级诊断字段

`round57_error_by_site.csv` 字段：

```text
station_id
station_name
capacity_mw
rows
positive_rows
zero_ratio_6_19
actual_sum_mwh_like
pred_sum_mwh_like
pred_actual_ratio
bias_percent
mae_mw
rmse_mw
nrmse_percent
pred_zero_ratio_6_19
actual_max_mw
pred_max_mw
max_power_ratio
has_geo_ratio
geo_confidence
scene_night_ratio_6_19
scene_low_ratio
scene_mid_ratio
scene_clear_peak_ratio
g_blend_non_null_ratio
g_blend_zero_ratio
solar_elevation_non_null_ratio
risk_flags
```

### 3. 小时级诊断字段

`round57_error_by_hour.csv` 字段：

```text
hour
rows
site_mean_nrmse_percent
city_nrmse_percent
mae_mw_mean
rmse_mw_mean
bias_percent_city
pred_actual_ratio_city
actual_sum
pred_sum
zero_ratio_actual
zero_ratio_pred
top_error_sites
```

### 4. 站点-小时诊断

`round57_error_by_site_hour.csv` 字段：

```text
station_id
station_name
hour
rows
nrmse_percent
mae_mw
rmse_mw
bias_percent
pred_actual_ratio
actual_zero_ratio
pred_zero_ratio
scene_main
risk_flags
```

用于定位：

- 哪些站点在 10-14 点拖高站点平均 NRMSE；
- 哪些站点早晚边界误差高；
- 哪些站点白天预测长期偏高/偏低。

### 5. 月份/季节诊断

`round57_error_by_month.csv` 字段：

```text
month
rows
site_mean_nrmse_percent
city_nrmse_percent
bias_percent_city
pred_actual_ratio_city
top_error_sites
```

目标：

- 看是否 9-12 月某个月份误差明显高；
- 判断是否有季节漂移或测试期分布漂移。

### 6. 场景诊断

按 `scene_v151` 或实际可用场景字段统计：

```text
scene
rows
site_mean_nrmse_percent
city_nrmse_percent
bias_percent
pred_actual_ratio
top_error_sites
```

如果 `scene_v151` 缺失，报告中明确写：

```text
final_eval 未包含 scene 字段，本轮无法做场景误差诊断。
```

不要用空字段硬算。

---

## 四、误差原因自动打标

在 `round57_error_by_site.csv` 和 `round57_error_by_site_hour.csv` 中生成 `risk_flags`。

规则建议：

```python
flags = []
if nrmse_percent >= 20:
    flags.append("high_nrmse")
if abs(bias_percent) >= 20:
    flags.append("high_bias")
if pred_actual_ratio >= 1.25:
    flags.append("over_prediction")
if pred_actual_ratio <= 0.75:
    flags.append("under_prediction")
if zero_ratio_6_19 >= 0.5:
    flags.append("high_actual_zero_ratio")
if pred_zero_ratio_6_19 >= 0.5:
    flags.append("high_pred_zero_ratio")
if g_blend_zero_ratio >= 0.5:
    flags.append("irradiance_zero_or_missing")
if has_geo_ratio < 1:
    flags.append("missing_geo")
if geo_confidence == "low":
    flags.append("low_confidence_geo")
if max_power_ratio > 1.2:
    flags.append("capacity_or_power_outlier")
if scene_night_ratio_6_19 > 0.2:
    flags.append("daytime_scene_night")
```

要求：

- 每个高误差站点至少给出一个可能原因。
- 如果无法判断，标记 `unknown_driver`。

---

## 五、输出“优先处理站点”清单

`round57_priority_sites.csv`：

```text
priority_rank
station_id
station_name
capacity_mw
nrmse_percent
bias_percent
pred_actual_ratio
zero_ratio_6_19
main_bad_hours
main_risk_flags
recommended_next_action
```

优先级规则：

```text
1. NRMSE 高且容量大
2. 对城市 NRMSE 贡献大
3. 10-14 点误差高
4. 非数据缺失导致，存在模型可改空间
```

`recommended_next_action` 示例：

```text
检查容量映射
检查功率数据异常/限电
检查辐照特征
检查低置信度经纬度
考虑站点级偏差校准
考虑小时级残差模型
暂不建议模型修正，需数据确认
```

---

## 六、训练链路完整性审计

运行已有审计脚本 quick 模式：

```bash
python scripts/audit_training_pipeline_flow.py --level quick 2>&1 | tee output/pv_pipeline/logs/round57_pipeline_audit_quick.log
```

如脚本不存在或输出不完整，补充以下审计：

```text
数据入口是否齐全
train/valid/test 时间范围是否正确
manual geo override 是否进入 station metadata
final_eval 是否只包含 test 6-19
dashboard 是否来自 canonical final
manifest artifacts 是否存在
```

输出：

```text
output/pv_pipeline/validation/round57_pipeline_audit_summary.md
```

---

## 七、顺手解决 Round56 遗留小问题

### 1. manifest 新鲜度改用 hash，不只看 mtime

当前 C16 因 auto-sync 可能出现时间 WARN。

修改：

```text
scripts/run_full_pipeline.py
scripts/posttrain_validation.py
```

要求 manifest 记录 canonical artifact 的 hash：

```json
"artifact_hashes": {
  "final_full_pkl": "...",
  "final_eval_pkl": "...",
  "hourly_nrmse_csv": "...",
  "site_metrics_csv": "...",
  "dashboard_index": "..."
}
```

`posttrain_validation.py`：

- 优先检查 hash 是否一致；
- hash 一致时，即使 mtime 早于 pkl，也 PASS；
- hash 不一致时 FAIL；
- 不要因为 auto-sync 直接降级 WARN。

### 2. Step 11 拆分为轻量子步骤

暂不大改架构，只在 `run_full_pipeline.py` 中明确拆分日志：

```text
11a recompute_hourly_metrics
11b export_dashboard_data
11c dashboard_stamp_check
11d dashboard_regression_check
```

每个子步骤单独计时，方便下一步继续优化。

### 3. 删除或修正 Round55 误判说明

在最新报告中不要再写：

```text
S115/S116 final_full scene_v151 = all night 是预期行为
```

改为：

```text
Round55 all night 为诊断 scope 误读；以 test 10-14 口径为准，S115/S116 链路正常。
```

---

## 八、执行诊断

```bash
python scripts/diagnose_prediction_error_drivers.py 2>&1 | tee output/pv_pipeline/logs/round57_error_driver_diagnosis.log

python scripts/audit_training_pipeline_flow.py --level quick 2>&1 | tee output/pv_pipeline/logs/round57_pipeline_audit_quick.log

python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode audit-only 2>&1 | tee output/pv_pipeline/logs/round57_final_audit.log
```

检查：

```bash
grep -Ei "FAIL|ERROR|Traceback|Exception|FileNotFound|KeyError|ValueError" \
  output/pv_pipeline/logs/round57_error_driver_diagnosis.log \
  output/pv_pipeline/logs/round57_pipeline_audit_quick.log \
  output/pv_pipeline/logs/round57_final_audit.log || true
```

---

## 九、生成 Round57 诊断报告

新增：

```text
docs/Round57_预测精度问题评估与训练链路体检报告.md
```

模板：

```markdown
# Round57 预测精度问题评估与训练链路体检报告

## 1. 本轮目标

## 2. 是否修改模型

本轮不修改模型，仅做诊断。

## 3. 当前总体结果

| 指标 | 结果 | 结论 |
|---|---:|---|
| 6-19 城市 NRMSE |  |  |
| 10-14 城市 NRMSE |  |  |
| 站点平均 NRMSE |  |  |
| 高误差站点数量 |  |  |

## 4. 误差主要集中在哪里

### 4.1 按小时

说明哪些小时高，可能原因是什么。

### 4.2 按站点

列出高误差站点及原因。

### 4.3 按月份/季节

说明是否存在测试期分布漂移。

### 4.4 按场景

说明低辐照、clear_peak、mid、早晚等场景表现。

## 5. 主要问题归因

| 问题类型 | 涉及站点/时段 | 证据 | 是否适合通过模型修复 |
|---|---|---|---|
| 数据质量 |  |  |  |
| 经纬度/气象 |  |  |  |
| 容量/映射 |  |  |  |
| 系统性偏差 |  |  |  |
| 模型欠拟合/泛化 |  |  |  |

## 6. 优先处理站点

粘贴 priority_sites 前 10。

## 7. 训练链路体检结果

## 8. Round56 遗留问题处理

- manifest hash：
- Step 11 子步骤耗时：
- S115/S116 诊断口径修正：

## 9. 下一步建议

只提出方向，不直接改模型：

1. 如果主要是系统性偏差：考虑站点级/小时级 bias 校准。
2. 如果主要是场景误差：考虑场景专用残差模型。
3. 如果主要是气象/辐照缺失：先修特征。
4. 如果主要是数据质量：先剔除或单独标记异常站点。
```

---

## 十、验收标准

```text
[PASS] 不完整重训
[PASS] 不修改模型训练策略
[PASS] 输出 round57_error_by_site.csv
[PASS] 输出 round57_error_by_hour.csv
[PASS] 输出 round57_error_by_site_hour.csv
[PASS] 输出 round57_error_by_month.csv
[PASS] 输出 round57_error_by_scene.csv 或说明 scene 字段缺失
[PASS] 输出 round57_priority_sites.csv
[PASS] 输出 round57_pipeline_audit_summary.md
[PASS] manifest 新鲜度优先用 hash 判断
[PASS] Step 11 子步骤有独立耗时
[PASS] posttrain/dashboard audit 无 FAIL
```

