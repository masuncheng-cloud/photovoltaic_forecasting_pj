# 训练后逻辑审计报告

**生成时间**: 2026-06-01 15:33:00
**最终预测列**: power_pred_final
**评估口径**: split=test, hour=6-19

## 校验结果汇总

| 状态 | 数量 |
|------|------|
| PASS | 32 |
| FAIL | 1 |
| WARN | 3 |

## 逐项结果

| # | 状态 | 检查项 | 说明 |
|---|------|--------|------|
| 1 | ✓ PASS | C1: 最终预测 pkl 存在且可读 | canonical: distributed_predictions_final_full.pkl, 898,175 行, 53 列, 68 站 |
| 2 | ✓ PASS | C2: eval pkl 数据范围 | [NOTE] (Round66 口径) 含 ['test', 'valid'], 175,168 行, 68 站 |
| 3 | ✓ PASS | C3: 最终预测列存在 | power_pred_final: 175,168/898,175 (19.5%) |
| 4 | ✓ PASS | C4: 真实功率列存在 | power_mw: 898,175/898,175 |
| 5 | ✓ PASS | C5: split 口径正确 | 值=['test', 'train', 'valid'], test行数=116,144 |
| 6 | ✓ PASS | C6: 测试集时间切分正确 | test=2025-09-01~2025-12-31 |
| 7 | ✓ PASS | C7: 使用正式预测列 | power_pred_final 就绪 |
| 8 | ✓ PASS | C8: 测试集有预测结果 | 116,144 行 |
| 9 | ⚠ WARN | C9: 夜间/future 不参与评估 | 夜间 180,660 行（评估时会排除） |
| 10 | ✓ PASS | C10: hourly_nrmse_consistent.csv 正确 | 14 小时数据, NRMSE范围: 3.94%~16.97% |
| 11 | ✓ PASS | C11: dashboard 一致性校验 | 68 站, 全部 PASS |
| 12 | ✓ PASS | C12: dashboard 数据新鲜 | dashboard 晚于 canonical pkl 0.05h |
| 13 | ✓ PASS | C13: Git 不追踪 pkl | 0 个 |
| 14 | ✓ PASS | C13: Git 不追踪 site_series JSON | [NOTE] 69 个（交互式数据，可按需生成，.gitignore 规则正常） |
| 15 | ✓ PASS | C14: 训练集样本量 | 421,771 行（2023-01-01~2025-06-30 白天） |
| 16 | ✓ PASS | C15: 站点数量合理 | 68 个站点 |
| 17 | ✓ PASS | C16: manifest.pipeline_entry | scripts/run_full_pipeline.py |
| 18 | ✓ PASS | C16: manifest.final_prediction_column | power_pred_final |
| 19 | ✗ FAIL | C16: manifest artifacts | 缺失: ['final_full_pkl: 044eb723094251aa8bd6efabd3a79c174d950b423361b61b38bd63f6c7e75884', 'final_eval_pkl: 60614f81497c7119ba6fcc2620de7058220d95c4e6febe76b6b8a0fb29b6e826', 'dashboard_metadata: 7b2312624059c1b7d069e617ec5c9820a764554b24810ca2bfb736f07bbbc8ec', 'metrics_distributed_metrics_by_hour_fixed: aa8db40dfd7eaa1a3887d3248a88dfd47cd1b56682a493ee25b68203c88ded19', 'metrics_hourly_nrmse_consistent: e2ef1130f18d1916b3b74b2f92b76bbaa5964fe728826a44bc57194ee8dabb2e', 'metrics_hourly_site_nrmse_consistent: 7327f8cd645763eb09b4833ea359c79f8774fd05eadbd6c84e57eeef2e2ca3c8', 'metrics_round36_city_hourly_nrmse: 7b07d11310f08f59bca2e1531505ed2a0ea0b65daade5d346f426cf6624e1662', 'metrics_round36_site_avg_hourly_nrmse: 46cdeac0102f3e9b80910d48d4952e33c7b9e3cb609b9fd3651be84c72baa6a6', 'metrics_round36_site_hourly_nrmse: 4a6194f3bec3792f7025aa698baae2913410fa02d519295e9cd9c14775fb46c7', 'metrics_round39_edge_hour_pkl_vs_dashboard: 252198291185b6efe19b2bff7b9519079ca21956f74a3e741a835ea4b618ef8d', 'metrics_round39_edge_hour_zero_by_hour: 8492238f19189fc9ff98254181a0571ebb20c0445659b769b2fadd5023638de3', 'metrics_round39_edge_hour_zero_by_time: c4f1fc33c147e7350a9cdacfbb8d9b87238d1ca522993bbe6b1217e0547416d2', 'metrics_round46_hourly_nrmse_consistent: e2ef1130f18d1916b3b74b2f92b76bbaa5964fe728826a44bc57194ee8dabb2e', 'metrics_round46_site_hour_nrmse_consistent: 7327f8cd645763eb09b4833ea359c79f8774fd05eadbd6c84e57eeef2e2ca3c8', 'metrics_round59_compare_hourly: ff1dbbad45fe5ffdb6ab6075e9f60bc5cbfc243a127b995403a4425fb3ed4197', 'metrics_round60_compare_hourly: 2a93aec95dd07a5eb1766cafe36aebf9cd14b5ec6d8c2ef2cc9f306dfdc95ff5', 'metrics_round61_compare_hourly: 0070ce183780e61076f62d02541094e8fc5fd7fa862c4152854c967e77152376', 'metrics_audit_site_mapping: 83e491537f8bbd42490cab576215ad67e6112ea66e162d709c64d5c4d25222a5', 'metrics_calibration_ablation_by_site: c4deb77d3fe3ee9ffdbb13559fbc04af8029ca17efe24b86c8628b01bb522a84', 'metrics_distributed_metrics_by_site: 26af84c24a20f7a1a5123d92526db3e5e63a209d0c6bc7849457f71577117110', 'metrics_distributed_metrics_by_site_fixed: 356cb00342b5b62cec4e57b70548c5b3abf21a8546b9a082e66d796a579ce6a7', 'metrics_round36_bias_sites: 7c99c16e4cb6f3a4cebbb23ec15e1a8f289b69c0160d15bec98d99c61d6e3d81', 'metrics_round36_distribution_drift_sites: 4e57561feb1675342aec937ab51282b5500e8073531df2e9e64c7e350958339f', 'metrics_round36_invalid_eval_sites: bc0271b2f171ed63034067f00359273f98f253de31733d2be9e25d425f7e617e', 'metrics_round36_site_count_summary: e7e2b56b6ef5ea95e4f97414ad3448aed186c3079d6c4f4b6dc011685962e3cb', 'metrics_round36_site_metrics: 4fa0aee2d7a8fa398913e6703ec7a021d9f2e8d0d7a6e447054daf922799929b', 'metrics_round36_site_validity: 6c9400c73893b745f9e49cafcd78455a3029bab05254ac65ebff937f78053062', 'metrics_round36_typical_sites: a00da7b1ed4fa11e9f7ea6bc0f0457564448ad072eeed5ab248bb65ff9f4925a', 'metrics_round59_compare_site: 28afc6f4acf8821081dae10a19c16ccfa9e4fe59ed875b5f077568b7ed96ce01', 'metrics_round60_compare_site: d82b09e2e7a5dcef89059cd0dc027e521f885ba75164616420df7c72449d6588', 'metrics_round61_compare_site: cf291cf01a7ca865ee32810fbc26436607c433ee27ee58c7b5ff94b9e22ec3bd', 'metrics_site_metrics_consistent: 4fa0aee2d7a8fa398913e6703ec7a021d9f2e8d0d7a6e447054daf922799929b', 'metrics_site_test_daytime_zero_ratio_summary: f49ab5305fdff5fd689b8de82527c66e41db7b2493319b15f436dbf7560c85ea', 'metrics_top_day_zero_sites: 94c9597e8b53e55c01d7a568e3329385dc0329febbda767e7416a9b08a1e22e3'] |
| 20 | ⚠ WARN | C16: artifact hash 验证 | manifest 中无有效 hash 信息（可能由旧版 pipeline 生成） |
| 21 | ✓ PASS | C16: manifest 生成时间 | 晚于 canonical full pkl 0.42h |
| 22 | ✓ PASS | GEO1: 经纬度覆盖 | S115 lat=34.5933, lon=119.2172 |
| 23 | ✓ PASS | GEO1: 经纬度覆盖 | S116 lat=34.2983, lon=119.2318 |
| 24 | ✓ PASS | GEO2: 坐标范围 | S115 (34.5933, 119.2172) 在连云港范围内 |
| 25 | ✓ PASS | GEO2: 坐标范围 | S116 (34.2983, 119.2318) 在连云港范围内 |
| 26 | ✓ PASS | GEO3: 置信度 | S115 confidence=medium |
| 27 | ✓ PASS | GEO3: 置信度 | S116 confidence=low |
| 28 | ⚠ WARN | GEO4: 低置信度警告 | S116 confidence=low，精确光伏场区中心有待甲方/运维台账确认 |
| 29 | ✓ PASS | GEO5: S115 scene_v151 test 10-14 | scene 正常 {'mid': 378, 'clear_peak': 183, 'low': 49}，非 all-night |
| 30 | ✓ PASS | GEO5: S115 g_blend_pred test 10-14 | max=828.0，正常 |
| 31 | ✓ PASS | GEO5: S115 power_pred_final test 10-14 | 610/610 行非0，正常 |
| 32 | ✓ PASS | GEO5: S116 scene_v151 test 10-14 | scene 正常 {'mid': 370, 'clear_peak': 186, 'low': 54}，非 all-night |
| 33 | ✓ PASS | GEO5: S116 g_blend_pred test 10-14 | max=835.7，正常 |
| 34 | ✓ PASS | GEO5: S116 power_pred_final test 10-14 | 610/610 行非0，正常 |
| 35 | ✓ PASS | C17: 站点数量一致性 | full=68, eval=68，数量相同 |
| 36 | ✓ PASS | BIAS: 口径说明 | BIAS = mean(power_pred_final - power_mw); BIAS > 0 表示预测偏高，BIAS < 0 表示预测偏低 |

## 训练切分

- train_start: 2023-01-01
- train_end: 2025-06-30
- valid_start: 2025-07-01
- valid_end: 2025-08-31
- test_start: 2025-09-01
- test_end: 2025-12-31
- future_start: 2026-01-01
- future_end: 2026-03-31

## 结论

**1 项 FAIL，不合格。请修复后重新运行训练流程。**
