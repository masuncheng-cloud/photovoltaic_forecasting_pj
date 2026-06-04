# Dashboard 预测值一致性检查报告

**生成时间**: 2026-06-04 23:46:05

**检查口径**: split != 'future', hour in 6..19
**预测列**: power_pred_final

## 总体结果

| 指标 | 值 |
|------|---|
| 总站点数 | 68 |
| PASS | 0 |
| FAIL | 68 |
| WARN | 0 |
| 最大 actual 误差 | 0.00e+00 |
| 最大 pred 误差 | 6.02e+00 |
| 最大 capacity 误差 | 0.00e+00 |

## 逐站点详情

| site_id | n_json | n_pkl | n_matched | count_ok | max_diff_actual | max_diff_pred | status |
|----------|--------|-------|-----------|---------|-----------------|---------------|--------|
| S002 | 3439 | 3439 | 3439 | ✓ | 0.00e+00 | 3.40e-01 | ✗ FAIL |
| S003 | 11938 | 11938 | 11938 | ✓ | 0.00e+00 | 7.18e-01 | ✗ FAIL |
| S004 | 3519 | 3519 | 3519 | ✓ | 0.00e+00 | 2.79e-01 | ✗ FAIL |
| S006 | 3461 | 3461 | 3461 | ✓ | 0.00e+00 | 4.23e-01 | ✗ FAIL |
| S007 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 5.99e+00 | ✗ FAIL |
| S008 | 3844 | 3844 | 3844 | ✓ | 0.00e+00 | 3.66e-01 | ✗ FAIL |
| S009 | 6115 | 6115 | 6115 | ✓ | 0.00e+00 | 4.78e-01 | ✗ FAIL |
| S010 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 1.21e-01 | ✗ FAIL |
| S011 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 1.24e-01 | ✗ FAIL |
| S012 | 3435 | 3435 | 3435 | ✓ | 0.00e+00 | 1.34e+00 | ✗ FAIL |
| S014 | 3440 | 3440 | 3440 | ✓ | 0.00e+00 | 6.06e-01 | ✗ FAIL |
| S016 | 3444 | 3444 | 3444 | ✓ | 0.00e+00 | 1.05e+00 | ✗ FAIL |
| S017 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 8.54e-02 | ✗ FAIL |
| S018 | 9390 | 9390 | 9390 | ✓ | 0.00e+00 | 1.08e+00 | ✗ FAIL |
| S019 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 1.03e+00 | ✗ FAIL |
| S020 | 5180 | 5180 | 5180 | ✓ | 0.00e+00 | 3.21e-01 | ✗ FAIL |
| S021 | 3728 | 3728 | 3728 | ✓ | 0.00e+00 | 1.10e-01 | ✗ FAIL |
| S022 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 1.33e-01 | ✗ FAIL |
| S023 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 2.83e+00 | ✗ FAIL |
| S024 | 12436 | 12436 | 12436 | ✓ | 0.00e+00 | 1.51e+00 | ✗ FAIL |
| S025 | 8361 | 8361 | 8361 | ✓ | 0.00e+00 | 9.17e-01 | ✗ FAIL |
| S028 | 6115 | 6115 | 6115 | ✓ | 0.00e+00 | 3.58e-01 | ✗ FAIL |
| S030 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 4.37e-01 | ✗ FAIL |
| S031 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 6.87e-02 | ✗ FAIL |
| S032 | 10500 | 10500 | 10500 | ✓ | 0.00e+00 | 3.60e+00 | ✗ FAIL |
| S033 | 4121 | 4121 | 4121 | ✓ | 0.00e+00 | 5.84e-01 | ✗ FAIL |
| S034 | 3119 | 3119 | 3119 | ✓ | 0.00e+00 | 3.55e-01 | ✗ FAIL |
| S035 | 11578 | 11578 | 11578 | ✓ | 0.00e+00 | 2.42e+00 | ✗ FAIL |
| S037 | 3462 | 3462 | 3462 | ✓ | 0.00e+00 | 2.12e+00 | ✗ FAIL |
| S038 | 3440 | 3440 | 3440 | ✓ | 0.00e+00 | 8.02e-02 | ✗ FAIL |
| S039 | 3435 | 3435 | 3435 | ✓ | 0.00e+00 | 1.38e-01 | ✗ FAIL |
| S040 | 3710 | 3710 | 3710 | ✓ | 0.00e+00 | 1.02e+00 | ✗ FAIL |
| S041 | 10262 | 10262 | 10262 | ✓ | 0.00e+00 | 1.85e-01 | ✗ FAIL |
| S042 | 5661 | 5661 | 5661 | ✓ | 0.00e+00 | 4.06e-01 | ✗ FAIL |
| S044 | 4236 | 4236 | 4236 | ✓ | 0.00e+00 | 4.14e+00 | ✗ FAIL |
| S045 | 4065 | 4065 | 4065 | ✓ | 0.00e+00 | 6.63e-01 | ✗ FAIL |
| S046 | 5324 | 5324 | 5324 | ✓ | 0.00e+00 | 5.51e-01 | ✗ FAIL |
| S047 | 13398 | 13398 | 13398 | ✓ | 0.00e+00 | 6.12e-01 | ✗ FAIL |
| S048 | 3439 | 3439 | 3439 | ✓ | 0.00e+00 | 3.08e-01 | ✗ FAIL |
| S049 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 2.97e+00 | ✗ FAIL |
| S050 | 3435 | 3435 | 3435 | ✓ | 0.00e+00 | 7.00e-02 | ✗ FAIL |
| S051 | 3440 | 3440 | 3440 | ✓ | 0.00e+00 | 4.27e-01 | ✗ FAIL |
| S052 | 6986 | 6986 | 6986 | ✓ | 0.00e+00 | 4.54e-01 | ✗ FAIL |
| S053 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 4.03e+00 | ✗ FAIL |
| S054 | 4904 | 4904 | 4904 | ✓ | 0.00e+00 | 3.22e+00 | ✗ FAIL |
| S055 | 3435 | 3435 | 3435 | ✓ | 0.00e+00 | 1.08e-01 | ✗ FAIL |
| S056 | 3519 | 3519 | 3519 | ✓ | 0.00e+00 | 1.00e-01 | ✗ FAIL |
| S058 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 2.15e+00 | ✗ FAIL |
| S059 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 7.94e-02 | ✗ FAIL |
| S060 | 3584 | 3584 | 3584 | ✓ | 0.00e+00 | 5.99e-01 | ✗ FAIL |
| S061 | 3519 | 3519 | 3519 | ✓ | 0.00e+00 | 2.29e-01 | ✗ FAIL |
| S062 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 4.14e-01 | ✗ FAIL |
| S063 | 3438 | 3438 | 3438 | ✓ | 0.00e+00 | 4.36e-01 | ✗ FAIL |
| S064 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 3.67e-01 | ✗ FAIL |
| S065 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 1.46e-01 | ✗ FAIL |
| S066 | 7434 | 7434 | 7434 | ✓ | 0.00e+00 | 6.98e-01 | ✗ FAIL |
| S068 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 5.74e-02 | ✗ FAIL |
| S069 | 3438 | 3438 | 3438 | ✓ | 0.00e+00 | 7.08e-02 | ✗ FAIL |
| S070 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 1.09e-01 | ✗ FAIL |
| S071 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 4.24e+00 | ✗ FAIL |
| S072 | 11578 | 11578 | 11578 | ✓ | 0.00e+00 | 1.43e+00 | ✗ FAIL |
| S073 | 10467 | 10467 | 10467 | ✓ | 0.00e+00 | 4.71e+00 | ✗ FAIL |
| S074 | 5087 | 5087 | 5087 | ✓ | 0.00e+00 | 4.29e-01 | ✗ FAIL |
| S075 | 4072 | 4072 | 4072 | ✓ | 0.00e+00 | 1.00e-01 | ✗ FAIL |
| S076 | 3440 | 3440 | 3440 | ✓ | 0.00e+00 | 5.45e-01 | ✗ FAIL |
| S077 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 7.01e-02 | ✗ FAIL |
| S115 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 1.72e+00 | ✗ FAIL |
| S116 | 15344 | 15344 | 15344 | ✓ | 0.00e+00 | 6.02e+00 | ✗ FAIL |

## FAIL 详情

- **S002**: actual=0.00e+00, pred=3.40e-01, cap=0.00e+00, count_ok=True
- **S003**: actual=0.00e+00, pred=7.18e-01, cap=0.00e+00, count_ok=True
- **S004**: actual=0.00e+00, pred=2.79e-01, cap=0.00e+00, count_ok=True
- **S006**: actual=0.00e+00, pred=4.23e-01, cap=0.00e+00, count_ok=True
- **S007**: actual=0.00e+00, pred=5.99e+00, cap=0.00e+00, count_ok=True
- **S008**: actual=0.00e+00, pred=3.66e-01, cap=0.00e+00, count_ok=True
- **S009**: actual=0.00e+00, pred=4.78e-01, cap=0.00e+00, count_ok=True
- **S010**: actual=0.00e+00, pred=1.21e-01, cap=0.00e+00, count_ok=True
- **S011**: actual=0.00e+00, pred=1.24e-01, cap=0.00e+00, count_ok=True
- **S012**: actual=0.00e+00, pred=1.34e+00, cap=0.00e+00, count_ok=True
- **S014**: actual=0.00e+00, pred=6.06e-01, cap=0.00e+00, count_ok=True
- **S016**: actual=0.00e+00, pred=1.05e+00, cap=0.00e+00, count_ok=True
- **S017**: actual=0.00e+00, pred=8.54e-02, cap=0.00e+00, count_ok=True
- **S018**: actual=0.00e+00, pred=1.08e+00, cap=0.00e+00, count_ok=True
- **S019**: actual=0.00e+00, pred=1.03e+00, cap=0.00e+00, count_ok=True
- **S020**: actual=0.00e+00, pred=3.21e-01, cap=0.00e+00, count_ok=True
- **S021**: actual=0.00e+00, pred=1.10e-01, cap=0.00e+00, count_ok=True
- **S022**: actual=0.00e+00, pred=1.33e-01, cap=0.00e+00, count_ok=True
- **S023**: actual=0.00e+00, pred=2.83e+00, cap=0.00e+00, count_ok=True
- **S024**: actual=0.00e+00, pred=1.51e+00, cap=0.00e+00, count_ok=True
- **S025**: actual=0.00e+00, pred=9.17e-01, cap=0.00e+00, count_ok=True
- **S028**: actual=0.00e+00, pred=3.58e-01, cap=0.00e+00, count_ok=True
- **S030**: actual=0.00e+00, pred=4.37e-01, cap=0.00e+00, count_ok=True
- **S031**: actual=0.00e+00, pred=6.87e-02, cap=0.00e+00, count_ok=True
- **S032**: actual=0.00e+00, pred=3.60e+00, cap=0.00e+00, count_ok=True
- **S033**: actual=0.00e+00, pred=5.84e-01, cap=0.00e+00, count_ok=True
- **S034**: actual=0.00e+00, pred=3.55e-01, cap=0.00e+00, count_ok=True
- **S035**: actual=0.00e+00, pred=2.42e+00, cap=0.00e+00, count_ok=True
- **S037**: actual=0.00e+00, pred=2.12e+00, cap=0.00e+00, count_ok=True
- **S038**: actual=0.00e+00, pred=8.02e-02, cap=0.00e+00, count_ok=True
- **S039**: actual=0.00e+00, pred=1.38e-01, cap=0.00e+00, count_ok=True
- **S040**: actual=0.00e+00, pred=1.02e+00, cap=0.00e+00, count_ok=True
- **S041**: actual=0.00e+00, pred=1.85e-01, cap=0.00e+00, count_ok=True
- **S042**: actual=0.00e+00, pred=4.06e-01, cap=0.00e+00, count_ok=True
- **S044**: actual=0.00e+00, pred=4.14e+00, cap=0.00e+00, count_ok=True
- **S045**: actual=0.00e+00, pred=6.63e-01, cap=0.00e+00, count_ok=True
- **S046**: actual=0.00e+00, pred=5.51e-01, cap=0.00e+00, count_ok=True
- **S047**: actual=0.00e+00, pred=6.12e-01, cap=0.00e+00, count_ok=True
- **S048**: actual=0.00e+00, pred=3.08e-01, cap=0.00e+00, count_ok=True
- **S049**: actual=0.00e+00, pred=2.97e+00, cap=0.00e+00, count_ok=True
- **S050**: actual=0.00e+00, pred=7.00e-02, cap=0.00e+00, count_ok=True
- **S051**: actual=0.00e+00, pred=4.27e-01, cap=0.00e+00, count_ok=True
- **S052**: actual=0.00e+00, pred=4.54e-01, cap=0.00e+00, count_ok=True
- **S053**: actual=0.00e+00, pred=4.03e+00, cap=0.00e+00, count_ok=True
- **S054**: actual=0.00e+00, pred=3.22e+00, cap=0.00e+00, count_ok=True
- **S055**: actual=0.00e+00, pred=1.08e-01, cap=0.00e+00, count_ok=True
- **S056**: actual=0.00e+00, pred=1.00e-01, cap=0.00e+00, count_ok=True
- **S058**: actual=0.00e+00, pred=2.15e+00, cap=0.00e+00, count_ok=True
- **S059**: actual=0.00e+00, pred=7.94e-02, cap=0.00e+00, count_ok=True
- **S060**: actual=0.00e+00, pred=5.99e-01, cap=0.00e+00, count_ok=True
- **S061**: actual=0.00e+00, pred=2.29e-01, cap=0.00e+00, count_ok=True
- **S062**: actual=0.00e+00, pred=4.14e-01, cap=0.00e+00, count_ok=True
- **S063**: actual=0.00e+00, pred=4.36e-01, cap=0.00e+00, count_ok=True
- **S064**: actual=0.00e+00, pred=3.67e-01, cap=0.00e+00, count_ok=True
- **S065**: actual=0.00e+00, pred=1.46e-01, cap=0.00e+00, count_ok=True
- **S066**: actual=0.00e+00, pred=6.98e-01, cap=0.00e+00, count_ok=True
- **S068**: actual=0.00e+00, pred=5.74e-02, cap=0.00e+00, count_ok=True
- **S069**: actual=0.00e+00, pred=7.08e-02, cap=0.00e+00, count_ok=True
- **S070**: actual=0.00e+00, pred=1.09e-01, cap=0.00e+00, count_ok=True
- **S071**: actual=0.00e+00, pred=4.24e+00, cap=0.00e+00, count_ok=True
- **S072**: actual=0.00e+00, pred=1.43e+00, cap=0.00e+00, count_ok=True
- **S073**: actual=0.00e+00, pred=4.71e+00, cap=0.00e+00, count_ok=True
- **S074**: actual=0.00e+00, pred=4.29e-01, cap=0.00e+00, count_ok=True
- **S075**: actual=0.00e+00, pred=1.00e-01, cap=0.00e+00, count_ok=True
- **S076**: actual=0.00e+00, pred=5.45e-01, cap=0.00e+00, count_ok=True
- **S077**: actual=0.00e+00, pred=7.01e-02, cap=0.00e+00, count_ok=True
- **S115**: actual=0.00e+00, pred=1.72e+00, cap=0.00e+00, count_ok=True
- **S116**: actual=0.00e+00, pred=6.02e+00, cap=0.00e+00, count_ok=True

## 结论

**68 个站点 FAIL**，请检查上述详情。
