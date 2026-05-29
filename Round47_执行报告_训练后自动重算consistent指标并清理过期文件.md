# Round47 执行报告：训练后自动重算 consistent 指标并清理过期文件

**执行时间**：2026-05-29 23:30 ~ 23:50 (UTC+8)
**执行人**：Cursor AI
**状态**：✅ 全部完成

---

## 1. 目标回顾

本次 Round47 做项目流程收口，包含两件事：

1. **接入训练主流程**：把"重新训练后自动重新计算 consistent 指标"接入训练主流程，保证可视化页面始终读取最新训练结果
2. **清理过期文件**：清理项目中前面多轮修改留下的残留脚本、旧结果文件，避免后续误读旧产物

**不改变**：模型结构、最终预测列口径、NRMSE 定义

---

## 2. 修改内容

### 2.1 新建脚本

#### `scripts/post_training_finalize_outputs.py`（全新）

训练后统一收口脚本，作为每次训练完成后的唯一收口入口：

```
执行步骤（5步）：
  1. compute_hourly_nrmse_consistent.py — 重新计算逐小时 consistent NRMSE
  2. export_interactive_dashboard_data.py — 导出可视化 dashboard 数据
  3. update_dashboard_after_training.py — 检测 dashboard 是否刷新
  4. check_dashboard_auto_update_stamp.py — 验证 stamp 文件
  5. round44_dashboard_regression_check.py — dashboard 回归检查
```

特点：
- 自动检测脚本路径（优先用通用名，找不到则 fallback）
- pre-flight 检查 final pkl 是否存在
- 失败时立即停止，不静默跳过
- 输出 `post_training_finalize_stamp.json` 执行记录

#### `scripts/check_post_training_auto_finalize.py`（全新）

验证训练后自动收口链路是否完整（7 项检查）：

| # | 检查项 | 状态 |
|---|--------|------|
| 1 | `round46_hourly_nrmse_consistent.csv` 存在 | ✅ |
| 2 | `hourly_prediction_summary.json` 存在 | ✅ |
| 3 | `post_training_finalize_stamp.json` 存在 | ✅ |
| 4 | stamp 新鲜度（< 48h） | ✅ |
| 5 | 10-14 点 NRMSE 不是旧错误口径（< 25%） | ✅ |
| 6 | `metadata.json` 预测列为 `power_pred_final` | ✅ |
| 7 | JSON 行数为 14（6-19时） | ✅ |

#### `scripts/compute_hourly_nrmse_consistent.py`（全新 wrapper）

作为 `round46_recompute_hourly_nrmse_consistent.py` 的通用命名入口，避免项目长期依赖 Round 编号。

```python
# 实际调用 round46 版本（wrapper）
subprocess.run([sys.executable, "scripts/round46_recompute_hourly_nrmse_consistent.py"])
```

#### `scripts/audit_stale_round_artifacts.py`（全新）

审计脚本，扫描 scripts/、output/，识别过期文件：

- 分类：keep_core、keep_latest、archive_artifact、delete_cache、manual_review
- 输出 CSV + Markdown 清单

#### `scripts/archive_stale_round_artifacts.py`（全新）

安全归档脚本：
- 默认 dry-run，只打印操作
- `--apply` 才真正移动文件
- 写出 `archive_manifest.csv` manifest
- 写入归档目录 `README.md`

---

### 2.2 脚本修改

#### `scripts/run_round36_full_retrain.py`

训练主入口新增 Step 11，统一收口：

| 步骤 | 描述 | 状态 |
|------|------|------|
| 1-6 | 训练 + 预测 + 分层 + 校准 + 指标 | 原有 |
| 7-10 | 旧步骤（已被 Step 11 替代） | 保留但标记废弃 |
| **11** | **post_training_finalize_outputs.py** | **新增** |

#### `scripts/run_round44_training_logic_fix.py`

逻辑修正入口新增 Step 10，替代原 Step 4-9：

| 步骤 | 描述 | 状态 |
|------|------|------|
| 1-3 | 逻辑修正 + 指标 + 守门 | 原有 |
| 4-9 | 旧步骤（已被 Step 10 替代） | 保留但标记废弃 |
| **10** | **post_training_finalize_outputs.py** | **新增** |

#### `scripts/export_interactive_dashboard_data.py`

修复 CSV 路径检测逻辑：
- **修复前**：只查找 `round{rn}_city_hourly_nrmse.csv`（Round36 存在，Round46 不存在）
- **修复后**：自动扫描 `round*_hourly_nrmse_consistent.csv`，按 mtime 取最新
- **效果**：训练完成后总是使用最新 consistent NRMSE 数据，不再回退到旧口径

---

### 2.3 归档结果

77 个旧轮次脚本已移动到 `archive/round_artifacts_before_round47/scripts/`：

| 分类 | 数量 |
|------|------|
| 归档脚本 | 3 |
| dawn/dusk 修复实验 | 5 |
| midday 专精实验 | 7 |
| 早期偏差校准 | 1 |
| 早期版本验证/报告 | 7 |
| 旧对比和守门 | 4 |
| 旧预测构建 | 4 |
| 早期 MAE/MAPE 实验 | 4 |
| 旧典型站点分析 | 2 |
| 旧校准 | 2 |
| 其他已废弃 | 9 |
| 旧存档脚本 | 3 |
| 旧 delivery/守门/候选 | 8 |
| 旧入口脚本 | 3 |
| Round45 脚本（被 46/47 替代） | 4 |
| 重复文件名 | 2 |
| update_taskbook_compliance | 1 |
| generate_round36_training_log | 1（重复） |
| **合计** | **77** |

**未被归档的核心文件**（保持原位）：
- `round46_recompute_hourly_nrmse_consistent.py` — 核心 NRMSE 计算
- `round41_42_unified_daytime_and_site_calibration.py` — 训练逻辑修正
- `round45_site_hour_nrmse_diagnosis.py` — 诊断工具（Round47 也需要）
- `round45_guard_and_commit.py` — 守门工具
- `round45_apply_site_hour_shrinkage_calibration.py` — 校准工具

---

### 2.4 数据验收（10-14h 站点平均 NRMSE）

| 小时 | 实际值 | 方案预期值 | 差异 | 状态 |
|---:|---:|---:|---:|:---:|
| 10 | 13.786% | ~13.79% | 0.004 | ✅ |
| 11 | 15.298% | ~15.30% | 0.002 | ✅ |
| 12 | 16.145% | ~16.14% | 0.005 | ✅ |
| 13 | 15.864% | ~15.86% | 0.004 | ✅ |
| 14 | 13.818% | ~13.82% | 0.002 | ✅ |

---

## 3. 验证脚本结果

| 脚本 | 结果 |
|------|------|
| `post_training_finalize_outputs.py` | ✅ 5/5 步 OK |
| `check_post_training_auto_finalize.py` | ✅ 7/7 项 PASS |
| `check_dashboard_auto_update_stamp.py` | ✅ 7/7 项 PASS |
| `round44_dashboard_regression_check.py` | ✅ 27/27 项 PASS |
| **合计** | **46/46 全部通过** |

---

## 4. 推荐文件白名单（Round47 更新版）

### 必须保留的脚本

```text
# 核心训练和评估
scripts/train_distributed_model_v159.py
scripts/train_fixed.py
scripts/apply_round36_calibration.py
scripts/compute_round36_metrics.py
scripts/build_round36_predictions.py
scripts/build_site_validity_round36.py
scripts/pretrain_audit_round36.py
scripts/regenerate_project_report_round36.py
scripts/posttrain_validation_round36.py

# 训练逻辑修正（核心）
scripts/round41_42_unified_daytime_and_site_calibration.py
scripts/round41_42_guard.py
scripts/round40_compare_final_prediction_metrics.py

# 最终预测列选择
scripts/select_final_prediction_by_guard.py
scripts/select_final_prediction_v3.py

# 站点元数据
scripts/annotate_sites.py
scripts/generate_site_parameters.py
scripts/apply_site_metadata_overrides.py

# 核心可视化导出
scripts/export_interactive_dashboard_data.py
scripts/update_dashboard_after_training.py

# 统一收口链路（Round47 新增）
scripts/post_training_finalize_outputs.py
scripts/check_post_training_auto_finalize.py
scripts/compute_hourly_nrmse_consistent.py
scripts/round46_recompute_hourly_nrmse_consistent.py
scripts/check_dashboard_auto_update_stamp.py
scripts/round44_dashboard_regression_check.py

# 诊断工具
scripts/diagnose_hourly_bias.py
scripts/baseline_diagnostic.py
scripts/evaluate_dawn_dusk.py
scripts/check_pipeline_consistency.py
scripts/plot_map_visualization.py

# Round45 诊断/校准工具（保留）
scripts/round45_site_hour_nrmse_diagnosis.py
scripts/round45_guard_and_commit.py
scripts/round45_apply_site_hour_shrinkage_calibration.py

# 入口脚本
scripts/run_round36_full_retrain.py
scripts/run_round44_training_logic_fix.py

# 图表和截图
scripts/take_dashboard_screenshots.py
take_dashboard_screenshots.py
stages/05_visualization/interactive_forecast_dashboard.html
```

### 必须保留的输出

```text
output/pv_pipeline/metrics/round46_hourly_nrmse_consistent.csv
output/pv_pipeline/metrics/round46_site_hour_nrmse_consistent.csv
output/pv_pipeline/interactive_dashboard/
output/pv_pipeline/docs/post_training_finalize_stamp.json
output/pv_pipeline/docs/stale_artifacts_audit.csv
output/pv_pipeline/docs/stale_artifacts_audit.md
光伏功率预测项目.md
任务书-2026年国网江苏省电力有限公司面向生产一线的科技项目包（连云港公司）.doc
```

---

## 5. 后续使用方法

### 完整重训（包含统一收口）

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
python3 scripts/run_round36_full_retrain.py
# 训练成功后 Step 11 自动执行
```

### 仅逻辑修正（包含统一收口）

```bash
python3 scripts/run_round44_training_logic_fix.py
# Step 10 自动执行收口
```

### 独立执行收口

```bash
python3 scripts/post_training_finalize_outputs.py
python3 scripts/check_post_training_auto_finalize.py
```

### 查看归档清单

```bash
cat output/pv_pipeline/docs/stale_artifacts_audit.md
```

### 从归档恢复文件

```bash
cp archive/round_artifacts_before_round47/scripts/<file>.py scripts/
```

---

## 6. 修改文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `scripts/post_training_finalize_outputs.py` | 新建 | 训练后统一收口脚本 |
| `scripts/check_post_training_auto_finalize.py` | 新建 | 收口链路验证脚本 |
| `scripts/compute_hourly_nrmse_consistent.py` | 新建 | 通用命名 NRMSE 重算 wrapper |
| `scripts/audit_stale_round_artifacts.py` | 新建 | 过期文件审计脚本 |
| `scripts/archive_stale_round_artifacts.py` | 新建 | 安全归档脚本 |
| `scripts/run_round36_full_retrain.py` | 修改 | 新增 Step 11 统一收口 |
| `scripts/run_round44_training_logic_fix.py` | 修改 | 新增 Step 10 统一收口 |
| `scripts/export_interactive_dashboard_data.py` | 修复 | 优先读取 latest _consistent.csv |
| `archive/round_artifacts_before_round47/` | 新建 | 归档目录（77 个旧脚本） |
| `output/pv_pipeline/docs/stale_artifacts_audit.csv` | 新建 | 过期文件 CSV 清单 |
| `output/pv_pipeline/docs/stale_artifacts_audit.md` | 新建 | 过期文件 Markdown 清单 |
