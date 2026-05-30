# Round49 执行报告：样本量散点图新增"训练验证正功率样本"横轴

**执行时间**：2026-05-30 15:30 ~ 16:00 (UTC+8)
**执行人**：Cursor AI
**状态**：✅ 全部完成

---

## 1. 目标回顾

在可视化页面"单站点样本数与 NRMSE 关系"散点图的横轴中，新增"训练+验证阶段 6-19 点正功率样本量"选项，让分析更有价值（因为这个口径更接近模型实际可学习的有效发电样本）。

---

## 2. 修改内容

### 2.1 新增 `SAMPLE_X_AXIS_CONFIG` 配置对象

在 HTML 中定义横轴配置表：

```js
const SAMPLE_X_AXIS_CONFIG = {
  full: {        // 原"全量历史样本数"口径
    label: "全量历史样本数",
    field: "full_history_rows",
    axisLabel: "单站点全量历史样本数（行）",
    bins: [[0,5000], [5000,10000], ...],
  },
  tv_positive: { // 新增口径
    label: "训练验证正功率样本",
    field: "train_valid_positive_rows",
    axisLabel: "训练+验证阶段6-19点正功率样本量（行）",
    bins: [[0,1000],[1000,2000],[2000,3000],[3000,5000],[5000,8000],[8000,11000],[11000,∞]],
  }
};
```

### 2.2 新增动态数据计算函数

- `buildThresholdData(chartData, mode)` — 根据当前口径计算阈值表数据
- `buildBinsData(chartData, mode)` — 根据当前口径计算分箱表数据
- `recomputeThresholdAndBins()` — 统一重新计算两种口径的数据

两种口径的数据在页面加载时同时预计算，切换时无需重新读取 JSON。

### 2.3 新增按钮

```html
<button class="tab-btn" data-xaxis="tv_positive" title="统计 train + valid 阶段、6-19 点、真实功率 power_mw > 0 的样本数...">
  训练验证正功率样本
</button>
```

### 2.4 动态标题

| 口径 | 散点图标题 | 阈值表标题 | 分箱表标题 |
|------|-----------|-----------|-----------|
| 全量历史样本数 | 单站点全量历史样本数与测试集 NRMSE 关系 | 达到不同 NRMSE 阈值的全量历史样本量分布 | 按单站点全量历史样本数分箱的 NRMSE 分布 |
| 训练验证正功率样本 | 训练验证正功率样本量与测试集 NRMSE 关系 | 达到不同 NRMSE 阈值的训练验证正功率样本量分布 | 按训练验证正功率样本量分箱的 NRMSE 分布 |

### 2.5 tooltip 增强

新增显示字段：

```
训练验证6-19点正功率样本数：${train_valid_positive_rows} 行
```

tooltip 中始终展示两种口径的样本量，方便对比。

### 2.6 说明文字更新

```
横轴可切换为"训练验证正功率样本"：统计 train + valid 阶段 6-19 点 power_mw > 0 的样本数，
更接近模型实际可学习的数据规模。样本量只是经验参考，容量映射、异常0值、限电、遮挡和气象匹配仍会影响最终 NRMSE。
```

---

## 3. 验证结果

### 3.1 导出脚本结果

```
scatter_pts (site) = 67 有效站点的散点数据
train_valid_positive_rows 范围: 3 ~ 12,289
```

### 3.2 新字段存在于 JSON

`scatter_site_sample_nrmse.json` 中每条记录均包含 `train_valid_positive_rows` 字段。

### 3.3 Dashboard 验证

| 脚本 | 结果 |
|------|------|
| `check_dashboard_data_freshness.py` | ✅ 8/8 PASS |
| `check_dashboard_auto_update_stamp.py` | ✅ 7/7 PASS |
| `export_interactive_dashboard_data.py` | ✅ 成功（68站点，67有效散点）|

---

## 4. 修改文件清单

| 文件 | 修改类型 | 说明 |
|------|---------|------|
| `stages/05_visualization/interactive_forecast_dashboard.html` | 修改 | 新增配置、按钮、动态表格、横轴切换逻辑 |

---

## 5. 使用说明

1. 打开页面：http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
2. Ctrl+Shift+R 强制刷新
3. 在"横轴口径"按钮区域点击"训练验证正功率样本"
4. 散点图横轴、数值标签、标题、阈值表和分箱表均自动切换

### 数据分箱边界（训练验证口径）

| 区间 | 预期站点分布 |
|------|------------|
| 0-1000 | 数据严重不足的站点 |
| 1000-2000 | 数据偏少的站点 |
| 2000-3000 | 适度数据 |
| 3000-5000 | 较好数据 |
| 5000-8000 | 充足数据 |
| 8000-11000 | 充裕数据 |
| 11000+ | 最充足数据 |
