# 项目修改历史

本文档记录光伏预测项目的所有重要修改，方便日后查阅。

---

## 2026-05-17: 完整修复 (本次整理)

### 修复内容

#### P0 修复（必须）

**P0-1: 修复 `fix_hourly_bias.py` 测试集泄漏**
- 问题: 脚本在测试集 (2025-07后) 上选择修正策略，导致指标偏乐观
- 修复: 拆分为 fit/apply 两阶段，策略选择仅用验证集
- 修改文件: `scripts/fix_hourly_bias.py`
- 新增输出: `metrics/hourly_strategy_valid_selected.csv`
- 约束: `selection_split` 字段必须为 `valid`

**P0-2: 重建 `distributed_predictions_fixed.pkl`**
- 问题: 缺少 `split` 字段，无法区分 train/valid/test
- 修复: 添加 split 划分和正确的 scene_label
- 修改文件: `scripts/rebuild_fixed_predictions.py`
- 新增字段: `split`, `scene_label`, `power_pred_original`, `power_pred_site_fixed`
- 数据划分: train (2025-07前), valid (2025-07~08), test (2025-09后)

**P0-3: 修复 `train_fixed.py` 完整流程**
- 问题: 缺少对修复脚本的调用
- 修复: 扩展调用链，包含所有修复脚本
- 修改文件: `scripts/train_fixed.py`
- 执行顺序: 训练 -> 诊断 -> 修正 -> 评估

**P0-4: 修复 `evaluate_fixed_predictions.py` 空指标**
- 问题: `distributed_metrics_fixed.csv` 为空
- 修复: 修复 key 对齐问题和场景划分逻辑
- 修改文件: `scripts/evaluate_fixed_predictions.py`
- 场景列表: dawn/morning/midday/afternoon/dusk/night

#### P1 修复（验收前必须）

**P1-1: 校准保护真正生效**
- 问题: 校准机制存在但未真正接入
- 修复: 生成每站点校准状态报告
- 修改文件: `scripts/generate_calibration_report.py`
- 参数约束: a ∈ [0.95, 1.30], b ∈ [-0.10, 0.20]
- 启用条件: 验证集改善 >= 2%
- 结果: 17/56 站点启用校准

**P1-2: 黎明/黄昏专项评估**
- 问题: 6点、19点误差偏高未单独分析
- 修复: 生成专项评估报告
- 修改文件: `scripts/evaluate_dawn_dusk.py`
- 新增输出: `metrics/dawn_dusk_error_before_after.csv`

**P1-3: 生成验证报告**
- 修改文件: `output/pv_pipeline/docs/fixed_pipeline_validation.md`

#### P2 增强

**P2-1: 生成组件参数表**
- 修改文件: `scripts/generate_site_parameters.py`
- 新增输出: `metrics/site_parameter_completeness.csv`
- 参数来源: rooftop_default (67), ground_default (18), unknown_default (33)

**P2-2: 生成时间对齐文档**
- 修改文件: `output/pv_pipeline/docs/time_convention.md`
- 内容: 时间戳含义、UTC/CST转换、峰值偏移诊断

**P2-3: 整理项目文件清单**
- 修改文件: `output/pv_pipeline/docs/项目文件清单.md`

### 关键结果

| 指标 | 修复前 | 修复后 | 改善 |
|------|--------|--------|------|
| 全市相对误差 | 20.6% | 7.7% | +12.9% |
| 傍晚 (17-19) | 59.7% | 15.5% | +44.2% |
| 下午 (15-16) | 21.6% | 5.0% | +16.6% |
| 中午 (10-14) | 13.0% | 2.7% | +10.3% |

### 新增脚本

| 脚本 | 功能 |
|------|------|
| `scripts/train_fixed.py` | 修复版训练入口 |
| `scripts/fix_hourly_bias.py` | 无泄漏偏差修正 |
| `scripts/rebuild_fixed_predictions.py` | 重建预测表 |
| `scripts/generate_calibration_report.py` | 校准报告 |
| `scripts/evaluate_dawn_dusk.py` | 黎明/黄昏评估 |
| `scripts/generate_site_parameters.py` | 组件参数表 |

---

## 2026-05-15: v159 版本修复

### 主要修改

**重构 per-site calibration**
- 文件: `src/pv_forecasting/tasks/distributed_power_v152.py`
- 修复: 重构校准逻辑，添加安全约束
- 参数: CAL_A_MIN=0.95, CAL_A_MAX=1.30, CAL_B_MIN=-0.10, CAL_B_MAX=0.20
- 阈值: CAL_IMPROVEMENT_THRESHOLD=0.98

### 遗留问题

1. 测试集调参风险未解决
2. train_fixed.py 调用链不完整
3. 场景评估全为 night

---

## 2026-05-12: 初始版本

### 初始功能

1. 数据层 (Stage 1): 站点主表、气象数据清洗
2. 辐照度层 (Stage 2): 逆模型、辐照度融合
3. 功率层 (Stage 3): 分布式功率预测
4. 评估层 (Stage 4): 多层级评估

### 初始问题

1. 全市逐小时相对误差偏高 (35.3%)
2. calibration 层系统性压缩
3. 早晚 ramp 时段误差大

---

## 清理的冗余文件

| 文件 | 原因 |
|------|------|
| `src/pv_forecasting/tasks/distributed_model.py` | 被 v152 替代 |
| `src/pv_forecasting/tasks/distributed_power_v151.py` | 被 v152 替代 |
| `stages/03_power/train_distributed_model.py` | 被 v159 替代 |
| `scripts/train.py` | 被 train_fixed.py 替代 |
| `scripts/all.py` | 用途不明 |
| `scripts/dashboard.py` | 用途不明 |

---

## 使用说明

### 完整训练
```bash
python scripts/train_fixed.py
```

### 仅运行评估
```bash
python scripts/evaluate_fixed_predictions.py
```

### 生成报告
```bash
python scripts/generate_calibration_report.py
python scripts/generate_site_parameters.py
python scripts/evaluate_dawn_dusk.py
```

---

**维护说明**: 每次修改项目后，请在此文件添加相应记录。
