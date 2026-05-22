# Cursor 下一步修改代码：修复 Round4 报告一致性与测试集泄漏

## 一、当前问题

当前 Round4 代码和报告相比周二版有两个核心问题：

1. `光伏功率预测项目.md` 没有同步 Round4 最新结果。
   - MD 中仍写：`ratio=0.9561`、`bias=-4.39%`、`MAE=0.5927`、`RMSE=1.2164`
   - 实际 final pkl 是：`ratio=0.9333`、`bias=-6.674%`、`MAE=0.5932`、`RMSE=1.2276`

2. `select_final_prediction_by_guard.py` 中新增的 `select_blend_per_hour_on_test()` 使用 test 集选择 BlendTotal alpha。
   - 这会导致 test 集参与模型选择。
   - 即使当前只评估已有数据集能力，也应避免把它写成严格泛化测试结果。
   - 正式 final 应只允许用 valid 选择参数，test 只做最终评估。

当前目标：

```text
先修结果一致性和评估可信度，不继续追总量 ratio。
```

本轮不重训模型，只修改后处理、报告生成和选择逻辑。

---

## 二、修改最终选择逻辑：禁止 test 集选 alpha

文件：

`scripts/select_final_prediction_by_guard.py`

### 2.1 保留 test 诊断，但不能用于 final

找到当前函数：

```python
def select_blend_per_hour_on_test(candidates, selection):
    ...
```

不要直接删除，改名为：

```python
def diagnose_blend_per_hour_on_test(candidates, selection):
```

函数用途改成“只输出诊断 CSV，不修改 selection”。

函数开头 docstring 改为：

```python
"""仅用于诊断 BlendTotal 在 test 集上的理论上限，不参与 final 版本选择。

注意：
- test 集不能用于模型选择；
- 该函数只生成 oracle 诊断文件；
- final 仍必须使用 valid 集选择结果。
"""
```

### 2.2 删除或注释该函数中修改 selection 的代码

在原函数里如果有类似：

```python
selection[h] = (best_ver, best_metrics, best_score, reasons)
```

必须删除或注释，替换为只记录行：

```python
rows.append({
    "hour": int(h),
    "oracle_best_version_on_test": best_ver,
    "oracle_score_on_test": round(best_score, 4),
    "oracle_mae_on_test": round(best_metrics.get("mae", np.nan), 4),
    "oracle_rmse_on_test": round(best_metrics.get("rmse", np.nan), 4),
    "oracle_nrmse_capacity_pct_on_test": round(best_metrics.get("nrmse_capacity_pct", np.nan), 4),
    "oracle_pred_actual_ratio_on_test": round(best_metrics.get("pred_actual_ratio", np.nan), 6),
    "note": "diagnostic_only_not_used_for_final_selection",
})
```

函数最后保存：

```python
diag = pd.DataFrame(rows)
diag.to_csv(
    METRICS_DIR / "blend_oracle_on_test_diagnostic_only.csv",
    index=False,
    encoding="utf-8-sig",
)
print(f"  已保存 test oracle 诊断: {METRICS_DIR / 'blend_oracle_on_test_diagnostic_only.csv'}")
return selection
```

### 2.3 main 中不要再用 test 诊断覆盖 selection

找到 main 中类似：

```python
selection = select_blend_per_hour_on_test(candidates, selection)
```

替换为：

```python
# 只生成 test oracle 诊断，不参与 final 选择，避免测试集泄漏
selection = diagnose_blend_per_hour_on_test(candidates, selection)
```

并确保 `diagnose_blend_per_hour_on_test()` 返回的仍是原始 `selection`。

---

## 三、修改 valid 选择策略：MAE/RMSE 优先，但保持 ratio 底线

仍在：

`scripts/select_final_prediction_by_guard.py`

### 3.1 保留扩展 alpha

确保：

```python
BLEND_ALPHAS = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
```

### 3.2 修改 BlendTotal guard

在 `elif ver.startswith("BlendTotal"):` 分支中，使用 valid 集判断候选是否可用。逻辑如下：

```python
# MAE/RMSE 主约束：不允许为了 ratio 大幅牺牲站点误差
if np.isfinite(base_mae) and np.isfinite(cand_mae):
    if cand_mae > base_mae * 1.05:
        passed = False
        reasons.append(
            f"BlendTotal mae 恶化: {cand_mae:.4f} > 1.05*base {base_mae:.4f}"
        )

if np.isfinite(base_rmse) and np.isfinite(cand_rmse):
    if cand_rmse > base_rmse * 1.05:
        passed = False
        reasons.append(
            f"BlendTotal rmse 恶化: {cand_rmse:.4f} > 1.05*base {base_rmse:.4f}"
        )
```

同时增加 ratio 下限保护，但只作为软约束：

```python
cand_ratio = cand_metrics.get("pred_actual_ratio", np.nan)
if np.isfinite(cand_ratio) and cand_ratio < 0.55 and h not in STRICT_NRMSE_GUARD_HOURS:
    passed = False
    reasons.append(f"BlendTotal ratio 过低: {cand_ratio:.3f} < 0.55")
```

说明：

- 这里用 valid 集选择，不再用 test 选择。
- ratio 底线不能太高，因为 valid/test 季节分布不同；设置 0.55 只排除明显异常。

### 3.3 strict hours 固定 V1

在遍历候选之前，给 6、17、18、19 点直接回退 V1，避免早晚时段被混合策略扰动：

在 `for h in HOURS:` 内，算完 `base_metrics` 后加入：

```python
if h in STRICT_NRMSE_GUARD_HOURS:
    base_score = score_candidates(base_metrics)
    selection[h] = ("V1", base_metrics, base_score, ["strict hour: force V1"])
    print(
        f"  h={h:02d}: strict hour 强制 V1 "
        f"(score={base_score:.2f}, mae={base_metrics.get('mae', np.nan):.4f}, "
        f"rmse={base_metrics.get('rmse', np.nan):.4f})"
    )
    continue
```

这样 strict hours 不再经过 BlendTotal 选择。

---

## 四、修复 final MAE/RMSE guard：只能用 valid 规则，不能用 test 调参

当前 `apply_final_mae_rmse_guard()` 会在 final 生成后用 test 对比 V1 并回退。它属于“test 后验修正”，也会造成 test 参与最终产物。

两种处理方式选一种：

### 推荐方式 A：默认关闭 final test guard

在常量区加入：

```python
ENABLE_TEST_ORACLE_GUARD = False
```

在 main 中找到：

```python
df_final, selection, mae_guard_hours = apply_final_mae_rmse_guard(...)
```

改成：

```python
if ENABLE_TEST_ORACLE_GUARD:
    df_final, selection, mae_guard_hours = apply_final_mae_rmse_guard(
        df_final,
        candidates["V1"],
        selection,
    )
    if mae_guard_hours:
        print(f"  final MAE/RMSE oracle guard 回退小时: {mae_guard_hours}")
else:
    print("  跳过 final MAE/RMSE test oracle guard，避免 test 集参与最终选择")
```

### 可选方式 B：保留函数但只生成诊断

如果需要保留 test 回退分析，把输出另存为：

```text
metrics/final_mae_rmse_oracle_guard_diagnostic_only.csv
```

但不能修改 `df_final`。

---

## 五、同步当前 MD 报告数据

文件：

`光伏功率预测项目.md`

当前 MD 仍是 Round3 数据，必须改为 Round4 当前实际结果，或者改为脚本自动生成。

### 5.1 修改 3.3.3 测试集周报整体统计

把当前表：

```text
预测总出力 89,286.70
pred_actual_ratio 0.9561
bias -4.39%
全样本NRMSE 19.90%
MAE 0.5927
RMSE 1.2164
```

改为当前 Round4 实际值：

```text
预测总出力 87,150.14
pred_actual_ratio 0.9333
bias -6.674%
全样本NRMSE 20.086%
MAE 0.5932
RMSE 1.2276
```

注意：全样本 NRMSE 用：

```text
RMSE / mean(capacity_mw) × 100%
```

如果脚本输出为其他值，以 `分布式光伏预测_周报_整体统计.csv` 为准。

### 5.2 修改 3.3.2 版本选择逻辑

当前 MD 写：

```text
7-16 BlendTotal_a10
```

这是 Round3，不是 Round4。

改为 Round4 选择：

```markdown
| 小时 | 选中版本 | 说明 |
|:---:|:---:|:---|
| 6 | V1 | strict hour，固定 V1 |
| 7 | BlendTotal_a10 | valid 选择，早晨爬坡 |
| 8 | BlendTotal_a10 | valid 选择 |
| 9 | BlendTotal_a10 | valid 选择 |
| 10 | BlendTotal_a30 | 主体发电时段，增加 ML 权重 |
| 11 | BlendTotal_a20 | 主体发电时段 |
| 12 | BlendTotal_a30 | 主体发电时段 |
| 13 | BlendTotal_a30 | 主体发电时段 |
| 14 | BlendTotal_a30 | 主体发电时段 |
| 15 | BlendTotal_a20 | 下午回落前 |
| 16 | BlendTotal_a10 | 傍晚前过渡 |
| 17 | V1 | strict hour，固定 V1 |
| 18 | V1 | strict hour，固定 V1 |
| 19 | V1 | strict hour，固定 V1 |
```

如果本轮修复后不再使用 test 选 alpha，则以新的 `final_version_selection_by_hour.csv` 为准重新写。

### 5.3 修改 3.3.4 逐小时 NRMSE

当前 Round4 实际值：

```text
6:  rows=1241, site=5.81, city=13.378
7:  rows=4668, site=5.12, city=3.294
8:  rows=6331, site=7.26, city=1.293
9:  rows=6388, site=10.68, city=0.199
10: rows=6403, site=13.40, city=0.134
11: rows=6414, site=14.90, city=0.031
12: rows=6421, site=15.51, city=0.261
13: rows=6419, site=15.44, city=0.258
14: rows=6419, site=13.52, city=0.036
15: rows=6415, site=9.89, city=0.011
16: rows=6341, site=6.70, city=0.459
17: rows=3480, site=5.43, city=5.142
18: rows=1255, site=5.34, city=11.615
19: rows=693, site=13.53, city=20.141
```

用这些值替换旧表。

### 5.4 修改 3.6 与周二基准对比

加入明确判断：

```markdown
当前 Round4 与周二相比：

- 工程闭环、指标口径、报告一致性优于周二；
- 城市级逐小时 NRMSE 多数小时优于周二；
- 但站点级 MAE/RMSE 仍未恢复到周二水平；
- 当前 MAE 为 0.5932 MW，高于周二 0.4547 MW；
- 当前 RMSE 为 1.2276 MW，高于周二 0.9676 MW；
- 因此不能表述为“效果达到周二”，只能表述为“工程闭环更完整，但站点级预测精度仍低于周二”。
```

---

## 六、让报告自动读取最新结果，避免手动不同步

建议新建脚本：

`scripts/update_project_md_metrics.py`

作用：

- 读取 `distributed_predictions_final_eval.pkl`
- 读取 `final_version_selection_by_hour.csv`
- 读取 `分布式光伏预测_逐小时平均NRMSE.csv`
- 替换 `光伏功率预测项目.md` 中 3.3.2、3.3.3、3.3.4、3.6 的数据块

如果暂时不做自动替换，至少新增一个自动生成摘要文件：

`output/pv_pipeline/docs/当前最终结果摘要.md`

写入代码：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics


OUT = PROJECT_ROOT / "output" / "pv_pipeline"
TABLES = OUT / "tables"
METRICS = OUT / "metrics"
DOCS = OUT / "docs"
DOCS.mkdir(parents=True, exist_ok=True)


def main():
    df = safe_pickle_load(TABLES / "distributed_predictions_final_eval.pkl")
    ev = build_eval_frame(df, target_site_count=53)

    actual = pd.to_numeric(ev["power_mw"], errors="coerce").sum()
    pred = pd.to_numeric(ev["power_pred"], errors="coerce").sum()
    err = pd.to_numeric(ev["power_pred"], errors="coerce") - pd.to_numeric(ev["power_mw"], errors="coerce")
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err ** 2)))
    cap_mean = float(pd.to_numeric(ev["capacity_mw"], errors="coerce").mean())
    nrmse = rmse / max(cap_mean, 1e-9) * 100

    lines = []
    lines.append("# 当前最终结果摘要\n")
    lines.append("## 整体指标\n")
    lines.append(f"- 样本数：{len(ev):,}")
    lines.append(f"- 站点数：{ev['site_id'].nunique()}")
    lines.append(f"- 实际总出力：{actual:.2f} MWh")
    lines.append(f"- 预测总出力：{pred:.2f} MWh")
    lines.append(f"- pred_actual_ratio：{pred / max(actual, 1e-9):.4f}")
    lines.append(f"- bias：{(pred - actual) / max(actual, 1e-9) * 100:.3f}%")
    lines.append(f"- 全样本 NRMSE：{nrmse:.3f}%")
    lines.append(f"- MAE：{mae:.4f} MW")
    lines.append(f"- RMSE：{rmse:.4f} MW")

    lines.append("\n## 逐小时 NRMSE\n")
    h = hourly_nrmse_metrics(ev)[["hour", "rows", "site_nrmse_mean_pct", "city_nrmse_pct"]]
    lines.append(h.to_string(index=False))

    sel_path = METRICS / "final_version_selection_by_hour.csv"
    if sel_path.exists():
        sel = pd.read_csv(sel_path)
        cols = [c for c in ["hour", "selected_version", "mae", "rmse", "pred_actual_ratio"] if c in sel.columns]
        lines.append("\n## 版本选择\n")
        lines.append(sel[cols].to_string(index=False))

    (DOCS / "当前最终结果摘要.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Saved: {DOCS / '当前最终结果摘要.md'}")


if __name__ == "__main__":
    main()
```

然后把它加入 `train_fixed.py` 后处理阶段：

```python
ROOT / 'scripts' / 'update_project_md_metrics.py',
```

或者先手动执行：

```bash
python scripts/update_project_md_metrics.py
```

---

## 七、修改 `compare_with_week2_reference.py` 文案

文件：

`scripts/compare_with_week2_reference.py`

把结论改得更明确：

```python
if current["mae_mw"] <= ref["mae_mw"] and current["rmse_mw"] <= ref["rmse_mw"]:
    md.append("当前 MAE/RMSE 已达到或优于周二基准。")
else:
    md.append(
        "当前 MAE/RMSE 仍未达到周二基准。"
        "当前版本工程闭环和口径统一更完整，但站点级预测精度仍低于周二。"
    )
```

---

## 八、执行顺序

本轮先不完整重训，只跑后处理：

```bash
cd /Users/masuncheng/Downloads/photovoltaic_forecasting_pj
python scripts/select_final_prediction_by_guard.py
python scripts/regenerate_chinese_metrics.py
python scripts/compare_with_week2_reference.py
python scripts/update_project_md_metrics.py
python scripts/check_pipeline_consistency.py
python scripts/train_fixed.py --skip-training --data-root data --output-root output/pv_pipeline
```

如果确认没有 test 选参泄漏、报告同步正确，再决定是否完整重训。

---

## 九、验收标准

执行后检查：

1. `final_version_selection_by_hour.csv` 不应再由 test oracle 覆盖 selection。
2. 可以生成 `blend_oracle_on_test_diagnostic_only.csv`，但该文件只能用于诊断。
3. `光伏功率预测项目.md` 和 `当前最终结果摘要.md` 中的整体指标必须一致。
4. `当前结果_vs_周二基准_整体对比.csv` 中当前值必须等于 final pkl 复算值。
5. 报告中不能写“达到周二效果”，除非 MAE/RMSE 真正低于周二。
6. 若当前 MAE/RMSE 仍为约 `0.5932 / 1.2276`，结论必须写成：

```text
工程闭环更完整，但站点级预测精度仍低于周二版。
```

---

## 十、后续真正提升 MAE/RMSE 的方向

如果这轮修完后 MAE/RMSE 仍高于周二，不要继续调 BlendTotal。原因是后处理已接近上限。

下一步需要回到训练层：

1. 恢复或重建周二版 `distributed_model.py / train_distributed_model_v159.py` 中更优的站点级模型配置。
2. 对 10-14 点主体发电时段增加站点级误差权重。
3. 对 S019、S053 等高误差站点做站点级单独校准。
4. 分别评估城市聚合模型和站点级模型，不要用城市总量优化覆盖站点预测目标。

