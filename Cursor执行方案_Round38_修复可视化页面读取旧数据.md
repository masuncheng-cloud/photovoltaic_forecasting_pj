# Round38 修复可视化页面读取旧数据方案

## 一、问题判断

从 `可视化.docx` 中提取到的数据看，当前网页展示的不是 Round36 最新训练结果，而是旧版本数据。

明显证据：

1. 典型站点仍是旧列表：

```text
预测最好：S017、S023、S031、S049、S062
预测最差：S012、S019、S045、S053、S115
```

Round36 最新应为：

```text
预测最好：S062、S023、S049、S047、S056
预测最差：S007、S063、S065、S041、S072
```

2. 页面逐小时样本数不符合 Round36 `final_eval` 口径。

Round36 `final_eval` 是：

```text
68 站 × 122 天 × 14 小时 = 116,144 行
```

如果逐小时按完整 test 6-19 口径，单小时应接近：

```text
68 × 122 = 8,296 行
```

但页面中出现：

```text
6点 1,241 行
10点 6,403 行
19点 693 行
```

这说明页面可能仍在读旧 JSON，或读的是正功率过滤后的旧统计。

3. 页面说明中仍出现旧公式：

```text
NRMSE = RMSE_city / median(capacity_sum_mw) × 100%
```

Round36 正确口径应为：

```text
NRMSE = RMSE_city / capacity_sum_mw × 100%
```

4. 阈值统计总站点数仍是 67，而 Round36 当前口径是：

```text
全部登记站点：118
有 test 结果站点：68
正常可排名站点：14
```

5. 无有效发电样本站点只列 S069，而 Round36 测试期无有效发电应为：

```text
S003、S044、S069、S076、S077
```

因此本轮不需要重新训练，重点修复：

```text
HTML 实际读取的数据路径
页面缓存
旧 JSON 残留
导出脚本是否写到了网页正在读取的目录
```

## 二、目标

让当前打开的：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

读取 Round36 最新数据，并确保页面中：

1. 典型站点为 Round36 最新列表；
2. 逐小时结果来自 `round36_city_hourly_nrmse.csv` 和 `round36_site_avg_hourly_nrmse.csv`；
3. 城市 NRMSE 公式说明为 `RMSE_city / capacity_sum_mw × 100%`；
4. 阈值统计总站点数与 Round36 口径一致；
5. 无有效发电站点列表包含 S003、S044、S069、S076、S077；
6. 可视化折线图仍读取 `power_pred_final`；
7. 页面默认不含 future。

## 三、Cursor 执行步骤

### Step 1：确认当前 HTML 读取的数据路径

在 Cursor 终端执行：

```bash
grep -n "fetch\\|site_metrics\\|typical\\|hourly\\|site_series\\|city_series\\|data/" stages/05_visualization/interactive_forecast_dashboard.html | head -120
```

重点查看页面到底在读取哪些文件，例如：

```text
data/site_metrics.json
data/hourly_metrics.json
output/pv_pipeline/interactive_dashboard/site_metrics.json
output/pv_pipeline/interactive_dashboard/...
```

同时执行：

```bash
find . -path "*interactive_dashboard*" -maxdepth 6 -type f | sort | head -200
find . -name "*site_metrics*.json" -o -name "*typical*.json" -o -name "*hourly*.json" -o -name "*city_series*.json"
```

### Step 2：定位旧数据来源

搜索旧典型站点和旧公式：

```bash
grep -R "S017\\|S012\\|S019\\|median(capacity_sum_mw)\\|无有效发电样本站点" -n \
  stages/05_visualization output/pv_pipeline \
  --include="*.html" --include="*.json" --include="*.js" --include="*.csv" --include="*.md" | head -200
```

如果发现旧数据存在于：

```text
stages/05_visualization/data/
```

或：

```text
stages/05_visualization/*.json
```

说明当前页面正在读旧静态数据。

### Step 3：重新导出 Round36 可视化数据

执行：

```bash
python scripts/export_interactive_dashboard_data.py
python scripts/check_dashboard_prediction_values_round36.py
python scripts/posttrain_validation_round36.py
```

要求：

```text
check_dashboard_prediction_values_round36.py：68/68 PASS
posttrain_validation_round36.py：0 FAIL / 0 WARN
```

### Step 4：把 Round36 数据同步到页面实际读取目录

如果 Step 1 发现 HTML 读取的是：

```text
stages/05_visualization/data/
```

而导出脚本写的是：

```text
output/pv_pipeline/interactive_dashboard/
```

则同步数据：

```bash
mkdir -p stages/05_visualization/data
rsync -av --delete output/pv_pipeline/interactive_dashboard/ stages/05_visualization/data/
```

如果 HTML 直接读取：

```text
site_series/
city_series.json
```

则确认同步后的结构与 HTML fetch 路径一致。

例如，如果 HTML fetch：

```javascript
fetch("data/site_series/S001.json")
```

则文件必须存在：

```text
stages/05_visualization/data/site_series/S001.json
```

如果 HTML fetch：

```javascript
fetch("site_series/S001.json")
```

则文件必须存在：

```text
stages/05_visualization/site_series/S001.json
```

### Step 5：优先修 HTML fetch 路径，而不是复制多份数据

更推荐把 `stages/05_visualization/interactive_forecast_dashboard.html` 的数据根路径统一为：

```javascript
const DATA_ROOT = "../../output/pv_pipeline/interactive_dashboard";
```

或根据当前服务根目录设置：

```javascript
const DATA_ROOT = "/output/pv_pipeline/interactive_dashboard";
```

然后所有 fetch 改成：

```javascript
fetch(`${DATA_ROOT}/site_metrics.json?v=${Date.now()}`)
fetch(`${DATA_ROOT}/typical_sites.json?v=${Date.now()}`)
fetch(`${DATA_ROOT}/city_hourly_nrmse.json?v=${Date.now()}`)
fetch(`${DATA_ROOT}/site_avg_hourly_nrmse.json?v=${Date.now()}`)
fetch(`${DATA_ROOT}/site_series/${siteId}.json?v=${Date.now()}`)
```

注意：

1. 路径必须与你的启动方式匹配。
2. 你当前地址是：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

因此从该 HTML 到 output 目录的相对路径通常是：

```text
../../output/pv_pipeline/interactive_dashboard
```

### Step 6：修正页面文字说明

在 HTML 中搜索：

```bash
grep -n "median(capacity_sum_mw)\\|NRMSE = RMSE_city" stages/05_visualization/interactive_forecast_dashboard.html
```

将：

```text
NRMSE = RMSE_city / median(capacity_sum_mw) × 100%
```

改为：

```text
NRMSE = RMSE_city / capacity_sum_mw × 100%
```

并补充说明：

```text
城市 NRMSE 表示先按时间聚合全市真实功率和预测功率，再计算 RMSE，并除以参与评价站点总装机容量。
```

### Step 7：增加页面版本标记

在 HTML 顶部或指标卡附近增加一个小字段：

```text
数据版本：Round36 / power_pred_final / test=2025-09-01~2025-12-31 / 默认不含 future
```

该信息应来自 JSON，例如：

```text
metadata.json
```

如果没有 metadata，导出脚本新增：

```text
output/pv_pipeline/interactive_dashboard/metadata.json
```

内容：

```json
{
  "round": "Round36",
  "prediction_column": "power_pred_final",
  "test_period": "2025-09-01~2025-12-31",
  "hours": "6-19",
  "exclude_future": true,
  "generated_at": "..."
}
```

页面加载并显示：

```text
数据版本：Round36（power_pred_final，默认不含 future）
```

### Step 8：增加页面自检

在 HTML 加载后检查典型站点是否为 Round36：

```javascript
const expectedBest = ["S062", "S023", "S049", "S047", "S056"];
const expectedWorst = ["S007", "S063", "S065", "S041", "S072"];
```

如果当前加载的 typical_sites 不匹配，在页面顶部显示红色提示：

```text
警告：当前页面加载的典型站点不是 Round36 最新数据，请检查数据路径或缓存。
```

### Step 9：清理旧数据缓存

删除或重命名旧数据目录，避免误读：

```bash
find stages/05_visualization -maxdepth 3 -type f \\( -name "*.json" -o -name "*.csv" \\) -print
```

如果确认这些是旧数据，可以移动到归档目录：

```bash
mkdir -p output/pv_pipeline/archive_old_visualization_data_round38
mv stages/05_visualization/data output/pv_pipeline/archive_old_visualization_data_round38/stages_data_old 2>/dev/null || true
```

如果 HTML 已经改为读取 `output/pv_pipeline/interactive_dashboard`，则不需要保留 `stages/05_visualization/data`。

### Step 10：浏览器强制刷新

重新启动服务或保持原服务：

```bash
python -m http.server 8070
```

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round36_latest
```

浏览器强制刷新：

```text
Ctrl + Shift + R
```

### Step 11：页面内容人工核对

页面恢复后，确认：

1. 页面上显示：

```text
数据版本：Round36
```

2. 典型站点表：

```text
预测最好：S062、S023、S049、S047、S056
预测最差：S007、S063、S065、S041、S072
```

3. 无有效发电站点包含：

```text
S003、S044、S069、S076、S077
```

4. 公式说明为：

```text
NRMSE = RMSE_city / capacity_sum_mw × 100%
```

5. 页面不再出现：

```text
median(capacity_sum_mw)
S017 被标为预测最好
S012/S019/S045/S053/S115 被标为预测最差
总站点数 67
```

## 四、验收标准

Round38 通过必须满足：

1. 页面读取 Round36 最新 JSON。
2. 页面显示 `数据版本：Round36`。
3. 典型站点与 Round36 执行反馈一致。
4. 城市 NRMSE 公式说明正确。
5. 页面默认不含 future。
6. 可视化 `pred_mw` 与 `power_pred_final` 一致。
7. 可视化 `actual_mw` 与 `power_mw` 一致。
8. `check_dashboard_prediction_values_round36.py` 全部 PASS。
9. `posttrain_validation_round36.py` 0 FAIL / 0 WARN。
10. 页面强制刷新后仍不显示旧数据。

## 五、完成后回传

请回传：

1. 最新页面截图；
2. 以下命令输出：

```bash
python scripts/check_dashboard_prediction_values_round36.py
python scripts/posttrain_validation_round36.py
grep -R "S017\\|S012\\|median(capacity_sum_mw)" -n stages/05_visualization output/pv_pipeline --include="*.html" --include="*.json" --include="*.js" | head -50
```

3. 如果页面仍显示旧数据，请回传：

```bash
grep -n "fetch\\|DATA_ROOT\\|site_metrics\\|typical\\|hourly\\|site_series" stages/05_visualization/interactive_forecast_dashboard.html | head -120
```
