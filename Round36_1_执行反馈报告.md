# Round36.1 执行反馈报告

**时间**：2026-05-28 22:50 (UTC+8)
**执行方式**：无需重新训练，修复报告/校验/日志自动化

---

## 一、验收标准核对

| 验收项 | 要求 | 实际 | 状态 |
|--------|------|------|------|
| 不重新训练 | 无需训练 | 无训练调用 | ✅ |
| posttrain_validation | 0 FAIL, 0 WARN | 18 PASS / 0 FAIL / 0 WARN | ✅ |
| 报告不含 MAPE 核心指标 | MAPE不出现在核心结果 | MAPE仅在模型名称和口径说明中出现 | ✅ |
| 报告不含旧口径 | 无0.3365%/0.3420% | 正文未发现旧口径 | ✅ |
| Round34对比 | 从CSV自动核对 | 6.31%→4.25%，自动读取 | ✅ |
| 训练日志 | 自动补全含split行数 | 3260字，含所有必需内容 | ✅ |
| S115/S116说明 | 保留缺失说明 | 已写入"六"章节 | ✅ |
| Git不追踪大文件 | 无pkl/json/site_series | 0个文件被追踪 | ✅ |

---

## 二、修改内容详情

### 2.1 新增脚本

**`scripts/check_round36_vs_round34_metrics.py`**
- 从 `round34_city_hourly_nrmse.csv` 和 `round36_city_hourly_nrmse.csv` 自动读取10-14时NRMSE均值
- 输出 `output/pv_pipeline/metrics/round36_vs_round34_metric_check.csv`

**`scripts/generate_round36_training_log.py`**
- 读取 `distributed_predictions_final_round36.pkl` 统计 split 行数/站点数
- 输出 `output/pv_pipeline/docs/Round36_训练日志.md`
- 日志中明确注明"本日志由 Round36.1 根据 Round36 已完成训练产物自动补全生成，未重新训练"

### 2.2 修改脚本

**`scripts/posttrain_validation_round36.py`**
- C5 future：WARN → PASS（future保留在final_full但已排除指标和默认可视化）
- C16 训练日志：从"手动生成WARN"改为严格内容检查PASS（必须包含7项必需内容）

**`scripts/regenerate_project_report_round36.py`**
- 章节重构：
  - 六：S115/S116经纬度缺失说明（新增）
  - 七：Round36全链路验证摘要（新增）
  - 八：当前仍存在的问题
  - 九：指标口径说明
- 从 `round36_vs_round34_metric_check.csv` 读取Round34对比数值（自动，非手写）
- 核心指标不含MAPE，在口径说明中注明"MAPE仅在模型训练过程中作为辅助参考"

---

## 三、关键指标

| 指标 | Round34 | Round36 | 变化 |
|------|---------|---------|------|
| 全市10-14时NRMSE | 6.31% | 4.25% | **-2.06pp 改善** |

> 数据来源：`round36_vs_round34_metric_check.csv`（从真实CSV自动核对）

---

## 四、全链路验证结果

```
18 PASS | 0 FAIL | 0 WARN
```

| 检查项 | 结果 |
|--------|------|
| C1: final_round36.pkl 存在且可读 | PASS |
| C2: eval_round36 只含 test 6-19 | PASS |
| C3: power_pred_final 存在 | PASS |
| C4: power_pred_final 在 [0, capacity] | PASS |
| C5: future 不参与指标 | PASS |
| C6: 站点数量自洽（118/68/50） | PASS |
| C7: city_hourly_nrmse 口径正确 | PASS |
| C8: round36_site_metrics.csv 有效 | PASS |
| C9: typical_sites 无重复 | PASS |
| C10: dashboard pred/actual 一致 | PASS |
| C11: 可视化默认不含 future | PASS |
| C12: Git 不追踪 pkl | PASS |
| C12: Git 不追踪 site_series JSON | PASS |
| C12: Git 不追踪 tables/ | PASS |
| C13: 无旧口径（0.3365%/0.3420%） | PASS |
| C14: 报告含 Round36 内容 | PASS |
| C15: split 时间边界正确 | PASS |
| C16: 训练日志内容完整 | PASS |

---

## 五、Git 提交

```
commit d586b1c
docs: finalize round36.1 training validation report

8 files changed, 497 insertions(+), 108 deletions(-)
 rewrite Round36_训练日志.md (82%)
 create round36_vs_round34_metric_check.csv
 create check_round36_vs_round34_metrics.py
 create generate_round36_training_log.py
```

---

## 六、产出文件清单

| 文件 | 说明 |
|------|------|
| `output/pv_pipeline/metrics/round36_vs_round34_metric_check.csv` | Round34/36对比CSV |
| `output/pv_pipeline/docs/Round36_训练日志.md` | 自动补全训练日志 |
| `output/pv_pipeline/docs/Round36_训练逻辑与可视化一致性验证报告.md` | 验证报告 |
| `光伏功率预测项目.md` | 正式项目报告 |
| `scripts/check_round36_vs_round34_metrics.py` | 指标核对脚本 |
| `scripts/generate_round36_training_log.py` | 日志补全脚本 |
| `scripts/posttrain_validation_round36.py` | 验证脚本（含修复） |
| `scripts/regenerate_project_report_round36.py` | 报告生成脚本（含修复） |
