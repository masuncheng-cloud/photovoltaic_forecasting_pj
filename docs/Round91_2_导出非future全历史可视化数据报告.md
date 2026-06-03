# Round91_2 导出非 future 全历史可视化数据报告

## 1. 问题

日期框显示全年，但 city_series / site_series 实际只从 2025-07-01 开始（仅 2,576 行），
没有 2025 年春季数据（3-5 月），导致春季按钮不可用。
根因：`power_pred_final` 在 train split（2023-01-01 ~ 2025-06-30）无数据，
旧的 `resolve_prediction_column()` 只选一个列，导致 train 段数据被丢弃。

## 2. 修改

### 2.1 新增 `build_full_history_frame()`

每个 split 用最优预测列：
- **train（2023-01-01 ~ 2025-06-30）**：使用 `power_pred_cal`
- **valid（2025-07-01 ~ 2025-08-31）**：使用 `power_pred_final`
- **test（2025-09-01 ~ 2025-12-31）**：使用 `power_pred_final`

统一输出 `actual_mw` / `pred_mw` 列，排序后返回。

### 2.2 所有导出函数改为使用 `full_history_df`

`export_city_series`、`export_site_series`、`export_midday_city`、`export_season_days`、
`export_season_best_days_city`、`export_season_best_days_by_site`、`export_scatter_site_hour`、
`export_scatter_site_sample_nrmse`、`export_hourly_prediction_summary` 均改为传入 `full_history_df`。

### 2.3 新增 `validate_dashboard_full_history()`

在 main() 末尾调用，将导出覆盖情况写入 `full_history_coverage_check.json`：
- scope、city_rows、min_date、max_date
- has_2025_spring、spring_2025_rows
- season_coverage_2025（四季 2025 年数据行数）
- split_counts（train/valid/test 分布）

### 2.4 metadata 增加覆盖字段

`write_metadata()` 新增：
- `dashboard_data_scope: "non_future_full_history"`
- `include_future: false`
- `min_date`、`max_date`（来自 full_history_df）
- `has_2025_spring`

## 3. 导出覆盖范围

| 指标 | 旧导出 | 新导出 |
|------|--------|--------|
| city_series 行数 | 2,576 | 15,344 |
| 最早日期 | 2025-07-01 | 2023-01-01 |
| 最新日期 | 2025-12-31 | 2025-12-31 |
| has_2025_spring | False | **True** |
| spring 2025 行数 | 0 | **1,288** |
| future 行数 | 0 | 0 |

### 2025 年四季数据（城市级小时聚合）

| 季节 | 天数 | 状态 |
|------|------|------|
| 春季（3-5月） | 276 天 | ✅ 可用 |
| 夏季（6-8月） | 276 天 | ✅ 可用 |
| 秋季（9-11月） | 273 天 | ✅ 可用 |
| 冬季（12,1,2月） | 271 天 | ✅ 可用 |

### 四季最佳代表日

| 季节 | 代表日 | NRMSE% |
|------|--------|---------|
| 春季 | 2025-03-02 | 1.30% |
| 夏季 | 2024-08-12 | 1.39% |
| 秋季 | 2024-10-30 | 1.16% |
| 冬季 | 2025-12-28 | 0.92% |

## 4. 验证

- ✅ future 数据已排除（city_series 中 future rows = 0）
- ✅ city_series 覆盖范围 2023-01-01 ~ 2025-12-31
- ✅ site_series 包含 train/valid/test 全历史（部分站点因 train 期无数据，起始日期各有不同）
- ✅ `full_history_coverage_check.json` 已写入
- ✅ `metadata.json` 包含 `has_2025_spring = true`
- ✅ 春季数据 1,288 行，四季按钮均可点击

## 5. 影响

本轮只修改可视化数据导出口径，不改变训练结果、不重训、不改模型。

## 6. 回退方案

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

cp archive/round91_2_export_non_future_full_history/current_state/export_interactive_dashboard_data.before_round91_2.py \
  scripts/export_interactive_dashboard_data.py

cp archive/round91_2_export_non_future_full_history/current_state/interactive_forecast_dashboard.before_round91_2.html \
  stages/05_visualization/interactive_forecast_dashboard.html

rm -rf output/pv_pipeline/interactive_dashboard
cp -a archive/round91_2_export_non_future_full_history/current_state/interactive_dashboard.before_round91_2 \
  output/pv_pipeline/interactive_dashboard
```

## 7. 修改文件清单

| 文件 | 操作 |
|------|------|
| `scripts/export_interactive_dashboard_data.py` | 修改 |
| `stages/05_visualization/interactive_forecast_dashboard.html` | 未改（Round91_1 已完成） |

## 8. 访问地址

```
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round91_2
```

（强制刷新：Ctrl+Shift+R）

建议：页面默认日期为 2025-09-01 ~ 2025-12-31（测试期），四季均可点击。
如需查看春季数据，手动将日期改为 2025-03-01 ~ 2025-05-31，春季按钮应可点击。
