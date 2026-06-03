# Cursor执行方案 Round92_1：完全重新训练与新旧产物隔离

## 目标

本轮不使用任何以前训练产生的中间文件、预测文件、指标文件或可视化文件。

要求：

1. 旧训练文件全部移动到一个独立备份目录。
2. 新训练文件全部从空目录重新生成。
3. 不允许从旧目录复制 `inverse_predictions.pkl`、预测 pkl、metrics、dashboard JSON 等文件补流程。
4. 修复当前主流程缺少“辐照反演”步骤的问题。
5. 用正式入口完整重训。
6. 训练完成后更新可视化页面。
7. 最终保留：
   - 旧产物目录：`archive/round92_1_previous_training_files/<时间戳>/`
   - 新产物目录：`output/pv_pipeline/`
   - 新产物快照：`output/pv_pipeline_round92_1_fresh_<时间戳>/`

---

## 一、使用正确 Python

训练必须使用 Anaconda Python：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

export PYTHON=/home/ac/anaconda3/bin/python3
$PYTHON --version
```

要求显示 Python 3.13 或当前项目依赖可用的 Anaconda Python。

不要使用：

```bash
/usr/bin/python3
```

---

## 二、修复主流程：补上辐照反演步骤

修改：

```text
scripts/run_full_pipeline.py
```

### 2.1 在辐照融合前插入辐照反演

找到 `STEPS = [` 中：

```python
{
    "id": "4",
    "name": "辐照融合",
    "script": "stages/02_irradiance/train_irradiance_blend.py",
    "required": True,
    "timeout": 600,
},
```

在它前面插入：

```python
{
    "id": "3b",
    "name": "辐照反演",
    "script": "stages/02_irradiance/train_inverse_model.py",
    "required": True,
    "timeout": 900,
},
```

插入后顺序应为：

```text
1 站点元数据构建
2 应用人工经纬度覆盖
3 数据清洗与气象插值
3b 辐照反演
4 辐照融合
5 训练前数据审计
...
```

### 2.2 修复手写 mode 的步骤列表

`full` 模式通常自动读取 `STEPS`，不用手动加。

但以下模式如果有手写步骤列表，必须加入 `3b`：

```python
"geo-refresh": {
    ...
    "steps": ["1", "2", "3", "3b", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13"],
}
```

如果 `geo-refresh` 本来没有 `"3"`，也要加上 `"3"`，因为清空 output 后不能跳过数据清洗。

`train-only`、`eval-only`、`dashboard-only` 不需要加 `3b`，因为它们依赖已有上游产物。

### 2.3 更新注释说明

把 `run_full_pipeline.py` 顶部训练链路说明改为：

```text
[4]  辐照反演                   → stages/02_irradiance/train_inverse_model.py
[5]  辐照融合                   → stages/02_irradiance/train_irradiance_blend.py
```

后续编号可以不强求完全重排，但日志里必须能看到“辐照反演”在“辐照融合”之前执行。

---

## 三、禁止使用旧训练文件

### 3.1 归档旧 output

执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

STAMP=$(date +%Y%m%d_%H%M%S)
OLD_DIR="archive/round92_1_previous_training_files/${STAMP}"
mkdir -p "$OLD_DIR"

if [ -d output/pv_pipeline ]; then
  mv output/pv_pipeline "$OLD_DIR/pv_pipeline_old"
fi

mkdir -p output/pv_pipeline/logs

echo "$OLD_DIR" > output/pv_pipeline/logs/round92_1_old_dir.txt
echo "Old training files moved to: $OLD_DIR"
```

注意：

- 这里是 `mv`，不是 `cp`。
- 旧产物不能继续留在 `output/pv_pipeline`。
- 后续任何缺失文件都必须由重新训练生成，不能从 `$OLD_DIR` 复制回来。

### 3.2 清除缓存和 pycache

执行：

```bash
find . -type d -name "__pycache__" -prune -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
find . -type f -name ".DS_Store" -delete

rm -rf output/pv_pipeline/cache
rm -rf output/pv_pipeline/backups
rm -rf output/pv_pipeline/baselines
rm -rf output/pv_pipeline/round*
rm -rf output/pv_pipeline/archive*
```

---

## 四、训练前结构检查

执行：

```bash
$PYTHON scripts/audit_round92_project_integrity.py
```

如果该脚本不存在，先用下面的最小检查：

```bash
$PYTHON - <<'PY'
from pathlib import Path

required = [
    "scripts/run_full_pipeline.py",
    "stages/01_data/build_site_master.py",
    "stages/01_data/prepare_meteo_and_power.py",
    "stages/02_irradiance/train_inverse_model.py",
    "stages/02_irradiance/train_irradiance_blend.py",
    "stages/03_power/train_distributed_model_v159.py",
    "scripts/build_round36_predictions.py",
    "scripts/apply_round36_calibration.py",
    "scripts/compute_round36_metrics.py",
    "scripts/post_training_finalize_outputs.py",
    "scripts/export_interactive_dashboard_data.py",
    "scripts/posttrain_validation.py",
    "scripts/check_dashboard_prediction_values.py",
]

missing = [p for p in required if not Path(p).exists()]
print("missing:", missing)
if missing:
    raise SystemExit(1)

text = Path("scripts/run_full_pipeline.py").read_text(encoding="utf-8", errors="ignore")
assert "train_inverse_model.py" in text, "run_full_pipeline.py still missing train_inverse_model.py"
print("[OK] required scripts exist and inverse step is registered")
PY
```

---

## 五、完整重新训练

执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
mkdir -p output/pv_pipeline/logs

$PYTHON scripts/run_full_pipeline.py --mode full --force 2>&1 | tee output/pv_pipeline/logs/round92_1_full_retrain.log
```

本次必须在日志中看到：

```text
辐照反演
辐照融合
```

并且顺序必须是：

```text
辐照反演先于辐照融合
```

如果仍然报：

```text
inverse_predictions.pkl not found
```

说明主流程仍未正确执行 `train_inverse_model.py`，不要从旧目录复制文件，回到第二步修主流程。

---

## 六、训练后导出可视化数据

完整训练通过后，执行：

```bash
$PYTHON scripts/run_full_pipeline.py --mode dashboard-only --force 2>&1 | tee output/pv_pipeline/logs/round92_1_dashboard_update.log
```

再单独执行一次导出，确保非 future 全历史数据已刷新：

```bash
$PYTHON scripts/export_interactive_dashboard_data.py 2>&1 | tee -a output/pv_pipeline/logs/round92_1_dashboard_update.log
```

---

## 七、训练后验证

执行：

```bash
$PYTHON scripts/check_pipeline_consistency.py
$PYTHON scripts/posttrain_validation.py
$PYTHON scripts/check_dashboard_prediction_values.py
$PYTHON scripts/check_no_future_in_outputs.py
```

如果存在以下脚本，也执行：

```bash
[ -f scripts/check_dashboard_data_freshness.py ] && $PYTHON scripts/check_dashboard_data_freshness.py
[ -f scripts/check_dashboard_auto_update_stamp.py ] && $PYTHON scripts/check_dashboard_auto_update_stamp.py
[ -f scripts/check_post_training_auto_finalize.py ] && $PYTHON scripts/check_post_training_auto_finalize.py
[ -f scripts/audit_prediction_column_consistency.py ] && $PYTHON scripts/audit_prediction_column_consistency.py
```

所有正式检查必须 PASS。

---

## 八、确认没有使用旧文件

执行：

```bash
$PYTHON - <<'PY'
from pathlib import Path
from datetime import datetime
import json
import pandas as pd

out = Path("output/pv_pipeline")
old_dir_file = out / "logs" / "round92_1_old_dir.txt"
print("old_dir:", old_dir_file.read_text().strip() if old_dir_file.exists() else "not recorded")

required = [
    out / "predictions/distributed_predictions_final_full.pkl",
    out / "predictions/distributed_predictions_final_eval.pkl",
    out / "metrics/hourly_nrmse_consistent.csv",
    out / "metrics/site_metrics_consistent.csv",
    out / "interactive_dashboard/index.json",
    out / "interactive_dashboard/metadata.json",
    out / "interactive_dashboard/city_series.json",
]

for p in required:
    assert p.exists(), f"missing {p}"
    print("[OK]", p, datetime.fromtimestamp(p.stat().st_mtime))

full = pd.read_pickle(out / "predictions/distributed_predictions_final_full.pkl")
assert "power_pred_final" in full.columns, "missing power_pred_final"
print("final_full shape:", full.shape)
if "split" in full.columns:
    print(full["split"].value_counts(dropna=False))

meta = json.loads((out / "interactive_dashboard/metadata.json").read_text(encoding="utf-8"))
print("dashboard metadata:", {
    k: meta.get(k) for k in ["generated_at", "dashboard_data_scope", "include_future", "min_date", "max_date", "has_2025_spring"]
})
PY
```

检查重点：

- 所有输出文件修改时间都应是本次训练之后。
- `power_pred_final` 必须存在。
- `interactive_dashboard/metadata.json` 必须是本次导出时间。
- 不允许旧目录文件被复制回 `output/pv_pipeline`。

---

## 九、保存新训练产物到独立文件夹

训练和验证全部通过后，把新结果复制成独立快照：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

STAMP=$(date +%Y%m%d_%H%M%S)
NEW_SNAPSHOT="output/pv_pipeline_round92_1_fresh_${STAMP}"

cp -a output/pv_pipeline "$NEW_SNAPSHOT"

echo "New training snapshot: $NEW_SNAPSHOT"
```

最终目录结构应为：

```text
archive/round92_1_previous_training_files/<时间戳>/pv_pipeline_old/
output/pv_pipeline/
output/pv_pipeline_round92_1_fresh_<时间戳>/
```

含义：

- `archive/.../pv_pipeline_old/`：旧训练文件，仅作备份；
- `output/pv_pipeline/`：当前页面和主流程使用的新训练结果；
- `output/pv_pipeline_round92_1_fresh_*/`：本次全新训练产物快照。

---

## 十、启动可视化页面

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
$PYTHON -m http.server 8070
```

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round92_1
```

强制刷新：

```text
Ctrl + Shift + R
```

Safari：

```text
Option + Command + R
```

页面检查：

- 数据版本时间为本次训练后时间。
- 全市折线图有数据。
- 单站点折线图有数据。
- 日期范围来自新导出的 metadata。
- 不包含 future。
- 如果新导出数据有 3-5 月，春季按钮可用；如果没有，春季灰掉是正常。

---

## 十一、生成执行报告

新建：

```text
docs/Round92_1_完全重新训练与新旧产物隔离报告.md
```

内容模板：

```markdown
# Round92_1 完全重新训练与新旧产物隔离报告

## 1. 执行目标

- 不使用旧训练产物。
- 修复主流程缺少辐照反演步骤。
- 旧文件整体归档。
- 新文件从空 output/pv_pipeline 重新生成。
- 更新可视化页面。

## 2. 旧文件归档

- 旧目录：
- 旧文件是否仍在 output/pv_pipeline：否

## 3. 主流程修复

- 是否添加 train_inverse_model.py：
- 辐照反演是否先于辐照融合执行：

## 4. 完整训练

- 命令：
- 开始时间：
- 结束时间：
- 总耗时：
- 是否 PASS：
- 中断/告警：

## 5. 新训练产物

- final_full 行数：
- final_eval 行数：
- 最终预测列：
- metrics 文件：
- dashboard metadata 时间：
- dashboard min_date/max_date：
- include_future：
- has_2025_spring：

## 6. 验证结果

- check_pipeline_consistency：
- posttrain_validation：
- check_dashboard_prediction_values：
- check_no_future_in_outputs：

## 7. 新旧产物位置

- 旧产物：
- 当前新产物：
- 新产物快照：

## 8. 结论

本轮完成完全重新训练。当前 output/pv_pipeline 中所有正式产物均由本轮训练重新生成，未复用旧训练中间文件。
```

---

## 十二、Git 保存

如果训练和验证全部通过：

```bash
git status --short
git add .
git commit -m "Round92_1: fresh full retrain with separated old and new artifacts"
git tag -a round92_1-fresh-full-retrain -m "Fresh full retrain, old artifacts archived, dashboard updated"
git push
git push --tags
```

如果训练失败，不要提交 tag。

---

## 十三、失败处理

### 13.1 如果辐照融合仍缺 inverse_predictions.pkl

不要复制旧文件。

检查：

```bash
grep -n "train_inverse_model.py\\|辐照反演" scripts/run_full_pipeline.py
tail -120 output/pv_pipeline/logs/round92_1_full_retrain.log
```

确认 `train_inverse_model.py` 是否执行、是否报错。

### 13.2 如果想回退旧产物

只在确认新训练失败且需要恢复页面时执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

OLD_DIR=$(cat output/pv_pipeline/logs/round92_1_old_dir.txt)
rm -rf output/pv_pipeline
cp -a "$OLD_DIR/pv_pipeline_old" output/pv_pipeline
```

但回退后要在报告中明确：

```text
本轮新训练失败，当前页面已回退旧产物。
```

---

## 十四、注意事项

1. 不允许从旧 output 中复制任何中间文件到新 output。
2. 不允许跳过 `train_inverse_model.py`。
3. 不允许直接运行历史 round 实验脚本替代正式主流程。
4. 不允许 dashboard 包含 future。
5. 新训练结果必须集中在 `output/pv_pipeline/`。
6. 旧训练结果必须集中在 `archive/round92_1_previous_training_files/`。
7. 新训练完成后必须复制一份快照到 `output/pv_pipeline_round92_1_fresh_<时间戳>/`。
