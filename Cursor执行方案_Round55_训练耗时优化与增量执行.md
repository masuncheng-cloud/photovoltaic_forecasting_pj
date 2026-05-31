# Cursor 执行方案 Round55：训练耗时优化、增量执行与链路耗时审计

## 目标

Round54 已经修复 S115/S116 经纬度进入特征链路的问题，但执行时间过长。本轮不优先改模型精度，而是优化训练流程执行效率，避免每次小修改都全量重训。

本轮目标：

1. 给完整训练链路增加逐步骤耗时统计。
2. 建立 `full / train-only / eval-only / dashboard-only / audit-only / geo-refresh` 多种执行模式。
3. 对输入文件和中间产物做指纹校验，未变化的步骤允许跳过。
4. 避免诊断脚本全项目 `rglob` 扫描大量 pkl/csv。
5. 修复 Round54 中 Step 11 需要单独执行的问题，让主流程真正一次跑完。
6. 去掉 `export_interactive_dashboard_data.py` 中硬编码 Round36/46 的复杂逻辑。
7. 保证提速后结果仍然可验证、可复现、可视化仍然最新。

---

## 一、先判断 Round54 慢在哪里

Round54 慢的主要原因预计有 5 个：

1. **完整重训本身耗时**  
   Step 6 分布式功率模型训练通常是最耗时部分。

2. **经纬度链路诊断脚本全项目扫描**  
   `diagnose_geo_feature_flow.py` 如果使用 `ROOT.rglob("*.pkl") / rglob("*.csv")`，会读取大量历史产物，I/O 很慢。

3. **可视化导出全量 JSON**  
   站点序列、城市序列、典型站点、散点图、逐小时指标都重新导出，会有明显 I/O。

4. **验证脚本重复读取大 pkl**  
   `posttrain_validation.py`、`check_dashboard_prediction_values.py`、dashboard export 可能重复读取同一个百万行 pkl。

5. **Step 11 失败后单独重跑**  
   Round54 报告显示 Step 11 是“修复断言后单独执行通过”，说明主流程仍存在一次失败重跑成本。

---

## 二、给 run_full_pipeline.py 增加执行模式

修改：

```text
scripts/run_full_pipeline.py
```

新增参数：

```bash
--mode full
--mode train-only
--mode eval-only
--mode dashboard-only
--mode audit-only
--mode geo-refresh
--force
```

模式含义：

| mode | 执行内容 | 使用场景 |
|---|---|---|
| `full` | 从 Stage 01 到最终 dashboard 全部执行 | 原始数据、核心模型、特征逻辑变化 |
| `geo-refresh` | 重建站点元数据、太阳/辐照特征、预测与评估 | 只改经纬度或地理特征 |
| `train-only` | 从训练表开始训练模型，不重跑原始清洗 | 模型参数、特征选择变化 |
| `eval-only` | 使用已有预测 pkl 重算指标和报告 | 只改指标口径 |
| `dashboard-only` | 使用 canonical pkl/csv 重新导出可视化 | 只改网页或导出逻辑 |
| `audit-only` | 只跑 posttrain/dashboard/链路审计 | 只验证结果 |

执行示例：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode full
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode dashboard-only
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode eval-only
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode audit-only
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode geo-refresh
```

要求：

- 默认 `--mode full`。
- 如果某个模式依赖的上游文件不存在，必须报错并提示应使用 `--mode full`。
- 不允许静默 fallback 到 legacy 文件。

---

## 三、增加步骤耗时日志

在 `run_full_pipeline.py` 中增加统一计时器：

```python
from contextlib import contextmanager
from time import perf_counter
from datetime import datetime
import json

timing_rows = []

@contextmanager
def timed_step(name, outputs=None):
    start = perf_counter()
    wall_start = datetime.now().isoformat(timespec="seconds")
    print(f"\n[STEP START] {name} @ {wall_start}")
    status = "PASS"
    error = ""
    try:
        yield
    except Exception as exc:
        status = "FAIL"
        error = repr(exc)
        raise
    finally:
        sec = perf_counter() - start
        row = {
            "step": name,
            "status": status,
            "seconds": round(sec, 3),
            "minutes": round(sec / 60, 3),
            "started_at": wall_start,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "error": error,
            "outputs": outputs or [],
        }
        timing_rows.append(row)
        print(f"[STEP END] {name}: {status}, {sec:.1f}s")
```

流程结束时写出：

```text
output/pv_pipeline/logs/pipeline_timing_latest.csv
output/pv_pipeline/logs/pipeline_timing_latest.json
```

报告中必须列出耗时 Top 5 步骤。

---

## 四、增加文件指纹和跳过机制

新增工具：

```text
scripts/pipeline_cache.py
```

功能：

```python
import hashlib
from pathlib import Path

def file_fingerprint(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"exists": False}
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return {
        "exists": True,
        "path": str(p),
        "size": p.stat().st_size,
        "mtime": p.stat().st_mtime,
        "sha256": h.hexdigest(),
    }
```

每一步保存：

```text
output/pv_pipeline/cache/<step_name>.json
```

内容：

```json
{
  "step": "stage01_clean",
  "input_fingerprints": {},
  "output_files": [],
  "finished_at": "...",
  "status": "PASS"
}
```

跳过规则：

- 输入文件指纹未变化。
- 输出文件存在。
- 未指定 `--force`。
- 该步骤允许缓存。

不允许跳过的步骤：

```text
manifest 写出
posttrain_validation
dashboard freshness check
```

这些必须每次执行。

---

## 五、减少 diagnose_geo_feature_flow.py 的扫描范围

当前诊断脚本不要再 `ROOT.rglob("*.pkl")` 全项目扫描。

改为只检查固定清单：

```python
FILES_TO_CHECK = [
    "configs/manual_station_geo_overrides.csv",
    "output/pv_pipeline/tables/station_metadata_canonical.pkl",
    "output/pv_pipeline/tables/station_metadata_canonical.csv",
    "output/pv_pipeline/tables/train_features.pkl",
    "output/pv_pipeline/tables/distributed_predictions_final_round36.pkl",
    "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl",
    "output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl",
    "output/pv_pipeline/metrics/site_metrics_consistent.csv",
]
```

如果项目实际文件名不同，用 `manifest.json` 中的 artifact 路径作为优先来源。

要求：

- 默认不扫描 `archive/`。
- 默认不扫描 `output/` 下所有历史文件。
- 如需深度扫描，增加参数：

```bash
python scripts/diagnose_geo_feature_flow.py --deep-scan
```

---

## 六、修复 Step 11 必须单独执行的问题

Round54 报告显示：

```text
Step 11 PASS（修复断言后单独执行）
```

这说明主流程首次执行时 Step 11 没有完全通过。

要求：

1. 把 Step 11 中的断言修复纳入代码。
2. `run_full_pipeline.py --mode full` 一次执行必须完整通过。
3. 不允许报告中再出现“某步骤单独执行通过”。

验证：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode full 2>&1 | tee output/pv_pipeline/logs/round55_full_pipeline.log
grep -Ei "单独执行|manual|rerun|retry|FAIL|Traceback|Exception" output/pv_pipeline/logs/round55_full_pipeline.log || true
```

---

## 七、清理 Round36/46 硬编码逻辑

重点修改：

```text
scripts/export_interactive_dashboard_data.py
scripts/compute_round36_metrics.py
scripts/round46_recompute_hourly_nrmse_consistent.py
```

如果暂时不能重命名脚本，至少做到：

- 脚本内部读取 canonical 文件。
- 输出 canonical 文件。
- round36/round46 文件只作为兼容副本。
- 典型站点不再硬编码 expected list。

典型站点应从当前 `site_metrics_consistent.csv` 动态生成：

```text
预测最好：正常评价站点中 nrmse_percent 最低 5 个
预测最差：正常评价站点中 nrmse_percent 最高 5 个
相对正确：pred/actual 接近 1 且 NRMSE 中等的站点
样本少：训练+验证 6-19 正功率样本较少的站点
```

不要再写：

```python
expected_worst = [...]
expected_best = [...]
```

---

## 八、优化 dashboard 导出

`dashboard-only` 模式下：

1. 只读取：

```text
predictions/distributed_predictions_final_full.pkl
metrics/hourly_nrmse_consistent.csv
metrics/site_metrics_consistent.csv
manifest.json
```

2. 如果 final pkl 未变化，网页 HTML 未变化，且 JSON 已存在，可跳过未变 JSON。

3. 写出 `dashboard_export_manifest.json`：

```json
{
  "source_final_full_sha256": "...",
  "source_site_metrics_sha256": "...",
  "source_hourly_metrics_sha256": "...",
  "generated_at": "...",
  "json_files": []
}
```

4. `check_dashboard_prediction_values.py` 必须验证 dashboard JSON 的 source hash 与当前 final pkl 一致。

---

## 九、全训练链路审计改为轻量版 + 深度版

`audit_training_pipeline_flow.py` 增加参数：

```bash
--level quick
--level full
```

quick 默认执行：

- 只读取 manifest 中列出的 canonical 文件。
- 只输出站点级诊断。
- 不扫描历史文件。

full 执行：

- 允许扫描更多中间产物。
- 用于排查疑难问题，不作为每次训练默认步骤。

默认主流程只跑：

```bash
python scripts/audit_training_pipeline_flow.py --level quick
```

---

## 十、重新执行并比较耗时

### 1. 全量重跑一次

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode full --force 2>&1 | tee output/pv_pipeline/logs/round55_full_force.log
```

### 2. 只重跑 dashboard

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode dashboard-only 2>&1 | tee output/pv_pipeline/logs/round55_dashboard_only.log
```

### 3. 只重跑评估

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode eval-only 2>&1 | tee output/pv_pipeline/logs/round55_eval_only.log
```

### 4. 只跑审计

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode audit-only 2>&1 | tee output/pv_pipeline/logs/round55_audit_only.log
```

查看耗时：

```bash
cat output/pv_pipeline/logs/pipeline_timing_latest.csv
```

要求输出：

```text
full 总耗时
dashboard-only 总耗时
eval-only 总耗时
audit-only 总耗时
耗时 Top 5 步骤
```

---

## 十一、验收标准

本轮必须满足：

```text
[PASS] run_full_pipeline.py 支持 --mode full/train-only/eval-only/dashboard-only/audit-only/geo-refresh
[PASS] 每一步有耗时记录
[PASS] 输出 pipeline_timing_latest.csv/json
[PASS] diagnose_geo_feature_flow 默认不再全项目 rglob
[PASS] Step 11 不再需要单独执行
[PASS] dashboard-only 不触发模型训练
[PASS] eval-only 不触发模型训练
[PASS] audit-only 不触发模型训练
[PASS] canonical 缺失仍然直接 FAIL
[PASS] dashboard check 仍然 PASS
[PASS] posttrain_validation 仍然 PASS 或仅有 S116 low confidence WARN
```

---

## 十二、生成 Round55 报告

新增：

```text
docs/Round55_训练耗时优化与增量执行报告.md
```

模板：

```markdown
# Round55 训练耗时优化与增量执行报告

## 1. 本轮目标

## 2. 修改文件

## 3. 新增执行模式

| mode | 是否重训模型 | 是否重算指标 | 是否导出 dashboard | 适用场景 |
|---|---:|---:|---:|---|

## 4. 耗时对比

| 执行方式 | 总耗时 | 说明 |
|---|---:|---|
| full --force |  | 全量重训 |
| dashboard-only |  | 只更新可视化 |
| eval-only |  | 只重算指标 |
| audit-only |  | 只做验证 |

## 5. 耗时 Top 5 步骤

## 6. Step 11 修复情况

## 7. S115/S116 链路是否仍正常

## 8. posttrain/dashboard 验证结果

## 9. 后续建议
```

---

## 十三、以后怎么用

后续不要每次都完整重训。

### 只改可视化页面

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode dashboard-only
```

### 只改指标计算或报告

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode eval-only
```

### 只验证当前结果是否可信

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode audit-only
```

### 只改站点经纬度或空间特征

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode geo-refresh
```

### 改模型训练逻辑

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml --mode full --force
```

