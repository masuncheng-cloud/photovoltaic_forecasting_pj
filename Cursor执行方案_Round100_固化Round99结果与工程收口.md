# Cursor执行方案 Round100：固化 Round99 结果与工程收口

## 0. 本轮目标

Round99 已经完成完整前台重训，结果优于旧版本，但训练过程不是一遍无干预跑完，中途修复了多个 bug 并多次 resume。

本轮先不要继续改模型，也不要立即再次完整重训。

本轮目标：

1. 固化 Round99 当前有效结果，防止后续修改变差无法恢复。
2. 修复跨环境硬编码路径问题。
3. 确认 Step 6 分布式功率模型训练是否有真实阶段内进度条。
4. 做一次不重训的主流程自检，确认当前代码已经具备下一次“一条命令跑完”的条件。
5. 生成工程收口报告。

严禁执行完整训练：

```bash
python scripts/run_full_pipeline.py --mode full
python scripts/run_full_pipeline.py --mode full --force
python scripts/start_full_training.py
```

## 1. 固化 Round99 当前结果

### 1.1 创建本地归档快照

```bash
cd /Users/masuncheng/Downloads/photovoltaic_forecasting_pj

mkdir -p output/_archive/round100_round99_best_snapshot

python - <<'PY'
from pathlib import Path
import shutil
import json
from datetime import datetime

root = Path("output/pv_pipeline")
archive = Path("output/_archive/round100_round99_best_snapshot")
archive.mkdir(parents=True, exist_ok=True)

items = [
    "interactive_dashboard",
    "metrics",
    "predictions",
    "models",
    "tables",
    "docs",
    "manifest.json",
]

for name in items:
    src = root / name
    dst = archive / name
    if not src.exists():
        print("[SKIP]", src, "not exists")
        continue
    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    print("[SNAPSHOT]", src, "->", dst)

info = {
    "snapshot_time": datetime.now().isoformat(timespec="seconds"),
    "source": str(root),
    "reason": "Round99 best validated result before further engineering cleanup",
}
(archive / "snapshot_info.json").write_text(
    json.dumps(info, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print("[PASS] Round99 best snapshot saved")
PY
```

### 1.2 生成 Git 标签或本地 bundle

先检查 git 状态：

```bash
git status --short
```

如果当前仓库允许提交：

```bash
git add scripts src stages configs docs output/pv_pipeline/docs output/pv_pipeline/metrics output/pv_pipeline/interactive_dashboard
git commit -m "Round100 preserve Round99 validated training outputs and pipeline fixes"
git tag -f round99-best-validated
```

如果 GitHub 网络仍不可用，生成 bundle：

```bash
mkdir -p output/_archive/git_bundles
git bundle create output/_archive/git_bundles/round99-best-validated.bundle --all
```

如果仓库体积太大或包含不适合提交的大文件，至少生成补丁：

```bash
mkdir -p output/_archive/git_bundles
git diff > output/_archive/git_bundles/round99_code_changes.patch
```

## 2. 修复硬编码路径

Round99 报告指出：

```text
test_integrity_guards_round97_3.py 存在 Mac 路径硬编码
```

请搜索所有硬编码路径：

```bash
rg -n "/Users/masuncheng|/home/ac|/home/mjj|/root/autodl-tmp|127.0.0.1:8070" scripts src stages configs docs README.md
```

处理原则：

1. 测试脚本不得硬编码本地路径。
2. 使用 `Path(__file__).resolve().parents[...]` 定位项目根目录。
3. 允许文档里出现示例路径，但脚本逻辑中不允许依赖固定路径。

修复示例：

```python
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "output" / "pv_pipeline"
```

修复后执行：

```bash
python scripts/test_integrity_guards_round97_3.py
python scripts/test_integrity_guards_round98_1.py
```

两个测试必须通过。

## 3. 检查 Step 6 分布式功率模型训练进度条

Round99 报告中 Step 6 耗时约 600s，但没有明确记录 Step 6 的 `tqdm` 进度条。

请检查：

```text
stages/03_power/train_distributed_model_v159.py
src/pv_forecasting/tasks/distributed_power_v152.py
```

搜索：

```bash
rg -n "progress_iter|tqdm|fit\\(|for .*site|for .*hour|for .*scene|for .*candidate" \
  stages/03_power/train_distributed_model_v159.py \
  src/pv_forecasting/tasks/distributed_power_v152.py
```

要求：

1. 站点循环必须有进度条。
2. 小时模型或场景模型循环如果耗时明显，也必须有进度条。
3. 如果单个 `model.fit()` 很耗时但没有 callback，至少在 fit 前后打印清晰阶段提示：

```text
[Step 6] training global model: start
[Step 6] training global model: done elapsed=...
```

4. 不要使用一行一行打印的伪进度条。

如果发现 Step 6 没有真实进度条，请补上：

```python
from pv_forecasting.core.progress import progress_iter

for site_id in progress_iter(site_ids, total=len(site_ids), desc="[6] distributed model site loop", unit="site"):
    ...
```

如果 Step 6 是少数几个大 `fit()`，则新增阶段计时函数：

```python
from contextlib import contextmanager
import time

@contextmanager
def timed_stage(name: str):
    t0 = time.time()
    print(f"{name}: start", flush=True)
    try:
        yield
    finally:
        print(f"{name}: done elapsed={time.time() - t0:.1f}s", flush=True)
```

## 4. 不重训主流程自检

执行：

```bash
export PV_PROGRESS=1
export PV_PROGRESS_MODE=tqdm
export PV_MODEL_VERBOSE=0
export PYTHONUNBUFFERED=1

python scripts/preflight_check.py
python scripts/check_pipeline_consistency.py --stage pretrain
python scripts/run_full_pipeline.py --dry-run
python scripts/check_dashboard_integrity.py
python scripts/check_pipeline_consistency.py --stage posttrain
python scripts/test_integrity_guards_round97_3.py
python scripts/test_integrity_guards_round98_1.py
```

注意：这一步只检查当前 Round99 结果和主流程，不重新训练。

## 5. 检查 Round99 结果仍然有效

执行：

```bash
python - <<'PY'
from pathlib import Path
import json
import pandas as pd
from pv_forecasting.core.file_checks import is_lfs_pointer

base = Path("output/pv_pipeline")
full_pkl = base / "predictions" / "distributed_predictions_final_full.pkl"
eval_pkl = base / "predictions" / "distributed_predictions_final_eval.pkl"
dash = base / "interactive_dashboard"

for p in [full_pkl, eval_pkl]:
    assert p.exists(), p
    assert not is_lfs_pointer(p), p
    df = pd.read_pickle(p)
    print(p.name, "rows=", len(df), "cols=", len(df.columns))
    assert len(df) > 0

meta = json.loads((dash / "metadata.json").read_text(encoding="utf-8"))
print("dashboard generated_at:", meta.get("generated_at"))
print("prediction_column:", meta.get("prediction_column"))
print("policy:", meta.get("prediction_column_policy"))

assert meta.get("prediction_column") == "power_pred_final"
assert len(list((dash / "site_series").glob("*.json"))) >= 60
assert (dash / "typical_sites.json").exists()
assert (dash / "hourly_prediction_summary.json").exists()
print("[PASS] Round99 result still valid")
PY
```

## 6. 更新可视化启动说明

确认 README 或 docs 中有当前启动方式：

```bash
cd /Users/masuncheng/Downloads/photovoltaic_forecasting_pj
python -m http.server 8070
```

访问：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

如果是云服务器，说明需要端口转发或使用服务器 IP：

```text
http://<服务器IP>:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

## 7. 生成 Round100 报告

生成：

```text
docs/Round100_固化Round99结果与工程收口报告.md
```

报告必须包含：

1. 是否执行完整训练：必须为“未执行”。
2. Round99 快照是否已保存。
3. 是否创建 git tag 或 bundle。
4. 硬编码路径扫描结果和修复情况。
5. Step 6 是否存在真实进度反馈。
6. 不重训主流程自检结果。
7. Round99 pkl 是否仍为真实文件。
8. dashboard 是否仍然通过完整性检查。
9. 当前是否具备下一次一条命令完整训练的条件。

## 8. 通过标准

Round100 通过条件：

1. 未执行完整训练。
2. Round99 结果已快照保存。
3. 当前代码和结果已通过 git tag、bundle 或 patch 至少一种方式固化。
4. 脚本中无关键硬编码路径。
5. Step 6 进度反馈已确认或补齐。
6. `check_dashboard_integrity.py` 通过。
7. `check_pipeline_consistency.py --stage posttrain` 通过。
8. 下一次完整训练前不会再因工程残留问题卡住。

