# Round35 执行反馈报告

> **执行时间**：2026-05-28 18:36 (UTC+8)
> **方案来源**：`Cursor执行方案_Round35_产物收口与可视化预测一致性补强.md`
> **Git 提交**：`d424a10`
> **方案负责人**：Cursor Agent

---

## 一、执行总览

| 步骤 | 任务 | 状态 | 备注 |
|------|------|------|------|
| Step 1 | 新增可视化 pred/actual 全量一致性检查脚本 | ✅ | 68 站全部 PASS |
| Step 2 | 修正报告路径（metrics/docs → docs） | ✅ | Round34 报告已迁移 |
| Step 3 | 修正项目报告站点数量说明（118/68/14） | ✅ | 新增口径说明段落 |
| Step 4 | 弱化历史口径 NRMSE 0.3365% | ✅ | Round34 反馈报告已加注 |
| Step 5 | 检查 Git 追踪内容和 .gitignore | ✅ | 移除 160 个大体积 JSON |
| Step 6 | 重新导出可视化 + 全量一致性检查 | ✅ | pred_mw 已改用 power_pred_final |
| Step 7 | 新增 Round35 总体验证脚本 | ✅ | 12/13 PASS（1 WARN 可接受） |
| Step 8 | Git 提交推送 | ✅ | d424a10，净减 ~9.7MB |

---

## 二、验收标准核对

| # | 标准 | 结果 | 说明 |
|---|------|------|------|
| 1 | `round35_dashboard_prediction_consistency.csv` 所有站点 PASS | ✅ PASS | 68/68 站 |
| 2 | `max_abs_diff_actual ≤ 1e-9` | ✅ PASS | 0.00e+00 |
| 3 | `max_abs_diff_pred ≤ 1e-9` | ✅ PASS | 0.00e+00 |
| 4 | 项目报告含 118/68/14/50 站点说明 | ✅ PASS | 含口径说明段落 |
| 5 | 历史口径 0.3365% 不作正式核心指标 | ✅ PASS | 正文未发现 |
| 6 | 所有 Markdown 报告位于 `output/pv_pipeline/docs/` | ✅ PASS | 路径已修正 |
| 7 | Git 不追踪大体积 pkl 和 site_series JSON | ✅ PASS | 160 文件已移除 |
| 8 | 可视化页面默认不含 future | ✅ PASS | 已验证 |

---

## 三、全量可视化一致性检查结果

### 3.1 方法

对比 `distributed_predictions_final_round34.pkl` 与 `interactive_dashboard/site_series/*.json`：
- `json.pred_mw` vs `pkl.power_pred_final`（按 time 精确匹配）
- `json.actual_mw` vs `pkl.power_mw`
- `json.capacity_mw` vs `pkl.capacity_mw`
- 默认排除 `split == "future"`
- 数值精度：JSON 存储 `round(..., 4)`，比较时对 pkl 值同样四舍五入到 4 位，容差 ≤ 1e-9

### 3.2 结果

| 指标 | 值 |
|------|-----|
| 检查站点数 | 68 |
| PASS | 68 |
| FAIL | 0 |
| WARN | 0 |
| `max_abs_diff_pred` | 0.00e+00 |
| `max_abs_diff_actual` | 0.00e+00 |
| `max_abs_diff_capacity` | 0.00e+00 |

> **结论**：可视化中 `pred_mw` 与 `power_pred_final`、`actual_mw` 与 `power_mw` 完全一致。

---

## 四、Round35 总体验证结果（13 项）

| # | 检查项 | 状态 | 说明 |
|---|--------|------|------|
| C1 | Round34 预测文件存在且可读 | ✅ PASS | 1,172,180 行, 25 列 |
| C2 | `power_pred_final` 存在 | ✅ PASS | 1,172,180 个非空值 |
| C3 | Round34 指标文件全部存在 | ✅ PASS | 8 个文件 |
| C4 | 城市 NRMSE 使用总出力口径 | ✅ PASS | NRMSE 2.42%~5.95% |
| C5 | 典型站点无跨类重复 | ✅ PASS | 预测最好5 + 最差5 + 相对正确4 |
| C6 | dashboard pred/actual 一致 | ✅ PASS | 68/68 PASS |
| C7 | 报告路径正确 | ⚠ WARN | Round35 报告在本次运行后生成 |
| C8 | 项目报告含站点数量说明 | ✅ PASS | 118/68/14/50 均含 |
| C9 | 历史口径不作核心指标 | ✅ PASS | 正文未发现 0.3365% |
| C10 | Git 不追踪 pkl | ✅ PASS | 0 个 |
| C10 | Git 不追踪 site_series JSON | ✅ PASS | 0 个 |
| C11 | 可视化不含 future | ✅ PASS | 无 future 数据 |
| C12 | 站点数量自洽 | ✅ PASS | 118 = 68 + 50 |

**结果：12 PASS / 0 FAIL / 1 WARN（可接受）**

---

## 五、发现的 Bug 及修复记录

| # | Bug 描述 | 位置 | 修复方式 |
|---|---------|------|---------|
| 1 | `export_site_series` 硬编码 `power_pred`，未使用校准后的 `power_pred_final` | `export_interactive_dashboard_data.py` | 导入 `resolve_prediction_column()`，动态解析预测列 |
| 2 | JSON 存储 `round(value, 4)`，与 pkl 全精度比较导致浮点差异 | `check_dashboard_prediction_values_round35.py` | 对 pkl 值也应用 `round(..., 4)` 后再比较 |
| 3 | 合并 DataFrame 时 `suffixes` 策略导致 actual/pred 无 suffix，capacity 有 suffix | `check_dashboard_prediction_values_round35.py` | 显式 rename 所有参与比较的列，避免 suffix 歧义 |
| 4 | `posttrain_validation_round35.py` 中 `git ls-files` 循环逻辑错误（只检查最后一个 pattern） | `posttrain_validation_round35.py` | 改用直接 subprocess 调用，检查结果清晰 |
| 5 | `.gitignore` 未排除 `interactive_dashboard/` 下生成文件 | `.gitignore` | 新增 11 条规则排除 dashboard JSON 数据 |
| 6 | Round34 报告路径误写为 `metrics/docs/` | `posttrain_validation_round34.py` | 改为 `docs/` + `os.makedirs(DOCS, exist_ok=True)` |

---

## 六、Git 清理结果

| 项目 | 处理前 | 处理后 |
|------|--------|--------|
| 追踪的 site_series JSON | 160 个 | 0 个 |
| 追踪的 city_series.json | 1 个 | 0 个 |
| 追踪的 dashboard JSON（其他） | 若干 | 0 个 |
| 本次提交净变更 | — | -9.7MB（删除了 ~9.7MB JSON 数据） |

> 原因：`interactive_dashboard/` 为生成数据（每次 `export_interactive_dashboard_data.py` 重新生成），不应纳入版本控制。已通过 `git rm --cached -r` 移除并写入 `.gitignore`，本地文件保留。

---

## 七、新增/修改文件清单

### 新增脚本（2 个）
```
scripts/check_dashboard_prediction_values_round35.py   # 68站全量pred/actual一致性检查
scripts/posttrain_validation_round35.py               # Round35 总体验证（13项）
```

### 修改文件（3 个）
```
scripts/export_interactive_dashboard_data.py           # pred_mw改用power_pred_final；加sys.path
scripts/posttrain_validation_round34.py                # 报告路径修正为docs/
.gitignore                                          # 新增interactive_dashboard排除规则
```

### 项目报告修改
```
光伏功率预测项目.md                                  # 新增口径说明段落
Round34_执行反馈报告.md                              # 移除历史口径NRMSE数值，加注说明
```

### 新增输出文件
```
output/pv_pipeline/metrics/round35_dashboard_prediction_consistency.csv
output/pv_pipeline/docs/Round35_产物收口与可视化一致性验证报告.md
output/pv_pipeline/docs/Round35_可视化预测值一致性检查报告.md
```

---

## 八、执行顺序

```bash
# Step 6：重新导出可视化（使用 power_pred_final）
python scripts/export_interactive_dashboard_data.py

# Step 1：全量一致性检查
python scripts/check_dashboard_prediction_values_round35.py

# Step 7：总体验证（会生成 Round35 验证报告）
python scripts/posttrain_validation_round35.py
```

---

## 九、Round34 与 Round35 对比

| 项目 | Round34 | Round35 |
|------|---------|---------|
| 全市 NRMSE 计算口径 | 已修复为城市聚合口径 | — |
| 站点有效性分层 | 已新增"无测试预测结果" | — |
| power_pred_final 落地 | 已写入 pkl | — |
| 典型站点互斥 | 已修复 | — |
| 可视化 pred_mw 来源 | 硬编码 power_pred | **改用 power_pred_final** |
| pred/actual 一致性 | 仅 actual 验证通过 | **pred+actual 全量验证** |
| Git 追踪清理 | 未处理 | **160 个 JSON 已移除** |
| 报告路径 | metrics/docs/ | **docs/** |
