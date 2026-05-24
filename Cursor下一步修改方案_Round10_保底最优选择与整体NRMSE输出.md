# Cursor 下一步修改方案 Round10：保底最优选择与整体 NRMSE 输出

## 0. 当前结论

当前项目在既有数据和现有特征条件下，10-14 点已经接近当前模型能力上限。

当前最优 final 结果为：

| 小时 | 当前最优站点平均 NRMSE |
|---:|---:|
| 10 | 13.29% |
| 11 | 14.68% |
| 12 | 15.36% |
| 13 | 15.31% |
| 14 | 13.51% |

Round9 的中午专用模型没有超过当前最优结果，因此不能进入 final。

本轮 Round10 的目标不是盲目继续压低指标，而是建立一个**保底最优机制**：

```text
任何新模型/新修正/新候选
→ 先生成候选
→ 与当前最优 final 对比
→ 只有明确更优才替换
→ 否则自动回退当前最优
```

这样可以保证后续每次实验都不会把结果越改越差。

---

## 1. 本轮目标

### 1.1 主目标

建立“当前最优结果保护机制”，确保：

1. 当前 final 永远不被更差候选覆盖。
2. 新候选如果 10-14 点变差，自动回退。
3. 新候选如果整体 NRMSE、MAE、RMSE 明显变差，自动回退。
4. 每次运行都输出：
   - 每个站点的逐小时 NRMSE；
   - 全部站点整体 NRMSE；
   - 每小时整体 NRMSE；
   - 每个候选与当前最优的对比。

### 1.2 不做的事

1. 暂不增加新数据源。
2. 不继续使用 test 集调参。
3. 不自动修改站点容量。
4. 不自动剔除异常站点。
5. 不允许更差候选覆盖 final。

---

## 2. 当前最优版本定义

当前最优版本固定为：

```text
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
```

建议先备份为：

```text
output/pv_pipeline/tables/best_predictions_eval.pkl
output/pv_pipeline/tables/best_predictions_full.pkl
```

后续所有候选都和 `best_predictions_eval.pkl` 比较。

---

## 3. 修改一：新增当前最优版本备份脚本

新建：

```text
scripts/save_current_best_round10.py
```

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import shutil
import json
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

FINAL_EVAL = TABLES / "distributed_predictions_final_eval.pkl"
FINAL_FULL = TABLES / "distributed_predictions_final_full.pkl"
BEST_EVAL = TABLES / "best_predictions_eval.pkl"
BEST_FULL = TABLES / "best_predictions_full.pkl"
BEST_META = METRICS / "round10_best_version_meta.json"


def main():
    if not FINAL_EVAL.exists():
        raise FileNotFoundError(FINAL_EVAL)
    if not FINAL_FULL.exists():
        raise FileNotFoundError(FINAL_FULL)

    # 如果 best 不存在，初始化 best；如果已存在，不覆盖，避免误把差结果保存成 best。
    initialized = False
    if not BEST_EVAL.exists():
        shutil.copy2(FINAL_EVAL, BEST_EVAL)
        initialized = True
    if not BEST_FULL.exists():
        shutil.copy2(FINAL_FULL, BEST_FULL)
        initialized = True

    meta = {
        "best_eval": str(BEST_EVAL.relative_to(PROJECT_ROOT)),
        "best_full": str(BEST_FULL.relative_to(PROJECT_ROOT)),
        "initialized_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if initialized else None,
        "note": "best_predictions_* 是当前最优保护版本，后续候选只有更优才允许覆盖。",
    }
    BEST_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[OK] current best initialized/protected")
    print(BEST_META)


if __name__ == "__main__":
    main()
```

---

## 4. 修改二：新增统一 NRMSE 计算脚本

新建：

```text
scripts/compute_nrmse_reports_round10.py
```

作用：

1. 输出每个站点逐小时 NRMSE。
2. 输出每小时整体 NRMSE。
3. 输出全局整体 NRMSE。
4. 输出当前 final 与 best 的对比。

输出文件：

```text
output/pv_pipeline/metrics/round10_site_hour_nrmse.csv
output/pv_pipeline/metrics/round10_hour_overall_nrmse.csv
output/pv_pipeline/metrics/round10_overall_nrmse_summary.csv
output/pv_pipeline/metrics/round10_final_vs_best_nrmse.csv
```

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

FINAL_EVAL = TABLES / "distributed_predictions_final_eval.pkl"
BEST_EVAL = TABLES / "best_predictions_eval.pkl"


def ensure_hour(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour
    if "date" not in out.columns and "time" in out.columns:
        out["date"] = out["time"].dt.date
    return out


def nrmse(y, p, c) -> float:
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(c, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (c > 0)
    if not m.any():
        return np.nan
    rmse = float(np.sqrt(np.mean((y[m] - p[m]) ** 2)))
    cap = float(np.nanmean(c[m]))
    return rmse / cap * 100.0 if cap > 0 else np.nan


def mae(y, p) -> float:
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p)
    return float(np.mean(np.abs(y[m] - p[m]))) if m.any() else np.nan


def rmse(y, p) -> float:
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p)
    return float(np.sqrt(np.mean((y[m] - p[m]) ** 2))) if m.any() else np.nan


def overall_summary(df: pd.DataFrame, label: str) -> dict:
    y = pd.to_numeric(df["power_mw"], errors="coerce")
    p = pd.to_numeric(df["power_pred"], errors="coerce")
    c = pd.to_numeric(df["capacity_mw"], errors="coerce")
    actual = float(y.sum())
    pred = float(p.sum())
    return {
        "version": label,
        "rows": int(len(df)),
        "n_sites": int(df["site_id"].nunique()),
        "actual_mwh": round(actual, 4),
        "pred_mwh": round(pred, 4),
        "pred_actual_ratio": round(pred / actual, 6) if actual > 0 else np.nan,
        "bias_pct": round((pred / actual - 1.0) * 100.0, 4) if actual > 0 else np.nan,
        "mae_mw": round(mae(y, p), 6),
        "rmse_mw": round(rmse(y, p), 6),
        "overall_nrmse_pct": round(nrmse(y, p, c), 6),
    }


def build_reports(df: pd.DataFrame, label: str):
    site_hour_rows = []
    for (sid, h), g in df.groupby(["site_id", "hour"]):
        site_hour_rows.append({
            "version": label,
            "site_id": sid,
            "hour": int(h),
            "rows": int(len(g)),
            "capacity_mw": round(float(pd.to_numeric(g["capacity_mw"], errors="coerce").mean()), 6),
            "site_hour_nrmse_pct": round(nrmse(g["power_mw"], g["power_pred"], g["capacity_mw"]), 6),
            "mae_mw": round(mae(g["power_mw"], g["power_pred"]), 6),
            "rmse_mw": round(rmse(g["power_mw"], g["power_pred"]), 6),
        })

    hour_rows = []
    for h, g in df.groupby("hour"):
        # 每小时整体 NRMSE：将该小时所有站点样本合并计算。
        hour_rows.append({
            "version": label,
            "hour": int(h),
            "rows": int(len(g)),
            "n_sites": int(g["site_id"].nunique()),
            "hour_overall_nrmse_pct": round(nrmse(g["power_mw"], g["power_pred"], g["capacity_mw"]), 6),
            "hour_mae_mw": round(mae(g["power_mw"], g["power_pred"]), 6),
            "hour_rmse_mw": round(rmse(g["power_mw"], g["power_pred"]), 6),
        })

    return pd.DataFrame(site_hour_rows), pd.DataFrame(hour_rows), overall_summary(df, label)


def main():
    if not FINAL_EVAL.exists():
        raise FileNotFoundError(FINAL_EVAL)
    final = ensure_hour(safe_pickle_load(FINAL_EVAL))

    all_site_hour = []
    all_hour = []
    all_summary = []

    sh, hh, ss = build_reports(final, "final")
    all_site_hour.append(sh)
    all_hour.append(hh)
    all_summary.append(ss)

    if BEST_EVAL.exists():
        best = ensure_hour(safe_pickle_load(BEST_EVAL))
        sh, hh, ss = build_reports(best, "best")
        all_site_hour.append(sh)
        all_hour.append(hh)
        all_summary.append(ss)

    site_hour = pd.concat(all_site_hour, ignore_index=True)
    hour = pd.concat(all_hour, ignore_index=True)
    summary = pd.DataFrame(all_summary)

    site_hour.to_csv(METRICS / "round10_site_hour_nrmse.csv", index=False, encoding="utf-8-sig")
    hour.to_csv(METRICS / "round10_hour_overall_nrmse.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(METRICS / "round10_overall_nrmse_summary.csv", index=False, encoding="utf-8-sig")

    if {"final", "best"}.issubset(set(summary["version"])):
        f = summary[summary["version"] == "final"].iloc[0]
        b = summary[summary["version"] == "best"].iloc[0]
        cmp = pd.DataFrame([{
            "metric": "overall_nrmse_pct",
            "best": b["overall_nrmse_pct"],
            "final": f["overall_nrmse_pct"],
            "delta_final_minus_best": f["overall_nrmse_pct"] - b["overall_nrmse_pct"],
        }, {
            "metric": "mae_mw",
            "best": b["mae_mw"],
            "final": f["mae_mw"],
            "delta_final_minus_best": f["mae_mw"] - b["mae_mw"],
        }, {
            "metric": "rmse_mw",
            "best": b["rmse_mw"],
            "final": f["rmse_mw"],
            "delta_final_minus_best": f["rmse_mw"] - b["rmse_mw"],
        }])
        cmp.to_csv(METRICS / "round10_final_vs_best_nrmse.csv", index=False, encoding="utf-8-sig")

    print("[OK] Round10 NRMSE reports generated.")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
```

---

## 5. 修改三：新增候选安全晋级脚本

新建：

```text
scripts/promote_candidate_if_better_round10.py
```

作用：

1. 输入候选 full/eval。
2. 与当前 best 比较。
3. 如果候选更优，则更新 final 和 best。
4. 如果候选更差，则保留 best，不覆盖 final。

默认候选可以是：

```text
distributed_predictions_midday_specialist_round9_eval.pkl
distributed_predictions_midday_specialist_round9_full.pkl
```

但以后任何新候选都可以复用这个脚本。

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import shutil
import argparse
import json
from datetime import datetime
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

BEST_EVAL = TABLES / "best_predictions_eval.pkl"
BEST_FULL = TABLES / "best_predictions_full.pkl"
FINAL_EVAL = TABLES / "distributed_predictions_final_eval.pkl"
FINAL_FULL = TABLES / "distributed_predictions_final_full.pkl"

MIDDAY = [10, 11, 12, 13, 14]


def ensure_hour(df):
    out = df.copy()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour
    return out


def nrmse(y, p, c):
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(c, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (c > 0)
    if not m.any():
        return np.nan
    return float(np.sqrt(np.mean((y[m] - p[m]) ** 2)) / np.nanmean(c[m]) * 100.0)


def rmse(y, p):
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p)
    return float(np.sqrt(np.mean((y[m] - p[m]) ** 2))) if m.any() else np.nan


def mae(y, p):
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p)
    return float(np.mean(np.abs(y[m] - p[m]))) if m.any() else np.nan


def metrics(df):
    df = ensure_hour(df)
    y = df["power_mw"]
    p = df["power_pred"]
    c = df["capacity_mw"]

    out = {
        "overall_nrmse_pct": nrmse(y, p, c),
        "mae_mw": mae(y, p),
        "rmse_mw": rmse(y, p),
    }

    midday = df[df["hour"].isin(MIDDAY)].copy()
    out["midday_overall_nrmse_pct"] = nrmse(midday["power_mw"], midday["power_pred"], midday["capacity_mw"])

    # 每小时整体 NRMSE
    for h in MIDDAY:
        sub = df[df["hour"] == h]
        out[f"h{h}_overall_nrmse_pct"] = nrmse(sub["power_mw"], sub["power_pred"], sub["capacity_mw"])

    return out


def score(m):
    # 分数越低越好；同时关注整体和 10-14。
    return (
        0.45 * m["midday_overall_nrmse_pct"]
        + 0.35 * m["overall_nrmse_pct"]
        + 0.10 * m["mae_mw"]
        + 0.10 * m["rmse_mw"]
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-eval", required=True)
    parser.add_argument("--candidate-full", required=True)
    parser.add_argument("--name", default="candidate")
    parser.add_argument("--min-midday-improve-pp", type=float, default=0.20)
    parser.add_argument("--max-overall-worse-pp", type=float, default=0.05)
    args = parser.parse_args()

    cand_eval = Path(args.candidate_eval)
    cand_full = Path(args.candidate_full)
    if not cand_eval.is_absolute():
        cand_eval = PROJECT_ROOT / cand_eval
    if not cand_full.is_absolute():
        cand_full = PROJECT_ROOT / cand_full

    if not BEST_EVAL.exists() or not BEST_FULL.exists():
        raise FileNotFoundError("请先运行 save_current_best_round10.py 初始化 best_predictions_*")
    if not cand_eval.exists():
        raise FileNotFoundError(cand_eval)
    if not cand_full.exists():
        raise FileNotFoundError(cand_full)

    best_df = safe_pickle_load(BEST_EVAL)
    cand_df = safe_pickle_load(cand_eval)

    best_m = metrics(best_df)
    cand_m = metrics(cand_df)

    best_score = score(best_m)
    cand_score = score(cand_m)

    midday_improve = best_m["midday_overall_nrmse_pct"] - cand_m["midday_overall_nrmse_pct"]
    overall_worse = cand_m["overall_nrmse_pct"] - best_m["overall_nrmse_pct"]

    accept = True
    reasons = []

    if midday_improve < args.min_midday_improve_pp:
        accept = False
        reasons.append(
            f"midday 改善不足: {midday_improve:.4f} pp < {args.min_midday_improve_pp:.4f} pp"
        )

    if overall_worse > args.max_overall_worse_pp:
        accept = False
        reasons.append(
            f"整体 NRMSE 恶化过多: {overall_worse:.4f} pp > {args.max_overall_worse_pp:.4f} pp"
        )

    if cand_score >= best_score:
        accept = False
        reasons.append(f"综合 score 未改善: candidate={cand_score:.6f} >= best={best_score:.6f}")

    decision = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "candidate_name": args.name,
        "accepted": accept,
        "reasons": reasons,
        "best_metrics": best_m,
        "candidate_metrics": cand_m,
        "best_score": best_score,
        "candidate_score": cand_score,
        "midday_improve_pp": midday_improve,
        "overall_worse_pp": overall_worse,
    }

    out_json = METRICS / f"round10_candidate_decision_{args.name}.json"
    out_json.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")

    if accept:
        shutil.copy2(cand_eval, FINAL_EVAL)
        shutil.copy2(cand_full, FINAL_FULL)
        shutil.copy2(cand_eval, BEST_EVAL)
        shutil.copy2(cand_full, BEST_FULL)
        print(f"[ACCEPT] {args.name} promoted to final and best.")
    else:
        # 回退 final 到 best，保证当前版本永远是最优保护版本。
        shutil.copy2(BEST_EVAL, FINAL_EVAL)
        shutil.copy2(BEST_FULL, FINAL_FULL)
        print(f"[REJECT] {args.name} rejected. final rolled back to best.")
        for r in reasons:
            print(" -", r)

    print(out_json)


if __name__ == "__main__":
    main()
```

---

## 6. 修改四：新增“当前是否最优”检查脚本

新建：

```text
scripts/check_final_is_best_round10.py
```

作用：

1. 比较 final 和 best。
2. 如果 final 比 best 差，立即回退。
3. 输出检查结果。

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import shutil
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

FINAL_EVAL = TABLES / "distributed_predictions_final_eval.pkl"
FINAL_FULL = TABLES / "distributed_predictions_final_full.pkl"
BEST_EVAL = TABLES / "best_predictions_eval.pkl"
BEST_FULL = TABLES / "best_predictions_full.pkl"


def nrmse(df):
    y = pd.to_numeric(df["power_mw"], errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(df["power_pred"], errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(df["capacity_mw"], errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (c > 0)
    return float(np.sqrt(np.mean((y[m] - p[m]) ** 2)) / np.nanmean(c[m]) * 100.0)


def main():
    if not BEST_EVAL.exists():
        raise FileNotFoundError(BEST_EVAL)

    final = safe_pickle_load(FINAL_EVAL)
    best = safe_pickle_load(BEST_EVAL)

    final_n = nrmse(final)
    best_n = nrmse(best)

    if final_n > best_n + 1e-6:
        shutil.copy2(BEST_EVAL, FINAL_EVAL)
        shutil.copy2(BEST_FULL, FINAL_FULL)
        status = "rolled_back"
    else:
        status = "ok"

    out = pd.DataFrame([{
        "final_overall_nrmse_pct": final_n,
        "best_overall_nrmse_pct": best_n,
        "status": status,
    }])
    out.to_csv(METRICS / "round10_final_is_best_check.csv", index=False, encoding="utf-8-sig")
    print(out.to_string(index=False))

    if status == "rolled_back":
        raise SystemExit("[WARN] final was worse than best, rolled back.")


if __name__ == "__main__":
    main()
```

---

## 7. 修改五：更新 final 选择器原则

在：

```text
scripts/select_final_prediction_by_guard.py
```

保留当前逻辑，但新增注释和保护：

```python
# Round10 原则：
# select_final_prediction_by_guard.py 可以生成 candidate final，
# 但最终是否替换 best，必须由 promote_candidate_if_better_round10.py 决定。
# 不允许任何实验候选直接永久覆盖 best_predictions_*。
```

如果当前脚本会直接写 `distributed_predictions_final_eval.pkl`，可以保留，但必须在后续立刻运行：

```bash
python scripts/promote_candidate_if_better_round10.py ...
```

或者：

```bash
python scripts/check_final_is_best_round10.py
```

确保变差时回退。

---

## 8. 修改六：Round9 specialist 作为候选，不直接进 final

Round9 中午专用模型输出：

```text
distributed_predictions_midday_specialist_round9_eval.pkl
distributed_predictions_midday_specialist_round9_full.pkl
```

不要直接覆盖 final。

用 Round10 晋级脚本判断：

```bash
python scripts/promote_candidate_if_better_round10.py \
  --candidate-eval output/pv_pipeline/tables/distributed_predictions_midday_specialist_round9_eval.pkl \
  --candidate-full output/pv_pipeline/tables/distributed_predictions_midday_specialist_round9_full.pkl \
  --name midday_specialist_round9 \
  --min-midday-improve-pp 0.20 \
  --max-overall-worse-pp 0.05
```

如果 specialist 比 best 差，脚本会自动：

```text
拒绝候选
final 回退到 best
保存拒绝原因
```

---

## 9. 修改七：更新报告生成

在：

```text
scripts/update_project_md_metrics.py
```

加入 Round10 输出说明：

```text
Round10 保底机制：
- 当前 final 由 best_predictions_eval.pkl 保护；
- 新候选只有在整体 NRMSE 和 10-14 点 NRMSE 均不劣化时才允许晋级；
- 每次输出站点逐小时 NRMSE 和整体 NRMSE。
```

报告中新增两个表：

1. 全局整体 NRMSE：

```text
round10_overall_nrmse_summary.csv
```

2. 每小时整体 NRMSE：

```text
round10_hour_overall_nrmse.csv
```

同时保留每站点逐小时文件引用：

```text
round10_site_hour_nrmse.csv
```

---

## 10. Cursor 执行顺序

### 10.1 初始化 best

```bash
python scripts/save_current_best_round10.py
python scripts/compute_nrmse_reports_round10.py
```

### 10.2 如果有新候选，比如 Round9 specialist

```bash
python scripts/promote_candidate_if_better_round10.py \
  --candidate-eval output/pv_pipeline/tables/distributed_predictions_midday_specialist_round9_eval.pkl \
  --candidate-full output/pv_pipeline/tables/distributed_predictions_midday_specialist_round9_full.pkl \
  --name midday_specialist_round9 \
  --min-midday-improve-pp 0.20 \
  --max-overall-worse-pp 0.05
```

### 10.3 无论是否晋级，都重新生成指标

```bash
python scripts/check_final_is_best_round10.py
python scripts/regenerate_final_metrics_round7.py
python scripts/assert_final_metrics_consistency_round7.py
python scripts/compute_nrmse_reports_round10.py
python scripts/update_project_md_metrics.py
```

---

## 11. 输出文件

Round10 必须新增以下文件：

```text
output/pv_pipeline/tables/best_predictions_eval.pkl
output/pv_pipeline/tables/best_predictions_full.pkl
output/pv_pipeline/metrics/round10_best_version_meta.json
output/pv_pipeline/metrics/round10_site_hour_nrmse.csv
output/pv_pipeline/metrics/round10_hour_overall_nrmse.csv
output/pv_pipeline/metrics/round10_overall_nrmse_summary.csv
output/pv_pipeline/metrics/round10_final_vs_best_nrmse.csv
output/pv_pipeline/metrics/round10_final_is_best_check.csv
```

如果运行候选晋级，还会生成：

```text
output/pv_pipeline/metrics/round10_candidate_decision_<candidate_name>.json
```

---

## 12. 验收标准

### 12.1 最优保护

必须满足：

```text
final_overall_nrmse_pct <= best_overall_nrmse_pct + 1e-6
```

如果不满足，自动回退。

### 12.2 新候选晋级

新候选必须同时满足：

| 条件 | 要求 |
|---|---:|
| 10-14 点整体 NRMSE | 至少比 best 下降 0.20 pp |
| 全局整体 NRMSE | 不得比 best 高超过 0.05 pp |
| 综合 score | 必须低于 best |

否则拒绝。

### 12.3 输出完整

必须输出：

1. `round10_site_hour_nrmse.csv`
2. `round10_hour_overall_nrmse.csv`
3. `round10_overall_nrmse_summary.csv`

其中：

```text
round10_site_hour_nrmse.csv
```

包含字段：

```text
version, site_id, hour, rows, capacity_mw, site_hour_nrmse_pct, mae_mw, rmse_mw
```

```text
round10_overall_nrmse_summary.csv
```

包含字段：

```text
version, rows, n_sites, actual_mwh, pred_mwh, pred_actual_ratio, bias_pct, mae_mw, rmse_mw, overall_nrmse_pct
```

---

## 13. 最终说明

Round10 的意义是：

1. 后续可以继续实验，但不会破坏当前最优结果。
2. 如果实验比当前差，自动回退。
3. 如果实验比当前好，才晋级为新的 best。
4. 每次不仅输出站点逐小时 NRMSE，也输出整体 NRMSE。

这能保证项目始终处于“当前已知最优版本”，不会因为后续尝试把结果拉坏。

