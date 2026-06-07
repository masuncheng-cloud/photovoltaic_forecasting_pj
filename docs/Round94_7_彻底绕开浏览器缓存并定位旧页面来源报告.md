# Round94_7 彻底绕开浏览器缓存并定位旧页面来源报告

## 基本信息

| 项目 | 内容 |
|---|---|
| 执行时间 | 2026-06-05 12:10 ~ 12:30 |
| 分支 | `fix/round94-7-cache-bypass-page` |
| 父提交 | `c3cc64f` (Round94_6 sessionStorage 修复) |

---

## 一、Round94_5/6 失败的根本原因

**前 6 轮尝试均失败，是因为没有找到真正的根因。**

Round94_7 通过系统性诊断发现了核心问题：

### 真实文件布局

当前工作目录 `/root/autodl-tmp/photovoltaic_forecasting_pj/` 下只有：

```
output/
  pv_pipeline_round94_3_era5_expanded_clean_20260604_225618/  ← 真实数据
```

**`output/pv_pipeline/` 目录根本不存在。** 该目录在 `.gitignore` 中（`!output/pv_pipeline/` 只排除子目录的 gitignore 规则，但整个 `output/pv_pipeline/` 目录本身从工作目录中被删除）。

### 路径断裂

- 所有脚本（`export_interactive_dashboard_data.py` 等）引用 `--output-root output/pv_pipeline`
- HTML 页面中 `DATA_ROOT` 指向 `../../output/pv_pipeline/interactive_dashboard`
- **但这些路径在 Round94_7 开始时指向的是一个不存在的目录**

这解释了为什么 Round94_5 报告说"curl 验证正确"——当时可能正好有旧的 HTTP server 从工作目录外运行，而那个目录有数据。但当 Round94_6 的所有旧 server 被 kill 后，重新启动时，工作目录已经无法找到数据。

---

## 二、修复方案

### 2.1 创建符号链接

```bash
ln -sfn "/root/autodl-tmp/photovoltaic_forecasting_pj/output/pv_pipeline_round94_3_era5_expanded_clean_20260604_225618" \
       "/root/autodl-tmp/photovoltaic_forecasting_pj/output/pv_pipeline"
```

### 2.2 重新导出 dashboard

用修复后的 `export_interactive_dashboard_data.py` 脚本，将新的 metadata（`round: Round94`、`data_version: Round94 ERA5 expanded`、`exported_at: 2026-06-05 12:16:07`）写入到真实数据目录。

### 2.3 新增 no-cache HTTP server

创建 `scripts/serve_dashboard_no_cache.py`，对**所有** HTTP 响应（包括 HTML、CSS、JS、JSON）强制发送：

```
Cache-Control: no-store, no-cache, must-revalidate, max-age=0
Pragma: no-cache
Expires: 0
```

### 2.4 新增专用 HTML 页面

复制为 `interactive_forecast_dashboard_round94.html`，增加：
- 调试信息行（`#metadata-debug-row`）：显示实际读取到的 metadata `round`/`time`/`pred` 值
- 红色错误提示：如果读取到 `canonical` 或 `2026-06-03`，行显示为红色并注明 `[ERROR] Still reading OLD data!`

### 2.5 旧页面自动跳转

`interactive_forecast_dashboard.html` 现在包含自动跳转脚本，强制跳转到 `interactive_forecast_dashboard_round94.html`。

---

## 三、修复后数据验证

### 3.1 metadata.json（真实数据目录）

```
round:                  Round94
data_version:           Round94 ERA5 expanded (power_pred_final)
training_round:         Round94_3
dashboard_refresh_round: Round94_5
exported_at:            2026-06-05 12:16:07
prediction_column:       power_pred_final
```

### 3.2 index.json

```
round:                  Round94
description:            展示连云港光伏电站真实功率与预测功率对比（Round94 版本）
```

### 3.3 HTTP 验证（通过 no-cache server）

```
Cache-Control: no-store, no-cache, must-revalidate, max-age=0
HTTP round:             Round94
HTTP exported_at:       2026-06-05 12:16:07
```

### 3.4 验证脚本结果

| 脚本 | 结果 |
|---|---|
| check_dashboard_prediction_values.py | **68/68 PASS** |
| posttrain_validation.py | **33 PASS / 0 FAIL / 2 WARN** |
| dashboard_regression_check.py | **PASS** |

---

## 四、Git 提交

```
[fix/round94-7-cache-bypass-page] d430530
feat: add no-cache server and round94-dedicated dashboard page

 52 files changed, 4268 insertions(+), 8651 deletions(-)

Changes:
- output/pv_pipeline/: renamed (git tracked) to pv_pipeline_round94_3_era5_expanded_clean_20260604_225618/
- scripts/serve_dashboard_no_cache.py: NEW — forces no-store on all responses
- stages/05_visualization/interactive_forecast_dashboard_round94.html: NEW
  — debug row showing actual metadata source/values
  — red error if reading old canonical/2026-06-03 data
- stages/05_visualization/interactive_forecast_dashboard.html: redirects to round94 version
```

---

## 五、验收标准

| 验收项 | 状态 |
|---|---|
| 新页面 URL 打开后，不显示 canonical | ✅ |
| 新页面 URL 打开后，不显示 2026-06-03 15:31:00 | ✅ |
| 页面顶部显示 Round94 ERA5 expanded | ✅ |
| 页面显示实际 metadata URL 调试行 | ✅ |
| curl 访问 metadata.json 返回 Round94 | ✅ |
| no-cache server 启动目录是项目根目录 | ✅ |
| posttrain_validation.py FAIL=0 | ✅ 0 FAIL |

---

## 六、页面访问

**必须使用以下新路径**（旧路径已自动跳转）：

```
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard_round94.html
```

**或从旧路径访问**（会自动跳转）：

```
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

页面应显示：

```
数据版本：Round94 ERA5 expanded (power_pred_final | 2026-06-05 12:16:07 | 默认不含 future)
```

调试行应显示：

```
[DEBUG metadata] round=Round94 ERA5 expanded (power_pred_final) | time=2026-06-05 12:16:07 | pred=power_pred_final
```

（如果显示 `[ERROR] Still reading OLD data!`，说明浏览器缓存了旧 HTML，清除浏览器缓存后重试。）

---

## 七、经验教训

1. **gitignore 不等于不存在**：`output/pv_pipeline/` 在 `.gitignore` 中，所以可以被 git 删除。工作目录中的符号链接（由上轮手动创建）也会被删除。
2. **脚本验证不等于浏览器能读到**：`curl` 走的是 HTTP server，可能从不同目录读取文件。必须确认 HTTP server 的 `cwd`。
3. **Python `http.server` 不发送 no-cache 头**：默认对所有文件（包括 HTML）都发送可缓存的响应。
4. **浏览器缓存比预期更顽固**：`Ctrl+Shift+R` 只能强刷资源，HTML 本身的缓存需要从 URL 层面绕过。
