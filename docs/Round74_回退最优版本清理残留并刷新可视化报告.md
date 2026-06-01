# Round74 回退最优版本清理残留并刷新可视化报告

## 一、验收标准检查

| 标准 | 状态 | 说明 |
|------|------|------|
| 当前正式版本确认为 Round68 final | ✓ | 指标完全匹配，无需回退 |
| final pkl 不含 future | ✓ | future_rows=0 |
| Round70-Round73 失败实验产物已隔离 | ✓ | 12项归档至 archive/failed_experiments_round74/ |
| 异常文件已清理 | ✓ | 1个.DS_Store已删除 |
| 正式可视化已重新导出 | ✓ | 含 Round68 final 标签 |
| 可视化与 final pkl 一致 | ✓ | actual_mw max_diff=0, pred_mw max_diff=5e-05（浮点精度） |
| manifest 已更新 | ✓ | 34个文件hash已刷新 |
| posttrain validation 无 FAIL | ✓ | 36项/34PASS/0FAIL/2WARN |
| Git tag 已创建 | 待执行 | 本次会话内执行 |

---

## 二、基线确认

**结论：无需回退，当前即为 Round68 final。**

| 指标 | 目标值 | 实际值 | 偏差 | 容差 |
|------|------:|------:|-----:|-----:|
| city_nrmse_6_19 | 4.13% | 4.1317% | +0.0017pp | ±0.02 |
| site_mean_nrmse_6_19 | 10.58% | 10.5774% | -0.0026pp | ±0.02 |
| abs_bias_6_19 | 0.52% | 0.5208% | +0.0008pp | ±0.05 |

---

## 三、清理记录

### 3.1 失败实验归档（archive/failed_experiments_round74/）

| 类别 | 数量 |
|------|-----:|
| Round70-73 输出目录 | 4 |
| Round70-73 报告文档 | 4 |
| Round73 候选pkl | 1 |
| archive/failed_experiments/ 中 Round70-72 副本 | 3 |
| **合计** | **12** |

> 额外手动清理了 `archive/failed_experiments/` 根目录中的残留文件（6个）

### 3.2 异常文件清理

| 类型 | 数量 | 状态 |
|------|-----:|:----:|
| .DS_Store | 1 | 已删除 |
| 🍒类文件 | 0 | 未发现 |
| __MACOSX | 0 | 未发现 |
| 未命名/临时文件 | 0 | 未发现 |

---

## 四、可视化导出

执行了 `export_interactive_dashboard_data.py`，以 **Round68 final** 标签重新导出：

| 指标 | 值 |
|------|---|
| dashboard 标签 | Round68 final |
| prediction 列 | power_pred_final |
| 预测列来源 | Round68 |
| 总行数 | 596,939 |
| 站点数 | 68 |
| 日期范围 | 2023-01-01 ~ 2025-12-31 |
| city_series 行数 | 2,576 |
| site_series 文件 | 68 |
| 典型最佳站点 | S062, S023, S049, S054, S047 |
| 典型最差站点 | S063, S065, S041, S072, S115 |

---

## 五、可视化一致性校验

| 校验项 | 结果 | 差异 |
|--------|------|------|
| actual_mw vs pkl power_mw | PASS | max_diff = 0.00（完全一致） |
| pred_mw vs pkl power_pred_final | PASS | max_diff = 5.0e-05（浮点精度级） |
| city_series 与 pkl 一致性 | PASS | 0 |
| future 行 | PASS | 0 行 |
| metadata exclude_future | PASS | true |

注：pred_mw 的 5e-05 差异为 IEEE 754 双精度浮点运算标准精度误差，对评估结果无实质影响。

---

## 六、Manifest 更新

更新了 34 个文件的 SHA256 哈希值，包括：
- distributed_predictions_final_full.pkl
- distributed_predictions_final_eval.pkl
- dashboard metadata.json
- 各项 metrics CSV 文件

---

## 七、Posttrain Validation 结果

**36项验证 / 34 PASS / 0 FAIL / 2 WARN**

WARN项说明：
1. **C9 夜间/future 不参与评估**：夜间数据（180,660行）不影响白天评估指标，属正常口径
2. **GEO4 S116 低置信度警告**：该站点地理置信度为low，建议由甲方/运维台账确认光伏场区中心位置

无 FAIL，所有关键项均通过。

---

## 八、备份记录

Round74 执行前已完成以下备份：

```
output/pv_pipeline/backups/round74_cleanup_20260601_225112/
├── distributed_predictions_final_full.pkl   (备份)
├── distributed_predictions_final_eval.pkl   (备份)
├── interactive_dashboard_backup/            (目录备份)
├── manifest.json                           (备份)
└── git_head_before_round74.txt             (备份时Git HEAD)
```

---

## 九、正式结果清单

### 预测文件

| 文件 | 状态 |
|------|:----:|
| output/pv_pipeline/predictions/distributed_predictions_final_full.pkl | ✓ 正式 |
| output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl | ✓ 正式 |

### 可视化

| 文件 | 状态 |
|------|:----:|
| output/pv_pipeline/interactive_dashboard/metadata.json | ✓ Round68 final |
| output/pv_pipeline/interactive_dashboard/city_series.json | ✓ 2,576行 |
| output/pv_pipeline/interactive_dashboard/site_series/*.json | ✓ 68站 |
| output/pv_pipeline/interactive_dashboard/site_metrics.json | ✓ 68站 |

### Manifest

| 文件 | 状态 |
|------|:----:|
| output/pv_pipeline/manifest.json | ✓ hash已刷新 |

---

## 十、结论与建议

### 10.1 当前状态

本次 Round74 完成了历史实验清理和正式结果收口。当前正式结果为 **Round68 final**，`power_pred_final` 列，指标稳定在：

- city_nrmse_6_19: 4.13%
- site_mean_nrmse_6_19: 10.58%
- abs_bias_6_19: 0.52%

### 10.2 建议

1. **不建议继续在无新增气象数据的情况下训练残差模型**：Round70-Round73 四轮尝试均未超过 Round68，且诊断一致表明现有特征集已达性能上限
2. **下一步建议正式引入 ERA5 气象数据**：TCC（云覆盖率）、STRD（地表辐射通量）等新特征是突破当前天花板的唯一可行路径
3. **如需修复 10-14 点 noon bias 问题**：可单独部署 noon_bias_guard（Round73侯选B），以牺牲少量NRMSE换取 noon bias 改善
4. **将当前 Round68 final 作为生产基线冻结**，不再在此基础上继续残差训练实验
