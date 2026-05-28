# Cursor 修改方案 Round29：统一全市 NRMSE 容量基准

## 一、修改目标

当前项目中单站点 NRMSE 已经使用容量归一化：

```text
单站点 NRMSE = RMSE_site / C_site × 100%
```

但可视化页面中的全市指标卡存在旧口径问题：

```js
const nrmse = isSite ? (rmse / capMean * 100) : rmse;
```

也就是说：

```text
单站点模式：NRMSE = RMSE / 容量 × 100%
全市模式：NRMSE = RMSE
```

这会导致全市指标卡的 NRMSE 实际不是 NRMSE。

本轮目标：

1. 全市 NRMSE 统一为：

```text
全市 NRMSE = RMSE_city_total / C_city_ref × 100%
```

2. `C_city_ref` 使用当前筛选范围内全市聚合容量 `capacity_sum_mw` 的稳定值，推荐使用：

```text
median(capacity_sum_mw)
```

而不是直接用 `mean(capacity_sum_mw)`。

3. 单站点 NRMSE 保持：

```text
单站点 NRMSE = RMSE_site / C_site × 100%
```

4. 页面说明同步修改。

本轮只修改指标计算和说明，不重新训练模型，不修改预测结果。

## 二、涉及文件

主要修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

可选同步修改：

```text
scripts/export_interactive_dashboard_data.py
src/pv_forecasting/core/evaluation.py
scripts/regenerate_project_report_round14.py
```

如果前端已拆分 JS/CSS，则同步修改对应文件。

## 三、全市容量基准定义

### 3.1 单站点

```text
C_site = 当前站点 capacity_mw
```

实际计算：

```js
C_site = median(rows.map(r => r.capacity_mw))
```

同一站点容量正常应固定，取 `median` 比 `mean` 更稳。

### 3.2 全市

```text
C_city_ref = 当前筛选范围内 capacity_sum_mw 的中位数
```

也就是：

```js
C_city_ref = median(rows.map(r => r.capacity_sum_mw))
```

理由：

- `city_series.json` 每一行是一个时间点的全市聚合。
- `capacity_sum_mw` 表示该时间点参与聚合站点的容量总和。
- 若个别时间点站点缺失，`capacity_sum_mw` 可能波动。
- 用中位数比均值更稳定，不容易被少数异常时间点影响。

如果项目后续希望用完全固定全市装机容量，可以在 `index.json` 中导出 `city_capacity_ref_mw`，但本轮先使用前端已有的 `capacity_sum_mw`。

## 四、前端新增 median 工具函数

在 `interactive_forecast_dashboard.html` 中 JS 工具函数区增加：

```js
function median(values) {
  const nums = values
    .map(v => Number(v))
    .filter(v => Number.isFinite(v))
    .sort((a, b) => a - b);

  if (!nums.length) return 0;

  const mid = Math.floor(nums.length / 2);
  if (nums.length % 2 === 1) {
    return nums[mid];
  }
  return (nums[mid - 1] + nums[mid]) / 2;
}
```

如果已有 `median` 函数，则复用，不要重复定义。

## 五、修改 `computeMetrics`

找到当前函数：

```js
function computeMetrics(rows, isSite) {
  ...
  const nrmse = isSite ? (rmse / Math.max(capMean, 1e-9) * 100) : rmse;
  ...
}
```

替换为下面逻辑：

```js
function computeMetrics(rows, isSite) {
  if (!rows || rows.length === 0) {
    return { samples: 0, sites: 0, actualSum: 0, predSum: 0,
             mae: 0, rmse: 0, nrmse: 0, bias: 0, ratio: 0,
             capacityRefMw: 0 };
  }

  const actuals = rows.map(r => Number(r.actual_mw)).filter(v => Number.isFinite(v));
  const preds = rows.map(r => Number(r.pred_mw)).filter(v => Number.isFinite(v));

  // 防止 actuals/preds 长度错位，按行循环计算误差
  let actualSum = 0;
  let predSum = 0;
  let maeSum = 0;
  let rmseSum = 0;
  let count = 0;

  for (const r of rows) {
    const actual = Number(r.actual_mw);
    const pred = Number(r.pred_mw);
    if (!Number.isFinite(actual) || !Number.isFinite(pred)) continue;

    const err = pred - actual;
    actualSum += actual;
    predSum += pred;
    maeSum += Math.abs(err);
    rmseSum += err * err;
    count += 1;
  }

  if (count === 0) {
    return { samples: 0, sites: 0, actualSum: 0, predSum: 0,
             mae: 0, rmse: 0, nrmse: 0, bias: 0, ratio: 0,
             capacityRefMw: 0 };
  }

  const mae = maeSum / count;
  const rmse = Math.sqrt(rmseSum / count);

  let capacityRefMw;
  if (isSite) {
    capacityRefMw = median(rows.map(r => r.capacity_mw));
  } else {
    capacityRefMw = median(rows.map(r => r.capacity_sum_mw));
  }

  const nrmse = capacityRefMw > 0
    ? rmse / capacityRefMw * 100
    : 0;

  const bias = (predSum - actualSum) / Math.max(actualSum, 1e-9) * 100;
  const ratio = predSum / Math.max(actualSum, 1e-9);

  const siteIds = new Set(rows.map(r => r.site_id).filter(Boolean));
  const siteCount = isSite
    ? 1
    : Math.max(...rows.map(r => Number(r.n_sites) || 0), siteIds.size, 0);

  return {
    samples: count,
    sites: siteCount,
    actualSum,
    predSum,
    mae,
    rmse,
    nrmse,
    bias,
    ratio,
    capacityRefMw,
  };
}
```

注意：

- 不要再保留 `: rmse` 作为全市 NRMSE。
- 全市和单站点都必须除以容量基准。
- `capacityRefMw` 返回出去，便于页面 tooltip 或说明展示。

## 六、如果已经使用 Round28 的单站点样本数逻辑

如果当前代码中 `samples` 已经改成：

```text
单站点显示 full_history_rows
全市显示 sum(sample_count)
```

请保留该逻辑，只替换 NRMSE 分母。

也就是说，可以在 `computeMetrics` 里保留：

```js
const sampleCount = isSite
  ? getSelectedSiteMetric()?.full_history_rows
  : sum(rows.map(r => r.sample_count));
```

但 NRMSE 必须改为：

```js
const capacityRefMw = isSite
  ? median(rows.map(r => r.capacity_mw))
  : median(rows.map(r => r.capacity_sum_mw));

const nrmse = capacityRefMw > 0
  ? rmse / capacityRefMw * 100
  : 0;
```

## 七、指标卡增加容量基准说明

建议给 NRMSE 卡片加 `title`：

```js
const nrmseCard = document.getElementById("m-nrmse")?.closest(".metric-card");
if (nrmseCard) {
  nrmseCard.title = "NRMSE = RMSE / 容量基准 × 100%。单站点容量基准为该站点装机容量；全市容量基准为当前筛选范围内 capacity_sum_mw 的中位数。";
}
```

如果页面支持小字说明，也可以显示：

```text
容量基准：xxx MW
```

示例：

```html
<div class="metric-card">
  <div class="label">NRMSE</div>
  <div class="value"><span id="m-nrmse">--</span><span class="unit">%</span></div>
  <div class="sub-value" id="m-nrmse-cap-ref"></div>
</div>
```

JS：

```js
const capRefEl = document.getElementById("m-nrmse-cap-ref");
if (capRefEl) {
  capRefEl.textContent = metrics.capacityRefMw
    ? `容量基准 ${fmt2(metrics.capacityRefMw)} MW`
    : "";
}
```

如果不想加小字，至少保留 `title`。

## 八、页面说明同步修改

把页面中关于 NRMSE 的说明统一改为：

```text
NRMSE = RMSE / 容量基准 × 100%。单站点容量基准为该站点装机容量；全市容量基准为当前筛选范围内全市聚合容量 capacity_sum_mw 的中位数。
```

如果有旧说明：

```text
城市 NRMSE 表示全市聚合功率在该小时的误差水平
```

可以补充：

```text
城市 NRMSE 的分母为该小时参与聚合站点总容量。
```

## 九、后端可选同步：逐小时城市 NRMSE

当前 `src/pv_forecasting/core/evaluation.py` 中 `city_hour_nrmse` 是：

```python
return abs(sum(pred) - sum(actual)) / sum(capacity) * 100
```

这其实是“城市总量归一化偏差”，不是严格 RMSE-NRMSE。

如果本轮只修页面指标卡，可以暂不动。

如果要同步严谨口径，建议新增函数，不直接覆盖旧函数：

```python
def city_hour_rmse_nrmse(df, pred_col="power_pred") -> float:
    city_by_time = df.groupby("time").agg(
        actual=("power_mw", "sum"),
        pred=(pred_col, "sum"),
        capacity=("capacity_mw", "sum"),
    ).reset_index()

    y = city_by_time["actual"].astype(float).to_numpy()
    p = city_by_time["pred"].astype(float).to_numpy()
    c_ref = float(city_by_time["capacity"].median())

    if c_ref <= 0:
        return np.nan

    rmse = float(np.sqrt(np.mean((p - y) ** 2)))
    return rmse / c_ref * 100
```

然后在报告里明确区分：

```text
城市 RMSE-NRMSE
城市总量归一化偏差
```

本轮前端优先修复即可。

## 十、验证示例

页面中选择：

```text
展示对象：全市
日期：2025-09-01 至 2025-09-30
小时：6-19
```

假设：

```text
RMSE = 23.29 MW
capacityRefMw = 390 MW
```

则：

```text
NRMSE = 23.29 / 390 × 100%
      = 5.97%
```

页面应显示约：

```text
NRMSE 5.97%
```

而不是：

```text
NRMSE 23.29%
```

## 十一、启动验证

```bash
cd /path/to/photovoltaic_forecasting_pj
python3 -m http.server 8060
```

打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

强制刷新：

```text
Ctrl + Shift + R
```

## 十二、验收标准

1. 单站点 NRMSE 仍等于：

```text
RMSE / 当前站点容量 × 100%
```

2. 全市 NRMSE 改为：

```text
RMSE_city_total / median(capacity_sum_mw) × 100%
```

3. 全市模式下 NRMSE 不再直接等于 RMSE。
4. NRMSE 卡片 tooltip 或说明中明确容量基准。
5. 指标卡中 RMSE 单位仍为 MW，NRMSE 单位为 %。
6. 不重新训练模型，不修改预测 pkl。

