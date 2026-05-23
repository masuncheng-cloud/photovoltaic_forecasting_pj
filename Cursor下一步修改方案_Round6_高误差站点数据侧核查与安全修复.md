# Cursor 下一步修改方案 Round6：高误差站点数据侧核查与安全修复

## 0. 当前判断

Round5 的结论很明确：

1. `MiddaySiteCalibrated` 是当前 10-14 点最稳的有效版本。
2. `MiddaySiteSelectiveCorrected` 在 valid 上改善，但 test 上变差，说明通用站点小时后处理存在过拟合。
3. 最终选择器强制保留 `MiddaySiteCalibrated`，安全机制有效。
4. 10-14 点高误差主要集中在少数站点：

| 站点 | 现象 | 判断 |
|---|---|---|
| S012 | 10-14 点系统性高估 2-3 倍 | 优先检查容量、别名映射、功率列匹配 |
| S055 | 10-14 点系统性高估 2.5-2.8 倍 | 优先检查容量、别名映射、功率列匹配 |
| S050 | 10-14 点系统性高估约 2 倍 | 优先检查容量、别名映射、功率列匹配 |
| S032 | 10-14 点系统性低估约 50% | 优先检查容量、功率列是否混入或映射错位 |
| S019 | 轻微低估但 NRMSE 高 | 小容量站点波动敏感，后续再处理 |

因此，Round6 不再继续做全体站点的后处理搜索，而是转向：

```text
高误差站点数据侧诊断
→ 稳定偏差站点识别
→ 只对 train/valid 均稳定的极端站点做保守修正
→ final 安全选择
→ 报告同步
```

---

## 1. 本轮目标

### 1.1 主目标

在不牺牲当前安全结果的前提下，尝试进一步降低 10-14 点站点平均 NRMSE。

### 1.2 更重要的目标

找出 S012、S055、S050、S032 等站点误差异常的真实原因：

1. 装机容量是否填错。
2. 站点名称/功率列是否映射错。
3. 分布式功率列是否被重复、错位或混入其他站点。
4. 实际功率峰值与容量是否明显不匹配。
5. 模型预测偏差是否在 train、valid、test 均稳定存在。

### 1.3 验收标准

| 项目 | 验收标准 |
|---|---|
| 诊断产物 | 必须输出高误差站点容量、峰值、映射、偏差稳定性报告 |
| 修正安全性 | 没有稳定证据的站点不允许自动修正 |
| 10-14 点结果 | final 不得低于当前 `MiddaySiteCalibrated` |
| 若有修正生效 | 10-14 点至少 2/5 小时改善，且无单小时恶化超过 0.2 pp |
| 报告一致性 | `当前最终结果摘要.md` 必须来自最新 `distributed_predictions_final_eval.pkl` |

---

## 2. 修改总览

请在 Cursor 中按以下顺序修改：

| 顺序 | 文件 | 作用 |
|---:|---|---|
| 1 | 新建 `scripts/diagnose_site_capacity_mapping_round6.py` | 核查站点容量、峰值、0 值占比、预测偏差 |
| 2 | 新建 `scripts/diagnose_midday_bias_stability_round6.py` | 判断高误差站点偏差是否 train/valid 稳定 |
| 3 | 新建 `config/site_metadata_overrides.csv` | 人工确认后的容量/站点修正入口，默认空 |
| 4 | 新建 `scripts/apply_site_metadata_overrides.py` | 只应用人工确认的 overrides |
| 5 | 新建 `scripts/apply_midday_stable_bias_correction_round6.py` | 仅对 train/valid 稳定偏差站点做保守修正 |
| 6 | 修改 `scripts/select_final_prediction_by_guard.py` | 接入 Round6 候选，但不允许劣化 |
| 7 | 新建 `scripts/check_round6_midday_gain.py` | 对比 Round6 final vs 当前安全基准 |
| 8 | 修改 `scripts/train_fixed.py` | 接入 Round6 脚本顺序 |

---

## 3. 修改一：新增容量与映射诊断脚本

新建：

```text
scripts/diagnose_site_capacity_mapping_round6.py
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

TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)

MIDDAY_HOURS = [10, 11, 12, 13, 14]
WATCH_SITES = {"S012", "S055", "S050", "S032", "S019", "S053", "S072", "S002", "S059"}


def safe_num(s):
    return pd.to_numeric(s, errors="coerce")


def summarize_site(g: pd.DataFrame) -> dict:
    power = safe_num(g["power_mw"])
    cap = safe_num(g["capacity_mw"])
    pred = safe_num(g["power_pred"]) if "power_pred" in g.columns else pd.Series(np.nan, index=g.index)
    nonnull = power.notna()
    pos = power > 0
    cap_med = float(cap.median()) if cap.notna().any() else np.nan
    p95 = float(power[pos].quantile(0.95)) if pos.any() else np.nan
    p99 = float(power[pos].quantile(0.99)) if pos.any() else np.nan
    pmax = float(power[pos].max()) if pos.any() else np.nan

    actual_sum = float(power[pos].sum()) if pos.any() else np.nan
    pred_sum = float(pred[pos].sum()) if pos.any() and pred.notna().any() else np.nan

    return {
        "site_id": g["site_id"].iloc[0],
        "rows": int(len(g)),
        "nonnull_power_rows": int(nonnull.sum()),
        "positive_power_rows": int(pos.sum()),
        "zero_rows": int(((power == 0) & nonnull).sum()),
        "zero_ratio_pct": round(float(((power == 0) & nonnull).sum() / max(nonnull.sum(), 1) * 100.0), 2),
        "capacity_mw": round(cap_med, 4) if np.isfinite(cap_med) else np.nan,
        "p95_power_mw": round(p95, 4) if np.isfinite(p95) else np.nan,
        "p99_power_mw": round(p99, 4) if np.isfinite(p99) else np.nan,
        "max_power_mw": round(pmax, 4) if np.isfinite(pmax) else np.nan,
        "p99_over_capacity": round(p99 / cap_med, 4) if np.isfinite(p99) and np.isfinite(cap_med) and cap_med > 0 else np.nan,
        "max_over_capacity": round(pmax / cap_med, 4) if np.isfinite(pmax) and np.isfinite(cap_med) and cap_med > 0 else np.nan,
        "eval_pred_actual_ratio": round(pred_sum / actual_sum, 4) if np.isfinite(pred_sum) and np.isfinite(actual_sum) and actual_sum > 0 else np.nan,
    }


def main():
    full_path = TABLES_DIR / "distributed_predictions_final_full.pkl"
    eval_path = TABLES_DIR / "distributed_predictions_final_eval.pkl"
    if not full_path.exists():
        raise FileNotFoundError(full_path)
    if not eval_path.exists():
        raise FileNotFoundError(eval_path)

    full = safe_pickle_load(full_path)
    eval_df = safe_pickle_load(eval_path)

    full["time"] = pd.to_datetime(full["time"], errors="coerce")
    if "hour" not in full.columns:
        full["hour"] = full["time"].dt.hour

    eval_df["time"] = pd.to_datetime(eval_df["time"], errors="coerce")
    if "hour" not in eval_df.columns:
        eval_df["hour"] = eval_df["time"].dt.hour

    rows = []
    for sid, g in full.groupby("site_id"):
        rows.append(summarize_site(g))
    site_summary = pd.DataFrame(rows)

    # 只看 10-14 final eval 的误差表现
    midday = eval_df[eval_df["hour"].isin(MIDDAY_HOURS)].copy()
    err_rows = []
    for sid, g in midday.groupby("site_id"):
        y = safe_num(g["power_mw"]).to_numpy(dtype=float)
        p = safe_num(g["power_pred"]).to_numpy(dtype=float)
        c = safe_num(g["capacity_mw"]).to_numpy(dtype=float)
        m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (y > 0) & (c > 0)
        if not m.any():
            continue
        rmse = float(np.sqrt(np.mean((y[m] - p[m]) ** 2)))
        cap = float(np.nanmean(c[m]))
        actual = float(np.sum(y[m]))
        pred = float(np.sum(p[m]))
        err_rows.append({
            "site_id": sid,
            "midday_eval_rows": int(m.sum()),
            "midday_site_nrmse_pct": round(rmse / cap * 100.0, 4) if cap > 0 else np.nan,
            "midday_pred_actual_ratio": round(pred / actual, 4) if actual > 0 else np.nan,
            "midday_bias_pct": round((pred - actual) / actual * 100.0, 4) if actual > 0 else np.nan,
        })
    err = pd.DataFrame(err_rows)

    out = site_summary.merge(err, on="site_id", how="left")
    out["is_watch_site"] = out["site_id"].isin(WATCH_SITES)

    def flag(row):
        flags = []
        if pd.notna(row.get("p99_over_capacity")) and row["p99_over_capacity"] > 1.10:
            flags.append("p99_power_exceeds_capacity")
        if pd.notna(row.get("max_over_capacity")) and row["max_over_capacity"] > 1.20:
            flags.append("max_power_exceeds_capacity")
        if pd.notna(row.get("midday_pred_actual_ratio")) and row["midday_pred_actual_ratio"] > 1.60:
            flags.append("midday_prediction_over_high")
        if pd.notna(row.get("midday_pred_actual_ratio")) and row["midday_pred_actual_ratio"] < 0.65:
            flags.append("midday_prediction_too_low")
        if pd.notna(row.get("zero_ratio_pct")) and row["zero_ratio_pct"] > 70:
            flags.append("zero_ratio_high")
        return ";".join(flags)

    out["diagnostic_flags"] = out.apply(flag, axis=1)
    out = out.sort_values(["is_watch_site", "midday_site_nrmse_pct"], ascending=[False, False])

    out.to_csv(METRICS_DIR / "round6_site_capacity_mapping_diagnosis.csv", index=False, encoding="utf-8-sig")
    out[out["is_watch_site"]].to_csv(METRICS_DIR / "round6_watch_site_diagnosis.csv", index=False, encoding="utf-8-sig")
    out[out["diagnostic_flags"] != ""].to_csv(METRICS_DIR / "round6_flagged_site_diagnosis.csv", index=False, encoding="utf-8-sig")

    print("重点站点诊断:")
    print(out[out["is_watch_site"]].to_string(index=False))
    print()
    print("异常标记站点:")
    print(out[out["diagnostic_flags"] != ""].head(50).to_string(index=False))


if __name__ == "__main__":
    main()
```

运行后重点查看：

```text
output/pv_pipeline/metrics/round6_watch_site_diagnosis.csv
output/pv_pipeline/metrics/round6_flagged_site_diagnosis.csv
```

如果 S012/S055/S050 的 `midday_pred_actual_ratio` 很高，但 `p99_over_capacity` 正常，说明更可能是模型/映射偏差；如果 `p99_over_capacity` 或 `max_over_capacity` 异常，优先查容量或功率列。

---

## 4. 修改二：新增偏差稳定性诊断脚本

新建：

```text
scripts/diagnose_midday_bias_stability_round6.py
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

TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)

MIDDAY_HOURS = [10, 11, 12, 13, 14]
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}


def nrmse(y, p, c):
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(c, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (y > 0) & (c > 0)
    if not m.any():
        return np.nan
    return float(np.sqrt(np.mean((y[m] - p[m]) ** 2)) / np.nanmean(c[m]) * 100.0)


def ratio(y, p):
    y = pd.to_numeric(y, errors="coerce")
    p = pd.to_numeric(p, errors="coerce")
    m = y.notna() & p.notna() & (y > 0)
    if not m.any():
        return np.nan
    actual = float(y[m].sum())
    pred = float(p[m].sum())
    return pred / actual if actual > 0 else np.nan


def main():
    base_path = TABLES_DIR / "distributed_predictions_midday_site_calibrated_full.pkl"
    if not base_path.exists():
        base_path = TABLES_DIR / "distributed_predictions_final_full.pkl"
    if not base_path.exists():
        raise FileNotFoundError(base_path)

    df = safe_pickle_load(base_path)
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour

    work = df[
        df["hour"].isin(MIDDAY_HOURS)
        & (~df["site_id"].isin(BAD_SITES))
        & (pd.to_numeric(df["power_mw"], errors="coerce") > 0)
    ].copy()

    rows = []
    for (sid, h, split), g in work.groupby(["site_id", "hour", "split"]):
        rows.append({
            "site_id": sid,
            "hour": int(h),
            "split": split,
            "rows": len(g),
            "pred_actual_ratio": ratio(g["power_mw"], g["power_pred"]),
            "site_nrmse_pct": nrmse(g["power_mw"], g["power_pred"], g["capacity_mw"]),
        })
    long = pd.DataFrame(rows)
    long.to_csv(METRICS_DIR / "round6_midday_bias_stability_long.csv", index=False, encoding="utf-8-sig")

    piv = long.pivot_table(
        index=["site_id", "hour"],
        columns="split",
        values=["rows", "pred_actual_ratio", "site_nrmse_pct"],
        aggfunc="first",
    )
    piv.columns = [f"{a}_{b}" for a, b in piv.columns]
    piv = piv.reset_index()

    def classify(row):
        tr = row.get("pred_actual_ratio_train", np.nan)
        va = row.get("pred_actual_ratio_valid", np.nan)
        if not np.isfinite(tr) or not np.isfinite(va):
            return "insufficient"
        # train/valid 同向且幅度接近，才认为稳定。
        if tr > 1.35 and va > 1.35:
            return "stable_over_prediction"
        if tr < 0.75 and va < 0.75:
            return "stable_under_prediction"
        return "unstable_or_mild"

    piv["bias_class"] = piv.apply(classify, axis=1)
    piv["train_valid_ratio_gap"] = (
        piv.get("pred_actual_ratio_train", np.nan) - piv.get("pred_actual_ratio_valid", np.nan)
    ).abs()

    # 稳定极端偏差候选：只允许 train/valid 都有足够样本且偏差同向。
    piv["is_stable_extreme_candidate"] = (
        piv["bias_class"].isin(["stable_over_prediction", "stable_under_prediction"])
        & (piv.get("rows_train", 0).fillna(0) >= 80)
        & (piv.get("rows_valid", 0).fillna(0) >= 30)
        & (piv["train_valid_ratio_gap"].fillna(999) <= 0.50)
    )

    piv = piv.sort_values(["is_stable_extreme_candidate", "site_nrmse_pct_valid"], ascending=[False, False])
    piv.to_csv(METRICS_DIR / "round6_midday_bias_stability_summary.csv", index=False, encoding="utf-8-sig")
    piv[piv["is_stable_extreme_candidate"]].to_csv(
        METRICS_DIR / "round6_stable_extreme_bias_candidates.csv",
        index=False,
        encoding="utf-8-sig",
    )

    print("稳定极端偏差候选:")
    print(piv[piv["is_stable_extreme_candidate"]].head(50).to_string(index=False))


if __name__ == "__main__":
    main()
```

这个脚本的作用是区分：

1. train/valid 都稳定高估或低估的站点小时，可以考虑修正。
2. valid 好但 test 差、train/valid 不稳定的站点小时，不应该自动修正。

---

## 5. 修改三：新增人工 metadata overrides 入口

新建目录和文件：

```text
config/site_metadata_overrides.csv
```

默认写入表头即可：

```csv
site_id,override_capacity_mw,override_site_name,reason,enabled
```

说明：

1. 默认不做任何容量或名称修正。
2. 只有人工核查确认容量/名称错误后，才填入 override。
3. `enabled` 必须为 `1` 才生效。

示例，不要默认写入：

```csv
S012,8.0,,容量台账核查后修正,1
```

---

## 6. 修改四：新增 overrides 应用脚本

新建：

```text
scripts/apply_site_metadata_overrides.py
```

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

from pv_forecasting.core.utils import safe_pickle_load, write_prediction_pickle_atomic

TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
METRICS_DIR.mkdir(parents=True, exist_ok=True)

OVERRIDE_PATH = CONFIG_DIR / "site_metadata_overrides.csv"
IN_PATH = TABLES_DIR / "distributed_predictions_midday_site_calibrated_full.pkl"
OUT_PATH = TABLES_DIR / "distributed_predictions_metadata_overridden_full.pkl"
OUT_LOG = METRICS_DIR / "round6_site_metadata_overrides_applied.csv"


def main():
    if not OVERRIDE_PATH.exists():
        OVERRIDE_PATH.write_text("site_id,override_capacity_mw,override_site_name,reason,enabled\n", encoding="utf-8")
        print(f"已创建空 overrides 文件: {OVERRIDE_PATH}")

    if not IN_PATH.exists():
        raise FileNotFoundError(IN_PATH)

    df = safe_pickle_load(IN_PATH)
    overrides = pd.read_csv(OVERRIDE_PATH)
    if overrides.empty:
        write_prediction_pickle_atomic(
            df,
            OUT_PATH,
            required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
        )
        pd.DataFrame(columns=["site_id", "field", "old_value", "new_value", "reason"]).to_csv(
            OUT_LOG, index=False, encoding="utf-8-sig"
        )
        print("overrides 为空，不做修改，仅透传输出。")
        return

    overrides = overrides[overrides.get("enabled", 0).astype(str).isin(["1", "True", "true", "YES", "yes"])].copy()
    log_rows = []

    out = df.copy()
    for _, row in overrides.iterrows():
        sid = str(row["site_id"])
        mask = out["site_id"].astype(str) == sid
        if not mask.any():
            continue

        reason = row.get("reason", "")
        if pd.notna(row.get("override_capacity_mw")):
            new_cap = float(row["override_capacity_mw"])
            if new_cap <= 0:
                raise ValueError(f"{sid} override_capacity_mw 必须 > 0")
            old = out.loc[mask, "capacity_mw"].dropna().median()
            out.loc[mask, "capacity_mw"] = new_cap
            # 物理裁剪同步更新，避免超过新容量。
            out.loc[mask, "power_pred"] = pd.to_numeric(out.loc[mask, "power_pred"], errors="coerce").clip(0, new_cap)
            log_rows.append({
                "site_id": sid,
                "field": "capacity_mw",
                "old_value": old,
                "new_value": new_cap,
                "reason": reason,
            })

        if "override_site_name" in row and pd.notna(row.get("override_site_name")) and str(row.get("override_site_name")).strip():
            if "site_name" in out.columns:
                old_name = out.loc[mask, "site_name"].dropna().iloc[0] if out.loc[mask, "site_name"].notna().any() else ""
                new_name = str(row["override_site_name"])
                out.loc[mask, "site_name"] = new_name
                log_rows.append({
                    "site_id": sid,
                    "field": "site_name",
                    "old_value": old_name,
                    "new_value": new_name,
                    "reason": reason,
                })

    write_prediction_pickle_atomic(
        out,
        OUT_PATH,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
    )
    pd.DataFrame(log_rows).to_csv(OUT_LOG, index=False, encoding="utf-8-sig")
    print(f"保存: {OUT_PATH}")
    print(f"应用记录: {OUT_LOG}")


if __name__ == "__main__":
    main()
```

注意：不要让脚本自动猜容量并修改。容量修正必须通过 `config/site_metadata_overrides.csv` 人工确认。

---

## 7. 修改五：新增稳定偏差保守修正脚本

新建：

```text
scripts/apply_midday_stable_bias_correction_round6.py
```

这个脚本只修正 train/valid 均显示稳定极端偏差的站点小时。它和 Round5 的选择性修正不同：

1. Round5 是 valid 上网格搜索，容易过拟合。
2. Round6 是 train 学系数，valid 验证稳定性。
3. 只有 train 和 valid 同向偏差，且 valid 也改善，才应用。

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

from pv_forecasting.core.utils import safe_pickle_load, write_prediction_pickle_atomic
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics

TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)

MIDDAY_HOURS = [10, 11, 12, 13, 14]
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}

IN_PATH = TABLES_DIR / "distributed_predictions_metadata_overridden_full.pkl"
FALLBACK_PATH = TABLES_DIR / "distributed_predictions_midday_site_calibrated_full.pkl"
OUT_FULL = TABLES_DIR / "distributed_predictions_round6_stable_bias_full.pkl"
OUT_EVAL = TABLES_DIR / "distributed_predictions_round6_stable_bias_eval.pkl"
OUT_PARAMS = METRICS_DIR / "round6_stable_bias_correction_params.csv"
OUT_VALID = METRICS_DIR / "round6_stable_bias_valid_ablation.csv"
OUT_TEST = METRICS_DIR / "round6_stable_bias_test_hourly_nrmse.csv"


def ensure_columns(df):
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour
    return out


def nrmse_pct(g, pred_col="power_pred"):
    y = pd.to_numeric(g["power_mw"], errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(g[pred_col], errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(g["capacity_mw"], errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (y > 0) & (c > 0)
    if not m.any():
        return np.nan
    return float(np.sqrt(np.mean((y[m] - p[m]) ** 2)) / np.nanmean(c[m]) * 100.0)


def pred_actual_ratio(g, pred_col="power_pred"):
    y = pd.to_numeric(g["power_mw"], errors="coerce")
    p = pd.to_numeric(g[pred_col], errors="coerce")
    m = y.notna() & p.notna() & (y > 0)
    if not m.any():
        return np.nan
    actual = float(y[m].sum())
    pred = float(p[m].sum())
    return pred / actual if actual > 0 else np.nan


def learn_train_k(g):
    y = pd.to_numeric(g["power_mw"], errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(g["power_pred"], errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & (y > 0) & (p > 0)
    if m.sum() < 80:
        return np.nan
    denom = float(np.sum(p[m] ** 2))
    if denom <= 1e-9:
        return np.nan
    k = float(np.sum(y[m] * p[m]) / denom)
    return float(np.clip(k, 0.55, 1.45))


def apply_k(g, k):
    out = g.copy()
    cap = pd.to_numeric(out["capacity_mw"], errors="coerce").fillna(0)
    pred = pd.to_numeric(out["power_pred"], errors="coerce") * k
    out["power_pred_candidate"] = pred.clip(lower=0, upper=cap)
    return out


def learn_params(df):
    work = df[
        df["hour"].isin(MIDDAY_HOURS)
        & (~df["site_id"].isin(BAD_SITES))
        & (pd.to_numeric(df["power_mw"], errors="coerce") > 0)
    ].copy()

    rows = []
    for (sid, h), g in work.groupby(["site_id", "hour"]):
        train = g[g["split"] == "train"]
        valid = g[g["split"] == "valid"]
        if len(train) < 80 or len(valid) < 30:
            continue

        train_ratio = pred_actual_ratio(train)
        valid_ratio = pred_actual_ratio(valid)
        if not np.isfinite(train_ratio) or not np.isfinite(valid_ratio):
            continue

        # 只处理 train/valid 同向的极端偏差。
        stable_over = train_ratio > 1.35 and valid_ratio > 1.35
        stable_under = train_ratio < 0.75 and valid_ratio < 0.75
        if not (stable_over or stable_under):
            continue

        # train 学 k，valid 验证。
        k_raw = learn_train_k(train)
        if not np.isfinite(k_raw):
            continue

        # 更保守：向 1 收缩，避免直接套满 train 系数。
        k = 1.0 + 0.55 * (k_raw - 1.0)
        k = float(np.clip(k, 0.70, 1.25))

        valid_before = nrmse_pct(valid)
        valid_cand = apply_k(valid, k)
        valid_after = nrmse_pct(valid_cand, "power_pred_candidate")
        if not np.isfinite(valid_before) or not np.isfinite(valid_after):
            continue

        improve = valid_before - valid_after

        # valid 必须真正改善，且幅度不只是噪声。
        if improve < 0.20:
            continue

        rows.append({
            "site_id": sid,
            "hour": int(h),
            "train_rows": int(len(train)),
            "valid_rows": int(len(valid)),
            "bias_class": "stable_over_prediction" if stable_over else "stable_under_prediction",
            "train_ratio": round(float(train_ratio), 4),
            "valid_ratio": round(float(valid_ratio), 4),
            "k_raw_train": round(float(k_raw), 4),
            "k_final": round(float(k), 4),
            "valid_before_nrmse_pct": round(float(valid_before), 4),
            "valid_after_nrmse_pct": round(float(valid_after), 4),
            "valid_improvement_pp": round(float(improve), 4),
        })

    return pd.DataFrame(rows)


def apply_params(df, params):
    out = df.copy()
    out["_row_order"] = np.arange(len(out))
    if params.empty:
        out["round6_stable_bias_applied"] = False
        return out.drop(columns=["_row_order"])

    p = params[["site_id", "hour", "k_final"]].copy()
    out = out.merge(p, on=["site_id", "hour"], how="left")
    mask = out["hour"].isin(MIDDAY_HOURS) & out["k_final"].notna()
    cap = pd.to_numeric(out.loc[mask, "capacity_mw"], errors="coerce").fillna(0)
    pred = pd.to_numeric(out.loc[mask, "power_pred"], errors="coerce") * pd.to_numeric(out.loc[mask, "k_final"], errors="coerce")
    out.loc[mask, "power_pred"] = pred.clip(lower=0, upper=cap)
    out["round6_stable_bias_applied"] = False
    out.loc[mask, "round6_stable_bias_applied"] = True
    out = out.sort_values("_row_order").drop(columns=["_row_order", "k_final"])
    return out


def valid_ablation(before, after):
    rows = []
    for h in MIDDAY_HOURS:
        b = before[(before["split"] == "valid") & (before["hour"] == h)]
        a = after[(after["split"] == "valid") & (after["hour"] == h)]
        if b.empty or a.empty:
            continue
        bm = hourly_nrmse_metrics(b)
        am = hourly_nrmse_metrics(a)
        br = bm[bm["hour"] == h].iloc[0]
        ar = am[am["hour"] == h].iloc[0]
        rows.append({
            "hour": h,
            "before_site_nrmse_mean_pct": float(br["site_nrmse_mean_pct"]),
            "after_site_nrmse_mean_pct": float(ar["site_nrmse_mean_pct"]),
            "improvement_pp": float(br["site_nrmse_mean_pct"] - ar["site_nrmse_mean_pct"]),
            "before_city_nrmse_pct": float(br["city_nrmse_pct"]),
            "after_city_nrmse_pct": float(ar["city_nrmse_pct"]),
        })
    return pd.DataFrame(rows)


def main():
    in_path = IN_PATH if IN_PATH.exists() else FALLBACK_PATH
    if not in_path.exists():
        raise FileNotFoundError(in_path)

    print(f"读取: {in_path}")
    df = ensure_columns(safe_pickle_load(in_path))
    params = learn_params(df)
    params.to_csv(OUT_PARAMS, index=False, encoding="utf-8-sig")
    print(f"稳定偏差修正参数数量: {len(params)}")
    if not params.empty:
        print(params.to_string(index=False))

    corrected = apply_params(df, params)
    ab = valid_ablation(df, corrected)
    ab.to_csv(OUT_VALID, index=False, encoding="utf-8-sig")
    print("valid 消融:")
    print(ab.to_string(index=False))

    eval_df = build_eval_frame(
        corrected,
        split="test",
        hours=tuple(range(6, 20)),
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=53,
    )

    write_prediction_pickle_atomic(
        corrected,
        OUT_FULL,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
    )
    write_prediction_pickle_atomic(
        eval_df,
        OUT_EVAL,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
        hour_range=(6, 19),
    )

    hmet = hourly_nrmse_metrics(eval_df)
    hmet[hmet["hour"].isin(MIDDAY_HOURS)].to_csv(OUT_TEST, index=False, encoding="utf-8-sig")
    print("test 10-14 NRMSE，仅最终查看:")
    print(hmet[hmet["hour"].isin(MIDDAY_HOURS)].to_string(index=False))


if __name__ == "__main__":
    main()
```

---

## 8. 修改六：选择器接入 Round6 候选

打开：

```text
scripts/select_final_prediction_by_guard.py
```

在 `load_candidates()` 中 `MiddaySiteCalibrated` 后增加：

```python
    # Round6StableBias: 只对 train/valid 稳定极端偏差站点做保守修正
    try:
        round6_path = TABLES_DIR / "distributed_predictions_round6_stable_bias_full.pkl"
        if round6_path.exists():
            df = pd.read_pickle(round6_path)
            df["time"] = pd.to_datetime(df["time"])
            df["hour"] = df["time"].dt.hour
            candidates["Round6StableBias"] = df
            print(f"  Round6StableBias: {len(df):,} 行")
        else:
            print("  Round6StableBias: 文件不存在，跳过")
    except Exception as e:
        print(f"  Round6StableBias 加载失败: {e}")
```

将 midday 专用候选集合改为：

```python
elif ver in {"MiddaySiteCalibrated", "Round6StableBias"}:
```

### 8.1 重要安全逻辑

当前 Round5 里 10-14 点强制 `MiddaySiteCalibrated`。Round6 如果要测试新候选，需要允许 `Round6StableBias` 参与，但必须保留安全规则：

```python
if h in MIDDAY_NRMSE_PRIORITY_HOURS:
    # MiddaySiteCalibrated 是安全基准。
    # Round6StableBias 只有在 valid 的 site_nrmse_mean_pct 明确优于 MiddaySiteCalibrated 时才允许入选。
```

具体做法：

1. 对 `MiddaySiteCalibrated` 计算 valid 指标，作为 `midday_safe_metrics`。
2. 对 `Round6StableBias` 的 guard 不再只和 V1 比，而要和 `MiddaySiteCalibrated` 比。
3. 如果 `Round6StableBias` 没有优于 `MiddaySiteCalibrated`，则拒绝。

在 `select_per_hour()` 每个小时循环内，base 指标之后增加：

```python
        midday_safe_metrics = None
        if h in MIDDAY_NRMSE_PRIORITY_HOURS and "MiddaySiteCalibrated" in candidates:
            safe_h = candidates["MiddaySiteCalibrated"][candidates["MiddaySiteCalibrated"]["hour"] == h][["time", "site_id", "power_pred"]].copy()
            safe_h = safe_h.rename(columns={"power_pred": "safe_pred"})
            safe_merged = valid_h[["time", "site_id", "power_mw", "capacity_mw", "hour"]].merge(
                safe_h, on=["time", "site_id"], how="inner"
            )
            if len(safe_merged):
                midday_safe_metrics = compute_hour_metrics(safe_merged, "safe_pred")
                midday_safe_metrics["_ver"] = "MiddaySiteCalibrated"
```

在 `Round6StableBias` guard 中加入：

```python
                    compare_metrics = midday_safe_metrics if (ver == "Round6StableBias" and midday_safe_metrics is not None) else base_metrics
                    ref_site_nrmse = compare_metrics.get("site_nrmse_mean_pct", np.nan)
                    cand_site_nrmse = cand_metrics.get("site_nrmse_mean_pct", np.nan)

                    if ver == "Round6StableBias":
                        if np.isfinite(ref_site_nrmse) and np.isfinite(cand_site_nrmse):
                            if cand_site_nrmse > ref_site_nrmse - 0.05:
                                passed = False
                                reasons.append(
                                    f"Round6 未显著优于 MiddaySiteCalibrated: {cand_site_nrmse:.2f} >= safe-0.05 {ref_site_nrmse - 0.05:.2f}"
                                )
```

### 8.2 保留强制安全回退

如果最终 `Round6StableBias` 未通过，则 10-14 点仍应选择：

```text
MiddaySiteCalibrated
```

不要回退到 V1，也不要回退到 `MiddaySiteSelectiveCorrected`。

---

## 9. 修改七：新增 Round6 验收脚本

新建：

```text
scripts/check_round6_midday_gain.py
```

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
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

MIDDAY = [10, 11, 12, 13, 14]
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}


def eval_from_full(path):
    df = safe_pickle_load(path)
    return build_eval_frame(
        df,
        split="test",
        hours=tuple(range(6, 20)),
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=53,
    )


def main():
    safe_path = TABLES / "distributed_predictions_midday_site_calibrated_full.pkl"
    final_path = TABLES / "distributed_predictions_final_full.pkl"
    if not safe_path.exists():
        raise FileNotFoundError(safe_path)
    if not final_path.exists():
        raise FileNotFoundError(final_path)

    safe_eval = eval_from_full(safe_path)
    final_eval = eval_from_full(final_path)

    safe_h = hourly_nrmse_metrics(safe_eval)
    final_h = hourly_nrmse_metrics(final_eval)

    rows = []
    for h in MIDDAY:
        s = safe_h[safe_h["hour"] == h].iloc[0]
        f = final_h[final_h["hour"] == h].iloc[0]
        before = float(s["site_nrmse_mean_pct"])
        after = float(f["site_nrmse_mean_pct"])
        rows.append({
            "hour": h,
            "safe_site_nrmse_pct": round(before, 4),
            "final_site_nrmse_pct": round(after, 4),
            "improvement_pp": round(before - after, 4),
            "safe_city_nrmse_pct": round(float(s["city_nrmse_pct"]), 4),
            "final_city_nrmse_pct": round(float(f["city_nrmse_pct"]), 4),
        })

    out = pd.DataFrame(rows)
    out.to_csv(METRICS / "round6_midday_gain_vs_safe.csv", index=False, encoding="utf-8-sig")
    print(out.to_string(index=False))

    improved = int((out["improvement_pp"] > 0).sum())
    avg_drop = float(out["improvement_pp"].mean())
    worst_degrade = float((-out["improvement_pp"]).max())
    city_worse = float((out["final_city_nrmse_pct"] - out["safe_city_nrmse_pct"]).mean())

    print()
    print(f"改善小时数: {improved}/5")
    print(f"平均改善: {avg_drop:.4f} pp")
    print(f"最大单小时恶化: {worst_degrade:.4f} pp")
    print(f"城市 NRMSE 平均变化: {city_worse:.4f} pp")

    if worst_degrade > 0.2:
        raise SystemExit("[FAIL] Round6 造成单小时明显恶化")

    if avg_drop <= 0:
        print("[WARN] Round6 未带来增量提升，但安全回退有效。")
        return

    if improved >= 2 and avg_drop >= 0.1:
        print("[OK] Round6 有小幅增量改善")
    else:
        print("[WARN] Round6 改善很小，建议继续数据侧核查")


if __name__ == "__main__":
    main()
```

---

## 10. 修改八：更新总入口

打开：

```text
scripts/train_fixed.py
```

将 Round6 相关脚本加入 `FIX_SCRIPTS`，顺序如下：

```python
FIX_SCRIPTS = [
    ...
    "apply_midday_site_nrmse_calibration.py",
    "diagnose_midday_worst_site_hours.py",
    "diagnose_site_capacity_mapping_round6.py",
    "diagnose_midday_bias_stability_round6.py",
    "apply_site_metadata_overrides.py",
    "apply_midday_stable_bias_correction_round6.py",
    "select_final_prediction_by_guard.py",
    "check_midday_nrmse_improvement.py",
    "check_round6_midday_gain.py",
    "update_project_md_metrics.py",
]
```

建议 critical 设置：

| 脚本 | critical |
|---|---|
| `diagnose_site_capacity_mapping_round6.py` | 否 |
| `diagnose_midday_bias_stability_round6.py` | 否 |
| `apply_site_metadata_overrides.py` | 是 |
| `apply_midday_stable_bias_correction_round6.py` | 是 |
| `check_round6_midday_gain.py` | 否 |

---

## 11. Cursor 执行顺序

在项目根目录执行：

```bash
python scripts/apply_midday_site_nrmse_calibration.py
python scripts/diagnose_midday_worst_site_hours.py
python scripts/diagnose_site_capacity_mapping_round6.py
python scripts/diagnose_midday_bias_stability_round6.py
python scripts/apply_site_metadata_overrides.py
python scripts/apply_midday_stable_bias_correction_round6.py
python scripts/select_final_prediction_by_guard.py
python scripts/check_midday_nrmse_improvement.py
python scripts/check_round6_midday_gain.py
python scripts/update_project_md_metrics.py
```

---

## 12. 运行后必须检查的文件

```text
output/pv_pipeline/metrics/round6_watch_site_diagnosis.csv
output/pv_pipeline/metrics/round6_flagged_site_diagnosis.csv
output/pv_pipeline/metrics/round6_midday_bias_stability_summary.csv
output/pv_pipeline/metrics/round6_stable_extreme_bias_candidates.csv
output/pv_pipeline/metrics/round6_site_metadata_overrides_applied.csv
output/pv_pipeline/metrics/round6_stable_bias_correction_params.csv
output/pv_pipeline/metrics/round6_stable_bias_valid_ablation.csv
output/pv_pipeline/metrics/round6_stable_bias_test_hourly_nrmse.csv
output/pv_pipeline/metrics/round6_midday_gain_vs_safe.csv
output/pv_pipeline/metrics/final_version_selection_by_hour.csv
output/pv_pipeline/docs/当前最终结果摘要.md
```

---

## 13. 如何判断 Round6 是否有效

### 13.1 如果 final 仍是 MiddaySiteCalibrated

说明 Round6 修正没有被证明更好，但安全回退有效。此时不算失败，说明现有数据条件下自动修正不可靠。

### 13.2 如果 final 部分小时选择 Round6StableBias

查看：

```text
output/pv_pipeline/metrics/round6_midday_gain_vs_safe.csv
```

满足以下条件才认为有效：

| 条件 | 要求 |
|---|---|
| 改善小时数 | ≥ 2/5 |
| 平均改善 | > 0 |
| 最大单小时恶化 | ≤ 0.2 pp |
| 城市 NRMSE | 不明显变差 |

### 13.3 如果 S012/S055/S050/S032 被标记为异常

查看：

```text
output/pv_pipeline/metrics/round6_watch_site_diagnosis.csv
```

如果这些站点出现以下标记：

```text
p99_power_exceeds_capacity
max_power_exceeds_capacity
midday_prediction_over_high
midday_prediction_too_low
```

下一步应人工核查站点台账和功率列，不要继续自动调参数。

---

## 14. 预期结果

Round6 最可能出现三种情况：

### 情况 A：发现容量或映射异常

这是最有价值的结果。说明 10-14 点高误差并不是模型问题，而是数据侧问题。应人工修正 `config/site_metadata_overrides.csv` 后重新运行。

### 情况 B：发现稳定偏差，Round6StableBias 小幅改善

说明少数站点确实存在跨 train/valid 稳定偏差，可以保守修正。预期 10-14 点平均站点 NRMSE 下降 0.1-0.4 pp。

### 情况 C：Round6 没有增量提升

说明当前自动后处理已经到边界。下一步必须回到：

1. 站点映射核验；
2. 容量台账核验；
3. 气象和辐照特征；
4. 针对异常站点的单独建模。

---

## 15. 本轮不要做的事

1. 不要再用 test 集选择参数。
2. 不要继续扩大 alpha/k 网格搜索。
3. 不要把 valid 上好、test 上差的候选强行写入 final。
4. 不要自动修改容量，必须通过 `config/site_metadata_overrides.csv` 人工确认。
5. 不要把 S012/S055/S050/S032 直接删除，除非任务书允许剔除异常站点，并且报告中明确说明。

Round6 的核心目标是把问题从“盲目调模型”推进到“定位高误差站点为什么异常”。

