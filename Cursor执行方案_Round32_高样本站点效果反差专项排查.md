# Cursor 执行方案 Round32：高样本站点效果反差专项排查

## 一、排查目标

当前现象：

```text
部分 26,000+ 行历史样本的站点，测试集 NRMSE 反而比 6,000 行左右的站点更差；
而且这些高样本站点的全量 0 值占比不一定更高。
```

这不一定说明训练逻辑错误。需要进一步排查：

1. 高样本站点是否在测试期发生分布漂移。
2. 高样本站点是否存在系统性高估/低估。
3. 高样本站点是否容量映射不准。
4. 高样本站点是否测试期白天低出力比例高。
5. 高样本站点是否有重复 `site_id + time` 记录。
6. 高样本站点是否真实功率与辐照相关性差。
7. 高样本站点是否在特定月份/小时集中出错。

本轮只做排查，不重新训练，不修改预测结果。

## 二、输出文件

新增脚本：

```text
scripts/diagnose_high_sample_bad_sites_round32.py
```

输出：

```text
output/pv_pipeline/metrics/round32_high_sample_vs_low_sample_compare.csv
output/pv_pipeline/metrics/round32_high_sample_bad_site_monthly.csv
output/pv_pipeline/metrics/round32_high_sample_bad_site_hourly.csv
output/pv_pipeline/metrics/round32_duplicate_site_time_detail.csv
output/pv_pipeline/metrics/round32_capacity_mapping_suspicion.csv
output/pv_pipeline/docs/Round32_高样本站点效果反差专项排查报告.md
```

## 三、对比对象定义

### 3.1 高样本但效果差站点

定义：

```text
full_history_rows >= 20000
test_nrmse_pct >= 15
```

这类站点是重点排查对象。

### 3.2 中低样本但效果好站点

定义：

```text
full_history_rows <= 8000
test_nrmse_pct <= 10
```

这类站点作为对照组。

如果样本数量不足，可放宽：

```text
full_history_rows <= 10000
test_nrmse_pct <= 12
```

## 四、新增脚本

新建：

```text
scripts/diagnose_high_sample_bad_sites_round32.py
```

代码：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

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


def prep(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour
    if "date" not in out.columns:
        out["date"] = out["time"].dt.strftime("%Y-%m-%d")
    out["month"] = out["time"].dt.strftime("%Y-%m")
    return out


def rmse(y, p):
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p)
    if not m.any():
        return np.nan
    return float(np.sqrt(np.mean((p[m] - y[m]) ** 2)))


def mae(y, p):
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p)
    if not m.any():
        return np.nan
    return float(np.mean(np.abs(p[m] - y[m])))


def safe_corr(a, b):
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    m = a.notna() & b.notna()
    if m.sum() < 10:
        return np.nan
    if a[m].std() <= 1e-12 or b[m].std() <= 1e-12:
        return np.nan
    return float(a[m].corr(b[m]))


def site_name_lookup():
    path = TABLES / "site_master.csv"
    if not path.exists():
        return {}
    sm = pd.read_csv(path)
    name_col = "site_short_name" if "site_short_name" in sm.columns else "site_full_name"
    return dict(zip(sm["site_id"].astype(str), sm[name_col].astype(str)))


def build_site_features(full_df: pd.DataFrame) -> pd.DataFrame:
    df = prep(full_df)
    names = site_name_lookup()

    hist = df[df["split"].isin(["train", "valid", "test"])].copy()
    hist_day = hist[hist["hour"].between(6, 19) & hist["power_mw"].notna()].copy()
    tv = hist_day[hist_day["split"].isin(["train", "valid"])].copy()
    te = hist_day[hist_day["split"].eq("test")].copy()

    rows = []
    for sid in sorted(hist["site_id"].astype(str).unique()):
        h = hist[hist["site_id"].astype(str).eq(sid)].copy()
        tvs = tv[tv["site_id"].astype(str).eq(sid)].copy()
        tes = te[te["site_id"].astype(str).eq(sid)].copy()
        if h.empty:
            continue

        cap = float(pd.to_numeric(h["capacity_mw"], errors="coerce").dropna().median())

        def stats(g, prefix):
            if g.empty:
                return {
                    f"{prefix}_rows": 0,
                    f"{prefix}_positive_rows": 0,
                    f"{prefix}_zero_ratio_pct": np.nan,
                    f"{prefix}_low_output_ratio_pct": np.nan,
                    f"{prefix}_capacity_factor_mean": np.nan,
                    f"{prefix}_capacity_factor_p95": np.nan,
                }
            y = pd.to_numeric(g["power_mw"], errors="coerce").fillna(0)
            cf = y / max(cap, 1e-9)
            low = (y > 0) & (cf <= 0.03)
            return {
                f"{prefix}_rows": int(len(g)),
                f"{prefix}_positive_rows": int((y > 0).sum()),
                f"{prefix}_zero_ratio_pct": round(float((y == 0).mean() * 100), 4),
                f"{prefix}_low_output_ratio_pct": round(float(low.mean() * 100), 4),
                f"{prefix}_capacity_factor_mean": round(float(cf.mean()), 6),
                f"{prefix}_capacity_factor_p95": round(float(cf.quantile(0.95)), 6),
            }

        item = {
            "site_id": sid,
            "site_name": names.get(sid, sid),
            "capacity_mw": round(cap, 4),
            "full_history_rows": int(len(h)),
            "full_history_positive_rows": int((pd.to_numeric(h["power_mw"], errors="coerce").fillna(0) > 0).sum()),
            "full_history_zero_ratio_pct": round(float((pd.to_numeric(h["power_mw"], errors="coerce").fillna(0) == 0).mean() * 100), 4),
        }
        item.update(stats(tvs, "train_valid"))
        item.update(stats(tes, "test"))

        if not tes.empty:
            y = pd.to_numeric(tes["power_mw"], errors="coerce")
            p = pd.to_numeric(tes["power_pred"], errors="coerce")
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
                "test_actual_sum_mwh": round(actual_sum, 6),
                "test_pred_sum_mwh": round(pred_sum, 6),
            })
            if "ssrd_wm2" in tes.columns:
                item["test_actual_ssrd_corr"] = round(safe_corr(tes["power_mw"], tes["ssrd_wm2"]), 6)
                item["test_pred_ssrd_corr"] = round(safe_corr(tes["power_pred"], tes["ssrd_wm2"]), 6)
        else:
            item.update({
                "test_mae_mw": np.nan,
                "test_rmse_mw": np.nan,
                "test_nrmse_pct": np.nan,
                "test_bias_pct": np.nan,
                "test_pred_actual_ratio": np.nan,
            })

        item["capacity_factor_shift_mean"] = (
            item.get("test_capacity_factor_mean", np.nan)
            - item.get("train_valid_capacity_factor_mean", np.nan)
        )
        item["capacity_factor_shift_p95"] = (
            item.get("test_capacity_factor_p95", np.nan)
            - item.get("train_valid_capacity_factor_p95", np.nan)
        )

        rows.append(item)

    out = pd.DataFrame(rows)
    return out


def build_groups(site_df: pd.DataFrame) -> pd.DataFrame:
    out = site_df.copy()
    out["diagnosis_group"] = "other"
    out.loc[
        (out["full_history_rows"] >= 20000)
        & (out["test_nrmse_pct"] >= 15),
        "diagnosis_group",
    ] = "high_sample_bad"
    out.loc[
        (out["full_history_rows"] <= 8000)
        & (out["test_nrmse_pct"] <= 10),
        "diagnosis_group",
    ] = "low_sample_good"

    # 放宽对照组
    if (out["diagnosis_group"] == "low_sample_good").sum() < 3:
        out.loc[
            (out["full_history_rows"] <= 10000)
            & (out["test_nrmse_pct"] <= 12),
            "diagnosis_group",
        ] = "low_sample_good_relaxed"

    return out


def monthly_hourly(full_df: pd.DataFrame, target_sites: list[str]):
    df = prep(full_df)
    test = df[
        df["split"].eq("test")
        & df["hour"].between(6, 19)
        & df["site_id"].astype(str).isin(target_sites)
        & df["power_mw"].notna()
        & df["power_pred"].notna()
    ].copy()

    month_rows = []
    hour_rows = []

    for (sid, month), g in test.groupby(["site_id", "month"]):
        cap = float(pd.to_numeric(g["capacity_mw"], errors="coerce").median())
        y = pd.to_numeric(g["power_mw"], errors="coerce")
        p = pd.to_numeric(g["power_pred"], errors="coerce")
        r = rmse(y, p)
        month_rows.append({
            "site_id": sid,
            "month": month,
            "rows": len(g),
            "zero_ratio_pct": round(float((y.fillna(0) == 0).mean() * 100), 4),
            "low_output_ratio_pct": round(float(((y > 0) & ((y / max(cap, 1e-9)) <= 0.03)).mean() * 100), 4),
            "actual_sum_mwh": round(float(y.sum()), 6),
            "pred_sum_mwh": round(float(p.sum()), 6),
            "pred_actual_ratio": round(float(p.sum()) / max(float(y.sum()), 1e-9), 6),
            "rmse_mw": round(r, 6),
            "nrmse_pct": round(r / max(cap, 1e-9) * 100, 6),
        })

    for (sid, hour), g in test.groupby(["site_id", "hour"]):
        cap = float(pd.to_numeric(g["capacity_mw"], errors="coerce").median())
        y = pd.to_numeric(g["power_mw"], errors="coerce")
        p = pd.to_numeric(g["power_pred"], errors="coerce")
        r = rmse(y, p)
        hour_rows.append({
            "site_id": sid,
            "hour": int(hour),
            "rows": len(g),
            "zero_ratio_pct": round(float((y.fillna(0) == 0).mean() * 100), 4),
            "actual_mean_mw": round(float(y.mean()), 6),
            "pred_mean_mw": round(float(p.mean()), 6),
            "rmse_mw": round(r, 6),
            "nrmse_pct": round(r / max(cap, 1e-9) * 100, 6),
        })

    return pd.DataFrame(month_rows), pd.DataFrame(hour_rows)


def duplicate_detail(full_df: pd.DataFrame) -> pd.DataFrame:
    df = prep(full_df)
    dup_mask = df.duplicated(["site_id", "time"], keep=False)
    dup = df[dup_mask].copy()
    if dup.empty:
        return pd.DataFrame(columns=["site_id", "time", "split", "dup_count"])

    cols = [
        "site_id", "time", "split", "power_mw", "power_pred",
        "capacity_mw", "power_alias", "power_name_norm", "match_score", "match_method",
    ]
    cols = [c for c in cols if c in dup.columns]
    dup["dup_count"] = dup.groupby(["site_id", "time"])["site_id"].transform("size")
    return dup[cols + ["dup_count"]].sort_values(["site_id", "time"])


def capacity_suspicion(site_df: pd.DataFrame) -> pd.DataFrame:
    df = site_df.copy()
    flags = []
    for _, r in df.iterrows():
        rs = []
        if r.get("test_capacity_factor_p95", 0) > 1.05:
            rs.append("测试期95分位功率超过容量")
        if r.get("train_valid_capacity_factor_p95", 0) > 1.05:
            rs.append("训练期95分位功率超过容量")
        if abs(r.get("capacity_factor_shift_p95", 0)) > 0.25:
            rs.append("训练/测试峰值容量利用率漂移大")
        flags.append("；".join(rs))
    df["capacity_mapping_suspicion"] = flags
    return df[df["capacity_mapping_suspicion"] != ""].copy()


def write_report(site_df, month_df, hour_df, dup_df, cap_df):
    high_bad = site_df[site_df["diagnosis_group"].eq("high_sample_bad")].copy()
    low_good = site_df[site_df["diagnosis_group"].str.startswith("low_sample_good")].copy()

    lines = []
    lines.append("# Round32 高样本站点效果反差专项排查报告\n")

    lines.append("## 1. 结论摘要\n")
    lines.append(f"- 高样本但效果差站点数：{len(high_bad)}")
    lines.append(f"- 中低样本但效果好对照站点数：{len(low_good)}")
    lines.append(f"- 重复 site_id+time 明细行数：{len(dup_df)}")
    lines.append(f"- 容量映射疑似异常站点数：{cap_df['site_id'].nunique() if not cap_df.empty else 0}")
    lines.append("")

    if len(high_bad):
        lines.append("高样本站点效果差通常不由样本量单独决定，优先检查测试期容量利用率漂移、系统性偏差、白天0值/低出力和容量映射。")
    else:
        lines.append("按当前阈值未发现明显高样本但效果差站点。")
    lines.append("")

    lines.append("## 2. 高样本但效果差站点\n")
    cols = [
        "site_id", "site_name", "capacity_mw", "full_history_rows",
        "full_history_zero_ratio_pct", "train_valid_positive_rows",
        "test_zero_ratio_pct", "test_low_output_ratio_pct",
        "train_valid_capacity_factor_mean", "test_capacity_factor_mean",
        "capacity_factor_shift_mean", "test_nrmse_pct",
        "test_pred_actual_ratio", "test_bias_pct",
        "test_actual_ssrd_corr", "test_pred_ssrd_corr",
    ]
    cols = [c for c in cols if c in high_bad.columns]
    lines.append(high_bad[cols].sort_values("test_nrmse_pct", ascending=False).to_markdown(index=False) if len(high_bad) else "无")
    lines.append("")

    lines.append("## 3. 中低样本但效果好对照站点\n")
    cols2 = [c for c in cols if c in low_good.columns]
    lines.append(low_good[cols2].sort_values("test_nrmse_pct").head(15).to_markdown(index=False) if len(low_good) else "无")
    lines.append("")

    lines.append("## 4. 高样本差站点逐月误差\n")
    if len(month_df):
        lines.append(month_df.sort_values(["site_id", "month"]).to_markdown(index=False))
    else:
        lines.append("无")
    lines.append("")

    lines.append("## 5. 高样本差站点逐小时误差\n")
    if len(hour_df):
        lines.append(hour_df.sort_values(["site_id", "hour"]).to_markdown(index=False))
    else:
        lines.append("无")
    lines.append("")

    lines.append("## 6. 重复记录排查\n")
    if len(dup_df):
        lines.append("存在重复 `site_id + time`，需先确认是否同一功率别名重复映射或多条记录未去重。建议后续按 site_id+time 去重后重跑指标。")
        lines.append(dup_df.head(30).to_markdown(index=False))
    else:
        lines.append("未发现重复 `site_id + time`。")
    lines.append("")

    lines.append("## 7. 容量映射疑似异常\n")
    if len(cap_df):
        show = [
            "site_id", "site_name", "capacity_mw",
            "train_valid_capacity_factor_p95", "test_capacity_factor_p95",
            "capacity_factor_shift_p95", "capacity_mapping_suspicion",
        ]
        show = [c for c in show if c in cap_df.columns]
        lines.append(cap_df[show].to_markdown(index=False))
    else:
        lines.append("未发现明显容量映射异常。")
    lines.append("")

    lines.append("## 8. 判断建议\n")
    lines.append("- 如果高样本差站点的 `test_pred_actual_ratio` 远离 1，说明是系统性高估/低估。")
    lines.append("- 如果 `capacity_factor_shift_mean` 或 `capacity_factor_shift_p95` 很大，说明训练期和测试期出力分布不一致。")
    lines.append("- 如果测试期 0 值/低出力比例高，说明测试期运行状态异常可能主导误差。")
    lines.append("- 如果真实功率与辐照相关性低，而预测功率与辐照相关性高，说明模型按气象预测正常发电，但站点实际受非气象因素影响。")
    lines.append("- 如果重复记录存在，必须先修复重复记录，否则样本量和城市聚合可能被扰动。")

    path = DOCS / "Round32_高样本站点效果反差专项排查报告.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main():
    full_df = read_pickle(TABLES / "distributed_predictions_final_full.pkl")

    site_df = build_site_features(full_df)
    site_df = build_groups(site_df)

    high_bad_sites = site_df[site_df["diagnosis_group"].eq("high_sample_bad")]["site_id"].astype(str).tolist()
    month_df, hour_df = monthly_hourly(full_df, high_bad_sites)
    dup_df = duplicate_detail(full_df)
    cap_df = capacity_suspicion(site_df)

    site_df.to_csv(METRICS / "round32_high_sample_vs_low_sample_compare.csv", index=False, encoding="utf-8-sig")
    month_df.to_csv(METRICS / "round32_high_sample_bad_site_monthly.csv", index=False, encoding="utf-8-sig")
    hour_df.to_csv(METRICS / "round32_high_sample_bad_site_hourly.csv", index=False, encoding="utf-8-sig")
    dup_df.to_csv(METRICS / "round32_duplicate_site_time_detail.csv", index=False, encoding="utf-8-sig")
    cap_df.to_csv(METRICS / "round32_capacity_mapping_suspicion.csv", index=False, encoding="utf-8-sig")

    report_path = write_report(site_df, month_df, hour_df, dup_df, cap_df)

    print("[OK] Round32 diagnostics generated")
    print(f"  high_sample_bad_sites = {len(high_bad_sites)}")
    print(f"  duplicate_rows = {len(dup_df)}")
    print(f"  capacity_suspicion_sites = {cap_df['site_id'].nunique() if not cap_df.empty else 0}")
    print(f"  report = {report_path}")


if __name__ == "__main__":
    main()
```

## 五、执行命令

```bash
cd /path/to/photovoltaic_forecasting_pj
python scripts/diagnose_high_sample_bad_sites_round32.py
```

## 六、重点看哪些结果

### 6.1 高样本差站点对比表

看：

```text
output/pv_pipeline/metrics/round32_high_sample_vs_low_sample_compare.csv
```

重点字段：

```text
full_history_rows
test_nrmse_pct
test_zero_ratio_pct
test_low_output_ratio_pct
capacity_factor_shift_mean
test_pred_actual_ratio
test_bias_pct
test_actual_ssrd_corr
test_pred_ssrd_corr
```

判断：

- `test_pred_actual_ratio >> 1`：模型系统性高估；
- `test_pred_actual_ratio << 1`：模型系统性低估；
- `capacity_factor_shift_mean` 绝对值大：训练/测试分布漂移；
- `test_actual_ssrd_corr` 低：真实功率不随辐照变化，可能非气象因素主导；
- `test_zero_ratio_pct` 或 `test_low_output_ratio_pct` 高：测试期运行/数据异常。

### 6.2 逐月误差表

看：

```text
round32_high_sample_bad_site_monthly.csv
```

判断误差是不是集中在某几个月。

如果只在某个月突然变差，通常不是训练逻辑整体问题，而是该月站点状态/数据质量问题。

### 6.3 逐小时误差表

看：

```text
round32_high_sample_bad_site_hourly.csv
```

判断误差是不是集中在早晚或正午。

### 6.4 重复记录明细

看：

```text
round32_duplicate_site_time_detail.csv
```

如果重复集中在高样本差站点，说明样本量偏高可能来自重复记录，需要优先修复。

## 七、下一步判断

如果 Round32 发现：

```text
高样本差站点重复记录明显
```

下一轮应做：

```text
site_id + time 去重修复
```

如果发现：

```text
高样本差站点测试期 pred/actual 远离 1
```

下一轮应做：

```text
站点级测试期偏差诊断和校准，但不能用 test 调参，只能用 valid 学校准
```

如果发现：

```text
真实功率与辐照相关性低
```

下一轮应做：

```text
异常运行状态识别/剔除，不把非气象因素强行让模型学习
```

如果发现：

```text
容量利用率峰值超过 1 或漂移明显
```

下一轮应做：

```text
容量映射和台账核验
```

## 八、验收标准

本轮通过标准：

- 成功生成 Round32 五个输出文件。
- 能列出高样本但效果差站点。
- 能列出中低样本但效果好站点作为对照。
- 能说明高样本站点差是由哪类因素主导。
- 能确认重复记录是否影响这些站点。
- 不重新训练，不修改预测结果。

