# Cursor执行方案 Round74：回退最优版本、清理残留并刷新可视化

## 一、目标

当前最优版本为：

```text
Round68 final
prediction column: power_pred_final
```

本轮不再继续训练新模型，目标是做一次正式收口：

1. 回退或确认当前正式结果为 Round68 final。
2. 删除/归档 Round70-Round73 失败实验产物。
3. 清理之前多轮修改产生的临时文件、异常文件、无用文件，包括文件名异常或包含特殊符号的“🍒”类文件。
4. 重新生成正式可视化网页数据。
5. 校验正式结果与可视化数据一致。
6. 更新 manifest、validation 和最终说明报告。

---

## 二、最优版本定义

Round68 final 的参考指标：

| 指标 | 目标值 |
|---|---:|
| city_nrmse_6_19 | 4.1317% |
| site_mean_nrmse_6_19 | 10.5774% |
| abs_bias_6_19 | 0.5208% |
| future_rows | 0 |

只要当前正式结果满足上述容差，即认为已经处于最优版本，不需要重新 promote。

容差：

```text
city_nrmse_6_19 ± 0.02pp
site_mean_nrmse_6_19 ± 0.02pp
abs_bias_6_19 ± 0.05pp
future_rows = 0
```

---

## 三、执行前备份

进入项目目录：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
```

创建本轮备份目录：

```bash
mkdir -p output/pv_pipeline/backups/round74_cleanup_$(date +%Y%m%d_%H%M%S)
```

备份正式产物：

```bash
BACKUP_DIR=$(ls -td output/pv_pipeline/backups/round74_cleanup_* | head -1)

cp -a output/pv_pipeline/predictions/distributed_predictions_final_full.pkl "$BACKUP_DIR/" 2>/dev/null || true
cp -a output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl "$BACKUP_DIR/" 2>/dev/null || true
cp -a output/pv_pipeline/interactive_dashboard "$BACKUP_DIR/interactive_dashboard_backup" 2>/dev/null || true
cp -a output/pv_pipeline/manifest.json "$BACKUP_DIR/" 2>/dev/null || true
```

记录当前 Git 状态：

```bash
git status > "$BACKUP_DIR/git_status_before_round74.txt"
git rev-parse HEAD > "$BACKUP_DIR/git_head_before_round74.txt"
```

---

## 四、确认或回退到 Round68 final

### 4.1 新增/使用校验脚本

如果已有：

```text
scripts/verify_current_best_round68.py
```

直接执行：

```bash
python scripts/verify_current_best_round68.py
```

如果没有，请新建该脚本，检查：

1. `distributed_predictions_final_full.pkl` 是否存在。
2. `distributed_predictions_final_eval.pkl` 是否存在。
3. `future_rows == 0`。
4. test 6-19 指标是否接近 Round68 final：

```text
city_nrmse_6_19 ≈ 4.1317%
site_mean_nrmse_6_19 ≈ 10.5774%
abs_bias_6_19 ≈ 0.5208%
```

输出：

```text
output/pv_pipeline/round74/round74_verify_round68_final.json
output/pv_pipeline/round74/round74_verify_round68_final.csv
```

### 4.2 如果当前不是 Round68 final

优先使用 Round68 promotion 脚本重新恢复：

```bash
python scripts/promote_round68_candidate.py --apply --exclude-future
```

然后再次执行：

```bash
python scripts/verify_current_best_round68.py
```

如果没有 Round68 candidate pkl，需要从备份或 Git tag 恢复，不要直接 `git reset --hard`。先查：

```bash
git tag | grep round68
find output/pv_pipeline -name "*round68*" -o -name "*before_round68*"
```

必须确认正式结果通过 Round68 校验后，再进入清理。

---

## 五、清理失败实验产物

### 5.1 原则

正式保留：

```text
output/pv_pipeline/predictions/
output/pv_pipeline/interactive_dashboard/
output/pv_pipeline/manifest.json
output/pv_pipeline/metrics/
output/pv_pipeline/baselines/round61/
docs/Round68_*.md
docs/Round69_*.md
```

清理或归档：

```text
output/pv_pipeline/round70/
output/pv_pipeline/round71/
output/pv_pipeline/round72/
output/pv_pipeline/round73/
docs/Round70_*.md
docs/Round71_*.md
docs/Round72_*.md
docs/Round73_*.md
archive/failed_experiments/ 中重复或临时文件
```

### 5.2 建议先归档，再删除源目录

创建归档目录：

```bash
mkdir -p archive/failed_experiments_round74
```

Dry-run 查看将要移动的文件：

```bash
python scripts/cleanup_round74_failed_artifacts.py --dry-run
```

如果没有该脚本，新建：

```text
scripts/cleanup_round74_failed_artifacts.py
```

脚本功能：

- 扫描 Round70-Round73 输出和报告；
- 生成清理清单；
- 默认只 dry-run；
- `--apply` 时先移动到 `archive/failed_experiments_round74/`，再从正式输出目录删除；
- 不允许删除 predictions、interactive_dashboard、metrics、manifest、baselines。

输出：

```text
output/pv_pipeline/round74/round74_cleanup_plan.csv
output/pv_pipeline/round74/round74_cleanup_apply_log.csv
```

执行：

```bash
python scripts/cleanup_round74_failed_artifacts.py --dry-run
python scripts/cleanup_round74_failed_artifacts.py --apply
```

---

## 六、清理“🍒”和异常残留文件

### 6.1 先扫描

不要直接删除，先扫描：

```bash
find . -name "*🍒*" -o -name "._*" -o -name ".DS_Store" -o -name "*未命名*" -o -name "*临时*" -o -name "*tmp*" > output/pv_pipeline/round74/round74_special_file_scan.txt
```

同时扫描常见异常残留：

```bash
find . \
  \( -name "__MACOSX" -o -name ".DS_Store" -o -name "._*" -o -name "*🍒*" -o -name "*未命名*" -o -name "*临时*" -o -name "*.tmp" -o -name "*.bak" \) \
  -print > output/pv_pipeline/round74/round74_junk_file_scan.txt
```

人工检查：

```bash
sed -n '1,200p' output/pv_pipeline/round74/round74_junk_file_scan.txt
```

### 6.2 新建清理脚本

新建：

```text
scripts/cleanup_junk_files_round74.py
```

要求：

- 默认 `--dry-run`；
- 只清理明确无用文件：

```text
.DS_Store
__MACOSX/
._*
*.tmp
*临时*
*未命名*
*🍒*
```

- 不清理 `.pkl` 正式产物；
- 不清理 `predictions/`；
- 不清理 `interactive_dashboard/` 当前正式目录；
- 不清理 `metrics/`；
- 不清理 `configs/`；
- 不清理 `scripts/` 中非临时脚本。

执行：

```bash
python scripts/cleanup_junk_files_round74.py --dry-run
python scripts/cleanup_junk_files_round74.py --apply
```

输出：

```text
output/pv_pipeline/round74/round74_junk_cleanup_plan.csv
output/pv_pipeline/round74/round74_junk_cleanup_apply_log.csv
```

---

## 七、重新导出正式可视化网页数据

确认当前正式 pkl 已是 Round68 final 后执行：

```bash
python scripts/export_interactive_dashboard_data.py \
  --prediction-pkl output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --prediction-col power_pred_final \
  --dashboard-root output/pv_pipeline/interactive_dashboard \
  --label "Round68 final" \
  --exclude-future
```

要求 `metadata.json` 包含：

```json
{
  "round": "Round68 final",
  "prediction_column": "power_pred_final",
  "official_final": true,
  "exclude_future": true,
  "source_round": "Round68"
}
```

如果导出脚本目前显示 `Round64` 或 `Round66` 等旧标签，必须改为 `Round68 final`。

---

## 八、可视化一致性校验

执行：

```bash
python scripts/check_dashboard_prediction_values_round66.py \
  --prediction-pkl output/pv_pipeline/predictions/distributed_predictions_final_full.pkl \
  --prediction-col power_pred_final \
  --dashboard-root output/pv_pipeline/interactive_dashboard \
  --fail-on-future
```

如果脚本名已更新，可使用最新一致性检查脚本，但必须校验：

1. `actual_mw` 与 pkl 中 `power_mw` 一致。
2. `pred_mw` 与 pkl 中 `power_pred_final` 一致。
3. city 聚合与站点聚合一致。
4. metadata `exclude_future=true`。
5. JSON 不含 future。

输出：

```text
output/pv_pipeline/round74/round74_dashboard_consistency.csv
output/pv_pipeline/round74/round74_dashboard_consistency.json
```

---

## 九、更新 manifest 与 validation

执行：

```bash
python scripts/update_final_manifest_hashes.py
python scripts/posttrain_validation.py
```

要求：

```text
FAIL = 0
```

如果仍有 WARN，需要写入 Round74 报告，但不能有真实 FAIL。

---

## 十、生成 Round74 报告

新建：

```text
docs/Round74_回退最优版本清理残留并刷新可视化报告.md
```

报告必须包含：

1. 当前正式版本是否为 Round68 final。
2. 是否执行了回退。
3. 回退/校验后的核心指标。
4. future 行数是否为 0。
5. 清理了哪些 Round70-Round73 失败实验文件。
6. 是否清理了“🍒”、`__MACOSX`、`.DS_Store`、`._*`、`未命名`、临时文件。
7. 可视化是否重新导出。
8. 可视化是否与 final pkl 一致。
9. posttrain validation 是否通过。
10. 当前是否建议继续模型训练：

```text
不建议在无新增气象/NWP 数据情况下继续残差模型训练。
```

---

## 十一、执行命令汇总

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

mkdir -p output/pv_pipeline/round74

python scripts/verify_current_best_round68.py

# 如果不是 Round68 final，再执行：
# python scripts/promote_round68_candidate.py --apply --exclude-future
# python scripts/verify_current_best_round68.py

python scripts/cleanup_round74_failed_artifacts.py --dry-run
python scripts/cleanup_round74_failed_artifacts.py --apply

python scripts/cleanup_junk_files_round74.py --dry-run
python scripts/cleanup_junk_files_round74.py --apply

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

通过后提交：

```bash
git status

git add scripts/verify_current_best_round68.py
git add scripts/cleanup_round74_failed_artifacts.py
git add scripts/cleanup_junk_files_round74.py
git add scripts/export_interactive_dashboard_data.py
git add scripts/update_final_manifest_hashes.py
git add docs/Round74_回退最优版本清理残留并刷新可视化报告.md
git add output/pv_pipeline/round74/*.csv
git add output/pv_pipeline/round74/*.json
git add output/pv_pipeline/round74/*.txt

git commit -m "chore: restore best round68 final and clean stale artifacts"
git tag -a round68-final-clean-20260601 -m "Clean Round68 final baseline after removing failed experiment artifacts"
git push origin HEAD
git push origin round68-final-clean-20260601
```

不要提交：

```text
*.pkl
*.parquet
*.joblib
archive/failed_experiments_round74/**/*
output/pv_pipeline/interactive_dashboard/**/*.json
```

---

## 十三、验收标准

本轮通过标准：

1. 当前正式版本确认为 Round68 final。
2. final pkl 不含 future。
3. Round70-Round73 失败实验产物已隔离或清理。
4. “🍒”类异常文件、`__MACOSX`、`.DS_Store`、`._*`、`未命名` 文件已清理。
5. 正式可视化重新导出。
6. 可视化数据与 final pkl 一致。
7. manifest 已更新。
8. posttrain validation 无 FAIL。
9. Git tag 已创建，方便恢复。

---

## 十四、执行完成后发回

请发回：

```text
docs/Round74_回退最优版本清理残留并刷新可视化报告.md
output/pv_pipeline/round74/round74_verify_round68_final.json
output/pv_pipeline/round74/round74_cleanup_plan.csv
output/pv_pipeline/round74/round74_junk_cleanup_plan.csv
output/pv_pipeline/round74/round74_dashboard_consistency.json
output/pv_pipeline/manifest.json
```

我会检查：

- 是否真正回到 Round68 final；
- 是否清理干净；
- 可视化是否最新；
- 是否可以把当前代码作为最终稳定版本保存。

