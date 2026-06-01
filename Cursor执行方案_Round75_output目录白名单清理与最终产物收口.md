# Cursor执行方案 Round75：output 目录白名单清理与最终产物收口

## 一、目标

当前 `output/pv_pipeline/` 下仍存在大量历史修改残留，例如：

```text
archive_before_round36/
calibration/
diagnostics/
interactive_dashboard_round64_candidate/
round63/
round64/
round66/
round67/
round68/
round69/
round74/
cache/
models/
```

这些目录会造成两个问题：

1. 甲方或后续维护者无法判断哪个结果才是正式结果。
2. 可视化、报告、metrics 可能误读历史 round 产物。

本轮目标：

```text
以白名单方式清理 output/pv_pipeline，只保留正式交付所需目录。
历史 round 与候选结果统一归档到 archive/failed_or_old_rounds/，不再散落在 output 根目录。
```

---

## 二、当前正式版本

当前正式版本为：

```text
Round68 final
prediction column: power_pred_final
```

清理前必须先确认：

```text
city_nrmse_6_19 ≈ 4.1317%
site_mean_nrmse_6_19 ≈ 10.5774%
abs_bias_6_19 ≈ 0.5208%
future_rows = 0
```

如果不满足，停止清理，先恢复 Round68 final。

---

## 三、最终 output 白名单

`output/pv_pipeline/` 根目录最终只建议保留：

```text
output/pv_pipeline/
├── predictions/                 # 正式 final pkl
├── metrics/                     # 正式指标 csv/json
├── interactive_dashboard/       # 正式可视化数据
├── docs/                        # 正式报告
├── figures/                     # 正式图表
├── figures_dashboard/           # 可视化截图/图表，如确认为正式需要
├── tables/                      # 正式表格
├── validation/                  # 正式 validation 输出
├── logs/                        # 最近一次正式运行日志
├── baselines/                   # 只保留 round61/round68 等稳定基线说明
├── backups/                     # 只保留少量关键备份
└── manifest.json                # 正式 manifest
```

可选保留：

```text
models/
```

仅当当前正式流程仍需要加载模型文件时保留。否则归档。

---

## 四、需要归档或删除的目录

### 4.1 必须从 output 根目录移走

以下目录不应继续放在 `output/pv_pipeline/` 根目录：

```text
archive_before_round36/
calibration/
diagnostics/
cache/
interactive_dashboard_round64_candidate/
round63/
round64/
round66/
round67/
round68/
round69/
round70/
round71/
round72/
round73/
round74/
```

处理方式：

```text
移动到 archive/old_output_pv_pipeline/YYYYMMDD_HHMMSS/
```

不要直接删除，除非明确是 `.DS_Store`、`__MACOSX`、`._*`、临时文件。

### 4.2 根目录脚本残留

截图里还有：

```text
output/pv_pipeline/analyze_and_annotate.py
output/pv_pipeline/analyze_predictions.py
```

原则：

- `output/` 不应该放脚本；
- 如果脚本仍有价值，移动到：

```text
scripts/archive/
```

- 如果只是历史分析脚本，移动到：

```text
archive/old_output_pv_pipeline/scripts/
```

---

## 五、实现清理脚本

新建：

```text
scripts/cleanup_output_pv_pipeline_whitelist.py
```

### 5.1 参数

支持：

```bash
--dry-run
--apply
--output-root output/pv_pipeline
--archive-root archive/old_output_pv_pipeline
```

默认必须是 dry-run。

### 5.2 白名单

脚本内定义：

```python
KEEP_DIRS = {
    "predictions",
    "metrics",
    "interactive_dashboard",
    "docs",
    "figures",
    "figures_dashboard",
    "tables",
    "validation",
    "logs",
    "baselines",
    "backups",
}

KEEP_FILES = {
    "manifest.json",
}
```

`models` 是否保留：

```python
KEEP_MODELS_IF_USED = True
```

判断方式：

- 如果正式 pipeline 或 manifest 引用了 `models/`，保留；
- 否则归档。

### 5.3 归档规则

所有非白名单目录移动到：

```text
archive/old_output_pv_pipeline/YYYYMMDD_HHMMSS/<原目录名>
```

所有 output 根目录下的 `.py` 文件移动到：

```text
archive/old_output_pv_pipeline/YYYYMMDD_HHMMSS/root_scripts/
```

### 5.4 垃圾文件直接删除

以下文件可以删除，不需要归档：

```text
.DS_Store
__MACOSX/
._*
*.tmp
*🍒*
```

但也必须在 dry-run 清单中列出。

### 5.5 输出清单

输出：

```text
output/pv_pipeline/validation/round75_output_cleanup_plan.csv
output/pv_pipeline/validation/round75_output_cleanup_apply_log.csv
output/pv_pipeline/validation/round75_output_tree_after.txt
```

注意：清理脚本输出放在 `validation/`，因为 `round75/` 本身不在白名单里。

---

## 六、清理前校验

执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/verify_current_best_round68.py
```

必须通过后继续。

生成清理计划：

```bash
python scripts/cleanup_output_pv_pipeline_whitelist.py \
  --output-root output/pv_pipeline \
  --archive-root archive/old_output_pv_pipeline \
  --dry-run
```

查看清单：

```bash
sed -n '1,200p' output/pv_pipeline/validation/round75_output_cleanup_plan.csv
```

确认没有包含：

```text
predictions/
metrics/
interactive_dashboard/
manifest.json
baselines/
backups/
```

---

## 七、执行清理

确认 dry-run 无误后执行：

```bash
python scripts/cleanup_output_pv_pipeline_whitelist.py \
  --output-root output/pv_pipeline \
  --archive-root archive/old_output_pv_pipeline \
  --apply
```

执行后查看目录：

```bash
find output/pv_pipeline -maxdepth 2 -type d | sort > output/pv_pipeline/validation/round75_output_tree_after.txt
sed -n '1,200p' output/pv_pipeline/validation/round75_output_tree_after.txt
```

`output/pv_pipeline/` 根目录不应再出现：

```text
round63/
round64/
round66/
round67/
round68/
round69/
round74/
interactive_dashboard_round64_candidate/
archive_before_round36/
calibration/
diagnostics/
cache/
```

---

## 八、刷新正式可视化数据

清理后重新导出正式可视化：

```bash
python scripts/export_interactive_dashboard_data.py \
  --prediction-pkl output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --prediction-col power_pred_final \
  --dashboard-root output/pv_pipeline/interactive_dashboard \
  --label "Round68 final" \
  --exclude-future
```

要求：

```text
output/pv_pipeline/interactive_dashboard/metadata.json
```

包含：

```json
{
  "round": "Round68 final",
  "source_round": "Round68",
  "prediction_column": "power_pred_final",
  "official_final": true,
  "exclude_future": true
}
```

---

## 九、重新校验正式产物

执行：

```bash
python scripts/check_dashboard_prediction_values_round66.py \
  --prediction-pkl output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --prediction-col power_pred_final \
  --dashboard-root output/pv_pipeline/interactive_dashboard \
  --fail-on-future

python scripts/update_final_manifest_hashes.py

python scripts/posttrain_validation.py
```

要求：

```text
posttrain validation: FAIL = 0
dashboard consistency: PASS
future rows: 0
```

---

## 十、生成 Round75 报告

新建：

```text
docs/Round75_output目录白名单清理与最终产物收口报告.md
```

报告必须包含：

1. 清理前是否确认 Round68 final。
2. 清理前 output 根目录有哪些残留。
3. 哪些目录被归档。
4. 哪些垃圾文件被删除。
5. 清理后 output 根目录树。
6. 可视化是否重新导出。
7. 可视化是否与 final pkl 一致。
8. manifest 是否更新。
9. validation 是否通过。
10. 当前正式产物目录说明。

---

## 十一、执行命令汇总

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/verify_current_best_round68.py

python scripts/cleanup_output_pv_pipeline_whitelist.py \
  --output-root output/pv_pipeline \
  --archive-root archive/old_output_pv_pipeline \
  --dry-run

sed -n '1,200p' output/pv_pipeline/validation/round75_output_cleanup_plan.csv

python scripts/cleanup_output_pv_pipeline_whitelist.py \
  --output-root output/pv_pipeline \
  --archive-root archive/old_output_pv_pipeline \
  --apply

find output/pv_pipeline -maxdepth 2 -type d | sort > output/pv_pipeline/validation/round75_output_tree_after.txt

python scripts/export_interactive_dashboard_data.py \
  --prediction-pkl output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --prediction-col power_pred_final \
  --dashboard-root output/pv_pipeline/interactive_dashboard \
  --label "Round68 final" \
  --exclude-future

python scripts/check_dashboard_prediction_values_round66.py \
  --prediction-pkl output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --prediction-col power_pred_final \
  --dashboard-root output/pv_pipeline/interactive_dashboard \
  --fail-on-future

python scripts/update_final_manifest_hashes.py
python scripts/posttrain_validation.py
```

---

## 十二、Git 提交

执行通过后：

```bash
git status

git add scripts/cleanup_output_pv_pipeline_whitelist.py
git add scripts/export_interactive_dashboard_data.py
git add scripts/update_final_manifest_hashes.py
git add docs/Round75_output目录白名单清理与最终产物收口报告.md
git add output/pv_pipeline/validation/round75_output_cleanup_plan.csv
git add output/pv_pipeline/validation/round75_output_cleanup_apply_log.csv
git add output/pv_pipeline/validation/round75_output_tree_after.txt
git add output/pv_pipeline/manifest.json

git commit -m "chore: clean output artifacts and keep final round68 deliverables"
git tag -a round68-final-output-clean-20260601 -m "Round68 final with cleaned output directory"
git push origin HEAD
git push origin round68-final-output-clean-20260601
```

不要提交：

```text
archive/old_output_pv_pipeline/**/*
output/pv_pipeline/predictions/*.pkl
output/pv_pipeline/interactive_dashboard/**/*.json
```

---

## 十三、验收标准

通过标准：

1. output 根目录只保留白名单目录和 `manifest.json`。
2. 历史 round 目录不再散落在 output 根目录。
3. “🍒”、`__MACOSX`、`.DS_Store`、`._*`、`未命名` 等残留清理完成。
4. 当前正式结果仍是 Round68 final。
5. 可视化数据已刷新。
6. dashboard consistency 通过。
7. posttrain validation 无 FAIL。
8. Git tag 已创建。

---

## 十四、执行完成后发回

请发回：

```text
docs/Round75_output目录白名单清理与最终产物收口报告.md
output/pv_pipeline/validation/round75_output_cleanup_plan.csv
output/pv_pipeline/validation/round75_output_cleanup_apply_log.csv
output/pv_pipeline/validation/round75_output_tree_after.txt
output/pv_pipeline/interactive_dashboard/metadata.json
output/pv_pipeline/manifest.json
```

我会检查：

- output 是否真的清爽；
- 是否误删正式产物；
- 可视化是否最新；
- 是否可以把当前项目作为最终稳定交付版本。

