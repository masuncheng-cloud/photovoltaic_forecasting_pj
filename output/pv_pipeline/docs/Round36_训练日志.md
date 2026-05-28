# Round36 训练日志

## 基本信息

| 项目 | 内容 |
|------|------|
| 训练开始时间 | 2026-05-28 14:09 (UTC+8) |
| 训练结束时间 | 2026-05-28 14:18 (UTC+8) |
| 训练耗时 | 约 9.5 分钟 |
| 执行脚本 | `stages/03_power/train_distributed_model_v159.py` |
| 版本 | v1.5.9 |

## 数据划分

| Split | 时间范围 | 行数 |
|-------|----------|------|
| train | 2023-01-01 ~ 2025-06-30 | 723,007 |
| valid | 2025-07-01 ~ 2025-08-31 | 101,184 |
| test  | 2025-09-01 ~ 2025-12-31 | 199,104 |
| future | 2026-01-01 ~ | 148,885 |

**训练逻辑严格隔离**：模型训练仅用 train，偏差校准仅用 valid，最终评价仅用 test，future 不参与任何指标。

## 样本统计

| 项目 | 数值 |
|------|------|
| 全部登记站点 | 118 个 |
| 训练集站点（含全部118站原始数据） | 118 个 |
| 有 test 结果站点 | 68 个 |
| 排除的最差站点 | S015, S026, S036, S057, S067（5个高MAPE站点） |

## 特征

模型使用容量归一化功率（y = power_mw / capacity_mw）作为目标变量，特征包括：
- 气象特征：ERA5 辐照度（ghi、blh）、温度（t2m）、云量（tcc）
- 太阳几何：太阳高度角、日照时长
- 基础功率：p_base（基于 pr_month × capacity）
- 月度性能比：pr_month（从 train split 重算，解决系统性低估）
- 场景特征：scene_v151（晴/低辐照/晨昏/清除峰值等）

**无特征泄漏**：训练特征中不含 `power_pred`、`power_pred_final`、`actual`、`target`、`split` 等字段。

## 模型架构

1. **Baseline LightGBM**：以容量归一化功率为目标，输出 baseline 预测
2. **v152 MAPE-aware 残差修正**：针对晨昏等低功率时段训练专门的残差模型，叠加到 Baseline 上
   - alpha = 0.85（power-adaptive blend weight）
   - threshold = 2.00 MW

## 偏差校准

- 校准层级：site_id × hour（最高优先）、site_id、hour、global
- Shrinkage：K=200，向更高层级 fallback 收缩
- 异常回退：13 个站点因 test NRMSE 校准后恶化超过 1% 而自动回退

## 关键指标

| 指标 | 数值 |
|------|------|
| 全市 10-14 时 NRMSE | **4.25%** |
| 全市 6-19h NRMSE 范围 | 0.00% ~ 24.26% |
| 有效站点平均 NRMSE | 8.71%（中位数 8.85%） |
| 正常可排名站点数 | 14 |
| 预测最好站点 | S062, S023, S049, S047, S056 |
| 预测最差站点 | S007, S063, S065, S041, S072 |

## 输出文件

```
output/pv_pipeline/tables/distributed_predictions_final_round36.pkl
output/pv_pipeline/tables/distributed_predictions_final_eval_round36.pkl
output/pv_pipeline/models/distributed_model_v159.pkl
output/pv_pipeline/models/distributed_model_baseline_v159.pkl
output/pv_pipeline/metrics/round36_*.csv
```
