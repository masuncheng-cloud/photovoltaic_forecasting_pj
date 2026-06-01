# Round61 稳定基线说明

## 基线说明

Round61 是当前稳定版本。该版本综合了 Round58 的城市总量精度和 Round60 的站点稳定性保护机制：

- 城市总量 NRMSE 基本回到 Round58 水平（city_nrmse_6_19: 3.9531%）
- 变差超过 +1pp 的站点数为 0
- 含三层校准：hour_scene → site → city_total

## 关键指标（test 6-19h）

| 指标 | 值 |
|------|---:|
| city_nrmse_6_19 | 3.9531% |
| city_nrmse_10_14 | 6.2359% |
| site_mean_nrmse_6_19 | 11.4095% |
| bias_6_19 | +1.42% |
| bias_10_14 | +8.40% |
| 变差 > +1pp 站点数 | 0 |

## 预测来源

`power_pred_final` = `power_pred_round61_city_safe`

含三层后处理校准：
1. Round60 hour_scene calibrator（保守，valid 回退）
2. Round60 site calibrator（保守，valid 回退）
3. Round61 city_total calibrator（小时级，站点/小时保护）

## 回退方式

如果后续实验导致结果恶化，可回退：

```bash
# 恢复代码
git checkout round61-stable-20260601

# 恢复产物（需手动从备份目录复制）
# 产物位于: output/pv_pipeline/baselines/round61/
```

完整文件清单见 `round61_baseline_files.csv`。
