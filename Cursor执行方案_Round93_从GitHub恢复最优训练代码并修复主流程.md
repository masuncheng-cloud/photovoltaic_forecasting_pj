# Cursor执行方案 Round93：从 GitHub 恢复最优训练代码并修复主流程

## 目标

当前 Round92_1 完整重训结果整体不如原来的结果：

- 最新站点平均 NRMSE 变差；
- 最新 10-14 点站点平均 NRMSE 变差；
- 最新主流程虽然产物完整，但 `manifest.json` 写出顺序仍会导致从空 `output/pv_pipeline` 直接运行时报错；
- `archive/` 存在递归归档风险，导致 zip 路径过长。

本轮目标：

1. 从 GitHub 拉取并恢复原来更好的训练代码。
2. 不采用 Round92_1 变差后的训练结果作为正式版本。
3. 保留并修复必要工程问题：
   - 主流程必须包含 `train_inverse_model.py`；
   - `manifest.json` 必须在 `posttrain_validation.py` 前写出；
   - dashboard 必须导出非 future 全历史数据；
   - 清理脚本不能递归归档 `archive/` 自己；
   - README 与正式入口一致。
4. 恢复后执行一次 `eval/dashboard/audit` 验证，不盲目重训。
5. 若确需重训，必须先确认恢复后的代码和原最优指标一致，再执行。

---

## 一、当前结果判断

不要把 Round92_1 当作最优版本。

已知对比：

| 指标 | 原来版本 | Round92_1 最新重训 | 判断 |
|---|---:|---:|---|
| 6-19 点站点平均 NRMSE 均值 | 9.77% | 10.00% | Round92_1 变差 |
| 10-14 点站点平均 NRMSE 均值 | 15.72% | 16.86% | Round92_1 明显变差 |
| 6-19 点城市 NRMSE 均值 | 3.95% | 4.17% | Round92_1 变差 |
| 10-14 点城市 NRMSE 均值 | 6.24% | 6.12% | Round92_1 略好 |
| 站点 NRMSE 均值 | 11.41% | 12.14% | Round92_1 变差 |
| 最大站点 NRMSE | 30.43% | 31.71% | Round92_1 变差 |

结论：

```text
原来版本整体更好；Round92_1 只在 10-14 城市聚合指标上略好，不足以覆盖站点级变差。
```

---

## 二、先备份当前状态

在 Cursor 云服务器项目根目录执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="archive/round93_before_github_restore_${STAMP}"
mkdir -p "$BACKUP_DIR"

cp -a scripts "$BACKUP_DIR/scripts_current"
cp -a stages "$BACKUP_DIR/stages_current"
cp -a configs "$BACKUP_DIR/configs_current"
cp -a output/pv_pipeline "$BACKUP_DIR/output_pv_pipeline_current" 2>/dev/null || true
cp -a README.md "$BACKUP_DIR/README.current.md" 2>/dev/null || true
cp -a CHANGELOG.md "$BACKUP_DIR/CHANGELOG.current.md" 2>/dev/null || true

git status --short > "$BACKUP_DIR/git_status_before_restore.txt" || true

echo "$BACKUP_DIR" > /tmp/round93_backup_dir.txt
echo "Backup saved to: $BACKUP_DIR"
```

如果当前工作区有重要未提交修改，先提交备份分支：

```bash
git checkout -B backup-before-round93-restore
git add .
git commit -m "Backup before Round93 GitHub restore" || true
```

---

## 三、连接并拉取 GitHub

确认远程仓库：

```bash
git remote -v
```

如果没有 origin：

```bash
git remote add origin git@github.com:masuncheng-cloud/photovoltaic_forecasting_pj.git
```

如果 origin 地址不对：

```bash
git remote set-url origin git@github.com:masuncheng-cloud/photovoltaic_forecasting_pj.git
```

拉取所有分支和 tag：

```bash
git fetch origin --prune
git fetch origin --tags
git branch -a
git tag --list | sort
```

---

## 四、选择要恢复的 GitHub 版本

优先级如下：

1. 如果 GitHub 上有明确最优 tag，优先使用：

```text
round61
round61-baseline
round68-final
before-round92-cleanup-retrain
```

2. 如果没有 tag，则使用 GitHub 上 Round92 之前的稳定 commit。

查看候选：

```bash
git log --oneline --decorate --all -30
```

建议先创建恢复分支，不直接覆盖 main：

```bash
git checkout -B round93_restore_best_from_github origin/main
```

如果确认有稳定 tag，例如 `before-round92-cleanup-retrain`：

```bash
git checkout -B round93_restore_best_from_github before-round92-cleanup-retrain
```

如果有 `round68-final` 或 `round61-baseline`，并且它对应原来更好的指标，也可以：

```bash
git checkout -B round93_restore_best_from_github round68-final
```

---

## 五、恢复原来更好的 output

如果 GitHub 仓库不追踪大文件 output，则从本地备份恢复原来更好的结果。

原来更好的结果通常在：

```text
archive/round92_before_cleanup_and_retrain/output_pv_pipeline_backup/
archive/round92_before_full_retrain/output_pv_pipeline_before_full_retrain/
archive/round92_cleanup_removed/20260603_162131/output/pv_pipeline/baselines/round61/
```

优先恢复完整 output：

```bash
rm -rf output/pv_pipeline

if [ -d archive/round92_before_full_retrain/output_pv_pipeline_before_full_retrain ]; then
  cp -a archive/round92_before_full_retrain/output_pv_pipeline_before_full_retrain output/pv_pipeline
elif [ -d archive/round92_before_cleanup_and_retrain/output_pv_pipeline_backup ]; then
  cp -a archive/round92_before_cleanup_and_retrain/output_pv_pipeline_backup output/pv_pipeline
else
  echo "[WARN] 未找到原完整 output 备份，需要从 GitHub LFS 或历史 release 获取 output。"
fi
```

注意：

- 这里恢复的是“原来更好”的正式结果；
- 不恢复 Round92_1 fresh 输出作为正式版本；
- 如果恢复目录里出现 `output/pv_pipeline/pv_pipeline/...` 双层嵌套，要手工整理为单层。

检查：

```bash
find output/pv_pipeline -maxdepth 2 -type f | sort | head -80
```

必须存在：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl
output/pv_pipeline/metrics/hourly_nrmse_consistent.csv
output/pv_pipeline/metrics/site_metrics_consistent.csv
```

---

## 六、只应用必要工程修复

恢复原代码后，不要引入 Round92_1 的模型结果，但要保留以下工程修复。

### 6.1 修复 run_full_pipeline.py 缺少辐照反演

修改：

```text
scripts/run_full_pipeline.py
```

确认 `STEPS` 中 `数据清洗与气象插值` 后、`辐照融合` 前存在：

```python
{
    "id": "3b",
    "name": "辐照反演",
    "script": "stages/02_irradiance/train_inverse_model.py",
    "required": True,
    "timeout": 900,
},
```

并确认 `geo-refresh` 中有：

```python
"steps": ["1", "2", "3", "3b", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13"]
```

### 6.2 修复 manifest 写出顺序

当前问题：

```text
posttrain_validation.py 会检查 manifest.json
但 run_full_pipeline.py 在 posttrain_validation 后才写 manifest
```

必须改为：

```text
Step 11 训练后收口
Step 14 sync canonical
Step 15 write manifest.json
Step 12 posttrain_validation.py
Step 13 check_dashboard_prediction_values.py
```

实现方式：

在 `run_full_pipeline.py` 的 main 执行逻辑中，找到类似：

```python
for step_id in mode_info["steps"]:
    ok = run_step(...)
    ...

if mode_info.get("run_step14", True):
    sync_canonical_paths(cwd)

if mode_info.get("run_step15", True):
    write_manifest(cfg, cwd)
```

改成：

```python
pre_validation_steps = []
post_manifest_steps = []

for sid in mode_info["steps"]:
    if sid in {"12", "13"}:
        post_manifest_steps.append(sid)
    else:
        pre_validation_steps.append(sid)

for step_id in pre_validation_steps:
    step = step_by_id[step_id]
    ok = run_step(step, python, cwd, cfg, cache)
    if not ok:
        write_timing_logs(out_dir, mode)
        sys.exit(1)

if mode_info.get("run_step14", True):
    with timed_step("[14] 同步正式产物文件名"):
        sync_canonical_paths(cwd)

if mode_info.get("run_step15", True):
    with timed_step("[15] 写出 manifest.json"):
        write_manifest(cfg, cwd)

for step_id in post_manifest_steps:
    step = step_by_id[step_id]
    ok = run_step(step, python, cwd, cfg, cache)
    if not ok:
        write_timing_logs(out_dir, mode)
        sys.exit(1)
```

如果当前代码结构不同，原则不变：

```text
manifest 必须在 posttrain_validation.py 之前写出。
```

### 6.3 修复清理脚本递归归档 archive

修改：

```text
scripts/cleanup_round92_redundant_artifacts.py
```

要求：

- 永远不要遍历或移动 `archive/` 自己；
- 永远不要把 `archive/round92_cleanup_removed/...` 再次移动进它自己；
- 不要移动 `.git/`、`data/`、`output/pv_pipeline` 当前正式产物。

在所有 `rglob` 遍历前加入过滤：

```python
def is_under_archive(path: Path) -> bool:
    try:
        rel = path.resolve().relative_to((ROOT / "archive").resolve())
        return True
    except ValueError:
        return False
```

移动前：

```python
if is_under_archive(path):
    return
```

并且不要再执行类似：

```python
for p in ROOT.rglob(...)
```

去处理 archive 内部文件。

### 6.4 保留 dashboard 全历史非 future 导出

确认：

```text
scripts/export_interactive_dashboard_data.py
```

必须满足：

- 读取 `distributed_predictions_final_full.pkl`
- 使用 `power_pred_final`
- 排除 `split == future`
- 导出 `dashboard_data_scope = non_future_full_history`
- 写出 `full_history_coverage_check.json`

执行检查：

```bash
grep -n "non_future_full_history\\|full_history_coverage_check\\|power_pred_final\\|future" scripts/export_interactive_dashboard_data.py
```

---

## 七、验证恢复后的结果是否为原来更好版本

执行：

```bash
python - <<'PY'
import pandas as pd
from pathlib import Path

base = Path("output/pv_pipeline/metrics")
hour = pd.read_csv(base / "hourly_nrmse_consistent.csv", encoding="utf-8-sig")
site = pd.read_csv(base / "site_metrics_consistent.csv", encoding="utf-8-sig")

noon = hour[hour["hour"].between(10, 14)]

print("6-19站点平均NRMSE均值:", hour["site_avg_nrmse_pct"].mean())
print("10-14站点平均NRMSE均值:", noon["site_avg_nrmse_pct"].mean())
print("6-19城市NRMSE均值:", hour["city_nrmse_pct"].mean())
print("10-14城市NRMSE均值:", noon["city_nrmse_pct"].mean())
print("站点NRMSE均值:", site["nrmse_pct"].mean())
print("站点NRMSE中位数:", site["nrmse_pct"].median())
print("最大站点NRMSE:", site["nrmse_pct"].max())
PY
```

期望接近原来版本：

```text
6-19站点平均NRMSE均值 ≈ 9.77%
10-14站点平均NRMSE均值 ≈ 15.72%
6-19城市NRMSE均值 ≈ 3.95%
10-14城市NRMSE均值 ≈ 6.24%
站点NRMSE均值 ≈ 11.41%
最大站点NRMSE ≈ 30.43%
```

如果输出接近 Round92_1：

```text
站点NRMSE均值 ≈ 12.14%
10-14站点平均NRMSE ≈ 16.86%
```

说明仍然是变差后的结果，没有恢复成功。

---

## 八、执行非重训验证

恢复代码和原结果后，先不要完整重训，先执行：

```bash
python scripts/run_full_pipeline.py --mode eval-only --force 2>&1 | tee output/pv_pipeline/logs/round93_eval_only.log
python scripts/run_full_pipeline.py --mode dashboard-only --force 2>&1 | tee output/pv_pipeline/logs/round93_dashboard_only.log
python scripts/run_full_pipeline.py --mode audit-only --force 2>&1 | tee output/pv_pipeline/logs/round93_audit_only.log
```

要求：

- 不报 `manifest.json 不存在`；
- 不报 `inverse_predictions.pkl 不存在`；
- dashboard 能导出；
- validation PASS 或只有可解释 WARN。

如果 audit-only 仍因 manifest 顺序失败，说明第 6.2 没修好。

---

## 九、检查能否从空 output 直接跑通

不要马上覆盖当前原最优结果。

使用临时目录模拟空 output：

```bash
mkdir -p archive/round93_verify_direct_run
cp -a output/pv_pipeline archive/round93_verify_direct_run/output_best_before_direct_run
rm -rf output/pv_pipeline
mkdir -p output/pv_pipeline/logs
```

执行完整流程：

```bash
python scripts/run_full_pipeline.py --mode full --force 2>&1 | tee output/pv_pipeline/logs/round93_direct_full_run.log
```

如果完整跑通：

```bash
python scripts/check_pipeline_consistency.py
python scripts/posttrain_validation.py
python scripts/check_dashboard_prediction_values.py
python scripts/check_no_future_in_outputs.py
```

如果完整重训结果又比原最优差，不采用新结果，恢复原最优 output：

```bash
rm -rf output/pv_pipeline
cp -a archive/round93_verify_direct_run/output_best_before_direct_run output/pv_pipeline
```

注意：

```text
这一步的目的只是验证“能否从空 output 直接跑通”，不是强制采用重训结果。
```

---

## 十、可视化启动验证

```bash
python -m http.server 8070
```

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round93
```

验证：

- 全市折线图有数据；
- 单站点折线图有数据；
- `metadata.json` 显示 `include_future=false`；
- 日期覆盖 `2023-01-01 ~ 2025-12-31`；
- 春季可点击；
- `典型日期` 和 `四季最佳日` 不改写日期选择框；
- 样本数/全量样本数口径正确。

---

## 十一、生成 Round93 报告

新建：

```text
docs/Round93_从GitHub恢复最优训练代码并修复主流程报告.md
```

写入：

```markdown
# Round93 从 GitHub 恢复最优训练代码并修复主流程报告

## 1. 恢复原因

Round92_1 完整重训后，站点级和整体指标较原版本变差，因此恢复 GitHub 上原最优训练代码与原最优输出。

## 2. 恢复来源

- GitHub 仓库：
- 分支/tag/commit：
- 是否恢复原 output：

## 3. 保留的工程修复

- run_full_pipeline.py 已补充辐照反演步骤。
- manifest.json 已改为在 posttrain_validation.py 前写出。
- dashboard 导出保持非 future 全历史。
- 清理脚本避免递归归档 archive。

## 4. 指标对比

| 指标 | 原最优 | Round92_1 | 当前恢复后 |
|---|---:|---:|---:|
| 6-19站点平均NRMSE均值 | | | |
| 10-14站点平均NRMSE均值 | | | |
| 6-19城市NRMSE均值 | | | |
| 10-14城市NRMSE均值 | | | |
| 站点NRMSE均值 | | | |
| 最大站点NRMSE | | | |

## 5. 启动与验证

- eval-only：
- dashboard-only：
- audit-only：
- 空 output full run 验证：
- dashboard 页面验证：

## 6. 结论

当前版本恢复到原来更优的训练结果，同时保留必要工程修复。后续模型优化必须以当前恢复版本为基线，任何新结果若整体指标差于基线，应自动回退。
```

---

## 十二、提交 GitHub

如果验证通过：

```bash
git status --short
git add .
git commit -m "Round93: restore best GitHub baseline and fix pipeline execution order"
git tag -a round93-restore-best-baseline -m "Restore best baseline from GitHub, fix inverse step and manifest order"
git push origin HEAD
git push origin round93-restore-best-baseline
```

---

## 十三、注意事项

1. 不要采用 Round92_1 作为正式最优结果。
2. 不要把完整重训得到的差结果覆盖原最优 output。
3. 不要从旧 output 手工复制单个中间文件补流程。
4. 恢复代码后，只允许保留工程修复，不要混入 Round92_1 的模型结果。
5. 清理脚本不能再归档 `archive/` 自己。
6. 后续任何模型改动都必须先和当前恢复基线对比，差则回退。
