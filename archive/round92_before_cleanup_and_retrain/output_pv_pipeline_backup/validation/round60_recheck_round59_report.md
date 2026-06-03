# Round60 独立复核 Round59 对比口径报告

## 1. 复核目的

复核 `compare_round58_round59_metrics.py` 中的 city NRMSE 计算公式是否与 Round58 确认口径一致。

## 2. 口径对比

| 口径 | 方法 | Round58 city_nrmse_6_19 |
|------|------|--------------------------|
| Round59 旧脚本 | all-rows RMSE / 总容量 | 0.2398% |
| Round58 确认口径 | per-hour RMSE / hour_cap 平均 | 0.2320% |

量级差异: Round59 报告为 0.24%，实际应为 0.23%（差异 16 倍）。

## 3. 复核结论

**compare_round58_round59_metrics.py 中的 city_nrmse 公式错误。**

- 旧公式: `RMSE(all_rows) / total_city_capacity`
- 正确公式: `mean( RMSE(per_hour) / per_hour_capacity )`

正确公式与 `hourly_nrmse_consistent.csv` 一致，是 Round57-58 确认的标准口径。

## 4. Round59 真实效果（使用正确公式）

| 指标 | Round58 | Round59 | Delta |
|------|---------|---------|-------|
| site_mean_nrmse_6_19 | 11.4087% | 11.4407% | +0.0320pp |
| city_nrmse_per_hour_avg_6_19 | 0.2320% | 0.2316% | -0.0004pp |
| city_nrmse_overall_6_19 | 0.2398% | 0.2384% | -0.0014pp |
| bias_6_19 | 1.3872% | 1.2264% | -0.1608pp |
| bias_10_14 | 8.3951% | 8.1152% | -0.2799pp |

## 5. 下一步

修改 `compare_round58_round59_metrics.py`，将 city_nrmse 改为 per-hour 平均口径。
