# Round34 执行反馈报告

> **执行时间**：2026-05-28 18:07 (UTC+8)
> **方案来源**：`Cursor执行方案_Round34_修复Round33指标口径与最终产物一致性.md`
> **Git 提交**：`c20e3ee`

---

## 一、执行总览

| 步骤 | 任务 | 状态 | 备注 |
|------|------|------|------|
| Step 1 | `resolve_prediction_column()` 写入 `eval_frame.py` | ✅ | 优先级：power_pred_final > pred_calibrated > power_pred |
| Step 2 | 站点有效性表 → `round34_site_validity.csv` | ✅ | 50站标为"无测试预测结果"，118站自洽 |
| Step 3 | 校准落地 → `power_pred_final` | ✅ | S017 恶化>1%触发自动回退 |
| Step 4 | 全市逐小时 NRMSE 重算 | ✅ | 修复聚合 bug（actual 用 power_mw） |
| Step 5 | 站点级指标重算 | ✅ | 修复 validity dict lookup bug |
| Step 6 | 典型站点互斥 | ✅ | 14站无跨类重复 |
| Step 7 | 项目报告重写 | ✅ | 区分全市 vs 站点平均 NRMSE |
| Step 8 | 可视化导出修复 | ✅ | 优先读 Round34 pkl |
| Step 9 | 后验校验 | ✅ | 12/12 PASS |
| Step 10 | Git 提交推送 | ✅ | c20e3ee，101 文件 |

---

## 二、关键数据对比

### 2.1 全市总出力 NRMSE（正确口径）

> 算法：先按时间点聚合全市功率，再算 RMSE，再除以城市总装机。

| 小时 | NRMSE (%) | MAE (MW) | RMSE (MW) |
|------|-----------|-----------|------------|
| 6   | 2.52 | 9.43 | 9.80 |
| 7   | 3.65 | 12.10 | 14.18 |
| 8   | 4.73 | 15.88 | 18.39 |
| 9   | 4.98 | 14.71 | 19.37 |
| **10** | **5.59** | **16.42** | **21.72** |
| **11** | **5.95** | **17.67** | **23.14** |
| **12** | **5.87** | **16.69** | **22.81** |
| **13** | **5.77** | **16.84** | **22.44** |
| **14** | **5.74** | **16.18** | **22.29** |
| 15  | 3.81 | 10.97 | 14.83 |
| 16  | 2.47 | 6.93 | 9.60 |
| 17  | 2.42 | 8.67 | 9.42 |
| 18  | 2.49 | 8.55 | 9.67 |
| 19  | 2.50 | 8.79 | 9.73 |

**10-14 点主力发电时段 NRMSE = 5.78%**（早晚辐照弱、功率低，NRMSE 天然偏大）

### 2.2 站点有效性分层

| 类别 | 数量 | 纳入排名 |
|------|------|----------|
| 全部登记站点 | 118 | — |
| 有 test 结果站点 | 68 | — |
| ↳ 正常可排名站点 | **14** | ✓ |
| ↳ 测试期无有效发电 | 5 | ✗ |
| ↳ 测试期分布漂移 | 37 | ✗ |
| ↳ 系统性偏差 | 12 | ✗ |
| 无测试预测结果 | 50 | ✗ |

> 自洽验证：118 = 68 + 50 ✓，68 = 14 + 5 + 37 + 12 ✓

### 2.3 校准效果

|| 指标 | 值 |
||------|-----|
|| 应用校准行数 | 666,015 / 1,172,180（56.8%） |
|| 回退站点 | S017（test NRMSE 恶化>1%，自动回退） |

> **注意**：下表 NRMSE 为旧版站点行级归一化口径（除以站点容量均值），不作为最终验收指标，仅用于对比校准前后方向。正式结果见"全市总出力 10-14 点 NRMSE = 5.78%"。

### 2.4 典型站点（14 个正常可排名站点的互斥分类）

| 类型 | 站点列表 |
|------|---------|
| 预测最好（5站） | S062, S023, S031, S049, S047 |
| 预测最差（5站） | S072, S065, S058, S007, S030 |
| 相对正确（4站） | S064, S068, S048, S011 |

---

## 三、发现的 Bug 及修复记录

| # | Bug 描述 | 位置 | 修复方式 |
|---|---------|------|---------|
| 1 | `city_hourly_nrmse` 中 `agg` 用 `pred_col` 同时计算 actual 和 pred | `compute_round34_metrics.py` | 改为 actual_mw=("power_mw", "sum") |
| 2 | `validity_df.set_index()` 用 `.get()` 返回 Series 导致 fallback 失效 | `compute_round34_metrics.py` | 改用 `.to_dict("index")` |
| 3 | 校准汇总中 `df_test` 未包含新生成的 `power_pred_final` 列 | `apply_bias_calibration_round34.py` | 重新 filter df 后再计算 |
| 4 | `posttrain_validation_round34.py` 中 JSON 数据类型判断错误 | `posttrain_validation_round34.py` | 加 `isinstance(data, dict)` 分支 |
| 5 | 一致性 CSV 列名 `max_abs_diff_power_clean` 与代码不匹配 | `posttrain_validation_round34.py` | 兼容两列名 |

---

## 四、12 项后验校验结果

| # | 检查项 | 状态 | 说明 |
|---|--------|------|------|
| C1 | final pkl 存在且可读 | ✅ PASS | 1,172,180 行, 25 列 |
| C2 | eval pkl 只含 test 6-19 | ✅ PASS | 116,144 行, 68 站 |
| C3 | `power_pred_final` 存在 | ✅ PASS | 1,172,180 个非空值 |
| C4 | `power_pred_final` ∈ [0, capacity] | ✅ PASS | 无违规 |
| C5 | 无 test 数据站点不标"正常评价" | ✅ PASS | 50 站已正确标记为"无测试预测结果" |
| C6 | site_metrics 站点与 eval pkl 一致 | ✅ PASS | 68 站 |
| C7 | city_hourly_nrmse 数值合理 | ✅ PASS | NRMSE 范围 2.42%~5.95% |
| C8 | typical_sites 无跨类重复 | ✅ PASS | 预测最好5 + 最差5 + 相对正确4 |
| C9 | Markdown 与 CSV 口径一致 | ✅ PASS | 10-14点 5.78%，CSV 已为%不乘100 |
| C10 | 可视化 JSON 可读 | ✅ PASS | 已检查 5 个 site_series 文件 |
| C11 | dashboard actual 与 power_clean 一致 | ✅ PASS | max_diff = 8.88e-16 |
| C12 | 站点数量自洽 | ✅ PASS | 118 = 68+50, 68 = 14+5+37+12 |

**结果：12 PASS / 0 FAIL / 0 WARN**

---

## 五、新增/修改文件清单

### 新增脚本（4 个）
```
scripts/build_site_validity_round34.py        # 站点有效性分层
scripts/apply_bias_calibration_round34.py     # 校准落地 power_pred_final
scripts/compute_round34_metrics.py           # 全市聚合 NRMSE + 站点指标 + 典型站点
scripts/posttrain_validation_round34.py       # 12 项后验校验
```

### 修改文件（3 个）
```
src/pv_forecasting/core/eval_frame.py          # 新增 resolve_prediction_column()
scripts/export_interactive_dashboard_data.py    # 优先读 Round34 pkl
光伏功率预测项目.md                              # 重写，区分口径
```

### 新增输出文件（10 个）
```
output/pv_pipeline/metrics/round34_site_validity.csv
output/pv_pipeline/metrics/round34_site_count_summary.csv
output/pv_pipeline/metrics/round34_city_hourly_nrmse.csv
output/pv_pipeline/metrics/round34_site_hourly_nrmse.csv
output/pv_pipeline/metrics/round34_site_avg_hourly_nrmse.csv
output/pv_pipeline/metrics/round34_site_metrics.csv
output/pv_pipeline/metrics/round34_typical_sites.csv
output/pv_pipeline/metrics/round34_calibration_selection.csv
output/pv_pipeline/metrics/docs/Round34_指标口径与最终产物一致性验证报告.md
output/pv_pipeline/tables/distributed_predictions_final_round34.pkl
output/pv_pipeline/tables/distributed_predictions_final_eval_round34.pkl
```

---

## 六、执行顺序

```bash
python scripts/build_site_validity_round34.py
python scripts/apply_bias_calibration_round34.py
python scripts/compute_round34_metrics.py
python scripts/export_interactive_dashboard_data.py
python scripts/posttrain_validation_round34.py
```

---

## 七、验收标准核对

| 标准 | 结果 |
|------|------|
| posttrain_validation_round34.py 全部 PASS | ✅ 12/12 PASS |
| round34_site_count_summary.csv 自洽 | ✅ 118 = 68+50，68 = 14+5+37+12 |
| 城市 NRMSE 为 time 聚合口径 | ✅ city_hourly_nrmse 先 groupby time 再算 RMSE |
| round34_site_metrics.csv 使用 power_pred_final | ✅ 所有指标基于校准后字段 |
| round34_typical_sites.csv 无跨类重复 | ✅ 14站严格互斥 |
| 光伏功率预测项目.md 不含 Round33 错误数值 | ✅ 报告已重写，明确区分口径 |
| NRMSE 不重复乘100 | ✅ CSV 已是%，报告直接写% |
| 可视化默认不含 future | ✅ 脚本排除 split=="future" |
| 可视化预测值来自 power_pred_final | ✅ 优先读取含 power_pred_final 的 Round34 pkl |
