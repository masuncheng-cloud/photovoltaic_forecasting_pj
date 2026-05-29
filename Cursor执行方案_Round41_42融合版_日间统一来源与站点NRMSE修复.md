# Round41+42 融合版：日间统一来源与站点平均 NRMSE 修复

## 一、为什么融合

当前 Round41 还没有执行，而 Round42 是建立在“已有最终预测列”基础上的站点级校准。

如果先执行 Round41，再执行 Round42，会连续覆盖：

```text
power_pred_final
```

容易出现：

```text
快照混乱
守门指标对应不上
可视化导出读到旧列
回退困难
```

因此本轮合并为一次执行：

```text
Step A：保留 Round40 早晚不贴 0 的成果；
Step B：选择一个统一的日间预测来源，优化 10-14 全市逐小时 NRMSE；
Step C：在 A+B 结果上做站点级偏差校准，降低站点平均 NRMSE；
Step D：统一守门；
Step E：通过则导出 dashboard，失败则回退。
```

---

## 二、本轮策略

### 2.1 不再逐小时拼接多个来源

不要采用：

```text
10点用A，11点用B，12点用C
```

改成：

```text
6、7、18、19：边缘小时保护；
8-17：统一使用一个 daytime_source。
```

### 2.2 日间统一来源选择

在 `valid` 集上比较候选列：

```text
power_pred
power_pred_cal
pred_calibrated
power_pred_final_round40_snapshot
power_pred_final
```

选择目标：

```text
10-14 点全市逐小时 NRMSE 平均值最低
```

选出的列作为：

```text
8-17 点统一来源 daytime_source
```

### 2.3 站点级校准

在 `train + valid` 上学习站点级缩放系数：

```text
alpha_site = sum(actual * pred) / sum(pred^2)
```

只使用有效发电样本：

```text
actual_mw > max(0.02 * capacity_mw, 0.05 MW)
```

并做 shrinkage：

```text
alpha_final = w * alpha_site + (1 - w) * 1
w = n / (n + 500)
alpha_final 限制在 [0.70, 1.30]
```

---

## 三、新增融合脚本

新增：

```text
scripts/round41_42_unified_daytime_and_site_calibration.py
```

内容如下：

```python
from pathlib import Path
import json
import math
import shutil
import numpy as np
import pandas as pd


ROOT = Path("output/pv_pipeline")
TABLE_DIR = ROOT / "tables"
METRIC_DIR = ROOT / "metrics"
METRIC_DIR.mkdir(parents=True, exist_ok=True)

EDGE_HOURS = [6, 7, 18, 19]
DAYTIME_HOURS = list(range(8, 18))
FOCUS_HOURS = [10, 11, 12, 13, 14]


def find_final_pkl():
    candidates = sorted(TABLE_DIR.glob("distributed_predictions_final_round*.pkl"))
    if candidates:
        return candidates[-1]
    for name in ["distributed_predictions_final_full.pkl", "distributed_predictions_final.pkl"]:
        p = TABLE_DIR / name
        if p.exists():
            return p
    raise FileNotFoundError("找不到 distributed_predictions_final*.pkl")


def normalize(df):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    if "date" not in df.columns:
        df["date"] = df["time"].dt.strftime("%Y-%m-%d")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    return df


def candidate_columns(df):
    cols = []
    for c in [
        "power_pred",
        "power_pred_cal",
        "pred_calibrated",
        "power_pred_final_round40_snapshot",
        "power_pred_final",
    ]:
        if c in df.columns and c not in cols:
            cols.append(c)
    return cols


def rmse(x):
    x = np.asarray(x, dtype=float)
    return math.sqrt(float(np.mean(x * x))) if len(x) else np.nan


def city_hour_metrics(df, pred_col, split, hours):
    work = df[
        df["split"].eq(split)
        & df["hour"].isin(hours)
        & df["power_mw"].notna()
        & df[pred_col].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()
    if work.empty:
        return None

    work["actual_mw"] = pd.to_numeric(work["power_mw"], errors="coerce")
    work["pred_mw"] = pd.to_numeric(work[pred_col], errors="coerce")
    work["capacity_mw"] = pd.to_numeric(work["capacity_mw"], errors="coerce")
    work = work[work["actual_mw"].notna() & work["pred_mw"].notna()].copy()
    if work.empty:
        return None

    rows = []
    for hour, hdf in work.groupby("hour"):
        city = (
            hdf.groupby("time", as_index=False)
            .agg(
                actual_mw=("actual_mw", "sum"),
                pred_mw=("pred_mw", "sum"),
                capacity_sum_mw=("capacity_mw", "sum"),
                site_count=("site_id", "nunique"),
            )
        )
        err = city["pred_mw"] - city["actual_mw"]
        rmse_mw = rmse(err)
        cap = float(city["capacity_sum_mw"].mean())
        nrmse = rmse_mw / max(cap, 1e-9) * 100
        bias = (city["pred_mw"].sum() - city["actual_mw"].sum()) / max(city["actual_mw"].sum(), 1e-9) * 100
        suspicious_zero = int(((city["actual_mw"] > 1e-9) & (city["pred_mw"].abs() <= 1e-9)).sum())
        rows.append({
            "hour": int(hour),
            "samples": int(len(city)),
            "city_nrmse_pct": float(nrmse),
            "city_bias_pct": float(bias),
            "suspicious_city_zero_count": suspicious_zero,
        })

    h = pd.DataFrame(rows)
    return {
        "pred_col": pred_col,
        "split": split,
        "hours": ",".join(map(str, hours)),
        "hour_count": int(h["hour"].nunique()),
        "mean_hourly_city_nrmse_pct": round(float(h["city_nrmse_pct"].mean()), 6),
        "max_hourly_city_nrmse_pct": round(float(h["city_nrmse_pct"].max()), 6),
        "mean_abs_bias_pct": round(float(h["city_bias_pct"].abs().mean()), 6),
        "total_suspicious_city_zero_count": int(h["suspicious_city_zero_count"].sum()),
    }


def select_daytime_source(df, cols):
    rows = []
    for col in cols:
        m = city_hour_metrics(df, col, "valid", FOCUS_HOURS)
        if m is not None:
            rows.append(m)
    if not rows:
        raise RuntimeError("valid 集无法计算 10-14 候选来源指标")
    table = pd.DataFrame(rows).sort_values(
        ["mean_hourly_city_nrmse_pct", "mean_abs_bias_pct"],
        ascending=[True, True],
    )
    selected = table.iloc[0].to_dict()
    return table, selected


def apply_unified_daytime_source(df, daytime_source):
    out = df.copy()
    if "power_pred_final_round40_snapshot" not in out.columns:
        out["power_pred_final_round40_snapshot"] = out["power_pred_final"]

    out["power_pred_final_before_round41_42"] = out["power_pred_final"]
    out["power_pred_round41_daytime"] = out["power_pred_final_round40_snapshot"]

    # 边缘小时：优先 power_pred_cal，保留早晚不贴 0 的成果
    if "power_pred_cal" in out.columns:
        edge_mask = out["hour"].isin(EDGE_HOURS) & out["power_pred_cal"].notna()
        out.loc[edge_mask, "power_pred_round41_daytime"] = out.loc[edge_mask, "power_pred_cal"]

    # 日间主体小时：统一使用 daytime_source
    day_mask = out["hour"].isin(DAYTIME_HOURS) & out[daytime_source].notna()
    out.loc[day_mask, "power_pred_round41_daytime"] = out.loc[day_mask, daytime_source]

    out["power_pred_round41_daytime"] = pd.to_numeric(out["power_pred_round41_daytime"], errors="coerce").clip(lower=0)
    out["power_pred_final"] = out["power_pred_round41_daytime"]
    return out


def fit_site_alpha(df):
    train = df[
        df["split"].isin(["train", "valid"])
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df["power_pred_final"].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()

    train["power_mw"] = pd.to_numeric(train["power_mw"], errors="coerce")
    train["power_pred_final"] = pd.to_numeric(train["power_pred_final"], errors="coerce")
    train["capacity_mw"] = pd.to_numeric(train["capacity_mw"], errors="coerce")
    train["active_threshold_mw"] = np.maximum(0.02 * train["capacity_mw"], 0.05)
    train = train[train["power_mw"] > train["active_threshold_mw"]].copy()

    rows = []
    for sid, g in train.groupby("site_id"):
        y = g["power_mw"].to_numpy(dtype=float)
        p = g["power_pred_final"].to_numpy(dtype=float)

        valid = np.isfinite(y) & np.isfinite(p) & (p > 1e-9)
        y = y[valid]
        p = p[valid]
        n = len(y)

        if n < 50:
            alpha_raw = 1.0
            alpha = 1.0
            w = 0.0
        else:
            alpha_raw = float(np.sum(y * p) / max(np.sum(p * p), 1e-9))
            alpha_raw = float(np.clip(alpha_raw, 0.70, 1.30))
            w = float(n / (n + 500))
            alpha = float(w * alpha_raw + (1 - w) * 1.0)

        rows.append({
            "site_id": sid,
            "fit_samples": int(n),
            "alpha_raw_clipped": round(alpha_raw, 8),
            "alpha": round(alpha, 8),
            "weight": round(w, 8),
        })

    return pd.DataFrame(rows)


def apply_site_calibration(df, alpha):
    out = df.merge(alpha[["site_id", "alpha"]], on="site_id", how="left")
    out["alpha"] = out["alpha"].fillna(1.0)
    out["power_pred_final_before_round42_site_cal"] = out["power_pred_final"]
    out["power_pred_round42_site_cal"] = out["power_pred_final"] * out["alpha"]
    out["power_pred_round42_site_cal"] = out["power_pred_round42_site_cal"].clip(lower=0)
    out["power_pred_round42_site_cal"] = np.minimum(out["power_pred_round42_site_cal"], out["capacity_mw"])
    out["power_pred_final"] = out["power_pred_round42_site_cal"]
    out = out.drop(columns=["alpha"])
    return out


def metric_site_summary(df):
    work = df[
        df["split"].eq("test")
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df["power_pred_final"].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()
    work["power_mw"] = pd.to_numeric(work["power_mw"], errors="coerce")
    work["power_pred_final"] = pd.to_numeric(work["power_pred_final"], errors="coerce")
    work["capacity_mw"] = pd.to_numeric(work["capacity_mw"], errors="coerce")
    work["active_threshold_mw"] = np.maximum(0.02 * work["capacity_mw"], 0.05)
    work["is_active_actual"] = work["power_mw"] > work["active_threshold_mw"]

    rows = []
    for sid, g in work.groupby("site_id"):
        err = g["power_pred_final"] - g["power_mw"]
        cap = float(g["capacity_mw"].mean())
        nrmse = rmse(err) / max(cap, 1e-9) * 100
        active = g[g["is_active_actual"]]
        if len(active):
            aerr = active["power_pred_final"] - active["power_mw"]
            active_nrmse = rmse(aerr) / max(cap, 1e-9) * 100
        else:
            active_nrmse = np.nan
        rows.append({
            "site_id": sid,
            "full_nrmse_pct": float(nrmse),
            "active_nrmse_pct": float(active_nrmse) if np.isfinite(active_nrmse) else np.nan,
        })

    s = pd.DataFrame(rows)
    return {
        "site_count": int(len(s)),
        "full_site_mean_nrmse_pct": round(float(s["full_nrmse_pct"].mean()), 6),
        "full_site_median_nrmse_pct": round(float(s["full_nrmse_pct"].median()), 6),
        "active_site_mean_nrmse_pct": round(float(s["active_nrmse_pct"].mean()), 6),
        "active_site_median_nrmse_pct": round(float(s["active_nrmse_pct"].median()), 6),
    }


def main():
    pkl = find_final_pkl()
    backup = pkl.with_suffix(".before_round41_42.pkl")
    shutil.copy2(pkl, backup)
    print("[OK] backup:", backup)

    df = pd.read_pickle(pkl)
    df = normalize(df)

    if "power_pred_final_round40_snapshot" not in df.columns:
        df["power_pred_final_round40_snapshot"] = df["power_pred_final"]

    cols = candidate_columns(df)
    selection_table, selected = select_daytime_source(df, cols)
    daytime_source = selected["pred_col"]

    selection_table.to_csv(METRIC_DIR / "round41_42_daytime_source_selection.csv", index=False, encoding="utf-8-sig")
    selection_info = {
        "strategy": "edge_protection_plus_unified_daytime_source_plus_site_bias_calibration",
        "edge_hours": EDGE_HOURS,
        "daytime_hours": DAYTIME_HOURS,
        "focus_hours_for_daytime_source_selection": FOCUS_HOURS,
        "selected_daytime_source": daytime_source,
        "selected_valid_metrics": selected,
    }
    (METRIC_DIR / "round41_42_selection_info.json").write_text(
        json.dumps(selection_info, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    df1 = apply_unified_daytime_source(df, daytime_source)

    alpha = fit_site_alpha(df1)
    alpha.to_csv(METRIC_DIR / "round41_42_site_bias_alpha.csv", index=False, encoding="utf-8-sig")

    df2 = apply_site_calibration(df1, alpha)

    site_summary = pd.DataFrame([metric_site_summary(df2)])
    site_summary.to_csv(METRIC_DIR / "round41_42_site_summary_after.csv", index=False, encoding="utf-8-sig")

    tmp = pkl.with_suffix(".round41_42.tmp.pkl")
    df2.to_pickle(tmp)
    check = pd.read_pickle(tmp)
    assert len(check) == len(df2)
    assert "power_pred_final" in check.columns
    tmp.replace(pkl)

    print("[OK] updated:", pkl)
    print("[OK] selected daytime source:", daytime_source)
    print(selection_table.to_string(index=False))
    print(site_summary.to_string(index=False))
    print("[OK] wrote round41_42 metrics")


if __name__ == "__main__":
    main()
```

---

## 四、新增融合守门脚本

新增：

```text
scripts/round41_42_guard.py
```

内容：

```python
from pathlib import Path
import shutil
import pandas as pd


ROOT = Path("output/pv_pipeline")
TABLE_DIR = ROOT / "tables"
METRIC_DIR = ROOT / "metrics"


def find_final_pkl():
    candidates = sorted(TABLE_DIR.glob("distributed_predictions_final_round*.pkl"))
    if candidates:
        return candidates[-1]
    return TABLE_DIR / "distributed_predictions_final_full.pkl"


def main():
    pkl = find_final_pkl()
    backup = pkl.with_suffix(".before_round41_42.pkl")

    city_summary = pd.read_csv(METRIC_DIR / "round40_prediction_column_compare_summary.csv")
    final = city_summary[city_summary["pred_col"].eq("power_pred_final")].iloc[0]

    hourly = pd.read_csv(METRIC_DIR / "round40_prediction_column_compare_hourly.csv")
    final_hour = hourly[hourly["pred_col"].eq("power_pred_final")]
    edge = final_hour[final_hour["hour"].isin([6, 7, 18, 19])]
    focus = final_hour[final_hour["hour"].isin([10, 11, 12, 13, 14])]

    site_summary = pd.read_csv(METRIC_DIR / "round41_42_site_summary_after.csv").iloc[0]

    checks = []
    checks.append({
        "check": "edge_suspicious_city_zero_count",
        "value": int(edge["suspicious_city_zero_count"].sum()),
        "threshold": 0,
        "status": "PASS" if int(edge["suspicious_city_zero_count"].sum()) == 0 else "FAIL",
    })
    checks.append({
        "check": "focus_10_14_city_hourly_nrmse_under_6",
        "value": round(float(focus["city_nrmse_pct"].mean()), 6),
        "threshold": 6.0,
        "status": "PASS" if float(focus["city_nrmse_pct"].mean()) <= 6.0 else "FAIL",
    })
    checks.append({
        "check": "city_nrmse_under_10",
        "value": round(float(final["city_nrmse_pct"]), 6),
        "threshold": 10.0,
        "status": "PASS" if float(final["city_nrmse_pct"]) <= 10.0 else "FAIL",
    })
    checks.append({
        "check": "city_abs_bias_under_15",
        "value": round(abs(float(final["city_bias_pct"])), 6),
        "threshold": 15.0,
        "status": "PASS" if abs(float(final["city_bias_pct"])) <= 15.0 else "FAIL",
    })
    checks.append({
        "check": "full_site_mean_nrmse_under_35",
        "value": round(float(site_summary["full_site_mean_nrmse_pct"]), 6),
        "threshold": 35.0,
        "status": "PASS" if float(site_summary["full_site_mean_nrmse_pct"]) <= 35.0 else "FAIL",
    })
    checks.append({
        "check": "active_site_mean_nrmse_under_25",
        "value": round(float(site_summary["active_site_mean_nrmse_pct"]), 6),
        "threshold": 25.0,
        "status": "PASS" if float(site_summary["active_site_mean_nrmse_pct"]) <= 25.0 else "FAIL",
    })

    out = pd.DataFrame(checks)
    out.to_csv(METRIC_DIR / "round41_42_guard.csv", index=False, encoding="utf-8-sig")
    print(out.to_string(index=False))

    if (out["status"] == "FAIL").any():
        if backup.exists():
            shutil.copy2(backup, pkl)
            print("[RESTORE] guard failed, restored:", pkl)
        raise SystemExit("[FAIL] Round41+42 guard failed")

    print("[PASS] Round41+42 guard passed")


if __name__ == "__main__":
    main()
```

---

## 五、执行顺序

执行融合脚本：

```bash
python scripts/round41_42_unified_daytime_and_site_calibration.py
```

重新计算指标：

```bash
python scripts/round40_compare_final_prediction_metrics.py
```

执行守门：

```bash
python scripts/round41_42_guard.py
```

如果守门通过，再导出可视化：

```bash
python scripts/export_interactive_dashboard_data.py
python scripts/check_dashboard_city_series_consistency_round40.py
python scripts/check_dashboard_prediction_values_round36.py
python scripts/posttrain_validation_round36.py
```

如果守门失败，`round41_42_guard.py` 会自动恢复：

```text
distributed_predictions_final*.before_round41_42.pkl
```

---

## 六、输出文件

生成：

```text
output/pv_pipeline/metrics/round41_42_daytime_source_selection.csv
output/pv_pipeline/metrics/round41_42_selection_info.json
output/pv_pipeline/metrics/round41_42_site_bias_alpha.csv
output/pv_pipeline/metrics/round41_42_site_summary_after.csv
output/pv_pipeline/metrics/round41_42_guard.csv
```

---

## 七、验收标准

必须满足：

1. 8-17 点只使用一个统一 `daytime_source`，不出现 10-14 每小时不同来源。
2. 6、7、18、19 仍无整城预测为 0。
3. 10-14 全市逐小时 NRMSE 平均值不高于 6%。
4. 全市整体 NRMSE 不高于 10%。
5. 全市 BIAS 绝对值不高于 15%。
6. 完整口径站点平均 NRMSE 不高于 35%。
7. 有效发电口径站点平均 NRMSE 不高于 25%。
8. dashboard 数据与 final pkl 一致。

---

## 八、页面和报告说明

写入报告时说明：

```text
最终预测采用分时段统一策略：
早晚临界小时（6、7、18、19）使用边缘保护预测，避免低 GHI 硬置零；
日间主体小时（8-17）统一使用验证集 10-14 全市逐小时 NRMSE 最优的预测来源；
随后使用 train+valid 有效发电样本学习站点级缩放系数，对单站点系统偏差进行收缩校准。
```

不要写：

```text
每小时独立选择最优来源
```

---

## 九、如果结果不理想

如果守门失败，不要强行发布。

优先看：

```text
round41_42_daytime_source_selection.csv
round41_42_site_bias_alpha.csv
round41_42_guard.csv
```

如果 10-14 未改善：

```text
在统一 daytime_source 基础上增加一个 10-14 统一缩放系数 alpha_midday。
```

如果站点 NRMSE 未改善：

```text
分组处理异常站点，而不是继续放大站点校准系数。
```

---

## 十、完成后回传

请回传：

```text
output/pv_pipeline/metrics/round41_42_daytime_source_selection.csv
output/pv_pipeline/metrics/round41_42_selection_info.json
output/pv_pipeline/metrics/round41_42_site_bias_alpha.csv
output/pv_pipeline/metrics/round41_42_site_summary_after.csv
output/pv_pipeline/metrics/round41_42_guard.csv
output/pv_pipeline/metrics/round40_prediction_column_compare_summary.csv
output/pv_pipeline/metrics/round40_prediction_column_compare_hourly.csv
```

以及页面截图：

```text
全市 10-14
全市 6-19
逐小时 NRMSE 表
典型站点表
```

