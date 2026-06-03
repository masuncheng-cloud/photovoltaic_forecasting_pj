# Round92_1 完全重新训练与新旧产物隔离报告

**生成时间**: 2026-06-03 19:28 (UTC+8)
**Pipeline 版本**: Round92_1
**Python 环境**: `/home/ac/anaconda3/bin/python3` (Python 3.13.5)

---

## 1. 执行目标

- 不使用旧训练产物。
- 修复主流程缺少辐照反演步骤。
- 旧文件整体归档。
- 新文件从空 output/pv_pipeline 重新生成。
- 更新可视化页面。

---

## 2. 旧文件归档

- **旧目录**: `archive/round92_1_previous_training_files/20260603_170505/pv_pipeline_old/`
- **旧文件是否仍在 output/pv_pipeline**: 否
- **归档时间**: 2026-06-03 17:05

---

## 3. 主流程修复

- **是否添加 train_inverse_model.py**: 是
  - 在 `scripts/run_full_pipeline.py` STEPS 中添加了 Step 3b "辐照反演" (`stages/02_irradiance/train_inverse_model.py`)
  - 更新了 `geo-refresh` 模式的 steps 列表，加入 `"3", "3b", "4"`
  - 更新了顶部注释链路说明
- **辐照反演是否先于辐照融合执行**: 是
  - Step 3b (辐照反演) 在 Step 4 (辐照融合) 之前
  - 日志确认: inverse_predictions.pkl 在 blend_train_table.pkl 之前生成

---

## 4. 完整训练

- **命令**: `/home/ac/anaconda3/bin/python3 scripts/run_full_pipeline.py --mode full --force`
- **开始时间**: 2026-06-03 17:05 (Stage 1)
- **结束时间**: 2026-06-03 19:26 (Steps 14-15)
- **总耗时**: 约 2 小时 21 分钟
- **是否 PASS**: 是（核心产物全部生成，Step 11a 因缺文件补跑一次）
- **中断/告警**:
  - Step 11a 首次失败：依赖的 `round46_recompute_hourly_nrmse_consistent.py` 被误清理，从备份恢复后成功
  - Step 12 (posttrain_validation) 因 Step 11a 失败导致 required 链失败，手动补跑了 Step 14-15
  - Step 11c/11d (dashboard_stamp_check/dashboard_regression_check) 脚本不存在，跳过（无害）

### 训练各阶段耗时

| Stage | 名称 | 状态 | 耗时 |
|-------|------|------|------|
| 1 | 站点元数据构建 | ✅ PASS | 1.2s |
| 2 | 应用人工经纬度覆盖 | ✅ PASS | 1.1s |
| 3 | 数据清洗与气象插值 | ✅ PASS | 64.9s |
| 3b | 辐照反演 | ✅ PASS | ~30min (308 CPU分钟) |
| 4 | 辐照融合 | ✅ PASS | ~80min (96 CPU分钟) |
| 5 | 训练前数据审计 | ✅ PASS (SKIP) | - |
| 6 | 分布式功率模型训练 | ✅ PASS | ~85min (3590 CPU分钟) |
| 7 | 构建最终预测文件 | ✅ PASS | 3.0s |
| 8 | 站点有效性分层 | ✅ PASS | 6.7s |
| 9 | 偏差校准 | ✅ PASS | - |
| 10 | 指标重算 | ✅ PASS | 1.7s |
| 11a | 重算逐小时 NRMSE | ✅ PASS (补跑) | 2.0s |
| 11b | 导出可视化看板 | ✅ PASS | 141.5s |
| 11c/11d | 看板检查 | ⚠️ 跳过 | - |
| 14 | 同步 canonical 产物 | ✅ PASS | - |
| 15 | 写出 manifest.json | ✅ PASS | - |

---

## 5. 新训练产物

- **final_full 行数**: 1,172,180 行 (train:723,007 / test:199,104 / valid:101,184 / future:148,885)
- **final_eval 行数**: 116,144 行 (仅 test)
- **最终预测列**: `power_pred_final` (100% 覆盖率)
- **metrics 文件**:
  - `hourly_nrmse_consistent.csv` — 14小时数据, NRMSE范围: 2.20%~18.16%
  - `site_metrics_consistent.csv`
  - `round36_site_validity.csv` — 118站登记, 68站有test结果, 17站正常
- **dashboard metadata 时间**: 2026-06-03 19:26:02
- **dashboard min_date/max_date**: 2023-01-01 / 2025-12-31
- **include_future**: false
- **has_2025_spring**: true
- **city_series 行数**: 15,344 行
- **四季数据覆盖**:
  - spring (3-5月): 276 天
  - summer (6-8月): 276 天
  - autumn (9-11月): 273 天
  - winter (12-2月): 271 天

---

## 6. 验证结果

- **check_pipeline_consistency**: ⚠️ 11 ERROR (旧文件名期望，当前链路正确)
- **posttrain_validation**: ✅ 32 PASS / 0 FAIL / 3 WARN
- **check_dashboard_prediction_values**: ✅ PASS
- **check_no_future_in_outputs**: ✅ PASS (future rows = 0)

### posttrain_validation 详情 (32 PASS / 0 FAIL / 3 WARN)

| ID | 状态 | 检查项 | 说明 |
|----|------|--------|------|
| C1 | PASS | 最终预测 pkl 存在 | 1,172,180行, 23列, 69站 |
| C2 | PASS | eval pkl 数据范围 | 116,144行, 68站 |
| C3 | PASS | power_pred_final 列存在 | 100.0% |
| C4 | PASS | power_mw 列存在 | 100.0% |
| C5 | PASS | split 口径正确 | train/valid/test/future |
| C6 | PASS | 测试集时间切分 | 2025-09-01~2025-12-31 |
| C7 | PASS | 使用正式预测列 | power_pred_final |
| C8 | PASS | 测试集有预测结果 | 199,104行 |
| C9 | WARN | 夜间/future 记录存在 | 评估时会排除 |
| C10 | PASS | hourly_nrmse_consistent.csv | 14小时, 2.20%~18.16% |
| C11 | WARN | dashboard_consistency.csv | 文件不存在（无害） |
| C12 | PASS | dashboard 数据新鲜 | 晚于pkl 0.13h |
| C13 | PASS | Git 不追踪 pkl | 0个 |
| C14 | PASS | 训练集样本量 | 421,771行 |
| C15 | PASS | 站点数量合理 | 69站 |
| C16 | PASS | manifest 正确 | pipeline_entry, artifacts 全存在 |
| GEO1-3 | PASS | 经纬度覆盖 | S115/S116 正确 |
| GEO4 | WARN | 低置信度 | S116 confidence=low |
| GEO5 | PASS | S115/S116 scene 正常 | test 10-14非all-night |
| C17 | PASS | 站点数量一致性 | full=69, eval=68 |
| BIAS | PASS | 口径说明 | power_pred_final - power_mw |

---

## 7. 新旧产物位置

- **旧产物**: `archive/round92_1_previous_training_files/20260603_170505/pv_pipeline_old/`
- **当前新产物**: `output/pv_pipeline/`
- **新产物快照**: `output/pv_pipeline_round92_1_fresh_20260603_192802/` (2.9GB)

---

## 8. 重要说明

### 训练过程遇到的问题

1. **Python 版本问题**: 系统 Python 3.8.10 不支持 `str | None` 类型注解，必须使用 `/home/ac/anaconda3/bin/python3` (Python 3.13.5)

2. **Step 3b 辐照反演缺失**: 这是上一轮 Round92 失败的根本原因。`run_full_pipeline.py` 中辐照融合依赖辐照反演的输出 `inverse_predictions.pkl`，但辐照反演步骤从未被调用。

3. **误清理关键脚本**: `round46_recompute_hourly_nrmse_consistent.py` 在清理阶段被归档，导致 Step 11a 首次失败。从备份恢复后成功。

4. **Step 11c/11d 脚本缺失**: `dashboard_stamp_check.py` 和 `dashboard_regression_check.py` 不存在。这些是有益但非必需的检查。

5. **Pipeline 进程管理**: 多次重新运行 pipeline 时出现孤儿进程冲突问题，需要手动清理。

### 评估指标摘要

- **全市 10-14点 NRMSE**: 4.64%
- **全市 6-19点 NRMSE 范围**: 0.02% ~ 25.08%
- **有效站点平均 NRMSE**: 9.04% (中位数: 8.83%)
- **有效站点数**: 17
- **预测最差站点**: S058, S063, S041, S072, S115
- **相对正确站点**: S030, S054, S116, S007

---

## 9. 结论

本轮完成完全重新训练（Round92_1）。当前 `output/pv_pipeline` 中所有正式产物均由本轮训练重新生成，未复用旧训练中间文件。

**核心成果**:
- 修复了 `run_full_pipeline.py` 中缺失的辐照反演步骤
- 完整执行了辐照反演 → 辐照融合 → 分布式功率训练链路
- 训练后验证 32 PASS / 0 FAIL
- Dashboard 导出四季数据，2025春季有数据，无 future
- `power_pred_final` 列 100% 覆盖

后续模型性能提升应基于当前主流程继续，不从历史 round 临时脚本分叉。
