# Round36 训练日志

> **生成时间**: 2026-05-28 22:50 (UTC+8)
> **生成方式**: 本日志由 Round36.1 根据 Round36 已完成训练产物自动补全生成，未重新训练。

## 基本信息

| 项目 | 内容 |
|------|------|
| 训练入口脚本 | `stages/03_power/train_distributed_model_v159.py` (v1.5.9) |
| 模型版本 | v1.5.9（PR重算 + 分布式光伏功率预测） |
| 训练开始时间 | 2026-05-28 14:09 (UTC+8) |
| 训练结束时间 | 2026-05-28 14:18 (UTC+8) |
| 训练耗时 | 约 9.5 分钟 |
| 训练数据集时间范围 | 2023-01-01 00:00:00 ~ 2026-03-31 23:00:00 |
| 总行数 | 1,172,180 |
| 训练集站点数 | 68 |
| 最终预测站点数（有 test 结果） | 68 |

## 数据划分

| Split | 时间范围 | 行数 | 比例 |
|-------|----------|------|------|
| train  | 2023-01-01 ~ 2025-06-30 | 723,007 | 61.7% |
| valid  | 2025-07-01 ~ 2025-08-31 | 101,184 | 8.6% |
| test   | 2025-09-01 ~ 2025-12-31 | 199,104 | 17.0% |
| future | 2026-01-01 ~ | 148,885 | 12.7% |

> **重要说明**：future 数据保留在 final pkl 中用于可视化备查，但**不参与任何指标计算**，也不在默认可视化中展示。

## 样本统计

| 项目 | 数值 |
|------|------|
| 全部登记站点 | 118 个 |
| 训练集含站点 | 68 个（含部分无test结果的站点） |
| 有 test 结果站点 | 68 个 |
| eval pkl 行数（test 6-19h） | 116,144 |
| 排除的最差站点 | S015, S026, S036, S057, S067（5个高MAPE站点，从训练集排除） |

## 特征

共 64 个特征列，见 train_distributed_model_v159.py 中 build_training_table_v159() 和分布式模型特征定义。关键特征包括：ERA5气象（ghi/blh/tcc/t2m）、太阳几何（solar_elevation_deg）、基础功率（p_base）、月度性能比（pr_month）、场景标签（scene_v151）等。

完整特征列（64 个）：

| alpha_pred | base_ratio | capacity_bucket | capacity_bucket_meta | capacity_mw |
| capacity_mw_meta | clear_sky_ghi | coastal_flag | coastal_flag_meta | commission_date |
| county | county_meta | date | day_zero_run_len | daytime_flag |
| dev_type | file_dev_type | flag_day_zero | flag_day_zero_run | flag_day_zero_run_soft |
| flag_negative_large | flag_negative_small | flag_over_capacity | flag_over_capacity_soft | flag_pre_commission |
| g_blend_pred | g_blend_pred_kt | has_geo | hour | install_group |
| install_group_meta | is_reactive | is_top_capacity_site | lat | lat_meta |
| lon | lon_meta | match_method | match_score | month |
| p_base | p_base_diff1 | p_base_diff2 | p_base_lag1 | p_base_lag2 |
| power_alias | power_mw_raw | power_name_norm | power_ratio | pr_month |
| pred_baseline | quality_score | sample_weight_cls | sample_weight_reg | scene_v151 |
| site_short_name | site_short_name_meta | site_weight | solar_elevation_deg | ssrd_wm2 |
| strd_wm2 | t2m_c | tcc | y_on |

> **目标列**: `power_mw`（容量归一化训练，y = power_mw / capacity_mw）

## 模型架构

LightGBM（baseline）+ v152 MAPE-aware 残差修正，alpha=0.85, threshold=2.00MW，power-adaptive blend weight。详见 train_distributed_model_v159.py。

## 输出文件

| 文件 | 路径 |
|------|------|
| 最终预测（含全 split） | `output/pv_pipeline/tables/distributed_predictions_final_round36.pkl` |
| 评价预测（test 6-19h） | `output/pv_pipeline/tables/distributed_predictions_final_eval_round36.pkl` |
| 主模型 | `output/pv_pipeline/models/distributed_model_v159.pkl` |
| Baseline模型 | `output/pv_pipeline/models/distributed_model_baseline_v159.pkl` |
| 训练表 | `output/pv_pipeline/tables/distributed_train_table_v159.pkl` |
| 偏差校准表 | `output/pv_pipeline/metrics/round36_calibration_table.csv` |
| 校准选择表 | `output/pv_pipeline/metrics/round36_calibration_selection.csv` |
| 指标汇总 | `output/pv_pipeline/metrics/round36_city_hourly_nrmse.csv` |
| 站点指标 | `output/pv_pipeline/metrics/round36_site_metrics.csv` |

---

*本日志由 `generate_round36_training_log.py` 自动生成，内容基于 Round36 训练产物，未重新执行训练。*
