# Cursor执行方案 Round99：完整前台重训与自动更新闭环验证

## 0. 本轮目标

本轮开始完整前台重训。

重点不只是“训练跑完”，而是验证整个流程能否一遍顺畅闭环：

1. 训练前检查不被旧 LFS 指针 pkl 卡住。
2. 每个长耗时阶段有真实 `tqdm` 动态进度条。
3. 训练流程不需要中途手动修错。
4. 训练完成后自动生成真实 pkl。
5. 训练完成后自动导出可视化数据。
6. 可视化页面数据自动更新，不需要手动伪造 metadata/index/site_series。
7. `check_dashboard_integrity.py` 和 `check_pipeline_consistency.py --stage posttrain` 自动通过。
8. 如果新结果失败或明显差于旧结果，可以回滚。

## 1. 训练前快照

必须先做快照。

```bash
cd /Users/masuncheng/Downloads/photovoltaic_forecasting_pj

mkdir -p output/_archive/round99_before_full_train

python - <<'PY'
from pathlib import Path
import shutil
import json
from datetime import datetime

root = Path("output/pv_pipeline")
archive = Path("output/_archive/round99_before_full_train")
archive.mkdir(parents=True, exist_ok=True)

items = [
    "interactive_dashboard",
    "metrics",
    "predictions",
    "models",
    "tables",
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
}
(archive / "snapshot_info.json").write_text(
    json.dumps(info, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print("[PASS] round99 snapshot done")
PY
```

## 2. 训练前检查

执行：

```bash
export PV_PROGRESS=1
export PV_PROGRESS_MODE=tqdm
export PV_MODEL_VERBOSE=0
export PYTHONUNBUFFERED=1

python scripts/preflight_check.py
python scripts/check_pipeline_consistency.py --stage pretrain
python scripts/check_dashboard_integrity.py --allow-structure-only
python scripts/run_full_pipeline.py --dry-run
```

通过标准：

1. `preflight_check.py` 通过。
2. `check_pipeline_consistency.py --stage pretrain` 通过。
3. `check_dashboard_integrity.py --allow-structure-only` 通过，并明确说明不代表预测值一致性。
4. `run_full_pipeline.py --dry-run` 显示：

```text
pretrain checks:
  - preflight_check.py
  - check_pipeline_consistency.py --stage pretrain

posttrain hooks:
  - export_interactive_dashboard_data.py
  - check_dashboard_integrity.py
  - check_pipeline_consistency.py --stage posttrain
```

如果任意一项失败，不要开始训练。

## 3. 记录训练前 dashboard 版本

执行：

```bash
python - <<'PY'
import json
from pathlib import Path

base = Path("output/pv_pipeline/interactive_dashboard")
meta_path = base / "metadata.json"
idx_path = base / "index.json"
site_dir = base / "site_series"

meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
idx = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}

print("[BEFORE] metadata generated_at:", meta.get("generated_at"))
print("[BEFORE] metadata round:", meta.get("round"))
print("[BEFORE] prediction_column:", meta.get("prediction_column"))
print("[BEFORE] index total_rows:", idx.get("total_rows"))
print("[BEFORE] site_series_count:", len(list(site_dir.glob("*.json"))) if site_dir.exists() else 0)
PY
```

把输出复制到 Round99 报告中，用于训练后对比。

## 4. 前台完整训练

本轮必须前台执行，不要后台。

如果在本地 Mac：

```bash
cd /Users/masuncheng/Downloads/photovoltaic_forecasting_pj

export PV_PROGRESS=1
export PV_PROGRESS_MODE=tqdm
export PV_MODEL_VERBOSE=0
export PYTHONUNBUFFERED=1

python scripts/run_full_pipeline.py --mode full
```

如果在云服务器：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

export PV_PROGRESS=1
export PV_PROGRESS_MODE=tqdm
export PV_MODEL_VERBOSE=0
export PYTHONUNBUFFERED=1

/home/ac/anaconda3/bin/python3 scripts/run_full_pipeline.py --mode full
```

不要先加 `--force`。如果不加 `--force` 导致主流程明确提示必须重建，再记录原因后使用：

```bash
python scripts/run_full_pipeline.py --mode full --force
```

## 5. 训练中重点观察

训练过程中必须记录以下内容：

### 5.1 进度条是否真实

应该看到类似：

```text
辐照融合-训练样本:  57%|███████████████| 15000/26304 [01:11<00:53, 210it/s]
分布式预测-站点建模:  42%|███████████| 29/68 [03:12<04:20, 6.68s/site]
dashboard-站点JSON导出: 100%|██████████| 68/68 [00:08<00:00, 8.1site/s]
```

不应该出现：

```text
[辐照融合] 10000/26304 38.0% elapsed=...
[██████░░░░░] 25.0% (4/16)
```

### 5.2 是否一遍流畅执行

记录是否出现：

1. 中途手动改代码。
2. 中途手动复制 pkl。
3. 中途手动伪造 metadata/index/site_series。
4. 某阶段失败后重新单独跑脚本。
5. 读取 LFS 指针导致超时。

目标是：一条主流程命令从头跑到尾。

### 5.3 长时间无进度反馈

如果某阶段超过 5 分钟没有任何输出或进度变化，记录：

```text
阶段名：
开始时间：
无输出持续时间：
最后一行日志：
```

这用于判断进度条仍有哪些盲区。

## 6. 训练后自动闭环检查

完整训练结束后，先确认主流程最后是否自动执行了：

```text
export_interactive_dashboard_data.py
check_dashboard_integrity.py
check_pipeline_consistency.py --stage posttrain
```

然后手动复核一次：

```bash
python scripts/check_dashboard_integrity.py
python scripts/check_pipeline_consistency.py --stage posttrain
python scripts/test_integrity_guards_round97_3.py
python scripts/test_integrity_guards_round98_1.py
```

## 7. 验证真实 pkl 已生成

执行：

```bash
python - <<'PY'
from pathlib import Path
import pandas as pd
from pv_forecasting.core.file_checks import is_lfs_pointer

paths = [
    Path("output/pv_pipeline/predictions/distributed_predictions_final_full.pkl"),
    Path("output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl"),
]

for p in paths:
    print("file:", p)
    print("exists:", p.exists())
    print("size:", p.stat().st_size if p.exists() else None)
    print("is_lfs_pointer:", is_lfs_pointer(p))
    assert p.exists(), f"missing {p}"
    assert not is_lfs_pointer(p), f"LFS pointer remains: {p}"
    df = pd.read_pickle(p)
    print("rows:", len(df), "cols:", len(df.columns))
    assert len(df) > 0
PY
```

## 8. 验证 dashboard 自动更新

执行：

```bash
python - <<'PY'
import json
from pathlib import Path

base = Path("output/pv_pipeline/interactive_dashboard")
meta = json.loads((base / "metadata.json").read_text(encoding="utf-8"))
idx = json.loads((base / "index.json").read_text(encoding="utf-8"))
site_count = len(list((base / "site_series").glob("*.json")))

print("[AFTER] metadata generated_at:", meta.get("generated_at"))
print("[AFTER] metadata round:", meta.get("round"))
print("[AFTER] prediction_column:", meta.get("prediction_column"))
print("[AFTER] prediction_column_policy:", meta.get("prediction_column_policy"))
print("[AFTER] index total_rows:", idx.get("total_rows"))
print("[AFTER] city_series rows:", len(idx.get("city_series", [])) if isinstance(idx.get("city_series"), list) else "check index schema")
print("[AFTER] site_series_count:", site_count)
print("[AFTER] typical_sites exists:", (base / "typical_sites.json").exists())
print("[AFTER] hourly_prediction_summary exists:", (base / "hourly_prediction_summary.json").exists())

assert meta.get("prediction_column") == "power_pred_final"
assert site_count >= 60
assert (base / "typical_sites.json").exists()
assert (base / "hourly_prediction_summary.json").exists()
PY
```

和第 3 节训练前输出对比：

1. `generated_at` 应更新。
2. `index total_rows` 应和新训练结果一致。
3. `site_series_count` 应完整。
4. 页面必需 JSON 应存在。

## 9. 启动可视化页面验证

在项目根目录启动：

```bash
python -m http.server 8070
```

浏览器打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

检查：

1. 页面能打开。
2. 数据版本时间是本次训练后时间。
3. 全市曲线有数据。
4. 单站点曲线有数据。
5. 逐小时预测结果表有数据。
6. 典型站点表有数据。
7. 不显示 `stale`、`placeholder`、旧版本警告。

## 10. 如果训练失败或结果异常，回滚

如果出现以下任一情况，执行回滚：

1. 训练中断。
2. pkl 仍是 LFS 指针。
3. dashboard 导出失败。
4. dashboard integrity fail。
5. pipeline consistency posttrain fail。
6. 页面显示占位或旧数据。
7. 新结果明显差于旧结果且没有合理解释。

回滚命令：

```bash
cd /Users/masuncheng/Downloads/photovoltaic_forecasting_pj

python - <<'PY'
from pathlib import Path
import shutil

root = Path("output/pv_pipeline")
archive = Path("output/_archive/round99_before_full_train")

for name in ["interactive_dashboard", "metrics", "predictions", "models", "tables", "manifest.json"]:
    src = archive / name
    dst = root / name
    if not src.exists():
        print("[SKIP]", src)
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
    print("[RESTORE]", src, "->", dst)
PY

python scripts/check_dashboard_integrity.py --allow-structure-only
python scripts/check_pipeline_consistency.py --stage pretrain
```

## 11. 生成 Round99 执行报告

生成：

```text
docs/Round99_完整前台重训与自动更新闭环验证报告.md
```

报告必须包含：

1. 是否执行完整训练。
2. 是否一条主流程命令跑完。
3. 是否中途手动修代码或补文件。
4. 每个阶段耗时。
5. 哪些阶段显示真实 `tqdm` 进度条。
6. 哪些阶段仍长时间无进度反馈。
7. 最终 pkl 是否真实、非 LFS 指针。
8. final full/eval 行数。
9. dashboard 是否自动更新。
10. `check_dashboard_integrity.py` 是否通过。
11. `check_pipeline_consistency.py --stage posttrain` 是否通过。
12. 可视化页面是否能打开。
13. 新旧核心指标对比。
14. 是否需要回滚，是否已回滚。

## 12. Round99 通过标准

本轮通过条件：

1. 完整训练前检查通过。
2. 完整训练在前台执行。
3. 主流程一遍跑完，中途不手动修补。
4. 长耗时阶段有真实 `tqdm` 进度条。
5. 真实 pkl 生成，非 LFS 指针。
6. dashboard 自动导出并更新。
7. `check_dashboard_integrity.py` 通过。
8. `check_pipeline_consistency.py --stage posttrain` 通过。
9. 可视化页面显示本次训练结果。

