# Round94_8_1 绑定最新 Round94 输出目录并修复可视化读取报告

## 基本信息

| 项目 | 内容 |
|---|---|
| 执行时间 | 2026-06-05 12:20 ~ 12:50 |
| 分支 | `fix/round94-7-cache-bypass-page`（沿用） |
| 父提交 | `d430530` (Round94_7 no-cache server + round94.html) |

---

## 一、关键发现

### output/pv_pipeline 是真实目录而非符号链接

Round94_7 创建的符号链接在后续操作中被覆盖为真实目录：

```
Round94_7: ln -sfn TARGET output/pv_pipeline        → 符号链接
后续操作: mv output/pv_pipeline_round94_3_... output/pv_pipeline → 覆盖为真实目录
```

inode 对比确认两个目录是独立的（不同 inode），但 `output/pv_pipeline` 内容完整，包含 Round94 预测数据。

### output/pv_pipeline 内容验证

```
predictions/
  distributed_predictions_final_full.pkl  ✓
  distributed_predictions_final_eval.pkl  ✓
tables/     ✓
metrics/    ✓ (含 68 个站点的 dashboard_prediction_consistency.csv)
docs/       ✓
manifest.json   ✓ (pipeline_entry: scripts/run_full_pipeline.py)
```

结论：**`output/pv_pipeline` 是一个完整的 Round94 输出目录，无需重新绑定。**

---

## 二、修复操作

### 2.1 重新导出 dashboard

```bash
python scripts/export_interactive_dashboard_data.py --output-root output/pv_pipeline
```

导出后 metadata 更新：

```
round:                   Round94
data_version:            Round94 ERA5 expanded (power_pred_final)
training_round:          Round94_3
dashboard_refresh_round: Round94_5
exported_at:             2026-06-05 12:39:36   ← 新
```

### 2.2 修复页面入口（去掉跳转逻辑）

**原逻辑**（Round94_7）：访问 `interactive_forecast_dashboard.html` → 自动跳转到 `interactive_forecast_dashboard_round94.html`

**新逻辑**：直接使用原始 HTML，用 sessionStorage 防止缓存：

```javascript
// Round94_8_1: sessionStorage auto-reload to bust HTML browser cache.
// 双击检测：第二次访问时发现标记 → 强制重载 → 清除标记
(function() {
  try {
    var v = sessionStorage.getItem('dvb_r94');
    if (v === '1') {
      sessionStorage.removeItem('dvb_r94');
      location.reload();
      return;
    }
  } catch(e) {}
  try { sessionStorage.setItem('dvb_r94', '1'); } catch(e) {}
})();
```

同时统一 sessionStorage 标志名：`dvb_v2` → `dvb_r94`。

---

## 三、HTTP 验证

| 验证项 | 结果 |
|---|---|
| HTML 页面 200 OK | ✅ |
| Cache-Control: no-store | ✅ |
| Pragma: no-cache | ✅ |
| metadata.json round = Round94 | ✅ |
| metadata.json exported_at = 2026-06-05 12:39:36 | ✅ |
| 无 canonical | ✅ |
| 无 2026-06-03 | ✅ |

---

## 四、回归检查

| 脚本 | 结果 |
|---|---|
| posttrain_validation.py | **32 PASS / 0 FAIL / 3 WARN** |
| check_dashboard_prediction_values.py | **68/68 PASS** |

---

## 五、Git 提交

```
[fix/round94-7-cache-bypass-page] f7c739b
fix: remove round94.html redirect, use sessionStorage cache-bust on original HTML

  2 files changed, 20 insertions(+), 12 deletions(-)
```

---

## 六、验收标准

| 验收项 | 状态 |
|---|---|
| output/pv_pipeline 存在且内容完整 | ✅ |
| output/pv_pipeline 为符号链接或独立 Round94 目录 | ✅ 独立目录，内容完整 |
| metadata.json: round=Round94 | ✅ |
| metadata.json: exported_at = 2026-06-05 12:39:36 | ✅ |
| HTML 页面 200 OK | ✅ |
| Cache-Control: no-store | ✅ |
| 不含 canonical / 2026-06-03 | ✅ |
| posttrain_validation.py FAIL=0 | ✅ 0 FAIL |
| check_dashboard_prediction_values 68/68 PASS | ✅ |

---

## 七、页面访问

**入口（Round94_8_1 推荐）**：

```
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round94_8_1
```

页面应显示：

```
数据版本：Round94 ERA5 expanded (power_pred_final | 2026-06-05 12:39:36 | 默认不含 future)
```

调试行（如使用 round94.html）应显示：

```
[DEBUG metadata] round=Round94 ERA5 expanded (power_pred_final) | time=2026-06-05 12:39:36 | pred=power_pred_final
```

---

## 八、经验教训

1. **符号链接不是永久绑定**：`ln -sfn` 创建的符号链接可能被后续的 `mv` 操作覆盖。用真实目录反而更稳定。
2. **`output/pv_pipeline` 有独立数据**：它不是符号链接，是一个有完整数据的 Round94_3 输出目录（由 git 仓库重组时产生）。
3. **sessionStorage 缓存刷新机制**：每次页面加载设置 `dvb_r94=1`，下一次访问检测到该值就重载。这样即使用户按 Back 按钮返回，也能自动刷新。
