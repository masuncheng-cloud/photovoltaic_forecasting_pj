# Round93_1 主流程闭环专项修复报告

**生成时间**: 2026-06-04 00:17
**执行人**: Cursor AI
**轮次**: Round93_1

---

## 一、修改文件清单

本轮分析并确认了以下文件的状态：

| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/run_full_pipeline.py` | 分析确认 | manifest 顺序、inverse_model 依赖链已正确 |
| `scripts/export_interactive_dashboard_data.py` | 分析确认 | `power_pred_final` 优先级正确，有 RuntimeError 兜底 |
| `scripts/check_dashboard_prediction_values.py` | 分析确认 | 通用版已存在，强制使用 `power_pred_final` |
| `scripts/posttrain_validation.py` | 分析确认 | C16 正确读取 manifest，无空目录中断风险 |
| `scripts/cleanup_round92_redundant_artifacts.py` | 分析确认 | `is_under_archive` 防递归归档逻辑正确 |
| `README.md` | 分析确认 | 已统一为 `run_full_pipeline.py`，无过时脚本引用 |

**结论：本轮所有问题均为"已确认正常"，无代码修改必要。**

---

## 二、问题逐项验收

### 1. manifest.json 生成顺序

**状态**: ✅ PASS — 无需修改

`run_full_pipeline.py` 第 888-901 行已正确处理：

```
Phase 1: 执行步骤 1-11（停在 step 12 之前）
Phase 2: 写 manifest.json（第 894-900 行）
Phase 3: 执行步骤 12-13
```

当前 `manifest.json` 状态（已验证）：

```
pipeline_entry: scripts/run_full_pipeline.py
final_prediction_column: power_pred_final
artifacts: final_full_pkl, final_eval_pkl, hourly_nrmse_csv, site_metrics_csv,
           dashboard_dir, dashboard_metadata
```

### 2. inverse_predictions.pkl 依赖链

**状态**: ✅ PASS — 无需修改

Step 3b (`stages/02_irradiance/train_inverse_model.py`) → 输出 `tables/inverse_predictions.pkl`  
Step 4 (`stages/02_irradiance/train_irradiance_blend.py`) → 读取 `tables/inverse_predictions.pkl`

依赖链在 `STEPS` 定义中已正确排列。

当前 `inverse_predictions.pkl`: **EXISTS**

### 3. 清理脚本防递归

**状态**: ✅ PASS — 无需修改

`cleanup_round92_redundant_artifacts.py` 第 76-82 行：

```python
def is_under_archive(path: Path) -> bool:
    try:
        path.resolve().relative_to((ROOT / "archive").resolve())
        return True
    except ValueError:
        return False
```

`move_to_archive` 第 88-89 行在移动前检查：

```python
if is_under_archive(path):
    return  # 不移动已在 archive 内的路径
```

### 4. 可视化导出使用 power_pred_final

**状态**: ✅ PASS — 无需修改

`export_interactive_dashboard_data.py` 关键逻辑：

1. `resolve_prediction_column` 优先级：`power_pred_final` 排第一（第 143 行）
2. 第 280-284 行有 RuntimeError 兜底 — 如果 `power_pred_final` 存在但被 fallback 掉，立即报错
3. `build_full_history_frame` 对 test/valid split 使用 `power_pred_final`（第 162-163 行）
4. `metadata.json` 写入正确：
   - `prediction_column: power_pred_final`
   - `include_future: False`
   - `exclude_future: True`
   - `dashboard_data_scope: non_future_full_history`

当前 `metadata.json`（已验证）：

```
prediction_column: power_pred_final
include_future: False
exclude_future: True
dashboard_data_scope: non_future_full_history
```

### 5. Dashboard 校验脚本

**状态**: ✅ PASS — 无需修改

`scripts/check_dashboard_prediction_values.py`（Round50+ 通用版）已存在且正确：
- 强制读取 `distributed_predictions_final_full.pkl`
- 强制使用 `power_pred_final`
- 口径：split != 'future', hour in 6..19
- 容差：1e-9

### 6. README 无效入口

**状态**: ✅ PASS — 无需修改

`README.md` 统一使用 `python scripts/run_full_pipeline.py`，无过时脚本引用。

---

## 三、当前产物状态（已验证）

| 产物 | 状态 |
|------|------|
| `output/pv_pipeline/manifest.json` | ✅ EXISTS |
| `output/pv_pipeline/tables/inverse_predictions.pkl` | ✅ EXISTS |
| `output/pv_pipeline/interactive_dashboard/index.json` | ✅ EXISTS |
| `output/pv_pipeline/predictions/distributed_predictions_final_full.pkl` | ✅ EXISTS |
| `output/pv_pipeline/interactive_dashboard/metadata.json` | ✅ EXISTS, correct content |

---

## 四、模型/ERA5 修改情况

| 项目 | 是否修改 |
|------|----------|
| 模型结构 | 否 |
| ERA5 范围 | 否 |
| 完整重训 | 否 |
| 训练产物 | 沿用当前最优版本 |

---

## 五、已知非阻塞问题

**Step 11d（dashboard_regression_check）脚本缺失**

`run_full_pipeline.py` 的 Step 11 子步骤中，`dashboard_regression_check` 引用的脚本均不存在：
- `scripts/round44_dashboard_regression_check.py` — 不存在
- `scripts/dashboard_regression_check.py` — 不存在

影响：`run_step_with_subs` 在脚本不存在时输出 `[WARN]` 并跳过，不影响主流程执行。

建议后续按需补充或移除该子步骤定义。

---

## 六、结论

**本轮 Round93 分析完成。全部 6 项问题均已确认为正常状态，无需代码修改。**

主流程当前状态满足所有验收标准：
1. ✅ manifest.json 在 posttrain_validation 前生成
2. ✅ inverse_predictions.pkl 可正确生成
3. ✅ 清理脚本不递归归档 archive 自身
4. ✅ 可视化导出只使用 `power_pred_final`
5. ✅ 可视化导出默认不包含 future
6. ✅ README 中不存在无效启动入口
