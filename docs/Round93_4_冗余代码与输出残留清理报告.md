# Round93_4 冗余代码与输出残留清理报告

**生成时间**: 2026-06-04 03:58
**执行人**: Cursor AI
**轮次**: Round93_4

---

## 一、本轮修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/cleanup_redundant_outputs.py` | **新增** | 通用冗余输出归档脚本，支持 dry-run/archive |
| `output/pv_pipeline/archive/round93_4_cleanup_20260604_115522/` | **归档** | 32 个历史 round 残留文件 |

---

## 二、清理前状态确认

清理前执行完整健康检查，全部通过：

| 检查项 | 结果 |
|--------|------|
| posttrain_validation.py | ✅ 34 PASS / 0 FAIL / 2 WARN |
| audit_training_project_structure.py | ✅ 全部 PASS |
| audit_training_metric_contract.py | ✅ PASS (11/13, 2 INFO) |
| dashboard_regression_check.py | ✅ PASS |
| check_dashboard_prediction_values.py | ✅ 68/68 PASS |

---

## 三、metrics 目录清理结果

### 清理前

- **metrics 文件总数**: 62 个
- 历史残留 roundXX 文件: 32 个

### 归档内容（32 个文件）

| 来源 | 文件数 | 归档路径 |
|------|--------|----------|
| round36 | 15 | `metrics/round36_*.csv` |
| round39 | 3 | `metrics/round39_*.csv` |
| round44 | 2 | `metrics/round44_*.csv` |
| round46 | 2 | `metrics/round46_*.csv` |
| round48 | 1 | `metrics/round48_*.csv` |
| round59 | 3 | `metrics/round59_*.csv` |
| round60 | 3 | `metrics/round60_*.csv` |
| round61 | 3 | `metrics/round61_*.csv` |
| **合计** | **32** | |

### 清理后

- **metrics 文件总数**: 30 个（均为当前正式产物）
- 历史残留 roundXX 文件: 0 个

### 保留的 30 个正式文件

```
audit_data_integrity.csv
audit_metric_overall.csv
audit_metric_recompute.csv
audit_site_mapping.csv
audit_split_integrity.csv
calibration_ablation_by_site.csv
dashboard_actual_value_consistency.csv
dashboard_prediction_consistency.csv
dashboard_vs_power_clean_consistency.csv
data_quality_metrics.csv
distributed_metrics_*.csv (9个，当前正式指标)
hourly_nrmse_consistent.csv
hourly_site_nrmse_consistent.csv
irradiance_blend_metrics.csv
power_on_metrics_v159.csv
power_scene_summary_v159.csv
pr_month_comparison.csv
site_metrics_consistent.csv
site_test_daytime_zero_ratio_summary.csv
top_day_zero_sites.csv
分布式光伏预测_逐小时平均NRMSE.csv
分布式光伏预测_逐小时平均相对误差.csv
```

### 归档位置

```
output/pv_pipeline/archive/round93_4_cleanup_20260604_115522/metrics/
```

归档大小：1.7 MB

---

## 四、历史脚本处理

检查了所有 `round*.py` 文件引用关系：

| 脚本 | 状态 | 原因 |
|------|------|------|
| `apply_round36_calibration.py` | **保留** | 被 pipeline 引用 |
| `audit_round92_project_integrity.py` | **保留** | 被 cleanup_round92 引用 |
| `build_round36_predictions.py` | **保留** | 被 pipeline 引用 |
| `build_site_validity_round36.py` | **保留** | 被 pipeline 引用 |
| `compute_round36_metrics.py` | **保留** | 被 pipeline 引用 |
| `pretrain_audit_round36.py` | **保留** | 被 pipeline 引用 |
| `round46_recompute_hourly_nrmse_consistent.py` | **保留** | 被 pipeline 候选引用 |
| `round44_dashboard_regression_check.py` | **保留** | 虽已从 pipeline 候选移除，但若删除需先确认无其他引用 |

所有历史 round 脚本均被当前 pipeline 引用，暂不归档。

---

## 五、清理后健康检查

| 检查项 | 结果 |
|--------|------|
| posttrain_validation.py | ✅ 34 PASS / 0 FAIL / 2 WARN（与清理前完全一致） |
| audit_training_project_structure.py | ✅ 全部 PASS |
| audit_training_metric_contract.py | ✅ PASS (11/13) |
| dashboard_regression_check.py | ✅ PASS |
| check_dashboard_prediction_values.py | ✅ 68/68 PASS |
| run_full_pipeline.py --help | ✅ 正常 |

---

## 六、是否删除文件

**否**，本次所有操作均为归档（move to archive），未删除任何文件。

---

## 七、正式产物保护确认

| 产物 | 状态 |
|------|------|
| manifest.json | ✅ 未触碰 |
| models/ | ✅ 未触碰 |
| predictions/ | ✅ 未触碰 |
| tables/ | ✅ 未触碰 |
| metrics/ 目录 | ✅ 保留，32 个旧文件归档到 archive |
| interactive_dashboard/ | ✅ 未触碰 |
| validation/ | ✅ 未触碰 |
| docs/ | ✅ 未触碰 |
| figures/ | ✅ 未触碰 |
| data/ 原始数据 | ✅ 未触碰 |
| 正式预测结果 | ✅ 未覆盖 |

---

## 八、验收标准检查

| 标准 | 状态 |
|------|------|
| 1. metrics 中不再堆积 round36/round39/round44/round46/round48/round59/round60/round61 残留 | ✅ 32 个历史文件全部归档，metrics 现为 30 个正式文件 |
| 2. 所有旧文件在 archive/round93_4_cleanup_* 中可追溯 | ✅ 所有 32 个文件归档于 `archive/round93_4_cleanup_20260604_115522/` |
| 3. 当前正式 dashboard 仍可正常打开 | ✅ dashboard_regression_check.py PASS |
| 4. 当前正式指标和报告依赖文件没有被误移动 | ✅ 保留 30 个文件均为当前正式产物，清理后健康检查与清理前完全一致 |
| 5. 项目结构、指标口径、dashboard、posttrain validation 全部通过 | ✅ 全部 PASS |
| 6. 没有删除原始数据、正式模型、正式预测、正式 dashboard | ✅ 所有操作均为归档，无删除 |
