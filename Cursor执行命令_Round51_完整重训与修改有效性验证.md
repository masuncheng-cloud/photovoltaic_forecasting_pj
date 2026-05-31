# Cursor 执行命令 Round51：完整重训与修改有效性验证

## 目标

重新启动一次完整训练，验证 Round50 工程收口修改是否真正生效。

本轮重点不是继续改模型，而是确认：

1. 正式训练入口可以从头跑通。
2. 最终预测文件、指标文件、可视化数据都来自同一次最新训练。
3. `power_pred_final` 是唯一最终预测列。
4. 逐小时 NRMSE、站点指标、可视化页面数据口径一致。
5. 训练后自动刷新可视化数据机制有效。
6. 历史 round 文件归档后不影响主流程。

---

## 一、进入项目根目录

先进入 Cursor 云服务器中的正式项目目录。

如果项目目录是：

```bash
/home/ac/data16t/msc/photovoltaic_forecasting_pj
```

则执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
pwd
```

如果你的实际目录不同，请先用：

```bash
find /home -maxdepth 5 -type d -name "photovoltaic_forecasting_pj" 2>/dev/null
```

找到正式目录后再 `cd` 进入。

---

## 二、执行前结构检查

```bash
echo "==== project files ===="
ls

echo "==== key scripts ===="
ls scripts | sort | sed -n '1,200p'

echo "==== config ===="
ls configs || true

echo "==== output root ===="
ls output/pv_pipeline || true
```

必须确认存在：

```text
configs/pipeline.yaml
scripts/run_full_pipeline.py
scripts/export_interactive_dashboard_data.py
scripts/posttrain_validation.py
scripts/check_dashboard_prediction_values.py
stages/05_visualization/interactive_forecast_dashboard.html
```

如果缺少 `scripts/run_full_pipeline.py`，说明 Round50 没有完整落地，请先按 Round50 方案补齐，不要继续训练。

---

## 三、清理旧的临时缓存，但不删除历史结果

不要删除旧结果，只清理 Python 缓存和临时日志。

```bash
find . -type d -name "__pycache__" -prune -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
mkdir -p output/pv_pipeline/logs
mkdir -p output/pv_pipeline/validation
```

如果 Round50 已经提供归档脚本，先 dry-run：

```bash
python scripts/archive_legacy_round_files.py --dry-run
```

确认不会移动正式主流程文件后，再执行：

```bash
python scripts/archive_legacy_round_files.py --apply
```

归档完成后再次确认正式脚本仍存在：

```bash
test -f scripts/run_full_pipeline.py
test -f scripts/export_interactive_dashboard_data.py
test -f scripts/posttrain_validation.py
test -f scripts/check_dashboard_prediction_values.py
```

---

## 四、执行完整训练

使用唯一正式入口执行完整训练。

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml 2>&1 | tee output/pv_pipeline/logs/round51_full_train.log
```

训练完成后，立即检查日志是否有错误：

```bash
grep -Ei "error|exception|traceback|fail|missing|not found|nan|inf" output/pv_pipeline/logs/round51_full_train.log || true
```

说明：

- 如果出现 `Traceback`、`FileNotFoundError`、`KeyError`、`ValueError`，必须先修复后重跑。
- 如果只是验证报告中主动打印的 `0 FAIL`，不算错误。
- 不允许跳过失败步骤继续生成报告。

---

## 五、检查最终产物是否生成

```bash
echo "==== final prediction files ===="
ls -lh output/pv_pipeline/predictions || true

echo "==== final metrics files ===="
ls -lh output/pv_pipeline/metrics || true

echo "==== dashboard files ===="
ls -lh output/pv_pipeline/interactive_dashboard || true

echo "==== manifest ===="
ls -lh output/pv_pipeline/manifest.json || true
```

必须存在：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl
output/pv_pipeline/metrics/hourly_nrmse_consistent.csv
output/pv_pipeline/metrics/site_metrics_consistent.csv
output/pv_pipeline/interactive_dashboard/index.json
output/pv_pipeline/manifest.json
```

如果你的项目实际路径略有不同，请在 `manifest.json` 中明确最终文件路径。

---

## 六、验证最终预测列

执行：

```bash
python - <<'PY'
import pandas as pd
from pathlib import Path

full_path = Path("output/pv_pipeline/predictions/distributed_predictions_final_full.pkl")
eval_path = Path("output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl")

for path in [full_path, eval_path]:
    print(f"\n==== {path} ====")
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_pickle(path)
    print("rows:", len(df))
    print("columns:", list(df.columns)[:80])
    required = ["timestamp", "station_id", "power_mw", "power_pred_final", "capacity_mw"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"{path} missing columns: {missing}")
    print("power_pred_final null ratio:", df["power_pred_final"].isna().mean())
    print("power_pred_final min/max:", df["power_pred_final"].min(), df["power_pred_final"].max())
    if df["power_pred_final"].isna().all():
        raise ValueError(f"{path} power_pred_final is all NaN")
print("\n[OK] final prediction column exists and is usable")
PY
```

验收标准：

- `power_pred_final` 必须存在。
- `power_pred_final` 不能全空。
- 不允许最终评估和可视化使用 `power_pred_cal` 或其他临时列。

---

## 七、重新计算一致性指标

执行训练后审计：

```bash
python scripts/posttrain_validation.py --config configs/pipeline.yaml 2>&1 | tee output/pv_pipeline/logs/round51_posttrain_validation.log
```

检查结果：

```bash
grep -Ei "FAIL|ERROR|Traceback|Exception" output/pv_pipeline/logs/round51_posttrain_validation.log || true
```

必须生成：

```text
output/pv_pipeline/validation/posttrain_validation_report.md
output/pv_pipeline/validation/posttrain_validation_results.csv
```

如果验证报告中有 FAIL，必须修复后重新完整训练。

---

## 八、验证可视化数据与最终预测一致

执行：

```bash
python scripts/check_dashboard_prediction_values.py --config configs/pipeline.yaml 2>&1 | tee output/pv_pipeline/logs/round51_dashboard_check.log
```

检查：

```bash
grep -Ei "FAIL|ERROR|Traceback|Exception|max_abs_diff" output/pv_pipeline/logs/round51_dashboard_check.log || true
```

验收标准：

```text
actual max_abs_diff <= 1e-9
prediction max_abs_diff <= 1e-9
city aggregation max_abs_diff <= 1e-6
dashboard generated_at >= final prediction mtime
```

如果发现 dashboard 数据旧于最终 pkl，执行：

```bash
python scripts/export_interactive_dashboard_data.py --config configs/pipeline.yaml
python scripts/check_dashboard_prediction_values.py --config configs/pipeline.yaml
```

然后检查 `run_full_pipeline.py` 是否已经在最后自动调用了导出脚本。若没有，补上后重新完整训练。

---

## 九、检查逐小时 NRMSE 结果

```bash
echo "==== hourly NRMSE ===="
python - <<'PY'
import pandas as pd
from pathlib import Path

path = Path("output/pv_pipeline/metrics/hourly_nrmse_consistent.csv")
if not path.exists():
    raise FileNotFoundError(path)
df = pd.read_csv(path)
print(df.to_string(index=False))

required = ["hour", "sample_count", "site_mean_nrmse_percent", "city_nrmse_percent"]
missing = [c for c in required if c not in df.columns]
if missing:
    raise KeyError(f"hourly csv missing columns: {missing}")

if not set(range(6, 20)).issubset(set(df["hour"].astype(int))):
    raise ValueError("hourly csv does not contain all 6-19 hours")

print("\n10-14 city NRMSE:")
print(df[df["hour"].between(10, 14)][["hour", "city_nrmse_percent", "site_mean_nrmse_percent"]].to_string(index=False))
PY
```

关注：

- 6-19 点是否齐全。
- 10-14 点城市 NRMSE 是否没有明显劣化。
- 站点平均 NRMSE 是否仍异常偏高。
- 样本数是否与测试集口径一致。

---

## 十、检查站点指标结果

```bash
echo "==== site metrics top/bottom ===="
python - <<'PY'
import pandas as pd
from pathlib import Path

path = Path("output/pv_pipeline/metrics/site_metrics_consistent.csv")
if not path.exists():
    raise FileNotFoundError(path)
df = pd.read_csv(path)

print("rows:", len(df))
print("columns:", list(df.columns))

for col in ["station_id", "station_name", "capacity_mw", "mae_mw", "rmse_mw", "nrmse_percent"]:
    if col not in df.columns:
        raise KeyError(f"missing column: {col}")

print("\nBest 10:")
print(df.sort_values("nrmse_percent").head(10).to_string(index=False))

print("\nWorst 10:")
print(df.sort_values("nrmse_percent", ascending=False).head(10).to_string(index=False))
PY
```

关注：

- 典型站点按钮使用的最好、最差站点是否与该 CSV 一致。
- 无效站点是否已从样本量-NRMSE 统计中排除。
- 测试集 6-19 点 0 值占比是否有记录。

---

## 十一、检查可视化页面数据是否最新

查看 `index.json`、`metadata.json`、最终预测文件修改时间：

```bash
python - <<'PY'
from pathlib import Path
import json
from datetime import datetime

files = [
    "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl",
    "output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl",
    "output/pv_pipeline/interactive_dashboard/index.json",
    "output/pv_pipeline/interactive_dashboard/metadata.json",
    "output/pv_pipeline/metrics/hourly_nrmse_consistent.csv",
    "output/pv_pipeline/metrics/site_metrics_consistent.csv",
]

for f in files:
    p = Path(f)
    if not p.exists():
        print("[MISSING]", f)
        continue
    print("[FILE]", f, datetime.fromtimestamp(p.stat().st_mtime).isoformat())

meta = Path("output/pv_pipeline/interactive_dashboard/metadata.json")
if meta.exists():
    print("\nmetadata:")
    print(json.dumps(json.loads(meta.read_text(encoding="utf-8")), ensure_ascii=False, indent=2)[:3000])
PY
```

判断：

- `interactive_dashboard/*.json` 的修改时间应晚于或接近最终预测 pkl。
- 如果页面仍显示旧数据，优先怀疑浏览器缓存或访问目录错误。

---

## 十二、启动可视化页面

先确认端口没有旧服务占用。

```bash
lsof -i :8060 || true
```

如果 8060 被旧服务占用，可以使用 8070：

```bash
python -m http.server 8060
```

或者：

```bash
python -m http.server 8070
```

访问：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

或：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

浏览器强制刷新：

```text
Ctrl + Shift + R
```

页面检查：

1. 全市总出力曲线有数据。
2. 单站点曲线有数据。
3. 典型站点按钮能切换站点。
4. 四季最佳日能切换日期。
5. 指标卡随筛选条件变化。
6. 逐小时预测结果表有 6-19 点。
7. 样本量与 NRMSE 散点图存在。
8. 页面不再显示“旧数据”或“请重新运行导出脚本”的警告。

---

## 十三、生成 Round51 执行报告

新增文件：

```text
docs/Round51_完整重训与修改有效性验证报告.md
```

报告内容按以下模板填写：

```markdown
# Round51 完整重训与修改有效性验证报告

## 1. 执行时间与环境

- 项目路径：
- Python 版本：
- 训练入口：
- 配置文件：

## 2. 完整训练结果

- 是否跑通：
- 总耗时：
- 是否出现报错：
- 最终预测列：

## 3. 最终产物

| 产物 | 路径 | 是否存在 | 修改时间 |
|---|---|---:|---|
| final full pkl |  |  |  |
| final eval pkl |  |  |  |
| hourly nrmse csv |  |  |  |
| site metrics csv |  |  |  |
| dashboard index |  |  |  |
| manifest |  |  |  |

## 4. 训练后审计结果

- posttrain_validation 是否 PASS：
- dashboard prediction check 是否 PASS：
- actual max_abs_diff：
- prediction max_abs_diff：
- city aggregation max_abs_diff：

## 5. 逐小时 NRMSE

粘贴 `hourly_nrmse_consistent.csv` 中 6-19 点结果。

## 6. 站点指标

- 最好 5 个站点：
- 最差 5 个站点：
- 无效站点：

## 7. 可视化页面验证

- 全市曲线：
- 单站点曲线：
- 典型站点按钮：
- 四季最佳日：
- 指标卡刷新：
- 页面是否仍有旧数据警告：

## 8. 结论

- Round50 修改是否生效：
- 当前仍存在的问题：
- 下一步建议：
```

---

## 十四、如果训练失败，按以下顺序排查

### 1. 缺文件

```bash
find . -name "run_full_pipeline.py" -o -name "pipeline.yaml" -o -name "export_interactive_dashboard_data.py"
```

### 2. 预测列缺失

```bash
python - <<'PY'
import pandas as pd
from pathlib import Path
for p in Path("output/pv_pipeline").rglob("*.pkl"):
    try:
        df = pd.read_pickle(p)
        cols = [c for c in df.columns if "pred" in c.lower()]
        if cols:
            print(p, cols)
    except Exception:
        pass
PY
```

### 3. 可视化仍旧数据

```bash
python scripts/export_interactive_dashboard_data.py --config configs/pipeline.yaml
python scripts/check_dashboard_prediction_values.py --config configs/pipeline.yaml
```

然后重新启动 http server，并强制刷新浏览器。

### 4. 指标不一致

```bash
python scripts/posttrain_validation.py --config configs/pipeline.yaml
```

优先修复公共指标函数 `scripts/metrics_common.py`，不要在报告脚本里单独重写公式。

---

## 十五、验收结论标准

本轮只有满足以下条件，才算修改有效：

```text
[PASS] 完整训练入口 run_full_pipeline.py 跑通
[PASS] final_full/final_eval 均包含 power_pred_final
[PASS] posttrain_validation 无 FAIL
[PASS] dashboard prediction check 无 FAIL
[PASS] 可视化 JSON 修改时间不早于最终预测文件
[PASS] 页面全市和单站点曲线均正常显示
[PASS] 页面指标与 CSV 口径一致
[PASS] README 中正式入口与实际入口一致
```

如果任一项失败，不要进入下一轮模型优化，先修复工程链路。

