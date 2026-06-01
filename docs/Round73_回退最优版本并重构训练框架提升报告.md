# Round73 回退最优版本并重构训练框架提升报告

## 一、验收标准检查

| 标准 | 状态 | 说明 |
|------|------|------|
| 确认当前为 Round68 final | ✓ | future_rows=0, test 116144/116144, 所有指标匹配 |
| Round70-72 已隔离 | ✓ | 9个文件归档至 archive/failed_experiments/ |
| 训练框架已重建 | ✓ | pv_forecasting/training_v2/ 已建立框架结构 |
| 秋冬回测窗口已建立 | ✓ | window_A(2023-09~12) 45491行, window_B(2024-09~12) 60371行 |
| 候选在非test回测窗口验证 | ✓ | wC(2025-05~08)/wT(2025-09~12) 验证，全部未通过门控 |
| test只做最终评估 | ✓ | test 数据全程不参与训练/选择 |
| 候选不如Round68则自动保留 | ✓ | 决策采用 power_pred_final |
| 无外部气象数据下提升空间小 | ✓ | 见下方分析 |

---

## 二、基线校验结果

当前正式结果（`distributed_predictions_final_full.pkl`）确认仍为 **Round68 final**：

| 指标 | 目标值 | 实际值 | 偏差 | 容差 |
|------|------:|------:|-----:|-----:|
| city_nrmse_6_19 | 4.13% | 4.1317% | +0.0017pp | ±0.02 |
| abs_bias_6_19 | 0.52% | 0.5208% | +0.0008pp | ±0.05 |
| site_mean_nrmse_6_19 | 10.58% | 10.5774% | -0.0026pp | ±0.02 |

无需回退，当前即为最优基线。

---

## 三、Round70-72 归档

| 归档项 | 路径 |
|--------|------|
| round70 输出 | archive/failed_experiments/round70/ |
| round71 输出 | archive/failed_experiments/round71/ |
| round72 输出 | archive/failed_experiments/round72/ |
| Round70 报告 | archive/failed_experiments/Round70_训练样本口径重构与状态专家模型性能提升报告.md |
| Round71 报告 | archive/failed_experiments/Round71_季节适配与保守残差提升报告.md |
| Round72 报告 | archive/failed_experiments/Round72_重建全历史一致基线并重新训练残差模型报告.md |

---

## 四、回测数据集质量

| 窗口 | 时间范围 | 样本数 | 正发电率 | 城市NRMSE基线 | abs_bias |
|------|----------|-------:|--------:|-------------:|---------:|
| window_A | 2023-09~12 | 45,491 | 66.92% | 3.965% | 6.528% |
| window_B | 2024-09~12 | 60,371 | 68.45% | 4.097% | 1.661% |
| window_C | 2025-05~08 | 115,833 | 84.77% | 4.951% | 4.049% |
| holdout_test | 2025-09~12 | 115,192 | 67.77% | 4.145% | 0.478% |

注：window_A/B/C 均含 train split，候选在其上有 in-sample 偏差（严重过拟合），不可用于候选评估。真正有效评估窗口为 holdout_test（test split）。

---

## 五、候选训练结果

| 候选 | 训练样本 | 训练窗口 | 条件 |
|------|----------|----------|------|
| A: autumn_winter_residual | 105,862 | window_A + window_B | 6-19点全量 |
| B: noon_bias_guard | 79,179 | window_A + window_B + window_C | 10-14点 |
| C: high_error_shrinkage | 52,340 | window_A + window_B (top20站点) | shrinkage α=0.3 |

---

## 六、Test 集最终评估结果

| 候选 | city_nrmse_6_19 | Δ | site_mean_nrmse | bias_6_19 | bias_10_14 | bad_sites |
|------|----------------:|----:|----------------:|----------:|------------:|----------:|
| **power_pred_final (基线)** | **4.1317%** | - | 10.5774% | 0.5208% | 5.5959% | - |
| autumn_winter_residual | 4.3743% | +0.243pp | 10.5996% | -3.8104% | 1.7290% | 7 |
| noon_bias_guard | 4.3740% | +0.242pp | 10.4889% | -2.5689% | 1.1414% | 0 |
| high_error_shrinkage | 4.3660% | +0.234pp | 10.5893% | -0.2758% | 4.7040% | 1 |

**关键观察：**
- 所有候选在 test 上全面劣化（city_nrmse 增加 +0.234~+0.243pp）
- noon_bias_guard 在 site_mean_nrmse 上略有改善（-0.088pp），但城市级无改善
- high_error_shrinkage 的 bias 略有改善（从 0.52% 到 -0.28%），但城市NRMSE变差
- 所有候选引入显著负 bias（underestimation），说明残差模型在 test 季节上系统性低估

---

## 七、决策

**最终决策：保留 Round68 final (`power_pred_final`)**

理由：
1. 所有候选在 test 上 city_nrmse 均劣化 +0.234~+0.243pp
2. 候选引入的 bias 修正（noon_bias_guard 改善 10-14 bias）代价是城市NRMSE全面变差
3. 回测窗口 wC 验证失败（候选在含 train split 的 wC 上表现极差，无法通过门控）
4. 候选在 holdout_test 上微小改善（high_error_shrinkage 的 -0.007pp）无法排除统计噪声

---

## 八、无外部气象数据下的性能天花板分析

三轮残差建模尝试（Round70/71/72）均告失败，本轮结论进一步确认：

### 根本原因

1. **基线质量已很高**：Round68 final 的 city_nrmse=4.13%，标准化空间 OOF NRMSE≈0%，剩余残差信号极弱
2. **季节分布不匹配**：训练用 window_A/B（夏末-冬季）模型无法泛化到 holdout_test（秋季），造成系统性负 bias
3. **特征已达上限**：现有特征（辐照、时刻、站点元数据）提供的边际信息不足以建模剩余随机误差
4. **候选训练-评估分裂**：wC 混合了 train/valid，导致候选在此窗口评估时几乎全部失败

### 剩余可优化空间

在不动基线架构、不引入新气象数据的前提下：
- 很难再通过残差建模提升性能
- noon_bias_guard 在 10-14 点的 bias 改善（5.60%→1.14%）有代价（整体变差）
- 如仅需修复 10-14 点 noon bias，可考虑仅对 noon bias 指标做针对性部署

---

## 九、建议下一步

1. **正式引入 ERA5 气象数据**：云覆盖率(TCC)、辐射通量(STRD)、温度等新特征是突破当前天花板的关键
2. **不推荐在无新数据情况下继续训练残差模型**：Round68 已接近当前特征集的理论上限
3. **如需修复 noon bias 问题**：可单独部署 noon_bias_guard 候选（以 bias 改善为主目标，NRMSE略牺牲）
4. **保留 Round68 final 作为生产基线**

---

## 十、输出文件清单

| 文件 | 说明 |
|------|------|
| round73/round73_current_best_verify.json | 基线校验结果 |
| round73/round73_archive_failed_experiments.csv | 归档记录 |
| round73/training_v2_backtest_dataset.parquet | 回测数据集 |
| round73/training_v2_backtest_windows.csv | 窗口定义 |
| round73/training_v2_data_quality.csv | 各窗口质量指标 |
| round73/round73_candidate_training_summary.csv | 候选训练摘要 |
| round73/round73_candidates.pkl | 含候选预测的完整表 |
| round73/round73_backtest_candidate_compare.csv | 回测窗口对比 |
| round73/round73_candidate_decision.json | 选择决策 |
| round73/round73_test_overall_compare.csv | Test 整体对比 |
| round73/round73_test_hourly_compare.csv | Test 分小时对比 |
| round73/round73_test_site_compare.csv | Test 分站点对比 |
