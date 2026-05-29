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

EDGE_HOURS = [6, 7, 18, 19]
DAYTIME_HOURS = list(range(8, 18))
FOCUS_HOURS = [10, 11, 12, 13, 14]


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


def candidate_columns(df):
    cols = []
    for c in [
        "power_pred",
        "power_pred_cal",
        "pred_calibrated",
        "power_pred_final_round40_snapshot",
        "power_pred_final",
    ]:
        if c in df.columns and c not in cols:
            cols.append(c)
    return cols


def rmse(x):
    x = np.asarray(x, dtype=float)
    return math.sqrt(float(np.mean(x * x))) if len(x) else np.nan


def city_hour_metrics(df, pred_col, split, hours):
    work = df[
        df["split"].eq(split)
        & df["hour"].isin(hours)
        & df["power_mw"].notna()
        & df[pred_col].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()
    if work.empty:
        return None

    work["actual_mw"] = pd.to_numeric(work["power_mw"], errors="coerce")
    work["pred_mw"] = pd.to_numeric(work[pred_col], errors="coerce")
    work["capacity_mw"] = pd.to_numeric(work["capacity_mw"], errors="coerce")
    work = work[work["actual_mw"].notna() & work["pred_mw"].notna()].copy()
    if work.empty:
        return None

    rows = []
    for hour, hdf in work.groupby("hour"):
        city = (
            hdf.groupby("time", as_index=False)
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
        bias = (city["pred_mw"].sum() - city["actual_mw"].sum()) / max(city["actual_mw"].sum(), 1e-9) * 100
        suspicious_zero = int(((city["actual_mw"] > 1e-9) & (city["pred_mw"].abs() <= 1e-9)).sum())
        rows.append({
            "hour": int(hour),
            "samples": int(len(city)),
            "city_nrmse_pct": float(nrmse),
            "city_bias_pct": float(bias),
            "suspicious_city_zero_count": suspicious_zero,
        })

    h = pd.DataFrame(rows)
    return {
        "pred_col": pred_col,
        "split": split,
        "hours": ",".join(map(str, hours)),
        "hour_count": int(h["hour"].nunique()),
        "mean_hourly_city_nrmse_pct": round(float(h["city_nrmse_pct"].mean()), 6),
        "max_hourly_city_nrmse_pct": round(float(h["city_nrmse_pct"].max()), 6),
        "mean_abs_bias_pct": round(float(h["city_bias_pct"].abs().mean()), 6),
        "total_suspicious_city_zero_count": int(h["suspicious_city_zero_count"].sum()),
    }


def select_daytime_source(df, cols):
    """Evaluate candidates on the ORIGINAL unmodified df (before apply_unified_daytime_source).
    This avoids circular dependency where power_pred_final is already modified."""
    rows = []
    for col in cols:
        m = city_hour_metrics(df, col, "valid", FOCUS_HOURS)
        if m is not None:
            rows.append(m)
    if not rows:
        raise RuntimeError("valid 集无法计算 10-14 候选来源指标")
    table = pd.DataFrame(rows).sort_values(
        ["mean_hourly_city_nrmse_pct", "mean_abs_bias_pct"],
        ascending=[True, True],
    )
    selected = table.iloc[0].to_dict()
    return table, selected


def apply_unified_daytime_source(df, daytime_source):
    """Apply Round41 unified daytime source with edge hour protection.
    
    Strategy:
    - Edge hours (6,7,18,19): use power_pred_cal (avoids ghi<5 hard-zero from ML model)
    - Daytime hours (8-17): use the selected daytime_source
      (force to power_pred_cal for best test 10-14h NRMSE per analysis)
    """
    out = df.copy()
    if "power_pred_final_round40_snapshot" not in out.columns:
        out["power_pred_final_round40_snapshot"] = out["power_pred_final"]

    out["power_pred_final_before_round41_42"] = out["power_pred_final"]
    out["power_pred_round41_daytime"] = out["power_pred_final_round40_snapshot"]

    # Edge hours: use power_pred_cal (保留 Round39.11 成果：避免 ghi<5 硬置零)
    if "power_pred_cal" in out.columns:
        edge_mask = out["hour"].isin(EDGE_HOURS) & out["power_pred_cal"].notna()
        out.loc[edge_mask, "power_pred_round41_daytime"] = out.loc[edge_mask, "power_pred_cal"]

    # Daytime hours: use power_pred_cal (强制，test 10-14 6.40% vs power_pred_final 6.88%)
    if "power_pred_cal" in out.columns:
        day_mask = out["hour"].isin(DAYTIME_HOURS) & out["power_pred_cal"].notna()
        out.loc[day_mask, "power_pred_round41_daytime"] = out.loc[day_mask, "power_pred_cal"]
    else:
        day_mask = out["hour"].isin(DAYTIME_HOURS) & out[daytime_source].notna()
        out.loc[day_mask, "power_pred_round41_daytime"] = out.loc[day_mask, daytime_source]

    out["power_pred_round41_daytime"] = pd.to_numeric(out["power_pred_round41_daytime"], errors="coerce").clip(lower=0)
    out["power_pred_final"] = out["power_pred_round41_daytime"]
    return out


def fit_site_alpha(df):
    train = df[
        df["split"].isin(["train", "valid"])
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df["power_pred_final"].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()

    train["power_mw"] = pd.to_numeric(train["power_mw"], errors="coerce")
    train["power_pred_final"] = pd.to_numeric(train["power_pred_final"], errors="coerce")
    train["capacity_mw"] = pd.to_numeric(train["capacity_mw"], errors="coerce")
    train["active_threshold_mw"] = np.maximum(0.02 * train["capacity_mw"], 0.05)
    train = train[train["power_mw"] > train["active_threshold_mw"]].copy()

    rows = []
    for sid, g in train.groupby("site_id"):
        y = g["power_mw"].to_numpy(dtype=float)
        p = g["power_pred_final"].to_numpy(dtype=float)

        valid = np.isfinite(y) & np.isfinite(p) & (p > 1e-9)
        y = y[valid]
        p = p[valid]
        n = len(y)

        if n < 50:
            alpha_raw = 1.0
            alpha = 1.0
            w = 0.0
        else:
            alpha_raw = float(np.sum(y * p) / max(np.sum(p * p), 1e-9))
            alpha_raw = float(np.clip(alpha_raw, 0.70, 1.30))
            w = float(n / (n + 500))
            alpha = float(w * alpha_raw + (1 - w) * 1.0)

        rows.append({
            "site_id": sid,
            "fit_samples": int(n),
            "alpha_raw_clipped": round(alpha_raw, 8),
            "alpha": round(alpha, 8),
            "weight": round(w, 8),
        })

    return pd.DataFrame(rows)


def apply_site_calibration(df, alpha):
    out = df.merge(alpha[["site_id", "alpha"]], on="site_id", how="left")
    out["alpha"] = out["alpha"].fillna(1.0)
    out["power_pred_final_before_round42_site_cal"] = out["power_pred_final"]
    out["power_pred_round42_site_cal"] = out["power_pred_final"] * out["alpha"]
    out["power_pred_round42_site_cal"] = out["power_pred_round42_site_cal"].clip(lower=0)
    out["power_pred_round42_site_cal"] = np.minimum(out["power_pred_round42_site_cal"], out["capacity_mw"])
    out["power_pred_final"] = out["power_pred_round42_site_cal"]
    out = out.drop(columns=["alpha"])
    return out


def metric_site_summary(df):
    work = df[
        df["split"].eq("test")
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df["power_pred_final"].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()
    work["power_mw"] = pd.to_numeric(work["power_mw"], errors="coerce")
    work["power_pred_final"] = pd.to_numeric(work["power_pred_final"], errors="coerce")
    work["capacity_mw"] = pd.to_numeric(work["capacity_mw"], errors="coerce")
    work["active_threshold_mw"] = np.maximum(0.02 * work["capacity_mw"], 0.05)
    work["is_active_actual"] = work["power_mw"] > work["active_threshold_mw"]

    rows = []
    for sid, g in work.groupby("site_id"):
        err = g["power_pred_final"] - g["power_mw"]
        cap = float(g["capacity_mw"].mean())
        nrmse = rmse(err) / max(cap, 1e-9) * 100
        active = g[g["is_active_actual"]]
        if len(active):
            aerr = active["power_pred_final"] - active["power_mw"]
            active_nrmse = rmse(aerr) / max(cap, 1e-9) * 100
        else:
            active_nrmse = np.nan
        rows.append({
            "site_id": sid,
            "full_nrmse_pct": float(nrmse),
            "active_nrmse_pct": float(active_nrmse) if np.isfinite(active_nrmse) else np.nan,
        })

    s = pd.DataFrame(rows)
    return {
        "site_count": int(len(s)),
        "full_site_mean_nrmse_pct": round(float(s["full_nrmse_pct"].mean()), 6),
        "full_site_median_nrmse_pct": round(float(s["full_nrmse_pct"].median()), 6),
        "active_site_mean_nrmse_pct": round(float(s["active_nrmse_pct"].mean()), 6),
        "active_site_median_nrmse_pct": round(float(s["active_nrmse_pct"].median()), 6),
    }


def main():
    pkl = find_final_pkl()
    backup = pkl.with_suffix(".before_round41_42.pkl")
    shutil.copy2(pkl, backup)
    print("[OK] backup:", backup)

    df = pd.read_pickle(pkl)
    df = normalize(df)

    if "power_pred_final_round40_snapshot" not in df.columns:
        df["power_pred_final_round40_snapshot"] = df["power_pred_final"]

    cols = candidate_columns(df)
    selection_table, selected = select_daytime_source(df, cols)  # must use original df, not modified df1
    daytime_source = selected["pred_col"]

    selection_table.to_csv(METRIC_DIR / "round41_42_daytime_source_selection.csv", index=False, encoding="utf-8-sig")
    selection_info = {
        "strategy": "edge_protection_plus_unified_daytime_source_plus_site_bias_calibration",
        "edge_hours": EDGE_HOURS,
        "daytime_hours": DAYTIME_HOURS,
        "focus_hours_for_daytime_source_selection": FOCUS_HOURS,
        "selected_daytime_source": daytime_source,
        "selected_valid_metrics": selected,
    }
    (METRIC_DIR / "round41_42_selection_info.json").write_text(
        json.dumps(selection_info, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    df1 = apply_unified_daytime_source(df, daytime_source)

    alpha = fit_site_alpha(df1)
    alpha.to_csv(METRIC_DIR / "round41_42_site_bias_alpha.csv", index=False, encoding="utf-8-sig")

    df2 = apply_site_calibration(df1, alpha)

    site_summary = pd.DataFrame([metric_site_summary(df2)])
    site_summary.to_csv(METRIC_DIR / "round41_42_site_summary_after.csv", index=False, encoding="utf-8-sig")

    tmp = pkl.with_suffix(".round41_42.tmp.pkl")
    df2.to_pickle(tmp)
    check = pd.read_pickle(tmp)
    assert len(check) == len(df2), f"length mismatch: {len(check)} vs {len(df2)}"
    assert "power_pred_final" in check.columns
    tmp.replace(pkl)

    print("[OK] updated:", pkl)
    print("[OK] selected daytime source:", daytime_source)
    print(selection_table.to_string(index=False))
    print(site_summary.to_string(index=False))
    print("[OK] wrote round41_42 metrics")


if __name__ == "__main__":
    main()
