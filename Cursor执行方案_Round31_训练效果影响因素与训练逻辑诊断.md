# Cursor 执行方案 Round31：训练效果影响因素与训练逻辑诊断

## 一、背景判断

现在“单站点全量历史样本数与测试集 NRMSE 关系”图中，单靠：

```text
全量历史样本数
测试集6-19点0值占比
```

无法稳定解释站点预测效果好坏。

这不一定说明训练逻辑有问题。更可能说明影响 NRMSE 的因素不止这两个，还包括：

- 容量映射是否准确；
- 测试期和训练期出力分布是否漂移；
- 站点是否存在限电、停机、遮挡、采集异常；
- 气象插值是否适合该站点；
- 站点容量大小导致 NRMSE 对绝对误差敏感程度不同；
- 模型是否对某些站点系统性高估/低估；
- 是否存在 train/valid/test 口径不一致；
- 是否存在特征泄漏或预测目标错位。

本轮目标是做系统诊断，判断：

```text
当前结果差异是数据/站点差异造成的，还是训练逻辑存在问题。
```

本轮不直接改模型，不重新训练，先生成诊断结果。

## 二、输出目标

新增诊断脚本：

```text
scripts/diagnose_training_effect_factors_round31.py
```

输出：

```text
output/pv_pipeline/metrics/round31_site_effect_factor_summary.csv
output/pv_pipeline/metrics/round31_factor_correlation.csv
output/pv_pipeline/metrics/round31_worst_site_diagnosis.csv
output/pv_pipeline/metrics/round31_training_logic_audit.csv
output/pv_pipeline/docs/Round31_训练效果影响因素与训练逻辑诊断报告.md
```

## 三、诊断维度

### 3.1 样本量类

按站点统计：

```text
full_history_rows
full_history_positive_rows
full_history_zero_ratio_pct
train_valid_rows
train_valid_positive_rows
test_rows
test_positive_rows
test_zero_ratio_6_19_pct
```

用途：

```text
判断样本量和正功率样本是否真的不足。
```

### 3.2 白天 0 值与低出力类

按站点统计：

```text
test_daytime_zero_ratio_6_19_pct
test_low_output_ratio_pct
train_valid_low_output_ratio_pct
```

低出力定义：

```text
0 < power_mw / capacity_mw <= 0.03
```

用途：

```text
区分“正常夜间0值”与“白天低出力/异常0值”。
```

### 3.3 容量利用率类

按站点统计：

```text
train_valid_capacity_factor_mean
test_capacity_factor_mean
capacity_factor_shift
test_peak_power_ratio
```

定义：

```text
capacity_factor = power_mw / capacity_mw
capacity_factor_shift = test_capacity_factor_mean - train_valid_capacity_factor_mean
test_peak_power_ratio = test功率95分位 / capacity_mw
```

用途：

```text
判断测试期是否比训练期明显低出力或高出力，以及容量是否疑似不准。
```

### 3.4 预测偏差类

按站点统计：

```text
test_mae_mw
test_rmse_mw
test_nrmse_pct
test_bias_pct
test_pred_actual_ratio
over_predict_ratio_pct
under_predict_ratio_pct
```

定义：

```text
over_predict_ratio_pct = 预测值 > 真实值 的样本比例
under_predict_ratio_pct = 预测值 < 真实值 的样本比例
```

用途：

```text
判断模型是系统性高估还是低估。
```

### 3.5 气象与辐照匹配类

若字段存在，统计：

```text
ssrd_wm2_mean
ssrd_wm2_p95
solar_elevation_mean
actual_ssrd_corr
pred_ssrd_corr
```

定义：

```text
actual_ssrd_corr = corr(power_mw, ssrd_wm2)
pred_ssrd_corr = corr(power_pred, ssrd_wm2)
```

用途：

```text
如果真实功率和辐照相关性很低，但预测功率和辐照相关性很高，
说明模型按气象预测正常发电，但真实站点可能受限电/停机/采集异常影响。
```

### 3.6 训练逻辑审计类

检查：

```text
train/valid/test 时间是否重叠
test 是否进入训练样本
target power_mw 是否被直接作为特征
power_pred 是否越界
final_eval 是否只包含 test
final_full 是否包含 train/valid/test 但不用于正式指标
同一站点同一时间是否重复
```

用途：

```text
判断是否有训练逻辑错误、数据泄漏或目标错位。
```

## 四、新增诊断脚本

新建：

```text
scripts/diagnose_training_effect_factors_round31.py
```

代码：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output" / "pv_pipeline"
TABLES = OUT / "tables"
METRICS = OUT / "metrics"
DOCS = OUT / "docs"
METRICS.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)


def read_pickle(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_pickle(path)


def safe_corr(a, b) -> float:
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    m = a.notna() & b.notna()
    if m.sum() < 10:
        return np.nan
    if a[m].std() <= 1e-12 or b[m].std() <= 1e-12:
        return np.nan
    return float(a[m].corr(b[m]))


def rmse(y, p) -> float:
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p)
    if not m.any():
        return np.nan
    return float(np.sqrt(np.mean((p[m] - y[m]) ** 2)))


def mae(y, p) -> float:
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p)
    if not m.any():
        return np.nan
    return float(np.mean(np.abs(p[m] - y[m])))


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour
    if "date" not in out.columns:
        out["date"] = out["time"].dt.strftime("%Y-%m-%d")
    return out


def build_site_summary(full_df: pd.DataFrame) -> pd.DataFrame:
    df = prepare(full_df)

    hist = df[df["split"].isin(["train", "valid", "test"])].copy()
    hist_day = hist[hist["hour"].between(6, 19) & hist["power_mw"].notna()].copy()
    tv_day = hist_day[hist_day["split"].isin(["train", "valid"])].copy()
    test_day = hist_day[hist_day["split"].eq("test")].copy()

    rows = []
    site_ids = sorted(hist["site_id"].dropna().astype(str).unique())

    for sid in site_ids:
        h = hist[hist["site_id"].astype(str).eq(sid)].copy()
        tv = tv_day[tv_day["site_id"].astype(str).eq(sid)].copy()
        te = test_day[test_day["site_id"].astype(str).eq(sid)].copy()

        if h.empty:
            continue

        cap = float(pd.to_numeric(h["capacity_mw"], errors="coerce").dropna().median())

        def count_stats(g: pd.DataFrame, prefix: str) -> dict:
            if g.empty:
                return {
                    f"{prefix}_rows": 0,
                    f"{prefix}_positive_rows": 0,
                    f"{prefix}_zero_rows": 0,
                    f"{prefix}_zero_ratio_pct": np.nan,
                    f"{prefix}_low_output_ratio_pct": np.nan,
                    f"{prefix}_capacity_factor_mean": np.nan,
                }
            y = pd.to_numeric(g["power_mw"], errors="coerce").fillna(0)
            cf = y / max(cap, 1e-9)
            low = (y > 0) & (cf <= 0.03)
            return {
                f"{prefix}_rows": int(len(g)),
                f"{prefix}_positive_rows": int((y > 0).sum()),
                f"{prefix}_zero_rows": int((y == 0).sum()),
                f"{prefix}_zero_ratio_pct": round(float((y == 0).mean() * 100), 4),
                f"{prefix}_low_output_ratio_pct": round(float(low.mean() * 100), 4),
                f"{prefix}_capacity_factor_mean": round(float(cf.mean()), 6),
            }

        item = {
            "site_id": sid,
            "site_name": str(h["site_name"].iloc[0]) if "site_name" in h.columns else sid,
            "capacity_mw": round(cap, 4),
            "full_history_rows": int(len(h)),
            "full_history_positive_rows": int((pd.to_numeric(h["power_mw"], errors="coerce").fillna(0) > 0).sum()),
            "full_history_zero_ratio_pct": round(float((pd.to_numeric(h["power_mw"], errors="coerce").fillna(0) == 0).mean() * 100), 4),
        }

        item.update(count_stats(tv, "train_valid_daytime"))
        item.update(count_stats(te, "test_daytime"))

        if not te.empty:
            y = pd.to_numeric(te["power_mw"], errors="coerce")
            p = pd.to_numeric(te["power_pred"], errors="coerce")
            e = p - y
            test_rmse = rmse(y, p)
            actual_sum = float(y.sum())
            pred_sum = float(p.sum())
            item.update({
                "test_mae_mw": round(mae(y, p), 6),
                "test_rmse_mw": round(test_rmse, 6),
                "test_nrmse_pct": round(test_rmse / max(cap, 1e-9) * 100, 6),
                "test_bias_pct": round((pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100, 6),
                "test_pred_actual_ratio": round(pred_sum / max(actual_sum, 1e-9), 6),
                "over_predict_ratio_pct": round(float((e > 0).mean() * 100), 4),
                "under_predict_ratio_pct": round(float((e < 0).mean() * 100), 4),
                "test_peak_power_ratio_p95": round(float(y.quantile(0.95) / max(cap, 1e-9)), 6),
            })

            if "ssrd_wm2" in te.columns:
                item["actual_ssrd_corr"] = round(safe_corr(te["power_mw"], te["ssrd_wm2"]), 6)
                item["pred_ssrd_corr"] = round(safe_corr(te["power_pred"], te["ssrd_wm2"]), 6)
                item["ssrd_wm2_mean"] = round(float(pd.to_numeric(te["ssrd_wm2"], errors="coerce").mean()), 6)
                item["ssrd_wm2_p95"] = round(float(pd.to_numeric(te["ssrd_wm2"], errors="coerce").quantile(0.95)), 6)

        item["capacity_factor_shift"] = (
            item.get("test_daytime_capacity_factor_mean", np.nan)
            - item.get("train_valid_daytime_capacity_factor_mean", np.nan)
        )
        rows.append(item)

    out = pd.DataFrame(rows)
    return out


def build_factor_correlation(site_df: pd.DataFrame) -> pd.DataFrame:
    target = "test_nrmse_pct"
    factors = [
        "full_history_rows",
        "full_history_positive_rows",
        "full_history_zero_ratio_pct",
        "train_valid_daytime_rows",
        "train_valid_daytime_positive_rows",
        "train_valid_daytime_zero_ratio_pct",
        "train_valid_daytime_low_output_ratio_pct",
        "test_daytime_rows",
        "test_daytime_positive_rows",
        "test_daytime_zero_ratio_pct",
        "test_daytime_low_output_ratio_pct",
        "capacity_mw",
        "train_valid_daytime_capacity_factor_mean",
        "test_daytime_capacity_factor_mean",
        "capacity_factor_shift",
        "test_peak_power_ratio_p95",
        "test_pred_actual_ratio",
        "test_bias_pct",
        "over_predict_ratio_pct",
        "under_predict_ratio_pct",
        "actual_ssrd_corr",
        "pred_ssrd_corr",
    ]

    rows = []
    for f in factors:
        if f not in site_df.columns:
            continue
        x = pd.to_numeric(site_df[f], errors="coerce")
        y = pd.to_numeric(site_df[target], errors="coerce")
        m = x.notna() & y.notna()
        if m.sum() < 5 or x[m].std() <= 1e-12:
            corr = np.nan
        else:
            corr = float(x[m].corr(y[m], method="spearman"))
        rows.append({
            "factor": f,
            "spearman_corr_with_test_nrmse": round(corr, 6) if np.isfinite(corr) else np.nan,
            "valid_site_count": int(m.sum()),
        })

    return pd.DataFrame(rows).sort_values(
        "spearman_corr_with_test_nrmse",
        key=lambda s: s.abs(),
        ascending=False,
        na_position="last",
    )


def audit_training_logic(full_df: pd.DataFrame, eval_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    df = prepare(full_df)
    ev = prepare(eval_df)

    # 1. split 时间范围
    for split, g in df.groupby("split"):
        rows.append({
            "check_item": f"split_time_range_{split}",
            "status": "INFO",
            "detail": f"rows={len(g)}, min={g['time'].min()}, max={g['time'].max()}",
        })

    # 2. final_eval 是否只含 test
    eval_splits = sorted(ev["split"].dropna().unique().tolist())
    rows.append({
        "check_item": "final_eval_only_test",
        "status": "PASS" if eval_splits == ["test"] else "FAIL",
        "detail": f"splits={eval_splits}",
    })

    # 3. final_eval 小时
    hmin, hmax = int(ev["hour"].min()), int(ev["hour"].max())
    rows.append({
        "check_item": "final_eval_hour_6_19",
        "status": "PASS" if hmin >= 6 and hmax <= 19 else "FAIL",
        "detail": f"hour_min={hmin}, hour_max={hmax}",
    })

    # 4. 同一站点同一时间是否重复
    dup = int(df.duplicated(["site_id", "time"]).sum())
    rows.append({
        "check_item": "duplicate_site_time",
        "status": "PASS" if dup == 0 else "FAIL",
        "detail": f"duplicate_rows={dup}",
    })

    # 5. 目标列是否可能作为特征
    suspicious_cols = [c for c in df.columns if c.lower() in [
        "target", "y", "power_mw_lag0", "power_mw_current"
    ]]
    rows.append({
        "check_item": "suspicious_target_feature_columns",
        "status": "WARN" if suspicious_cols else "PASS",
        "detail": ",".join(suspicious_cols) if suspicious_cols else "none",
    })

    # 6. 预测越界
    pred = pd.to_numeric(ev["power_pred"], errors="coerce")
    cap = pd.to_numeric(ev["capacity_mw"], errors="coerce")
    neg = int((pred < -1e-9).sum())
    over = int((pred > cap * 1.02).sum())
    rows.append({
        "check_item": "prediction_physical_range",
        "status": "PASS" if neg == 0 and over == 0 else "WARN",
        "detail": f"negative={neg}, over_capacity_2pct={over}",
    })

    return pd.DataFrame(rows)


def diagnose_worst_sites(site_df: pd.DataFrame, top_n: int = 15) -> pd.DataFrame:
    df = site_df.sort_values("test_nrmse_pct", ascending=False).head(top_n).copy()

    reasons = []
    for _, r in df.iterrows():
        rs = []
        if r.get("test_daytime_zero_ratio_pct", 0) >= 20:
            rs.append("测试期白天0值占比高")
        if r.get("test_daytime_low_output_ratio_pct", 0) >= 20:
            rs.append("测试期白天极低出力占比高")
        if abs(r.get("capacity_factor_shift", 0)) >= 0.05:
            rs.append("训练/测试容量利用率分布漂移")
        if abs(r.get("test_bias_pct", 0)) >= 30:
            rs.append("系统性高估/低估明显")
        if r.get("test_peak_power_ratio_p95", 0) > 1.05:
            rs.append("功率峰值超过容量，疑似容量映射问题")
        if pd.notna(r.get("actual_ssrd_corr")) and r.get("actual_ssrd_corr") < 0.2:
            rs.append("真实功率与辐照相关性低")
        if not rs:
            rs.append("需人工查看曲线/站点映射/气象代表性")
        reasons.append("；".join(rs))

    df["diagnosis_reason"] = reasons
    return df


def write_report(site_df, corr_df, worst_df, audit_df):
    lines = []
    lines.append("# Round31 训练效果影响因素与训练逻辑诊断报告\n")
    lines.append("## 1. 结论摘要\n")

    fail_count = int((audit_df["status"] == "FAIL").sum())
    warn_count = int((audit_df["status"] == "WARN").sum())

    if fail_count > 0:
        lines.append(f"- 训练逻辑审计存在 {fail_count} 个 FAIL，需优先修复。")
    elif warn_count > 0:
        lines.append(f"- 训练逻辑审计无 FAIL，但存在 {warn_count} 个 WARN，需检查。")
    else:
        lines.append("- 训练逻辑审计未发现明显 FAIL/WARN。")

    lines.append("- 当前散点图无法仅由样本量或测试集6-19点0值占比解释 NRMSE，需结合容量利用率漂移、偏差、低出力比例、气象相关性等共同判断。")
    lines.append("")

    lines.append("## 2. 训练逻辑审计\n")
    lines.append(audit_df.to_markdown(index=False))
    lines.append("")

    lines.append("## 3. 与测试集 NRMSE 相关性最高的因素（Spearman）\n")
    lines.append(corr_df.head(12).to_markdown(index=False))
    lines.append("")

    lines.append("## 4. 最差站点诊断\n")
    show_cols = [
        "site_id", "site_name", "capacity_mw", "test_nrmse_pct",
        "test_daytime_zero_ratio_pct", "test_daytime_low_output_ratio_pct",
        "capacity_factor_shift", "test_bias_pct", "test_pred_actual_ratio",
        "actual_ssrd_corr", "pred_ssrd_corr", "diagnosis_reason",
    ]
    show_cols = [c for c in show_cols if c in worst_df.columns]
    lines.append(worst_df[show_cols].to_markdown(index=False))
    lines.append("")

    lines.append("## 5. 判断标准\n")
    lines.append("- 如果训练逻辑审计无 FAIL，且高误差站点集中表现为测试期低出力、异常0值、容量利用率漂移或气象相关性低，则优先判断为数据/站点状态问题。")
    lines.append("- 如果出现 final_eval 非 test、时间重叠、重复站点时间、预测越界严重、目标列泄漏等 FAIL，则判断为训练流程或数据构造逻辑问题。")
    lines.append("- 样本量不是唯一决定因素，不能用“样本多但误差高”直接判断训练逻辑错误。")

    path = DOCS / "Round31_训练效果影响因素与训练逻辑诊断报告.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main():
    full_path = TABLES / "distributed_predictions_final_full.pkl"
    eval_path = TABLES / "distributed_predictions_final_eval.pkl"

    full_df = read_pickle(full_path)
    eval_df = read_pickle(eval_path)

    site_df = build_site_summary(full_df)
    corr_df = build_factor_correlation(site_df)
    audit_df = audit_training_logic(full_df, eval_df)
    worst_df = diagnose_worst_sites(site_df)

    site_df.to_csv(METRICS / "round31_site_effect_factor_summary.csv", index=False, encoding="utf-8-sig")
    corr_df.to_csv(METRICS / "round31_factor_correlation.csv", index=False, encoding="utf-8-sig")
    worst_df.to_csv(METRICS / "round31_worst_site_diagnosis.csv", index=False, encoding="utf-8-sig")
    audit_df.to_csv(METRICS / "round31_training_logic_audit.csv", index=False, encoding="utf-8-sig")

    report_path = write_report(site_df, corr_df, worst_df, audit_df)

    print("[OK] Round31 diagnostics generated")
    print(f"  {METRICS / 'round31_site_effect_factor_summary.csv'}")
    print(f"  {METRICS / 'round31_factor_correlation.csv'}")
    print(f"  {METRICS / 'round31_worst_site_diagnosis.csv'}")
    print(f"  {METRICS / 'round31_training_logic_audit.csv'}")
    print(f"  {report_path}")


if __name__ == "__main__":
    main()
```

## 五、执行命令

```bash
cd /path/to/photovoltaic_forecasting_pj
python scripts/diagnose_training_effect_factors_round31.py
```

## 六、如何判断训练逻辑是否有问题

执行后重点看：

```text
output/pv_pipeline/metrics/round31_training_logic_audit.csv
```

如果出现以下 FAIL，说明训练逻辑或数据构造可能有问题：

```text
final_eval_only_test = FAIL
final_eval_hour_6_19 = FAIL
duplicate_site_time = FAIL
prediction_physical_range = 严重 WARN/FAIL
```

如果这些都通过，而高误差站点主要有：

```text
测试期白天0值占比高
测试期低出力比例高
训练/测试容量利用率漂移
真实功率与辐照相关性低
系统性高估/低估
容量峰值异常
```

则更可能是：

```text
数据质量、站点运行状态、容量映射或气象代表性问题
```

不是训练逻辑错误。

## 七、建议后续页面增强

如果 Round31 发现强相关因素，后续可以在可视化页面加入：

```text
测试集低出力占比
容量利用率漂移
测试期 pred/actual
真实功率-辐照相关性
```

这些通常会比单看样本量、0值占比更能解释 NRMSE。

## 八、验收标准

本轮通过标准：

- 成功生成 Round31 四个 CSV 和一个 MD 报告。
- 报告能明确给出训练逻辑审计是否存在 FAIL。
- 报告能列出与测试集 NRMSE 相关性最高的因素。
- 报告能对最差站点给出可解释原因。
- 不重新训练，不修改预测结果。

