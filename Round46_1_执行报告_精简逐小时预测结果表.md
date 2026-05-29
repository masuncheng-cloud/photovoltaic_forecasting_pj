# Round46.1 执行报告：精简逐小时预测结果表

**执行时间**：2026-05-29 23:07 ~ 23:18 (UTC+8)
**执行人**：Cursor AI
**状态**：✅ 全部完成

---

## 1. 目标回顾

本次 Round46.1 只做**展示精简**，不改变训练结果、不改变最终预测列、不改变 NRMSE 计算口径。

删除以下 3 列：
- `站点中位 NRMSE（%）`
- `有效发电站点均NRMSE（%）`
- `平均0值占比（%）`

保留以下 4 列：
- `小时（时）`
- `样本数（行）`
- `站点平均 NRMSE（%）`
- `城市 NRMSE（%）`

---

## 2. 修改内容

### 2.1 页面文件修改

**文件**：`stages/05_visualization/interactive_forecast_dashboard.html`

| 位置 | 修改类型 | 说明 |
|---|---|---|
| 第 949-958 行（HTML 表头） | 删除列 | 删除了 `站点中位 NRMSE`、`有效发电站点均NRMSE`、`平均0值占比` 3 个 `<th>` |
| 第 964-966 行（表格说明） | 替换文字 | 说明改为"站点平均 NRMSE 按'先对每个站点在该小时计算 NRMSE，再对站点取平均'的口径统计" |
| 第 3312-3330 行（Tooltip 函数） | 精简内容 | 删除了 `站点中位 NRMSE`、`有效发电站点NRMSE` 的展示，样本数显示去掉站点数字后缀 |
| 第 3339-3357 行（表格渲染函数） | 删除列 | `colspan` 从 8 改为 4，TD 渲染去掉站点中位数、有效发电站均、0值占比 3 列 |

### 2.2 导出脚本修复

**文件**：`scripts/export_interactive_dashboard_data.py`

| 修复项 | 问题描述 | 修复方法 |
|---|---|---|
| `eval_df` UnboundLocalError | `elif csv_path.exists()` 分支内引用了未定义的 `eval_df` | 改为引用函数参数 `final_df` |
| 多日期 CSV 展开导致行数膨胀 | 当 CSV 含多个日期/小时行时，merge 展开行数 | 添加 `groupby("hour")` 聚合确保最终 14 行 |
| `round46_hourly_nrmse_consistent.csv` 未被优先读取 | 脚本查找 `round46_city_hourly_nrmse.csv`（不存在），导致 fallback 到 round36 PKL 计算错误口径 | 新增优先读取 `{round}_hourly_nrmse_consistent.csv` 的分支，直接使用 Round46 预计算的 NRMSE 数据 |

### 2.3 数据文件更新

**文件**：`output/pv_pipeline/interactive_dashboard/hourly_prediction_summary.json`

直接由 `round46_hourly_nrmse_consistent.csv` 生成，确保展示的是 Round46 正确口径的数据（不再经过 PKL 重新计算）。

---

## 3. 数据验收（10-14h 站点平均 NRMSE）

| 小时 | 实际值 | 方案预期值 | 差异 | 状态 |
|---:|---:|---:|---:|:---:|
| 10 | 13.786% | ~13.79% | 0.004 | ✅ PASS |
| 11 | 15.298% | ~15.30% | 0.002 | ✅ PASS |
| 12 | 16.145% | ~16.14% | 0.005 | ✅ PASS |
| 13 | 15.864% | ~15.86% | 0.004 | ✅ PASS |
| 14 | 13.818% | ~13.82% | 0.002 | ✅ PASS |

> 全部在 0.01pp 以内，数据口径与 Round46 完全一致，未回到旧错误口径（31%-37%）。

### 完整逐小时数据

| 小时 | 样本数 | 站点平均 NRMSE（%） | 城市 NRMSE（%） |
|---:|---:|---:|---:|
| 6  | 8296 | 3.719 | 1.461 |
| 7  | 8296 | 5.719 | 4.410 |
| 8  | 8296 | 7.423 | 2.911 |
| 9  | 8296 | 10.755 | 4.755 |
| 10 | 8296 | 13.786 | 6.910 |
| 11 | 8296 | 15.298 | 6.834 |
| 12 | 8296 | 16.145 | 6.970 |
| 13 | 8296 | 15.864 | 7.118 |
| 14 | 8296 | 13.818 | 6.593 |
| 15 | 8296 | 9.968 | 3.789 |
| 16 | 8296 | 6.609 | 2.022 |
| 17 | 8296 | 4.171 | 2.370 |
| 18 | 8296 | 3.816 | 1.591 |
| 19 | 8296 | 3.503 | 1.454 |

---

## 4. 验证脚本结果

### 4.1 `update_dashboard_after_training.py`

```
[PASS] Dashboard 刷新成功，85 个文件已更新
  city_series: PASS
  site_series: PASS
```

### 4.2 `check_dashboard_auto_update_stamp.py`

```
结果汇总：PASS=7, FAIL=0, WARN=0
[PASS] dashboard auto-update stamp 检查全部通过
```

| 检查项 | 状态 |
|---|:---:|
| refresh_detected | ✅ PASS |
| city_series_consistency | ✅ PASS |
| site_series_consistency | ✅ PASS |
| stamp_freshness | ✅ PASS |
| key_file_refreshed_city_series.json | ✅ PASS |
| key_file_refreshed_metadata.json | ✅ PASS |
| key_file_refreshed_typical_sites.json | ✅ PASS |

### 4.3 `round44_dashboard_regression_check.py`

```
结果：PASS=27, FAIL=0, WARN=0
[PASS] dashboard regression check 全部通过
```

27 项检查全部通过，覆盖：文件存在性、字段完整性、future 数据排除、季节数据、典型站点、site_series 文件数量等。

---

## 5. 页面验收方法

```bash
# 启动服务（如果未运行）
cd /home/ac/data16t/msc && python3 -m http.server 8070

# 访问页面
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html

# 强制刷新（清除缓存）
Ctrl + Shift + R
```

**验收点**：
- 逐小时预测结果表格只显示 4 列（小时、样本数、站点平均 NRMSE、城市 NRMSE）
- 不再出现站点中位 NRMSE、有效发电站点均NRMSE、平均0值占比 3 列
- 表格说明文字简洁明了
- 鼠标悬停 chart 或 table 行，tooltip 中无被删除的 3 个指标

---

## 6. 本轮不做

- ❌ 不重新训练模型
- ❌ 不修改最终预测列
- ❌ 不修改 NRMSE 计算公式
- ❌ 不删除导出 JSON 中的诊断辅助字段

---

## 7. 修改文件清单

| 文件路径 | 修改类型 | 说明 |
|---|---|---|
| `stages/05_visualization/interactive_forecast_dashboard.html` | 修改 | 表头、表格渲染、Tooltip、说明文字精简 |
| `scripts/export_interactive_dashboard_data.py` | 修复 | 修复 eval_df UnboundLocalError、多日期展开、优先读 consistent CSV |
| `output/pv_pipeline/interactive_dashboard/hourly_prediction_summary.json` | 重写 | 由 Round46 consistent CSV 生成，4 列格式 |
