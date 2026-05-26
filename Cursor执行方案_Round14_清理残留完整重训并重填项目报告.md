# Cursor 执行方案 Round14：清理残留、完整重训并重新填写项目报告

## 0. 本轮目标

在当前已通过严谨性验证的基础上，执行一次完整整理：

1. 清理历史修改残留、无用训练中间文件、过期结果文件。
2. 保留并备份当前 Grade A 可交付版本。
3. 重新完整执行一遍训练流程。
4. 完整训练后重新生成全部核心指标。
5. 重新填写 `光伏功率预测项目.md`。
6. 再次执行严谨性验证，确保新结果仍达到 Grade A。
7. 如果完整重训后的结果不如当前已验证版本，则自动回退到当前最优版本。

本轮重点是：

```text
清理工程状态 + 完整复现训练 + 重新生成正式报告
```

不是继续调参。

---

## 1. 严格禁止事项

本轮不要直接删除以下内容：

```text
data/
configs/
config/
src/
scripts/
stages/
requirements.txt
README.md
```

不要直接删除当前已验证的核心结果：

```text
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
output/pv_pipeline/tables/best_predictions_eval.pkl
output/pv_pipeline/tables/best_predictions_full.pkl
output/pv_pipeline/metrics/round10_overall_nrmse_summary.csv
output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv
output/pv_pipeline/interactive_dashboard/
docs/训练过程与结果严谨性验证报告.md
光伏功率预测项目.md
```

历史文件可以清理，但必须先移动到：

```text
output/pv_pipeline/archive_round14/
```

并生成归档清单。

---

## 2. 本轮推荐新增脚本

请新增以下脚本：

```text
scripts/backup_current_verified_state_round14.py
scripts/archive_stale_artifacts_round14.py
scripts/run_full_retrain_round14.py
scripts/compare_retrain_with_verified_best_round14.py
scripts/regenerate_project_report_round14.py
scripts/check_round14_final_delivery.py
```

各脚本职责：

| 脚本 | 作用 |
|---|---|
| `backup_current_verified_state_round14.py` | 备份当前 Grade A 版本 |
| `archive_stale_artifacts_round14.py` | 归档历史残留文件 |
| `run_full_retrain_round14.py` | 统一调用完整训练与后处理流程 |
| `compare_retrain_with_verified_best_round14.py` | 比较重训结果与备份最优结果，必要时回退 |
| `regenerate_project_report_round14.py` | 重新填写 `光伏功率预测项目.md` |
| `check_round14_final_delivery.py` | 最终交付检查 |

---

## 3. Step 1：备份当前 Grade A 版本

新增：

```text
scripts/backup_current_verified_state_round14.py
```

### 3.1 备份目录

```text
output/pv_pipeline/verified_backup_round14/
```

### 3.2 必须备份文件

```text
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
output/pv_pipeline/tables/best_predictions_eval.pkl
output/pv_pipeline/tables/best_predictions_full.pkl
output/pv_pipeline/metrics/round10_overall_nrmse_summary.csv
output/pv_pipeline/metrics/round10_hour_overall_nrmse.csv
output/pv_pipeline/metrics/round10_site_hour_nrmse.csv
output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv
output/pv_pipeline/metrics/round11_candidate_leaderboard.csv
output/pv_pipeline/interactive_dashboard/
docs/训练过程与结果严谨性验证报告.md
光伏功率预测项目.md
```

### 3.3 输出 manifest

生成：

```text
output/pv_pipeline/verified_backup_round14/backup_manifest.csv
```

字段：

```text
source_path
backup_path
exists
size_bytes
sha256
copied_at
```

### 3.4 验收

备份后必须确认：

```text
best_predictions_eval.pkl 可读
distributed_predictions_final_eval.pkl 可读
overall NRMSE = 19.7105%左右
final = best
```

如果备份失败，立即停止，不允许继续清理。

---

## 4. Step 2：归档清理历史残留

新增：

```text
scripts/archive_stale_artifacts_round14.py
```

### 4.1 原则

只归档，不硬删。

归档目录：

```text
output/pv_pipeline/archive_round14/
```

### 4.2 建议归档对象

归档以下类型：

#### 旧候选模型产物

```text
output/pv_pipeline/tables/*specialist*
output/pv_pipeline/tables/*round6*
output/pv_pipeline/tables/*round9*
output/pv_pipeline/models/*specialist*
output/pv_pipeline/models/*round6*
output/pv_pipeline/models/*round9*
```

#### 旧版临时指标

```text
output/pv_pipeline/metrics/*MAPE*
output/pv_pipeline/metrics/*相对误差*
output/pv_pipeline/metrics/v3_*
output/pv_pipeline/metrics/v4_*
output/pv_pipeline/metrics/round6_*
output/pv_pipeline/metrics/round9_*
```

注意：

```text
不要归档 round10 / round11 / round12 / audit / final / best 相关指标。
```

#### 旧图表和旧报告

```text
docs/Round5_*
docs/Round6_*
docs/Round7_*
docs/Round8_*
docs/Round9_*
docs/Round10_*
docs/Round11_*
docs/Round12_*
```

保留最新审计报告和最终项目报告。

### 4.3 必须保留清单

清理脚本中写死保护清单：

```python
KEEP_PATTERNS = [
    "distributed_predictions_final_eval.pkl",
    "distributed_predictions_final_full.pkl",
    "best_predictions_eval.pkl",
    "best_predictions_full.pkl",
    "round10_overall_nrmse_summary.csv",
    "round10_hour_overall_nrmse.csv",
    "round10_site_hour_nrmse.csv",
    "round11_candidate_leaderboard.csv",
    "分布式光伏预测_逐小时平均NRMSE.csv",
    "audit_summary.json",
    "audit_metric_recompute.csv",
    "audit_metric_overall.csv",
]
```

### 4.4 输出清单

生成：

```text
output/pv_pipeline/archive_round14/archive_manifest.csv
```

字段：

```text
source_path
archive_path
size_bytes
sha256
reason
archived_at
```

### 4.5 验收

归档后运行：

```bash
python scripts/check_pipeline_consistency.py
python scripts/audit_training_process_and_results.py \
  --output-root output/pv_pipeline \
  --report-path docs/训练过程与结果严谨性验证报告.md
```

要求：

```text
final 仍可读
best 仍可读
final = best
审计仍为 Grade A 或至少无 FAIL
```

如果清理后审计失败，立即从 `verified_backup_round14` 恢复。

---

## 5. Step 3：完整重新训练

新增：

```text
scripts/run_full_retrain_round14.py
```

该脚本统一调用现有训练入口。

优先执行：

```bash
python scripts/train_fixed.py
```

训练完成后必须自动执行：

```bash
python scripts/run_round10_best_guard_pipeline.py
python scripts/regenerate_final_metrics_round7.py
python scripts/compute_nrmse_reports_round10.py
python scripts/export_interactive_dashboard_data.py \
  --output-root output/pv_pipeline \
  --dashboard-root output/pv_pipeline/interactive_dashboard
python scripts/audit_training_process_and_results.py \
  --output-root output/pv_pipeline \
  --report-path docs/训练过程与结果严谨性验证报告.md
```

### 5.1 重训日志

所有日志写入：

```text
output/pv_pipeline/logs/round14_full_retrain.log
```

### 5.2 训练后生成指标

完整训练后必须存在：

```text
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
output/pv_pipeline/tables/best_predictions_eval.pkl
output/pv_pipeline/tables/best_predictions_full.pkl
output/pv_pipeline/metrics/round10_overall_nrmse_summary.csv
output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv
output/pv_pipeline/interactive_dashboard/index.json
docs/训练过程与结果严谨性验证报告.md
```

---

## 6. Step 4：与备份最优版本比较，必要时回退

新增：

```text
scripts/compare_retrain_with_verified_best_round14.py
```

### 6.1 比较对象

当前重训后：

```text
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
```

备份版本：

```text
output/pv_pipeline/verified_backup_round14/tables/distributed_predictions_final_eval.pkl
```

### 6.2 比较指标

统一使用 test 6-19 点：

```text
rows
site_count
MAE
RMSE
overall NRMSE
bias
pred_actual_ratio
10-14点站点平均 NRMSE
10-14点城市 NRMSE
逐小时站点平均 NRMSE
逐小时城市 NRMSE
```

### 6.3 晋级规则

新重训结果必须同时满足：

```text
overall NRMSE 不高于备份版本 + 0.05pp
10-14点站点平均 NRMSE 不高于备份版本 + 0.05pp
MAE 不高于备份版本 + 0.005 MW
RMSE 不高于备份版本 + 0.005 MW
final = best
审计 Grade A
```

如果不满足：

```text
自动恢复 verified_backup_round14 中的 final/best/metrics/report/page 数据。
```

### 6.4 输出

生成：

```text
output/pv_pipeline/metrics/round14_retrain_vs_verified_best.csv
output/pv_pipeline/metrics/round14_retrain_decision.json
docs/Round14_完整重训与回退决策报告.md
```

`round14_retrain_decision.json` 字段：

```json
{
  "accepted": true,
  "reason": "...",
  "current_overall_nrmse": 0,
  "backup_overall_nrmse": 0,
  "current_midday_site_nrmse": 0,
  "backup_midday_site_nrmse": 0,
  "restored_from_backup": false
}
```

---

## 7. Step 5：重新填写 `光伏功率预测项目.md`

新增：

```text
scripts/regenerate_project_report_round14.py
```

或在现有：

```text
scripts/update_project_md_metrics.py
```

基础上增强。

### 7.1 报告数据来源

报告所有数据必须来自当前最终产物：

```text
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
output/pv_pipeline/tables/site_master.csv
output/pv_pipeline/metrics/round10_overall_nrmse_summary.csv
output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv
output/pv_pipeline/metrics/round11_candidate_leaderboard.csv
output/pv_pipeline/metrics/audit_summary.json
output/pv_pipeline/interactive_dashboard/scatter_site_sample_nrmse.json
```

### 7.2 报告必须包含

```text
一、数据集情况
二、训练流程简述
三、训练结果
四、可视化页面说明
五、任务书完成情况
六、严谨性验证结论
七、当前存在的问题
```

### 7.3 训练结果必须包含

```text
集中式功率到辐照反演
全站点辐照融合
分布式功率预测整体结果
逐小时预测结果
10-14点重点时段结果
站点样本量与 NRMSE 关系
final/best 一致性
```

### 7.4 指标要求

继续坚持：

```text
不使用 WAPE 作为主指标
不使用 MAPE 作为主指标
主指标使用 NRMSE、MAE、RMSE、bias、pred/actual ratio
```

所有单位必须写清楚：

```text
MW
MWh
%
行
座
```

### 7.5 严谨性验证结论

报告中加入：

```text
当前训练过程与结果已通过严谨性验证：
Grade A
FAIL = 0
WARN = 0
final = best
指标可复算
页面与报告一致
```

---

## 8. Step 6：最终交付检查

新增：

```text
scripts/check_round14_final_delivery.py
```

检查：

```text
核心 pkl 可读
final = best
审计 Grade A
项目报告存在
项目报告不含 WAPE/MAPE 主指标描述
逐小时表存在 6-19 点 14 行
页面 JSON 存在
全量历史样本最大值 >= 20000
archive manifest 存在
backup manifest 存在
```

输出：

```text
output/pv_pipeline/metrics/round14_final_delivery_check.csv
```

全部通过后打印：

```text
[OK] Round14 final delivery package is ready
```

---

## 9. Cursor 执行顺序

请严格按顺序执行：

```bash
# 1. 备份当前 Grade A 版本
python scripts/backup_current_verified_state_round14.py

# 2. 归档清理历史残留
python scripts/archive_stale_artifacts_round14.py

# 3. 清理后立即做一次审计，确认没有误伤
python scripts/audit_training_process_and_results.py \
  --output-root output/pv_pipeline \
  --report-path docs/训练过程与结果严谨性验证报告.md

# 4. 完整重新训练
python scripts/run_full_retrain_round14.py

# 5. 比较重训结果和备份最优版本，必要时自动回退
python scripts/compare_retrain_with_verified_best_round14.py

# 6. 重新生成交互页面数据
python scripts/export_interactive_dashboard_data.py \
  --output-root output/pv_pipeline \
  --dashboard-root output/pv_pipeline/interactive_dashboard

# 7. 重新填写项目报告
python scripts/regenerate_project_report_round14.py

# 8. 再次严谨性验证
python scripts/audit_training_process_and_results.py \
  --output-root output/pv_pipeline \
  --report-path docs/训练过程与结果严谨性验证报告.md

# 9. 最终交付检查
python scripts/check_round14_final_delivery.py
```

---

## 10. 最终验收标准

最终必须满足：

```text
FAIL = 0
WARN = 0
Grade A
final = best
核心指标可复算
逐小时指标可复算
页面与报告一致
光伏功率预测项目.md 已重填
无 WAPE/MAPE 主指标
清理文件均有 archive manifest
当前 Grade A 版本有 verified backup
```

最终报告中应明确写：

```text
本轮执行了历史残留归档、完整训练复现、最优版本保护、指标复算、页面一致性检查和严谨性验证。最终版本达到 Grade A，可作为阶段性交付版本。
```

---

## 11. 如果完整重训失败怎么办

如果训练中断或结果变差：

1. 不要手工改指标。
2. 不要强行覆盖 best。
3. 执行恢复：

```bash
python scripts/compare_retrain_with_verified_best_round14.py --restore-only
```

4. 恢复后重新运行：

```bash
python scripts/audit_training_process_and_results.py \
  --output-root output/pv_pipeline \
  --report-path docs/训练过程与结果严谨性验证报告.md
```

确保回到：

```text
Grade A
final = best
overall NRMSE ≈ 19.7105%
```

---

## 12. 提交说明建议

```text
Round14: clean stale artifacts, rerun full training, and regenerate final report

- backup current Grade A verified outputs
- archive stale candidate and legacy metric artifacts with manifest
- run full training pipeline and best guard
- compare retrained outputs against verified best and restore if worse
- regenerate interactive dashboard data and project report
- rerun strict audit and final delivery checks
```

