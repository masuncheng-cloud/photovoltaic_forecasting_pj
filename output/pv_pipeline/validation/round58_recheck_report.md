# Round58 Round57 诊断口径独立复核报告
## 1. 复核结论
- **HOUR_SITE_CITY_IDENTICAL**（high）：未确认  - 证据：Round57 hour: site_mean_nrmse == city_nrmse for all rows = False- **HOUR_CITY_NRMSE_MISMATCH**（high）：未确认  - 证据：max abs diff Round57 city_nrmse vs independent recalc = 0.0000%- **HOUR_SITE_NRMSE_MISMATCH**（high）：未确认  - 证据：max abs diff Round57 site_mean vs independent recalc = 0.0000%- **MONTH_CITY_NRMSE_MISMATCH**（high）：未确认  - 证据：max abs diff Round57 monthly city vs independent recalc = 0.0000%- **MONTH_CONCLUSION_MAY_BE_WRONG**（medium）：未确认  - 证据：Round57 worst month=9, recalculated worst month=9- **MAIN_BAD_HOURS_EMPTY**（medium）：未确认  - 证据：main_bad_hours column all NaN in priority_sites- **DAYTIME_SCENE_NIGHT_OVERTRIGGER**（medium）：未确认  - 证据：daytime_scene_night flagged sites=0/68 (0%), mean scene_night_ratio_10_14=0.0- **NAN_BIAS_NEEDS_SEPARATE_CLASS**（medium）：未确认  - 证据：sites with NaN bias=5/68. Correctly classified as zero_actual_sum: True. Sites: station_id                                        risk_flags
      S003            zero_actual_sum|high_actual_zero_ratio
      S044            zero_actual_sum|high_actual_zero_ratio
      S069            zero_actual_sum|high_actual_zero_ratio
      S076 high_nrmse|zero_actual_sum|high_actual_zero_ratio
      S077            zero_actual_sum|high_actual_zero_ratio- **HOUR_METRICS_SHOULD_DIFFER**（low）：未确认  - 证据：mean abs diff between site_mean and city columns = 5.817743% (should be > 1%)
## 2. 小时级复算结果
| hour | rows | site_mean_nrmse% | city_nrmse% | bias% | P/A |
|-----|-----:|----------------:|------------:|------:|----:|
| 6 | 8296 | 4.20 | 1.03 | -33.46 | 0.6654 |
| 7 | 8296 | 5.62 | 4.04 | -61.33 | 0.3867 |
| 8 | 8296 | 7.84 | 4.08 | -21.31 | 0.7869 |
| 9 | 8296 | 11.34 | 4.66 | 1.66 | 1.0166 |
| 10 | 8296 | 14.52 | 5.90 | 8.24 | 1.0824 |
| 11 | 8296 | 16.30 | 6.42 | 8.29 | 1.0829 |
| 12 | 8296 | 16.98 | 6.43 | 8.86 | 1.0886 |
| 13 | 8296 | 16.58 | 6.55 | 10.37 | 1.1037 |
| 14 | 8296 | 14.24 | 5.89 | 5.75 | 1.0575 |
| 15 | 8296 | 10.09 | 3.58 | 1.18 | 1.0118 |
| 16 | 8296 | 6.68 | 2.11 | -2.32 | 0.9768 |
| 17 | 8296 | 4.28 | 2.11 | -43.49 | 0.5651 |
| 18 | 8296 | 4.19 | 1.32 | -28.75 | 0.7125 |
| 19 | 8296 | 3.94 | 1.24 | -27.88 | 0.7212 |

## 3. 月份复算结果
| month | rows | site_mean_nrmse% | city_nrmse% | bias% | P/A |
|-------|-----:|----------------:|------------:|------:|----:|
| 9 | 28560 | 13.96 | 5.49 | -3.36 | 0.9664 |
| 10 | 29512 | 10.68 | 4.53 | 1.66 | 1.0166 |
| 11 | 28560 | 10.38 | 4.29 | 2.82 | 1.0282 |
| 12 | 29512 | 9.00 | 3.15 | 5.36 | 1.0536 |

## 4. 场景复算结果
| scene | rows | site_mean_nrmse% | city_nrmse% | bias% | P/A |
|-------|-----:|----------------:|------------:|------:|----:|
| clear_peak | 11756 | 17.66 | 6.02 | 13.83 | 1.1383 |
| low | 32831 | 7.68 | 2.34 | -42.29 | 0.5771 |
| mid | 44695 | 11.93 | 4.86 | 11.93 | 1.1193 |
| night | 26862 | 3.94 | 1.35 | -36.23 | 0.6377 |

## 5. 处理建议
只有 exists=True 的问题才进入修复。
