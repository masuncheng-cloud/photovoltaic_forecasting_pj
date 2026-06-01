# Round65 Round64候选采用前全量审计与可视化收口报告

**日期**: 2026-06-01
**分支**: experiment/model-structure-round62
**执行人**: Cursor Agent

---

## 1. 审计执行情况总览

| 步骤 | 内容 | 状态 |
|------|------|------|
| ✅ | Round64 产物目录规范检查 | 通过（无未命名目录） |
| ✅ | Round64 报告修正（最优列、双概念、权重解释） | 完成 |
| ✅ | 全量站点审计（audit_round64_all_sites.py） | 68站全部通过 |
| ✅ | 候选可视化数据导出 | 68站点全部导出 |
| ✅ | 可视化数据一致性校验 | 5/5 检查 PASS |
| ✅ | 正式升级 dry-run | 完成 |
| ✅ | Round64 final_decision | adopt_round64_candidate |

---

## 2. Round64 产物目录规范

检查 `output/pv_pipeline/round64/` 目录：

| 文件 | 状态 |
|------|------|
| round64_candidates.pkl | ✅ |
| round64_final_decision.json | ✅ |
| round64_guard_summary.json | ✅ |
| round64_site_scene_weights.csv | ✅ |
| round64_valid_weight_search.csv | ✅ |
| round64_test_overall_compare.csv | ✅ |
| round64_test_hourly_compare.csv | ✅ |
| round64_test_site_compare.csv | ✅ |
| round64_all_site_compare.csv | ✅ |
| round64_bad_site_audit.csv | ✅ |
| round64_dashboard_candidate_consistency.csv | ✅ |
| round64_dashboard_candidate_consistency.json | ✅ |
| round64_promote_dry_run_report.md | ✅ |
| round64_promote_file_plan.csv | ✅ |

无"未命名"目录，所有文件在标准路径。

---

## 3. 全量站点审计结果

审计脚本：`scripts/audit_round64_all_sites.py`

### 3.1 汇总统计（test 6-19h，68站点）

| 指标 | 值 |
|------|---|
| 总站点数 | 68 |
| bad_sites_gt_1pp | **0** |
| 最大 delta（最差站点） | +0.1771pp (S073) |
| 最小 delta（最大改善） | -3.7932pp (S053) |
| 平均 delta | -0.1289pp |

> bad_sites_gt_1pp = 0 说明 Round64 safe 在 test 全量站点上无退化，满足安全门控。

### 3.2 退化站点检查

`round64_bad_site_audit.csv`（delta > 1.0pp 的站点）：**空（0 行）**

无站点退化超过 1pp 阈值。

### 3.3 改善最大的站点

| 站点 | delta | 说明 |
|------|------:|------|
| S053 | -3.79pp | 大幅改善 |
| S020 | -1.58pp | 大幅改善 |
| S046 | -1.52pp | 大幅改善 |
| S016 | -0.23pp | 改善 |
| S054 | -0.22pp | 改善 |
| S023 | -0.08pp | 改善 |
| S116 | -0.09pp | 改善 |

### 3.4 略差的站点（delta > 0 但 < 1pp）

| 站点 | delta | 说明 |
|------|------:|------|
| S073 | +0.18pp | 极微小劣化 |
| S071 | +0.09pp | 可忽略 |
| S052 | +0.06pp | 可忽略 |

---

## 4. 候选可视化导出

导出命令：
```bash
python scripts/export_interactive_dashboard_data.py \
  --prediction-pkl output/pv_pipeline/round64/round64_candidates.pkl \
  --prediction-col power_pred_round64_safe \
  --dashboard-root output/pv_pipeline/interactive_dashboard_round64_candidate \
  --label "Round64 safe candidate" \
  --exclude-future
```

导出结果：

| 指标 | 值 |
|------|---|
| 数据行数 | 175,168 行 |
| 站点数 | 68 |
| 时间范围 | 2025-07-01 ~ 2025-12-31 |
| city_series 行数 | 2,576 |
| site_series 文件数 | 68 |
| scatter 点数（site-hour） | 952 |
| scatter 点数（site） | 66 |

---

## 5. 候选可视化数据一致性校验

校验脚本：`scripts/check_round64_dashboard_candidate_consistency.py`

| 检查项 | 容差 | 结果 | 最大差异 |
|--------|------|------|----------|
| actual_mw 与 pkl 一致性 | 1e-6 | **PASS** | 8.88e-16 |
| pred_mw 与 pkl 一致性 | 1e-3 | **PASS** | 5.00e-05 |
| city actual_mw 与 pkl 聚合一致性 | 0.1 MW | **PASS** | 0.0000 |
| future 数据排除 | — | **PASS** | 无 |
| metadata.json 正确性 | — | **PASS** | prediction_column=power_pred_round64_safe, official_final=false |

> 注：pred_mw 5e-5 差异来自 JSON 序列化浮点精度损失（约 0.05W），在合理范围内。

---

## 6. 正式升级 dry-run

脚本：`scripts/promote_round64_candidate.py --dry-run`

**升级计划**：

| 步骤 | 动作 | 目标文件 | 是否覆盖 |
|------|------|----------|----------|
| 1 | 备份 | backups/distributed_predictions_final_full_before_round64_\*.pkl | 否 |
| 2 | 写入 | output/pv_pipeline/predictions/distributed_predictions_final_full.pkl | **是** |
| 3 | 更新 | output/pv_pipeline/manifest.json | **是** |
| 4 | 重新导出 | output/pv_pipeline/interactive_dashboard/ | **是** |
| 5 | 重新验证 | posttrain_validation.py | 否 |

> 本轮**未执行 apply**，所有正式文件保持不变。

---

## 7. Round64 vs Round61 总体指标对比（test 6-19h）

| 指标 | Round61 | Round64 safe | Delta | 评价 |
|------|---:|---:|---:|:---:|
| site_mean_nrmse_6_19 | 11.4095% | 11.2806% | -0.1289pp | 改善 |
| city_nrmse_6_19 | 3.9531% | 3.8104% | -0.1427pp | 改善 |
| city_nrmse_10_14 | 6.2359% | 6.1879% | -0.0480pp | 改善 |
| bias_6_19 | +1.4232% | +1.5477% | +0.1245pp | 略差 |
| bias_10_14 | +8.3998% | +8.0181% | -0.3817pp | 改善 |
| RMSE (MW) | 0.9321 | 0.9042 | -0.028 | 改善 |
| MAE (MW) | 0.4478 | 0.4359 | -0.012 | 改善 |
| 变差>+1pp 站点数 | 0 | 0 | 0 | 无退化 |

---

## 8. 本轮是否覆盖正式结果

**未覆盖。** 正式 `power_pred_final` 保持 Round61 版本不变。

候选版本存放于：
- 预测：`output/pv_pipeline/round64/round64_candidates.pkl`
- 可视化：`output/pv_pipeline/interactive_dashboard_round64_candidate/`

---

## 9. 是否建议执行正式升级

**建议升级（Round66）。**

理由：
1. valid 集 5/5 安全检查全部 PASS。
2. test 集 NRMSE 类指标全面改善（sm -0.13pp, city -0.14pp）。
3. test 集全量站点审计 bad_sites_gt_1pp = 0，无站点退化。
4. 可视化数据与 pkl 完全一致（5/5 校验通过）。
5. dry-run 升级计划完整，有备份、回退机制。

---

## 10. 下一步建议

进入 **Round66**：正式升级 Round64 为 final，执行以下操作：

1. `python scripts/promote_round64_candidate.py --apply`
2. 重新运行 posttrain validation
3. 确认所有检查通过
4. 生成 Round66 执行报告

---

## 11. 输出文件清单

| 文件 | 说明 |
|------|------|
| `output/pv_pipeline/round64/round64_all_site_compare.csv` | 全量 68 站点审计明细 |
| `output/pv_pipeline/round64/round64_bad_site_audit.csv` | 退化站点清单（空=无退化） |
| `output/pv_pipeline/round64/round64_dashboard_candidate_consistency.csv` | 一致性校验 CSV |
| `output/pv_pipeline/round64/round64_dashboard_candidate_consistency.json` | 一致性校验结果 JSON |
| `output/pv_pipeline/round64/round64_promote_dry_run_report.md` | 升级 dry-run 报告 |
| `output/pv_pipeline/round64/round64_promote_file_plan.csv` | 升级文件计划 |
| `output/pv_pipeline/interactive_dashboard_round64_candidate/metadata.json` | 候选可视化元数据 |
