# Round8 修改方案执行报告

> 生成时间：2026-05-23 22:31
> 执行目录：`/home/ac/data16t/msc/photovoltaic_forecasting_pj`

---

## 1. 修改内容

### 1.1 背景与目标

Round7 完成了主要工程闭环，但还残留几类交付层面的混淆点：

| 问题 | 当前表现 | Round8 处理 |
|---|---|---|
| Round6 诊断候选 pkl 残留 | `round6_stable_bias_*` 仍在 metrics 主目录 | 归档到 `archive_round7/` |
| `midday_next_step_gain_vs_site_calibrated.csv` 残留 | Round5 历史文件仍在 | 归档 |
| 旧周二对比文档残留 | `docs/当前结果_vs_周二基准对比.md` 仍在 | 归档 |
| 最终摘要含 Round5 参数段落 | 容易误以为 Round5 被 final 使用 | 删除并加历史说明 |
| 任务书文案未同步归档状态 | "需 archive" 仍在遗留问题中 | 更新文案 |
| 缺少正式交付清单 | 不知道哪些文件正式交付 | 生成 CSV/MD 清单 |

### 1.2 新建文件（4个）

| 序号 | 文件路径 | 作用 |
|:---:|---|---|
| 1 | `scripts/clean_final_summary_round8.py` | 删除摘要中的 Round5 参数段落，增加历史候选说明 |
| 2 | `scripts/update_taskbook_compliance_round8.py` | 修正任务书遗留问题文案为已归档状态 |
| 3 | `scripts/generate_final_delivery_manifest_round8.py` | 生成正式交付文件清单（CSV + MD） |
| 4 | `scripts/check_round8_final_package.py` | 最终交付包完整性检查 |

### 1.3 扩展文件（1个）

| 文件 | 修改内容 |
|---|---|
| `scripts/archive_stale_outputs_round7.py` | 扩展 `STALE_PATTERNS` 追加 round6 stable bias + midday_next_step；扩展扫描目录增加 `DOCS`；增加 `KEEP_PATTERNS` 保护项（midday_site_calibration 等） |

---

## 2. 执行过程

### 2.1 执行命令序列

```bash
# 归档扩展版（扫描 metrics + tables + docs）
python scripts/archive_stale_outputs_round7.py

# 清理摘要 + 更新任务书
python scripts/clean_final_summary_round8.py
python scripts/update_taskbook_compliance_round8.py

# 生成交付清单
python scripts/generate_final_delivery_manifest_round8.py

# 最终检查
python scripts/check_round8_final_package.py
```

### 2.2 归档清单

Round7 的扩展归档脚本本次归档了 5 个文件：

| 原路径 | 归档路径 | 大小 |
|---|---|---|
| `metrics/round6_stable_bias_correction_params.csv` | `archive_round7/metrics/` | 0.001 MB |
| `metrics/round6_stable_bias_test_hourly_nrmse.csv` | `archive_round7/metrics/` | — |
| `metrics/midday_next_step_gain_vs_site_calibrated.csv` | `archive_round7/metrics/` | — |
| `metrics/round6_stable_bias_valid_ablation.csv` | `archive_round7/metrics/` | — |
| `docs/当前结果_vs_周二基准对比.md` | `archive_round7/docs/` | 0.002 MB |

---

## 3. 执行结果

### 3.1 各脚本执行结果

| 脚本 | 退出码 | 结果 |
|---|:---:|---|
| `archive_stale_outputs_round7.py`（扩展版） | 0 | ✅ 归档 5 个文件 |
| `clean_final_summary_round8.py` | 0 | ✅ 摘要已清理 |
| `update_taskbook_compliance_round8.py` | 0 | ✅ 任务书文案已更新 |
| `generate_final_delivery_manifest_round8.py` | 0 | ✅ 交付清单已生成 |
| `check_round8_final_package.py` | 0 | ✅ **全部检查通过** |

### 3.2 最终交付文件清单（Round8）

**正式交付文件**（13项）：

| 类别 | 文件 |
|---|---|
| 预测表 | `tables/distributed_predictions_final_eval.pkl` |
| 预测表 | `tables/distributed_predictions_final_full.pkl` |
| 安全基准 | `tables/distributed_predictions_midday_site_calibrated_eval.pkl` |
| 安全基准 | `tables/distributed_predictions_midday_site_calibrated_full.pkl` |
| 指标 | `metrics/round7_final_overall_metrics.csv` |
| 指标 | `metrics/分布式光伏预测_逐小时平均NRMSE.csv` |
| 指标 | `metrics/final_version_selection_by_hour.csv` |
| 指标 | `metrics/round7_final_metrics_manifest.csv` |
| 指标 | `metrics/round7_final_metrics_summary.json` |
| 报告 | `docs/当前最终结果摘要.md` |
| 报告 | `docs/任务书完成情况_Round7.md` |
| 报告 | `docs/最终交付文件清单_Round8.md` |

**诊断保留文件**（7项）：

| 文件 | 用途 |
|---|---|
| `metrics/round6_watch_site_diagnosis.csv` | 高误差站点诊断 |
| `metrics/round6_site_capacity_mapping_diagnosis.csv` | 容量/映射诊断 |
| `metrics/round6_midday_bias_stability_summary.csv` | 正午偏差稳定性 |
| `metrics/round6_stable_extreme_bias_candidates.csv` | 稳定偏差候选 |
| `metrics/round6_flagged_site_diagnosis.csv` | 高误差标记 |
| `metrics/midday_site_calibration_params.csv` | MiddaySiteCalibrated 参数 |
| `metrics/midday_worst_site_hours_final.csv` | 最差站点小时 |

**归档历史文件**（Round7/Round8 共 19 个，全部在 `archive_round7/`）：

包括 Round5 选择性修正、Round6 稳定偏差、旧周二基准对比等历史诊断候选。

### 3.3 最终指标确认（不变）

| 指标 | 值 |
|---|---|
| final_eval 行数 | 68,888 |
| 站点数 | 53 |
| pred_actual_ratio | 0.9859 |
| MAE | 0.5893 MW |
| RMSE | 1.2047 MW |
| h10 NRMSE | 13.29% |
| h11 NRMSE | 14.68% |
| h12 NRMSE | 15.36% |
| h13 NRMSE | 15.31% |
| h14 NRMSE | 13.51% |

---

## 4. 结论

Round8 未修改模型结果，仅完成最终交付清理：

1. **final 指标保持不变** — 未触碰任何 pkl
2. **过期候选和历史对比文件已全部归档** — 19 个文件移入 `archive_round7/`
3. **当前最终结果摘要不再包含误导性的 Round5 参数段落** — 已删除并增加历史候选说明
4. **任务书完成情况文案已同步归档状态** — 不再写"需 archive"
5. **已生成正式交付文件清单** — CSV 和 MD 共 13 项必须文件 + 7 项诊断保留文件
6. **当前项目可作为"既有数据集上的分布式光伏预测模型能力评估与工程化结果包"提交**

**后续提升方向**：不再做自动后处理，应人工核查 S012/S055/S050/S032 的功率列映射和别名字典。
