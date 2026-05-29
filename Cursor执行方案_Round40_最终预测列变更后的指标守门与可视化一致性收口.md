# Round40：最终预测列变更后的指标守门与可视化一致性收口

## 一、当前背景

Round39.11 已经定位并修复了早晚临界小时预测大量为 0 的问题：

```text
原问题：power_pred 在 ghi < 5 时被硬置零，导致 6、7、18、19 点预测大量为 0
修复：apply_round36_calibration.py 改用 power_pred_cal 作为最终预测基础列
```

这次修复是有效方向，但它改变了最终预测列 `power_pred_final` 的来源，因此必须做一次完整守门：

```text
不能只看 6/7/18/19 修好了；
还必须确认整体 NRMSE、10-14 点 NRMSE、单站点 NRMSE 没被误伤；
同时确认 dashboard 展示数据与 final pkl 完全一致。
```

本轮不重新训练，只做：

1. 指标重算；
2. 修复前后对比；
3. 自动守门；
4. 可视化导出一致性校验；
5. 页面文案修正。

---

## 二、修改目标

### 2.1 指标守门

对比修复前与修复后：

```text
全市整体 NRMSE
全市逐小时 NRMSE
单站点平均 NRMSE
单站点中位 NRMSE
10-14 点全市 NRMSE
10-14 点站点平均 NRMSE
6/7/18/19 点全市 NRMSE
6/7/18/19 点站点平均 NRMSE
BIAS
pred/actual
```

### 2.2 守门规则

如果修复后满足：

```text
6/7/18/19 suspicious_city_zero_count = 0
6/7/18/19 NRMSE 明显改善或不恶化
10-14 点 NRMSE 不明显变差
整体 NRMSE 不明显变差
```

则保留当前 `power_pred_final`。

如果修复后整体或 10-14 明显变差，则不要全量回退，而是改成“小时级选择”：

```text
6/7/18/19 使用 power_pred_cal
8-17 使用原先更优的预测列
```

---

## 三、新增指标对比脚本

新增：

```text
scripts/round40_compare_final_prediction_metrics.py
```

内容如下：

```python
from pathlib import Path
import json
import math
import numpy as np
import pandas as pd


ROOT = Path("output/pv_pipeline")
TABLE_DIR = ROOT / "tables"
METRIC_DIR = ROOT / "metrics"
METRIC_DIR.mkdir(parents=True, exist_ok=True)


def find_final_pkl():
    candidates = sorted(TABLE_DIR.glob("distributed_predictions_final_round*.pkl"))
    if candidates:
        return candidates[-1]
    for name in ["distributed_predictions_final_full.pkl", "distributed_predictions_final.pkl"]:
        p = TABLE_DIR / name
        if p.exists():
            return p
    raise FileNotFoundError("找不到 distributed_predictions_final*.pkl")


def normalize_frame(df):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    if "date" not in df.columns:
        df["date"] = df["time"].dt.strftime("%Y-%m-%d")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    return df


def eval_frame(df, pred_col):
    df = normalize_frame(df)
    work = df.copy()
    if "split" in work.columns:
        work = work[work["split"].eq("test")].copy()
    work = work[
        work["hour"].between(6, 19)
        & work["power_mw"].notna()
        & work[pred_col].notna()
        & work["capacity_mw"].notna()
        & (work["capacity_mw"] > 0)
    ].copy()
    work["actual_mw"] = pd.to_numeric(work["power_mw"], errors="coerce")
    work["pred_mw"] = pd.to_numeric(work[pred_col], errors="coerce")
    work = work[work["actual_mw"].notna() & work["pred_mw"].notna()].copy()
    return work


def rmse(a):
    a = np.asarray(a, dtype=float)
    return math.sqrt(float(np.mean(a * a))) if len(a) else np.nan


def city_metrics(work):
    city = (
        work.groupby("time", as_index=False)
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
    mae = float(err.abs().mean())
    bias = (city["pred_mw"].sum() - city["actual_mw"].sum()) / max(city["actual_mw"].sum(), 1e-9) * 100
    ratio = city["pred_mw"].sum() / max(city["actual_mw"].sum(), 1e-9)
    return {
        "city_samples": int(len(city)),
        "city_mae_mw": round(mae, 6),
        "city_rmse_mw": round(rmse_mw, 6),
        "city_capacity_mw": round(cap, 6),
        "city_nrmse_pct": round(nrmse, 6),
        "city_bias_pct": round(bias, 6),
        "city_pred_actual": round(ratio, 6),
    }


def city_hourly_metrics(work):
    city = (
        work.groupby(["time", "hour"], as_index=False)
        .agg(
            actual_mw=("actual_mw", "sum"),
            pred_mw=("pred_mw", "sum"),
            capacity_sum_mw=("capacity_mw", "sum"),
            site_count=("site_id", "nunique"),
        )
    )
    out = []
    for h, g in city.groupby("hour"):
        err = g["pred_mw"] - g["actual_mw"]
        rmse_mw = rmse(err)
        cap = float(g["capacity_sum_mw"].mean())
        nrmse = rmse_mw / max(cap, 1e-9) * 100
        suspicious_zero = int(((g["actual_mw"] > 1e-9) & (g["pred_mw"].abs() <= 1e-9)).sum())
        out.append({
            "hour": int(h),
            "samples": int(len(g)),
            "city_actual_mean_mw": round(float(g["actual_mw"].mean()), 6),
            "city_pred_mean_mw": round(float(g["pred_mw"].mean()), 6),
            "city_rmse_mw": round(rmse_mw, 6),
            "city_nrmse_pct": round(nrmse, 6),
            "suspicious_city_zero_count": suspicious_zero,
        })
    return pd.DataFrame(out).sort_values("hour")


def site_metrics(work):
    out = []
    for sid, g in work.groupby("site_id"):
        err = g["pred_mw"] - g["actual_mw"]
        rmse_mw = rmse(err)
        mae = float(err.abs().mean())
        cap = float(g["capacity_mw"].mean())
        actual_sum = float(g["actual_mw"].sum())
        pred_sum = float(g["pred_mw"].sum())
        out.append({
            "site_id": sid,
            "site_name": g["site_name"].iloc[0] if "site_name" in g.columns else sid,
            "samples": int(len(g)),
            "capacity_mw": round(cap, 6),
            "mae_mw": round(mae, 6),
            "rmse_mw": round(rmse_mw, 6),
            "nrmse_pct": round(rmse_mw / max(cap, 1e-9) * 100, 6),
            "bias_pct": round((pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100, 6),
            "pred_actual": round(pred_sum / max(actual_sum, 1e-9), 6),
        })
    return pd.DataFrame(out).sort_values("nrmse_pct")


def subset_summary(work, hours, label):
    sub = work[work["hour"].isin(hours)].copy()
    if sub.empty:
        return {"label": label, "samples": 0}
    cm = city_metrics(sub)
    sm = site_metrics(sub)
    return {
        "label": label,
        "samples": int(len(sub)),
        "city_nrmse_pct": cm["city_nrmse_pct"],
        "city_bias_pct": cm["city_bias_pct"],
        "site_mean_nrmse_pct": round(float(sm["nrmse_pct"].mean()), 6),
        "site_median_nrmse_pct": round(float(sm["nrmse_pct"].median()), 6),
    }


def main():
    pkl = find_final_pkl()
    df = pd.read_pickle(pkl)

    pred_cols = [c for c in ["power_pred_final", "power_pred_cal", "power_pred", "pred_calibrated"] if c in df.columns]
    if "power_pred_final" not in pred_cols:
        raise AssertionError("缺少 power_pred_final")

    summaries = []
    hourly_tables = []
    site_tables = []

    for col in pred_cols:
        work = eval_frame(df, col)
        cm = city_metrics(work)
        sm = site_metrics(work)
        row = {
            "pred_col": col,
            "rows": int(len(work)),
            "site_count": int(work["site_id"].nunique()),
            **cm,
            "site_mean_nrmse_pct": round(float(sm["nrmse_pct"].mean()), 6),
            "site_median_nrmse_pct": round(float(sm["nrmse_pct"].median()), 6),
        }
        row.update({f"edge_{k}": v for k, v in subset_summary(work, [6,7,18,19], "edge").items() if k != "label"})
        row.update({f"midday_{k}": v for k, v in subset_summary(work, [10,11,12,13,14], "midday").items() if k != "label"})
        summaries.append(row)

        h = city_hourly_metrics(work)
        h.insert(0, "pred_col", col)
        hourly_tables.append(h)

        s = sm.copy()
        s.insert(0, "pred_col", col)
        site_tables.append(s)

    summary = pd.DataFrame(summaries)
    hourly = pd.concat(hourly_tables, ignore_index=True)
    sites = pd.concat(site_tables, ignore_index=True)

    summary.to_csv(METRIC_DIR / "round40_prediction_column_compare_summary.csv", index=False, encoding="utf-8-sig")
    hourly.to_csv(METRIC_DIR / "round40_prediction_column_compare_hourly.csv", index=False, encoding="utf-8-sig")
    sites.to_csv(METRIC_DIR / "round40_prediction_column_compare_sites.csv", index=False, encoding="utf-8-sig")

    print("[OK] pkl:", pkl)
    print(summary.to_string(index=False))
    print("[OK] wrote round40 comparison csv files")


if __name__ == "__main__":
    main()
```

执行：

```bash
python scripts/round40_compare_final_prediction_metrics.py
```

---

## 四、新增守门脚本

新增：

```text
scripts/round40_guard_final_prediction.py
```

内容：

```python
from pathlib import Path
import pandas as pd


ROOT = Path("output/pv_pipeline")
METRIC_DIR = ROOT / "metrics"


def main():
    summary_path = METRIC_DIR / "round40_prediction_column_compare_summary.csv"
    hourly_path = METRIC_DIR / "round40_prediction_column_compare_hourly.csv"

    summary = pd.read_csv(summary_path)
    hourly = pd.read_csv(hourly_path)

    required = {"power_pred_final", "power_pred_cal"}
    present = set(summary["pred_col"])
    missing = required - present
    if missing:
        raise AssertionError(f"缺少对比预测列: {missing}")

    final = summary[summary["pred_col"].eq("power_pred_final")].iloc[0]
    cal = summary[summary["pred_col"].eq("power_pred_cal")].iloc[0]

    checks = []

    # 1. 早晚临界小时不允许整城预测为 0
    final_hour = hourly[hourly["pred_col"].eq("power_pred_final")]
    edge = final_hour[final_hour["hour"].isin([6, 7, 18, 19])]
    suspicious_total = int(edge["suspicious_city_zero_count"].sum())
    checks.append({
        "check": "edge_suspicious_city_zero",
        "status": "PASS" if suspicious_total == 0 else "FAIL",
        "value": suspicious_total,
        "threshold": 0,
    })

    # 2. 10-14 不得明显劣化：相对 power_pred_cal 不高于 3 个百分点
    midday_delta = float(final["midday_city_nrmse_pct"] - cal["midday_city_nrmse_pct"])
    checks.append({
        "check": "midday_city_nrmse_not_worse_than_cal_by_3pp",
        "status": "PASS" if midday_delta <= 3.0 else "FAIL",
        "value": round(midday_delta, 6),
        "threshold": 3.0,
    })

    # 3. 整体不应离谱：全市整体 NRMSE 不超过 10%
    city_nrmse = float(final["city_nrmse_pct"])
    checks.append({
        "check": "overall_city_nrmse_under_10pct",
        "status": "PASS" if city_nrmse <= 10.0 else "FAIL",
        "value": round(city_nrmse, 6),
        "threshold": 10.0,
    })

    # 4. BIAS 不应明显偏置：绝对值不超过 15%
    bias = abs(float(final["city_bias_pct"]))
    checks.append({
        "check": "overall_city_abs_bias_under_15pct",
        "status": "PASS" if bias <= 15.0 else "FAIL",
        "value": round(bias, 6),
        "threshold": 15.0,
    })

    out = pd.DataFrame(checks)
    out_path = METRIC_DIR / "round40_final_prediction_guard.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(out.to_string(index=False))
    if (out["status"] == "FAIL").any():
      raise SystemExit("[FAIL] Round40 guard failed, do not publish dashboard as final")
    print("[PASS] Round40 guard passed")


if __name__ == "__main__":
    main()
```

执行：

```bash
python scripts/round40_guard_final_prediction.py
```

---

## 五、如果守门失败：改成小时级最终列

如果 `round40_guard_final_prediction.py` 失败，不要手动硬改页面。

修改：

```text
scripts/apply_round36_calibration.py
```

将最终预测改成小时级选择：

```python
edge_hour = df["hour"].isin([6, 7, 18, 19])

df["power_pred_final_candidate"] = df["power_pred_final"]

# 临界小时优先用 power_pred_cal，避免 ghi<5 硬置零
df.loc[edge_hour, "power_pred_final_candidate"] = df.loc[edge_hour, "power_pred_cal"]

# 非临界小时保留原有最优逻辑
df.loc[~edge_hour, "power_pred_final_candidate"] = df.loc[~edge_hour, "power_pred_final"]

df["power_pred_final"] = df["power_pred_final_candidate"].clip(lower=0)
```

然后重新执行：

```bash
python scripts/apply_round36_calibration.py
python scripts/round40_compare_final_prediction_metrics.py
python scripts/round40_guard_final_prediction.py
python scripts/export_interactive_dashboard_data.py
```

---

## 六、可视化一致性校验

新增或修改：

```text
scripts/check_dashboard_city_series_consistency_round40.py
```

内容：

```python
from pathlib import Path
import json
import numpy as np
import pandas as pd


ROOT = Path("output/pv_pipeline")
TABLE_DIR = ROOT / "tables"
DASH_DIR = ROOT / "interactive_dashboard"


def find_final_pkl():
    candidates = sorted(TABLE_DIR.glob("distributed_predictions_final_round*.pkl"))
    if candidates:
        return candidates[-1]
    return TABLE_DIR / "distributed_predictions_final_full.pkl"


def main():
    pkl = find_final_pkl()
    df = pd.read_pickle(pkl).copy()
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    if "split" in df.columns:
        df = df[df["split"].isin(["train", "valid", "test"])].copy()
    df = df[df["hour"].between(6, 19)].copy()
    df = df[df["power_mw"].notna() & df["power_pred_final"].notna()].copy()

    city_pkl = (
        df.groupby("time", as_index=False)
        .agg(
            actual_mw=("power_mw", "sum"),
            pred_mw=("power_pred_final", "sum"),
            n_sites=("site_id", "nunique"),
            capacity_sum_mw=("capacity_mw", "sum"),
        )
    )

    city_json = pd.read_json(DASH_DIR / "city_series.json")
    city_json["time"] = pd.to_datetime(city_json["time"])

    cmp = city_pkl.merge(
        city_json[["time", "actual_mw", "pred_mw", "n_sites", "capacity_sum_mw"]],
        on="time",
        how="outer",
        suffixes=("_pkl", "_json"),
        indicator=True,
    )

    for col in ["actual_mw", "pred_mw", "capacity_sum_mw"]:
        cmp[f"{col}_diff"] = cmp[f"{col}_pkl"] - cmp[f"{col}_json"]

    max_pred_diff = float(cmp["pred_mw_diff"].abs().max())
    max_actual_diff = float(cmp["actual_mw_diff"].abs().max())
    bad_merge = cmp[cmp["_merge"].ne("both")]

    out = ROOT / "metrics" / "round40_dashboard_city_series_consistency.csv"
    cmp.to_csv(out, index=False, encoding="utf-8-sig")

    print("[OK] pkl:", pkl)
    print("rows pkl/json/merged:", len(city_pkl), len(city_json), len(cmp))
    print("max_actual_diff:", max_actual_diff)
    print("max_pred_diff:", max_pred_diff)
    print("bad_merge_rows:", len(bad_merge))

    assert len(bad_merge) == 0, "city_series 与 pkl 时间戳不一致"
    assert max_actual_diff <= 1e-6, "actual_mw 不一致"
    assert max_pred_diff <= 1e-6, "pred_mw 不一致"
    print("[PASS] dashboard city_series matches final pkl")


if __name__ == "__main__":
    main()
```

执行：

```bash
python scripts/check_dashboard_city_series_consistency_round40.py
```

---

## 七、页面文案修正

修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

把说明中的：

```text
四季代表日
```

统一改成：

```text
四季最佳日
```

并在按钮或说明中写明：

```text
单站点模式：选择该站点该季节日级 NRMSE 最低的一天；
全市模式：选择全市该季节日级 NRMSE 最低的一天。
```

把旧说明：

```text
"典型日10-14"会自动选择一个10-14点表现接近中位数的代表日期
```

如果仍存在，删除或改为当前真实逻辑。

---

## 八、执行顺序

按顺序执行：

```bash
python scripts/apply_round36_calibration.py
python scripts/round40_compare_final_prediction_metrics.py
python scripts/round40_guard_final_prediction.py
python scripts/export_interactive_dashboard_data.py
python scripts/check_dashboard_city_series_consistency_round40.py
python scripts/check_dashboard_prediction_values_round36.py
python scripts/posttrain_validation_round36.py
```

如果 `round40_guard_final_prediction.py` 失败：

```text
先按第五节做小时级最终列修复，再重新执行上述命令。
```

---

## 九、最终验收

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round40
```

强制刷新：

```text
Ctrl + Shift + R
```

检查：

1. 页面顶部显示：

```text
Round36 / power_pred_final / 默认不含 future
```

2. 全市模式：

```text
2025-09-01 至 2025-12-31
06:00 至 19:00
```

6、7、18、19 点不再长期贴 0。

3. 全市四季最佳日按钮：

```text
选择全市该季节 NRMSE 最低日
```

4. 单站点四季最佳日按钮：

```text
选择当前站点该季节 NRMSE 最低日
站点下拉框保持显示
```

5. 从全市点击典型站点：

```text
选择站点下拉框显示，且站点名和曲线标题一致
```

---

## 十、完成后回传

请回传以下文件或关键内容：

```text
output/pv_pipeline/metrics/round40_prediction_column_compare_summary.csv
output/pv_pipeline/metrics/round40_prediction_column_compare_hourly.csv
output/pv_pipeline/metrics/round40_final_prediction_guard.csv
output/pv_pipeline/metrics/round40_dashboard_city_series_consistency.csv
```

以及页面截图：

```text
全市 2025-09-01 至 2025-12-31，06:00 至 19:00
单站点四季最佳日
全市四季最佳日
```

