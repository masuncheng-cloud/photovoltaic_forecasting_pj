# Round50 工程收口与训练逻辑审计执行报告

**执行时间**：2026-05-31 11:54 ~ 12:07 (UTC+8)
**执行人**：Cursor AI
**状态**：✅ 全部完成

---

## 1. 本轮修改内容

### 1.1 新建文件

| 文件 | 说明 |
|------|------|
| `configs/pipeline.yaml` | 统一配置：split 日期、评估口径、预测列名、数据质量门槛 |
| `scripts/common_paths.py` | 公共路径工具：统一加载配置、路径计算 |
| `scripts/metrics_common.py` | 统一指标口径：mae/rmse/nrmse_percent/bias_percent/pred_actual_ratio |
| `scripts/run_full_pipeline.py` | 唯一正式训练入口（9 步流水线） |
| `scripts/posttrain_validation.py` | 训练后逻辑审计（Round50+ 通用版，17 项检查） |
| `scripts/check_dashboard_prediction_values.py` | Dashboard 校验（Round50+ 通用版） |
| `scripts/archive_legacy_round_files.py` | 归档历史文件（dry-run + apply 模式） |

### 1.2 修改文件

| 文件 | 说明 |
|------|------|
| `README.md` | 清理过时入口，保留正式训练方式 |

### 1.3 归档文件

共归档 76 个文件：

| 归档目录 | 文件数 | 内容 |
|---------|--------|------|
| `archive/round_scripts/` | 27 | roundXX 临时脚本、v2/v3 脚本 |
| `archive/old_outputs/tables/` | 2 | `*_before_*.pkl` 旧版本 pkl |
| `archive/old_outputs/metrics/` | 32 | round34/35/40/41_42/44/45 历史指标 CSV |
| `archive/old_outputs/docs/` | 3 | Round44/45/46 执行总结 |
| `archive/old_outputs/archive_before_round36/` | 12 | archive_before_round36 内容 |

**受保护文件（未归档）**：
- `distributed_predictions_final_round36.pkl`（当前活跃预测结果）
- `round46_hourly_nrmse_consistent.csv`（当前指标）
- `round48_station_data_requirement_analysis.csv`（当前分析数据）
- `Round48/49/50` 执行文档
- `run_full_pipeline.py`、`posttrain_validation.py` 等正式脚本

---

## 2. 正式训练入口

### 完整训练（唯一入口）

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
python scripts/run_full_pipeline.py
```

**训练链路（9 步）**：

```
[1/9] 训练前数据审计         → pretrain_audit_round36.py
[2/9] 分布式功率模型训练      → stages/03_power/train_distributed_model_v159.py
[3/9] 构建最终预测文件       → build_round36_predictions.py
[4/9] 站点有效性分层        → build_site_validity_round36.py
[5/9] 偏差校准             → apply_round36_calibration.py
[6/9] 指标重算             → compute_round36_metrics.py
[7/9] 训练后统一收口        → post_training_finalize_outputs.py
[8/9] 训练后逻辑审计        → scripts/posttrain_validation.py
[9/9] Dashboard 预测值校验   → scripts/check_dashboard_prediction_values.py
```

### 启动可视化看板

```bash
python -m http.server 8060
# 访问 http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

---

## 3. 最终产物清单

| 产物 | 路径 |
|------|------|
| 最终预测（完整） | `output/pv_pipeline/tables/distributed_predictions_final_round36.pkl` |
| 最终预测（评估用） | `output/pv_pipeline/tables/distributed_predictions_final_eval_round36.pkl` |
| 逐小时站点 NRMSE | `output/pv_pipeline/metrics/round46_hourly_nrmse_consistent.csv` |
| 站点级指标 | `output/pv_pipeline/metrics/round36_site_metrics.csv` |
| Dashboard 数据 | `output/pv_pipeline/interactive_dashboard/` |
| 训练后审计报告 | `output/pv_pipeline/docs/posttrain_validation_report.md` |
| Dashboard 校验报告 | `output/pv_pipeline/docs/Dashboard预测值一致性检查报告.md` |

---

## 4. 指标口径

| 指标 | 公式 | 单位 |
|------|------|------|
| 站点 NRMSE | RMSE / capacity_mw × 100 | % |
| 城市 NRMSE | RMSE / sum(capacity_mw) × 100 | % |
| MAE | mean(|pred - actual|) | MW |
| RMSE | sqrt(mean((pred - actual)²)) | MW |
| BIAS | (sum(pred) - sum(actual)) / sum(actual) × 100 | % |
| pred/actual | sum(pred) / sum(actual) | 比值 |

**评估口径**：test 集，小时 6-19，不含 future

**主要指标**：NRMSE、MAE、RMSE、BIAS、pred/actual
**辅助指标**（仅诊断用）：MAPE、WAPE

---

## 5. 可视化数据自动更新机制

训练后自动执行（`post_training_finalize_outputs.py`）：
1. 重新计算逐小时 consistent NRMSE 指标
2. 重新导出可视化 dashboard JSON
3. 更新 dashboard_update_stamp.json
4. 执行 dashboard 回归检查

`check_dashboard_auto_update_stamp.py` 验证：dashboard JSON 修改时间 ≥ final pkl 修改时间。

---

## 6. 清理归档情况

- 76 个历史文件已移动到 `archive/`
- 主流程不依赖 `archive/` 内任何文件
- README 不再引用 roundXX 临时脚本

---

## 7. 训练后验证结果

### 7.1 `posttrain_validation.py`（17 项检查）

| 状态 | 数量 |
|------|------|
| PASS | 15 |
| FAIL | 0 |
| WARN | 2 |

**WARN 说明**：
- C9：pkl 中存在夜间和 future 记录（设计如此，评估时会正确排除）
- C16：manifest.json 尚未写出（需在完整训练流程结束后写入）

### 7.2 `check_dashboard_prediction_values.py`（68 站点全量校验）

| 指标 | 值 |
|------|-----|
| PASS | 68/68 |
| FAIL | 0 |
| 最大 pred 误差 | 0.00e+00（容差 1e-9） |
| 最大 actual 误差 | 0.00e+00 |

---

## 8. 当前仍需注意的问题

1. **辐照估计缺少独立实测验证**：clear_sky_ghi 是理论晴空辐照，不代表实际气象匹配质量
2. **部分站点存在容量映射、异常 0 值、遮挡/限电或数据漂移风险**：Round48 分析已识别 S019/S053/S115 等异常站点
3. **站点平均 NRMSE 与城市 NRMSE 表示不同层面的误差**，不能互相替代
4. **数据量不是唯一决定因素**：有效正功率样本、站点质量、容量准确性和分布漂移共同影响精度
5. **manifest.json** 在完整训练流程结束后自动写入，当前未生成

---

## 9. 新建文件清单

```
configs/pipeline.yaml                        — 统一配置
scripts/common_paths.py                     — 公共路径工具
scripts/metrics_common.py                    — 统一指标口径
scripts/run_full_pipeline.py                — 唯一正式训练入口
scripts/posttrain_validation.py             — 训练后逻辑审计（Round50+）
scripts/check_dashboard_prediction_values.py  — Dashboard 预测值校验
scripts/archive_legacy_round_files.py        — 归档历史文件工具
```
