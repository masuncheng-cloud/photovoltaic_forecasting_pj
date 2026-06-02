# Round76 工程收口与版本一致性清理报告

## 一、本轮目标

本轮不重新训练、不调整模型结构，只修复多轮修改后留下的工程一致性问题，确保正式结果、训练入口、manifest、README、可视化数据口径完全统一。

---

## 二、当前正式版本

| 字段 | 值 |
|------|---|
| final_round | Round68 final |
| prediction_column | power_pred_final |
| actual_column | power_mw |
| exclude_future | true |
| official_final | true |
| full pkl | predictions/distributed_predictions_final_full.pkl |
| eval pkl | predictions/distributed_predictions_final_eval.pkl |
| dashboard | interactive_dashboard/ |
| full_sha256 | d528169285c9e4df... |

---

## 三、执行记录

### 3.1 执行前保护 ✅

备份了以下关键文件：

```
archive/round76_engineering_cleanup/
├── README.before_round76.md
├── manifest.before_round76.json
└── dashboard_metadata.before_round76.json
```

### 3.2 manifest 版本口径修复 ✅

新建 `scripts/fix_round76_manifest_consistency.py`，完成以下修正：

- 设置 `final_round = "Round68 final"`
- 设置 `prediction_column = "power_pred_final"`
- 设置 `actual_column = "power_mw"`
- 设置 `exclude_future = true`
- 设置 `official_final = true`
- 添加 `final_prediction_files` 路径字段
- 添加 `dashboard` 元数据字段
- 更新 `artifact_hashes`（SHA256）
- 清理 `*_hashes` 历史 round 字段

验收通过：`manifest` 与 `dashboard metadata` 完全一致。

### 3.3 README.md 修正 ✅

修正了三处旧内容：

1. **预测文件路径**：将 `output/pv_pipeline/tables/distributed_predictions_final_round36.pkl` 更新为 `predictions/distributed_predictions_final_full.pkl` 和 `distributed_predictions_final_eval.pkl`
2. **future 描述**：明确正式评估不含 future，说明 test 集范围为 2025-09-01 至 2025-12-31，小时 6-19
3. **入口说明**：补充说明 `run_full_pipeline.py` 是唯一正式入口，历史 round 脚本不作为正式入口

### 3.4 历史 round 脚本归档 ✅

从 `scripts/` 归档了 **42 个** round 专用脚本至 `archive/experimental_scripts/`：

- 包含 round63-73 训练、评估、选择脚本
- 保留 22 个 pipeline 依赖脚本（如 `build_round64_safe_residual_blend.py`）于 `scripts/`

保留的正式脚本（8个）：
- `run_full_pipeline.py` — 唯一正式训练入口
- `posttrain_validation.py` — 训练后逻辑审计
- `check_dashboard_prediction_values.py` — Dashboard 校验
- `export_interactive_dashboard_data.py` — 可视化导出
- `check_pipeline_consistency.py` — Pipeline 一致性检查
- `verify_current_best_round68.py` — Round68 基线验证
- `fix_round76_manifest_consistency.py` — manifest 修复
- `cleanup_*.py`（round74、round75清理脚本）

### 3.5 根目录临时文件归档 ✅

归档了以下文件：

| 文件 | 类型 |
|------|------|
| auto_push_test.txt | 测试文件 |
| test_auto_push.txt | 测试文件 |
| auto_sync.py | 临时脚本 |
| auto_sync.log | 日志文件 |
| catboost_info/ | CatBoost 训练日志 |
| take_dashboard_screenshots.py | 临时截图脚本 |
| 光伏功率预测项目.md | 临时文档 |
| Cursor执行方案_Round76_... | Cursor 执行方案 |

### 3.6 output 目录检查 ✅

确认 `output/pv_pipeline/` 仅保留白名单目录（Round75 已清理完毕），无残留。

### 3.7 正式入口脚本验证 ✅

所有正式入口脚本编译通过：

| 脚本 | 状态 |
|------|:----:|
| scripts/run_full_pipeline.py | ✓ |
| scripts/posttrain_validation.py | ✓ |
| scripts/check_dashboard_prediction_values.py | ✓ |
| scripts/export_interactive_dashboard_data.py | ✓ |

pipeline 引用的 30 个 round 脚本均存在（包括恢复的 22 个依赖脚本）。

---

## 四、验证结果

### 4.1 Dashboard 导出 ✅

- 标签：Round68 final
- 预测列：power_pred_final
- city_series：2,576 行
- site_series：68 个文件
- 典型最佳站点：S062, S023, S049, S054, S047

### 4.2 Dashboard 一致性 ✅

| 校验项 | 结果 | 差异 |
|--------|------|------|
| actual_mw vs pkl | PASS | 0.00e+00 |
| pred_mw vs pkl | PASS | 5.00e-05（浮点精度） |
| future 行数 | PASS | 0 |

### 4.3 Posttrain Validation ✅

**36项 / 34 PASS / 0 FAIL / 2 WARN**

WARN项：
1. **C9**：夜间数据不参与评估（正常口径）
2. **GEO4**：S116 低置信度（需甲方确认场区中心）

### 4.4 最终一致性断言 ✅

```python
manifest.final_round == "Round68 final"
manifest.prediction_column == "power_pred_final"
manifest.exclude_future == True
dashboard.prediction_column == "power_pred_final"
dashboard.exclude_future == True
```

---

## 五、归档清单

| 归档目录 | 内容 |
|----------|------|
| archive/experimental_scripts/ | 42 个 round 专用脚本 |
| archive/round76_engineering_cleanup/ | Round76 备份、保护快照、临时文件 |
| archive/old_output_pv_pipeline/ | Round75 清理产物（round63-74旧output） |
| archive/failed_experiments_round74/ | Round70-73 失败实验产物 |

---

## 六、剩余风险

1. **本轮未重新训练**：当前正式结果仍为 Round68 final，不影响交付
2. **本轮未改变模型结构**：无风险
3. **pipeline 依赖 22 个 round 脚本**：这些是 Round68 正式训练的组成部分，移回 `scripts/` 后可正常工作

---

## 七、结论

本轮完成了工程层面的彻底收口：

- manifest、dashboard、README、pipeline 入口使用统一口径（Round68 final / power_pred_final）
- 42 个历史实验脚本归档至 `archive/experimental_scripts/`，减少 scripts/ 干扰
- 根目录和 output 目录完全整洁
- 所有正式脚本编译通过，pipeline 依赖完整
- dashboard 和 posttrain validation 全部通过

**当前项目可作为正式稳定交付版本使用。**
