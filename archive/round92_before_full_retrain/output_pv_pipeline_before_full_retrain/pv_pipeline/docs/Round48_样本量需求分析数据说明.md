# Round48 样本量需求分析数据说明

## 生成文件

- `output/pv_pipeline/metrics/round48_station_data_requirement_analysis.csv`
- `output/pv_pipeline/docs/Round48_样本量需求分析数据说明.md`

## 数据来源

`output/pv_pipeline/tables/distributed_predictions_final_round36.pkl`
- 行数：1,172,180
- 站点数：69
- split 分布：{'train': 723007, 'test': 199104, 'future': 148885, 'valid': 101184}

## 统计口径

- **不包含** `future` split
- **历史样本** = train + valid + test
- **白天样本** = 小时 6-19
- **中午样本** = 小时 10-14
- **正功率样本** = power_mw > 0
- **NRMSE** = RMSE / capacity_mw × 100%
- **测试误差** 仅使用 test 集计算

## 字段说明

| 字段 | 说明 |
|------|------|
| `site_id` | 站点编号 |
| `site_name` | 站点名称（无 site_name 列时等于 site_id）|
| `capacity_mw` | 额定装机容量（中位数）|
| `history_samples_total` | 历史总样本数（不含 future）|
| `history_samples_6_19` | 历史白天样本数（6-19点）|
| `history_positive_samples_6_19` | 历史白天正功率样本数 |
| `history_zero_ratio_6_19` | 历史白天零值比例（%）|
| `*_samples_6_19` | train/valid/test 白天样本数 |
| `train_valid_*` | train + valid 合计 |
| `test_zero_ratio_6_19` | 测试集白天零值比例 |
| `test_missing_ratio_6_19` | 测试集白天缺失比例 |
| `test_negative_ratio_6_19` | 测试集白天负功率比例 |
| `test_mae_mw` | 测试集 MAE（MW）|
| `test_rmse_mw` | 测试集 RMSE（MW）|
| `test_nrmse_pct` | 测试集 NRMSE（%）|
| `test_bias_pct` | 测试集 BIAS（%）|
| `test_pred_actual` | 测试集 预测总量/实际总量 |
| `test_10_14_*` | 测试集 10-14点 同类指标 |
| `nrmse_h19_pct` | 测试集第 h 小时 NRMSE（%）|
| `ghi_power_corr` | clear_sky_ghi 与功率的 Pearson 相关系数 |
| `weather_missing_ratio` | clear_sky_ghi 缺失比例（%）|
| `capacity_changed_flag` | 容量是否变化（0/1）|
| `suspected_curtailment_flag` | 疑似限电旗标（需人工标注，当前为空）|
| `mapping_issue_flag` | 映射问题旗标（需人工标注，当前为空）|
| `all_zero_or_invalid_flag` | 全历史无正功率样本（0/1）|

## 注意事项

- `suspected_curtailment_flag` 和 `mapping_issue_flag` 当前需要人工判断，值均为空。
- 气象字段：仅含 clear_sky_ghi（理论晴空辐照）。ghi_power_corr 已计算，反映理论辐照与功率的相关性。原始 GHI、辐照、温度、风速等字段均不可用。

## 统计摘要

站点数：68

训练+验证样本（6-19点）：
  - 均值：7071
  - 中位数：4842
  - 最小：1411
  - 最大：13636

测试集 NRMSE（6-19点）：
  - 均值：10.94%
  - 中位数：9.67%

测试集 NRMSE（10-14点）：
  - 均值：15.04%
  - 中位数：13.56%
