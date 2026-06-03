# Cursor执行方案 Round92：项目完整性审计、冗余清理、完整重训与可视化更新

## 目标

本轮目标不是继续小修可视化，而是做一次完整工程收口：

1. 确认项目结构是否完整。
2. 确认正式训练逻辑、预测逻辑、评估逻辑是否仍使用最新主流程。
3. 清除多轮修改产生的冗余代码、历史 round 文件、缓存文件、过期输出文件。
4. 重新完整执行一遍正式训练主流程。
5. 训练后自动更新可视化页面数据。
6. 验证可视化数据来自最新训练结果，并且导出所有非 future 的全历史数据。

本轮命名：

```text
Round92
```

---

## 一、当前判断

根据当前项目包，正式主入口应为：

```bash
python scripts/run_full_pipeline.py --mode full --force
```

正式训练链路应包含：

```text
Stage 01 数据准备
Stage 02 辐照反演 / 辐照融合
Stage 03 分布式功率预测
Stage 04 评估与最终预测文件收口
Dashboard 可视化数据导出
Posttrain 验证
Dashboard 预测值一致性验证
Manifest 写出
```

正式最终预测列：

```text
power_pred_final
```

正式最终预测文件：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl
```

正式可视化目录：

```text
output/pv_pipeline/interactive_dashboard/
```

需要特别避免：

- 直接运行 `train_roundXX_*.py` 作为主流程；
- 直接运行旧的 `apply_roundXX_*.py` 替代正式预测逻辑；
- 使用 `power_pred_cal`、`power_pred_raw`、`pred_mw` 等旧列作为最终预测列；
- 可视化导出包含 future；
- 可视化只导出测试期或局部窗口，导致春季等历史数据缺失。

---

## 二、执行前备份

在 Cursor 服务器项目根目录执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

mkdir -p archive/round92_before_cleanup_and_retrain

cp -a scripts archive/round92_before_cleanup_and_retrain/scripts_backup
cp -a stages archive/round92_before_cleanup_and_retrain/stages_backup
cp -a configs archive/round92_before_cleanup_and_retrain/configs_backup
cp -a output/pv_pipeline archive/round92_before_cleanup_and_retrain/output_pv_pipeline_backup
cp -a README.md archive/round92_before_cleanup_and_retrain/README.before_round92.md
cp -a CHANGELOG.md archive/round92_before_cleanup_and_retrain/CHANGELOG.before_round92.md

git status --short > archive/round92_before_cleanup_and_retrain/git_status_before_round92.txt || true
```

如果项目已连接 GitHub，先提交或打 tag：

```bash
git add .
git commit -m "backup before round92 cleanup and full retrain" || true
git tag -a before-round92-cleanup-retrain -m "Backup before Round92 cleanup and full retrain" || true
```

---

## 三、创建项目完整性审计脚本

新建：

```text
scripts/audit_round92_project_integrity.py
```

写入：

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pv_pipeline"


REQUIRED_FILES = [
    "README.md",
    "requirements.txt",
    "configs/pipeline.yaml",
    "scripts/run_full_pipeline.py",
    "scripts/common_paths.py",
    "scripts/metrics_common.py",
    "scripts/post_training_finalize_outputs.py",
    "scripts/posttrain_validation.py",
    "scripts/check_pipeline_consistency.py",
    "scripts/check_dashboard_prediction_values.py",
    "scripts/check_no_future_in_outputs.py",
    "scripts/export_interactive_dashboard_data.py",
    "stages/01_data/build_site_master.py",
    "stages/01_data/prepare_meteo_and_power.py",
    "stages/02_irradiance/train_inverse_model.py",
    "stages/02_irradiance/train_irradiance_blend.py",
    "stages/03_power/train_distributed_model_v159.py",
    "stages/04_evaluation/evaluate_layers.py",
    "stages/05_visualization/interactive_forecast_dashboard.html",
]

REQUIRED_OUTPUTS_AFTER_TRAIN = [
    "predictions/distributed_predictions_final_full.pkl",
    "predictions/distributed_predictions_final_eval.pkl",
    "metrics/hourly_nrmse_consistent.csv",
    "metrics/site_metrics_consistent.csv",
    "interactive_dashboard/index.json",
    "interactive_dashboard/metadata.json",
    "interactive_dashboard/city_series.json",
    "interactive_dashboard/full_history_coverage_check.json",
    "manifest.json",
]

FORBIDDEN_MAIN_REFERENCES = [
    "train_round63",
    "train_round64",
    "train_round67",
    "train_round70",
    "train_round71",
    "train_round72",
    "train_round73",
    "apply_round59",
    "apply_round60",
    "select_round64",
    "select_round71",
]


def exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def main():
    report = {
        "status": "PASS",
        "missing_required_files": [],
        "missing_outputs_after_train": [],
        "main_entry": "scripts/run_full_pipeline.py",
        "final_prediction_column_expected": "power_pred_final",
        "forbidden_main_references": [],
        "notes": [],
    }

    for rel in REQUIRED_FILES:
        if not exists(rel):
            report["missing_required_files"].append(rel)

    if report["missing_required_files"]:
        report["status"] = "FAIL"

    run_full = ROOT / "scripts" / "run_full_pipeline.py"
    run_text = read_text(run_full)
    for bad in FORBIDDEN_MAIN_REFERENCES:
        if bad in run_text:
            report["forbidden_main_references"].append(bad)

    # 允许 run_full_pipeline.py 在注释中提到 round36，因为当前正式链路仍可能沿用 round36 文件名；
    # 但不允许引用已失败或实验性质的 round63-73。
    if report["forbidden_main_references"]:
        report["status"] = "WARN"

    if OUT.exists():
        for rel in REQUIRED_OUTPUTS_AFTER_TRAIN:
            if not (OUT / rel).exists():
                report["missing_outputs_after_train"].append(rel)
    else:
        report["notes"].append("output/pv_pipeline does not exist yet; this is acceptable before full retrain.")

    scripts = sorted(p.name for p in (ROOT / "scripts").glob("*.py"))
    report["script_count"] = len(scripts)
    report["round_script_count"] = len([s for s in scripts if "round" in s.lower()])
    report["round_scripts"] = [s for s in scripts if "round" in s.lower()]

    out_path = OUT / "validation" / "round92_project_integrity_audit.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
```

执行：

```bash
python scripts/audit_round92_project_integrity.py
```

如果 `missing_required_files` 非空，先补齐缺失文件，不要继续清理。

---

## 四、确认正式训练和预测逻辑是否最新

执行以下检查：

```bash
python - <<'PY'
from pathlib import Path

root = Path(".")
run = root / "scripts/run_full_pipeline.py"
text = run.read_text(encoding="utf-8", errors="ignore")

required = [
    "stages/01_data/build_site_master.py",
    "stages/01_data/prepare_meteo_and_power.py",
    "stages/02_irradiance/train_irradiance_blend.py",
    "stages/03_power/train_distributed_model_v159.py",
    "scripts/post_training_finalize_outputs.py",
    "scripts/posttrain_validation.py",
    "scripts/check_dashboard_prediction_values.py",
]

print("正式入口:", run)
for item in required:
    print(("[OK]" if item in text else "[MISS]"), item)

print("\n检查最终预测列:")
for path in [
    "scripts/post_training_finalize_outputs.py",
    "scripts/export_interactive_dashboard_data.py",
    "scripts/check_dashboard_prediction_values.py",
]:
    p = root / path
    t = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""
    print(path, "power_pred_final=", "power_pred_final" in t)
PY
```

判断标准：

- `run_full_pipeline.py` 必须是唯一正式训练入口。
- 预测最终列必须是 `power_pred_final`。
- Dashboard 导出脚本必须优先读取 `distributed_predictions_final_full.pkl`。
- Dashboard 导出必须排除 future。
- Dashboard 导出必须基于所有非 future 全历史数据，而不是只用 test。

如果发现 `export_interactive_dashboard_data.py` 仍只导出测试期，按 Round91_2 方案修复后再继续。

---

## 五、清理冗余代码和文件

### 5.1 原则

不要直接删除重要文件，先移动到：

```text
archive/round92_cleanup_removed/
```

以下可以清理：

- `__MACOSX/`
- `.DS_Store`
- `__pycache__/`
- `*.pyc`
- 根目录乱码 `Cursor...RoundXX...md` 临时方案文件
- output 下旧 round 目录
- output 下 backups、archive_before_round36、interactive_dashboard_round64_candidate 等旧产物
- scripts 下失败实验和历史 round 临时脚本，但必须保留正式主流程依赖的脚本

### 5.2 创建清理脚本

新建：

```text
scripts/cleanup_round92_redundant_artifacts.py
```

写入：

```python
#!/usr/bin/env python3
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
ARCHIVE = ROOT / "archive" / "round92_cleanup_removed" / STAMP


KEEP_SCRIPTS = {
    "__init__.py",
    "run_full_pipeline.py",
    "common_paths.py",
    "metrics_common.py",
    "pipeline_cache.py",
    "check_pipeline_consistency.py",
    "audit_round92_project_integrity.py",
    "cleanup_round92_redundant_artifacts.py",
    "post_training_finalize_outputs.py",
    "posttrain_validation.py",
    "check_post_training_auto_finalize.py",
    "check_dashboard_prediction_values.py",
    "check_dashboard_actual_values.py",
    "check_dashboard_auto_update_stamp.py",
    "check_dashboard_data_freshness.py",
    "check_no_future_in_outputs.py",
    "export_interactive_dashboard_data.py",
    "update_dashboard_after_training.py",
    "pretrain_audit_round36.py",
    "build_round36_predictions.py",
    "build_site_validity_round36.py",
    "apply_round36_calibration.py",
    "compute_round36_metrics.py",
    "select_final_prediction_by_guard.py",
    "generate_site_parameters.py",
    "apply_manual_geo_overrides.py",
    "apply_site_metadata_overrides.py",
    "audit_training_pipeline_flow.py",
    "audit_training_process_and_results.py",
    "audit_prediction_column_consistency.py",
    "audit_edge_hour_zero_predictions.py",
}

KEEP_OUTPUT_DIRS = {
    "predictions",
    "metrics",
    "models",
    "tables",
    "interactive_dashboard",
    "logs",
    "docs",
    "validation",
    "figures",
}


def move_to_archive(path: Path):
    if not path.exists():
        return
    rel = path.relative_to(ROOT)
    dst = ARCHIVE / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dst))
    print(f"[MOVED] {rel} -> {dst.relative_to(ROOT)}")


def remove_junk():
    for p in ROOT.rglob(".DS_Store"):
        move_to_archive(p)
    for p in ROOT.rglob("__pycache__"):
        move_to_archive(p)
    for p in ROOT.rglob("*.pyc"):
        move_to_archive(p)

    mac = ROOT / "__MACOSX"
    if mac.exists():
        move_to_archive(mac)


def archive_round_scripts():
    scripts = ROOT / "scripts"
    for p in scripts.glob("*.py"):
        name = p.name
        lower = name.lower()
        if name in KEEP_SCRIPTS:
            continue
        if "round" in lower or "compare_round" in lower or "candidate" in lower or "diagnose" in lower:
            move_to_archive(p)


def archive_output_round_dirs():
    out = ROOT / "output" / "pv_pipeline"
    if not out.exists():
        return

    for p in list(out.iterdir()):
        if not p.is_dir():
            continue
        name = p.name.lower()
        if p.name in KEEP_OUTPUT_DIRS:
            continue
        if (
            name.startswith("round")
            or name.startswith("archive")
            or name.startswith("backup")
            or name in {"backups", "baselines", "cache", "diagnostics", "calibration"}
            or "candidate" in name
        ):
            move_to_archive(p)


def archive_root_cursor_md():
    for p in ROOT.glob("Cursor*.md"):
        move_to_archive(p)


def main():
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    remove_junk()
    archive_round_scripts()
    archive_output_round_dirs()
    archive_root_cursor_md()
    print(f"[OK] cleanup archive: {ARCHIVE}")


if __name__ == "__main__":
    main()
```

先 dry-run 检查脚本内容后再执行：

```bash
python scripts/cleanup_round92_redundant_artifacts.py
```

清理后再次执行：

```bash
python scripts/audit_round92_project_integrity.py
```

如果审计失败，立刻从 `archive/round92_before_cleanup_and_retrain` 回退。

---

## 六、清理 output 并准备完整重训

为了保证完整重训结果干净，先归档当前 `output/pv_pipeline`，再保留必要目录结构。

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

mkdir -p archive/round92_before_full_retrain
cp -a output/pv_pipeline archive/round92_before_full_retrain/output_pv_pipeline_before_full_retrain

rm -rf output/pv_pipeline
mkdir -p output/pv_pipeline
```

注意：

- 这一步会清空当前输出，但已有备份。
- 不删除 `data/`、`configs/`、`stages/`、`scripts/`。

---

## 七、完整执行正式训练主流程

正式执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/run_full_pipeline.py --mode full --force 2>&1 | tee output/pv_pipeline/logs/round92_full_retrain.log
```

如果 `logs` 目录不存在，先创建：

```bash
mkdir -p output/pv_pipeline/logs
```

训练期间不要手动运行旧 round 脚本。

如果训练中断：

1. 查看最后报错：

```bash
tail -120 output/pv_pipeline/logs/round92_full_retrain.log
```

2. 不要跳过失败阶段继续导出 dashboard。
3. 先修复失败阶段，再重新运行：

```bash
python scripts/run_full_pipeline.py --mode full --force
```

---

## 八、训练后强制更新可视化数据

完整训练结束后，再单独执行一次 dashboard 更新，确保使用最新预测文件：

```bash
python scripts/run_full_pipeline.py --mode dashboard-only --force 2>&1 | tee output/pv_pipeline/logs/round92_dashboard_update.log
```

再执行：

```bash
python scripts/export_interactive_dashboard_data.py 2>&1 | tee -a output/pv_pipeline/logs/round92_dashboard_update.log
```

要求：

- 导出所有非 future 全历史数据；
- `metadata.json` 更新时间必须晚于本次训练开始时间；
- `full_history_coverage_check.json` 必须存在。

---

## 九、训练后验证

执行：

```bash
python scripts/check_pipeline_consistency.py
python scripts/posttrain_validation.py
python scripts/check_dashboard_prediction_values.py
python scripts/check_no_future_in_outputs.py
python scripts/audit_round92_project_integrity.py
```

如果项目里有这些脚本，也执行：

```bash
python scripts/check_dashboard_data_freshness.py
python scripts/check_dashboard_auto_update_stamp.py
python scripts/check_post_training_auto_finalize.py
python scripts/audit_prediction_column_consistency.py
```

要求：

- 所有正式检查必须 PASS。
- 如果脚本不存在，不要从历史 archive 里恢复，记录为“当前版本未提供该检查脚本”。

---

## 十、验证最终预测文件

执行：

```bash
python - <<'PY'
import pandas as pd
from pathlib import Path

base = Path("output/pv_pipeline/predictions")
full = base / "distributed_predictions_final_full.pkl"
evalp = base / "distributed_predictions_final_eval.pkl"

for p in [full, evalp]:
    print("\n==", p)
    assert p.exists(), f"missing {p}"
    df = pd.read_pickle(p)
    print("shape:", df.shape)
    print("columns:", list(df.columns)[:30])
    assert "power_pred_final" in df.columns, "missing power_pred_final"
    if "split" in df.columns:
        print(df["split"].value_counts(dropna=False))
    if "datetime" in df.columns:
        dt = pd.to_datetime(df["datetime"])
        print("date range:", dt.min(), dt.max())

df = pd.read_pickle(full)
if "split" in df.columns:
    non_future = df[df["split"].astype(str).str.lower() != "future"]
    print("\nnon_future rows:", len(non_future))
    print("future rows:", (df["split"].astype(str).str.lower() == "future").sum())
PY
```

要求：

- `distributed_predictions_final_full.pkl` 可读；
- `distributed_predictions_final_eval.pkl` 可读；
- 两者都有 `power_pred_final`；
- eval 文件应为 test 6-19 评估口径；
- dashboard 不包含 future。

---

## 十一、验证可视化导出是否为非 future 全历史

执行：

```bash
cat output/pv_pipeline/interactive_dashboard/full_history_coverage_check.json
cat output/pv_pipeline/interactive_dashboard/metadata.json | head -120
```

再执行：

```bash
python - <<'PY'
import json
from pathlib import Path

base = Path("output/pv_pipeline/interactive_dashboard")
city = json.loads((base / "city_series.json").read_text(encoding="utf-8"))
dates = sorted({str(r.get("date") or r.get("datetime") or r.get("time", ""))[:10] for r in city if r})

print("city rows:", len(city))
print("min date:", dates[0] if dates else None)
print("max date:", dates[-1] if dates else None)

for season, months in {
    "spring": {"03", "04", "05"},
    "summer": {"06", "07", "08"},
    "autumn": {"09", "10", "11"},
    "winter": {"12", "01", "02"},
}.items():
    cnt = sum(1 for d in dates if d[5:7] in months)
    print(season, cnt)

assert city, "city_series empty"
assert not any(str(r.get("split", "")).lower() == "future" for r in city), "future found in city_series"
PY
```

判断：

- 如果 `spring > 0`，页面春季按钮应可用；
- 如果 `spring = 0`，说明预测结果本身没有春季数据，春季按钮灰掉是合理的；
- 页面日期默认范围应等于 metadata 的真实 min/max。

---

## 十二、更新可视化页面并启动

启动：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
python -m http.server 8070
```

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round92
```

强制刷新：

```text
Ctrl + Shift + R
```

Safari：

```text
Option + Command + R
```

页面验收：

- 不显示旧版本红色警告。
- 数据版本时间为本次训练后时间。
- 日期默认范围和 `metadata.json` 一致。
- 全市折线图有数据。
- 单站点折线图有数据。
- `典型日期` 按钮可切换图表但不改写日期框。
- 四季按钮按真实数据范围可用/不可用。
- 若导出数据含 3-5 月，春季必须可点击。
- `样本数` 为当前窗口样本数。
- `全量样本数` 为当前展示对象全历史样本数。
- 不显示 RMSE 指标卡。

---

## 十三、生成 Round92 执行报告

新建：

```text
docs/Round92_项目完整性审计清理完整重训与可视化更新报告.md
```

写入以下内容：

```markdown
# Round92 项目完整性审计、冗余清理、完整重训与可视化更新报告

## 1. 执行目标

- 检查项目结构完整性。
- 确认正式训练入口和最终预测逻辑。
- 清理历史 round 残留、缓存和过期输出。
- 完整重训。
- 更新可视化页面数据。
- 验证 dashboard 使用最新非 future 全历史数据。

## 2. 项目结构审计

- 正式训练入口：
- 缺失文件：
- round 临时脚本数量：
- 是否存在禁止主流程引用的实验脚本：
- 审计结论：

## 3. 清理内容

- 移入 archive 的脚本：
- 移入 archive 的 output 旧目录：
- 删除/归档的缓存：
- 保留的正式目录：

## 4. 完整训练结果

- 训练命令：
- 开始时间：
- 结束时间：
- 总耗时：
- 是否全部 PASS：
- 失败/告警：

## 5. 最终预测文件

- distributed_predictions_final_full.pkl 行数：
- distributed_predictions_final_eval.pkl 行数：
- 最终预测列：
- split 分布：
- 是否包含 future：

## 6. 评估结果

- 全局 NRMSE：
- 城市 NRMSE：
- 站点平均 NRMSE：
- 逐小时结果文件：
- 高误差站点：

## 7. 可视化更新

- dashboard metadata 时间：
- dashboard min_date：
- dashboard max_date：
- include_future：
- has_2025_spring：
- spring_2025_rows：
- city_series 行数：
- site_series 站点数：

## 8. 验证结果

- check_pipeline_consistency：
- posttrain_validation：
- check_dashboard_prediction_values：
- check_no_future_in_outputs：
- audit_round92_project_integrity：

## 9. 结论

本轮完成项目结构收口、冗余清理、完整重训和可视化更新。后续模型性能提升应基于当前主流程继续，不再从历史 round 临时脚本分叉。
```

---

## 十四、Git 保存

如果所有检查通过：

```bash
git status --short
git add .
git commit -m "Round92: cleanup project, full retrain, refresh dashboard"
git tag -a round92-clean-full-retrain -m "Round92 clean project, full retrain, dashboard refreshed"
git push
git push --tags
```

如果检查未通过，不要提交最终 tag，只提交问题报告或先修复。

---

## 十五、失败回退

如果清理后项目无法运行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

rm -rf scripts stages configs output/pv_pipeline
cp -a archive/round92_before_cleanup_and_retrain/scripts_backup scripts
cp -a archive/round92_before_cleanup_and_retrain/stages_backup stages
cp -a archive/round92_before_cleanup_and_retrain/configs_backup configs
cp -a archive/round92_before_cleanup_and_retrain/output_pv_pipeline_backup output/pv_pipeline
```

如果 Git tag 已创建，也可以：

```bash
git checkout before-round92-cleanup-retrain
```

---

## 十六、注意事项

1. 本轮完整训练必须走 `scripts/run_full_pipeline.py`，不要直接跑历史 round 脚本。
2. 清理时先归档，不要直接永久删除。
3. 不要删除 `data/`。
4. 不要删除 `configs/manual_station_geo_overrides.csv` 和站点经纬度覆盖文件。
5. 不要把 future 导入 dashboard。
6. 可视化折线图可以使用非 future 全历史数据，评估指标仍保持 test 6-19 口径。
7. 如果训练耗时过长，先记录耗时 Top5，不要跳过正式验证。
8. 如果春季按钮仍不可用，先查看 `full_history_coverage_check.json`，确认导出数据是否真实包含 3-5 月。
