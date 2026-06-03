# Round93 从 GitHub 恢复最优训练代码并修复主流程报告

## 1. 恢复原因

Round92_1 完整重训后，站点级和整体指标较原版本变差，因此恢复原最优训练代码与原最优输出。

| 指标 | 原最优 | Round92_1 | 当前恢复后 |
|---:|---:|---:|---:|
| 6-19站点平均NRMSE均值 | 9.77% | 10.00% | **9.77%** |
| 10-14站点平均NRMSE均值 | 15.72% | 16.86% | **15.72%** |
| 6-19城市NRMSE均值 | ~3.95% | 4.17% | **~3.95%** |
| 10-14城市NRMSE均值 | ~6.24% | 6.12% | **~6.24%** |
| 站点NRMSE均值 | 11.41% | 12.14% | **11.41%** |
| 最大站点NRMSE | 30.43% | 31.71% | **30.43%** |

结论：Round92_1 变差，当前已恢复到原最优基线。

## 2. 恢复来源

- GitHub 仓库：git@github.com:masuncheng-cloud/photovoltaic_forecasting_pj.git
- 分支：main（本地）
- 恢复方式：从 `archive/round92_before_full_retrain/output_pv_pipeline_before_full_retrain` 恢复 output/pv_pipeline
- 代码修复：直接在本地应用工程修复，不引入 Round92_1 模型

## 3. 保留的工程修复

### 3.1 辐照反演步骤（Step 3b）
- `scripts/run_full_pipeline.py` STEPS 中已包含 `id="3b"`, `script="stages/02_irradiance/train_inverse_model.py"`
- geo-refresh 模式步骤列表已包含 `"3b"`

### 3.2 manifest.json 写出顺序
- **修复前**：posttrain_validation.py (step 12) 在 manifest 写出 (step 15) 之前执行，导致 audit-only 模式报错
- **修复后**：`run_full_pipeline.py` 重构为三阶段执行：
  - Phase 1：执行 step 1~11，step 12 ("posttrain_validation") 时停止
  - Phase 2：同步 canonical 产物 + **先写出 manifest.json**
  - Phase 3：执行 step 12 (posttrain_validation) 和 step 13 (dashboard 校验)

### 3.3 清理脚本递归归档保护
- `scripts/cleanup_round92_redundant_artifacts.py` 新增 `is_under_archive()` 函数
- `move_to_archive()` 在移动前检查路径是否在 `ROOT/archive/` 内，是则跳过
- 防止清理脚本将 archive/ 内部文件再次归档

### 3.4 Dashboard 导出非 future 全历史
- `scripts/export_interactive_dashboard_data.py` 已在 `build_full_history_frame()` 中排除 `split == future`
- 导出 scope = `non_future_full_history`
- 写出 `full_history_coverage_check.json`，验证 2023-2025 全历史覆盖

## 4. 验证结果

### 4.1 指标验证

| 指标 | 当前值 | 状态 |
|---:|---:|:---:|
| 6-19站点平均NRMSE | 9.7722% | 与原最优一致 |
| 10-14站点平均NRMSE | 15.7229% | 与原最优一致 |
| 站点NRMSE均值 | 11.4095% | 与原最优一致 |
| 最大站点NRMSE | 30.4253% | 与原最优一致 |

### 4.2 posttrain_validation 验证

- **34 PASS / 0 FAIL / 2 WARN**
- C16 manifest hash 验证：PASS（2 个文件 hash 一致）
- C11 dashboard 一致性校验：68 站全部 PASS
- GEO5 S115/S116 链路正常

### 4.3 Dashboard 数据验证

- `include_future`: false
- `data_scope`: train/valid/test only; future excluded
- `date_range`: 2023-01-01 ~ 2025-12-31
- 全历史覆盖检查：PASS（15344 行）
- 2025 四季数据：spring/summer/autumn/winter 全部有数据

## 5. GitHub 提交

- Commit: `bb1587f` Round93: restore original best baseline
- Tag: `round93-restore-best-baseline`
- 已通过 post-commit hook 自动推送到 origin/main

## 6. 备份

- 备份目录：`archive/round93_before_github_restore_20260603_214037`
- 包含：scripts_current, stages_current, configs_current, output_pv_pipeline_current, README.current.md, git_status_before_restore.txt

## 7. 结论

当前版本恢复到原来更优的训练结果，同时保留并新增了必要工程修复。后续模型优化必须以当前恢复版本为基线（6-19站点NRMSE 9.77%），任何新结果若整体指标差于基线，应自动回退。
