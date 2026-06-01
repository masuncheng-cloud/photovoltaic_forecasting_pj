# Cursor执行方案 Round66：正式升级 Round64 为 final，并强制排除 future 数据

## 一、目标

Round65 已确认 Round64 safe 候选具备正式采用条件。本轮执行正式升级，但增加一个硬约束：

```text
所有正式预测、正式评估、正式可视化、正式报告中都不能包含 future 数据。
```

本轮要完成：

1. 升级前再次检查 Round64 candidate 不含 future。
2. 执行 `promote_round64_candidate.py --apply`，将 Round64 safe 升级为正式 final。
3. 备份旧 final，确保可回退。
4. 重新生成正式评估指标。
5. 重新导出正式可视化数据，强制 `--exclude-future`。
6. 校验正式可视化数据与 final pkl 一致。
7. 校验所有正式输出不含 future。
8. 生成 Round66 正式升级报告。

---

## 二、执行前硬约束

如果任一检查发现 future 数据进入正式产物，必须：

```text
立即停止；
不允许继续升级；
如果已经 apply，必须回滚到备份；
报告中明确写出失败原因。
```

future 判断标准：

```text
split == "future"
```

或项目中等价的 future 标记字段。

---

## 三、升级前检查：Round64 candidate 不含 future

### 3.1 新增脚本

新建：

```text
scripts/check_no_future_in_outputs.py
```

支持参数：

```bash
--pkl-path
--csv-path
--json-dir
--name
--fail-on-future
```

功能：

1. 对 pkl：
   - 读取 DataFrame；
   - 检查是否存在 `split == "future"`；
   - 统计 `split` 分布；
   - 输出行数、future 行数。

2. 对 csv：
   - 如果有 `split` 字段，同样检查；
   - 如果没有，记录为 `NO_SPLIT_COLUMN`。

3. 对 json-dir：
   - 检查 `metadata.json` 是否有：

```json
"exclude_future": true
```

   - 抽查 `city_series.json` 和 `site_series/*.json` 是否存在 future 字段或 future 日期标记；
   - 如果 JSON 没有 split 字段，至少确认 metadata 中明确 `exclude_future=true`。

输出：

```text
output/pv_pipeline/round66/no_future_check_round64_candidate.json
output/pv_pipeline/round66/no_future_check_round64_candidate.csv
```

### 3.2 执行升级前检查

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

mkdir -p output/pv_pipeline/round66

python scripts/check_no_future_in_outputs.py \
  --pkl-path output/pv_pipeline/round64/round64_candidates.pkl \
  --name round64_candidate \
  --fail-on-future
```

要求：

```text
future_rows = 0
```

如果不为 0，需要先重新生成 `round64_candidates.pkl`，确保只包含 train/valid/test 或最终所需非 future 数据。

---

## 四、修正 promote 脚本：正式 final 也必须排除 future

修改：

```text
scripts/promote_round64_candidate.py
```

要求：

1. 写入正式 final 前，必须过滤：

```python
df = df[df["split"] != "future"].copy()
```

2. 写入前后都统计：

```text
split 分布
总行数
future 行数
```

3. 如果 future 行数不为 0，直接抛异常。

4. 写入 metadata / manifest 时记录：

```json
{
  "prediction_column": "power_pred_final",
  "source_round": "Round64",
  "exclude_future": true,
  "promoted_from": "power_pred_round64_safe"
}
```

5. 备份旧 final：

```text
output/pv_pipeline/backups/distributed_predictions_final_full_before_round64_YYYYMMDD_HHMMSS.pkl
output/pv_pipeline/backups/distributed_predictions_final_eval_before_round64_YYYYMMDD_HHMMSS.pkl
```

---

## 五、执行正式升级

执行：

```bash
python scripts/promote_round64_candidate.py --apply --exclude-future
```

如果脚本暂不支持 `--exclude-future`，请先添加该参数，默认也应为 true。

升级后必须生成：

```text
output/pv_pipeline/round66/round66_promote_apply_report.md
output/pv_pipeline/round66/round66_promote_file_plan.csv
output/pv_pipeline/round66/round66_backup_files.json
```

---

## 六、升级后检查：正式 final 不含 future

执行：

```bash
python scripts/check_no_future_in_outputs.py \
  --pkl-path output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --name final_full_after_round64_promote \
  --fail-on-future

python scripts/check_no_future_in_outputs.py \
  --pkl-path output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl \
  --name final_eval_after_round64_promote \
  --fail-on-future
```

要求：

```text
future_rows = 0
```

---

## 七、重新生成正式指标

执行现有正式指标脚本，例如：

```bash
python scripts/compute_hourly_relative_error_robust.py
python scripts/regenerate_chinese_metrics.py
python scripts/posttrain_validation_round36.py
```

如果已有统一入口，建议增加：

```bash
python scripts/run_full_pipeline.py --mode post-promote-validation
```

要求：

- 所有评估默认读取正式 final；
- 所有评估过滤 `split != "future"`；
- 报告中明确写：

```text
本轮正式结果不包含 future 数据。
```

---

## 八、重新导出正式可视化，强制不含 future

执行：

```bash
python scripts/export_interactive_dashboard_data.py \
  --prediction-pkl output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --prediction-col power_pred_final \
  --dashboard-root output/pv_pipeline/interactive_dashboard \
  --label "Round64 final" \
  --exclude-future
```

注意：

- 这一步是正式可视化目录，可以覆盖；
- 但只能在 final pkl 已确认不含 future 后执行；
- metadata 必须包含：

```json
{
  "prediction_column": "power_pred_final",
  "source_round": "Round64",
  "official_final": true,
  "exclude_future": true
}
```

---

## 九、正式可视化一致性校验

新增或修改：

```text
scripts/check_dashboard_prediction_values_round66.py
```

或扩展现有脚本支持：

```bash
python scripts/check_dashboard_prediction_values_round66.py \
  --prediction-pkl output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --prediction-col power_pred_final \
  --dashboard-root output/pv_pipeline/interactive_dashboard \
  --fail-on-future
```

校验：

1. 页面 `actual_mw` 与 final pkl `power_mw` 一致。
2. 页面 `pred_mw` 与 final pkl `power_pred_final` 一致。
3. city 聚合与站点聚合一致。
4. metadata `exclude_future=true`。
5. 页面 JSON 不含 future。

输出：

```text
output/pv_pipeline/round66/round66_dashboard_final_consistency.csv
output/pv_pipeline/round66/round66_dashboard_final_consistency.json
```

---

## 十、如果升级失败，必须回滚

修改或新增：

```text
scripts/rollback_round64_promotion.py
```

支持：

```bash
python scripts/rollback_round64_promotion.py --latest-backup
```

回滚内容：

```text
恢复 distributed_predictions_final_full.pkl
恢复 distributed_predictions_final_eval.pkl
恢复 manifest.json
重新导出 Round61 正式可视化
重新运行 posttrain validation
```

Round66 报告中必须写清楚：

```text
是否发生回滚：是/否
如果是，回滚到哪个备份文件
```

---

## 十一、生成 Round66 报告

新建：

```text
docs/Round66_正式升级Round64并排除future数据报告.md
```

必须包含：

1. 是否执行正式升级。
2. 是否备份旧 final。
3. 备份文件路径。
4. final_full 行数、split 分布、future 行数。
5. final_eval 行数、split 分布、future 行数。
6. 正式可视化 metadata。
7. 正式可视化一致性校验结果。
8. Round64 final 与 Round61 的核心指标对比。
9. 是否发生回滚。
10. 当前正式结果来自：

```text
Round64 safe candidate
```

11. 明确写：

```text
正式产物不包含 future 数据。
```

---

## 十二、执行命令汇总

按顺序执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

mkdir -p output/pv_pipeline/round66

python scripts/check_no_future_in_outputs.py \
  --pkl-path output/pv_pipeline/round64/round64_candidates.pkl \
  --name round64_candidate \
  --fail-on-future

python scripts/promote_round64_candidate.py --apply --exclude-future

python scripts/check_no_future_in_outputs.py \
  --pkl-path output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --name final_full_after_round64_promote \
  --fail-on-future

python scripts/check_no_future_in_outputs.py \
  --pkl-path output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl \
  --name final_eval_after_round64_promote \
  --fail-on-future

python scripts/export_interactive_dashboard_data.py \
  --prediction-pkl output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --prediction-col power_pred_final \
  --dashboard-root output/pv_pipeline/interactive_dashboard \
  --label "Round64 final" \
  --exclude-future

python scripts/check_dashboard_prediction_values_round66.py \
  --prediction-pkl output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --prediction-col power_pred_final \
  --dashboard-root output/pv_pipeline/interactive_dashboard \
  --fail-on-future

python scripts/posttrain_validation_round36.py
python scripts/regenerate_chinese_metrics.py
```

---

## 十三、Git 提交

通过后提交：

```bash
git status

git add scripts/check_no_future_in_outputs.py
git add scripts/promote_round64_candidate.py
git add scripts/check_dashboard_prediction_values_round66.py
git add scripts/rollback_round64_promotion.py
git add scripts/export_interactive_dashboard_data.py
git add docs/Round66_正式升级Round64并排除future数据报告.md
git add output/pv_pipeline/round66/*.csv
git add output/pv_pipeline/round66/*.json
git add output/pv_pipeline/round66/*.md

git commit -m "chore: promote round64 final without future data"
git tag -a round64-final-no-future-20260601 -m "Round64 final promoted with future data excluded"
git push origin HEAD
git push origin round64-final-no-future-20260601
```

不要提交：

```text
*.pkl
interactive_dashboard/**/*.json
```

---

## 十四、验收标准

本轮通过标准：

1. Round64 正式升级成功。
2. 旧 final 已备份。
3. final_full 不含 future。
4. final_eval 不含 future。
5. 正式可视化不含 future。
6. 正式可视化与 final pkl 一致。
7. 指标重新生成成功。
8. Round66 报告明确当前正式结果来自 Round64 safe。
9. Git tag 已创建，方便回退。

---

## 十五、执行完成后发回

请发回：

```text
docs/Round66_正式升级Round64并排除future数据报告.md
output/pv_pipeline/round66/no_future_check_*.json
output/pv_pipeline/round66/round66_dashboard_final_consistency.json
output/pv_pipeline/round66/round66_dashboard_final_consistency.csv
output/pv_pipeline/round66/round66_promote_apply_report.md
output/pv_pipeline/manifest.json
```

我会检查：

- 正式结果是否真的不含 future；
- 可视化是否使用最新 final；
- 是否可以把 Round64 作为新的正式基线；
- 下一步是否进入主模型结构继续优化。

