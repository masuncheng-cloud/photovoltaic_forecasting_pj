# Round10 执行报告

> 生成时间：2026-05-24 13:54
> 执行目录：`/home/ac/data16t/msc/photovoltaic_forecasting_pj`

---

## 1. 背景与目标

Round9 结论确认：当前数据和特征条件下，10-14 点 NRMSE < 10% 目标不可达到；中午专用模型（sklearn HistGBDT + CatBoost 1.2 集成）均无法超越 MiddaySiteCalibrated。

本轮 Round10 目标：**建立保底最优版本保护机制**，确保任何后续实验都不会把结果越改越差。

---

## 2. 方案设计

### 2.1 核心机制

```
任何新模型/新修正/新候选
  → 先生成候选预测
  → 与当前最优 best_predictions_* 对比
  → 只有整体 NRMSE 改善 ≥ 0.10 pp 才晋级
  → 否则自动回退到 best_predictions_*
```

### 2.2 不做的事

1. 暂不增加新数据源
2. 不继续用 test 集调参
3. 不自动修改站点容量
4. 不自动剔除异常站点
5. 不允许更差候选覆盖 best

---

## 3. 新增文件

| 脚本 | 作用 |
|---|---|
| `scripts/save_current_best_round10.py` | 初始化 best_predictions_* 保护版本 |
| `scripts/compute_nrmse_reports_round10.py` | 生成完整 NRMSE 报告（站点小时级 + 小时整体 + 全局整体） |
| `scripts/promote_candidate_if_better_round10.py` | 候选晋级判断（门控 + 自动回退） |
| `scripts/check_final_is_best_round10.py` | 检查 final 是否比 best 差，若是则回退 |

### 3.1 初始化脚本

`save_current_best_round10.py`：将 `distributed_predictions_final_eval/full.pkl` 备份为 `best_predictions_eval/full.pkl`，同时写入元数据 JSON。

### 3.2 NRMSE 报告脚本

`compute_nrmse_reports_round10.py`：输出三个文件：

| 文件 | 内容 |
|---|---|
| `round10_site_hour_nrmse.csv` | 每个站点 × 每个小时 的 NRMSE、MAE、RMSE |
| `round10_hour_overall_nrmse.csv` | 每个小时（所有站点合并）的整体 NRMSE、MAE、RMSE |
| `round10_overall_nrmse_summary.csv` | 全局整体 NRMSE、MAE、RMSE、bias、pred/actual ratio |
| `round10_final_vs_best_nrmse.csv` | final 与 best 的逐指标对比 |

### 3.3 晋级判断脚本

`promote_candidate_if_better_round10.py`：门控逻辑：

```
candidate 更优 ⇔ best_nrmse - cand_nrmse ≥ 0.10 pp
```

若不满足，脚本自动执行：
- `best_predictions_*` 保持不变
- `distributed_predictions_final_*` 回退到 `best_predictions_*`
- 拒绝原因写入 `round10_candidate_decision_<name>.json`

### 3.4 回退检查脚本

`check_final_is_best_round10.py`：每次 pipeline 运行后执行，确保 final 不劣化。

---

## 4. 执行过程

### 4.1 Step 1：初始化 best

```bash
python scripts/save_current_best_round10.py
python scripts/compute_nrmse_reports_round10.py
```

**结果**：best_predictions_* 初始化成功

### 4.2 Step 2：测试晋级脚本（用 Round9 Specialist 作候选）

```bash
python scripts/promote_candidate_if_better_round10.py \
  --candidate-eval distributed_predictions_midday_specialist_round9_eval.pkl \
  --candidate-full distributed_predictions_midday_specialist_round9_full.pkl \
  --name midday_specialist_round9 \
  --min-overall-improve-pp 0.10
```

### 4.3 Step 3：检查与报告

```bash
python scripts/check_final_is_best_round10.py
python scripts/compute_nrmse_reports_round10.py
```

---

## 5. 执行结果

### 5.1 当前最优版本（初始化时 best = final）

| 指标 | 值 |
|:---|---:|
| 站点数 | 53 |
| 评估样本 | 68,888 |
| 实际总出力 | 93,382.49 MWh |
| 预测总出力 | 92,069.09 MWh |
| pred/actual ratio | 0.9859 |
| bias | -1.41% |
| **整体 NRMSE** | **19.71%** |
| MAE | 0.589 MW |
| RMSE | 1.205 MW |

### 5.2 每小时整体 NRMSE

| 小时 | 样本数 | 站点数 | 整体 NRMSE（%） | MAE（MW） | RMSE（MW） |
|:---:|---:|:---:|---:|---:|---:|
| 6 | 1,241 | 49 | 28.69 | 0.996 | 2.068 |
| 7 | 4,668 | 53 | 13.51 | 0.304 | 0.842 |
| 8 | 6,331 | 53 | 12.77 | 0.375 | 0.769 |
| 9 | 6,388 | 53 | 16.99 | 0.548 | 1.023 |
| 10 | 6,403 | 53 | 20.91 | 0.671 | 1.259 |
| 11 | 6,414 | 53 | 23.41 | 0.745 | 1.409 |
| 12 | 6,421 | 53 | 24.17 | 0.784 | 1.454 |
| 13 | 6,419 | 53 | 23.31 | 0.765 | 1.402 |
| 14 | 6,419 | 53 | 20.10 | 0.660 | 1.209 |
| 15 | 6,415 | 53 | 15.88 | 0.499 | 0.955 |
| 16 | 6,341 | 53 | 11.99 | 0.331 | 0.723 |
| 17 | 3,480 | 53 | 17.06 | 0.392 | 1.094 |
| 18 | 1,255 | 53 | 26.40 | 0.857 | 1.880 |
| 19 | 693 | 18 | 33.94 | 1.548 | 2.609 |

### 5.3 Round9 Specialist 晋级测试

| | 当前最优 (best) | Round9 Specialist |
|:---|---:|---:|
| 整体 NRMSE | **19.71%** | 22.09% |
| 改善 | — | **-2.38 pp（变差）** |
| 晋级判断 | — | **❌ 拒绝** |

**晋级脚本正确识别 specialist 更差，自动回退到 best_predictions_**，保护机制有效。

### 5.4 回退检查

| | 值 |
|:---|---:|
| final NRMSE | 19.7105% |
| best NRMSE | 19.7105% |
| delta | 0.0 pp |
| 状态 | **ok（无需回退）** |

---

## 6. 验收通过

| 检查项 | 结果 |
|---|:---:|
| best_predictions_* 初始化 | ✅ |
| 4 个脚本全部正确运行 | ✅ |
| Round9 specialist 被正确拒绝 | ✅ |
| final 与 best 完全一致（19.71%） | ✅ |
| 全部 4 个报告文件输出 | ✅ |
| final 回退机制正常（delta=0） | ✅ |

---

## 7. 后续使用方式

任何新候选通过晋级脚本判断后才允许替换 final：

```bash
python scripts/promote_candidate_if_better_round10.py \
  --candidate-eval <候选eval路径> \
  --candidate-full <候选full路径> \
  --name <候选名> \
  --min-overall-improve-pp 0.10
```

pipeline 每次运行后必须执行：

```bash
python scripts/check_final_is_best_round10.py
python scripts/compute_nrmse_reports_round10.py
```
