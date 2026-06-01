# Cursor执行方案 Round73：回退到当前最优版本，并从训练框架重新提升

## 一、目标

当前已知最优正式版本是：

```text
Round68 final
prediction column: power_pred_final
```

Round70、Round71、Round72 的模型候选均未超过 Round68，而且 Round72 暴露出 OOF 指标异常。因此本轮不要继续沿着 Round72 小修，而是：

1. **确认并回退到当前最优 Round68 final。**
2. **隔离 Round70-72 的实验产物，避免污染正式训练链路。**
3. **重新搭建一个干净、可复现、无泄漏的训练框架。**
4. **在新框架下做大步模型提升，而不是继续修补旧候选。**

本轮核心原则：

```text
先固定最优基线 -> 清理实验污染 -> 建立统一训练框架 -> 多窗口验证 -> 再训练候选模型
```

---

## 二、当前最优版本定义

以 Round68 final 为最优基线：

| 指标 | Round68 final |
|---|---:|
| site_mean_nrmse_6_19 | 10.58% |
| city_nrmse_6_19 | 4.13% |
| abs_bias_6_19 | 0.52% |
| bad_sites_gt_1pp | 0 |

如果本地正式结果已经是 Round68 final，则不需要真的覆盖 pkl，只需要校验并打 baseline 标记。

如果正式结果被 Round70/71/72 代码或产物污染，则必须回退到 Round68 final 备份或 tag。

---

## 三、第一步：确认当前是否已经是 Round68 final

### 3.1 新建脚本

新建：

```text
scripts/verify_current_best_round68.py
```

检查：

1. `distributed_predictions_final_full.pkl` 是否存在。
2. `distributed_predictions_final_eval.pkl` 是否存在。
3. `split == "future"` 行数是否为 0。
4. `metadata.json` 是否显示：

```json
"source_round": "Round68"
```

或等价信息。

5. 重新计算 test 6-19 指标：

```text
site_mean_nrmse_6_19
city_nrmse_6_19
abs_bias_6_19
bad_sites_gt_1pp
```

6. 与 Round68 指标容差比较：

```text
site_mean_nrmse_6_19: 10.58 ± 0.02
city_nrmse_6_19: 4.13 ± 0.02
abs_bias_6_19: 0.52 ± 0.05
bad_sites_gt_1pp: 0
```

输出：

```text
output/pv_pipeline/round73/round73_current_best_verify.json
output/pv_pipeline/round73/round73_current_best_verify.csv
```

如果不满足，输出：

```text
current_is_round68_final = false
```

---

## 四、第二步：回退到 Round68 final

### 4.1 优先使用 tag 回退代码

检查 tag：

```bash
git tag | grep round68
```

如果存在：

```text
round68-final-20260601
```

不要直接在当前分支 `reset --hard`。新建恢复分支：

```bash
git checkout -b recover/round68-final-from-tag round68-final-20260601
```

如果项目是在当前工作分支继续执行，不方便切分支，则至少先备份当前工作：

```bash
git status
git stash push -u -m "before-round73-recover"
```

然后再切换。

### 4.2 如果 pkl 已污染，使用备份回退

优先找：

```text
output/pv_pipeline/backups/distributed_predictions_final_full_before_round68_*.pkl
output/pv_pipeline/backups/distributed_predictions_final_eval_before_round68_*.pkl
```

但注意：这些是 Round68 升级前备份，未必是 Round68 final。  
因此更推荐使用 Round69 执行后生成的 Round68 final 产物。

如果已有 `promote_round68_candidate.py`，可以重新执行：

```bash
python scripts/promote_round68_candidate.py --apply --exclude-future
```

然后：

```bash
python scripts/export_interactive_dashboard_data.py \
  --prediction-pkl output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --prediction-col power_pred_final \
  --dashboard-root output/pv_pipeline/interactive_dashboard \
  --label "Round68 final" \
  --exclude-future
```

再执行：

```bash
python scripts/verify_current_best_round68.py
```

必须通过后才能进入后续训练框架重构。

---

## 五、第三步：隔离 Round70-72 实验污染

不要删除，先归档。

新建脚本：

```text
scripts/archive_failed_round_experiments.py
```

将以下目录移动或复制到：

```text
archive/failed_experiments/
```

建议归档：

```text
output/pv_pipeline/round70/
output/pv_pipeline/round71/
output/pv_pipeline/round72/
docs/Round70_*.md
docs/Round71_*.md
docs/Round72_*.md
```

注意：

- 不删除源文件前，先 `--dry-run`。
- 不归档 Round68 final、Round69 正式采用报告。
- 不归档当前正式 `predictions/` 和 `interactive_dashboard/`。

执行：

```bash
python scripts/archive_failed_round_experiments.py --dry-run
python scripts/archive_failed_round_experiments.py --apply
```

输出：

```text
output/pv_pipeline/round73/round73_archive_failed_experiments.csv
```

---

## 六、第四步：重建训练框架，而不是继续补残差

### 6.1 新训练框架名称

新建目录：

```text
pv_forecasting/training_v2/
```

目标是把训练过程拆成稳定模块：

```text
data_spec.py
split_strategy.py
feature_builder.py
model_registry.py
candidate_runner.py
metric_guard.py
reporting.py
```

### 6.2 新框架必须解决的问题

1. **统一样本口径**

```text
训练、验证、测试默认都只看 6-19 点。
```

2. **统一预测列**

任何残差训练都必须显式声明：

```text
base_prediction_col
```

且 train/valid/test 都必须非空。

3. **禁止泄漏**

任何 OOF 或滚动训练必须满足：

```text
train_time < predict_time
```

4. **多窗口验证**

不能只用 7-8 月 valid。新增历史回测窗口，例如：

```text
2023-09~2023-12
2024-09~2024-12
2025-05~2025-08
```

实际窗口根据数据范围自动生成，但必须包含至少一个秋冬窗口。

5. **候选真实生效检查**

候选预测列必须与 baseline 有足够差异：

```text
changed_ratio > 1%
mean_abs_diff > 1e-6
```

否则标记为无效。

6. **性能优先**

主要优化目标：

```text
site_mean_nrmse_6_19
city_nrmse_6_19
city_nrmse_10_14
abs_bias_6_19
bad_sites_gt_1pp
```

---

## 七、第五步：建立新的回测式训练数据集

### 7.1 新建脚本

```text
scripts/build_training_v2_backtest_dataset.py
```

输入：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
```

输出：

```text
output/pv_pipeline/round73/training_v2_backtest_dataset.parquet
output/pv_pipeline/round73/training_v2_backtest_windows.csv
output/pv_pipeline/round73/training_v2_data_quality.csv
```

### 7.2 回测窗口设计

不要只用当前 train/valid/test。按历史月份构造多个“伪测试窗口”：

```text
window_A: 2023-09~2023-12
window_B: 2024-09~2024-12
window_C: 2025-05~2025-08
holdout_test: 原 test 2025-09~2025-12
```

如果某窗口样本不足，自动跳过，但必须保留至少 2 个非 test 回测窗口。

### 7.3 数据质量输出

每个窗口输出：

```text
sample_count
positive_rate
inactive_rate
city_nrmse_baseline
site_mean_nrmse_baseline
abs_bias_baseline
```

目的：确认训练框架能覆盖类似 test 的秋冬低发电分布。

---

## 八、第六步：训练真正的新候选模型

本轮不再训练复杂状态分类器，也不再训练旧式全功率模型。训练 3 类更稳的候选：

### 8.1 候选 A：秋冬专用保守残差模型

名称：

```text
power_pred_round73_autumn_winter_residual
```

训练窗口：

```text
历史 9-12 月窗口
```

目标：

```text
residual_norm = power_mw/capacity_mw - power_pred_final/capacity_mw
```

注意：如果历史窗口缺少 `power_pred_final`，不要继续用旧列混训；需要用统一的 `baseline_proxy_col`，并在报告中说明。

### 8.2 候选 B：10-14 点低幅度 bias 约束模型

名称：

```text
power_pred_round73_noon_bias_guard
```

只允许对 10-14 点做小幅修正：

```text
修正幅度 <= capacity_mw * 0.03
```

目标不是单纯降低 bias，而是：

```text
city_nrmse_10_14 不变差
abs_bias_10_14 下降
site_mean_nrmse_10_14 不变差
```

### 8.3 候选 C：高误差站点保守 shrinkage 模型

名称：

```text
power_pred_round73_high_error_shrinkage
```

高误差站点只基于非 test 回测窗口选择，不能用 test 选。

采用 shrinkage：

```text
P_new = P_base + alpha * correction
alpha ∈ [0.1, 0.2, 0.3, 0.5]
```

避免单站点过拟合。

### 8.4 输出

```text
output/pv_pipeline/round73/round73_candidates.pkl
output/pv_pipeline/round73/round73_candidate_training_summary.csv
output/pv_pipeline/round73/round73_candidate_diff_check.csv
```

---

## 九、第七步：回测窗口选择，不用 test 选模型

新建：

```text
scripts/select_round73_candidate_by_backtest.py
```

选择依据：

候选必须在至少 2 个非 test 回测窗口上满足：

```text
site_mean_nrmse_6_19 <= baseline - 0.05pp
city_nrmse_6_19 <= baseline + 0.05pp
bad_sites_gt_1pp == 0
abs_bias_6_19 <= baseline + 0.20pp
```

并且在秋冬回测窗口上：

```text
city_nrmse_10_14 <= baseline
abs_bias_10_14 <= baseline
```

输出：

```text
output/pv_pipeline/round73/round73_backtest_candidate_compare.csv
output/pv_pipeline/round73/round73_candidate_decision.json
```

如果没有候选通过：

```text
decision = keep_round68_final
```

---

## 十、第八步：test 只做最终评估

新建：

```text
scripts/evaluate_round73_candidate_on_test.py
```

输出：

```text
output/pv_pipeline/round73/round73_test_overall_compare.csv
output/pv_pipeline/round73/round73_test_hourly_compare.csv
output/pv_pipeline/round73/round73_test_site_compare.csv
docs/Round73_回退最优版本并重构训练框架提升报告.md
```

报告必须回答：

1. 是否已回退/确认到 Round68 final？
2. Round70-72 是否已隔离？
3. 新训练框架是否建立？
4. 是否构造了秋冬回测窗口？
5. 候选是否在非 test 回测窗口通过？
6. test 上是否真正超过 Round68 final？
7. 如果没有超过，是否说明当前无外部气象数据下提升空间很小？

---

## 十一、统一入口

修改：

```text
scripts/run_full_pipeline.py
```

新增：

```bash
python scripts/run_full_pipeline.py --mode round73-training-framework-reset
```

执行顺序：

```text
verify_current_best_round68
archive_failed_round_experiments --dry-run
build_training_v2_backtest_dataset
train_round73_backtest_candidates
select_round73_candidate_by_backtest
evaluate_round73_candidate_on_test
write Round73 report
```

---

## 十二、执行命令

优先执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/run_full_pipeline.py --mode round73-training-framework-reset
```

如果统一入口未接好：

```bash
mkdir -p output/pv_pipeline/round73

python scripts/verify_current_best_round68.py

python scripts/archive_failed_round_experiments.py --dry-run

python scripts/build_training_v2_backtest_dataset.py

python scripts/train_round73_backtest_candidates.py

python scripts/select_round73_candidate_by_backtest.py

python scripts/evaluate_round73_candidate_on_test.py
```

---

## 十三、Git 提交

执行通过后：

```bash
git status

git add pv_forecasting/training_v2/
git add scripts/verify_current_best_round68.py
git add scripts/archive_failed_round_experiments.py
git add scripts/build_training_v2_backtest_dataset.py
git add scripts/train_round73_backtest_candidates.py
git add scripts/select_round73_candidate_by_backtest.py
git add scripts/evaluate_round73_candidate_on_test.py
git add scripts/run_full_pipeline.py
git add docs/Round73_回退最优版本并重构训练框架提升报告.md
git add output/pv_pipeline/round73/*.csv
git add output/pv_pipeline/round73/*.json

git commit -m "feat: reset to best baseline and add training v2 framework"
git push origin HEAD
```

不要提交：

```text
*.pkl
*.parquet
*.joblib
archive/failed_experiments/**/*
```

---

## 十四、验收标准

Round73 通过标准：

1. 当前正式结果确认是 Round68 final。
2. Round70-72 实验结果已隔离，不再污染正式链路。
3. 新训练框架目录 `pv_forecasting/training_v2/` 建立。
4. 至少 2 个非 test 回测窗口建立。
5. 候选模型不使用 test 选择。
6. 候选列真实不同于 baseline。
7. test 只做最终评估。
8. 若候选不如 Round68 final，自动保留 Round68。
9. 报告明确说明是否仍有无外部气象数据下的提升空间。

---

## 十五、执行完成后发回

请发回：

```text
docs/Round73_回退最优版本并重构训练框架提升报告.md
output/pv_pipeline/round73/round73_current_best_verify.json
output/pv_pipeline/round73/training_v2_backtest_windows.csv
output/pv_pipeline/round73/training_v2_data_quality.csv
output/pv_pipeline/round73/round73_candidate_training_summary.csv
output/pv_pipeline/round73/round73_candidate_diff_check.csv
output/pv_pipeline/round73/round73_backtest_candidate_compare.csv
output/pv_pipeline/round73/round73_candidate_decision.json
output/pv_pipeline/round73/round73_test_overall_compare.csv
output/pv_pipeline/round73/round73_test_hourly_compare.csv
output/pv_pipeline/round73/round73_test_site_compare.csv
```

我会据此判断：

- 是否真正回到了最优基线；
- 新训练框架是否解决了之前的链路混乱；
- 是否还有无需外部气象数据的提升空间；
- 下一步是否该正式转向 ERA5/NWP 数据接入。

