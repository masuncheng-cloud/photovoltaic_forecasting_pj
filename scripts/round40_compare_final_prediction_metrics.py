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
