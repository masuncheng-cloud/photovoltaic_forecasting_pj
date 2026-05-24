# Cursor 下一步修改方案 Round9：10-14 点 NRMSE 压到 10% 以内

## 0. 目标变化

当前 final 的 10-14 点站点平均 NRMSE 为：

| 小时 | 当前站点平均 NRMSE |
|---:|---:|
| 10 | 13.29% |
| 11 | 14.68% |
| 12 | 15.36% |
| 13 | 15.31% |
| 14 | 13.51% |

如果目标是 **10-14 点最终 NRMSE 控制在 10% 以内**，则需要：

| 小时 | 当前值 | 目标值 | 需要下降 |
|---:|---:|---:|---:|
| 10 | 13.29% | <10% | 至少 3.29 pp |
| 11 | 14.68% | <10% | 至少 4.68 pp |
| 12 | 15.36% | <10% | 至少 5.36 pp |
| 13 | 15.31% | <10% | 至少 5.31 pp |
| 14 | 13.51% | <10% | 至少 3.51 pp |

这已经不是“校准系数”能稳定解决的问题。前几轮已经证明：

1. 后处理在 valid 上可以改善，但 test 上容易变差。
2. 高误差集中在少数站点，尤其 S012/S055/S050/S032/S019/S053/S116。
3. S012/S055/S050/S032 存在明显系统性异常，更像数据映射/别名字典/功率列问题。

因此 Round9 必须从数据侧和训练侧入手。

---

## 1. Round9 总目标

### 1.1 主目标

将测试集 10-14 点站点平均 NRMSE 尽量压到 10% 以下。

### 1.2 分级验收

| 等级 | 验收条件 |
|---|---|
| A 级 | 10、11、12、13、14 五个小时全部 < 10% |
| B 级 | 至少 3/5 个小时 < 10%，且 10-14 平均 NRMSE < 11% |
| C 级 | 10-14 平均 NRMSE 相对当前下降 ≥ 20% |
| 不通过 | 仍停留在 13%-15%，或只靠 test 后处理得到改善 |

### 1.3 关键原则

1. 不允许用 test 集调参。
2. 不允许继续扩大 alpha/k 后处理网格。
3. 不允许自动修改容量或站点映射。
4. 必须先核查高误差站点对整体 NRMSE 的贡献。
5. 如果确认映射错误，必须从数据清洗阶段重新跑全流程。

---

## 2. Round9 修改路线

本轮分四步：

```text
贡献拆解
→ 高误差站点映射核查
→ 数据修正后重建训练表
→ 中午专用模型重新训练
```

---

## 3. 修改一：新增 10-14 点 NRMSE 贡献拆解脚本

新建：

```text
scripts/analyze_midday_nrmse_contribution_round9.py
```

作用：

1. 计算每个站点对 10-14 点 NRMSE 的贡献。
2. 计算剔除某站点后，10-14 点 NRMSE 会下降多少。
3. 找出若要达到 10%，必须优先解决哪些站点。

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
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

MIDDAY = [10, 11, 12, 13, 14]


def site_hour_nrmse(g: pd.DataFrame) -> float:
    y = pd.to_numeric(g["power_mw"], errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(g["power_pred"], errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(g["capacity_mw"], errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (c > 0)
    if not m.any():
        return np.nan
    return float(np.sqrt(np.mean((y[m] - p[m]) ** 2)) / np.nanmean(c[m]) * 100.0)


def main():
    final_path = TABLES / "distributed_predictions_final_eval.pkl"
    if not final_path.exists():
        raise FileNotFoundError(final_path)

    df = safe_pickle_load(final_path)
    df = df[df["hour"].isin(MIDDAY)].copy()

    base = hourly_nrmse_metrics(df)
    base_mid = base[base["hour"].isin(MIDDAY)][["hour", "site_nrmse_mean_pct", "city_nrmse_pct"]].copy()
    base_avg = float(base_mid["site_nrmse_mean_pct"].mean())

    rows = []
    for sid in sorted(df["site_id"].unique()):
        sub = df[df["site_id"] != sid].copy()
        h = hourly_nrmse_metrics(sub)
        h = h[h["hour"].isin(MIDDAY)]
        avg_after_drop = float(h["site_nrmse_mean_pct"].mean())
        rows.append({
            "site_id": sid,
            "base_midday_avg_nrmse_pct": round(base_avg, 4),
            "avg_nrmse_after_drop_site_pct": round(avg_after_drop, 4),
            "drop_contribution_pp": round(base_avg - avg_after_drop, 4),
        })

    contrib = pd.DataFrame(rows).sort_values("drop_contribution_pp", ascending=False)
    contrib.to_csv(METRICS / "round9_midday_site_drop_contribution.csv", index=False, encoding="utf-8-sig")

    detail_rows = []
    for (sid, h), g in df.groupby(["site_id", "hour"]):
        y = pd.to_numeric(g["power_mw"], errors="coerce")
        p = pd.to_numeric(g["power_pred"], errors="coerce")
        actual = float(y.sum())
        pred = float(p.sum())
        detail_rows.append({
            "site_id": sid,
            "hour": int(h),
            "rows": len(g),
            "capacity_mw": round(float(pd.to_numeric(g["capacity_mw"], errors="coerce").mean()), 4),
            "site_hour_nrmse_pct": round(site_hour_nrmse(g), 4),
            "actual_sum_mwh": round(actual, 4),
            "pred_sum_mwh": round(pred, 4),
            "pred_actual_ratio": round(pred / actual, 4) if actual > 0 else np.nan,
        })

    detail = pd.DataFrame(detail_rows).sort_values("site_hour_nrmse_pct", ascending=False)
    detail.to_csv(METRICS / "round9_midday_site_hour_nrmse_detail.csv", index=False, encoding="utf-8-sig")

    print("10-14 当前逐小时 NRMSE:")
    print(base_mid.to_string(index=False))
    print()
    print("站点贡献 Top 20:")
    print(contrib.head(20).to_string(index=False))
    print()
    print("站点小时 NRMSE Top 30:")
    print(detail.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
```

运行后重点看：

```text
output/pv_pipeline/metrics/round9_midday_site_drop_contribution.csv
output/pv_pipeline/metrics/round9_midday_site_hour_nrmse_detail.csv
```

如果前 5-8 个站点贡献了大部分超额误差，则先修站点映射。

---

## 4. 修改二：新增功率列映射核查脚本

新建：

```text
scripts/diagnose_power_alias_mapping_round9.py
```

目标：

1. 对 S012/S055/S050/S032/S019/S053/S116 找到原始功率列名或别名。
2. 与 `power_mapping.csv`、`site_master.csv`、`power_long_raw.pkl` 做一致性核查。
3. 输出疑似错配、重复映射、同名/近似名映射。

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

WATCH = {"S012", "S055", "S050", "S032", "S019", "S053", "S116"}


def main():
    mapping_path = TABLES / "power_mapping.csv"
    site_path = TABLES / "site_master.csv"
    raw_path = TABLES / "power_long_raw.pkl"
    clean_path = TABLES / "power_clean.pkl"

    outputs = {}

    if mapping_path.exists():
        mapping = pd.read_csv(mapping_path)
        outputs["mapping_columns"] = list(mapping.columns)
        watch_mapping = mapping[
            mapping.astype(str).apply(lambda col: col.str.contains("|".join(WATCH), na=False)).any(axis=1)
        ].copy()
        watch_mapping.to_csv(METRICS / "round9_watch_site_power_mapping_rows.csv", index=False, encoding="utf-8-sig")

        # 检查重复映射
        dup_rows = []
        for col in mapping.columns:
            vc = mapping[col].astype(str).value_counts()
            dup = vc[vc > 1]
            for val, cnt in dup.items():
                if val and val != "nan":
                    dup_rows.append({"column": col, "value": val, "count": int(cnt)})
        pd.DataFrame(dup_rows).to_csv(METRICS / "round9_power_mapping_duplicate_values.csv", index=False, encoding="utf-8-sig")

    if site_path.exists():
        site = pd.read_csv(site_path)
        site_watch = site[site.astype(str).apply(lambda col: col.str.contains("|".join(WATCH), na=False)).any(axis=1)].copy()
        site_watch.to_csv(METRICS / "round9_watch_site_master_rows.csv", index=False, encoding="utf-8-sig")

    if raw_path.exists():
        raw = safe_pickle_load(raw_path)
        raw_cols = pd.DataFrame({"raw_columns": list(raw.columns)})
        raw_cols.to_csv(METRICS / "round9_power_long_raw_columns.csv", index=False, encoding="utf-8-sig")

        # 如果是长表，尝试输出 watch 站点相关行
        possible_cols = [c for c in raw.columns if c.lower() in {"site_id", "site_name", "alias", "name", "power_col"}]
        if possible_cols:
            mask = raw[possible_cols].astype(str).apply(lambda col: col.str.contains("|".join(WATCH), na=False)).any(axis=1)
            raw[mask].head(2000).to_csv(METRICS / "round9_watch_site_raw_power_rows_sample.csv", index=False, encoding="utf-8-sig")

    if clean_path.exists():
        clean = safe_pickle_load(clean_path)
        cols = list(clean.columns)
        pd.DataFrame({"clean_columns": cols}).to_csv(METRICS / "round9_power_clean_columns.csv", index=False, encoding="utf-8-sig")

        if "site_id" in clean.columns:
            watch_clean = clean[clean["site_id"].isin(WATCH)].copy()
            if "time" in watch_clean.columns:
                watch_clean["time"] = pd.to_datetime(watch_clean["time"], errors="coerce")
                watch_clean["hour"] = watch_clean["time"].dt.hour
            summary = []
            for sid, g in watch_clean.groupby("site_id"):
                power_col = "power_mw" if "power_mw" in g.columns else None
                if power_col:
                    p = pd.to_numeric(g[power_col], errors="coerce")
                    summary.append({
                        "site_id": sid,
                        "rows": len(g),
                        "positive_rows": int((p > 0).sum()),
                        "zero_rows": int((p == 0).sum()),
                        "p95": round(float(p[p > 0].quantile(0.95)), 4) if (p > 0).any() else np.nan,
                        "p99": round(float(p[p > 0].quantile(0.99)), 4) if (p > 0).any() else np.nan,
                        "max": round(float(p[p > 0].max()), 4) if (p > 0).any() else np.nan,
                    })
            pd.DataFrame(summary).to_csv(METRICS / "round9_watch_site_clean_power_summary.csv", index=False, encoding="utf-8-sig")

    print("Round9 alias/mapping diagnosis outputs written to metrics.")
    print(outputs)


if __name__ == "__main__":
    main()
```

运行后查看：

```text
round9_watch_site_power_mapping_rows.csv
round9_watch_site_master_rows.csv
round9_power_mapping_duplicate_values.csv
round9_watch_site_clean_power_summary.csv
```

如果发现某站点别名为空、重复、指向错误列，必须先修映射表。

---

## 5. 修改三：新增高误差站点曲线导出

新建：

```text
scripts/export_watch_site_midday_curves_round9.py
```

目标：

1. 导出 S012/S055/S050/S032/S019/S053/S116 的 10-14 点真实/预测曲线。
2. 输出日均曲线、逐日曲线、相邻站点对比表。
3. 便于人工判断是否功率列错位。

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

WATCH = ["S012", "S055", "S050", "S032", "S019", "S053", "S116"]
MIDDAY = [10, 11, 12, 13, 14]


def main():
    final_path = TABLES / "distributed_predictions_final_eval.pkl"
    df = safe_pickle_load(final_path)
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    if "date" not in df.columns:
        df["date"] = df["time"].dt.date

    sub = df[df["site_id"].isin(WATCH) & df["hour"].isin(MIDDAY)].copy()
    keep_cols = [c for c in ["time", "date", "hour", "site_id", "site_name", "capacity_mw", "power_mw", "power_pred", "pred_baseline"] if c in sub.columns]
    sub[keep_cols].to_csv(METRICS / "round9_watch_site_midday_true_pred_detail.csv", index=False, encoding="utf-8-sig")

    avg = (
        sub.groupby(["site_id", "hour"], as_index=False)
        .agg(
            capacity_mw=("capacity_mw", "mean"),
            actual_mean_mw=("power_mw", "mean"),
            pred_mean_mw=("power_pred", "mean"),
            actual_sum_mwh=("power_mw", "sum"),
            pred_sum_mwh=("power_pred", "sum"),
            rows=("power_mw", "size"),
        )
    )
    avg["pred_actual_ratio"] = avg["pred_sum_mwh"] / avg["actual_sum_mwh"]
    avg.to_csv(METRICS / "round9_watch_site_midday_hourly_mean_curve.csv", index=False, encoding="utf-8-sig")

    daily = (
        sub.groupby(["site_id", "date"], as_index=False)
        .agg(
            actual_midday_sum=("power_mw", "sum"),
            pred_midday_sum=("power_pred", "sum"),
            rows=("power_mw", "size"),
        )
    )
    daily["pred_actual_ratio"] = daily["pred_midday_sum"] / daily["actual_midday_sum"]
    daily.to_csv(METRICS / "round9_watch_site_midday_daily_ratio.csv", index=False, encoding="utf-8-sig")

    print("导出完成:")
    print(METRICS / "round9_watch_site_midday_true_pred_detail.csv")
    print(METRICS / "round9_watch_site_midday_hourly_mean_curve.csv")
    print(METRICS / "round9_watch_site_midday_daily_ratio.csv")


if __name__ == "__main__":
    main()
```

---

## 6. 修改四：人工映射修正入口

新增配置文件：

```text
config/power_alias_overrides_round9.csv
```

默认只写表头：

```csv
site_id,old_alias,new_alias,reason,enabled
```

说明：

1. 不要自动填。
2. 只有人工确认功率列映射错误后，才填写。
3. `enabled=1` 才生效。

示例，不要默认启用：

```csv
S012,旧错误列名,正确列名,人工核查确认功率列错配,1
```

---

## 7. 修改五：新增映射修正应用脚本

新建：

```text
scripts/apply_power_alias_overrides_round9.py
```

作用：

1. 读取 `config/power_alias_overrides_round9.csv`。
2. 如果为空，直接跳过。
3. 如果有 enabled 修正，则修改 `power_mapping.csv`。
4. 保存为新的映射文件，不覆盖原始文件：

```text
output/pv_pipeline/tables/power_mapping_round9_corrected.csv
```

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "config"
TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
CONFIG.mkdir(parents=True, exist_ok=True)
METRICS.mkdir(parents=True, exist_ok=True)

OVERRIDE = CONFIG / "power_alias_overrides_round9.csv"
IN_MAPPING = TABLES / "power_mapping.csv"
OUT_MAPPING = TABLES / "power_mapping_round9_corrected.csv"
LOG = METRICS / "round9_power_alias_overrides_applied.csv"


def main():
    if not OVERRIDE.exists():
        OVERRIDE.write_text("site_id,old_alias,new_alias,reason,enabled\n", encoding="utf-8")
        print(f"已创建空配置: {OVERRIDE}")

    if not IN_MAPPING.exists():
        raise FileNotFoundError(IN_MAPPING)

    mapping = pd.read_csv(IN_MAPPING)
    overrides = pd.read_csv(OVERRIDE)

    if overrides.empty:
        mapping.to_csv(OUT_MAPPING, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=["site_id", "old_alias", "new_alias", "reason", "status"]).to_csv(LOG, index=False, encoding="utf-8-sig")
        print("无 alias override，透传 power_mapping。")
        return

    enabled = overrides[overrides["enabled"].astype(str).isin(["1", "true", "True", "yes", "YES"])].copy()
    log_rows = []

    out = mapping.copy()
    for _, r in enabled.iterrows():
        sid = str(r["site_id"])
        old_alias = str(r["old_alias"])
        new_alias = str(r["new_alias"])
        reason = str(r.get("reason", ""))

        # 尽量兼容不同 mapping 列名：凡是该行包含 site_id 且包含 old_alias 的单元格，都替换为 new_alias。
        site_mask = out.astype(str).apply(lambda col: col.str.contains(sid, na=False)).any(axis=1)
        old_mask = out.astype(str).apply(lambda col: col == old_alias).any(axis=1)
        mask = site_mask & old_mask

        if not mask.any():
            log_rows.append({
                "site_id": sid,
                "old_alias": old_alias,
                "new_alias": new_alias,
                "reason": reason,
                "status": "not_found",
            })
            continue

        for col in out.columns:
            out.loc[mask & (out[col].astype(str) == old_alias), col] = new_alias

        log_rows.append({
            "site_id": sid,
            "old_alias": old_alias,
            "new_alias": new_alias,
            "reason": reason,
            "status": "applied",
        })

    out.to_csv(OUT_MAPPING, index=False, encoding="utf-8-sig")
    pd.DataFrame(log_rows).to_csv(LOG, index=False, encoding="utf-8-sig")
    print(f"保存: {OUT_MAPPING}")
    print(f"日志: {LOG}")


if __name__ == "__main__":
    main()
```

注意：这个脚本只生成修正后的 mapping 文件。后续数据清洗脚本必须显式支持优先读取 `power_mapping_round9_corrected.csv`。

---

## 8. 修改六：让数据清洗优先读取 Round9 修正映射

找到项目中读取 `power_mapping.csv` 的脚本，常见可能是：

```text
scripts/build_dataset.py
scripts/preprocess_power.py
scripts/train_fixed.py
src/pv_forecasting/...
```

搜索：

```bash
grep -R "power_mapping.csv" -n scripts src
```

将读取逻辑改为：

```python
mapping_path = TABLES_DIR / "power_mapping_round9_corrected.csv"
if not mapping_path.exists():
    mapping_path = TABLES_DIR / "power_mapping.csv"
```

目的：人工修正后，重新跑数据清洗和训练时能真正生效。

---

## 9. 修改七：中午专用模型，不再做后处理

如果映射核查后仍无法降到 10%，再训练 10-14 点专用模型。

新建：

```text
scripts/train_midday_specialist_model_round9.py
```

要求：

1. 只训练 10-14 点。
2. 目标为容量归一化功率：

```text
y = power_mw / capacity_mw
```

3. 样本权重：

| 样本类型 | 权重 |
|---|---:|
| 高误差站点 S012/S055/S050/S032/S019/S053/S116 | 2.5 |
| 其他站点 | 1.0 |
| 12-13 点 | 1.2 |

4. 特征必须包含：

```text
hour
month
dayofyear
capacity_mw
G_blend / GHI / clear-sky index
temperature
cloud cover
lag power if available
site_id encoding
```

5. 使用 train 训练，valid 选模型，test 只评估。
6. 输出候选：

```text
distributed_predictions_midday_specialist_round9_full.pkl
distributed_predictions_midday_specialist_round9_eval.pkl
```

7. final 选择器只能在 valid 上确认其 10-14 点相对 `MiddaySiteCalibrated` 改善 ≥ 1.0 pp 时才允许入选。

如果当前项目已有模型训练框架，直接复用现有 LightGBM/CatBoost/XGBoost，不要手写新模型框架。

---

## 10. 修改八：final 选择器接入 Round9 Specialist

在：

```text
scripts/select_final_prediction_by_guard.py
```

新增候选：

```python
Round9MiddaySpecialist
```

加载：

```python
round9_path = TABLES_DIR / "distributed_predictions_midday_specialist_round9_full.pkl"
```

10-14 点 guard：

```python
Round9MiddaySpecialist 只有在 valid 上比 MiddaySiteCalibrated 站点平均 NRMSE 至少低 1.0 pp 才允许入选。
```

原因：前几轮已经证明 0.05-0.7 pp 的 valid 改善不可靠。如果目标是 <10%，必须要求 valid 上有明显优势。

---

## 11. 修改九：Round9 验收脚本

新建：

```text
scripts/check_round9_midday_under10.py
```

输出：

```text
output/pv_pipeline/metrics/round9_midday_under10_acceptance.csv
```

验收逻辑：

1. 读取 final_eval。
2. 计算 10-14 点站点平均 NRMSE。
3. 判断是否 <10%。
4. 输出 A/B/C 等级。

写入：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load
from pv_forecasting.core.evaluation import hourly_nrmse_metrics

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

MIDDAY = [10, 11, 12, 13, 14]


def main():
    df = safe_pickle_load(TABLES / "distributed_predictions_final_eval.pkl")
    h = hourly_nrmse_metrics(df)
    out = h[h["hour"].isin(MIDDAY)][["hour", "rows", "site_nrmse_mean_pct", "city_nrmse_pct"]].copy()
    out["under_10_pct"] = out["site_nrmse_mean_pct"] < 10.0
    out.to_csv(METRICS / "round9_midday_under10_acceptance.csv", index=False, encoding="utf-8-sig")

    n_under = int(out["under_10_pct"].sum())
    avg = float(out["site_nrmse_mean_pct"].mean())

    if n_under == 5:
        grade = "A"
    elif n_under >= 3 and avg < 11:
        grade = "B"
    elif avg <= 14.43 * 0.80:
        grade = "C"
    else:
        grade = "FAIL"

    print(out.to_string(index=False))
    print(f"Round9 grade: {grade}, under10={n_under}/5, avg={avg:.2f}%")

    if grade == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
```

---

## 12. Cursor 执行顺序

### 12.1 先做诊断，不训练

```bash
python scripts/analyze_midday_nrmse_contribution_round9.py
python scripts/diagnose_power_alias_mapping_round9.py
python scripts/export_watch_site_midday_curves_round9.py
python scripts/apply_power_alias_overrides_round9.py
```

如果 `config/power_alias_overrides_round9.csv` 为空，不会改变结果。

### 12.2 人工核查

检查这些文件：

```text
output/pv_pipeline/metrics/round9_midday_site_drop_contribution.csv
output/pv_pipeline/metrics/round9_midday_site_hour_nrmse_detail.csv
output/pv_pipeline/metrics/round9_watch_site_power_mapping_rows.csv
output/pv_pipeline/metrics/round9_power_mapping_duplicate_values.csv
output/pv_pipeline/metrics/round9_watch_site_clean_power_summary.csv
output/pv_pipeline/metrics/round9_watch_site_midday_hourly_mean_curve.csv
```

如果确认映射错误，填写：

```text
config/power_alias_overrides_round9.csv
```

然后从数据清洗阶段重新跑。

### 12.3 如果映射修正后仍不达标，再训练中午专用模型

```bash
python scripts/train_midday_specialist_model_round9.py
python scripts/select_final_prediction_by_guard.py
python scripts/regenerate_final_metrics_round7.py
python scripts/assert_final_metrics_consistency_round7.py
python scripts/check_round9_midday_under10.py
python scripts/update_project_md_metrics.py
```

---

## 13. 是否能达到 10% 的判断

### 13.1 能达到的情况

如果 S012/S055/S050/S032 确实存在功率列映射错误，修正后重新训练，有可能把 10-14 点压到 10%-11% 附近，甚至部分小时 <10%。

### 13.2 很难达到的情况

如果映射没有错误，仅靠现有 ERA5 级别气象和当前特征，要把全部 10-14 点从 13%-15% 压到 <10%，难度很大。此时需要：

1. 更高分辨率气象数据；
2. 更准确的辐照观测或云量特征；
3. 按站点分组建模；
4. 更长训练数据；
5. 对小容量站点单独处理。

---

## 14. Round9 最终交付判断

Round9 完成后输出结论时必须分清：

1. **如果映射修正后达标**：说明主要问题是数据映射错误，模型链路可继续使用。
2. **如果映射无误但未达标**：说明当前数据条件下模型能力达到瓶颈，需要新增数据源或重新建模。
3. **如果只靠 test 后处理达标**：不算通过，属于数据泄漏风险。

目标 <10% 可以作为最终优化目标，但不能通过不稳定后处理硬压，必须通过数据修正或训练层改进实现。

