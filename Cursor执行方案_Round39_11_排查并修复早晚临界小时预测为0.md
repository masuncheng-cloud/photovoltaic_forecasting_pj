# Round39.11：排查并修复全市早晚临界小时预测大量为 0

## 一、当前现象

在可视化页面选择：

```text
展示对象：全市
日期：2025-09-01 至 2025-12-31
小时：06:00 至 19:00
```

可以看到 6 点、7 点、18 点、19 点等临界发电时段，预测功率经常贴近 0，甚至某些时刻：

```text
2025-09-17 19:00
真实功率：12.96 MW
预测功率：0 MW
```

这不应直接理解为模型自然误差。全市预测在某些临界小时成片为 0，更像下面两类问题之一：

1. 最终预测文件里 `power_pred_final` 已经被早晚裁剪、active mask、低太阳高度规则压成 0。
2. 可视化导出时把缺失预测 `NaN` 或缺失站点直接当成 0 聚合，导致全市预测被低估。

本轮目标：

```text
先定位 0 是来自 final pkl，还是来自 dashboard JSON；
再修复不合理的早晚硬置零或导出填零；
最后重新导出可视化数据，不重新训练。
```

---

## 二、不要直接做的事

不要直接把所有 0 改成真实值。

不要在前端强行平滑曲线来掩盖问题。

不要重新训练，除非排查结果证明最终预测文件本身就系统性错误且无法用后处理修复。

---

## 三、第一步：新增早晚 0 值审计脚本

新增：

```text
scripts/audit_edge_hour_zero_predictions.py
```

内容如下：

```python
from pathlib import Path
import json
import numpy as np
import pandas as pd


ROOT = Path("output/pv_pipeline")
TABLE_DIR = ROOT / "tables"
DASH_DIR = ROOT / "interactive_dashboard"
OUT_DIR = ROOT / "metrics"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def find_latest_final_pkl():
    candidates = sorted(TABLE_DIR.glob("distributed_predictions_final_round*.pkl"))
    if candidates:
        return candidates[-1]
    for name in [
        "distributed_predictions_final_full.pkl",
        "distributed_predictions_final.pkl",
    ]:
        p = TABLE_DIR / name
        if p.exists():
            return p
    raise FileNotFoundError("未找到 distributed_predictions_final*.pkl")


def resolve_pred_col(df):
    for c in ["power_pred_final", "pred_mw", "power_pred_cal", "pred_calibrated", "power_pred"]:
        if c in df.columns:
            return c
    raise KeyError(f"未找到预测列，当前列：{list(df.columns)[:80]}")


def main():
    pkl = find_latest_final_pkl()
    df = pd.read_pickle(pkl).copy()
    pred_col = resolve_pred_col(df)

    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    if "date" not in df.columns:
        df["date"] = df["time"].dt.strftime("%Y-%m-%d")

    # 只审计可视化默认口径：非 future、6-19 点
    if "split" in df.columns:
        df = df[df["split"].isin(["train", "valid", "test"])].copy()
    df = df[df["hour"].between(6, 19)].copy()

    df["actual_mw"] = pd.to_numeric(df.get("power_mw"), errors="coerce")
    df["pred_mw"] = pd.to_numeric(df[pred_col], errors="coerce")

    edge = df[df["hour"].isin([6, 7, 18, 19])].copy()
    edge["pred_is_nan"] = edge["pred_mw"].isna()
    edge["pred_is_zero"] = edge["pred_mw"].fillna(np.nan).eq(0)
    edge["actual_positive"] = edge["actual_mw"].fillna(0).gt(0)

    by_time = (
        edge.groupby(["time", "date", "hour"], as_index=False)
        .agg(
            site_rows=("site_id", "size"),
            site_count=("site_id", "nunique"),
            actual_city_mw=("actual_mw", "sum"),
            pred_city_mw=("pred_mw", "sum"),
            pred_nan_sites=("pred_is_nan", "sum"),
            pred_zero_sites=("pred_is_zero", "sum"),
            actual_positive_sites=("actual_positive", "sum"),
            capacity_sum_mw=("capacity_mw", "sum"),
        )
    )
    by_time["pred_city_is_zero"] = by_time["pred_city_mw"].abs() <= 1e-9
    by_time["actual_city_positive"] = by_time["actual_city_mw"] > 1e-9
    by_time["suspicious_city_zero"] = by_time["pred_city_is_zero"] & by_time["actual_city_positive"]
    by_time["zero_site_ratio_pct"] = by_time["pred_zero_sites"] / by_time["site_rows"].clip(lower=1) * 100

    by_hour = (
        by_time.groupby("hour", as_index=False)
        .agg(
            timestamps=("time", "size"),
            suspicious_city_zero_count=("suspicious_city_zero", "sum"),
            suspicious_city_zero_ratio_pct=("suspicious_city_zero", "mean"),
            mean_actual_city_mw=("actual_city_mw", "mean"),
            mean_pred_city_mw=("pred_city_mw", "mean"),
            mean_zero_site_ratio_pct=("zero_site_ratio_pct", "mean"),
            mean_pred_nan_sites=("pred_nan_sites", "mean"),
        )
    )
    by_hour["suspicious_city_zero_ratio_pct"] *= 100

    by_time.to_csv(OUT_DIR / "round39_edge_hour_zero_by_time.csv", index=False, encoding="utf-8-sig")
    by_hour.to_csv(OUT_DIR / "round39_edge_hour_zero_by_hour.csv", index=False, encoding="utf-8-sig")

    # 与 dashboard city_series 对比，判断是否导出环节导致
    city_json = DASH_DIR / "city_series.json"
    if city_json.exists():
        city = pd.read_json(city_json)
        city["time"] = pd.to_datetime(city["time"])
        cmp = by_time.merge(
            city[["time", "actual_mw", "pred_mw"]],
            on="time",
            how="left",
            suffixes=("_pkl", "_dashboard"),
        )
        cmp["actual_diff"] = cmp["actual_city_mw"] - cmp["actual_mw"]
        cmp["pred_diff"] = cmp["pred_city_mw"] - cmp["pred_mw"]
        cmp.to_csv(OUT_DIR / "round39_edge_hour_pkl_vs_dashboard.csv", index=False, encoding="utf-8-sig")

    print("[OK] pkl:", pkl)
    print("[OK] pred_col:", pred_col)
    print(by_hour.to_string(index=False))
    print("[OK] wrote:")
    print(" -", OUT_DIR / "round39_edge_hour_zero_by_time.csv")
    print(" -", OUT_DIR / "round39_edge_hour_zero_by_hour.csv")
    print(" -", OUT_DIR / "round39_edge_hour_pkl_vs_dashboard.csv")


if __name__ == "__main__":
    main()
```

执行：

```bash
python scripts/audit_edge_hour_zero_predictions.py
```

---

## 四、根据审计结果判断根因

### 情况 A：PKL 中 `pred_city_mw` 已经是 0

如果：

```text
round39_edge_hour_zero_by_time.csv 中 pred_city_mw = 0
actual_city_mw > 0
```

说明不是前端问题，最终预测文件已经被置零。

重点检查这些脚本：

```text
scripts/apply_round36_calibration.py
scripts/select_final_prediction_by_guard.py
scripts/*calibration*.py
scripts/*clip*.py
```

搜索：

```bash
grep -R "solar\\|elevation\\|active\\|threshold\\|clip\\|hour.*19\\|hour.*6\\|pred.*= 0\\|np.where" -n scripts | head -200
```

重点找类似逻辑：

```python
pred = np.where(solar_elevation <= threshold, 0, pred)
pred = np.where(is_active == 0, 0, pred)
pred[df["hour"].isin([6, 19])] = 0
pred = pred.clip(lower=0)
```

这种规则如果太硬，会把真实仍有出力的 6、7、18、19 点压成 0。

### 情况 B：PKL 中不是 0，但 dashboard 中是 0

如果：

```text
PKL pred_city_mw 正常
dashboard pred_mw 为 0
```

说明是 `scripts/export_interactive_dashboard_data.py` 导出时的问题。

重点检查：

```python
fillna(0)
sum(min_count=...)
pred_mw=("pred_mw", "sum")
```

不要把缺失预测当成 0。

---

## 五、修复导出脚本：禁止缺失预测填 0

修改：

```text
scripts/export_interactive_dashboard_data.py
```

要求：

1. 构建展示数据前，必须过滤预测缺失行：

```python
df_export = df_export[
    df_export["actual_mw"].notna()
    & df_export["pred_mw"].notna()
    & df_export["hour"].between(6, 19)
    & df_export["split"].isin(["train", "valid", "test"])
].copy()
```

2. 不允许：

```python
df_export["pred_mw"] = df_export["pred_mw"].fillna(0)
```

3. 全市聚合时增加预测有效站点数：

```python
city = (
    df_export.groupby("time", as_index=False)
    .agg(
        actual_mw=("actual_mw", "sum"),
        pred_mw=("pred_mw", "sum"),
        n_sites=("site_id", "nunique"),
        pred_valid_sites=("pred_mw", "count"),
        actual_positive_sites=("actual_mw", lambda s: int((s > 0).sum())),
        capacity_sum_mw=("capacity_mw", "sum"),
    )
)
```

4. 如果某时刻 `pred_valid_sites` 明显少于站点数，应在 JSON 中保留字段，方便前端提示。

---

## 六、修复最终预测：不要对 6/7/18/19 做硬置零

如果审计证明 `power_pred_final` 已经在临界小时被压成 0，则修改最终校准/裁剪脚本。

建议规则：

### 6.1 保留物理下限，但不要硬置零

不要：

```python
pred = np.where(low_solar | inactive, 0.0, pred)
```

改为：

```python
edge_hour = df["hour"].isin([6, 7, 18, 19])
day_hour = df["hour"].between(8, 17)

pred = pred.clip(lower=0)

# 仅夜间或明确无太阳时置零，6-19 不直接硬置零
night = ~df["hour"].between(6, 19)
pred = np.where(night, 0.0, pred)
```

### 6.2 对临界小时使用“保守非零下限”

对 6、7、18、19 点，如果该时刻同站点历史上真实功率常为正，预测不要被压到 0。

可以基于训练/验证集学习小时级下限：

```python
def build_edge_hour_floor(train_valid_df):
    tv = train_valid_df.copy()
    tv = tv[
        tv["split"].isin(["train", "valid"])
        & tv["hour"].isin([6, 7, 18, 19])
        & (tv["power_mw"] > 0)
        & (tv["capacity_mw"] > 0)
    ].copy()
    tv["y_norm"] = tv["power_mw"] / tv["capacity_mw"]
    floor = (
        tv.groupby(["site_id", "hour"])["y_norm"]
        .quantile(0.10)
        .reset_index()
        .rename(columns={"y_norm": "edge_floor_norm"})
    )
    return floor
```

应用时：

```python
df = df.merge(edge_floor, on=["site_id", "hour"], how="left")
edge = df["hour"].isin([6, 7, 18, 19])
actual_context_positive = edge & df["edge_floor_norm"].notna()

floor_mw = df["edge_floor_norm"].fillna(0) * df["capacity_mw"]

# 只对已经被压成 0 或极小的预测做下限保护
pred = np.where(
    actual_context_positive & (pred <= 1e-6),
    floor_mw,
    pred,
)
```

注意：

```text
floor 只能用 train/valid 学，不允许用 test。
```

### 6.3 全市层面的临界小时保护

如果站点级 floor 不稳定，可以只在可视化/最终选择前增加城市层面检查：

```python
city_check = df.groupby("time").agg(
    pred_city=("power_pred_final", "sum"),
    actual_city=("power_mw", "sum"),
)
```

但不能用 test actual 修正 prediction，只能用于审计报错。最终预测修正必须基于 train/valid 学到的规则。

---

## 七、增加可视化提示字段

在 `city_series.json` 中保留：

```text
pred_valid_sites
actual_positive_sites
zero_pred_sites
```

前端 tooltip 增加：

```text
有效预测站点数
预测为0站点数
实际正功率站点数
```

这样如果 19 点全市预测为 0，可以马上看出是：

```text
所有站点都预测为 0
```

还是：

```text
预测缺失站点太多
```

---

## 八、重新导出并检查

执行：

```bash
python scripts/audit_edge_hour_zero_predictions.py
python scripts/export_interactive_dashboard_data.py
python scripts/audit_edge_hour_zero_predictions.py
```

检查：

```text
output/pv_pipeline/metrics/round39_edge_hour_zero_by_hour.csv
output/pv_pipeline/metrics/round39_edge_hour_pkl_vs_dashboard.csv
```

要求：

1. `dashboard pred_mw` 与 `pkl pred_city_mw` 一致。
2. 如果 6、7、18、19 点仍有预测为 0，要能从 `power_pred_final` 追溯原因。
3. `suspicious_city_zero_count` 不应大量出现。

---

## 九、页面验收

打开：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=round39_11
```

选择：

```text
展示对象：全市
日期：2025-09-01 至 2025-12-31
小时：06:00 至 19:00
```

检查：

1. 6、7、18、19 点预测曲线不应长期贴 0。
2. 对于真实仍有明显出力的时刻，预测不应整城为 0。
3. 如果个别 19 点预测仍为 0，tooltip 必须显示有效预测站点数和预测为 0 站点数，便于判断是数据问题还是模型判断。

---

## 十、如果仍有异常，回传这些文件

```text
output/pv_pipeline/metrics/round39_edge_hour_zero_by_hour.csv
output/pv_pipeline/metrics/round39_edge_hour_zero_by_time.csv
output/pv_pipeline/metrics/round39_edge_hour_pkl_vs_dashboard.csv
```

以及：

```bash
grep -R "pred.*= 0\\|np.where\\|active\\|solar\\|clip\\|hour.*19\\|hour.*6" -n scripts | head -200
```

