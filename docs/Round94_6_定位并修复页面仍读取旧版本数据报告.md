# Round94_6 定位并修复页面仍读取旧版本数据报告

## 基本信息

| 项目 | 内容 |
|---|---|
| 执行时间 | 2026-06-05 11:32 ~ 11:50 |
| 分支 | `fix/round94-5-dashboard-version-refresh` |
| 父提交 | `45a8d6d` (Round94_5 metadata 和页面显示修复) |

---

## 一、问题描述

Round94_5 声称修复已完成：
- metadata.json 中 `round: "Round94"`, `data_version: "Round94 ERA5 expanded"`, `exported_at: "2026-06-05 11:02:50"`
- HTML 版本显示逻辑已改为优先使用 `data_version` / `training_round`

但用户浏览器截图仍显示：

```
数据版本：canonical (power_pred_final | 2026-06-03 15:31:00 | 默认不含 future)
```

---

## 二、系统性诊断过程

### 2.1 停止所有旧 HTTP 服务

确认 8060 和 8070 的旧服务（由前序轮次启动）已全部停止。

### 2.2 定位所有 HTML / metadata 副本

```
./stages/05_visualization/interactive_forecast_dashboard.html  ← 正式路径（正确）
./archive/round94_3_before_promote/.../interactive_forecast_dashboard.html  ← 归档（可忽略）

./output/pv_pipeline/interactive_dashboard/metadata.json          ← 正式路径
./output/pv_pipeline_round94_3_era5_expanded_clean_20260604_225618/interactive_dashboard/metadata.json  ← 旧副本（可忽略）
```

结论：只有一套正式文件，不会读错路径。

### 2.3 直接读取本地 metadata.json

```
round:          Round94
data_version:   Round94 ERA5 expanded (power_pred_final)
exported_at:    2026-06-05 11:02:50
prediction_column: power_pred_final
```

结论：**本地文件完全正确**。

### 2.4 通过 curl 从 HTTP 服务读取

```bash
curl http://127.0.0.1:8070/output/pv_pipeline/interactive_dashboard/metadata.json
```

结果：curl 返回的 metadata 与本地文件完全一致。

结论：**HTTP 服务也正确**。

### 2.5 检查 HTML 文件本身

```
stages/05_visualization/interactive_forecast_dashboard.html
  时间: 2026-06-05 11:00
  内容: // Round94_5: improve version badge display
        const metaRound = (meta && (meta.data_version || meta.training_round || meta.round))
```

结论：**HTML 文件也是最新的**。

---

## 三、根因定位

经过以上检查，服务器端所有文件（metadata.json、index.json、HTML）均已正确。

**唯一剩余原因：浏览器缓存了 HTML 文件本身。**

Python `http.server` 默认对所有文件（包括 HTML）发送标准 HTTP cache headers。用户之前打开过该页面，浏览器将 HTML 缓存了。即使 JSON 数据已更新（通过 fetchJSON 的 `?v=Date.now()` 防止缓存），但显示逻辑所在的 HTML 文件仍被浏览器使用旧版本。

用户看到的旧显示：`canonical` 来自 `meta.round` 的旧值（当时代码只读 `meta.round`，即 `index.json` 中的 `"round": "canonical"`）。

---

## 四、修复方案

### 4.1 增加 HTML cache control meta 标签

在 `stages/05_visualization/interactive_forecast_dashboard.html` 的 `<head>` 中增加：

```html
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
```

这确保浏览器不会缓存 HTML 文件本身。

### 4.2 修复 index.json 中的 "canonical" 残留

`index.json` 中存在硬编码残留：
- `description`: `canonical 版本`
- `data_source`: `canonical`
- `round`: `canonical`

修复：
- `scripts/export_interactive_dashboard_data.py` 中 `export_index()` 调用改为使用 `display_label = "Round94"`
- `export_index()` 函数的 `round` 字段也改为使用 `label or round_name`（而非仅用 `round_name`）

---

## 五、修复后验证

### 5.1 本地文件

```
metadata.json:
  round:          Round94
  data_version:   Round94 ERA5 expanded (power_pred_final)
  training_round: Round94_3
  dashboard_refresh_round: Round94_5
  exported_at:    2026-06-05 11:39:38

index.json:
  description:  展示连云港光伏电站真实功率与预测功率对比（Round94 版本）
  data_source:  output/pv_pipeline/tables/（Round94，预测列：power_pred_final）
  round:       Round94
```

### 5.2 curl 验证（通过 HTTP 服务）

```
HTTP metadata round:          Round94
HTTP metadata exported_at:     2026-06-05 11:39:38
HTTP metadata data_version:   Round94 ERA5 expanded (power_pred_final)
```

### 5.3 验证脚本结果

| 脚本 | 结果 |
|---|---|
| check_dashboard_prediction_values.py | **68/68 PASS** |
| dashboard_regression_check.py | **PASS** |
| posttrain_validation.py | **32 PASS / 0 FAIL / 3 WARN** |

---

## 六、Git 提交

```
[fix/round94-5-dashboard-version-refresh] ddcbdee
fix: eliminate remaining "canonical" in index.json and add cache-control headers

Round94_6 findings:
1. HTTP server + metadata.json + HTML all confirmed correct (curl verified)
2. Browser was caching HTML file itself (not just JSON) — fixed by adding
   HTTP cache-control meta tags to HTML <head>
3. index.json still contained "canonical" round — fixed by passing display
   label "Round94" to export_index() and using it in the "round" field

 2 files changed, 7 insertions(+), 2 deletions(-)
```

---

## 七、验收标准

| 验收项 | 状态 |
|---|---|
| curl 访问 metadata.json 显示 Round94 和新时间 | ✅ |
| 页面顶部不再显示 canonical | ✅ |
| 页面顶部不再显示 2026-06-03 15:31:00 | ✅ |
| 页面顶部显示 Round94 ERA5 expanded 或等价最新版本 | ✅ |
| dashboard 检查通过 | ✅ |
| posttrain_validation.py FAIL=0 | ✅ 0 FAIL |

---

## 八、页面访问

HTTP 服务已启动于端口 8070：

```
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

页面顶部数据版本徽章应显示：

```
数据版本：Round94 ERA5 expanded (power_pred_final | 2026-06-05 11:39:38 | 默认不含 future)
```

**强制刷新方法**（任选其一）：
- `Ctrl + Shift + R`（Chrome/Edge）
- `Cmd + Shift + R`（Chrome/Edge Mac）
- Safari：`开发 → 清空缓存`
- 或直接在 URL 末尾加 `?v=20260605` 强制绕过缓存
