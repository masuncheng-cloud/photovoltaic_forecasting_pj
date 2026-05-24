# Cursor 可执行方案 Round12：基于现有训练结果生成交互式预测结果页面

## 0. 本轮目标

在**不重新训练模型、不修改 final/best 预测结果**的前提下，基于当前项目已有产物生成一个可交互页面，用于展示：

1. 横坐标为时间、纵坐标为功率的折线图。
2. 同一坐标系中同时展示两条线：
   - 真实功率 `power_mw`
   - 预测功率 `power_pred`
3. 支持选择：
   - 全市总出力
   - 单个站点
   - 时间范围
   - 典型站点：预测最好、预测最差、相对正确、样本少
   - 典型时段：连云港全市 10-14 点
   - 典型日期：按四季各选一天，若当前数据中某季无数据则显示“暂无该季数据”
4. 增加散点图：
   - 横轴：样本量
   - 纵轴：NRMSE 或容量归一化误差
   - 点：站点-小时组合
   - 标注 5%、10%、15%、20% 等误差参考线
   - 给出达到 5%、10%、15% 误差阈值时，对应样本量统计

本轮只新增可视化页面和数据导出脚本，不参与模型晋级，不覆盖 `distributed_predictions_final_eval.pkl`、`best_predictions_eval.pkl` 等核心结果文件。

---

## 1. 当前项目可直接使用的数据文件

Cursor 请基于以下文件生成页面数据：

```text
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
output/pv_pipeline/tables/site_master.csv
output/pv_pipeline/metrics/round10_site_hour_nrmse.csv
output/pv_pipeline/metrics/round10_hour_overall_nrmse.csv
output/pv_pipeline/metrics/round10_overall_nrmse_summary.csv
```

优先读取：

```text
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
```

如果 full 文件不存在或读取失败，再回退到：

```text
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
```

读取后必须校验至少包含以下列：

```text
time
site_id
power_mw
power_pred
capacity_mw
hour
date
split
```

如缺少 `hour` 或 `date`，从 `time` 重新生成。

---

## 2. 新增文件

请新增以下文件：

```text
scripts/export_interactive_dashboard_data.py
stages/05_visualization/interactive_forecast_dashboard.html
```

并在已有文件中补充说明：

```text
stages/05_visualization/README.md
```

---

## 3. 数据导出脚本要求

新增脚本：

```text
scripts/export_interactive_dashboard_data.py
```

### 3.1 脚本运行方式

支持如下命令：

```bash
python scripts/export_interactive_dashboard_data.py \
  --output-root output/pv_pipeline \
  --dashboard-root output/pv_pipeline/interactive_dashboard
```

### 3.2 输出目录结构

脚本运行后生成：

```text
output/pv_pipeline/interactive_dashboard/
├── index.json
├── city_series.json
├── site_metrics.json
├── scatter_site_hour.json
├── error_threshold_summary.json
├── season_days.json
├── midday_city_by_date.json
└── site_series/
    ├── S001.json
    ├── S002.json
    └── ...
```

### 3.3 数据过滤口径

导出页面数据时统一使用以下口径：

```python
df = df[df["split"].isin(["train", "valid", "test"])]
df = df[df["hour"].between(6, 19)]
df = df[df["power_mw"].notna()]
df = df[df["power_pred"].notna()]
```

说明：

- 页面用于展示已有训练/验证/测试数据上的模型表现。
- 不展示 `future` 数据。
- 不展示夜间 0-5 点和 20-23 点，因为夜间光伏功率大量为 0，会压缩白天曲线。

### 3.4 全市曲线数据 `city_series.json`

按 `time` 聚合：

```python
city = df.groupby("time").agg(
    actual_mw=("power_mw", "sum"),
    pred_mw=("power_pred", "sum"),
    n_sites=("site_id", "nunique"),
    sample_count=("site_id", "size"),
    capacity_sum_mw=("capacity_mw", "sum"),
).reset_index()
```

同时保留：

```text
time
date
hour
split
actual_mw
pred_mw
n_sites
sample_count
capacity_sum_mw
abs_error_mw
city_nrmse_point_pct
```

其中：

```python
abs_error_mw = abs(pred_mw - actual_mw)
city_nrmse_point_pct = abs_error_mw / max(capacity_sum_mw, 1e-9) * 100
```

注意：这里是单时刻城市归一化误差，用于页面展示，不替代正式报告中的整体 NRMSE。

### 3.5 单站点曲线数据 `site_series/Sxxx.json`

每个站点单独导出一个 JSON，避免一次性加载所有站点数据导致浏览器卡顿。

每个文件至少包含：

```text
time
date
hour
split
site_id
site_name
actual_mw
pred_mw
capacity_mw
abs_error_mw
point_nrmse_pct
```

其中：

```python
point_nrmse_pct = abs(power_pred - power_mw) / max(capacity_mw, 1e-9) * 100
```

### 3.6 站点指标 `site_metrics.json`

按站点统计：

```text
site_id
site_name
county
capacity_mw
rows
positive_rows
zero_rows
zero_ratio_pct
mae_mw
rmse_mw
nrmse_pct
bias_pct
pred_actual_ratio
category
category_label
```

计算公式：

```python
mae_mw = mean(abs(pred - actual))
rmse_mw = sqrt(mean((pred - actual) ** 2))
nrmse_pct = rmse_mw / mean(capacity_mw) * 100
bias_pct = (sum(pred) - sum(actual)) / max(sum(actual), 1e-9) * 100
pred_actual_ratio = sum(pred) / max(sum(actual), 1e-9)
zero_ratio_pct = zero_rows / rows * 100
```

### 3.7 典型站点分类规则

在 `site_metrics.json` 中增加 `category` 和 `category_label`。

分类规则如下：

#### 预测最好 best

```python
rows >= max(200, rows_quantile_20)
positive_rows >= 100
nrmse_pct 最低的前 5 个站点
```

标记：

```text
category = "best"
category_label = "预测最好"
```

#### 预测最差 worst

```python
rows >= max(200, rows_quantile_20)
positive_rows >= 100
nrmse_pct 最高的前 5 个站点
```

标记：

```text
category = "worst"
category_label = "预测最差"
```

#### 相对正确 normal

从剩余站点中挑选 5 个：

```python
abs(pred_actual_ratio - 1.0) 最小
且 nrmse_pct 低于站点中位数
```

标记：

```text
category = "normal"
category_label = "相对正确"
```

#### 样本少 low_sample

按 `rows` 从小到大挑选 5 个站点。

标记：

```text
category = "low_sample"
category_label = "样本少"
```

注意：

- 不再标注“0 值多”“0 值偏多”等描述。
- 只允许出现：`预测最好`、`预测最差`、`相对正确`、`样本少`。
- 如果某站点同时满足多个类别，优先级为：

```text
样本少 > 预测最差 > 预测最好 > 相对正确
```

### 3.8 典型时段数据 `midday_city_by_date.json`

统计连云港全市 10-14 点逐日表现。

筛选：

```python
midday = df[df["hour"].between(10, 14)]
```

按 `date` 聚合：

```text
date
actual_mwh
pred_mwh
capacity_mw_sum
sample_count
n_sites
mae_mw
rmse_mw
nrmse_pct
bias_pct
pred_actual_ratio
```

其中：

```python
nrmse_pct = rmse_mw / mean(capacity_mw) * 100
```

页面中提供“连云港全市 10-14 点”快捷按钮，点击后自动：

1. scope 设为 city；
2. 小时范围设为 10-14；
3. 日期范围设为用户选择日期当天；
4. 折线图只显示当天 10-14 点的真实值与预测值。

### 3.9 四季典型日期 `season_days.json`

按月份定义四季：

```text
春季：3,4,5
夏季：6,7,8
秋季：9,10,11
冬季：12,1,2
```

对每个季节，在有数据的日期中选择一个代表日：

1. 只使用 6-19 点数据。
2. 优先选择站点数覆盖较完整的日期。
3. 在覆盖较完整日期中，选择全市日发电量接近该季节日发电量中位数的日期。

输出：

```text
season
season_label
date
available
actual_mwh
pred_mwh
n_sites
sample_count
reason
```

如果某季节没有数据：

```json
{
  "season": "spring",
  "season_label": "春季",
  "available": false,
  "reason": "当前 final 数据中没有 3-5 月记录"
}
```

页面中“四季一天”按钮只展示 available=true 的季节； unavailable 的季节置灰。

### 3.10 散点图数据 `scatter_site_hour.json`

每个点代表一个 `site_id + hour` 组合。

输出字段：

```text
site_id
site_name
hour
sample_count
capacity_mw
mae_mw
rmse_mw
nrmse_pct
bias_pct
pred_actual_ratio
category_label
```

计算：

```python
group = df.groupby(["site_id", "hour"])
rmse_mw = sqrt(mean((pred - actual)^2))
nrmse_pct = rmse_mw / mean(capacity_mw) * 100
sample_count = len(group)
```

页面散点图：

- 横轴：`sample_count`
- 纵轴：`nrmse_pct`
- 颜色：站点类别
- hover 显示：站点名、小时、样本量、NRMSE、MAE、RMSE、pred/actual ratio
- 增加水平参考线：5%、10%、15%、20%
- 可切换：
  - 全部小时
  - 10-14 点
  - 单个小时

### 3.11 误差阈值与样本量 `error_threshold_summary.json`

基于 `scatter_site_hour.json` 生成阈值表。

阈值：

```text
5%, 10%, 15%, 20%, 25%
```

对每个阈值输出：

```text
threshold_pct
qualified_points
total_points
qualified_ratio_pct
min_sample_count
p25_sample_count
median_sample_count
p75_sample_count
note
```

含义：

- `qualified_points`：NRMSE 不高于该阈值的站点-小时点数量。
- `qualified_ratio_pct`：满足该阈值的点占全部点比例。
- `min_sample_count`：满足该阈值的点中最小样本数。
- `median_sample_count`：满足该阈值的点中位样本数。

注意：这里不是因果结论，不能写成“只要达到多少样本就一定能达到某误差”。页面说明写成：

```text
该表表示在当前数据和模型结果中，达到指定误差阈值的站点-小时组合通常具备的样本量分布，不代表样本量是唯一决定因素。
```

---

## 4. 页面功能要求

新增页面：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

页面必须是一个静态 HTML 文件，通过浏览器访问：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

页面通过 `fetch()` 读取：

```text
../../output/pv_pipeline/interactive_dashboard/index.json
../../output/pv_pipeline/interactive_dashboard/city_series.json
../../output/pv_pipeline/interactive_dashboard/site_metrics.json
../../output/pv_pipeline/interactive_dashboard/scatter_site_hour.json
../../output/pv_pipeline/interactive_dashboard/error_threshold_summary.json
../../output/pv_pipeline/interactive_dashboard/season_days.json
../../output/pv_pipeline/interactive_dashboard/midday_city_by_date.json
../../output/pv_pipeline/interactive_dashboard/site_series/Sxxx.json
```

### 4.1 页面布局

页面分为 5 个区域：

#### 顶部控制区

包含：

```text
展示对象：全市 / 单站点
站点选择：下拉框
典型站点：预测最好 / 预测最差 / 相对正确 / 样本少
日期开始
日期结束
小时开始
小时结束
快捷按钮：连云港全市10-14
快捷按钮：春季 / 夏季 / 秋季 / 冬季
刷新按钮
```

#### 指标卡片区

根据当前选择动态显示：

```text
样本数
站点数
实际总电量 MWh
预测总电量 MWh
pred/actual ratio
MAE MW
RMSE MW
NRMSE %
bias %
```

#### 折线图区

展示：

```text
真实功率 MW
预测功率 MW
```

要求：

- 横轴为时间。
- 纵轴为功率 MW。
- 全市时显示全市总功率。
- 单站点时显示该站点功率。
- 支持 tooltip，显示时间、真实值、预测值、误差。
- 当选择日期范围太长时，不要求每个点都显示标签，但 tooltip 要正常。

#### 典型站点表

表格展示站点：

```text
类别
站点ID
站点名称
容量 MW
样本数
正功率样本数
0值占比 %
MAE MW
RMSE MW
NRMSE %
pred/actual ratio
```

点击表格中某个站点时：

1. 展示对象切换为单站点。
2. 站点下拉框切换到该站点。
3. 折线图刷新。

#### 散点图区

展示误差-样本量散点图。

要求：

- 横轴：样本数。
- 纵轴：NRMSE %。
- 加水平线：5%、10%、15%、20%。
- 鼠标悬浮显示站点、小时、样本数、NRMSE。
- 右侧或下方显示误差阈值样本量表。

### 4.2 前端实现方式

优先使用原生 HTML + CSS + JavaScript + SVG，不依赖外网 CDN。

如果 Cursor 认为实现时间过长，可以使用 Plotly CDN，但必须保留降级说明：

```html
<!-- 若服务器无法访问外网，Plotly CDN 可能无法加载；建议优先使用原生 SVG 实现。 -->
```

推荐直接实现 2 个轻量 SVG 绘图函数：

```javascript
drawLineChart(svgElement, rows, options)
drawScatterChart(svgElement, rows, options)
```

不需要复杂动画，重点是数据准确、筛选逻辑正确。

### 4.3 页面样式要求

整体风格：

- 白底或浅灰底。
- 控件清晰。
- 图表区域足够宽。
- 不要做营销式首页。
- 不要用大面积渐变背景。
- 表格单元格居中。
- 单位必须写清楚：MW、MWh、%、行。

---

## 5. 关键实现细节

### 5.1 时间筛选

前端筛选逻辑：

```javascript
row.date >= startDate
row.date <= endDate
row.hour >= startHour
row.hour <= endHour
```

如果没有选择日期，默认使用 `index.json` 中的：

```text
default_start_date
default_end_date
```

建议默认显示测试集第一天或最近一周。

### 5.2 全市与单站点切换

全市：

```javascript
load city_series.json
```

单站点：

```javascript
load site_series/{site_id}.json
```

站点数据做缓存：

```javascript
const siteSeriesCache = {};
```

避免重复请求。

### 5.3 快捷选择“连云港全市 10-14”

点击后：

```javascript
scope = "city"
startHour = 10
endHour = 14
date = 当前日期选择框的日期，如果为空，则取 midday_city_by_date.json 中 NRMSE 最接近中位数的一天
startDate = date
endDate = date
```

### 5.4 四季一天

点击春/夏/秋/冬按钮：

```javascript
读取 season_days.json
如果 available=false，则按钮禁用并显示 reason
如果 available=true，则 startDate=endDate=该季节代表日
hour=6-19
scope=city
```

### 5.5 指标动态计算

页面当前筛选结果中的指标前端实时计算：

```javascript
actualSum = sum(actual_mw)
predSum = sum(pred_mw)
mae = mean(abs(pred_mw - actual_mw))
rmse = sqrt(mean((pred_mw - actual_mw)^2))
nrmse = rmse / mean(capacity_mw or capacity_sum_mw) * 100
bias = (predSum - actualSum) / max(actualSum, 1e-9) * 100
ratio = predSum / max(actualSum, 1e-9)
```

注意：

- 折线图纵轴单位是 MW。
- 指标卡片中的电量近似按小时数据求和，单位写成 MWh。
- 页面说明中注明：当前数据是小时级，`sum(MW)` 在小时粒度下可近似理解为 MWh。

---

## 6. Cursor 具体执行步骤

请在 Cursor 项目根目录执行以下步骤。

### Step 1：新增数据导出脚本

创建：

```text
scripts/export_interactive_dashboard_data.py
```

要求：

1. 使用 `argparse`。
2. 使用 `pandas`、`numpy`、`json`，不要引入新依赖。
3. 输出 JSON 前将 `Timestamp` 转为字符串。
4. 所有浮点数保留 4-6 位即可，避免 JSON 过大。
5. 每个站点单独写入 `site_series/{site_id}.json`。
6. 运行结束打印：

```text
[OK] interactive dashboard data exported
rows=...
sites=...
date_range=... ~ ...
city_series=...
site_series_files=...
scatter_points=...
```

### Step 2：新增 HTML 页面

创建：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

要求：

1. 页面标题：`光伏功率预测交互式结果页面`
2. 图例：
   - 真实值：蓝色
   - 预测值：橙色
3. 散点图：
   - 预测最好：绿色
   - 预测最差：红色
   - 相对正确：蓝色
   - 样本少：灰色
   - 其他：浅灰
4. 所有指标均带单位。
5. 表格单元格居中。
6. 页面底部写明数据来源：

```text
数据来源：output/pv_pipeline/tables/distributed_predictions_final_full.pkl 或 distributed_predictions_final_eval.pkl。
页面只用于展示当前 final/best 预测结果，不参与模型训练和模型选择。
```

### Step 3：更新 README

在：

```text
stages/05_visualization/README.md
```

追加：

```markdown
## 交互式预测结果页面

生成数据：

```bash
python scripts/export_interactive_dashboard_data.py \
  --output-root output/pv_pipeline \
  --dashboard-root output/pv_pipeline/interactive_dashboard
```

启动本地服务：

```bash
python -m http.server 8060
```

浏览器打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

页面支持全市/单站点真实值与预测值对比、典型站点选择、10-14 点典型时段、四季代表日、误差-样本量散点图。
```

注意：README 的 Markdown 代码块要正确闭合。

### Step 4：运行导出

```bash
python scripts/export_interactive_dashboard_data.py \
  --output-root output/pv_pipeline \
  --dashboard-root output/pv_pipeline/interactive_dashboard
```

### Step 5：启动页面

```bash
python -m http.server 8060
```

打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

---

## 7. 验收标准

### 7.1 文件存在

执行后必须存在：

```text
output/pv_pipeline/interactive_dashboard/index.json
output/pv_pipeline/interactive_dashboard/city_series.json
output/pv_pipeline/interactive_dashboard/site_metrics.json
output/pv_pipeline/interactive_dashboard/scatter_site_hour.json
output/pv_pipeline/interactive_dashboard/error_threshold_summary.json
output/pv_pipeline/interactive_dashboard/season_days.json
output/pv_pipeline/interactive_dashboard/midday_city_by_date.json
output/pv_pipeline/interactive_dashboard/site_series/
stages/05_visualization/interactive_forecast_dashboard.html
```

### 7.2 数据正确性

Cursor 请新增一个轻量校验片段，或直接在脚本末尾校验：

```python
assert len(city_series) > 0
assert len(site_metrics) > 0
assert len(scatter_site_hour) > 0
assert actual_mw and pred_mw columns are not all zero
assert at least one site_series json exists
```

### 7.3 页面交互

人工检查：

1. 默认打开后能看到全市真实值和预测值两条线。
2. 切换单站点后，曲线变为该站点数据。
3. 选择日期范围后，折线图随之变化。
4. 点击“连云港全市10-14”后，只显示 10-14 点。
5. 点击预测最好/最差/相对正确/样本少站点，能够切换到对应站点曲线。
6. 四季按钮中，有数据的季节可点击，无数据的季节置灰。
7. 散点图能显示误差-样本量关系，并有 5%、10%、15%、20% 参考线。
8. 误差阈值表能显示不同误差阈值下的样本量统计。

---

## 8. 不允许做的事

本轮不要做以下操作：

1. 不要重新训练模型。
2. 不要修改 `distributed_predictions_final_eval.pkl`。
3. 不要修改 `best_predictions_eval.pkl`。
4. 不要删除 Round10/Round11 的 best guard 文件。
5. 不要把该页面生成的展示指标反写到正式训练报告中。
6. 不要把 `future` 数据混入页面默认评估。

---

## 9. 推荐提交说明

完成后提交说明可以写：

```text
Round12: add interactive forecast dashboard for city/site prediction review

- export final prediction data to dashboard JSON files
- add static interactive HTML page for actual vs predicted power curves
- support city/site selection, date/hour filtering, typical sites and 10-14 period
- add error-vs-sample scatter plot and error threshold sample summary
- keep model outputs unchanged
```

