# Round47.1 执行报告：可视化数据新鲜度与训练自动更新验证

**执行时间**：2026-05-30 00:15 ~ 00:25 (UTC+8)
**执行人**：Cursor AI
**状态**：✅ 全部完成

---

## 1. 目标回顾

本轮 Round47.1 不改模型、不改指标，专门验证：
1. 可视化页面数据是否来自最新训练产物
2. 后续重新训练后，数据是否会自动随训练结果更新

---

## 2. 检查结果

### 2.1 数据链路验证

当前完整链路：

```
distributed_predictions_final_round36.pkl
  -> power_pred_final
  -> round46_hourly_nrmse_consistent.csv  (mtime: 2026-05-29T23:34:54)
  -> export_interactive_dashboard_data.py
  -> interactive_dashboard/*.json           (mtime: 2026-05-29T23:39:14+)
  -> interactive_forecast_dashboard.html
```

所有文件修改时间均 **晚于** final pkl（+2.0h），链路正常。

### 2.2 `check_dashboard_data_freshness.py` 检查结果（8项）

| # | 检查项 | 结果 | 详情 |
|---|--------|------|------|
| 1 | latest final pkl 存在 | ✅ | `distributed_predictions_final_round36.pkl` |
| 2 | power_pred_final 列存在 | ✅ | final pkl 包含该列 |
| 3 | dashboard 关键文件存在 | ✅ | metadata.json, city_series.json, hourly JSON, site_metrics.json, 2个 CSV |
| 4 | site_series 文件数量 | ✅ | 68 个（>= 60） |
| 5 | metadata prediction_column | ✅ | `power_pred_final` |
| 6 | dashboard 文件新鲜度 | ✅ | 所有 dashboard 关键文件晚于 final pkl +2.0h |
| 7 | hourly JSON 与 CSV 一致 | ✅ | 14 行全部 MATCH（误差 < 0.001） |
| 8 | 未回到旧错误口径 | ✅ | 10-14点 max=16.14%（< 25%） |

### 2.3 其他验证脚本

| 脚本 | 结果 |
|------|------|
| `check_dashboard_auto_update_stamp.py` | ✅ 7/7 项 PASS |
| `round44_dashboard_regression_check.py` | ✅ 27/27 项 PASS |
| `check_post_training_auto_finalize.py` | ✅ 7/7 项 PASS |

---

## 3. 修改内容

### 3.1 新建 `scripts/check_dashboard_data_freshness.py`

8 项检查的独立脚本，供手动验证或 CI 使用：

```
[1/8] 查找 latest final pkl
[2/8] 检查 power_pred_final 列
[3/8] 检查 dashboard 关键文件
[4/8] 检查 site_series 文件数量
[5/8] 检查 metadata prediction_column
[6/8] 检查 dashboard 关键文件新鲜度
[7/8] 检查 hourly JSON 与 CSV 一致性
[8/8] 检查未回到旧错误口径
```

### 3.2 更新 `scripts/post_training_finalize_outputs.py`

在 dashboard stamp 检查之后，新增 Step 5：

```python
("check_dashboard_data_freshness",
 [PYTHON, str(ROOT / "scripts" / "check_dashboard_data_freshness.py")]),
```

收口链路现有 5 个步骤：

| 步骤 | 脚本 | 功能 |
|------|------|------|
| 1 | `compute_hourly_nrmse_consistent.py` | 重新计算 consistent NRMSE |
| 2 | `export_interactive_dashboard_data.py` | 导出 dashboard JSON |
| 3 | `update_dashboard_after_training.py` | 检测 dashboard 是否刷新 |
| 4 | `check_dashboard_auto_update_stamp.py` | 验证 stamp |
| **5** | **`check_dashboard_data_freshness.py`** | **新鲜度与口径验证** |
| 6 | `round44_dashboard_regression_check.py` | 回归检查（可选） |

### 3.3 浏览器缓存

页面已有完善的缓存防刷新机制，无需修改：

```js
async function fetchJSON(relativePath) {
  const url = `${DATA_ROOT}/${relativePath}?v=${Date.now()}`;
  const res = await fetch(url, { cache: "no-store" });
  return await res.json();
}
```

每次加载自动附加 `?v=<timestamp>`，且使用 `no-store`，浏览器不会缓存旧数据。

---

## 4. 验收标准检查

### 4.1 数据新鲜度

| 文件 | 与 final pkl 时间差 |
|------|---------------------|
| `round46_hourly_nrmse_consistent.csv` | +2.0h ✅ |
| `hourly_prediction_summary.json` | +2.0h ✅ |
| `city_series.json` | +2.0h ✅ |
| `metadata.json` | +2.0h ✅ |

### 4.2 预测列

`metadata.json` → `prediction_column` = **`power_pred_final`** ✅

### 4.3 逐小时数据

`hourly_prediction_summary.json` 与 `round46_hourly_nrmse_consistent.csv` 完全一致 ✅

### 4.4 浏览器缓存

页面已内置 `?v=Date.now()` + `no-store`，无需额外处理 ✅

### 4.5 自动更新

训练主入口（`run_round36_full_retrain.py` / `run_round44_training_logic_fix.py`）已在末尾调用 `post_training_finalize_outputs.py`，训练完成后自动执行全链路 ✅

---

## 5. 修改文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `scripts/check_dashboard_data_freshness.py` | 新建 | 可视化数据新鲜度检查脚本（8项） |
| `scripts/post_training_finalize_outputs.py` | 修改 | 新增 Step 5：check_dashboard_data_freshness |
| `scripts/audit_stale_round_artifacts.py` | 修改 | 新脚本加入白名单 |
