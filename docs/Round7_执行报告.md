# Round7 修改方案执行报告

> 生成时间：2026-05-23 21:45
> 执行目录：`/home/ac/data16t/msc/photovoltaic_forecasting_pj`

---

## 1. 修改内容

### 1.1 背景与目标

Round6 的结论是**自动后处理已到达边界**：S012/S055/S050/S032 的异常偏差在 train/valid 间不稳定，无法可靠自动修正。Round7 不再继续模型调优，而是做**工程闭环**：

1. 统一 final 指标来源，修复 CSV 与 final pkl 不一致问题
2. 完成整体流程验收
3. 完成任务书逐项对照
4. 归档无效候选和过期中间结果

### 1.2 新建文件（5个）

| 序号 | 文件路径 | 作用 |
|:---:|---|---|
| 1 | `scripts/regenerate_final_metrics_round7.py` | 从 `final_eval.pkl` 重算所有核心 metrics，覆盖旧的不一致文件 |
| 2 | `scripts/assert_final_metrics_consistency_round7.py` | 断言 CSV 与 final pkl 一致，检测旧数据残留（如 13.32 等） |
| 3 | `scripts/check_end_to_end_deliverables_round7.py` | 整体流程交付物验收，检查源码、表、metrics 是否齐全 |
| 4 | `scripts/generate_taskbook_compliance_round7.py` | 任务书完成情况对照，输出 CSV 和 MD 报告 |
| 5 | `scripts/archive_stale_outputs_round7.py` | 将无效候选和过期中间结果移动到 `archive_round7/` |

### 1.3 修改文件（3个）

| 文件 | 修改内容 |
|---|---|
| `scripts/update_project_md_metrics.py` | 移除对已归档文件的引用（`midday_next_step_gain_vs_site_calibrated.csv`），增加 Round7 工程闭环段落，更新 `当前最终结果摘要.md` 内容 |
| `scripts/train_fixed.py` | `FIX_SCRIPTS` 接入 Round7 脚本；`CRITICAL_SCRIPTS` 更新为 Round7 版本；`KEY_OUTPUT_FILES` 增加 Round7 输出文件 |
| `scripts/archive_stale_outputs_round7.py` | 修复 `should_archive()` 中变量作用域 bug |

---

## 2. 执行过程

### 2.1 执行命令序列

```bash
# 第一步：统一重算 metrics
python scripts/regenerate_final_metrics_round7.py

# 第二步：一致性断言
python scripts/assert_final_metrics_consistency_round7.py

# 第三步：流程验收 + 任务书对照（并行）
python scripts/check_end_to_end_deliverables_round7.py
python scripts/generate_taskbook_compliance_round7.py

# 第四步：更新报告
python scripts/update_project_md_metrics.py

# 第五步：归档（确认以上全部通过后）
python scripts/archive_stale_outputs_round7.py

# 第六步：归档后再次验证
python scripts/regenerate_final_metrics_round7.py
python scripts/assert_final_metrics_consistency_round7.py
python scripts/check_end_to_end_deliverables_round7.py
```

### 2.2 关键执行数据

#### 重算后的整体指标（`round7_final_overall_metrics.csv`）

| 指标 | 值 |
|---|---|
| 样本数 | 68,888 |
| 站点数 | 53 |
| 实际总出力 | 93,382.49 MWh |
| 预测总出力 | 92,069.09 MWh |
| pred_actual_ratio | 0.9859 |
| bias | -1.406% |
| MAE | 0.5893 MW |
| RMSE | 1.2047 MW |
| 全样本 NRMSE | 19.71% |

#### 重算后的逐小时 NRMSE（10-14 点关键验证）

| 小时 | 样本数 | site_nrmse（%） | city_nrmse（%） |
|---|---|---|---|
| 10 | 6,403 | **13.29** | 2.674 |
| 11 | 6,414 | **14.68** | 2.043 |
| 12 | 6,421 | **15.36** | 2.328 |
| 13 | 6,419 | **15.31** | 2.555 |
| 14 | 6,419 | **13.51** | 2.504 |

> 与 Round6 执行报告中承诺的目标值完全一致：13.29 / 14.68 / 15.36 / 15.31 / 13.51。旧数据（13.32/14.72/15.39/15.35/13.54）已全部清除。

---

## 3. 执行结果

### 3.1 各脚本执行结果

| 脚本 | 退出码 | 结果 |
|---|:---:|---|
| `regenerate_final_metrics_round7.py` | 0 | ✅ 通过，生成 6 个文件 |
| `assert_final_metrics_consistency_round7.py` | 0 | ✅ 通过，truth={10:13.29, 11:14.68, 12:15.36, 13:15.31, 14:13.51} |
| `check_end_to_end_deliverables_round7.py` | 0 | ✅ 18/18 项全部 OK |
| `generate_taskbook_compliance_round7.py` | 0 | ✅ 9 项任务书要求全部输出 |
| `update_project_md_metrics.py` | 0 | ✅ 报告已更新 |
| `archive_stale_outputs_round7.py` | 0 | ✅ 14 个文件归档 |
| **归档后重验证** | 0 | ✅ metrics 正确，核心文件未误删 |

### 3.2 归档清单（14个文件）

| 类别 | 原路径 | 归档路径 | 大小 |
|---|---|---|---|
| midday residual specialist pkl | `tables/distributed_predictions_midday_residual_specialist_eval.pkl` | `archive_round7/tables/` | 14.9 MB |
| midday residual specialist pkl | `tables/distributed_predictions_midday_residual_specialist_full.pkl` | `archive_round7/tables/` | 244.7 MB |
| round6 stable bias pkl | `tables/distributed_predictions_round6_stable_bias_eval.pkl` | `archive_round7/tables/` | 11.8 MB |
| round6 stable bias pkl | `tables/distributed_predictions_round6_stable_bias_full.pkl` | `archive_round7/tables/` | 193.2 MB |
| midday residual specialist csv | `metrics/midday_residual_specialist_params.csv` | `archive_round7/metrics/` | 0.1 MB |
| midday residual specialist csv | `metrics/midday_residual_specialist_valid_grid.csv` | `archive_round7/metrics/` | — |
| midday residual specialist csv | `metrics/midday_residual_specialist_valid_ablation.csv` | `archive_round7/metrics/` | — |
| midday residual specialist csv | `metrics/midday_residual_specialist_test_hourly_nrmse.csv` | `archive_round7/metrics/` | — |
| midday selective correction csv | `metrics/midday_selective_site_correction_params.csv` | `archive_round7/metrics/` | — |
| midday selective correction csv | `metrics/midday_selective_site_correction_valid_ablation.csv` | `archive_round7/metrics/` | — |
| midday selective correction csv | `metrics/midday_selective_site_correction_test_hourly_nrmse.csv` | `archive_round7/metrics/` | — |
| midday acceptance csv | `metrics/midday_nrmse_acceptance.csv` | `archive_round7/metrics/` | — |
| 周二基准对比 csv | `metrics/当前结果_vs_周二基准_整体对比.csv` | `archive_round7/metrics/` | — |
| 周二基准对比 csv | `metrics/当前结果_vs_周二基准_逐小时NRMSE对比.csv` | `archive_round7/metrics/` | — |

**未归档文件（永久保留）**：

```
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
output/pv_pipeline/tables/distributed_predictions_midday_site_calibrated_eval.pkl
output/pv_pipeline/tables/distributed_predictions_midday_site_calibrated_full.pkl
output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv
output/pv_pipeline/metrics/final_version_selection_by_hour.csv
output/pv_pipeline/metrics/round6_watch_site_diagnosis.csv
output/pv_pipeline/metrics/round6_site_capacity_mapping_diagnosis.csv
output/pv_pipeline/metrics/round6_midday_bias_stability_summary.csv
output/pv_pipeline/metrics/round6_stable_extreme_bias_candidates.csv
output/pv_pipeline/metrics/round7_final_overall_metrics.csv
output/pv_pipeline/metrics/round7_final_metrics_manifest.csv
output/pv_pipeline/metrics/round7_end_to_end_deliverables_check.csv
output/pv_pipeline/metrics/round7_taskbook_compliance.csv
output/pv_pipeline/docs/当前最终结果摘要.md
output/pv_pipeline/docs/任务书完成情况_Round7.md
```

### 3.3 任务书完成情况对照

| 任务书要求方向 | 完成状态 | 遗留问题 |
|---|:---:|---|
| 汇聚气象、辐照、功率、站点台账等多源数据 | 基本满足 | S012/S055/S050/S032 需人工核查功率列映射 |
| 利用集中式光伏功率反演光伏资源/辐照 | 满足 | 需说明辐照 NRMSE 归一化基准 |
| 将集中式信息扩展到分布式站点 | 满足 | 高误差站点需核查映射，而非继续调融合参数 |
| 实现分布式光伏功率预测 | 基本满足 | 小容量和异常映射站点误差偏高 |
| 输出站点级和全市级预测结果 | 满足 | 需清理过期候选结果（Round7 已完成） |
| 评估模型预测能力 | 满足 | 统一禁止使用旧 MAPE/WAPE |
| 逐小时误差诊断 | 满足 | 6/18/19 城市 NRMSE 仍偏高，本阶段暂不优化 |
| 结果闭环和可复现检查 | 满足 | 需归档过期产物（Round7 已完成） |
| 工程化交付 | 部分满足 | 需输出最终交付清单（Round7 已归档） |

---

## 4. 结论

### 4.1 本轮结论

Round7 未继续调模型，而是完成最终结果一致性和工程闭环：

1. **统一指标来源**：所有核心 metrics 均从 `distributed_predictions_final_eval.pkl` 重算，10-14 点 NRMSE 固定为 13.29/14.68/15.36/15.31/13.51
2. **修复不一致问题**：消除了旧 CSV 中的残留数据（13.32 等）
3. **流程验收通过**：18/18 项全部 OK，交付物完整
4. **任务书对照完成**：9 项要求全部有据可查
5. **归档过期产物**：14 个无效候选和过期中间结果移入 `archive_round7/`，可回溯

### 4.2 后续方向

**继续提升精度需要转向人工数据核查，而非继续自动后处理**：

1. 核查 S012/S055/S050/S032 的原始功率列名、别名、站点台账、装机容量、坐标
2. 对比这些站点与相邻站点的日曲线，确认是否列错位或混入其他站点
3. 若确认映射错误，修正映射表后重新从数据清洗开始跑全流程
4. 若映射无误，再考虑引入更高分辨率气象或站点分组模型

> 不要继续做纯后处理系数搜索；前几轮已经证明 valid 上的小幅改善无法稳定泛化到 test。
