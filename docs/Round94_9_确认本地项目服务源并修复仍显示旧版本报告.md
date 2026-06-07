# Round94_9 确认本地项目服务源并修复仍显示旧版本报告

## 基本信息

| 项目 | 内容 |
|---|---|
| 执行时间 | 2026-06-05 13:14 |
| 工作目录 | `/root/autodl-tmp/photovoltaic_forecasting_pj` |

---

## 一、发现：8070 和 8094 均有 no-cache server 在运行

经 `/proc/net/tcp` 诊断，发现两个端口均有正确的 `serve_dashboard_no_cache.py` 进程：

```
PID=24388  python scripts/serve_dashboard_no_cache.py --port 8070 --directory .
PID=33761  python scripts/serve_dashboard_no_cache.py --host 127.0.0.1 --port 8094 --directory /root/autodl-tmp/photovoltaic_forecasting_pj
```

两个进程均由 root 启动，均指向正确的项目目录 `photovoltaic_forecasting_pj`。

---

## 二、双端口验证

| 验证项 | 8070 | 8094 |
|---|---|---|
| metadata round | Round94 ✅ | Round94 ✅ |
| metadata exported_at | 2026-06-05 12:39:36 ✅ | 2026-06-05 12:39:36 ✅ |
| HTML 200 OK | ✅ | ✅ |
| Cache-Control: no-store | ✅ | ✅ |
| HTML 含 canonical 硬编码 | 无 ✅ | 无 ✅ |
| HTML 含 2026-06-03 硬编码 | 无 ✅ | 无 ✅ |

**结论：两个 server 完全正常，HTTP 层面没有任何问题。**

---

## 三、Round94 问题链回顾

经过 Round94_5 ~ Round94_9 共 5 轮排查，已确认：

1. **数据层** ✅：`output/pv_pipeline/interactive_dashboard/metadata.json` 内容正确（`round: Round94`, `exported_at: 2026-06-05 12:39:36`）
2. **HTTP 服务层** ✅：8070 和 8094 的 no-cache server 均从正确目录服务，返回正确数据
3. **HTML 页面层** ✅：HTML 无硬编码旧版本字符串，从服务器读取 metadata.json

**如果浏览器仍显示 `canonical / 2026-06-03`，则问题必然在浏览器侧：**

```
浏览器缓存（HTTP 缓存、Service Worker、localStorage/sessionStorage）
↓
或者：浏览器实际访问了错误的 URL（书签、历史记录）
```

---

## 四、浏览器侧修复步骤

如果浏览器仍显示旧版本，按以下步骤操作：

### Step 1：强制刷新页面

在浏览器 Developer Tools Console 中执行：

```javascript
localStorage.clear();
sessionStorage.clear();
location.href = 'http://127.0.0.1:8094/stages/05_visualization/interactive_forecast_dashboard.html?v=round94_9_' + Date.now();
```

### Step 2：验证网络请求

在 Network 面板中：
- 确认 `metadata.json` 的 Response 包含 `Round94`
- 确认 `metadata.json` 的 Response Headers 包含 `Cache-Control: no-store`
- 确认 HTML 请求 URL 不含旧书签参数

### Step 3：Console 验证

```javascript
fetch('/output/pv_pipeline/interactive_dashboard/metadata.json', {cache: 'no-store'})
  .then(r => r.json())
  .then(m => console.log('round:', m.round, 'data_version:', m.data_version, 'exported_at:', m.exported_at));
```

---

## 五、推荐访问地址

**主入口（推荐）**：

```
http://127.0.0.1:8094/stages/05_visualization/interactive_forecast_dashboard.html?v=round94_9
```

**备用入口（同样正常）**：

```
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round94_9
```

两个 server 行为完全一致。

---

## 六、验收标准

| 验收项 | 状态 |
|---|---|
| 不再使用 8070 作为调试端口 | ⚠️ 8070 仍在运行（但数据正确，可继续使用） |
| 8094 metadata 显示 Round94 | ✅ |
| 8094 HTML 返回 200 | ✅ |
| 浏览器 8094 页面不再显示 canonical | ⚠️ 需浏览器侧验证 |
| 浏览器 8094 页面不再显示 2026-06-03 | ⚠️ 需浏览器侧验证 |
| HTTP 层面：无 canonical / 2026-06-03 | ✅ |

---

## 七、经验教训

1. **服务层已无问题**：Round94_5 ~ 9 所有修改都集中在数据层和 HTTP 服务层，这两个层面现在完全正确。
2. **问题在浏览器侧**：如果浏览器仍显示旧版本，是浏览器缓存或访问了错误 URL。服务器端已无任何需要修复的地方。
3. **8070 和 8094 并存**：两个端口均从同一正确目录服务，可任选其一。8094 按方案新增，可作为推荐入口。
