# Round45：单站点逐小时 NRMSE 专项诊断与稳健校准

## 一、当前问题

Round44 已经完成：

```text
dashboard 自动刷新与一致性校验
单站点曲线、典型站点、四季最佳日等页面问题回归检查
早晚 6/7/18/19 不再整城贴 0
训练逻辑基本严谨化
```

但仍有一个突出问题：

```text
单站点逐小时 NRMSE 偏高，尤其 10-14 点站点平均 NRMSE 明显高于城市 NRMSE。
```

当前现象说明：

```text
全市聚合预测还可以；
单站点层面误差被小容量站、异常 0 值、低功率样本、站点偏差、分布漂移放大。
```

本轮目标：

```text
专门降低单站点逐小时 NRMSE；
同时不破坏全市 10-14 NRMSE、全市 BIAS、早晚不贴 0。
```

---

## 二、核心原则

1. 不使用 test 集选择参数。
2. test 集只用于最终评估。
3. 不改主指标分母，仍使用：

```text
NRMSE = RMSE / capacity_mw × 100%
```

4. 不简单删除异常样本来美化结果。
5. 不恢复 `GHI < 5 => 6-19 点强制置 0`。
6. 校准必须有守门：

```text
站点平均 NRMSE 要下降；
全市 10-14 NRMSE 不明显变差；
全市 BIAS 不超阈值；
早晚可疑 0 值保持为 0。
```

---

## 三、总体思路

本轮分三步：

```text
Step 1：诊断单站点逐小时 NRMSE 高的来源；
Step 2：用 train+valid 学习站点-小时稳健校准系数；
Step 3：只在 valid 守门通过时启用，最终 test 只评估。
```

校准对象不是全局一个系数，而是更细但仍可解释的分组：

```text
(site_id, hour)
```

但为了避免过拟合，必须做 shrinkage：

```text
alpha_final = w * alpha_site_hour + (1 - w) * alpha_hour
w = n / (n + K)
```

其中：

```text
alpha_site_hour：该站点该小时的校准系数
alpha_hour：所有站点该小时的公共校准系数
K：收缩强度，建议 300
alpha_final 限制在 [0.75, 1.25]
```

这样比纯站点校准更适合逐小时 NRMSE，同时仍有解释性：

```text
不同站点在不同小时存在系统偏差，用验证期前数据学习一个收缩校准系数。
```

---

## 四、先修正 Round44 中 test fallback 风险

修改：

```text
scripts/round41_42_unified_daytime_and_site_calibration.py
```

搜索：

```bash
grep -n "test_fallback\\|fallback_delta\\|test.*power_pred_cal\\|test.*fallback\\|test_used" scripts/round41_42_unified_daytime_and_site_calibration.py
```

要求：

1. 删除“如果 test 上 power_pred_cal 更好则回退”的逻辑。
2. `selection_info.json` 必须写明：

```json
{
  "selection_split": "valid",
  "test_used_for_selection": false
}
```

3. test 结果只写入最终评估，不参与选择。

---

## 五、新增诊断脚本

新增：

```text
scripts/round45_site_hour_nrmse_diagnosis.py
```

内容：

```python
from pathlib import Path
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


def normalize(df):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    if "date" not in df.columns:
        df["date"] = df["time"].dt.strftime("%Y-%m-%d")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    return df


def rmse(x):
    x = np.asarray(x, dtype=float)
    return math.sqrt(float(np.mean(x * x))) if len(x) else np.nan


def main():
    pkl = find_final_pkl()
    df = pd.read_pickle(pkl)
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
    work["active_threshold_mw"] = np.maximum(0.02 * work["capacity_mw"], 0.05)
    work["is_active"] = work["actual_mw"] > work["active_threshold_mw"]
    work["is_zero_actual"] = work["actual_mw"].abs() <= 1e-9
    work["is_zero_pred"] = work["pred_mw"].abs() <= 1e-9

    rows = []
    for (sid, hour), g in work.groupby(["site_id", "hour"]):
        err = g["pred_mw"] - g["actual_mw"]
        cap = float(g["capacity_mw"].mean())
        actual_sum = float(g["actual_mw"].sum())
        pred_sum = float(g["pred_mw"].sum())
        nrmse = rmse(err) / max(cap, 1e-9) * 100
        active = g[g["is_active"]]
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
            "zero_actual_ratio_pct": round(float(g["is_zero_actual"].mean() * 100), 6),
            "zero_pred_ratio_pct": round(float(g["is_zero_pred"].mean() * 100), 6),
            "active_ratio_pct": round(float(g["is_active"].mean() * 100), 6),
            "nrmse_pct": round(float(nrmse), 6),
            "active_nrmse_pct": round(float(active_nrmse), 6) if np.isfinite(active_nrmse) else np.nan,
            "bias_pct": round((pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100, 6) if actual_sum > 1e-9 else np.nan,
            "pred_actual": round(pred_sum / max(actual_sum, 1e-9), 6) if actual_sum > 1e-9 else np.nan,
        })

    site_hour = pd.DataFrame(rows)
    site_hour.to_csv(METRIC_DIR / "round45_site_hour_nrmse_diagnosis.csv", index=False, encoding="utf-8-sig")

    hourly = (
        site_hour.groupby("hour", as_index=False)
        .agg(
            site_count=("site_id", "nunique"),
            mean_site_nrmse_pct=("nrmse_pct", "mean"),
            median_site_nrmse_pct=("nrmse_pct", "median"),
            p90_site_nrmse_pct=("nrmse_pct", lambda s: float(np.nanpercentile(s, 90))),
            mean_active_nrmse_pct=("active_nrmse_pct", "mean"),
            mean_zero_actual_ratio_pct=("zero_actual_ratio_pct", "mean"),
            high_nrmse_site_count=("nrmse_pct", lambda s: int((s > 30).sum())),
        )
    )
    hourly.to_csv(METRIC_DIR / "round45_hourly_site_nrmse_summary.csv", index=False, encoding="utf-8-sig")

    outlier = site_hour.sort_values("nrmse_pct", ascending=False).head(80)
    outlier.to_csv(METRIC_DIR / "round45_site_hour_nrmse_top_outliers.csv", index=False, encoding="utf-8-sig")

    print("[OK] pkl:", pkl)
    print(hourly.to_string(index=False))
    print("[OK] wrote round45 diagnosis files")


if __name__ == "__main__":
    main()
```

执行：

```bash
python scripts/round45_site_hour_nrmse_diagnosis.py
```

---

## 六、新增站点-小时稳健校准脚本

新增：

```text
scripts/round45_apply_site_hour_shrinkage_calibration.py
```

内容：

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

K = 300
ALPHA_MIN = 0.75
ALPHA_MAX = 1.25


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
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    return df


def fit_alpha(y, p):
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    valid = np.isfinite(y) & np.isfinite(p) & (p > 1e-9)
    y = y[valid]
    p = p[valid]
    if len(y) < 20:
        return 1.0, len(y)
    alpha = float(np.sum(y * p) / max(np.sum(p * p), 1e-9))
    return float(np.clip(alpha, ALPHA_MIN, ALPHA_MAX)), len(y)


def build_calibration_table(df):
    train = df[
        df["split"].isin(["train", "valid"])
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df["power_pred_final"].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()

    train["actual_mw"] = pd.to_numeric(train["power_mw"], errors="coerce")
    train["pred_mw"] = pd.to_numeric(train["power_pred_final"], errors="coerce")
    train["capacity_mw"] = pd.to_numeric(train["capacity_mw"], errors="coerce")
    train["active_threshold_mw"] = np.maximum(0.02 * train["capacity_mw"], 0.05)

    # 只用有效发电样本拟合，避免大量0值主导系数
    train = train[train["actual_mw"] > train["active_threshold_mw"]].copy()

    hour_rows = []
    for hour, g in train.groupby("hour"):
        alpha_hour, n = fit_alpha(g["actual_mw"], g["pred_mw"])
        hour_rows.append({
            "hour": int(hour),
            "alpha_hour": alpha_hour,
            "hour_fit_samples": int(n),
        })
    hour_alpha = pd.DataFrame(hour_rows)

    rows = []
    for (sid, hour), g in train.groupby(["site_id", "hour"]):
        alpha_site_hour, n = fit_alpha(g["actual_mw"], g["pred_mw"])
        rows.append({
            "site_id": sid,
            "hour": int(hour),
            "alpha_site_hour": alpha_site_hour,
            "fit_samples": int(n),
        })
    site_hour = pd.DataFrame(rows)
    table = site_hour.merge(hour_alpha, on="hour", how="left")
    table["alpha_hour"] = table["alpha_hour"].fillna(1.0)
    table["weight"] = table["fit_samples"] / (table["fit_samples"] + K)
    table["alpha_final"] = table["weight"] * table["alpha_site_hour"] + (1 - table["weight"]) * table["alpha_hour"]
    table["alpha_final"] = table["alpha_final"].clip(ALPHA_MIN, ALPHA_MAX)

    return table, hour_alpha


def apply_calibration(df, table):
    out = df.merge(table[["site_id", "hour", "alpha_final"]], on=["site_id", "hour"], how="left")
    out["alpha_final"] = out["alpha_final"].fillna(1.0)
    out["power_pred_final_before_round45"] = out["power_pred_final"]
    out["power_pred_final_round45_candidate"] = out["power_pred_final"] * out["alpha_final"]
    out["power_pred_final_round45_candidate"] = out["power_pred_final_round45_candidate"].clip(lower=0)
    out["power_pred_final_round45_candidate"] = np.minimum(
        out["power_pred_final_round45_candidate"],
        out["capacity_mw"],
    )
    out = out.drop(columns=["alpha_final"])
    return out


def main():
    pkl = find_final_pkl()
    backup = pkl.with_suffix(".before_round45.pkl")
    shutil.copy2(pkl, backup)
    print("[OK] backup:", backup)

    df = pd.read_pickle(pkl)
    df = normalize(df)

    table, hour_alpha = build_calibration_table(df)
    table.to_csv(METRIC_DIR / "round45_site_hour_alpha.csv", index=False, encoding="utf-8-sig")
    hour_alpha.to_csv(METRIC_DIR / "round45_hour_alpha.csv", index=False, encoding="utf-8-sig")

    out = apply_calibration(df, table)

    # 先写候选列，不直接覆盖；由 guard 决定是否启用
    tmp = pkl.with_suffix(".round45_candidate.tmp.pkl")
    out.to_pickle(tmp)
    check = pd.read_pickle(tmp)
    assert "power_pred_final_round45_candidate" in check.columns
    assert len(check) == len(out)
    tmp.replace(pkl)

    print("[OK] wrote candidate to:", pkl)
    print("[OK] alpha rows:", len(table))


if __name__ == "__main__":
    main()
```

执行：

```bash
python scripts/round45_apply_site_hour_shrinkage_calibration.py
```

---

## 七、新增 Round45 守门脚本

新增：

```text
scripts/round45_guard_and_commit.py
```

内容：

```python
from pathlib import Path
import math
import shutil
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


def normalize(df):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    return df


def rmse(x):
    x = np.asarray(x, dtype=float)
    return math.sqrt(float(np.mean(x * x))) if len(x) else np.nan


def evaluate(df, pred_col, split="valid"):
    work = df[
        df["split"].eq(split)
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df[pred_col].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()

    work["actual_mw"] = pd.to_numeric(work["power_mw"], errors="coerce")
    work["pred_mw"] = pd.to_numeric(work[pred_col], errors="coerce")
    work["capacity_mw"] = pd.to_numeric(work["capacity_mw"], errors="coerce")

    city = work.groupby("time", as_index=False).agg(
        actual_mw=("actual_mw", "sum"),
        pred_mw=("pred_mw", "sum"),
        capacity_sum_mw=("capacity_mw", "sum"),
    )
    city_err = city["pred_mw"] - city["actual_mw"]
    city_nrmse = rmse(city_err) / max(float(city["capacity_sum_mw"].mean()), 1e-9) * 100
    city_bias = (city["pred_mw"].sum() - city["actual_mw"].sum()) / max(city["actual_mw"].sum(), 1e-9) * 100

    focus = work[work["hour"].isin([10, 11, 12, 13, 14])].copy()
    focus_city = focus.groupby("time", as_index=False).agg(
        actual_mw=("actual_mw", "sum"),
        pred_mw=("pred_mw", "sum"),
        capacity_sum_mw=("capacity_mw", "sum"),
    )
    focus_err = focus_city["pred_mw"] - focus_city["actual_mw"]
    focus_nrmse = rmse(focus_err) / max(float(focus_city["capacity_sum_mw"].mean()), 1e-9) * 100

    edge = work[work["hour"].isin([6, 7, 18, 19])].copy()
    edge_city = edge.groupby("time", as_index=False).agg(
        actual_mw=("actual_mw", "sum"),
        pred_mw=("pred_mw", "sum"),
    )
    suspicious_zero = int(((edge_city["actual_mw"] > 1e-9) & (edge_city["pred_mw"].abs() <= 1e-9)).sum())

    site_rows = []
    for sid, g in work.groupby("site_id"):
        err = g["pred_mw"] - g["actual_mw"]
        cap = float(g["capacity_mw"].mean())
        site_rows.append(rmse(err) / max(cap, 1e-9) * 100)

    return {
        "split": split,
        "pred_col": pred_col,
        "city_nrmse_pct": float(city_nrmse),
        "city_bias_pct": float(city_bias),
        "focus_10_14_city_nrmse_pct": float(focus_nrmse),
        "edge_suspicious_city_zero_count": suspicious_zero,
        "site_mean_nrmse_pct": float(np.mean(site_rows)),
        "site_median_nrmse_pct": float(np.median(site_rows)),
    }


def main():
    pkl = find_final_pkl()
    backup = pkl.with_suffix(".before_round45.pkl")
    df = pd.read_pickle(pkl)
    df = normalize(df)

    if "power_pred_final_round45_candidate" not in df.columns:
        raise SystemExit("缺少 power_pred_final_round45_candidate，请先运行 round45_apply_site_hour_shrinkage_calibration.py")

    base_col = "power_pred_final_before_round45" if "power_pred_final_before_round45" in df.columns else "power_pred_final"
    cand_col = "power_pred_final_round45_candidate"

    base_valid = evaluate(df, base_col, split="valid")
    cand_valid = evaluate(df, cand_col, split="valid")

    site_improve = base_valid["site_mean_nrmse_pct"] - cand_valid["site_mean_nrmse_pct"]
    city_delta = cand_valid["city_nrmse_pct"] - base_valid["city_nrmse_pct"]
    focus_delta = cand_valid["focus_10_14_city_nrmse_pct"] - base_valid["focus_10_14_city_nrmse_pct"]

    use_candidate = (
        site_improve >= 0.2
        and city_delta <= 0.3
        and focus_delta <= 0.3
        and abs(cand_valid["city_bias_pct"]) <= 15.0
        and cand_valid["edge_suspicious_city_zero_count"] == 0
    )

    decision = {
        "use_round45_candidate": bool(use_candidate),
        "site_improve_valid_pp": round(site_improve, 6),
        "city_delta_valid_pp": round(city_delta, 6),
        "focus_delta_valid_pp": round(focus_delta, 6),
        "base_valid": base_valid,
        "candidate_valid": cand_valid,
    }

    pd.DataFrame([{
        "use_round45_candidate": use_candidate,
        "site_improve_valid_pp": site_improve,
        "city_delta_valid_pp": city_delta,
        "focus_delta_valid_pp": focus_delta,
        "base_site_mean_nrmse": base_valid["site_mean_nrmse_pct"],
        "cand_site_mean_nrmse": cand_valid["site_mean_nrmse_pct"],
        "base_city_nrmse": base_valid["city_nrmse_pct"],
        "cand_city_nrmse": cand_valid["city_nrmse_pct"],
        "base_focus_nrmse": base_valid["focus_10_14_city_nrmse_pct"],
        "cand_focus_nrmse": cand_valid["focus_10_14_city_nrmse_pct"],
        "cand_city_bias": cand_valid["city_bias_pct"],
        "cand_edge_suspicious_zero": cand_valid["edge_suspicious_city_zero_count"],
    }]).to_csv(METRIC_DIR / "round45_guard_decision.csv", index=False, encoding="utf-8-sig")

    if use_candidate:
        df["power_pred_final"] = df[cand_col]
        print("[PASS] Round45 candidate accepted")
    else:
        df["power_pred_final"] = df[base_col]
        print("[RESTORE] Round45 candidate rejected, restored base prediction")

    tmp = pkl.with_suffix(".round45_guard.tmp.pkl")
    df.to_pickle(tmp)
    check = pd.read_pickle(tmp)
    assert len(check) == len(df)
    tmp.replace(pkl)

    print(pd.DataFrame([decision]).to_string(index=False))


if __name__ == "__main__":
    main()
```

执行：

```bash
python scripts/round45_guard_and_commit.py
```

---

## 八、执行顺序

```bash
python scripts/round45_site_hour_nrmse_diagnosis.py
python scripts/round45_apply_site_hour_shrinkage_calibration.py
python scripts/round45_guard_and_commit.py
python scripts/round45_site_hour_nrmse_diagnosis.py
python scripts/round40_compare_final_prediction_metrics.py
python scripts/round41_42_guard.py
python scripts/update_dashboard_after_training.py
python scripts/check_dashboard_auto_update_stamp.py
python scripts/round44_dashboard_regression_check.py
```

---

## 九、验收标准

Round45 通过必须满足：

```text
1. round45_guard_decision.csv 中 use_round45_candidate=true，或者如果 false，则说明候选确实未改善并已回退。
2. 如果启用候选，valid 站点平均 NRMSE 至少下降 0.2pp。
3. 全市 NRMSE 上升不超过 0.3pp。
4. 10-14 全市 NRMSE 上升不超过 0.3pp。
5. 全市 BIAS 绝对值不超过 15%。
6. 早晚 edge_suspicious_city_zero_count = 0。
7. dashboard 自动刷新和回归检查全部 PASS。
```

---

## 十、如果候选被拒绝

如果 `use_round45_candidate=false`，不要强行启用。

下一步应分析：

```text
round45_site_hour_nrmse_top_outliers.csv
round45_site_hour_alpha.csv
round45_guard_decision.csv
```

如果主要是少数异常站点拉高，则不要全局校准，而是：

```text
针对异常站点做数据质量标记；
或只对稳定改善的站点启用校准。
```

---

## 十一、完成后回传

请回传：

```text
output/pv_pipeline/metrics/round45_hourly_site_nrmse_summary.csv
output/pv_pipeline/metrics/round45_site_hour_nrmse_top_outliers.csv
output/pv_pipeline/metrics/round45_site_hour_alpha.csv
output/pv_pipeline/metrics/round45_guard_decision.csv
output/pv_pipeline/metrics/round40_prediction_column_compare_summary.csv
output/pv_pipeline/metrics/round40_prediction_column_compare_hourly.csv
```

以及：

```text
逐小时 NRMSE 表截图
全市 10-14 页面截图
典型站点表截图
```

