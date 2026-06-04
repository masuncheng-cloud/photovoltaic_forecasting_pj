# 项目结构审计报告

生成时间: 2026-06-04 11:55:34

| 描述 | 路径 | 类型 | 必需 | 状态 | 说明 |
|------|------|------|------|------|------|
| 数据根目录 | `data/` | dir | 是 | PASS | OK |
| 功率数据目录 | `data/power_data/` | dir | 是 | PASS | OK |
| 2023 年数据 | `data/2023/` | dir | 是 | PASS | OK |
| 2023 瞬时气象文件 | `data/2023/data_stream-oper_stepType-instant.nc` | file | 是 | PASS | OK |
| 2023 累积气象文件 | `data/2023/data_stream-oper_stepType-accum.nc` | file | 是 | PASS | OK |
| 2024 年数据 | `data/2024/` | dir | 是 | PASS | OK |
| 2024 瞬时气象文件 | `data/2024/data_stream-oper_stepType-instant.nc` | file | 是 | PASS | OK |
| 2024 累积气象文件 | `data/2024/data_stream-oper_stepType-accum.nc` | file | 是 | PASS | OK |
| 2025 年数据 | `data/2025/` | dir | 是 | PASS | OK |
| 2025 瞬时气象文件 | `data/2025/data_stream-oper_stepType-instant.nc` | file | 是 | PASS | OK |
| 2025 累积气象文件 | `data/2025/data_stream-oper_stepType-accum.nc` | file | 是 | PASS | OK |
| 主流程入口 | `scripts/run_full_pipeline.py` | file | 是 | PASS | OK |
| Dashboard 导出脚本 | `scripts/export_interactive_dashboard_data.py` | file | 是 | PASS | OK |
| Dashboard 回归检查 | `scripts/dashboard_regression_check.py` | file | 是 | PASS | OK |
| Dashboard 预测值校验 | `scripts/check_dashboard_prediction_values.py` | file | 是 | PASS | OK |
| 训练后审计 | `scripts/posttrain_validation.py` | file | 是 | PASS | OK |
| 源码目录（可选） | `src/pv_forecasting/` | dir | 否 | PASS | OK |
| Stages 目录（可选） | `stages/` | dir | 否 | PASS | OK |
| Pipeline 配置（可选） | `configs/pipeline.yaml` | file | 否 | PASS | OK |

汇总: 19 PASS / 0 WARN / 0 FAIL
