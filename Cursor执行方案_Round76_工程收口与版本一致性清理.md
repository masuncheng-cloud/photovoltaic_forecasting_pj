# Cursor执行方案 Round76：工程收口与版本一致性清理

## 目标

本轮不重新训练、不调整模型结构，重点解决多轮修改后留下的工程混乱问题，确保当前最优结果、训练入口、manifest、README、可视化数据和交付目录口径一致。

本轮完成后应达到：

- 当前正式版本明确为 `Round68 final`。
- 正式预测列统一为 `power_pred_final`。
- 正式预测文件统一使用 `output/pv_pipeline/predictions/distributed_predictions_final_full.pkl` 和 `distributed_predictions_final_eval.pkl`。
- 可视化数据默认不包含 `future`。
- `README.md`、`manifest.json`、可视化 `metadata.json`、验证脚本使用同一套口径。
- 历史 round 脚本和临时文件归档，不再干扰正式主流程。

---

## 一、执行前保护

请先在项目根目录执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
git status --short
mkdir -p archive/round76_engineering_cleanup
cp -a README.md archive/round76_engineering_cleanup/README.before_round76.md
cp -a output/pv_pipeline/manifest.json archive/round76_engineering_cleanup/manifest.before_round76.json
cp -a output/pv_pipeline/interactive_dashboard/metadata.json archive/round76_engineering_cleanup/dashboard_metadata.before_round76.json
```

如果 `git status --short` 显示大量未提交模型结果，不要直接删除，先继续执行归档步骤。

---

## 二、修正 manifest 版本口径

### 2.1 编写修复脚本

新建脚本：

`scripts/fix_round76_manifest_consistency.py`

内容如下：

```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "output" / "pv_pipeline"
MANIFEST = PIPELINE / "manifest.json"

FINAL_FULL = PIPELINE / "predictions" / "distributed_predictions_final_full.pkl"
FINAL_EVAL = PIPELINE / "predictions" / "distributed_predictions_final_eval.pkl"
DASHBOARD_META = PIPELINE / "interactive_dashboard" / "metadata.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    if not MANIFEST.exists():
        raise FileNotFoundError(MANIFEST)
    if not FINAL_FULL.exists():
        raise FileNotFoundError(FINAL_FULL)
    if not FINAL_EVAL.exists():
        raise FileNotFoundError(FINAL_EVAL)
    if not DASHBOARD_META.exists():
        raise FileNotFoundError(DASHBOARD_META)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dashboard_meta = json.loads(DASHBOARD_META.read_text(encoding="utf-8"))

    manifest["final_round"] = "Round68 final"
    manifest["source_round"] = manifest.get("source_round") or "Round68 lgb_safe_blend"
    manifest["prediction_column"] = "power_pred_final"
    manifest["actual_column"] = "power_mw"
    manifest["exclude_future"] = True
    manifest["official_final"] = True

    manifest["final_prediction_files"] = {
        "full": str(FINAL_FULL.relative_to(ROOT)),
        "eval": str(FINAL_EVAL.relative_to(ROOT)),
    }

    manifest["dashboard"] = {
        "path": "stages/05_visualization/interactive_forecast_dashboard.html",
        "data_root": "output/pv_pipeline/interactive_dashboard",
        "metadata": "output/pv_pipeline/interactive_dashboard/metadata.json",
        "exclude_future": True,
        "round": dashboard_meta.get("round", "Round68 final"),
        "prediction_column": dashboard_meta.get("prediction_column", "power_pred_final"),
    }

    manifest["artifact_hashes"] = {
        "final_full_pkl": sha256_file(FINAL_FULL),
        "final_eval_pkl": sha256_file(FINAL_EVAL),
        "dashboard_metadata_json": sha256_file(DASHBOARD_META),
    }
    manifest["full_sha256"] = manifest["artifact_hashes"]["final_full_pkl"]
    manifest["eval_sha256"] = manifest["artifact_hashes"]["final_eval_pkl"]

    # 历史 round 指标不再放入正式 manifest，避免把临时实验误认为交付物。
    for key in [
        "round36",
        "round39",
        "round46",
        "round58",
        "round59",
        "round60",
        "round61",
        "round63",
        "round64",
        "round67",
        "round68",
        "round69",
        "round70",
        "round71",
        "round72",
        "round73",
    ]:
        manifest.pop(f"{key}_hashes", None)

    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("[OK] manifest fixed:", MANIFEST)
    print("[OK] final_round =", manifest["final_round"])
    print("[OK] final_full sha256 =", manifest["artifact_hashes"]["final_full_pkl"])


if __name__ == "__main__":
    main()
```

执行：

```bash
python scripts/fix_round76_manifest_consistency.py
```

验收：

```bash
python - <<'PY'
import json
from pathlib import Path
m = json.loads(Path("output/pv_pipeline/manifest.json").read_text(encoding="utf-8"))
assert m["final_round"] == "Round68 final"
assert m["prediction_column"] == "power_pred_final"
assert m["exclude_future"] is True
assert m["artifact_hashes"]["final_full_pkl"] == m["full_sha256"]
print("[OK] manifest version/hash consistency passed")
PY
```

---

## 三、修正 README 中旧路径和旧口径

请修改 `README.md`，重点替换以下旧内容：

### 3.1 删除或替换旧 Round36 文件路径

把类似内容：

```text
output/pv_pipeline/tables/distributed_predictions_final_round36.pkl
```

统一改为：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl
```

### 3.2 修正 future 描述

如果 README 中写到“最终预测文件包含 train/valid/test/future”，请改为：

```text
当前正式预测结果默认不包含 future。正式评估与可视化仅使用 train、valid、test 中的有效样本；
test 集评估范围为 2025-09-01 至 2025-12-31，小时范围为 6-19 点。
```

### 3.3 明确唯一正式入口

保留：

```bash
python scripts/run_full_pipeline.py
python scripts/posttrain_validation.py
python scripts/check_dashboard_prediction_values.py
```

并补充说明：

```text
run_full_pipeline.py 是正式主入口；历史 round 脚本只作为归档和审计材料，不作为正式训练入口。
```

---

## 四、归档历史 round 脚本

### 4.1 先生成待归档清单

执行：

```bash
python - <<'PY'
from pathlib import Path
scripts = Path("scripts")
patterns = [
    "*round63*",
    "*round64*",
    "*round67*",
    "*round68*",
    "*round69*",
    "*round70*",
    "*round71*",
    "*round72*",
    "*round73*",
]
files = []
for p in patterns:
    files.extend(scripts.glob(p))
files = sorted(set(f for f in files if f.is_file()))
out = Path("archive/round76_engineering_cleanup/round_scripts_to_archive.txt")
out.write_text("\n".join(str(f) for f in files), encoding="utf-8")
print(f"[INFO] scripts to archive: {len(files)}")
for f in files:
    print(f)
PY
```

人工检查 `archive/round76_engineering_cleanup/round_scripts_to_archive.txt`，确认里面没有以下正式脚本：

- `scripts/run_full_pipeline.py`
- `scripts/posttrain_validation.py`
- `scripts/check_dashboard_prediction_values.py`
- `scripts/export_interactive_dashboard_data.py`
- `scripts/regenerate_chinese_metrics.py`
- `scripts/check_pipeline_consistency.py`

### 4.2 归档历史脚本

确认无误后执行：

```bash
mkdir -p archive/experimental_scripts
python - <<'PY'
from pathlib import Path
import shutil

root = Path(".")
archive = root / "archive" / "experimental_scripts"
list_file = root / "archive" / "round76_engineering_cleanup" / "round_scripts_to_archive.txt"

keep = {
    "scripts/run_full_pipeline.py",
    "scripts/posttrain_validation.py",
    "scripts/check_dashboard_prediction_values.py",
    "scripts/export_interactive_dashboard_data.py",
    "scripts/regenerate_chinese_metrics.py",
    "scripts/check_pipeline_consistency.py",
}

for line in list_file.read_text(encoding="utf-8").splitlines():
    src = Path(line)
    if not src.exists():
        continue
    if str(src) in keep:
        raise RuntimeError(f"refuse to archive formal script: {src}")
    dst = archive / src.name
    if dst.exists():
        dst = archive / f"{src.stem}_round76dup{src.suffix}"
    shutil.move(str(src), str(dst))
    print(f"[ARCHIVE] {src} -> {dst}")
PY
```

注意：这一步不是删除，是移动到 `archive/experimental_scripts/`，便于以后追溯。

---

## 五、清理根目录明显临时文件

以下文件如果确认不是正式交付需要，请移动到归档目录，不要直接删除：

```bash
mkdir -p archive/round76_engineering_cleanup/root_temp_files
for f in auto_push_test.txt test_auto_push.txt auto_sync.py auto_sync.log; do
  if [ -e "$f" ]; then
    mv "$f" archive/round76_engineering_cleanup/root_temp_files/
    echo "[ARCHIVE] $f"
  fi
done
```

如果 `catboost_info/` 只是训练日志，也归档：

```bash
if [ -d catboost_info ]; then
  mv catboost_info archive/round76_engineering_cleanup/root_temp_files/
  echo "[ARCHIVE] catboost_info"
fi
```

---

## 六、检查 output 目录是否仍有明显历史残留

执行：

```bash
find output/pv_pipeline -maxdepth 2 -type d | sort
```

正式允许保留的目录建议只有：

```text
output/pv_pipeline/docs
output/pv_pipeline/figures
output/pv_pipeline/figures_dashboard
output/pv_pipeline/interactive_dashboard
output/pv_pipeline/logs
output/pv_pipeline/metrics
output/pv_pipeline/models
output/pv_pipeline/predictions
output/pv_pipeline/tables
output/pv_pipeline/validation
output/pv_pipeline/backups
output/pv_pipeline/baselines
```

如果仍看到下面这类目录，应移动到归档：

```text
output/pv_pipeline/round63
output/pv_pipeline/round64
output/pv_pipeline/round66
output/pv_pipeline/round67
output/pv_pipeline/round68
output/pv_pipeline/round69
output/pv_pipeline/round70
output/pv_pipeline/round71
output/pv_pipeline/round72
output/pv_pipeline/round73
output/pv_pipeline/round74
output/pv_pipeline/interactive_dashboard_round64_candidate
```

执行归档命令：

```bash
mkdir -p archive/round76_engineering_cleanup/output_round_residue
for d in output/pv_pipeline/round* output/pv_pipeline/interactive_dashboard_round*_candidate; do
  if [ -d "$d" ]; then
    mv "$d" archive/round76_engineering_cleanup/output_round_residue/
    echo "[ARCHIVE] $d"
  fi
done
```

---

## 七、确认正式主入口不会误用归档脚本

执行：

```bash
python -m py_compile scripts/run_full_pipeline.py
python -m py_compile scripts/posttrain_validation.py
python -m py_compile scripts/check_dashboard_prediction_values.py
python -m py_compile scripts/export_interactive_dashboard_data.py
```

然后检查 `run_full_pipeline.py` 中是否还直接调用已经归档的 round63-round73 脚本：

```bash
python - <<'PY'
from pathlib import Path
p = Path("scripts/run_full_pipeline.py")
txt = p.read_text(encoding="utf-8")
bad = [f"round{i}" for i in range(63, 74) if f"round{i}" in txt.lower()]
if bad:
    raise SystemExit(f"[FAIL] run_full_pipeline.py still references archived rounds: {bad}")
print("[OK] run_full_pipeline.py has no round63-round73 references")
PY
```

如果这里失败，不要强行继续；需要把对应逻辑改为正式脚本，或把必须依赖的脚本从 archive 移回 `scripts/` 并改名为正式功能名。

---

## 八、重新导出可视化数据并验证一致性

不重训，只刷新 dashboard 数据：

```bash
python scripts/export_interactive_dashboard_data.py
python scripts/check_dashboard_prediction_values.py
python scripts/posttrain_validation.py
```

验收条件：

- `check_dashboard_prediction_values.py` 必须通过。
- `posttrain_validation.py` 必须通过。
- `output/pv_pipeline/interactive_dashboard/metadata.json` 中：

```json
{
  "round": "Round68 final",
  "prediction_column": "power_pred_final",
  "exclude_future": true
}
```

---

## 九、检查 Git 状态

执行：

```bash
git status --short
```

预期变化包括：

- `README.md` 修改。
- `output/pv_pipeline/manifest.json` 修改。
- 新增 `scripts/fix_round76_manifest_consistency.py`。
- 历史 round 脚本从 `scripts/` 移到 `archive/experimental_scripts/`。
- 临时文件移动到 `archive/round76_engineering_cleanup/`。

如果还有已删除的 `Cursor执行方案_RoundXX...md`，请确认是否已经不需要。如果不需要，直接保留删除并提交；如果需要，移动到 `archive/round76_engineering_cleanup/cursor_plans/`。

---

## 十、最终生成 Round76 报告

新建：

`docs/Round76_工程收口与版本一致性清理报告.md`

内容至少包括：

```markdown
# Round76 工程收口与版本一致性清理报告

## 1. 本轮目标

本轮不重新训练，不改变模型结果，只修复多轮修改后留下的工程一致性问题。

## 2. 当前正式版本

- final_round: Round68 final
- prediction_column: power_pred_final
- final_full: output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
- final_eval: output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl
- dashboard: output/pv_pipeline/interactive_dashboard
- exclude_future: true

## 3. 已修复问题

- 修正 manifest 中 final_round/source_round 不一致问题。
- 修正 README 中 Round36 旧路径和 future 旧描述。
- 归档历史 round 脚本，减少正式 scripts 目录干扰。
- 归档根目录临时测试文件。
- 刷新可视化数据并完成一致性验证。

## 4. 验证结果

填写以下命令输出结论：

- python scripts/check_dashboard_prediction_values.py
- python scripts/posttrain_validation.py
- python -m py_compile ...

## 5. 剩余风险

- 本轮未重新训练。
- 本轮未改变模型结构。
- 如果后续重新训练，需要确认 run_full_pipeline.py 能完整复现当前正式产物。
```

---

## 十一、本轮验收标准

本轮完成后必须满足：

```bash
python scripts/check_dashboard_prediction_values.py
python scripts/posttrain_validation.py
python -m py_compile scripts/run_full_pipeline.py
python -m py_compile scripts/export_interactive_dashboard_data.py
```

全部通过。

同时执行：

```bash
python - <<'PY'
import json
from pathlib import Path
m = json.loads(Path("output/pv_pipeline/manifest.json").read_text(encoding="utf-8"))
d = json.loads(Path("output/pv_pipeline/interactive_dashboard/metadata.json").read_text(encoding="utf-8"))
assert m["final_round"] == "Round68 final"
assert m["prediction_column"] == "power_pred_final"
assert m["exclude_future"] is True
assert d["prediction_column"] == "power_pred_final"
assert d["exclude_future"] is True
print("[OK] final manifest/dashboard consistency passed")
PY
```

通过后，本轮才算完成。

---

## 十二、注意事项

- 本轮不要重新训练。
- 本轮不要改模型结构。
- 本轮不要改变 `power_pred_final` 数值。
- 所有删除动作优先改为归档移动。
- 如果归档后正式验证失败，立即把对应脚本从 archive 移回原位置，再排查依赖关系。

