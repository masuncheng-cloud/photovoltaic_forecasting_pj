from pathlib import Path
import math
import shutil
import numpy as np
import pandas as pd


ROOT = Path("output/pv_pipeline")
TABLE_DIR = ROOT / "tables"
METRIC_DIR = ROOT / "metrics"


def find_final_pkl():
    candidates = sorted(TABLE_DIR.glob("distributed_predictions_final_round*.pkl"))
    if candidates:
        return candidates[-1]
    return TABLE_DIR / "distributed_predictions_final_full.pkl"


def rmse(a):
    a = np.asarray(a, dtype=float)
    return math.sqrt(float(np.mean(a * a))) if len(a) else 0.0


def normalize(df):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    return df


def city_hourly_nrmse(df, pred_col, splits, hours):
    """Compute per-hour city NRMSE and suspicious zeros. Used for guard."""
    work = df[
        df["split"].isin(splits if isinstance(splits, list) else [splits])
        & df["hour"].isin(hours)
        & df["power_mw"].notna()
        & df[pred_col].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()
    if work.empty:
        return None

    work["actual"] = pd.to_numeric(work["power_mw"], errors="coerce")
    work["pred"] = pd.to_numeric(work[pred_col], errors="coerce")
    work = work[work["actual"].notna() & work["pred"].notna()].copy()

    rows = []
    for hour, hdf in work.groupby("hour"):
        city = hdf.groupby("time", as_index=False).agg(
            actual_mw=("actual", "sum"),
            pred_mw=("pred", "sum"),
            capacity_sum_mw=("capacity_mw", "sum"),
        )
        err = city["pred_mw"] - city["actual_mw"]
        rmse_mw = rmse(err)
        cap = float(city["capacity_sum_mw"].mean())
        nrmse = rmse_mw / max(cap, 1e-9) * 100
        suspicious_zero = int(
            ((city["actual_mw"] > 1e-9) & (city["pred_mw"].abs() <= 1e-9)).sum()
        )
        rows.append({
            "hour": int(hour),
            "city_nrmse_pct": nrmse,
            "suspicious_city_zero_count": suspicious_zero,
        })
    return pd.DataFrame(rows)


def city_overall_nrmse(df, pred_col):
    """Compute overall city NRMSE and bias."""
    work = df[
        df["split"].eq("test")
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df[pred_col].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()
    if work.empty:
        return {}
    work["actual"] = pd.to_numeric(work["power_mw"], errors="coerce")
    work["pred"] = pd.to_numeric(work[pred_col], errors="coerce")
    work = work[work["actual"].notna() & work["pred"].notna()].copy()

    city = work.groupby("time", as_index=False).agg(
        actual_mw=("actual", "sum"),
        pred_mw=("pred", "sum"),
        capacity_sum_mw=("capacity_mw", "sum"),
    )
    err = city["pred_mw"] - city["actual_mw"]
    rmse_mw = rmse(err)
    cap = float(city["capacity_sum_mw"].mean())
    nrmse = rmse_mw / max(cap, 1e-9) * 100
    bias = (city["pred_mw"].sum() - city["actual_mw"].sum()) / max(city["actual_mw"].sum(), 1e-9) * 100
    return {"city_nrmse_pct": nrmse, "city_bias_pct": bias}


def site_mean_nrmse(df, pred_col):
    """Compute full and active site mean NRMSE."""
    work = df[
        df["split"].eq("test")
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df[pred_col].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()
    work["actual"] = pd.to_numeric(work["power_mw"], errors="coerce")
    work["pred"] = pd.to_numeric(work[pred_col], errors="coerce")
    work["cap"] = pd.to_numeric(work["capacity_mw"], errors="coerce")
    work["active_threshold"] = np.maximum(0.02 * work["cap"], 0.05)
    work["is_active"] = work["actual"] > work["active_threshold"]
    work = work[work["actual"].notna() & work["pred"].notna()].copy()

    full_rows, active_rows = [], []
    for sid, g in work.groupby("site_id"):
        cap = float(g["cap"].mean())
        err = g["pred"] - g["actual"]
        nrmse_full = rmse(err) / max(cap, 1e-9) * 100
        full_rows.append(nrmse_full)

        active = g[g["is_active"]]
        if len(active):
            aerr = active["pred"] - active["actual"]
            nrmse_active = rmse(aerr) / max(cap, 1e-9) * 100
            active_rows.append(nrmse_active)

    return {
        "full_site_mean_nrmse_pct": float(np.mean(full_rows)),
        "active_site_mean_nrmse_pct": float(np.nanmean(active_rows)),
    }


def main():
    pkl = find_final_pkl()
    backup = pkl.with_suffix(".before_round41_42.pkl")

    df = pd.read_pickle(pkl)
    df = normalize(df)
    pred_col = "power_pred_final"

    # Compute all metrics directly from current PKL
    print("Computing guard metrics from PKL:", pkl)

    # 1. Edge suspicious zeros (test 6/7/18/19)
    edge_df = city_hourly_nrmse(df, pred_col, "test", [6, 7, 18, 19])
    edge_susp = int(edge_df["suspicious_city_zero_count"].sum()) if edge_df is not None else -1

    # 2. Focus 10-14 city hourly NRMSE (test)
    focus_df = city_hourly_nrmse(df, pred_col, "test", [10, 11, 12, 13, 14])
    focus_nrmse = float(focus_df["city_nrmse_pct"].mean()) if focus_df is not None else -1

    # 3. Overall city NRMSE (test 6-19)
    overall = city_overall_nrmse(df, pred_col)
    city_nrmse = overall.get("city_nrmse_pct", -1)
    city_bias = overall.get("city_bias_pct", -1)

    # 4. Site mean NRMSE
    site_metrics = site_mean_nrmse(df, pred_col)
    full_site_mean = site_metrics["full_site_mean_nrmse_pct"]
    active_site_mean = site_metrics["active_site_mean_nrmse_pct"]

    checks = [
        {
            "check": "edge_suspicious_city_zero_count",
            "value": edge_susp,
            "threshold": 0,
            "status": "PASS" if edge_susp == 0 else "FAIL",
        },
        {
            "check": "focus_10_14_city_hourly_nrmse_under_6",
            "value": round(focus_nrmse, 6),
            "threshold": 6.0,
            "status": "PASS" if focus_nrmse <= 6.0 else "FAIL",
        },
        {
            "check": "city_nrmse_under_10",
            "value": round(city_nrmse, 6),
            "threshold": 10.0,
            "status": "PASS" if city_nrmse <= 10.0 else "FAIL",
        },
        {
            "check": "city_abs_bias_under_15",
            "value": round(abs(city_bias), 6),
            "threshold": 15.0,
            "status": "PASS" if abs(city_bias) <= 15.0 else "FAIL",
        },
        {
            "check": "full_site_mean_nrmse_under_35",
            "value": round(full_site_mean, 6),
            "threshold": 35.0,
            "status": "PASS" if full_site_mean <= 35.0 else "FAIL",
        },
        {
            "check": "active_site_mean_nrmse_under_25",
            "value": round(active_site_mean, 6),
            "threshold": 25.0,
            "status": "PASS" if active_site_mean <= 25.0 else "FAIL",
        },
    ]

    out = pd.DataFrame(checks)
    out.to_csv(METRIC_DIR / "round41_42_guard.csv", index=False, encoding="utf-8-sig")
    print(out.to_string(index=False))

    if (out["status"] == "FAIL").any():
        if backup.exists():
            shutil.copy2(backup, pkl)
            print("[RESTORE] guard failed, restored:", pkl)
        raise SystemExit("[FAIL] Round41+42 guard failed")

    print("[PASS] Round41+42 guard passed")


if __name__ == "__main__":
    main()
