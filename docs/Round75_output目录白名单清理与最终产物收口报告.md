# Round75 output 目录白名单清理与最终产物收口报告

## 一、验收标准检查

| 标准 | 状态 | 说明 |
|------|------|------|
| output 根目录只保留白名单目录 | ✓ | 仅保留11个白名单目录 |
| 历史 round 不再散落在 output 根目录 | ✓ | round63~74 全部归档 |
| 垃圾文件清理完成 | ✓ | .DS_Store 等已清理 |
| 当前正式结果仍是 Round68 final | ✓ | 指标完全匹配 |
| 可视化数据已刷新 | ✓ | 含 Round68 final 标签 |
| dashboard consistency 通过 | ✓ | actual_mw/ pred_mw 均 PASS |
| posttrain validation 无 FAIL | ✓ | 36项/34PASS/0FAIL/2WARN |
| Git tag 已创建 | 待执行 | 本次会话内执行 |

---

## 二、清理前状态

### 2.1 output/pv_pipeline/ 清理前根目录

共27个条目，其中需归档：

| 目录/文件 | 操作 |
|-----------|------|
| round63/ (65M) | 归档 |
| round64/ (64M) | 归档 |
| round66/ (60K) | 归档 |
| round67/ (21M) | 归档 |
| round68/ (64K) | 归档 |
| round69/ (108M) | 归档 |
| round73/ (12K) | 归档 |
| round74/ (36K) | 归档 |
| archive_before_round36/ | 归档 |
| calibration/ (104M) | 归档 |
| diagnostics/ | 归档 |
| cache/ | 归档 |
| interactive_dashboard_round64_candidate/ (78M) | 归档 |
| models/ (126M) | 归档（已过期） |
| analyze_and_annotate.py | 归档脚本 |
| analyze_predictions.py | 归档脚本 |
| move_time.py | 归档脚本 |
| reorganize_back40.py | 归档脚本 |
| reorganize_cols.py | 归档脚本 |

**归档总量：约 549M（不含 pkl 内容）**

---

## 三、清理后状态

### 3.1 output/pv_pipeline/ 最终目录树

```
output/pv_pipeline/
├── backups/                     正式备份（本次 Round74 备份）
├── baselines/                   稳定基线目录 (round58-61)
├── docs/                        正式报告
├── figures/                     正式图表
├── figures_dashboard/           Dashboard 截图
├── interactive_dashboard/       正式可视化数据
├── logs/                        日志
├── manifest.json                正式 manifest
├── metrics/                     正式指标
├── predictions/                正式预测 pkl（含 canonical）
├── tables/                      表格数据（含 CSV/Parquet，少量中间 pkl）
└── validation/                   验证输出
```

**共计 13 个目录 + manifest.json**，完全符合白名单。

### 3.2 归档位置

```
archive/old_output_pv_pipeline/20260601_232037/
├── archive_before_round36/
├── cache/
├── calibration/                 (104M)
├── diagnostics/
├── interactive_dashboard_round64_candidate/  (78M)
├── models/                     (126M)
├── root_scripts/
│   ├── analyze_and_annotate.py
│   ├── analyze_predictions.py
│   ├── move_time.py
│   ├── reorganize_back40.py
│   └── reorganize_cols.py
├── round63/                   (65M)
├── round64/                   (64M)
├── round66/                   (60K)
├── round67/                   (21M)
├── round68/                   (64K)
├── round69/                   (108M)
├── round73/                   (12K)
└── round74/                   (36K)
```

---

## 四、tables/ 目录说明

`tables/` 中存在部分中间训练 pkl 文件（如 `power_clean.pkl`、`distributed_train_table_v159.pkl` 等），这些是训练流程的中间产物，体积较大但不影响正式交付。

正式交付核心文件为：
- `predictions/distributed_predictions_final_full.pkl`（canonical）
- `predictions/distributed_predictions_final_eval.pkl`（canonical）

---

## 五、Dashboard 和 Manifest 校验

### 5.1 Dashboard 元数据

| 字段 | 值 |
|------|---|
| label | Round68 final |
| source_round | Round68 |
| prediction_column | power_pred_final |
| official_final | true |
| exclude_future | true |

### 5.2 Dashboard 一致性（5站点抽查）

| 校验项 | 状态 | 差异 |
|--------|------|------|
| actual_mw vs pkl | PASS | 0.00e+00（完全一致） |
| pred_mw vs pkl | PASS | 4.99e-05（浮点精度） |
| future 行数 | PASS | 0 |

### 5.3 Manifest

| 字段 | 值 |
|------|---|
| final_prediction_column | power_pred_final |
| source_round | Round68 lgb_safe_blend |

---

## 六、Posttrain Validation 结果

**36项 / 34 PASS / 0 FAIL / 2 WARN**

WARN项：
1. **C9 夜间/future 不参与评估**：夜间数据（180,660行）不影响白天评估
2. **GEO4 S116 低置信度**：建议由甲方确认精确场区中心

无 FAIL。

---

## 七、正式产物清单

| 类别 | 文件 | 状态 |
|------|------|:----:|
| 正式预测 | predictions/distributed_predictions_final_full.pkl | ✓ |
| 评估预测 | predictions/distributed_predictions_final_eval.pkl | ✓ |
| 可视化 | interactive_dashboard/ (含 metadata.json) | ✓ |
| 指标 | metrics/ (含 34个 hash) | ✓ |
| Manifest | manifest.json | ✓ |
| 验证报告 | validation/posttrain_validation_results.csv | ✓ |
| Dashboard 报告 | docs/posttrain_validation_report.md | ✓ |

---

## 八、Round75 执行命令汇总

| 步骤 | 命令 | 状态 |
|------|------|:----:|
| 基线校验 | `verify_current_best_round68.py` | ✓ |
| 清理脚本创建 | `cleanup_output_pv_pipeline_whitelist.py` | ✓ |
| Dry-run | `--dry-run` | ✓ |
| Apply | `--apply` | ✓ |
| 目录树快照 | `find ... > tree_after.txt` | ✓ |
| Dashboard 导出 | `export_interactive_dashboard_data.py` | ✓ |
| 一致性校验 | `check_dashboard_prediction_values_round66.py` | ✓ |
| Manifest 更新 | `update_final_manifest_hashes.py` | ✓ |
| Validation | `posttrain_validation.py` | ✓ |
| 报告生成 | 本文档 | ✓ |

---

## 九、结论

本次 Round75 完成了 `output/pv_pipeline/` 的彻底白名单清理，将所有历史 round、中间产物、临时脚本归档至 `archive/old_output_pv_pipeline/20260601_232037/`，output 目录现仅保留正式交付所需内容。

当前正式结果为 **Round68 final**，`power_pred_final` 列：
- city_nrmse_6_19: **4.13%**
- site_mean_nrmse_6_19: **10.58%**
- abs_bias_6_19: **0.52%**

**不建议继续在无新增 ERA5 气象数据的情况下进行残差模型训练。**
