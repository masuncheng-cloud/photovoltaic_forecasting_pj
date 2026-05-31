"""
round46_recompute_hourly_nrmse_consistent.py
==========================================
Round46 Step 2: 用统一口径重新计算逐小时站点 NRMSE。

口径：先按每个 (site_id, hour) 组合算 RMSE/capacity，再对站点取平均。
不再混用 eval_df.groupby("hour").apply(...) 混站点 RMSE 的错误逻辑。

输出：
- round46_site_hour_nrmse_consistent.csv
- round46_hourly_nrmse_consistent.csv
- hourly_prediction_summary.json（替换 dashboard 中的旧文件）
"""

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
    # 优先读 canonical 路径
    canonical = Path("output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl")
    if canonical.exists():
        return canonical
    # fallback legacy
    candidates = sorted(TABLE_DIR.glob("distributed_predictions_final_eval_round36.pkl"))
    if candidates:
        return candidates[-1]
    for name in ["distributed_predictions_final_full.pkl", "distributed_predictions_final.pkl"]:
        p = TABLE_DIR / name
        if p.exists():
            return p
    raise FileNotFoundError(
        "找不到预测文件（优先 canonical: output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl）"
    )


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
    """对每个 (site_id, hour) 计算 RMSE/capacity。"""
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

    # 写 dashboard JSON（统一口径，替换旧文件）
    records = []
    for _, r in summary.iterrows():
        records.append({
            "hour": int(r["hour"]),
            "rows": int(r["row_samples"]),
            "site_count": int(r["site_count"]),
            "site_avg_nrmse_pct": round(float(r["site_avg_nrmse_pct"]), 3),
            "site_median_nrmse_pct": round(float(r["site_median_nrmse_pct"]), 3),
            "site_p90_nrmse_pct": round(float(r["site_p90_nrmse_pct"]), 3),
            "active_site_avg_nrmse_pct": round(float(r["active_site_avg_nrmse_pct"]), 3) if pd.notna(r["active_site_avg_nrmse_pct"]) else None,
            "avg_zero_actual_ratio_pct": round(float(r["avg_zero_actual_ratio_pct"]), 3),
            "city_nrmse_pct": round(float(r["city_nrmse_pct"]), 3),
            "definition": "site_avg_nrmse = mean over sites of RMSE(site,hour)/capacity(site); city_nrmse = RMSE(city_aggregate)/mean_capacity_sum",
        })

    (DASH_DIR / "hourly_prediction_summary.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("[OK] pkl:", pkl)
    print(summary[["hour", "site_count", "site_avg_nrmse_pct", "site_median_nrmse_pct", "active_site_avg_nrmse_pct", "city_nrmse_pct"]].to_string(index=False))
    print("[OK] wrote:")
    print(" -", METRIC_DIR / "round46_site_hour_nrmse_consistent.csv")
    print(" -", METRIC_DIR / "round46_hourly_nrmse_consistent.csv")
    print(" -", DASH_DIR / "hourly_prediction_summary.json")


if __name__ == "__main__":
    main()
