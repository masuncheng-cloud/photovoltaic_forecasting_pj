# Cursor 下一步修改方案 Round11：最优保护机制固化与候选管理

## 0. 当前状态

Round10 已经完成“保底最优机制”的第一版实现：

1. 已初始化：
   - `output/pv_pipeline/tables/best_predictions_eval.pkl`
   - `output/pv_pipeline/tables/best_predictions_full.pkl`
2. 当前 `final` 与 `best` 完全一致：

| 指标 | final | best |
|---|---:|---:|
| overall NRMSE（%） | 19.710496 | 19.710496 |
| MAE（MW） | 0.589320 | 0.589320 |
| RMSE（MW） | 1.204699 | 1.204699 |
| bias（%） | -1.4065 | -1.4065 |

3. Round9 specialist 已被正确拒绝：
   - best overall NRMSE = 19.7105%
   - candidate overall NRMSE = 22.0894%
   - 变差 2.3789 pp
   - final 已回退并保持 best

但是 Round10 还存在几个需要固化的问题：

| 问题 | 表现 | Round11 处理 |
---|---|---|
| 候选决策 JSON 中指标命名疑似错误 | `mae_mw` 记录成了 1.2047，实际像 RMSE | 修复指标函数，明确输出 MAE/RMSE |
| best 保护机制未完全接入总流程 | 目前需要手动调用 Round10 脚本 | 接入 `train_fixed.py` 或新增 pipeline 保护脚本 |
| rejected 候选产物仍留在主目录 | Round9 specialist pkl/csv 仍可能被误读 | 归档 rejected candidate |
| 缺少候选排行榜 | 只有单个 JSON，不方便看所有候选优劣 | 汇总所有 candidate decision |
| 报告没有清楚写“final=best保护版” | 交付时容易混淆 experimental candidate | 更新最终摘要和交付清单 |

Round11 不改模型预测结果，只把“最优保护机制”固化到工程流程中。

---

## 1. Round11 目标

### 1.1 必须完成

1. 修复 `promote_candidate_if_better_round10.py` 中指标命名/计算问题。
2. 增加候选决策汇总表。
3. 将被拒绝的 Round9 specialist 产物归档。
4. 将 best/final 保护检查接入总流程。
5. 更新最终摘要，明确当前 final 是 best 保护版本。
6. 保留并展示：
   - 每站点逐小时 NRMSE；
   - 每小时整体 NRMSE；
   - 全局整体 NRMSE；
   - 候选排行榜。

### 1.2 严禁操作

1. 不修改当前 final pkl 的预测值。
2. 不重新训练模型。
3. 不用 Round9 specialist 覆盖 final。
4. 不删除文件，只归档。
5. 不再追求通过后处理硬压 10-14 点到 10% 以下。

---

## 2. 修改一：修复候选晋级脚本的指标命名

打开：

```text
scripts/promote_candidate_if_better_round10.py
```

重点检查 `metrics()` 函数，确保输出字段如下：

```python
{
    "overall_nrmse_pct": ...,
    "midday_overall_nrmse_pct": ...,
    "mae_mw": ...,
    "rmse_mw": ...,
    "pred_actual_ratio": ...,
    "bias_pct": ...
}
```

如果当前 `mae_mw` 实际写入了 RMSE，请替换为以下稳定实现：

```python
def calc_mae(y, p):
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p)
    return float(np.mean(np.abs(y[m] - p[m]))) if m.any() else np.nan


def calc_rmse(y, p):
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p)
    return float(np.sqrt(np.mean((y[m] - p[m]) ** 2))) if m.any() else np.nan


def calc_nrmse(y, p, c):
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(c, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (c > 0)
    if not m.any():
        return np.nan
    rmse_val = float(np.sqrt(np.mean((y[m] - p[m]) ** 2)))
    cap_mean = float(np.nanmean(c[m]))
    return rmse_val / cap_mean * 100.0 if cap_mean > 0 else np.nan
```

然后 `metrics(df)` 改成：

```python
def metrics(df):
    df = ensure_hour(df)
    y = df["power_mw"]
    p = df["power_pred"]
    c = df["capacity_mw"]

    actual = float(pd.to_numeric(y, errors="coerce").sum())
    pred = float(pd.to_numeric(p, errors="coerce").sum())

    midday = df[df["hour"].isin(MIDDAY)].copy()

    return {
        "rows": int(len(df)),
        "n_sites": int(df["site_id"].nunique()),
        "actual_mwh": actual,
        "pred_mwh": pred,
        "pred_actual_ratio": pred / actual if actual > 0 else np.nan,
        "bias_pct": (pred / actual - 1.0) * 100.0 if actual > 0 else np.nan,
        "overall_nrmse_pct": calc_nrmse(y, p, c),
        "midday_overall_nrmse_pct": calc_nrmse(
            midday["power_mw"],
            midday["power_pred"],
            midday["capacity_mw"],
        ),
        "mae_mw": calc_mae(y, p),
        "rmse_mw": calc_rmse(y, p),
    }
```

`score()` 建议改为：

```python
def score(m):
    return (
        0.45 * m["midday_overall_nrmse_pct"]
        + 0.35 * m["overall_nrmse_pct"]
        + 0.10 * m["mae_mw"]
        + 0.10 * m["rmse_mw"]
    )
```

修复后重新跑一次 Round9 specialist 晋级测试，生成新的 JSON。

---

## 3. 修改二：新增候选决策汇总脚本

新建：

```text
scripts/summarize_candidate_decisions_round11.py
```

作用：

1. 扫描所有 `round10_candidate_decision_*.json`。
2. 汇总候选是否通过、整体 NRMSE、10-14 NRMSE、MAE、RMSE、拒绝原因。
3. 输出候选排行榜。

输出：

```text
output/pv_pipeline/metrics/round11_candidate_leaderboard.csv
output/pv_pipeline/docs/候选模型晋级记录_Round11.md
```

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import json
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"
METRICS.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)


def main():
    rows = []
    for path in sorted(METRICS.glob("round10_candidate_decision_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cand = data.get("candidate_metrics", {})
        best = data.get("best_metrics", {})
        rows.append({
            "candidate_name": data.get("candidate_name", path.stem.replace("round10_candidate_decision_", "")),
            "accepted": bool(data.get("accepted", False)),
            "candidate_overall_nrmse_pct": cand.get("overall_nrmse_pct"),
            "best_overall_nrmse_pct": best.get("overall_nrmse_pct"),
            "overall_improve_pp": data.get("overall_improve_pp"),
            "candidate_midday_nrmse_pct": cand.get("midday_overall_nrmse_pct"),
            "best_midday_nrmse_pct": best.get("midday_overall_nrmse_pct"),
            "candidate_mae_mw": cand.get("mae_mw"),
            "candidate_rmse_mw": cand.get("rmse_mw"),
            "best_mae_mw": best.get("mae_mw"),
            "best_rmse_mw": best.get("rmse_mw"),
            "candidate_score": data.get("candidate_score"),
            "best_score": data.get("best_score"),
            "reasons": "；".join(data.get("reasons", [])),
            "decision_file": str(path.relative_to(PROJECT_ROOT)),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(
            ["accepted", "overall_improve_pp"],
            ascending=[False, False],
        )

    out_csv = METRICS / "round11_candidate_leaderboard.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    lines = ["# 候选模型晋级记录 Round11", ""]
    lines.append("> 只有 accepted=true 的候选才允许覆盖 final/best。")
    lines.append("")
    if df.empty:
        lines.append("暂无候选决策记录。")
    else:
        lines.append("| 候选 | 是否晋级 | 候选整体 NRMSE | best 整体 NRMSE | 改善 pp | 候选 MAE | 候选 RMSE | 拒绝原因 |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
        for _, r in df.iterrows():
            lines.append(
                f"| {r['candidate_name']} | {r['accepted']} | "
                f"{r['candidate_overall_nrmse_pct']:.4f} | {r['best_overall_nrmse_pct']:.4f} | "
                f"{r['overall_improve_pp']:.4f} | "
                f"{r['candidate_mae_mw'] if pd.notna(r['candidate_mae_mw']) else ''} | "
                f"{r['candidate_rmse_mw'] if pd.notna(r['candidate_rmse_mw']) else ''} | "
                f"{r['reasons']} |"
            )

    out_md = DOCS / "候选模型晋级记录_Round11.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")

    print(f"已生成: {out_csv}")
    print(f"已生成: {out_md}")
    print(df.to_string(index=False) if not df.empty else "暂无候选记录")


if __name__ == "__main__":
    main()
```

---

## 4. 修改三：新增 rejected candidate 归档脚本

新建：

```text
scripts/archive_rejected_candidates_round11.py
```

作用：

1. 根据 `round10_candidate_decision_*.json` 判断哪些候选被拒绝。
2. 将对应候选 pkl、模型文件、对比 metrics 移入：

```text
output/pv_pipeline/archive_round11/rejected_candidates/
```

3. 保留 JSON 决策记录在主 metrics 目录，也复制一份到 archive。

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import json
import shutil
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output" / "pv_pipeline"
METRICS = OUT / "metrics"
TABLES = OUT / "tables"
ARCHIVE = OUT / "archive_round11" / "rejected_candidates"
ARCHIVE.mkdir(parents=True, exist_ok=True)

REJECTED_PATTERNS = {
    "midday_specialist_round9": [
        "distributed_predictions_midday_specialist_round9",
        "distributed_model_midday_specialist_round9",
        "round9_specialist",
    ],
}


def move_file(path: Path, rows: list[dict]):
    if not path.exists() or not path.is_file():
        return
    rel_parent = path.parent.relative_to(OUT)
    dest_dir = ARCHIVE / rel_parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    if dest.exists():
        dest.unlink()
    shutil.move(str(path), str(dest))
    rows.append({
        "original_path": str(path.relative_to(PROJECT_ROOT)),
        "archived_path": str(dest.relative_to(PROJECT_ROOT)),
        "size_mb": round(dest.stat().st_size / 1024 / 1024, 3),
    })


def main():
    rows = []
    for decision_path in sorted(METRICS.glob("round10_candidate_decision_*.json")):
        data = json.loads(decision_path.read_text(encoding="utf-8"))
        name = data.get("candidate_name", "")
        accepted = bool(data.get("accepted", False))
        if accepted:
            continue

        patterns = REJECTED_PATTERNS.get(name, [name])

        # 复制决策文件到 archive，但主目录保留。
        dest_decision_dir = ARCHIVE / "metrics"
        dest_decision_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(decision_path, dest_decision_dir / decision_path.name)

        for base in [TABLES, METRICS]:
            for path in base.iterdir():
                if not path.is_file():
                    continue
                if any(p in path.name for p in patterns):
                    move_file(path, rows)

    manifest = pd.DataFrame(rows)
    manifest_path = ARCHIVE / "archive_rejected_candidates_manifest.csv"
    manifest.to_csv(manifest_path, index=False, encoding="utf-8-sig")

    print(f"已归档 rejected candidate 文件数: {len(rows)}")
    if not manifest.empty:
        print(manifest.to_string(index=False))


if __name__ == "__main__":
    main()
```

注意：

1. 主 `final`、`best`、`MiddaySiteCalibrated` 不应被归档。
2. `round10_candidate_decision_*.json` 主目录保留，方便看拒绝原因。

---

## 5. 修改四：固化 pipeline 保护脚本

新建：

```text
scripts/run_round10_best_guard_pipeline.py
```

作用：

每次 pipeline 运行后，只需要执行这个脚本，它会完成：

1. 初始化 best。
2. 检查 final 是否比 best 差。
3. 生成 NRMSE 报告。
4. 生成候选排行榜。
5. 更新 final metrics。

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(script: str):
    cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / script)]
    print("=" * 80)
    print("运行:", " ".join(cmd))
    print("=" * 80)
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)


def main():
    run("save_current_best_round10.py")
    run("check_final_is_best_round10.py")
    run("regenerate_final_metrics_round7.py")
    run("assert_final_metrics_consistency_round7.py")
    run("compute_nrmse_reports_round10.py")
    run("summarize_candidate_decisions_round11.py")
    print("[OK] Round10/Round11 best guard pipeline completed.")


if __name__ == "__main__":
    main()
```

---

## 6. 修改五：更新最终摘要和交付清单

修改：

```text
scripts/update_project_md_metrics.py
```

在最终报告中增加一节：

```text
### 保底最优机制

当前 final 由 best_predictions_eval.pkl / best_predictions_full.pkl 保护。
任何新候选必须经过 promote_candidate_if_better_round10.py 判断。
若候选整体 NRMSE 未优于 best，自动拒绝并回退。

当前 best 整体 NRMSE = 19.7105%。
Round9 Specialist 整体 NRMSE = 22.0894%，已拒绝。

每次运行均输出：
- round10_site_hour_nrmse.csv：站点 × 小时 NRMSE；
- round10_hour_overall_nrmse.csv：每小时整体 NRMSE；
- round10_overall_nrmse_summary.csv：全局整体 NRMSE；
- round11_candidate_leaderboard.csv：候选晋级排行榜。
```

同时更新：

```text
output/pv_pipeline/docs/最终交付文件清单_Round8.md
```

加入 Round10/Round11 文件：

```text
output/pv_pipeline/tables/best_predictions_eval.pkl
output/pv_pipeline/tables/best_predictions_full.pkl
output/pv_pipeline/metrics/round10_site_hour_nrmse.csv
output/pv_pipeline/metrics/round10_hour_overall_nrmse.csv
output/pv_pipeline/metrics/round10_overall_nrmse_summary.csv
output/pv_pipeline/metrics/round10_final_vs_best_nrmse.csv
output/pv_pipeline/metrics/round11_candidate_leaderboard.csv
output/pv_pipeline/docs/候选模型晋级记录_Round11.md
```

---

## 7. 修改六：更新 train_fixed.py

打开：

```text
scripts/train_fixed.py
```

在完整流程最后加入：

```python
"run_round10_best_guard_pipeline.py",
```

如果不希望每次训练都自动归档 rejected candidates，归档脚本不要放进默认流程。

建议手动执行：

```bash
python scripts/archive_rejected_candidates_round11.py
```

---

## 8. Cursor 执行顺序

### 8.1 修复指标命名并重新生成候选决策

```bash
python scripts/save_current_best_round10.py

python scripts/promote_candidate_if_better_round10.py \
  --candidate-eval output/pv_pipeline/tables/distributed_predictions_midday_specialist_round9_eval.pkl \
  --candidate-full output/pv_pipeline/tables/distributed_predictions_midday_specialist_round9_full.pkl \
  --name midday_specialist_round9 \
  --min-overall-improve-pp 0.10
```

### 8.2 生成报告和排行榜

```bash
python scripts/run_round10_best_guard_pipeline.py
python scripts/summarize_candidate_decisions_round11.py
```

### 8.3 归档已拒绝候选

```bash
python scripts/archive_rejected_candidates_round11.py
```

### 8.4 归档后再次检查

```bash
python scripts/run_round10_best_guard_pipeline.py
python scripts/check_round8_final_package.py
python scripts/update_project_md_metrics.py
```

---

## 9. 验收标准

### 9.1 final 必须等于 best 或优于 best

检查：

```text
output/pv_pipeline/metrics/round10_final_is_best_check.csv
```

必须：

```text
status = ok
```

且：

```text
final_overall_nrmse_pct <= best_overall_nrmse_pct
```

### 9.2 Round9 specialist 必须被拒绝

检查：

```text
output/pv_pipeline/metrics/round10_candidate_decision_midday_specialist_round9.json
```

必须：

```json
"accepted": false
```

拒绝原因应包含：

```text
整体 NRMSE 改善不足
```

### 9.3 候选排行榜存在

必须生成：

```text
output/pv_pipeline/metrics/round11_candidate_leaderboard.csv
output/pv_pipeline/docs/候选模型晋级记录_Round11.md
```

### 9.4 Round10 NRMSE 报告完整

必须保留：

```text
output/pv_pipeline/metrics/round10_site_hour_nrmse.csv
output/pv_pipeline/metrics/round10_hour_overall_nrmse.csv
output/pv_pipeline/metrics/round10_overall_nrmse_summary.csv
```

其中：

```text
round10_site_hour_nrmse.csv
```

必须包含站点逐小时。

```text
round10_overall_nrmse_summary.csv
```

必须包含整体 NRMSE。

### 9.5 rejected candidate 归档

Round9 specialist 的以下文件不应继续留在主 `tables/metrics` 目录：

```text
distributed_predictions_midday_specialist_round9*.pkl
distributed_model_midday_specialist_round9*.pkl
round9_specialist*.csv
```

应移动到：

```text
output/pv_pipeline/archive_round11/rejected_candidates/
```

---

## 10. Round11 完成后的结论模板

```text
Round11 未修改 final 预测结果，仅固化最优保护机制。

1. 已修复候选晋级脚本中的 MAE/RMSE 指标命名问题；
2. 已生成候选排行榜；
3. Round9 Specialist 因整体 NRMSE 劣于 best 被拒绝；
4. final 与 best 保持一致，overall NRMSE = 19.7105%；
5. 已输出站点逐小时 NRMSE、每小时整体 NRMSE、全局整体 NRMSE；
6. 已将 rejected candidate 归档，避免交付误读；
7. 后续任何新实验必须通过 promote_candidate_if_better_round10.py 晋级，才能覆盖 final。
```

---

## 11. 后续如果还要继续优化

在当前无新增数据条件下，不建议继续做大范围自动后处理。

后续可以尝试的方向只能作为候选，不得直接覆盖 final：

1. 低功率站点分组模型；
2. S012/S055/S050/S032 单独模型；
3. 基于历史同小时均值的 station profile 模型；
4. 预测区间或分位数模型；
5. 评估口径区分正常站点与长期低效站点。

每一种都必须输出候选 pkl，然后走 Round10 晋级脚本。

