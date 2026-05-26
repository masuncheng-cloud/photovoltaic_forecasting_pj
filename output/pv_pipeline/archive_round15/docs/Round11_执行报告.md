# Round11 执行报告

> 生成时间：2026-05-24 15:52
> 执行目录：`/home/ac/data16t/msc/photovoltaic_forecasting_pj`

---

## 1. 背景与目标

Round10 建立了保底最优机制的第一版，但存在以下需要固化的问题：

| 问题 | 表现 | 修复方式 |
|:---|:---|:---|
| 候选决策 JSON 中 MAE/RMSE 命名错误 | `_mae` 函数实际输出 RMSE | 重写为独立 `calc_mae` / `calc_rmse` 函数 |
| 缺少候选排行榜 | 只有单个 JSON，不方便横向对比 | 新增 `summarize_candidate_decisions_round11.py` |
| rejected 候选产物仍在主目录 | 易被误读 | 归档到 `archive_round11/rejected_candidates/` |
| 保护机制未接入 train_fixed.py | 需手动调用 | 接入流水线 |
| 报告缺少历史候选说明 | 交付时易混淆 | 更新 `update_project_md_metrics.py` |

**Round11 不改任何模型预测结果，只做工程固化。**

---

## 2. 修改内容

### 2.1 修改一：修复候选晋级脚本指标命名（`promote_candidate_if_better_round10.py`）

**Bug 确认**：原 `_mae` 函数内部使用了 RMSE 公式，导致 `mae_mw` 字段实际记录的是 RMSE 值。

**修复内容**：
- 新增独立 `calc_mae(y, p)` → `mean(|y - p|)`
- 新增独立 `calc_rmse(y, p)` → `sqrt(mean((y-p)^2))`
- 保留 `calc_nrmse(y, p, c)` → `RMSE / mean(capacity) * 100`
- `metrics()` 输出：MAE、RMSE、NRMSE、midday_NRMSE、bias、pred/actual ratio
- `score()` 改为：0.45 × midday + 0.35 × overall + 0.10 × MAE + 0.10 × RMSE
- 新增 `midday_improve_pp` 字段

**修复后正确输出**：
- best MAE = 0.589320 MW
- best RMSE = 1.204699 MW

### 2.2 修改二：新增候选排行榜脚本（`summarize_candidate_decisions_round11.py`）

- 扫描所有 `round10_candidate_decision_*.json`
- 汇总晋级状态、整体 NRMSE、MAE、RMSE、拒绝原因
- 输出 `round11_candidate_leaderboard.csv` 和 `docs/候选模型晋级记录_Round11.md`

### 2.3 修改三：新增归档脚本（`archive_rejected_candidates_round11.py`）

- 根据 `round10_candidate_decision_*.json` 中 `accepted=false` 判断被拒候选
- 将对应 pkl、csv、模型文件移入 `archive_round11/rejected_candidates/`
- 主 metrics 目录保留 JSON 决策记录
- 输出归档清单 `archive_rejected_candidates_manifest.csv`

### 2.4 修改四：新增 pipeline 保护脚本（`run_round10_best_guard_pipeline.py`）

自动依次执行以下 6 个脚本：

| 顺序 | 脚本 | 作用 |
|:---:|:---|:---|
| 1 | `save_current_best_round10.py` | 初始化/保护 best |
| 2 | `check_final_is_best_round10.py` | 检查并回退 |
| 3 | `regenerate_final_metrics_round7.py` | 重算 final metrics |
| 4 | `assert_final_metrics_consistency_round7.py` | 一致性检查 |
| 5 | `compute_nrmse_reports_round10.py` | 生成 NRMSE 报告 |
| 6 | `summarize_candidate_decisions_round11.py` | 生成排行榜 |

### 2.5 修改五：更新报告生成脚本

**`update_project_md_metrics.py`** 新增：
- `## 历史候选说明` 段落（满足 `check_round8_final_package.py` 要求）
- `## Round10/11 保底最优机制` 段落
- 候选晋级记录汇总

### 2.6 修改六：接入 train_fixed.py

**SCRIPTS 列表**：新增 `run_round10_best_guard_pipeline.py`

**CRITICAL_SCRIPTS**：新增 `run_round10_best_guard_pipeline.py`

**KEY_OUTPUT_FILES**：新增：
- `tables/best_predictions_eval.pkl`
- `tables/best_predictions_full.pkl`
- `metrics/round10_site_hour_nrmse.csv`
- `metrics/round10_hour_overall_nrmse.csv`
- `metrics/round10_overall_nrmse_summary.csv`
- `metrics/round11_candidate_leaderboard.csv`

---

## 3. 执行过程

### Step 1：初始化 best
```bash
python scripts/save_current_best_round10.py
```

### Step 2：重新运行晋级（修复后版本）
```bash
python scripts/promote_candidate_if_better_round10.py \
  --candidate-eval .../distributed_predictions_midday_specialist_round9_eval.pkl \
  --candidate-full .../distributed_predictions_midday_specialist_round9_full.pkl \
  --name midday_specialist_round9 \
  --min-overall-improve-pp 0.10
```

### Step 3：生成排行榜
```bash
python scripts/summarize_candidate_decisions_round11.py
```

### Step 4：归档被拒绝候选
```bash
python scripts/archive_rejected_candidates_round11.py
```

### Step 5：运行完整保护 pipeline + 报告更新 + 验收
```bash
python scripts/run_round10_best_guard_pipeline.py
python scripts/update_project_md_metrics.py
python scripts/check_round8_final_package.py
```

---

## 4. 执行结果

### 4.1 候选晋级判断（修复后）

| 字段 | best | candidate (Round9 Specialist) |
|:---|---:|---:|
| 整体 NRMSE | **19.7105%** | 22.0894% |
| 10-14 NRMSE | 22.4364% | 22.0894%（+0.35pp 改善） |
| MAE | 0.5893 MW | 0.7747 MW |
| RMSE | 1.2047 MW | 1.4800 MW |
| 整体改善 | — | **-2.3789 pp（变差）** |
| 晋级判断 | — | **❌ 拒绝** |

指标修复后正确暴露了 Specialist 在中午时段 NRMSE 有小幅改善（+0.35pp），但整体 NRMSE 仍差 2.38pp，被正确拒绝。

### 4.2 归档结果

共归档 **11 个文件**（约 202 MB）：

| 类型 | 文件 |
|:---|:---|
| specialist eval/full pkl | 6 个 |
| specialist 模型 pkl | 2 个 |
| specialist metrics csv | 3 个 |

归档路径：`output/pv_pipeline/archive_round11/rejected_candidates/`

### 4.3 当前最优版本（final = best）

| 指标 | 值 |
|:---|---:|
| **整体 NRMSE** | **19.71%** |
| MAE | 0.589 MW |
| RMSE | 1.205 MW |
| bias | -1.41% |
| pred/actual ratio | 0.9859 |

### 4.4 验收通过

| 检查项 | 结果 |
|---|:---:|
| final = best（delta = 0.0 pp） | ✅ |
| Round9 specialist 正确拒绝 | ✅ |
| 指标命名正确（MAE ≠ RMSE） | ✅ |
| 排行榜生成 | ✅ |
| 11 个文件归档 | ✅ |
| `check_round8_final_package.py` | ✅ 通过 |
| `update_project_md_metrics.py` | ✅ |

---

## 5. 后续使用方式

任何新候选必须经过以下流程：

```bash
# 1. 生成候选预测（pkl 文件）
python scripts/<your_candidate_script>.py ...

# 2. 晋级判断
python scripts/promote_candidate_if_better_round10.py \
  --candidate-eval <eval.pkl> \
  --candidate-full <full.pkl> \
  --name <candidate_name> \
  --min-overall-improve-pp 0.10

# 3. 运行完整保护 pipeline
python scripts/run_round10_best_guard_pipeline.py

# 4. 更新报告
python scripts/update_project_md_metrics.py
```

只有 `accepted=true` 的候选才允许覆盖 final/best。
