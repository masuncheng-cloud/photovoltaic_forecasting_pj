# Round39.1 修复 `DASHBOARD_BASE` 未定义导致页面加载失败

## 一、问题原因

页面报错：

```text
Can't find variable: DASHBOARD_BASE
```

说明当前 HTML / JS 中仍然有代码在使用旧变量：

```javascript
DASHBOARD_BASE
```

但 Round39 方案中已经改为统一使用：

```javascript
DATA_ROOT
```

因此页面加载时找不到 `DASHBOARD_BASE`，导致整个可视化初始化失败。

这不是训练问题，不需要重新训练。

## 二、修复目标

统一前端数据根路径变量，确保页面只使用一个变量：

```javascript
DATA_ROOT
```

或者为了兼容旧代码，临时加入：

```javascript
const DASHBOARD_BASE = DATA_ROOT;
```

推荐做法：**全量替换 `DASHBOARD_BASE` 为 `DATA_ROOT`，并保留兼容别名。**

## 三、Cursor 执行步骤

### Step 1：定位所有 `DASHBOARD_BASE`

在项目根目录执行：

```bash
grep -R "DASHBOARD_BASE" -n \
  stages/05_visualization \
  output/pv_pipeline/interactive_dashboard \
  scripts \
  --include="*.html" --include="*.js" --include="*.py"
```

重点文件通常是：

```text
stages/05_visualization/interactive_forecast_dashboard.html
output/pv_pipeline/interactive_dashboard/index.html
output/pv_pipeline/interactive_dashboard/interactive_forecast_dashboard.html
```

### Step 2：修复 HTML 变量定义

打开：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

找到类似：

```javascript
const DATA_ROOT = ...
```

在它后面加一行兼容定义：

```javascript
const DASHBOARD_BASE = DATA_ROOT;
```

例如：

```javascript
const DATA_ROOT = (() => {
  const path = window.location.pathname;
  if (path.includes("/stages/05_visualization/")) {
    return "../../output/pv_pipeline/interactive_dashboard";
  }
  return ".";
})();

const DASHBOARD_BASE = DATA_ROOT;
```

### Step 3：推荐同步替换旧变量

在同一个 HTML 中，将：

```javascript
DASHBOARD_BASE
```

替换为：

```javascript
DATA_ROOT
```

但保留：

```javascript
const DASHBOARD_BASE = DATA_ROOT;
```

这样即使还有遗漏引用，也不会报错。

### Step 4：同步 output 页面

如果你也会访问：

```text
output/pv_pipeline/interactive_dashboard/index.html
```

则同步 HTML：

```bash
cp stages/05_visualization/interactive_forecast_dashboard.html output/pv_pipeline/interactive_dashboard/index.html
cp stages/05_visualization/interactive_forecast_dashboard.html output/pv_pipeline/interactive_dashboard/interactive_forecast_dashboard.html
```

### Step 5：确认数据文件存在

执行：

```bash
ls -lh output/pv_pipeline/interactive_dashboard/index.json
ls -lh output/pv_pipeline/interactive_dashboard/metadata.json
```

如果不存在，先重新导出：

```bash
python scripts/export_interactive_dashboard_data.py
```

### Step 6：重新启动页面

在项目根目录启动：

```bash
python -m http.server 8060
```

打开：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html?v=round39_1
```

然后强制刷新：

```text
Ctrl + Shift + R
```

### Step 7：验证

打开浏览器控制台，不应再出现：

```text
Can't find variable: DASHBOARD_BASE
```

页面顶部应显示：

```text
数据版本：Round36
预测列：power_pred_final
默认不含 future
```

同时执行：

```bash
python scripts/check_dashboard_prediction_values_round36.py
python scripts/posttrain_validation_round36.py
```

要求：

```text
68/68 PASS
0 FAIL / 0 WARN
```

## 四、如果仍然报错

继续检查：

```bash
grep -R "DASHBOARD_BASE" -n \
  stages/05_visualization \
  output/pv_pipeline/interactive_dashboard \
  --include="*.html" --include="*.js"
```

如果还有引用，全部替换为 `DATA_ROOT`，或确保文件顶部已经定义：

```javascript
const DASHBOARD_BASE = DATA_ROOT;
```

## 五、Git 提交

修复完成后提交：

```bash
git add stages/05_visualization/interactive_forecast_dashboard.html \
        output/pv_pipeline/interactive_dashboard/index.html \
        output/pv_pipeline/interactive_dashboard/interactive_forecast_dashboard.html

git commit -m "fix: define dashboard data root alias"
git push
```

不要提交：

```text
site_series/*.json
city_series.json
*.pkl
output/pv_pipeline/tables/
```
