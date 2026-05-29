# Round36 可视化预测值一致性检查报告
**生成时间**: 2026-05-28 22:xx
**检查口径**: split != 'future' 且 hour in 6..19

## 总体结果
| 指标 | 值 |
||------|
| 总站点数 | 68 |
| PASS | 0 |
| FAIL | 68 |
| WARN | 0 |
| 最大 actual 误差 | 0.00e+00 |
| 最大 pred 误差 | 1.47e+01 |
| 最大 capacity 误差 | 0.00e+00 |

## 逐站点详情
| site_id | n_json | n_pkl_6_19 | n_matched | count_ok | max_diff_actual | max_diff_pred | status | message |
|----------|--------|-------------|-----------|----------|-----------------|---------------|--------|---------|
| S002 | 3439 | 3439 | 3439 | ✓ | 0.00e+00 | 1.05e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.05e+00, cap_diff=0.00e+00, count_ok=True |
| S003 | 11938 | 11938 | 11938 | ✓ | 0.00e+00 | 2.02e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=2.02e+00, cap_diff=0.00e+00, count_ok=True |
| S004 | 3519 | 3519 | 3519 | ✓ | 0.00e+00 | 8.99e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=8.99e-01, cap_diff=0.00e+00, count_ok=True |
| S006 | 3461 | 3461 | 3461 | ✓ | 0.00e+00 | 8.97e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=8.97e-01, cap_diff=0.00e+00, count_ok=True |
| S007 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 5.64e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=5.64e+00, cap_diff=0.00e+00, count_ok=True |
| S008 | 3844 | 3844 | 3844 | ✓ | 0.00e+00 | 8.35e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=8.35e-01, cap_diff=0.00e+00, count_ok=True |
| S009 | 6115 | 6115 | 6115 | ✓ | 0.00e+00 | 4.27e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=4.27e+00, cap_diff=0.00e+00, count_ok=True |
| S010 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 5.36e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=5.36e-01, cap_diff=0.00e+00, count_ok=True |
| S011 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 6.72e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=6.72e-01, cap_diff=0.00e+00, count_ok=True |
| S012 | 3435 | 3435 | 3435 | ✓ | 0.00e+00 | 2.54e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=2.54e+00, cap_diff=0.00e+00, count_ok=True |
| S014 | 3440 | 3440 | 3440 | ✓ | 0.00e+00 | 1.01e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.01e+00, cap_diff=0.00e+00, count_ok=True |
| S016 | 3444 | 3444 | 3444 | ✓ | 0.00e+00 | 1.81e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.81e+00, cap_diff=0.00e+00, count_ok=True |
| S017 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 2.61e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=2.61e-01, cap_diff=0.00e+00, count_ok=True |
| S018 | 9390 | 9390 | 9390 | ✓ | 0.00e+00 | 1.14e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.14e+00, cap_diff=0.00e+00, count_ok=True |
| S019 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 1.39e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.39e+00, cap_diff=0.00e+00, count_ok=True |
| S020 | 5180 | 5180 | 5180 | ✓ | 0.00e+00 | 2.90e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=2.90e+00, cap_diff=0.00e+00, count_ok=True |
| S021 | 3728 | 3728 | 3728 | ✓ | 0.00e+00 | 1.81e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.81e+00, cap_diff=0.00e+00, count_ok=True |
| S022 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 1.39e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.39e+00, cap_diff=0.00e+00, count_ok=True |
| S023 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 3.84e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=3.84e+00, cap_diff=0.00e+00, count_ok=True |
| S024 | 12436 | 12436 | 12436 | ✓ | 0.00e+00 | 1.56e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.56e+00, cap_diff=0.00e+00, count_ok=True |
| S025 | 8361 | 8361 | 8361 | ✓ | 0.00e+00 | 2.23e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=2.23e+00, cap_diff=0.00e+00, count_ok=True |
| S028 | 6115 | 6115 | 6115 | ✓ | 0.00e+00 | 1.01e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.01e+00, cap_diff=0.00e+00, count_ok=True |
| S030 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 9.69e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=9.69e-01, cap_diff=0.00e+00, count_ok=True |
| S031 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 3.34e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=3.34e-01, cap_diff=0.00e+00, count_ok=True |
| S032 | 10500 | 10500 | 10500 | ✓ | 0.00e+00 | 6.85e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=6.85e+00, cap_diff=0.00e+00, count_ok=True |
| S033 | 4121 | 4121 | 4121 | ✓ | 0.00e+00 | 1.23e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.23e+00, cap_diff=0.00e+00, count_ok=True |
| S034 | 3119 | 3119 | 3119 | ✓ | 0.00e+00 | 8.93e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=8.93e-01, cap_diff=0.00e+00, count_ok=True |
| S035 | 11578 | 11578 | 11578 | ✓ | 0.00e+00 | 1.97e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.97e+00, cap_diff=0.00e+00, count_ok=True |
| S037 | 3462 | 3462 | 3462 | ✓ | 0.00e+00 | 2.09e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=2.09e+00, cap_diff=0.00e+00, count_ok=True |
| S038 | 3440 | 3440 | 3440 | ✓ | 0.00e+00 | 4.06e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=4.06e-01, cap_diff=0.00e+00, count_ok=True |
| S039 | 3435 | 3435 | 3435 | ✓ | 0.00e+00 | 9.12e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=9.12e-01, cap_diff=0.00e+00, count_ok=True |
| S040 | 3710 | 3710 | 3710 | ✓ | 0.00e+00 | 2.01e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=2.01e+00, cap_diff=0.00e+00, count_ok=True |
| S041 | 10262 | 10262 | 10262 | ✓ | 0.00e+00 | 1.15e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.15e+00, cap_diff=0.00e+00, count_ok=True |
| S042 | 5661 | 5661 | 5661 | ✓ | 0.00e+00 | 9.51e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=9.51e-01, cap_diff=0.00e+00, count_ok=True |
| S044 | 4236 | 4236 | 4236 | ✓ | 0.00e+00 | 2.89e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=2.89e+00, cap_diff=0.00e+00, count_ok=True |
| S045 | 4065 | 4065 | 4065 | ✓ | 0.00e+00 | 1.29e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.29e+00, cap_diff=0.00e+00, count_ok=True |
| S046 | 5324 | 5324 | 5324 | ✓ | 0.00e+00 | 3.61e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=3.61e+00, cap_diff=0.00e+00, count_ok=True |
| S047 | 13398 | 13398 | 13398 | ✓ | 0.00e+00 | 9.92e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=9.92e-01, cap_diff=0.00e+00, count_ok=True |
| S048 | 3439 | 3439 | 3439 | ✓ | 0.00e+00 | 1.33e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.33e+00, cap_diff=0.00e+00, count_ok=True |
| S049 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 3.09e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=3.09e+00, cap_diff=0.00e+00, count_ok=True |
| S050 | 3435 | 3435 | 3435 | ✓ | 0.00e+00 | 5.74e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=5.74e-01, cap_diff=0.00e+00, count_ok=True |
| S051 | 3440 | 3440 | 3440 | ✓ | 0.00e+00 | 8.87e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=8.87e-01, cap_diff=0.00e+00, count_ok=True |
| S052 | 6986 | 6986 | 6986 | ✓ | 0.00e+00 | 2.34e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=2.34e+00, cap_diff=0.00e+00, count_ok=True |
| S053 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 5.26e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=5.26e+00, cap_diff=0.00e+00, count_ok=True |
| S054 | 4904 | 4904 | 4904 | ✓ | 0.00e+00 | 2.42e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=2.42e+00, cap_diff=0.00e+00, count_ok=True |
| S055 | 3435 | 3435 | 3435 | ✓ | 0.00e+00 | 1.06e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.06e+00, cap_diff=0.00e+00, count_ok=True |
| S056 | 3519 | 3519 | 3519 | ✓ | 0.00e+00 | 6.96e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=6.96e-01, cap_diff=0.00e+00, count_ok=True |
| S058 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 2.26e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=2.26e+00, cap_diff=0.00e+00, count_ok=True |
| S059 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 4.14e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=4.14e-01, cap_diff=0.00e+00, count_ok=True |
| S060 | 3584 | 3584 | 3584 | ✓ | 0.00e+00 | 2.26e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=2.26e+00, cap_diff=0.00e+00, count_ok=True |
| S061 | 3519 | 3519 | 3519 | ✓ | 0.00e+00 | 9.45e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=9.45e-01, cap_diff=0.00e+00, count_ok=True |
| S062 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 1.52e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.52e+00, cap_diff=0.00e+00, count_ok=True |
| S063 | 3438 | 3438 | 3438 | ✓ | 0.00e+00 | 7.01e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=7.01e-01, cap_diff=0.00e+00, count_ok=True |
| S064 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 1.07e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.07e+00, cap_diff=0.00e+00, count_ok=True |
| S065 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 7.32e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=7.32e-01, cap_diff=0.00e+00, count_ok=True |
| S066 | 7434 | 7434 | 7434 | ✓ | 0.00e+00 | 4.22e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=4.22e+00, cap_diff=0.00e+00, count_ok=True |
| S068 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 3.18e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=3.18e-01, cap_diff=0.00e+00, count_ok=True |
| S069 | 3438 | 3438 | 3438 | ✓ | 0.00e+00 | 1.04e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.04e+00, cap_diff=0.00e+00, count_ok=True |
| S070 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 5.72e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=5.72e-01, cap_diff=0.00e+00, count_ok=True |
| S071 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 4.02e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=4.02e+00, cap_diff=0.00e+00, count_ok=True |
| S072 | 11578 | 11578 | 11578 | ✓ | 0.00e+00 | 1.03e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.03e+00, cap_diff=0.00e+00, count_ok=True |
| S073 | 10467 | 10467 | 10467 | ✓ | 0.00e+00 | 4.10e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=4.10e+00, cap_diff=0.00e+00, count_ok=True |
| S074 | 5087 | 5087 | 5087 | ✓ | 0.00e+00 | 8.75e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=8.75e-01, cap_diff=0.00e+00, count_ok=True |
| S075 | 4072 | 4072 | 4072 | ✓ | 0.00e+00 | 6.28e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=6.28e-01, cap_diff=0.00e+00, count_ok=True |
| S076 | 3440 | 3440 | 3440 | ✓ | 0.00e+00 | 1.03e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.03e+00, cap_diff=0.00e+00, count_ok=True |
| S077 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 5.00e-01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=5.00e-01, cap_diff=0.00e+00, count_ok=True |
| S115 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 4.65e+00 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=4.65e+00, cap_diff=0.00e+00, count_ok=True |
| S116 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 1.47e+01 | ✗ FAIL | actual_diff=0.00e+00, pred_diff=1.47e+01, cap_diff=0.00e+00, count_ok=True |

## FAIL 详情
- **S002**: actual_diff=0.00e+00, pred_diff=1.05e+00, cap_diff=0.00e+00, count_ok=True
- **S003**: actual_diff=0.00e+00, pred_diff=2.02e+00, cap_diff=0.00e+00, count_ok=True
- **S004**: actual_diff=0.00e+00, pred_diff=8.99e-01, cap_diff=0.00e+00, count_ok=True
- **S006**: actual_diff=0.00e+00, pred_diff=8.97e-01, cap_diff=0.00e+00, count_ok=True
- **S007**: actual_diff=0.00e+00, pred_diff=5.64e+00, cap_diff=0.00e+00, count_ok=True
- **S008**: actual_diff=0.00e+00, pred_diff=8.35e-01, cap_diff=0.00e+00, count_ok=True
- **S009**: actual_diff=0.00e+00, pred_diff=4.27e+00, cap_diff=0.00e+00, count_ok=True
- **S010**: actual_diff=0.00e+00, pred_diff=5.36e-01, cap_diff=0.00e+00, count_ok=True
- **S011**: actual_diff=0.00e+00, pred_diff=6.72e-01, cap_diff=0.00e+00, count_ok=True
- **S012**: actual_diff=0.00e+00, pred_diff=2.54e+00, cap_diff=0.00e+00, count_ok=True
- **S014**: actual_diff=0.00e+00, pred_diff=1.01e+00, cap_diff=0.00e+00, count_ok=True
- **S016**: actual_diff=0.00e+00, pred_diff=1.81e+00, cap_diff=0.00e+00, count_ok=True
- **S017**: actual_diff=0.00e+00, pred_diff=2.61e-01, cap_diff=0.00e+00, count_ok=True
- **S018**: actual_diff=0.00e+00, pred_diff=1.14e+00, cap_diff=0.00e+00, count_ok=True
- **S019**: actual_diff=0.00e+00, pred_diff=1.39e+00, cap_diff=0.00e+00, count_ok=True
- **S020**: actual_diff=0.00e+00, pred_diff=2.90e+00, cap_diff=0.00e+00, count_ok=True
- **S021**: actual_diff=0.00e+00, pred_diff=1.81e+00, cap_diff=0.00e+00, count_ok=True
- **S022**: actual_diff=0.00e+00, pred_diff=1.39e+00, cap_diff=0.00e+00, count_ok=True
- **S023**: actual_diff=0.00e+00, pred_diff=3.84e+00, cap_diff=0.00e+00, count_ok=True
- **S024**: actual_diff=0.00e+00, pred_diff=1.56e+00, cap_diff=0.00e+00, count_ok=True
- **S025**: actual_diff=0.00e+00, pred_diff=2.23e+00, cap_diff=0.00e+00, count_ok=True
- **S028**: actual_diff=0.00e+00, pred_diff=1.01e+00, cap_diff=0.00e+00, count_ok=True
- **S030**: actual_diff=0.00e+00, pred_diff=9.69e-01, cap_diff=0.00e+00, count_ok=True
- **S031**: actual_diff=0.00e+00, pred_diff=3.34e-01, cap_diff=0.00e+00, count_ok=True
- **S032**: actual_diff=0.00e+00, pred_diff=6.85e+00, cap_diff=0.00e+00, count_ok=True
- **S033**: actual_diff=0.00e+00, pred_diff=1.23e+00, cap_diff=0.00e+00, count_ok=True
- **S034**: actual_diff=0.00e+00, pred_diff=8.93e-01, cap_diff=0.00e+00, count_ok=True
- **S035**: actual_diff=0.00e+00, pred_diff=1.97e+00, cap_diff=0.00e+00, count_ok=True
- **S037**: actual_diff=0.00e+00, pred_diff=2.09e+00, cap_diff=0.00e+00, count_ok=True
- **S038**: actual_diff=0.00e+00, pred_diff=4.06e-01, cap_diff=0.00e+00, count_ok=True
- **S039**: actual_diff=0.00e+00, pred_diff=9.12e-01, cap_diff=0.00e+00, count_ok=True
- **S040**: actual_diff=0.00e+00, pred_diff=2.01e+00, cap_diff=0.00e+00, count_ok=True
- **S041**: actual_diff=0.00e+00, pred_diff=1.15e+00, cap_diff=0.00e+00, count_ok=True
- **S042**: actual_diff=0.00e+00, pred_diff=9.51e-01, cap_diff=0.00e+00, count_ok=True
- **S044**: actual_diff=0.00e+00, pred_diff=2.89e+00, cap_diff=0.00e+00, count_ok=True
- **S045**: actual_diff=0.00e+00, pred_diff=1.29e+00, cap_diff=0.00e+00, count_ok=True
- **S046**: actual_diff=0.00e+00, pred_diff=3.61e+00, cap_diff=0.00e+00, count_ok=True
- **S047**: actual_diff=0.00e+00, pred_diff=9.92e-01, cap_diff=0.00e+00, count_ok=True
- **S048**: actual_diff=0.00e+00, pred_diff=1.33e+00, cap_diff=0.00e+00, count_ok=True
- **S049**: actual_diff=0.00e+00, pred_diff=3.09e+00, cap_diff=0.00e+00, count_ok=True
- **S050**: actual_diff=0.00e+00, pred_diff=5.74e-01, cap_diff=0.00e+00, count_ok=True
- **S051**: actual_diff=0.00e+00, pred_diff=8.87e-01, cap_diff=0.00e+00, count_ok=True
- **S052**: actual_diff=0.00e+00, pred_diff=2.34e+00, cap_diff=0.00e+00, count_ok=True
- **S053**: actual_diff=0.00e+00, pred_diff=5.26e+00, cap_diff=0.00e+00, count_ok=True
- **S054**: actual_diff=0.00e+00, pred_diff=2.42e+00, cap_diff=0.00e+00, count_ok=True
- **S055**: actual_diff=0.00e+00, pred_diff=1.06e+00, cap_diff=0.00e+00, count_ok=True
- **S056**: actual_diff=0.00e+00, pred_diff=6.96e-01, cap_diff=0.00e+00, count_ok=True
- **S058**: actual_diff=0.00e+00, pred_diff=2.26e+00, cap_diff=0.00e+00, count_ok=True
- **S059**: actual_diff=0.00e+00, pred_diff=4.14e-01, cap_diff=0.00e+00, count_ok=True
- **S060**: actual_diff=0.00e+00, pred_diff=2.26e+00, cap_diff=0.00e+00, count_ok=True
- **S061**: actual_diff=0.00e+00, pred_diff=9.45e-01, cap_diff=0.00e+00, count_ok=True
- **S062**: actual_diff=0.00e+00, pred_diff=1.52e+00, cap_diff=0.00e+00, count_ok=True
- **S063**: actual_diff=0.00e+00, pred_diff=7.01e-01, cap_diff=0.00e+00, count_ok=True
- **S064**: actual_diff=0.00e+00, pred_diff=1.07e+00, cap_diff=0.00e+00, count_ok=True
- **S065**: actual_diff=0.00e+00, pred_diff=7.32e-01, cap_diff=0.00e+00, count_ok=True
- **S066**: actual_diff=0.00e+00, pred_diff=4.22e+00, cap_diff=0.00e+00, count_ok=True
- **S068**: actual_diff=0.00e+00, pred_diff=3.18e-01, cap_diff=0.00e+00, count_ok=True
- **S069**: actual_diff=0.00e+00, pred_diff=1.04e+00, cap_diff=0.00e+00, count_ok=True
- **S070**: actual_diff=0.00e+00, pred_diff=5.72e-01, cap_diff=0.00e+00, count_ok=True
- **S071**: actual_diff=0.00e+00, pred_diff=4.02e+00, cap_diff=0.00e+00, count_ok=True
- **S072**: actual_diff=0.00e+00, pred_diff=1.03e+00, cap_diff=0.00e+00, count_ok=True
- **S073**: actual_diff=0.00e+00, pred_diff=4.10e+00, cap_diff=0.00e+00, count_ok=True
- **S074**: actual_diff=0.00e+00, pred_diff=8.75e-01, cap_diff=0.00e+00, count_ok=True
- **S075**: actual_diff=0.00e+00, pred_diff=6.28e-01, cap_diff=0.00e+00, count_ok=True
- **S076**: actual_diff=0.00e+00, pred_diff=1.03e+00, cap_diff=0.00e+00, count_ok=True
- **S077**: actual_diff=0.00e+00, pred_diff=5.00e-01, cap_diff=0.00e+00, count_ok=True
- **S115**: actual_diff=0.00e+00, pred_diff=4.65e+00, cap_diff=0.00e+00, count_ok=True
- **S116**: actual_diff=0.00e+00, pred_diff=1.47e+01, cap_diff=0.00e+00, count_ok=True

## 结论
**68 个站点失败**，请检查上述 FAIL 条目。
