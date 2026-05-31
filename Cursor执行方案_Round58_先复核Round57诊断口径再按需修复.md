# Cursor 执行方案 Round58：先复核 Round57 诊断口径，再按需修复

## 目标

Round57 初步暴露出几个可能问题：

1. 小时/月/场景表中的 `site_mean_nrmse_percent` 与 `city_nrmse_percent` 完全相同，疑似计算口径错误。
2. 小时/月/场景表中的 NRMSE 数值疑似重复乘以 100 或使用了错误分母。
3. 月份结论可能与 CSV 不一致。
4. `daytime_scene_night` 风险标签可能过度触发。
5. `main_bad_hours` 为空，优先站点表没有真正反映“哪个小时差”。
6. NaN bias 站点可能被错误归入高估/低估。
7. 报告中个别站点 bias 描述可能误读，例如 S023。

但本轮不要直接修改。先独立复核这些问题是否真实存在，避免基于片面判断继续改。

本轮原则：

- 先复核，不盲改。
- 复核使用 `distributed_predictions_final_eval.pkl` 从零计算，不依赖 Round57 已生成 CSV。
- 只有复核确认问题存在，才修改 `diagnose_prediction_error_drivers.py`。
- 不重训模型。
- 不改最终预测列。
- 不改 dashboard 数据。

---

## 一、进入项目目录

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
mkdir -p output/pv_pipeline/validation
mkdir -p output/pv_pipeline/diagnostics
mkdir -p output/pv_pipeline/logs
```

---

## 二、先确认当前输入文件存在

```bash
ls -lh \
  output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl \
  output/pv_pipeline/diagnostics/round57_error_by_hour.csv \
  output/pv_pipeline/diagnostics/round57_error_by_month.csv \
  output/pv_pipeline/diagnostics/round57_error_by_scene.csv \
  output/pv_pipeline/diagnostics/round57_error_by_site.csv \
  output/pv_pipeline/diagnostics/round57_error_by_site_hour.csv \
  output/pv_pipeline/diagnostics/round57_priority_sites.csv
```

如果 Round57 诊断文件不存在，先不要修复，执行：

```bash
python scripts/diagnose_prediction_error_drivers.py
```

然后再继续。

---

## 三、新增独立复核脚本

新增：

```text
scripts/recheck_round57_diagnostic_metrics.py
```

该脚本必须从 `distributed_predictions_final_eval.pkl` 独立复算，不调用 Round57 诊断函数。

输出：

```text
output/pv_pipeline/validation/round58_recheck_hourly_metrics.csv
output/pv_pipeline/validation/round58_recheck_monthly_metrics.csv
output/pv_pipeline/validation/round58_recheck_scene_metrics.csv
output/pv_pipeline/validation/round58_recheck_site_hour_bad_hours.csv
output/pv_pipeline/validation/round58_recheck_findings.csv
output/pv_pipeline/validation/round58_recheck_report.md
```

参考实现：

```python
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(".")
PRED = ROOT / "output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl"
DIAG = ROOT / "output/pv_pipeline/diagnostics"
VAL = ROOT / "output/pv_pipeline/validation"
VAL.mkdir(parents=True, exist_ok=True)

PRED_COL = "power_pred_final"

def rmse(a, p):
    a = np.asarray(a, dtype=float)
    p = np.asarray(p, dtype=float)
    if len(a) == 0:
        return np.nan
    return float(np.sqrt(np.mean((p - a) ** 2)))

def mae(a, p):
    a = np.asarray(a, dtype=float)
    p = np.asarray(p, dtype=float)
    if len(a) == 0:
        return np.nan
    return float(np.mean(np.abs(p - a)))

def nrmse(a, p, den):
    den = float(den)
    if den <= 0:
        return np.nan
    return rmse(a, p) / den * 100

def bias_pct(a, p):
    a_sum = float(np.sum(a))
    p_sum = float(np.sum(p))
    if abs(a_sum) < 1e-12:
        return np.nan
    return (p_sum - a_sum) / a_sum * 100

def pred_actual(a, p):
    a_sum = float(np.sum(a))
    if abs(a_sum) < 1e-12:
        return np.nan
    return float(np.sum(p)) / a_sum

df = pd.read_pickle(PRED)
df["timestamp"] = pd.to_datetime(df["timestamp"])
df["hour"] = df["timestamp"].dt.hour
df["month"] = df["timestamp"].dt.month

if "split" in df.columns:
    df = df[df["split"].eq("test")].copy()
if "is_future" in df.columns:
    df = df[~df["is_future"].fillna(False)].copy()
df = df[df["hour"].between(6, 19)].copy()

required = ["station_id", "timestamp", "power_mw", PRED_COL, "capacity_mw", "hour", "month"]
missing = [c for c in required if c not in df.columns]
if missing:
    raise KeyError(f"missing required columns: {missing}")

capacity_by_site = (
    df[["station_id", "capacity_mw"]]
    .drop_duplicates("station_id")
    .set_index("station_id")["capacity_mw"]
)
city_capacity = float(capacity_by_site.sum())

def site_mean_nrmse(group):
    vals = []
    for sid, sdf in group.groupby("station_id"):
        cap = capacity_by_site.get(sid, np.nan)
        val = nrmse(sdf["power_mw"], sdf[PRED_COL], cap)
        if np.isfinite(val):
            vals.append(val)
    return float(np.mean(vals)) if vals else np.nan

def city_agg_nrmse(group):
    agg = group.groupby("timestamp", as_index=False).agg(
        actual=("power_mw", "sum"),
        pred=(PRED_COL, "sum"),
    )
    return nrmse(agg["actual"], agg["pred"], city_capacity)

hour_rows = []
for hour, hdf in df.groupby("hour"):
    agg = hdf.groupby("timestamp", as_index=False).agg(
        actual=("power_mw", "sum"),
        pred=(PRED_COL, "sum"),
    )
    hour_rows.append({
        "hour": int(hour),
        "rows": len(hdf),
        "site_mean_nrmse_percent_recalc": site_mean_nrmse(hdf),
        "city_nrmse_percent_recalc": nrmse(agg["actual"], agg["pred"], city_capacity),
        "city_bias_percent_recalc": bias_pct(agg["actual"], agg["pred"]),
        "city_pred_actual_ratio_recalc": pred_actual(agg["actual"], agg["pred"]),
        "actual_sum": float(hdf["power_mw"].sum()),
        "pred_sum": float(hdf[PRED_COL].sum()),
    })
hour_re = pd.DataFrame(hour_rows).sort_values("hour")
hour_re.to_csv(VAL / "round58_recheck_hourly_metrics.csv", index=False, encoding="utf-8-sig")

month_rows = []
for month, mdf in df.groupby("month"):
    agg = mdf.groupby("timestamp", as_index=False).agg(
        actual=("power_mw", "sum"),
        pred=(PRED_COL, "sum"),
    )
    month_rows.append({
        "month": int(month),
        "rows": len(mdf),
        "site_mean_nrmse_percent_recalc": site_mean_nrmse(mdf),
        "city_nrmse_percent_recalc": nrmse(agg["actual"], agg["pred"], city_capacity),
        "city_bias_percent_recalc": bias_pct(agg["actual"], agg["pred"]),
        "city_pred_actual_ratio_recalc": pred_actual(agg["actual"], agg["pred"]),
    })
month_re = pd.DataFrame(month_rows).sort_values("month")
month_re.to_csv(VAL / "round58_recheck_monthly_metrics.csv", index=False, encoding="utf-8-sig")

scene_col = "scene_v151" if "scene_v151" in df.columns else None
scene_rows = []
if scene_col:
    for scene, sdf in df.groupby(scene_col):
        agg = sdf.groupby("timestamp", as_index=False).agg(
            actual=("power_mw", "sum"),
            pred=(PRED_COL, "sum"),
        )
        scene_rows.append({
            "scene": scene,
            "rows": len(sdf),
            "site_mean_nrmse_percent_recalc": site_mean_nrmse(sdf),
            "city_nrmse_percent_recalc": nrmse(agg["actual"], agg["pred"], city_capacity),
            "bias_percent_recalc": bias_pct(sdf["power_mw"], sdf[PRED_COL]),
            "pred_actual_ratio_recalc": pred_actual(sdf["power_mw"], sdf[PRED_COL]),
        })
scene_re = pd.DataFrame(scene_rows)
scene_re.to_csv(VAL / "round58_recheck_scene_metrics.csv", index=False, encoding="utf-8-sig")

# 站点-小时：找每个站点最差小时
site_hour_rows = []
for (sid, hour), sdf in df.groupby(["station_id", "hour"]):
    cap = capacity_by_site.get(sid, np.nan)
    site_hour_rows.append({
        "station_id": sid,
        "hour": int(hour),
        "rows": len(sdf),
        "nrmse_percent_recalc": nrmse(sdf["power_mw"], sdf[PRED_COL], cap),
        "bias_percent_recalc": bias_pct(sdf["power_mw"], sdf[PRED_COL]),
        "pred_actual_ratio_recalc": pred_actual(sdf["power_mw"], sdf[PRED_COL]),
    })
site_hour_re = pd.DataFrame(site_hour_rows)
bad_hours = (
    site_hour_re.sort_values(["station_id", "nrmse_percent_recalc"], ascending=[True, False])
    .groupby("station_id")
    .head(3)
    .groupby("station_id")
    .agg(main_bad_hours=("hour", lambda x: "|".join(map(str, x))),
         main_bad_hour_nrmse=("nrmse_percent_recalc", "max"))
    .reset_index()
)
bad_hours.to_csv(VAL / "round58_recheck_site_hour_bad_hours.csv", index=False, encoding="utf-8-sig")

findings = []

def add_finding(code, severity, exists, evidence, recommended_fix):
    findings.append({
        "code": code,
        "severity": severity,
        "exists": bool(exists),
        "evidence": evidence,
        "recommended_fix": recommended_fix,
    })

# 对比 Round57 hour
hour57_path = DIAG / "round57_error_by_hour.csv"
if hour57_path.exists():
    h57 = pd.read_csv(hour57_path)
    merged = h57.merge(hour_re, on="hour", how="inner")
    same_cols = np.allclose(
        merged["site_mean_nrmse_percent"],
        merged["city_nrmse_percent"],
        equal_nan=True,
    )
    max_city_diff = float(np.nanmax(np.abs(merged["city_nrmse_percent"] - merged["city_nrmse_percent_recalc"]))) if len(merged) else np.nan
    max_site_diff = float(np.nanmax(np.abs(merged["site_mean_nrmse_percent"] - merged["site_mean_nrmse_percent_recalc"]))) if len(merged) else np.nan
    add_finding(
        "HOUR_SITE_CITY_IDENTICAL",
        "high",
        same_cols,
        f"Round57 hourly site_mean and city columns identical={same_cols}",
        "Separate station-mean NRMSE and city-aggregated NRMSE calculations",
    )
    add_finding(
        "HOUR_CITY_NRMSE_MISMATCH",
        "high",
        max_city_diff > 1e-6,
        f"max abs diff Round57 city vs independent recalculation = {max_city_diff}",
        "Replace hourly city NRMSE with city aggregated recalculation",
    )
    add_finding(
        "HOUR_SITE_NRMSE_MISMATCH",
        "high",
        max_site_diff > 1e-6,
        f"max abs diff Round57 site_mean vs independent recalculation = {max_site_diff}",
        "Replace hourly site_mean NRMSE with per-site capacity NRMSE mean",
    )

# 对比 month
month57_path = DIAG / "round57_error_by_month.csv"
if month57_path.exists():
    m57 = pd.read_csv(month57_path)
    merged = m57.merge(month_re, on="month", how="inner")
    max_month_city_diff = float(np.nanmax(np.abs(merged["city_nrmse_percent"] - merged["city_nrmse_percent_recalc"]))) if len(merged) else np.nan
    add_finding(
        "MONTH_CITY_NRMSE_MISMATCH",
        "high",
        max_month_city_diff > 1e-6,
        f"max abs diff Round57 monthly city vs independent recalculation = {max_month_city_diff}",
        "Replace monthly metrics with independent formula",
    )
    if len(merged):
        old_worst = int(merged.sort_values("city_nrmse_percent", ascending=False).iloc[0]["month"])
        new_worst = int(merged.sort_values("city_nrmse_percent_recalc", ascending=False).iloc[0]["month"])
        add_finding(
            "MONTH_CONCLUSION_MAY_BE_WRONG",
            "medium",
            old_worst != new_worst,
            f"Round57 worst month={old_worst}, recalculated worst month={new_worst}",
            "Update report conclusion according to recalculated monthly metrics",
        )

# main_bad_hours
prio_path = DIAG / "round57_priority_sites.csv"
if prio_path.exists():
    pr = pd.read_csv(prio_path)
    missing_bad_hours = "main_bad_hours" not in pr.columns or pr["main_bad_hours"].isna().all()
    add_finding(
        "MAIN_BAD_HOURS_EMPTY",
        "medium",
        missing_bad_hours,
        "round57_priority_sites.main_bad_hours is missing or all NaN",
        "Join top bad hours from site-hour metrics into priority_sites",
    )

# daytime_scene_night over-trigger
site_path = DIAG / "round57_error_by_site.csv"
if site_path.exists():
    site = pd.read_csv(site_path)
    if "risk_flags" in site.columns:
        cnt = int(site["risk_flags"].fillna("").str.contains("daytime_scene_night").sum())
        add_finding(
            "DAYTIME_SCENE_NIGHT_OVERTRIGGER",
            "medium",
            cnt > 20,
            f"daytime_scene_night flagged sites={cnt}/68",
            "Use test 10-14 or solar_elevation>0 criterion instead of broad 6-19 night ratio",
        )

# NaN bias classification
if site_path.exists():
    site = pd.read_csv(site_path)
    nan_bias = site["bias_percent"].isna().sum() if "bias_percent" in site.columns else 0
    add_finding(
        "NAN_BIAS_NEEDS_SEPARATE_CLASS",
        "medium",
        nan_bias > 0,
        f"sites with NaN bias={int(nan_bias)}",
        "Classify as no_valid_actual_generation or zero_actual_sum, not over/under prediction",
    )

findings_df = pd.DataFrame(findings)
findings_df.to_csv(VAL / "round58_recheck_findings.csv", index=False, encoding="utf-8-sig")

md = []
md.append("# Round58 Round57 诊断口径独立复核报告\n")
md.append("## 1. 复核结论\n")
for _, r in findings_df.iterrows():
    mark = "存在" if r["exists"] else "未确认"
    md.append(f"- **{r['code']}**：{mark}。证据：{r['evidence']}")
md.append("\n## 2. 小时复算结果\n")
md.append(hour_re.to_markdown(index=False))
md.append("\n## 3. 月份复算结果\n")
md.append(month_re.to_markdown(index=False))
if len(scene_re):
    md.append("\n## 4. 场景复算结果\n")
    md.append(scene_re.to_markdown(index=False))
md.append("\n## 5. 处理建议\n")
md.append("只有 exists=True 的问题才进入修复。")
(VAL / "round58_recheck_report.md").write_text("\n".join(md), encoding="utf-8")

print("[OK] recheck completed")
print(findings_df.to_string(index=False))
```

执行：

```bash
python scripts/recheck_round57_diagnostic_metrics.py 2>&1 | tee output/pv_pipeline/logs/round58_recheck_round57.log
```

---

## 四、查看复核结论

```bash
cat output/pv_pipeline/validation/round58_recheck_report.md

python - <<'PY'
import pandas as pd
df = pd.read_csv("output/pv_pipeline/validation/round58_recheck_findings.csv")
print(df.to_string(index=False))
print("\nConfirmed issues:")
print(df[df["exists"] == True].to_string(index=False))
PY
```

判断：

- 如果 `HOUR_CITY_NRMSE_MISMATCH=True`，再修小时城市 NRMSE。
- 如果 `HOUR_SITE_NRMSE_MISMATCH=True`，再修小时站点平均 NRMSE。
- 如果 `MONTH_CITY_NRMSE_MISMATCH=True`，再修月份指标和报告结论。
- 如果 `MAIN_BAD_HOURS_EMPTY=True`，再修 priority sites。
- 如果 `DAYTIME_SCENE_NIGHT_OVERTRIGGER=True`，再修风险标签。
- 如果 `NAN_BIAS_NEEDS_SEPARATE_CLASS=True`，再修 NaN bias 分类。

如果复核没有确认某个问题，不要修那个问题。

---

## 五、只有确认存在问题时，才修改诊断脚本

修改：

```text
scripts/diagnose_prediction_error_drivers.py
```

### 1. 修正小时级指标

确认存在后，小时级计算必须改为：

```python
def compute_hourly_metrics(eval_df):
    rows = []
    capacity_by_site = (
        eval_df[["station_id", "capacity_mw"]]
        .drop_duplicates("station_id")
        .set_index("station_id")["capacity_mw"]
    )
    city_capacity = capacity_by_site.sum()

    for hour, hdf in eval_df.groupby("hour"):
        site_vals = []
        for sid, sdf in hdf.groupby("station_id"):
            cap = capacity_by_site.get(sid)
            if cap and cap > 0:
                site_vals.append(rmse(sdf["power_mw"], sdf[PRED_COL]) / cap * 100)

        city_ts = hdf.groupby("timestamp", as_index=False).agg(
            actual=("power_mw", "sum"),
            pred=(PRED_COL, "sum"),
        )
        city_nrmse = rmse(city_ts["actual"], city_ts["pred"]) / city_capacity * 100

        rows.append({
            "hour": int(hour),
            "rows": len(hdf),
            "site_mean_nrmse_percent": np.nanmean(site_vals),
            "city_nrmse_percent": city_nrmse,
            "bias_percent_city": bias_pct(city_ts["actual"], city_ts["pred"]),
            "pred_actual_ratio_city": pred_actual(city_ts["actual"], city_ts["pred"]),
            "actual_sum": hdf["power_mw"].sum(),
            "pred_sum": hdf[PRED_COL].sum(),
        })
    return pd.DataFrame(rows).sort_values("hour")
```

### 2. 修正月份和场景级指标

月份和场景同理：

- `site_mean_nrmse_percent`：先按站点算 NRMSE，再平均。
- `city_nrmse_percent`：按 timestamp 聚合全市实际/预测，再除以全市容量。

不要使用：

```text
逐行 RMSE / mean(capacity_mw)
```

不要让：

```text
site_mean_nrmse_percent == city_nrmse_percent
```

除非极端巧合，否则这两列不应完全相同。

### 3. 修正 main_bad_hours

从 `round57_error_by_site_hour.csv` 或内存中的 site-hour 结果生成：

```python
bad_hours = (
    site_hour_df.sort_values(["station_id", "nrmse_percent"], ascending=[True, False])
    .groupby("station_id")
    .head(3)
    .groupby("station_id")
    .agg(
        main_bad_hours=("hour", lambda x: "|".join(map(str, x))),
        main_bad_hour_nrmse=("nrmse_percent", "max"),
    )
    .reset_index()
)
priority_df = priority_df.merge(bad_hours, on="station_id", how="left")
```

### 4. 修正 daytime_scene_night 风险标签

不要用 6-19 全时段夜间占比直接打风险。

改为：

```text
只在 test 10-14 中 scene 全为 night
或 solar_elevation_deg > 5 但 scene 为 night 的比例异常高
```

建议字段：

```text
scene_night_ratio_10_14
solar_positive_scene_night_ratio
```

风险规则：

```python
if scene_night_ratio_10_14 > 0.05:
    flags.append("daytime_scene_night")
```

### 5. 修正 NaN bias 分类

如果 `actual_sum == 0`：

```python
bias_percent = np.nan
pred_actual_ratio = np.nan
flags.append("no_valid_actual_generation")
```

不要归入：

```text
over_prediction
under_prediction
high_bias
```

### 6. 修正文档自动结论

报告结论必须从修正后的 CSV 自动读取，不手写旧结论。

尤其检查：

- 最差月份是哪一个。
- 10-14 城市 NRMSE 是多少。
- S023 bias 是多少。
- NaN bias 站点是否被单独归类。

---

## 六、修复后重新生成诊断

只运行诊断，不重训：

```bash
python scripts/diagnose_prediction_error_drivers.py 2>&1 | tee output/pv_pipeline/logs/round58_regenerate_diagnostics.log
```

再次独立复核：

```bash
python scripts/recheck_round57_diagnostic_metrics.py 2>&1 | tee output/pv_pipeline/logs/round58_recheck_after_fix.log
```

检查：

```bash
python - <<'PY'
import pandas as pd
f = pd.read_csv("output/pv_pipeline/validation/round58_recheck_findings.csv")
print(f.to_string(index=False))
bad = f[(f["exists"] == True) & (f["code"].str.contains("MISMATCH|IDENTICAL|EMPTY|OVERTRIGGER|NAN", regex=True))]
print("\nRemaining confirmed issues:")
print(bad.to_string(index=False))
PY
```

如果修复后仍有 confirmed issue，继续修，不要进入下一轮模型优化。

---

## 七、生成 Round58 报告

新增：

```text
docs/Round58_复核Round57诊断口径并按需修复报告.md
```

模板：

```markdown
# Round58 复核 Round57 诊断口径并按需修复报告

## 1. 本轮目标

## 2. 是否直接修改

先独立复核，确认问题存在后才修改。

## 3. 复核发现

| 问题 | 是否真实存在 | 证据 | 是否修改 |
|---|---:|---|---:|

## 4. 修复内容

## 5. 修复后复核结果

## 6. 修正后的关键指标

### 6.1 按小时

### 6.2 按月份

### 6.3 按场景

### 6.4 优先站点

## 7. 仍然可信的问题归因

只写经过修正口径后仍成立的问题。

## 8. 下一步是否可以进入模型改进

如果诊断口径已通过复核，可以进入下一轮模型改进；否则继续修诊断。
```

---

## 八、验收标准

```text
[PASS] 新增 recheck_round57_diagnostic_metrics.py
[PASS] 独立复核使用 final_eval 从零计算
[PASS] 复核报告明确每个疑似问题是否真实存在
[PASS] 只有确认存在的问题才修改
[PASS] 修复后 site_mean_nrmse_percent 与 city_nrmse_percent 不再错误完全相同
[PASS] 小时/月/场景 NRMSE 百分比不再重复乘 100
[PASS] main_bad_hours 不再全空
[PASS] daytime_scene_night 不再大面积误报
[PASS] actual_sum=0 的站点单独归类
[PASS] 报告结论与 CSV 一致
[PASS] 不重训模型
```

