# Cursor执行方案 Round65：采用 Round64 候选前的全量审计与可视化收口

## 一、目标

Round64 safe 已经显示出稳健小幅提升，但还不能直接覆盖正式结果。本轮一次性完成以下工作：

1. 修正 Round64 报告中的表述问题。
2. 规范 Round64 产物目录，去掉“未命名”目录。
3. 生成全量站点级对比，验证 `bad_sites=0` 是否真实成立。
4. 生成 Round64 候选可视化数据目录，不覆盖正式可视化。
5. 校验候选可视化中的真实值、预测值与候选 pkl 完全一致。
6. 输出“是否建议将 Round64 升级为正式 final”的明确结论。
7. 若建议升级，只生成升级脚本和 dry-run 报告，本轮仍不要直接覆盖正式结果。

本轮重点是：**让 Round64 从“结果看起来不错”变成“可审计、可展示、可回退、可正式采用的候选版本”。**

---

## 二、执行前原则

必须遵守：

- 不重新训练。
- 不修改指标公式。
- 不使用 test 集调参。
- 不直接覆盖 Round61/Round64 之前的正式结果。
- 不直接覆盖 `distributed_predictions_final_full.pkl`。
- 不直接覆盖正式 `interactive_dashboard/` 目录。
- 先生成 candidate 产物和 dry-run 升级报告。

---

## 三、规范 Round64 输出目录

### 3.1 检查并迁移“未命名”目录

现在压缩包中出现：

```text
output/pv_pipeline/round64/未命名/
```

需要改为：

```text
output/pv_pipeline/round64/
```

Cursor 中执行或写脚本处理：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

mkdir -p output/pv_pipeline/round64

if [ -d "output/pv_pipeline/round64/未命名" ]; then
  cp -n output/pv_pipeline/round64/未命名/* output/pv_pipeline/round64/
fi
```

然后检查：

```bash
ls -lh output/pv_pipeline/round64/
```

要求这些文件位于标准目录：

```text
round64_site_scene_weights.csv
round64_valid_weight_search.csv
round64_test_overall_compare.csv
round64_test_hourly_compare.csv
round64_test_site_compare.csv
round64_final_decision.json
round64_guard_summary.json
round64_candidates.pkl
```

### 3.2 后续脚本禁止再写入“未命名”

检查以下脚本是否有硬编码或默认空目录导致“未命名”：

```text
scripts/build_round64_safe_residual_blend.py
scripts/evaluate_round64_safe_blend.py
scripts/select_round64_final_decision.py
```

统一改成：

```python
output_dir = Path("output/pv_pipeline/round64")
output_dir.mkdir(parents=True, exist_ok=True)
```

---

## 四、修正 Round64 报告

文件：

```text
docs/Round64_安全残差融合与训练链路收口报告.md
```

### 4.1 修正“最优”列

当前表里“最优”列可能写成 `Round64 safe`，但数值上部分指标是 `Round63 lgb` 更低。

请改为两个概念：

```text
数值最优：单看 test 指标最低的候选。
可采用最优：同时满足 valid 安全门控、站点不退化、可回退要求的候选。
```

表格建议改成：

| 指标 | Round61 | Round63 lgb | Round64 safe | 数值最优 | 可采用最优 |
|---|---:|---:|---:|---|---|

结论中明确：

```text
Round63 lgb 在部分 test 指标上数值更优，但 valid 上存在站点退化，不能直接采用。
Round64 safe 的数值提升略小，但 valid 安全门控通过，且 test 上无 >+1pp 站点退化，因此是当前可采用最优候选。
```

### 4.2 增加“为什么提升不大”的解释

报告中加入：

```text
Round64 不是重训主模型，而是对 Round63 lgb 残差候选做安全融合。
大量站点-场景权重为 0，说明残差模型只在部分站点和部分时段有效。
因此 Round64 的定位是稳健小幅提升，而不是模型能力大幅突破。
```

---

## 五、补全全量站点审计

### 5.1 新建脚本

新建：

```text
scripts/audit_round64_all_sites.py
```

功能：

读取：

```text
output/pv_pipeline/round64/round64_candidates.pkl
```

对 test 集 6-19 点、所有有效站点计算：

```text
Round61 NRMSE
Round63 lgb NRMSE
Round64 safe NRMSE
Round64 - Round61 delta
Round63 lgb - Round61 delta
MAE
RMSE
pred/actual
capacity_mw
test_samples
test_positive_samples
test_6_19_zero_ratio
selected_weight_summary
```

输出：

```text
output/pv_pipeline/round64/round64_all_site_compare.csv
output/pv_pipeline/round64/round64_bad_site_audit.csv
```

其中：

```text
round64_bad_site_audit.csv
```

只保留：

```text
delta_nrmse_round64_vs_round61 > 1.0
```

如果没有，输出空表但保留表头。

### 5.2 必须验证

脚本最后打印：

```text
total_sites =
bad_sites_gt_1pp =
max_delta_nrmse =
min_delta_nrmse =
mean_delta_nrmse =
```

如果 `bad_sites_gt_1pp != 0`，脚本退出非 0。

---

## 六、生成 Round64 候选可视化数据

### 6.1 新增导出参数

修改：

```text
scripts/export_interactive_dashboard_data.py
```

支持参数：

```bash
--prediction-pkl output/pv_pipeline/round64/round64_candidates.pkl
--prediction-col power_pred_round64_safe
--output-dir output/pv_pipeline/interactive_dashboard_round64_candidate
--label "Round64 safe candidate"
--exclude-future
```

注意：

- 不要覆盖 `output/pv_pipeline/interactive_dashboard/`。
- 候选可视化目录必须单独存在。

### 6.2 执行导出

```bash
python scripts/export_interactive_dashboard_data.py \
  --prediction-pkl output/pv_pipeline/round64/round64_candidates.pkl \
  --prediction-col power_pred_round64_safe \
  --output-dir output/pv_pipeline/interactive_dashboard_round64_candidate \
  --label "Round64 safe candidate" \
  --exclude-future
```

### 6.3 候选可视化元数据要求

检查：

```text
output/pv_pipeline/interactive_dashboard_round64_candidate/metadata.json
```

必须包含：

```json
{
  "prediction_column": "power_pred_round64_safe",
  "label": "Round64 safe candidate",
  "source_round": "Round64",
  "official_final": false,
  "exclude_future": true
}
```

---

## 七、校验候选可视化数据一致性

### 7.1 新建脚本

新建：

```text
scripts/check_round64_dashboard_candidate_consistency.py
```

校验内容：

1. 页面 JSON 中 `actual_mw` 与 `round64_candidates.pkl` 的 `power_mw` 一致。
2. 页面 JSON 中 `pred_mw` 与 `power_pred_round64_safe` 一致。
3. 全市聚合 JSON 与逐站点 JSON 聚合后结果一致。
4. 不包含 future。
5. metadata 中 `prediction_column` 正确。

输出：

```text
output/pv_pipeline/round64/round64_dashboard_candidate_consistency.csv
output/pv_pipeline/round64/round64_dashboard_candidate_consistency.json
```

如果最大差值超过：

```text
1e-9
```

脚本退出非 0。

### 7.2 执行

```bash
python scripts/check_round64_dashboard_candidate_consistency.py
```

---

## 八、生成正式升级 dry-run

### 8.1 新建脚本

新建：

```text
scripts/promote_round64_candidate.py
```

支持两个模式：

```bash
--dry-run
--apply
```

本轮只执行 dry-run，不执行 apply。

dry-run 要输出：

```text
output/pv_pipeline/round64/round64_promote_dry_run_report.md
output/pv_pipeline/round64/round64_promote_file_plan.csv
```

文件计划至少包含：

| 动作 | 源文件 | 目标文件 | 是否覆盖 | 备注 |
|---|---|---|---|---|

如果未来 apply，需要做：

```text
备份当前 final pkl
写入 Round64 final pkl
更新 final metadata
重新导出正式 interactive_dashboard
重新运行 posttrain validation
```

但本轮不能实际 apply。

### 8.2 执行 dry-run

```bash
python scripts/promote_round64_candidate.py --dry-run
```

---

## 九、统一生成 Round65 报告

新建：

```text
docs/Round65_Round64候选采用前全量审计与可视化收口报告.md
```

必须包含：

1. Round64 是否建议采用。
2. Round64 与 Round61 的总体指标对比。
3. 全量站点审计结果。
4. `bad_sites_gt_1pp` 是否为 0。
5. 候选可视化是否导出。
6. 候选可视化数据是否与 pkl 一致。
7. 是否已生成 promote dry-run。
8. 本轮是否覆盖正式结果：必须写“未覆盖”。
9. 下一步是否建议执行正式升级。

---

## 十、执行命令汇总

按顺序执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/audit_round64_all_sites.py

python scripts/export_interactive_dashboard_data.py \
  --prediction-pkl output/pv_pipeline/round64/round64_candidates.pkl \
  --prediction-col power_pred_round64_safe \
  --output-dir output/pv_pipeline/interactive_dashboard_round64_candidate \
  --label "Round64 safe candidate" \
  --exclude-future

python scripts/check_round64_dashboard_candidate_consistency.py

python scripts/promote_round64_candidate.py --dry-run

python scripts/posttrain_validation_round36.py
```

如果已有统一入口，可增加：

```bash
python scripts/run_full_pipeline.py --mode round65-round64-candidate-audit
```

---

## 十一、Git 提交

如果全部通过，提交：

```bash
git status

git add scripts/audit_round64_all_sites.py
git add scripts/check_round64_dashboard_candidate_consistency.py
git add scripts/promote_round64_candidate.py
git add scripts/export_interactive_dashboard_data.py
git add scripts/run_full_pipeline.py
git add docs/Round64_安全残差融合与训练链路收口报告.md
git add docs/Round65_Round64候选采用前全量审计与可视化收口报告.md
git add output/pv_pipeline/round64/*.csv
git add output/pv_pipeline/round64/*.json
git add output/pv_pipeline/round64/*.md

git commit -m "chore: audit round64 candidate before promotion"
git push origin HEAD
```

不要提交：

```text
round64_candidates.pkl
interactive_dashboard_round64_candidate/**/*.json
*.pkl
*.joblib
*.parquet
```

---

## 十二、验收标准

本轮通过标准：

1. Round64 产物目录规范，不再出现“未命名”目录作为正式路径。
2. `round64_all_site_compare.csv` 覆盖全量有效站点。
3. `round64_bad_site_audit.csv` 显示 `bad_sites_gt_1pp = 0`。
4. 候选可视化目录生成成功。
5. 候选可视化真实值和预测值与 `round64_candidates.pkl` 完全一致。
6. 已生成 promote dry-run，但没有正式覆盖。
7. Round65 报告明确建议是否升级。

---

## 十三、执行完成后发回

请打包发回：

```text
docs/Round65_Round64候选采用前全量审计与可视化收口报告.md
output/pv_pipeline/round64/round64_all_site_compare.csv
output/pv_pipeline/round64/round64_bad_site_audit.csv
output/pv_pipeline/round64/round64_dashboard_candidate_consistency.csv
output/pv_pipeline/round64/round64_dashboard_candidate_consistency.json
output/pv_pipeline/round64/round64_promote_dry_run_report.md
output/pv_pipeline/round64/round64_promote_file_plan.csv
output/pv_pipeline/interactive_dashboard_round64_candidate/metadata.json
```

我会据此判断是否可以进入 Round66：正式升级 Round64 为 final，并重新生成正式可视化和项目报告。

