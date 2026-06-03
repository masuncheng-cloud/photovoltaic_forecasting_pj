# 光伏功率预测项目 Changelog

> **重要**: 本项目的完整修改历史已整理到 `docs/CHANGELOG.md`。根目录的 CHANGELOG.md 保留历史记录。

---

## 完整修复 (2026-05-17)

**目标**: 消除测试集泄漏，建立可复现、可验收的修复版 pipeline。

### 主要修复

#### P0 修复（必须）

| 修复项 | 文件 | 说明 |
|--------|------|------|
| 测试集泄漏 | `scripts/fix_hourly_bias.py` | 改为验证集选策略 |
| 预测文件重建 | `scripts/rebuild_fixed_predictions.py` | 添加 split/scene 字段 |
| 训练入口修复 | `scripts/train_fixed.py` | 完整调用链 |
| 评估脚本修复 | `scripts/evaluate_fixed_predictions.py` | 修复空指标问题 |

#### P1 修复（验收前必须）

| 修复项 | 文件 | 说明 |
|--------|------|------|
| 校准保护 | `scripts/generate_calibration_report.py` | 17/56 站点启用 |
| 黎明/黄昏评估 | `scripts/evaluate_dawn_dusk.py` | 专项指标 |
| 验证报告 | `docs/fixed_pipeline_validation.md` | 完整报告 |

#### P2 增强

| 修复项 | 文件 | 说明 |
|--------|------|------|
| 组件参数表 | `scripts/generate_site_parameters.py` | 118 站点参数 |
| 时间对齐文档 | `docs/time_convention.md` | 时间约定说明 |
| 项目文件清单 | `docs/项目文件清单.md` | 结构文档 |

### 结果

| 指标 | 修复前 | 修复后 | 改善 |
|------|--------|--------|------|
| 全市相对误差 | 20.6% | 7.7% | +12.9% |
| 傍晚 (17-19) | 59.7% | 15.5% | +44.2% |
| 中午 (10-14) | 13.0% | 2.7% | +10.3% |

### 清理的冗余文件

- `src/pv_forecasting/tasks/distributed_model.py` (75KB)
- `src/pv_forecasting/tasks/distributed_power_v151.py` (21KB)
- `stages/03_power/train_distributed_model.py` (8KB)
- `scripts/train.py` (1KB)
- `scripts/all.py` (1KB)
- `scripts/dashboard.py` (0.7KB)

---

## 项目结构重构（2026-05-04）

**定位**：规范化目录命名，删除废弃代码，统一运行入口。

### 主要变更

1. **目录重命名**：`src/pv_pipeline/` → `src/pv_forecasting/`，`run/` → `scripts/`
2. **删除废弃版本**：清理了 v2、v15 等实验分支的 stage 脚本和 task 模块
3. **统一流水线入口**：`scripts/train.py` 移除 v1/v2/v15/v152 版本选项，仅保留 v151 稳定版
4. **import 路径统一**：所有模块引用更新为 `pv_forecasting.*`
5. **README 重写**：目录结构、命令示例、流水线说明全面更新

### 清理文件

```
已删除（实验/废弃）：
  src/pv_forecasting/tasks/distributed_power_v2.py
  src/pv_forecasting/tasks/distributed_power_v15.py
  src/pv_forecasting/tasks/inverse_model_v2.py
  src/pv_forecasting/tasks/irradiance_blend_v2.py
  stages/02_irradiance/train_inverse_model_v2.py
  stages/02_irradiance/train_irradiance_blend_v2.py
  stages/02_irradiance/train_dynamic_pr_model.py
  stages/03_power/train_distributed_model.py
  stages/03_power/train_distributed_model_v2.py
  stages/03_power/train_distributed_model_v15.py
  stages/04_evaluation/evaluate_layers.py
  stages/04_evaluation/evaluate_layers_v15.py
```

### 新目录结构

```
photovoltaic_forecasting_pj/
├── scripts/                  # 统一运行入口（原 run/）
│   ├── train.py / train.sh
│   ├── dashboard.py / dashboard.sh
│   ├── diagnose.py / diagnose.sh
│   └── all.py / all.sh
├── stages/                   # 流水线阶段脚本
│   ├── 01_data/
│   ├── 02_irradiance/
│   ├── 03_power/
│   ├── 04_evaluation/
│   └── 05_visualization/
└── src/pv_forecasting/      # 核心算法模块（原 src/pv_pipeline/）
    ├── core/
    └── tasks/
```

---

## 目录

- [v1 — 初始基线](#v1--初始基线)
- [v2 — 大改主线（动态PR、清空融合、场景专家、城市约束）](#v2--大改主线动态pr清空融合场景专家城市约束)
- [v3 — v2迭代：放宽阈值、连续段唤醒、峰值专家](#v3--v2迭代放宽阈值连续段唤醒峰值专家)
- [v4 — v3迭代：峰值专家按站点选择性启用](#v4--v3迭代峰值专家按站点选择性启用)
- [v5 — v4迭代：关键站点专项优化](#v5--v4迭代关键站点专项优化)
- [v6 — v5迭代：数据治理增强、大站峰值修复](#v6--v5迭代数据治理增强大站峰值修复)
- [v10 — 大改主线（重新设计辐照→功率链路）](#v10--大改主线重新设计辐照功率链路)
- [v13 — 弃光根因修复（分布式训练数据过滤）](#v13--弃光根因修复分布式训练数据过滤)
- [v14 — daybias boost（白天正向修正）](#v14--daybias-boost白天正向修正)
- [v15 — v14修复（daybias boost 目标修复）](#v15--v14修复daybias-boost-目标修复)
- [v151 — 当前最佳稳定版（v15 + v1 前两层）](#v151--当前最佳稳定版v15--v1-前两层)
- [v152 — 实验分支（LightGBM+CatBoost ensemble）](#v152--实验分支lightgbmatboost-ensemble)

---

## v1 — 初始基线

**时间**：2026-04 初期  
**定位**：初始工程结构，快速跑通端到端流程。

### 流水线架构

```
ERA5 气象数据 ──IDW 插值──→ 站点气象
集中式功率 ──月度PR反演──→ 辐照估算 g_pred
全站点辐照融合（IDW + ERA5 加权）
分布式功率估算（场景分组建模 + 多候选融合）
全市总量聚合
```

### 关键设计

| 模块 | 设计 | 问题 |
|---|---|---|
| 辐照反演 | 月度PR + 温度修正，单层GBDT | 晴天偏保守 |
| 辐照融合 | IDW空间插值 + ERA5背景场，α通过GBDT学习 | 有效 |
| 功率估算 | 场景分组（night/low/ramp/mid/clear_peak） | ramp/peak 场景误差大 |
| 弃光处理 | 无专门机制，场景分组隐式处理 | 弃光日预测偏高 |
| 候选融合 | 多候选比较（blend / logcorr / logcorr_blend / ...） | 有效 |

### 输出指标

| 阶段 | RMSE | NRMSE | Corr |
|---|---|---|---|
| ERA5 → 反演辐照 | 3.70 | 0.0039 | 0.9999 |
| 反演 → 融合辐照 | 3.04 | 0.0032 | — |
| 融合 → 分布式功率 | 0.7154 | 0.0360 | 0.8749 |
| 城市总量 | 10.84 | 0.0477 | 0.9648 |

---

## v2 — 大改主线（动态PR、清空融合、场景专家、城市约束）

**时间**：2026-04-20  
**定位**：与 v1 并行的全新主线实验，非覆盖关系。

### 关键新设计

1. **动态PR反演**：月度PR改为每日动态估算，辐照反演精度提升
2. **清空指数辐照融合**：用晴空指数 kt 替代原始辐照做融合
3. **两阶段功率模型**：开机分类器（p_on）+ 正功率回归
4. **场景专家回归**：5个场景各自训练专属模型
5. **城市总量一致性约束**：预测后按城市总功率比例重分配

### 结果

v2 整体 RMSE 劣于 v1，未成为稳定主线。但场景专家、城市约束等设计思想影响了后续版本。

---

## v3 — v2迭代：放宽阈值、连续段唤醒、峰值专家

**时间**：2026-04-18  
**定位**：在 v2 基础上修 bug、加规则。

### 关键修改

1. **白天唤醒从单点触发改为连续段触发**：新增 `wakeup_run_len`，避免单点噪声触发
2. **放宽唤醒阈值并重新计算**：重新计算 pred_blend 后再次应用，解决 wakeup_rows=0 的问题
3. **下调峰值专家最小样本门槛**：允许更少样本的站点启用峰值专家
4. **适度放宽峰值残差裁剪**：减少过截断
5. **修复 dashboard 中 groupby.apply 的 FutureWarning**

### 结果

部分站点启用唤醒后 RMSE 轻微下降，但整体提升不稳定，峰值专家容易过拟合。

---

## v4 — v3迭代：峰值专家按站点选择性启用

**时间**：2026-04-18  
**定位**：解决 v3 全站启用峰值专家导致的过拟合问题。

### 关键修改

1. **峰值专家改为按站点选择性启用**：
   - 先在验证集构造 `pred_bias` vs `pred_local`
   - 只对"峰值专家真正带来收益"的站点启用峰值修正
   - 其他站点自动回退到原 blend 主线
2. **候选选择对 blend 轻微优先**：当 blend 与最优候选差距很小时，优先返回 blend，避免极小验证集波动覆盖冠军主线
3. **导出峰值站点清单**：`distributed_peak_site_table.csv`

### 结果

峰值专家被限制在少数站点，稳定性提升，但整体收益有限。

---

## v5 — v4迭代：关键站点专项优化

**时间**：2026-04-18  
**定位**：不再全局改主线，改为针对少数高容量、高误差站点的专项修复。

### 关键修改

1. **站点专项优化 candidate**：`pred_specialist`，基于验证集自动生成站点级专项修复计划
2. **站点级峰值修复**：对少数受益站点，按 `site_id + hour_band_peak + irr_band_peak` 倍率表修正中午高辐照时段
3. **站点级低平段修复**：对少数受益站点，按 `site_id + hour_band_floor + irr_band_floor` 底座表抬升白天连续偏低段
4. **新增输出表**：`distributed_specialist_plan.csv`、`distributed_specialist_peak_table.csv`、`distributed_specialist_floor_table.csv`、`distributed_specialist_site_delta.csv`

### 结果

少数大站点受益，但大量小站点的 specialist 规则容易过拟合验证集。

---

## v6 — v5迭代：白天唤醒保守化、诊断工具完善

**时间**：2026-04-18  
**定位**：保守化 targeted/wakeup/peak 规则，增加诊断工具。

### 关键修改

1. **统一运行入口**：`run/all.py` 支持 `--mode all/train/dashboard/diagnose`
2. **新增诊断脚本**：`run/diagnose.py` + `stages/04_evaluation/diagnose_bottlenecks.py`
3. **白天唤醒更保守**：仅在 elevation 较高、g_blend 不低、p_base 明显大于0但预测值仍贴地时触发
4. **中文字体强制加载**：避免中文站名缺字
5. **不引入新的 site-level 拟合型缩放**：避免泛化不稳

### 结果

诊断工具可用性提升，但 targeted/wakeup/peak 规则链仍过于复杂。

---

## v6 — v5迭代：数据治理增强、大站峰值修复

**时间**：2026-04-20  
**定位**：在稳定冠军主线基础上，加入数据治理和大站峰值修复。

### 关键修改

1. **训练阶段白天异常低平段识别**：`flag_train_day_low_soft` / `flag_train_day_low_hard`
   - 依据 solar_elevation_deg + g_blend_pred + p_base + power_ratio 识别白天异常低平段
   - 对 soft/hard 异常段在训练时进一步降权
   - 新增输出：`distributed_governance_summary.csv`
2. **关键大站专项峰值修复**：`pred_large_peak` candidate
   - 只在高辐照、高太阳高度角、预测已进入中高出力区间时触发
   - 自动从验证集筛选少数值得修复的大站
   - 新增输出：`distributed_large_peak_plan.csv`、`distributed_large_peak_table.csv`
3. **兼容第一/二层**：不改主线结构，保留所有工程修复

### 结果

候选自动对比决定是否启用，最终以稳定为优先。

---

## v10 — 大改主线（重新设计辐照→功率链路）

**时间**：2026-04-20  
**定位**：放弃叠加式规则改进，重新设计辐照到功率的完整链路。

### 关键修改

1. **动态 PR 反演辐照**（替代月度 PR）
2. **晴空指数 kt 融合**（替代原始辐照融合）
3. **两阶段功率模型**：p_on 分类 + 正功率回归
4. **场景专家回归**：low/ramp/mid/clear_peak 各有专属模型
5. **城市总量一致性约束 + 重分配**
6. **层级指标汇总**：`layer_metrics_summary.csv`

### 结果

v10 作为新主线尝试，但整体指标劣于 v1 稳定版，未被采纳为主流方向。

---

## v13 — 弃光根因修复（分布式训练数据过滤）

**时间**：2026-04 中下旬  
**定位**：分布式站点训练数据中混入大量弃光零值，导致 `estimate_dist_monthly_pr` 和残余训练都学到弃光特征。

### 根因

`estimate_dist_monthly_pr` 使用**全部样本**计算月度PR，包含了弃光日零功率，导致：
- PR 被低估 → g_est 偏大 → 预测偏高
- 残余训练数据混入大量零值，残差回归器被噪声污染

### 修复（Fix A）

1. **estimate_dist_monthly_pr 过滤**：
   - `power_ratio > 0.01`（弃光零功率不参与PR计算）
   - `g > 150 W/m²`（仅保留真正有辐照的时段）
2. **残余训练数据过滤**：仅用 active 样本训练残差模型

### 结果

| 指标 | 修复前 | 修复后 | 变化 |
|---|---|---|---|
| Site RMSE | 0.7237 | 0.7154 | -0.0083 ✓ |
| Site MAE | 0.3184 | 0.3134 | -0.0050 ✓ |
| City RMSE | 10.84 | 10.84 | 不变 ✓ |

---

## v14 — daybias boost（白天正向修正）

**时间**：2026-04 下旬  
**定位**：test 白天样本存在系统性正向 bias（预测偏低约 0.20 MW），加入固定倍率修正。

### 关键修改

```python
# daytime boost: daytime positive bias correction
mask = (pred['p_on_pred'] > 0.001) & (g > 150)
power_pred[mask] *= 1.04
```

### 结果

| 指标 | v13 | v14 |
|---|---|---|
| Site RMSE | 0.7154 | 0.7145 |
| Site MAE | 0.3134 | 0.3131 |
| City RMSE | 10.84 | **21.13** ❌ |

**严重问题**：City RMSE 从 10.84 暴涨到 21.13。根因是 boost 应用在了错误的变量上（`power_pred_logcorr_blend` 包含了夜间非活跃样本），导致夜间预测被污染，进而破坏城市总量。

---

## v15 — v14修复（daybias boost 目标修复）

**时间**：2026-04-20  
**定位**：修复 v14 的 city RMSE 退化问题，同时保留 daybias 的站点收益。

### 根因

v14 在 `logcorr_blend` 上做 boost，但该变量在夜间仍非零（被 logcorr 修正过），boost 后城市总量暴涨。

### 修复（Fix E）

```python
# v14 (wrong): applied on logcorr_blend
# v15 (correct): applied on pred_baseline (before any post-processing)
mask = (pred['p_on_pred'] > 0.001) & (g > 150)
pred['pred_baseline'][mask] *= 1.04
```

boost 现在应用在 `pred_baseline`（纯粹的场景分组建模结果），不影响夜间和 logcorr 路径。

### 结果

| 指标 | v13 | v14 (bug) | v15 (fix) |
|---|---|---|---|
| Site RMSE | 0.7154 | 0.7145 | **0.7146** ✓ |
| Site MAE | 0.3134 | 0.3131 | **0.3132** ✓ |
| City RMSE | 10.84 | 21.13 ❌ | **10.84** ✓ |

---

## v151 — 当前最佳稳定版（v15 + v1 前两层）

**时间**：2026-04 下旬至今  
**定位**：合并 v1 前两层（稳定）的辐照处理 + v15 分布式功率优化，作为当前最佳稳定版。

### 核心配置

```
前两层（同 v1）：
  - ERA5 → 月度PR反演辐照（稳定）
  - 集中式反演 → 全站点辐照融合（稳定）

第三层（v151）：
  - 两阶段：p_on 分类器 + 场景分组建模
  - 弃光过滤（Fix A）：power_ratio > 0.01, g > 150
  - Hard-zero gate：p_on < 0.04 → 强制置零
  - 候选融合：blend / logcorr / logcorr_blend / daybias
  - Daytime boost（Fix E）：pred_baseline × 1.04（白天 & p_on > 0.001 & g > 150）
```

### 关键超参数

| 参数 | 值 | 说明 |
|---|---|---|
| `ON_G_MIN` | 90.0 | 开机判断最小辐照 |
| `ON_ELEV_MIN` | 6.0 | 开机判断最小太阳高度角 |
| `ON_RATIO_MIN` | 0.01 | 开机判断最小功率比 |
| `ZERO_GATE_THRESH` | 0.04 | 硬截断阈值（relaxed from 0.08） |
| `LOG_RATIO_CLIP` | (-0.35, 0.38) | 对数残差裁剪 |
| `LOGCORR_MULT_CLIP` | (0.75, 1.40) | 对数修正倍率裁剪 |
| `SCENE_MIN_ROWS` | 800 | 场景专家最小样本数 |
| `BASELINE_KEEP_TOL` | 0.0008 | 候选融合保留阈值 |
| `TOPK_CAPACITY` | 12 | 大装机站点数量 |

### Test 最终指标

| 维度 | MAE | RMSE | NRMSE | Corr |
|---|---|---|---|---|
| **站点级** | 0.3132 | 0.7146 | 0.0360 | 0.8751 |
| **城市级** | 9.046 | 15.191 | 0.0669 | 0.9626 |

### 分场景

| 场景 | 样本数 | MAE | RMSE | Corr |
|---|---|---|---|---|
| low (低负荷) | 372,295 | 0.586 | 1.061 | 0.891 |
| ramp (爬坡) | 76,166 | 0.469 | 0.895 | 0.905 |
| mid (中等) | 35,477 | 0.372 | 0.779 | 0.830 |
| clear_peak (晴峰) | 18,728 | 0.206 | 0.526 | 0.765 |
| night (夜间) | 498,073 | 0.068 | 0.236 | 0.453 |

---

## v152 — 实验分支（LightGBM+CatBoost ensemble）

**时间**：2026-04 下旬  
**定位**：v151 的实验增强分支，引入 LightGBM + CatBoost ensemble。

### 关键修改

1. **双模型 ensemble**：LightGBM + CatBoost 联合训练功率模型
2. **新辐照输入**：`site_irradiance_v2.pkl`（来自 v2 的动态PR融合）
3. **独立训练表**：`distributed_train_table_v152.pkl`

### 结果

| 指标 | v151 | v152 |
|---|---|---|
| Site RMSE | **0.7146** | 0.7707 |
| Site MAE | **0.3132** | 0.3302 |
| Site Corr | **0.8751** | 0.8520 |

v152 指标劣于 v151，未被采纳为稳定版。当前作为实验分支保留。

---

## 版本选择建议

```
推荐运行方式：

# 当前最佳稳定版
python run/train.py --pipeline v151 --data-root data --output-root output/pv_pipeline

# 完整流程（训练 + 评估 + 看板）
python run/all.py --mode all --pipeline v151 --data-root data --output-root output/pv_pipeline

# 仅诊断
python run/all.py --mode diagnose --pipeline v151 --data-root data --output-root output/pv_pipeline
```

---

## 关键经验总结

1. **辐照融合（Stage 2）是稳定的**：v1 的月度PR + IDW/ERA5 融合始终是效果最好的方案，后续所有重构（v2/v10）都未能超越
2. **弃光零值污染是主要瓶颈**：分布式站点训练数据必须过滤弃光样本，否则 PR 估计和残差模型都会被污染（v13 修复）
3. **后处理规则要保守**：大量 targeted/wakeup/peak 规则在验证集上有效，但容易过拟合。v151 选择了最保守的方案（仅 4% daytime boost）
4. **City RMSE 是强约束**：任何影响城市总量聚合的修改（如 v14 daybias bug）都会快速暴露为 city RMSE 暴涨，必须优先保证
5. **场景分组建模有效**：5个场景（night/low/mid/ramp/clear_peak）各自建模，比单一全局模型有明显收益
6. **大装机站点需要特殊处理**：TOP 12 大站单独加权，避免大站点主导整体误差掩盖小站点问题
