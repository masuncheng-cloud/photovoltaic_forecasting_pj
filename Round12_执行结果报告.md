# Round12 执行结果报告

**日期：** 2026-05-25
**操作：** 执行 Round12 补充修改方案（站点总样本量与 NRMSE 关系图）

---

## 一、执行概况

| 项目 | 内容 |
|------|------|
| 修改文件 1 | `scripts/export_interactive_dashboard_data.py` |
| 修改文件 2 | `stages/05_visualization/interactive_forecast_dashboard.html` |
| 输出目录 | `output/pv_pipeline/interactive_dashboard/` |

---

## 二、第一次执行：脚本运行

### 2.1 命令

```bash
python scripts/export_interactive_dashboard_data.py \
  --output-root output/pv_pipeline \
  --dashboard-root output/pv_pipeline/interactive_dashboard
```

### 2.2 执行结果

| 指标 | 数值 |
|------|------|
| 数据源 | `distributed_predictions_final_full.pkl` |
| 数据总量 | 1,172,180 行 |
| 站点数 | 69 |
| 有效站点（含测试集数据） | 68 |
| 时间范围 | 2023-01-01 ~ 2026-03-31 |
| 训练/验证/测试有效行数（6-19时） | 596,939 行 |

### 2.3 新增输出文件

| 文件名 | 说明 | 状态 |
|--------|------|------|
| `scatter_site_sample_nrmse.json` | 站点级散点图数据（每点=1个站点） | ✅ 生成成功 |
| `sample_requirement_summary.json` | 达标阈值样本量分布表（5个阈值） | ✅ 生成成功 |
| `sample_requirement_bins.json` | 样本量分箱 NRMSE 统计（8个分箱） | ✅ 生成成功 |
| `scatter_site_hour.json` | 旧版站点-小时散点图（保留兼容） | ✅ 生成成功 |

### 2.4 散点图数据（`scatter_site_sample_nrmse.json`）

每行包含 19 个字段：

```
site_id, site_name, county, capacity_mw,
train_rows, valid_rows, train_valid_rows, train_valid_positive_rows,
train_valid_zero_ratio_pct,
test_rows, test_positive_rows,
test_mae_mw, test_rmse_mw, test_nrmse_pct, test_bias_pct, test_pred_actual_ratio,
category_label
```

数据口径：
- **横轴（样本量）**：来自训练集 + 验证集（`split` ∈ train/valid）
- **纵轴（NRMSE）**：来自测试集（`split` = test），仅 6-19 时有效样本

### 2.5 达标阈值样本量分布（`sample_requirement_summary.json`）

| NRMSE 阈值 | 达标站点数 | 总站点数 | 达标比例 | 正功率样本中位数 |
|-----------|-----------|---------|---------|--------------|
| ≤ 5% | 0 | 68 | 0% | - |
| ≤ 10% | 35 | 68 | 51.5% | 6,502 行 |
| ≤ 15% | 56 | 68 | 82.4% | 4,694 行 |
| ≤ 20% | 61 | 68 | 89.7% | 4,368 行 |
| ≤ 25% | 66 | 68 | 97.1% | 4,368 行 |

### 2.6 样本量分箱统计（`sample_requirement_bins.json`）

| 样本区间 | 站点数 | NRMSE 均值 | NRMSE 中位数 |
|---------|-------|-----------|------------|
| 0-1,000 | 4 | 34.4% | 23.1% |
| 1,000-3,000 | 25 | 15.2% | 10.1% |
| 3,000-6,000 | 10 | 11.8% | 9.6% |
| 6,000-10,000 | 10 | 14.5% | 11.7% |
| 10,000-15,000 | 19 | 11.3% | 8.9% |
| 15,000-20,000 | 0 | - | - |
| 20,000-26,000 | 0 | - | - |
| 26,000+ | 0 | - | - |

---

## 三、第二次修复：页面 JavaScript 变量作用域问题

### 3.1 问题描述

刷新页面后，散点图和下方两个表格均无显示。

### 3.2 根因分析

HTML 页面中，脚本使用顶级 `let` 声明变量：

```javascript
let gScatterSite = [];
let gSampleReqSummary = [];
let gSampleReqBins = [];
```

顶级 `let` 变量**不会自动挂载到 `window` 对象**，因此：

```javascript
// 在 drawScatterChart 函数内：
const chartData = (window.gScatterSite && window.gScatterSite.length > 0)
    ? window.gScatterSite    // ← 始终为 undefined！
    : (data || []);
```

导致代码 fallback 到旧数据结构（`sample_count` + `hour`），散点图无法渲染。

同样，`renderSampleReqSummaryTable()` 和 `renderSampleReqBinsTable()` 内部使用 `window.gSampleReqSummary` / `window.gSampleReqBins`，也为 `undefined`。

### 3.3 修复方案

将 4 处函数调用中的参数从 `gScatterData`（旧数据）改为 `gScatterSite`（新数据），并移除 `window.` 前缀：

| 位置 | 修复前 | 修复后 |
|------|-------|-------|
| `refreshAll()` 调用 | `drawScatterChart(gScatterData)` | `drawScatterChart(gScatterSite)` |
| resize handler 调用 | `drawScatterChart(gScatterData)` | `drawScatterChart(gScatterSite)` |
| xaxis toggle 调用 | `drawScatterChart(gScatterData)` | `drawScatterChart(gScatterSite)` |
| `drawScatterChart()` 内部 | `window.gScatterSite` | `gScatterSite` |
| `renderSampleReqSummaryTable()` | `window.gSampleReqSummary` | `gSampleReqSummary` |
| `renderSampleReqBinsTable()` | `window.gSampleReqBins` | `gSampleReqBins` |

### 3.4 修复文件

`stages/05_visualization/interactive_forecast_dashboard.html`

---

## 四、验收标准对照

| 验收项 | 要求 | 实际 | 状态 |
|--------|------|------|------|
| `scatter_site_sample_nrmse.json` 生成 | 必须存在 | 68 个站点，字段完整 | ✅ |
| `sample_requirement_summary.json` 生成 | 必须存在 | 5 个阈值行 | ✅ |
| `sample_requirement_bins.json` 生成 | 必须存在 | 8 个分箱 | ✅ |
| `train_valid_positive_rows` 字段 | 必须存在 | 存在于每行 | ✅ |
| `test_nrmse_pct` 字段 | 必须存在 | 存在于每行 | ✅ |
| 散点图每个点代表一个站点 | 是 | 是（68 点） | ✅ |
| 横轴名称"训练+验证正功率样本数（行）" | 是 | 是 | ✅ |
| 纵轴名称"测试集站点 NRMSE（%）" | 是 | 是 | ✅ |
| 阈值表标题"达到不同 NRMSE 阈值的站点样本量分布" | 是 | 是 | ✅ |
| 表格说明含"单站点累计训练+验证样本量" | 是 | 是 | ✅ |
| 页面刷新后图表/表格正常显示 | 是 | 是（修复后） | ✅ |

---

## 五、页面功能清单

| 功能 | 状态 |
|------|------|
| 全市/单站点折线图切换 | ✅ 正常 |
| 日期范围筛选 | ✅ 正常 |
| 小时范围筛选 | ✅ 正常 |
| 典型站点快速跳转（最好/最差/相对正确/样本少） | ✅ 正常 |
| 季节代表日跳转（春夏秋冬） | ✅ 正常 |
| 散点图横轴切换（总样本数 / 正功率样本数） | ✅ 正常 |
| 散点图 tooltip（站点ID、名称、容量、样本量、NRMSE、MAE、RMSE、pred/actual ratio） | ✅ 正常 |
| 达标阈值样本量分布表格 | ✅ 正常（修复后） |
| 样本量分箱 NRMSE 统计表格 | ✅ 正常（修复后） |
| 典型站点选择表格 | ✅ 正常 |

---

## 六、结论

本次 Round12 执行共修改 2 个文件，新增 3 个 JSON 数据文件，修复 1 个 JavaScript 变量作用域问题。所有验收标准均已通过，交互式预测结果页面功能完整。
