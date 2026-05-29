# Cursor执行方案 Round47：训练后自动重算 consistent 指标并清理过期文件

## 目标

本轮做项目流程收口，不以继续调模型为主。

需要完成两件事：

1. 把“重新训练后自动重新计算 `round46_hourly_nrmse_consistent.csv`”接入训练主流程，保证可视化页面始终读取最新训练结果。
2. 清理项目中前面多轮修改留下的残留脚本、旧结果文件和过时训练文件，避免后续 Cursor 或训练脚本误读旧产物。

本轮不改变模型结构、不改变最终预测列口径、不重新定义 NRMSE。

---

## 一、必须保留的核心口径

### 1. 最终预测列

最终预测列统一使用：

```text
power_pred_final
```

不要再回退到：

```text
power_pred_cal
power_pred_raw
power_pred_round*
```

除非这些列只是作为诊断对比列存在。

### 2. 逐小时站点平均 NRMSE 口径

必须保持 Round46 的正确口径：

```text
1. 测试集 split == "test"
2. 小时 6-19
3. 对每个 site_id、hour 分别计算 RMSE
4. NRMSE_site_hour = RMSE_site_hour / capacity_mw × 100%
5. 同一 hour 下，对所有站点的 NRMSE_site_hour 取平均
```

不要回到旧错误口径：

```text
所有站点混在一起按 hour groupby，然后除以 capacity_median 或其他全局容量
```

---

## 二、接入训练主流程

### 1. 新增统一后训练收口脚本

新建脚本：

```text
scripts/post_training_finalize_outputs.py
```

这个脚本作为每次训练完成后的唯一收口入口，负责：

1. 检查最终预测文件是否存在。
2. 检查 `power_pred_final` 是否存在。
3. 重新计算逐小时 consistent 指标。
4. 重新导出可视化 dashboard 数据。
5. 更新 dashboard 自动刷新 stamp。
6. 执行 dashboard 一致性检查。
7. 输出一份本次训练产物索引。

建议实现结构：

```python
from pathlib import Path
import subprocess
import sys
import json
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pv_pipeline"
METRICS = OUT / "metrics"
DOCS = OUT / "docs"
DASHBOARD = OUT / "interactive_dashboard"


def run_step(name, cmd, required=True):
    print(f"\n[STEP] {name}")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, text=True)
    if result.returncode != 0 and required:
        raise RuntimeError(f"{name} failed with code {result.returncode}")
    return result.returncode


def main():
    stamp = {
        "finalized_at": datetime.now().isoformat(timespec="seconds"),
        "steps": [],
    }

    steps = [
        ("recompute_hourly_nrmse_consistent", [sys.executable, "scripts/round46_recompute_hourly_nrmse_consistent.py"]),
        ("export_interactive_dashboard_data", [sys.executable, "scripts/export_interactive_dashboard_data.py"]),
        ("update_dashboard_after_training", [sys.executable, "scripts/update_dashboard_after_training.py"]),
        ("check_dashboard_auto_update_stamp", [sys.executable, "scripts/check_dashboard_auto_update_stamp.py"]),
    ]

    for name, cmd in steps:
        code = run_step(name, cmd, required=True)
        stamp["steps"].append({"name": name, "returncode": code})

    # dashboard 回归检查脚本不同轮次可能名称不同，按存在性选择
    candidates = [
        ROOT / "scripts" / "round44_dashboard_regression_check.py",
        ROOT / "scripts" / "dashboard_regression_check.py",
    ]
    for script in candidates:
        if script.exists():
            code = run_step("dashboard_regression_check", [sys.executable, str(script.relative_to(ROOT))], required=True)
            stamp["steps"].append({"name": "dashboard_regression_check", "script": str(script), "returncode": code})
            break

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "post_training_finalize_stamp.json").write_text(
        json.dumps(stamp, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n[PASS] post training finalize completed")


if __name__ == "__main__":
    main()
```

注意：如果项目已有类似 `post_training_finalize`、`update_dashboard_after_training` 总入口，不要重复造轮子；优先复用并补齐缺失步骤。

---

### 2. 将收口脚本接入训练主入口

检查项目训练入口，常见文件可能包括：

```text
run_pipeline.py
scripts/run_full_training.py
scripts/train_pipeline.py
scripts/run_round44_training_logic_fix.py
scripts/run_round36_training.py
```

使用命令查找：

```bash
grep -R "export_interactive_dashboard_data\|update_dashboard_after_training\|训练完成\|main()" -n scripts *.py
```

找到当前真正使用的完整训练入口后，在训练成功、最终预测文件写出之后添加：

```python
from scripts.post_training_finalize_outputs import main as finalize_outputs

# 训练成功并写出 final pkl 后执行
finalize_outputs()
```

如果训练入口不适合直接 import，则用 subprocess：

```python
subprocess.run(
    [sys.executable, "scripts/post_training_finalize_outputs.py"],
    cwd=ROOT,
    check=True,
)
```

要求：

- 只有训练成功后才执行。
- 如果收口失败，训练流程应返回失败，不能静默跳过。
- 日志中必须明确写出：

```text
[PASS] post training finalize completed
```

---

### 3. 检查重新训练后是否自动更新

新增验证脚本：

```text
scripts/check_post_training_auto_finalize.py
```

检查内容：

1. `output/pv_pipeline/metrics/round46_hourly_nrmse_consistent.csv` 存在。
2. `output/pv_pipeline/interactive_dashboard/hourly_prediction_summary.json` 存在。
3. `output/pv_pipeline/docs/post_training_finalize_stamp.json` 存在。
4. 三个文件的修改时间晚于本次训练开始时间。
5. JSON 中 10-14 点站点平均 NRMSE 不是旧错误口径的 31%-37%。
6. `metadata.json` 中预测列为 `power_pred_final`。

伪代码：

```python
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pv_pipeline"

hourly_csv = OUT / "metrics" / "round46_hourly_nrmse_consistent.csv"
hourly_json = OUT / "interactive_dashboard" / "hourly_prediction_summary.json"
stamp = OUT / "docs" / "post_training_finalize_stamp.json"
metadata = OUT / "interactive_dashboard" / "metadata.json"

for p in [hourly_csv, hourly_json, stamp, metadata]:
    assert p.exists(), f"missing {p}"

df = pd.read_csv(hourly_csv)
focus = df[df["hour"].between(10, 14)]
assert not focus.empty
assert focus["site_avg_nrmse_pct"].max() < 25, "hourly site NRMSE seems to use old wrong口径"

meta = json.loads(metadata.read_text(encoding="utf-8"))
assert meta.get("prediction_column") == "power_pred_final"

print("[PASS] post training auto finalize check passed")
```

---

## 三、清理过期文件和修改残留

### 1. 先生成清理清单，不直接删除

新增脚本：

```text
scripts/audit_stale_round_artifacts.py
```

输出：

```text
output/pv_pipeline/docs/stale_artifacts_audit.csv
output/pv_pipeline/docs/stale_artifacts_audit.md
```

扫描范围：

```text
scripts/
output/pv_pipeline/
docs/
stages/05_visualization/
```

重点识别：

- `round1` 到 `round45` 的临时诊断脚本。
- 旧的 `*_fixed.csv`、`*_old.csv`、`*_backup.*`。
- 旧的 `power_pred_cal`、`power_pred_raw` 相关导出文件。
- 重复 dashboard 检查脚本。
- 早期 `hourly_relative_error`、`mape` 相关文件。
- 不再使用的执行报告中间文件。

注意：先只生成清单，不删除。

---

### 2. 文件分类

清理清单中每个文件给出分类：

| 分类 | 处理方式 |
|---|---|
| `keep_core` | 核心训练、导出、评估、可视化文件，必须保留 |
| `keep_latest_report` | 最新报告和最终技术文档，保留 |
| `archive_round_artifact` | 旧轮次诊断/报告/临时结果，移动到归档目录 |
| `delete_cache` | 可重复生成的缓存文件，可删除 |
| `manual_review` | 不确定是否仍被引用，需要人工确认 |

不要直接删除 `manual_review`。

---

### 3. 建立归档目录

创建：

```text
archive/round_artifacts_before_round47/
```

将旧轮次文件移动到该目录，而不是直接删除。

建议目录结构：

```text
archive/round_artifacts_before_round47/
  scripts/
  metrics/
  docs/
  dashboard/
```

---

### 4. 安全清理脚本

新增：

```text
scripts/archive_stale_round_artifacts.py
```

要求：

- 默认 dry-run。
- 只有传入 `--apply` 才真正移动文件。
- 不使用永久删除。
- 移动前写出 manifest：

```text
archive/round_artifacts_before_round47/archive_manifest.csv
```

命令：

```bash
python scripts/audit_stale_round_artifacts.py
python scripts/archive_stale_round_artifacts.py
python scripts/archive_stale_round_artifacts.py --apply
```

---

## 四、推荐保留文件白名单

以下文件必须保留：

```text
scripts/export_interactive_dashboard_data.py
scripts/update_dashboard_after_training.py
scripts/post_training_finalize_outputs.py
scripts/round46_recompute_hourly_nrmse_consistent.py
scripts/check_dashboard_auto_update_stamp.py
scripts/check_post_training_auto_finalize.py
```

如果存在当前训练主入口，也必须保留，例如：

```text
scripts/run_full_training.py
scripts/run_pipeline.py
run_pipeline.py
```

以下输出必须保留：

```text
output/pv_pipeline/metrics/round46_hourly_nrmse_consistent.csv
output/pv_pipeline/metrics/round46_site_hour_nrmse_consistent.csv
output/pv_pipeline/interactive_dashboard/
output/pv_pipeline/docs/post_training_finalize_stamp.json
光伏功率预测项目.md
```

---

## 五、执行顺序

请在 Cursor 中按顺序执行：

### Step 1：确认训练入口

```bash
grep -R "def main\|if __name__ == .__main__.\|export_interactive_dashboard_data\|update_dashboard_after_training" -n scripts *.py
```

确认当前真正用于完整训练的入口脚本。

---

### Step 2：新增后训练收口脚本

创建并完善：

```text
scripts/post_training_finalize_outputs.py
scripts/check_post_training_auto_finalize.py
```

---

### Step 3：接入训练主流程

在完整训练入口中，最终预测文件写出后调用：

```bash
python scripts/post_training_finalize_outputs.py
```

---

### Step 4：执行一次非训练验证

先不重新训练，只执行：

```bash
python scripts/post_training_finalize_outputs.py
python scripts/check_post_training_auto_finalize.py
```

确保自动刷新链路可跑通。

---

### Step 5：生成过期文件清单

```bash
python scripts/audit_stale_round_artifacts.py
```

检查：

```text
output/pv_pipeline/docs/stale_artifacts_audit.md
```

确认没有把核心文件误标为可归档。

---

### Step 6：归档旧文件

先 dry-run：

```bash
python scripts/archive_stale_round_artifacts.py
```

确认无误后：

```bash
python scripts/archive_stale_round_artifacts.py --apply
```

---

### Step 7：完整训练验证

执行当前项目的完整训练命令。

训练完成后必须自动出现：

```text
[PASS] post training finalize completed
```

然后执行：

```bash
python scripts/check_post_training_auto_finalize.py
python scripts/check_dashboard_auto_update_stamp.py
python scripts/round44_dashboard_regression_check.py
```

如果 `round44_dashboard_regression_check.py` 已被归档或改名，则使用当前保留的 dashboard regression check 脚本。

---

## 六、验收标准

### 1. 自动更新验收

完整训练结束后，以下文件必须是最新修改时间：

```text
output/pv_pipeline/metrics/round46_hourly_nrmse_consistent.csv
output/pv_pipeline/interactive_dashboard/hourly_prediction_summary.json
output/pv_pipeline/interactive_dashboard/city_series.json
output/pv_pipeline/interactive_dashboard/site_series/*.json
output/pv_pipeline/docs/post_training_finalize_stamp.json
```

### 2. 数据口径验收

逐小时预测结果表中：

- 只显示 4 列。
- 10-14 点站点平均 NRMSE 不得回到 31%-37% 的旧错误口径。
- 城市 NRMSE 与 `round46_hourly_nrmse_consistent.csv` 一致。

### 3. 可视化验收

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

强制刷新：

```text
Ctrl + Shift + R
```

检查：

- 全市曲线正常显示。
- 单站点曲线正常显示。
- 典型站点按钮正常切换。
- 四季最佳日按钮正常切换。
- 页面不显示旧数据警告。
- 页面不读取 future。

### 4. 清理验收

清理后：

- 项目根目录不再散落大量 Round 临时报告。
- `scripts/` 中不再存在明显重复或已废弃的 Round 临时脚本。
- 被清理文件均进入 `archive/round_artifacts_before_round47/`，没有永久删除。
- 完整训练和 dashboard 检查仍全部 PASS。

---

## 七、注意事项

1. 清理时不要删除原始数据。
2. 清理时不要删除任务书、最终报告、当前可视化页面、当前训练主入口。
3. 不要把 `round46_recompute_hourly_nrmse_consistent.py` 归档；它现在是训练后自动刷新链路的一部分。
4. 如果后续不想保留 Round46 名称，可以新建通用脚本名：

```text
scripts/compute_hourly_nrmse_consistent.py
```

然后让 `round46_recompute_hourly_nrmse_consistent.py` 只作为兼容 wrapper。

推荐最终改成通用脚本名，避免项目长期依赖 Round 编号。

