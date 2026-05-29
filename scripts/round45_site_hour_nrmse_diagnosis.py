"""
round45_site_hour_nrmse_diagnosis.py
====================================
Round45 Step 1: 诊断单站点逐小时 NRMSE 高的来源。

对 test 集 6-19 点每个 (site_id, hour) 组合计算：
- 站点-小时 NRMSE
- 活跃/零值比例
- 站点-小时偏差

输出：
- round45_site_hour_nrmse_diagnosis.csv
- round45_hourly_site_nrmse_summary.csv
- round45_site_hour_nrmse_top_outliers.csv
"""

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
