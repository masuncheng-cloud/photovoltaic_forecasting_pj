# Round46：修复逐小时站点 NRMSE 展示口径并定位高误差来源

## 一、当前现象

用户当前看到的可视化/报告逐小时表为：

```text
10点 站点平均 NRMSE = 31.81%
11点 站点平均 NRMSE = 35.69%
12点 站点平均 NRMSE = 36.98%
13点 站点平均 NRMSE = 35.48%
14点 站点平均 NRMSE = 30.51%
```

但 Round45 执行总结中，诊断脚本输出为：

```text
10点 站点均值 NRMSE = 13.79%
11点 站点均值 NRMSE = 15.30%
12点 站点均值 NRMSE = 16.14%
13点 站点均值 NRMSE = 15.86%
14点 站点均值 NRMSE = 13.82%
```

两者差距非常大。

这说明现在首先要处理的不是继续盲目校准模型，而是：

```text
逐小时表里的“站点平均 NRMSE”计算口径很可能不一致或仍在读取旧文件。
```

本轮目标：

1. 找出当前页面逐小时表的 `站点平均 NRMSE` 到底来自哪个 JSON/CSV。
2. 统一逐小时站点 NRMSE 的定义。
3. 用同一套函数生成报告表和 dashboard 表。
4. 再判断单站点 NRMSE 是否真的过高。

---

## 二、推荐统一口径

逐小时“站点平均 NRMSE”应定义为：

```text
对每个站点、每个小时：
  在测试集该小时所有日期上计算 RMSE
  NRMSE_site_hour = RMSE_site_hour / capacity_mw × 100%

然后对该小时所有站点取平均：
  站点平均 NRMSE_hour = mean(NRMSE_site_hour)
```

也就是说：

```text
先按站点-小时算 RMSE，再平均站点。
```

不要用下面这种口径冒充 NRMSE：

```text
逐行 abs(pred - actual) / capacity 后直接平均
```

那更接近容量归一化 MAE，不是 NRMSE。

---

## 三、第一步：定位页面逐小时表数据来源

执行：

```bash
grep -R "hourly_prediction_summary\\|site_avg_hourly\\|站点平均 NRMSE\\|city_hourly\\|hourly" -n \
  scripts stages/05_visualization output/pv_pipeline/interactive_dashboard | head -300
```

重点找：

```text
output/pv_pipeline/interactive_dashboard/hourly_prediction_summary.json
output/pv_pipeline/interactive_dashboard/site_avg_hourly_nrmse.json
output/pv_pipeline/metrics/*hour*.csv
```

并执行：

```bash
python - <<'PY'
import json
from pathlib import Path

root = Path("output/pv_pipeline/interactive_dashboard")
for name in [
    "hourly_prediction_summary.json",
    "site_avg_hourly_nrmse.json",
    "city_hourly_nrmse.json",
]:
    p = root / name
    print("\\n==", name, "exists=", p.exists(), "size=", p.stat().st_size if p.exists() else None)
    if p.exists():
        data = json.load(open(p, encoding="utf-8"))
        print(json.dumps(data[:3] if isinstance(data, list) else data, ensure_ascii=False, indent=2)[:2000])
PY
```

如果这些 JSON 里仍是：

```text
10点 31.81%
12点 36.98%
```

说明导出脚本中的逐小时表口径有问题。

---

## 四、第二步：新增统一逐小时指标生成脚本

新增：

```text
scripts/round46_recompute_hourly_nrmse_consistent.py
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
DASH_DIR = ROOT / "interactive_dashboard"
METRIC_DIR.mkdir(parents=True, exist_ok=True)
DASH_DIR.mkdir(parents=True, exist_ok=True)


def find_final_pkl():
    candidates = sorted(TABLE_DIR.glob("distributed_predictions_final_round*.pkl"))
    if candidates:
        return candidates[-1]
    for name in ["distributed_predictions_final_full.pkl", "distributed_predictions_final.pkl"]:
        p = TABLE_DIR / name
        if p.exists():
            return p
    raise FileNotFoundError("找不到 distributed_predictions_final*.pkl")


def rmse(x):
    x = np.asarray(x, dtype=float)
    return math.sqrt(float(np.mean(x * x))) if len(x) else np.nan


def normalize(df):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    if "date" not in df.columns:
        df["date"] = df["time"].dt.strftime("%Y-%m-%d")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    return df


def build_eval_frame(df):
    df = normalize(df)
    work = df[
        df["split"].eq("test")
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df["power_pred_final"].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()
    work["actual_mw"] = pd.to_numeric(work["power_mw"], errors="coerce")
    work["pred_mw"] = pd.to_numeric(work["power_pred_final"], errors="coerce")
    work["capacity_mw"] = pd.to_numeric(work["capacity_mw"], errors="coerce")
    work = work[work["actual_mw"].notna() & work["pred_mw"].notna()].copy()
    return work


def compute_site_hour_metrics(work):
    rows = []
    for (sid, hour), g in work.groupby(["site_id", "hour"]):
        cap = float(g["capacity_mw"].mean())
        err = g["pred_mw"] - g["actual_mw"]
        rmse_mw = rmse(err)
        mae_mw = float(err.abs().mean())
        actual_sum = float(g["actual_mw"].sum())
        pred_sum = float(g["pred_mw"].sum())
        zero_ratio = float((g["actual_mw"].abs() <= 1e-9).mean() * 100)
        active_threshold = np.maximum(0.02 * g["capacity_mw"], 0.05)
        active = g[g["actual_mw"] > active_threshold]
        active_nrmse = np.nan
        if len(active):
            active_err = active["pred_mw"] - active["actual_mw"]
            active_nrmse = rmse(active_err) / max(cap, 1e-9) * 100

        rows.append({
            "site_id": sid,
            "site_name": g["site_name"].iloc[0] if "site_name" in g.columns else sid,
            "hour": int(hour),
            "samples": int(len(g)),
            "capacity_mw": round(cap, 6),
            "mae_mw": round(mae_mw, 6),
            "rmse_mw": round(rmse_mw, 6),
            "nrmse_pct": round(rmse_mw / max(cap, 1e-9) * 100, 6),
            "active_nrmse_pct": round(float(active_nrmse), 6) if np.isfinite(active_nrmse) else np.nan,
            "zero_actual_ratio_pct": round(zero_ratio, 6),
            "bias_pct": round((pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100, 6) if actual_sum > 1e-9 else np.nan,
            "pred_actual": round(pred_sum / max(actual_sum, 1e-9), 6) if actual_sum > 1e-9 else np.nan,
        })
    return pd.DataFrame(rows)


def compute_city_hour_metrics(work):
    city = (
        work.groupby(["time", "hour"], as_index=False)
        .agg(
            actual_mw=("actual_mw", "sum"),
            pred_mw=("pred_mw", "sum"),
            capacity_sum_mw=("capacity_mw", "sum"),
            site_count=("site_id", "nunique"),
        )
    )
    rows = []
    for hour, g in city.groupby("hour"):
        err = g["pred_mw"] - g["actual_mw"]
        rmse_mw = rmse(err)
        cap = float(g["capacity_sum_mw"].mean())
        rows.append({
            "hour": int(hour),
            "city_samples": int(len(g)),
            "city_rmse_mw": round(rmse_mw, 6),
            "city_nrmse_pct": round(rmse_mw / max(cap, 1e-9) * 100, 6),
            "city_actual_mean_mw": round(float(g["actual_mw"].mean()), 6),
            "city_pred_mean_mw": round(float(g["pred_mw"].mean()), 6),
            "city_capacity_mean_mw": round(cap, 6),
        })
    return pd.DataFrame(rows)


def main():
    pkl = find_final_pkl()
    df = pd.read_pickle(pkl)
    work = build_eval_frame(df)

    site_hour = compute_site_hour_metrics(work)
    city_hour = compute_city_hour_metrics(work)

    summary = (
        site_hour.groupby("hour", as_index=False)
        .agg(
            site_count=("site_id", "nunique"),
            row_samples=("samples", "sum"),
            site_avg_nrmse_pct=("nrmse_pct", "mean"),
            site_median_nrmse_pct=("nrmse_pct", "median"),
            site_p90_nrmse_pct=("nrmse_pct", lambda s: float(np.nanpercentile(s, 90))),
            active_site_avg_nrmse_pct=("active_nrmse_pct", "mean"),
            avg_zero_actual_ratio_pct=("zero_actual_ratio_pct", "mean"),
        )
    )
    summary = summary.merge(city_hour[["hour", "city_nrmse_pct"]], on="hour", how="left")
    summary = summary.sort_values("hour")

    site_hour.to_csv(METRIC_DIR / "round46_site_hour_nrmse_consistent.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(METRIC_DIR / "round46_hourly_nrmse_consistent.csv", index=False, encoding="utf-8-sig")

    # 写 dashboard 使用的统一 JSON
    records = []
    for _, r in summary.iterrows():
        records.append({
            "hour": int(r["hour"]),
            "samples": int(r["row_samples"]),
            "site_count": int(r["site_count"]),
            "site_avg_nrmse_pct": round(float(r["site_avg_nrmse_pct"]), 3),
            "site_median_nrmse_pct": round(float(r["site_median_nrmse_pct"]), 3),
            "site_p90_nrmse_pct": round(float(r["site_p90_nrmse_pct"]), 3),
            "active_site_avg_nrmse_pct": round(float(r["active_site_avg_nrmse_pct"]), 3) if pd.notna(r["active_site_avg_nrmse_pct"]) else None,
            "avg_zero_actual_ratio_pct": round(float(r["avg_zero_actual_ratio_pct"]), 3),
            "city_nrmse_pct": round(float(r["city_nrmse_pct"]), 3),
            "definition": "site_avg_nrmse = mean over sites of RMSE(site,hour)/capacity(site); city_nrmse = RMSE(city_aggregate,hour)/mean_capacity_sum",
        })

    (DASH_DIR / "hourly_prediction_summary.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("[OK] pkl:", pkl)
    print(summary.to_string(index=False))
    print("[OK] wrote:")
    print(" -", METRIC_DIR / "round46_site_hour_nrmse_consistent.csv")
    print(" -", METRIC_DIR / "round46_hourly_nrmse_consistent.csv")
    print(" -", DASH_DIR / "hourly_prediction_summary.json")


if __name__ == "__main__":
    main()
```

执行：

```bash
python scripts/round46_recompute_hourly_nrmse_consistent.py
```

---

## 五、第三步：修改 dashboard 导出脚本，统一调用 Round46 逻辑

修改：

```text
scripts/export_interactive_dashboard_data.py
```

找到生成：

```text
hourly_prediction_summary.json
```

的函数。

如果里面是手写计算，例如：

```python
abs_error / capacity
mean relative error
```

请删除或替换，统一改为与 `round46_recompute_hourly_nrmse_consistent.py` 一致的逻辑。

最简单方式：

```python
def export_hourly_prediction_summary(...):
    # 直接复用同样的 site-hour RMSE 逻辑
```

要求输出字段：

```text
hour
samples
site_count
site_avg_nrmse_pct
site_median_nrmse_pct
site_p90_nrmse_pct
active_site_avg_nrmse_pct
avg_zero_actual_ratio_pct
city_nrmse_pct
definition
```

不要再输出含糊字段：

```text
站点平均 NRMSE
```

但实际用的是逐行绝对误差均值。

---

## 六、第四步：修改前端表格展示

修改：

```text
stages/05_visualization/interactive_forecast_dashboard.html
```

找到逐小时表格渲染逻辑。

表头改为：

```text
小时（时）
样本数（行）
站点平均 NRMSE（%）
站点中位 NRMSE（%）
有效发电站点平均 NRMSE（%）
城市 NRMSE（%）
平均0值占比（%）
```

显示字段对应：

```javascript
hour
samples
site_avg_nrmse_pct
site_median_nrmse_pct
active_site_avg_nrmse_pct
city_nrmse_pct
avg_zero_actual_ratio_pct
```

在表格下方加一句说明：

```text
说明：站点平均 NRMSE 先按每个站点在该小时所有测试日期上计算 RMSE/capacity，再对站点取平均；有效发电口径仅统计 actual_mw > max(0.02×capacity_mw, 0.05MW) 的样本。
```

---

## 七、第五步：重新导出和验证

执行：

```bash
python scripts/round46_recompute_hourly_nrmse_consistent.py
python scripts/export_interactive_dashboard_data.py
python scripts/update_dashboard_after_training.py
python scripts/check_dashboard_auto_update_stamp.py
python scripts/round44_dashboard_regression_check.py
```

然后检查：

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path("output/pv_pipeline/interactive_dashboard/hourly_prediction_summary.json")
data = json.load(open(p, encoding="utf-8"))
for r in data:
    print(r)
PY
```

要求：

```text
10-14 站点平均 NRMSE 应接近 Round45 报告里的 13.79%-16.14%，
而不是 31%-37%。
```

如果仍是 31%-37%，说明前端读取了其他旧文件，继续搜索：

```bash
grep -R "31.81\\|36.98\\|site_avg_nrmse\\|hourly_prediction_summary" -n output stages scripts | head -200
```

---

## 八、如果统一口径后站点 NRMSE 仍偏高

如果统一后 10-14 仍大于 20%，再继续模型/校准优化。

但如果统一后为：

```text
10-14：约 14%-16%
```

说明原来的 31%-37% 主要是展示口径错误，不应继续盲目调模型。

下一步应做：

```text
按 round45_site_hour_nrmse_top_outliers.csv 定点分析异常站点；
对异常站点做数据质量说明；
必要时新增有效发电口径作为辅助指标。
```

---

## 九、完成后回传

请回传：

```text
output/pv_pipeline/metrics/round46_hourly_nrmse_consistent.csv
output/pv_pipeline/metrics/round46_site_hour_nrmse_consistent.csv
output/pv_pipeline/interactive_dashboard/hourly_prediction_summary.json
```

以及可视化页面逐小时表截图。

