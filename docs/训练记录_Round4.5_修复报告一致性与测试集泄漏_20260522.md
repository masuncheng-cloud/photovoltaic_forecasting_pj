# 训练记录：Round 4.5 — 修复报告一致性与测试集泄漏

> 日期：2026-05-22
> 目标：修复报告不一致问题，消除测试集泄漏，确保评估流程严格可信

---

## 一、问题背景

Round 4 执行后，发现两个核心问题：

1. **`光伏功率预测项目.md` 数据未同步**：MD 仍写 `ratio=0.9561`，但与 Round 3 混用
2. **测试集泄漏**：`select_blend_per_hour_on_test()` 用 test 集选择 BlendTotal alpha，违反评估规范

---

## 二、修改内容

### 2.1 新建 `scripts/update_project_md_metrics.py`

从 `distributed_predictions_final_eval.pkl` 自动读取最新结果，生成 `output/pv_pipeline/docs/当前最终结果摘要.md`，避免手动同步。

核心逻辑：
```python
df = safe_pickle_load(TABLES / "distributed_predictions_final_eval.pkl")
ev = build_eval_frame(df, target_site_count=53)
# 计算整体指标、逐小时 NRMSE、版本选择
```

### 2.2 重命名 `select_blend_per_hour_on_test()` → `diagnose_blend_per_hour_on_test()`

- 函数改为**只生成诊断 CSV**（`blend_oracle_on_test_diagnostic_only.csv`），不修改 `selection`
- 输出的 CSV 包含 `oracle_best_version_on_test`、`oracle_mae_on_test` 等字段，标注 `diagnostic_only_not_used_for_final_selection`
- main 中调用改为 `diagnose_blend_per_hour_on_test(candidates, selection)`

### 2.3 关闭 test oracle guard

新增两个常量，默认均为 `False`：
```python
ENABLE_TEST_ORACLE_GUARD = False   # 关闭 apply_final_mae_rmse_guard
ENABLE_NRMSE_ORACLE_GUARD = False  # 关闭 apply_final_nrmse_guard
```

main 中改为：
```python
if ENABLE_NRMSE_ORACLE_GUARD:
    df_final, selection, rollback_hours = apply_final_nrmse_guard(...)
else:
    print("  跳过 final NRMSE oracle guard，避免 test 集参与最终选择")
```

### 2.4 修改 BlendTotal guard（valid 集选择阶段）

修改 `elif ver.startswith("BlendTotal"):` 分支：

```python
# MAE/RMSE 主约束：不允许大幅牺牲站点误差
if cand_mae > base_mae * 1.05:
    passed = False
    reasons.append(f"BlendTotal mae 恶化: {cand_mae:.4f} > 1.05*base")
if cand_rmse > base_rmse * 1.05:
    passed = False
    reasons.append(f"BlendTotal rmse 恶化: {cand_rmse:.4f} > 1.05*base")
# ratio 下限软约束（排除明显异常）
if cand_ratio < 0.55:
    passed = False
    reasons.append(f"BlendTotal ratio 过低: {cand_ratio:.3f} < 0.55")
```

### 2.5 strict hour 提前返回

在 `for h in HOURS:` 循环中，算完 `base_metrics` 后直接检查：

```python
if h in STRICT_NRMSE_GUARD_HOURS:
    base_score = score_candidates(base_metrics)
    selection[h] = ("V1", base_metrics, base_score, ["strict hour: force V1"])
    print(f"  h={h:02d}: strict hour 强制 V1 ...")
    continue
```

这样 strict hours（6/17/18/19）完全不进入 BlendTotal 选择逻辑。

### 2.6 修改 `compare_with_week2_reference.py` 文案

```python
# 旧文案
verdict_text = "当前 MAE/RMSE 仍未达到周二基准...应继续优先降低站点级误差。"
# 新文案
verdict_text = "当前 MAE({mae}) 和 RMSE({rmse}) 仍未达到周二基准({ref_mae},{ref_rmse})。当前版本工程闭环和口径统一更完整，但站点级预测精度仍低于周二版。"
```

### 2.7 更新 `光伏功率预测项目.md`

- **3.3.2 版本选择逻辑**：新增 oracle 诊断说明，明确"test 集仅诊断不参与 final 选择"
- **3.3.5 逐小时改善分析**：新增"版本选择在验证集上进行，test oracle 仅作诊断参考"声明
- **3.6 与周二基准对比**：改为明确判断——"不能表述为达到周二效果"

---

## 三、遇到的问题与修复

### 问题 1：旧代码残留导致语法错误

在替换 BlendTotal guard 时，旧的"宽松 1.50x"代码未完全清理，导致语法错误：
```
reasons.append(f"BlendTotal mae 极端恶化: {cand_mae:.4f} > 1.50*base...")
```
**修复**：删除残留的 5 行旧代码。

### 问题 2：ratio 保护阈值在 valid 集上永不满足

Round 4 曾尝试设置 `ratio < 0.90` 时尝试高 alpha，但 valid 集上所有 alpha 的 ratio 都 < 0.90。
**处理**：去掉阈值限制，改由 test oracle 诊断文件提供参考。

---

## 四、执行结果

### 4.1 流水线执行

```
[Step 3] 逐小时选择 …
  h=06: strict hour 强制 V1 (score=16.13, mae=0.2318, rmse=0.6085)
  h=07: 选择 BlendTotal_a10 (score=6.15), city_rel=17.3%, raw=35.3%, clip=39.5%
  h=08: 选择 BlendTotal_a10 (score=6.25), ...
  ...
  h=17: strict hour 强制 V1 (score=9.50, mae=0.4405, rmse=0.8094)
  h=18: strict hour 强制 V1 (score=6.91, mae=0.2019, rmse=0.4582)
  h=19: strict hour 强制 V1 (score=22.48, mae=0.3202, rmse=1.0839)

BlendTotal Oracle 诊断（test 集，仅诊断不参与 final 选择）…
  已保存 oracle 诊断: .../blend_oracle_on_test_diagnostic_only.csv

跳过 final NRMSE oracle guard，避免 test 集参与最终选择
跳过 final MAE/RMSE test oracle guard，避免 test 集参与最终选择

[FINAL CHECK]
  rows=68,888, sites=53
  pred_actual_ratio=0.9561
  MAE=0.5927 MW
  RMSE=1.2164 MW
```

### 4.2 验收标准检查

| 验收标准 | 结果 |
|---|---|
| `blend_oracle_on_test_diagnostic_only.csv` 生成 | ✅ 14 行 |
| selection 不被 test oracle 覆盖 | ✅ ratio=0.9561（valid 选择结果） |
| `当前最终结果摘要.md` 生成 | ✅ |
| 指标与 final pkl 一致 | ✅ rows=68,888, sites=53 |
| 关闭 test oracle guard | ✅ 流水线日志显示"跳过" |
| 报告中不写"达到周二效果" | ✅ 明确判断"仍低于周二版" |

### 4.3 当前指标

| 指标 | 当前值 | 周二基准 | 状态 |
|---|---|---|---|
| 样本数 | 68,888 | 67,102 | 参考 |
| 站点数 | 53 | 53 | ✅ 一致 |
| pred_actual_ratio | 0.9561 | 0.9488 | ✅ 范围内 |
| bias | -4.39% | -5.12% | ✅ 范围内 |
| MAE | 0.5927 MW | 0.4547 MW | ⚠️ 高 30.4% |
| RMSE | 1.2164 MW | 0.9676 MW | ⚠️ 高 25.7% |

---

## 五、版本选择（最终状态）

| 小时 | 选中版本 | 说明 |
|:---:|:---:|:---|
| 6 | V1 | strict hour，验证集强制 |
| 7 | BlendTotal_a10 | 验证集选择（pred_baseline 90% + ML 10%） |
| 8-16 | BlendTotal_a10 | 验证集选择 |
| 17 | V1 | strict hour，验证集强制 |
| 18 | V1 | strict hour，验证集强制 |
| 19 | V1 | strict hour，验证集强制 |

> 所有选择均在**验证集**（2025-07-01 ~ 2025-09-01）上完成。test 集（2025-09-01 ~ 2026-01-01）仅用于最终评估，不参与任何模型选择或参数调优。

---

## 六、后续方向

后处理已接近工程上限。MAE/RMSE 瓶颈在 V1 模型本身（逐小时 ratio 显示 6/17/18/19 早晚小时系统性偏低），后续优化应回到训练层：

1. **提升 V1 站点级预测质量**（根本途径）
2. **针对 S019、S053 等高误差站点做专项校准**
3. **对 10-14 点主体发电时段增加站点级误差权重**
4. **分析周二版模型配置**，参考其更优的站点级建模策略
