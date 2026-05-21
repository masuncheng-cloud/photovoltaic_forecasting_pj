from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ..core.utils import corr, mae, nmae, nrmse, rmse


plt.rcParams['axes.unicode_minus'] = False


def evaluate_data_quality(power_clean: pd.DataFrame, mapping: pd.DataFrame, site_master: pd.DataFrame) -> pd.DataFrame:
    mapped_alias = mapping["site_id"].notna().mean()
    df = power_clean.copy()
    daytime = df["daytime_flag"] == 1
    rows = [{
        "metric": "site_mapping_rate",
        "value": float(mapped_alias),
    }, {
        "metric": "negative_large_rate",
        "value": float(df["flag_negative_large"].mean()),
    }, {
        "metric": "over_capacity_rate",
        "value": float((df["flag_over_capacity"].fillna(False) | df.get("flag_over_capacity_soft", False)).mean()),
    }, {
        "metric": "day_zero_rate",
        "value": float(df.loc[daytime, "flag_day_zero"].mean()) if daytime.any() else np.nan,
    }, {
        "metric": "day_zero_run_rate",
        "value": float(df.loc[daytime, "flag_day_zero_run"].mean()) if "flag_day_zero_run" in df.columns and daytime.any() else np.nan,
    }, {
        "metric": "usable_sample_rate",
        "value": float(df["power_mw"].notna().mean()),
    }]
    return pd.DataFrame(rows)



def evaluate_distributed_by_site(pred_df: pd.DataFrame, site_master: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for site_id, g in pred_df.groupby("site_id"):
        scale = float(g["capacity_mw"].iloc[0]) if np.isfinite(g["capacity_mw"].iloc[0]) and g["capacity_mw"].iloc[0] > 0 else None
        rows.append({
            "site_id": site_id,
            "rows": len(g),
            "mae": mae(g["power_mw"].to_numpy(), g["power_pred"].to_numpy()),
            "rmse": rmse(g["power_mw"].to_numpy(), g["power_pred"].to_numpy()),
            "nmae_cap": nmae(g["power_mw"].to_numpy(), g["power_pred"].to_numpy(), scale=scale),
            "nrmse_cap": nrmse(g["power_mw"].to_numpy(), g["power_pred"].to_numpy(), scale=scale),
            "corr": corr(g["power_mw"].to_numpy(), g["power_pred"].to_numpy()),
        })
    out = pd.DataFrame(rows)
    merge_cols = [c for c in ["site_id", "site_short_name", "county", "capacity_mw", "install_group", "capacity_bucket", "coastal_flag"] if c in site_master.columns]
    out = out.merge(site_master[merge_cols], on="site_id", how="left")
    return out.sort_values("rmse", ascending=False)



def evaluate_distributed_by_county(pred_df: pd.DataFrame) -> pd.DataFrame:
    agg = pred_df.groupby(["time", "county"], as_index=False)[["power_mw", "power_pred"]].sum()
    rows = []
    for county, g in agg.groupby("county"):
        rows.append({
            "county": county,
            "rows": len(g),
            "mae": mae(g["power_mw"].to_numpy(), g["power_pred"].to_numpy()),
            "rmse": rmse(g["power_mw"].to_numpy(), g["power_pred"].to_numpy()),
            "nrmse": nrmse(g["power_mw"].to_numpy(), g["power_pred"].to_numpy()),
            "corr": corr(g["power_mw"].to_numpy(), g["power_pred"].to_numpy()),
        })
    return pd.DataFrame(rows).sort_values("rmse", ascending=False)



def evaluate_pred_by_group(pred_df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for key, g in pred_df.groupby(group_col):
        rows.append({
            group_col: key,
            'rows': len(g),
            'mae': mae(g['power_mw'].to_numpy(), g['power_pred'].to_numpy()),
            'rmse': rmse(g['power_mw'].to_numpy(), g['power_pred'].to_numpy()),
            'nrmse': nrmse(g['power_mw'].to_numpy(), g['power_pred'].to_numpy()),
            'corr': corr(g['power_mw'].to_numpy(), g['power_pred'].to_numpy()),
        })
    return pd.DataFrame(rows).sort_values('rmse', ascending=False)



def evaluate_city_total(pred_df: pd.DataFrame) -> pd.DataFrame:
    agg = pred_df.groupby("time", as_index=False)[["power_mw", "power_pred"]].sum()
    return pd.DataFrame([{
        "scope": "city_total",
        "rows": len(agg),
        "mae": mae(agg["power_mw"].to_numpy(), agg["power_pred"].to_numpy()),
        "rmse": rmse(agg["power_mw"].to_numpy(), agg["power_pred"].to_numpy()),
        "nrmse": nrmse(agg["power_mw"].to_numpy(), agg["power_pred"].to_numpy()),
        "corr": corr(agg["power_mw"].to_numpy(), agg["power_pred"].to_numpy()),
    }])



def get_top_day_zero_sites(power_clean: pd.DataFrame, site_master: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    daytime = power_clean[power_clean['daytime_flag'] == 1].copy()
    rows = []
    for site_id, g in daytime.groupby('site_id'):
        if pd.isna(site_id):
            continue
        rows.append({
            'site_id': site_id,
            'day_zero_rate': float(g['flag_day_zero'].mean()),
            'day_zero_run_rate': float(g['flag_day_zero_run'].mean()) if 'flag_day_zero_run' in g.columns else np.nan,
            'day_rows': len(g),
        })
    out = pd.DataFrame(rows)
    merge_cols = [c for c in ['site_id', 'site_short_name', 'county', 'capacity_mw', 'dev_type'] if c in site_master.columns]
    out = out.merge(site_master[merge_cols], on='site_id', how='left')
    return out.sort_values(['day_zero_run_rate', 'day_zero_rate', 'capacity_mw'], ascending=[False, False, False]).head(top_n)



def plot_typical_day(pred_df: pd.DataFrame, out_path: Path) -> None:
    pred_df = pred_df.copy()
    pred_df["date"] = pd.to_datetime(pred_df["time"]).dt.date
    pred_df["hour"] = pd.to_datetime(pred_df["time"]).dt.hour
    daily = pred_df.groupby(["date", "hour"], as_index=False)[["power_mw", "power_pred"]].sum()
    if daily.empty:
        return
    daily["abs_err"] = (daily["power_mw"] - daily["power_pred"]).abs()
    daily_mae = daily.groupby("date", as_index=True)["abs_err"].mean()
    target_date = daily_mae.sort_values().index[len(daily_mae) // 2]
    g = daily[daily["date"] == target_date]
    plt.figure(figsize=(10, 4))
    plt.plot(g["hour"], g["power_mw"], label="Actual total power")
    plt.plot(g["hour"], g["power_pred"], label="Predicted total power")
    plt.xlabel("Hour")
    plt.ylabel("MW")
    plt.title(f"Typical day total power comparison: {target_date}")
    plt.legend()
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=180)
    plt.close()
