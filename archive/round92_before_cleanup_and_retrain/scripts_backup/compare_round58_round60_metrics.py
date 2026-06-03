#!/usr/bin/env python3
"""
compare_round58_round60_metrics.py
=================================
对比 Round58 baseline、Round59 和 Round60 在 test 集上的效果。

使用 Round58 确认口径（per-timestamp RMSE / per-hour mean capacity）。

输出：
  output/pv_pipeline/metrics/round60_compare_summary.csv
  output/pv_pipeline/metrics/round60_compare_hourly.csv
  output/pv_pipeline/metrics/round60_compare_site.csv
"""

from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"


def rmse(a, p=None):
    if p is None:
        p = np.zeros_like(a)
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean((p - a) ** 2)))


def site_mean_nrmse(df, pred_col):
    vals = []
    for sid, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        r = rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100
        vals.append(r)
    return float(np.mean(vals)) if vals else np.nan


def city_nrmse(df, pred_col):
    """Per-timestamp aggregation, per-hour average. Matches hourly_nrmse_consistent.csv."""
    vals = []
    for h, hdf in df.groupby("hour"):
        agg = hdf.groupby("time", as_index=False).agg(
            actual=("power_mw", "sum"),
            pred=(pred_col, "sum"),
            cap_sum=("capacity_mw", "sum"),
        )
        r = rmse(agg["pred"].values - agg["actual"].values)
        cap_h = float(agg["cap_sum"].mean())
        if cap_h <= 0:
            continue
        vals.append(r / cap_h * 100)
    return float(np.mean(vals)) if vals else np.nan


def bias_pct(df, pred_col):
    a_sum = float(df["power_mw"].sum())
    p_sum = float(df[pred_col].sum())
    if abs(a_sum) < 1e-9:
        return np.nan
    return (p_sum - a_sum) / a_sum * 100


def mae_per_site(df, pred_col):
    vals = []
    for sid, sdf in df.groupby("site_id"):
        vals.append(float(np.mean(np.abs(sdf[pred_col].values - sdf["power_mw"].values))))
    return float(np.mean(vals)) if vals else np.nan


def load_and_prep(path):
    df = pd.read_pickle(path)
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    return df


def main():
    print("=" * 60)
    print("Round58 vs Round59 vs Round60 对比报告")
    print("=" * 60)

    # Load all eval pkls
    r58 = load_and_prep(OUT / "baselines/round58/distributed_predictions_final_eval.pkl")
    r59 = load_and_prep(OUT / "baselines/round59/distributed_predictions_final_eval.pkl")
    r60 = load_and_prep(OUT / "predictions/distributed_predictions_final_eval.pkl")

    # Rename pred columns
    r58 = r58.rename(columns={"power_pred_final": "pred_r58"})
    r59 = r59.rename(columns={"power_pred_final": "pred_r59"})
    r60 = r60.rename(columns={"power_pred_final": "pred_r60"})

    # Merge
    base_cols = ["time", "site_id", "hour", "power_mw", "capacity_mw"]
    m58 = r58[base_cols + ["pred_r58"]].copy()
    m59 = r59[base_cols + ["pred_r59"]].copy()
    m60 = r60[base_cols + ["pred_r60"]].copy()

    merged = m58.merge(m59[base_cols + ["pred_r59"]], on=["time", "site_id"], how="inner")
    merged = merged.merge(m60[base_cols + ["pred_r60"]], on=["time", "site_id"], how="inner")

    print(f"Round58: {len(r58)} rows | Round59: {len(r59)} rows | Round60: {len(r60)} rows")
    print(f"Merged: {len(merged)} rows")

    df_all = merged[merged["hour"].between(6, 19)].copy()
    df_10_14 = df_all[df_all["hour"].between(10, 14)].copy()

    pred_cols = {
        "Round58": "pred_r58",
        "Round59": "pred_r59",
        "Round60": "pred_r60",
    }

    # ── Summary ─────────────────────────────────────────────────────
    print("\n[1] 总体指标对比 (6-19h test)")
    summary_rows = []
    for period, df_sub in [("6-19", df_all), ("10-14", df_10_14)]:
        row = {"period": period}
        for name, col in pred_cols.items():
            row[f"sm_nrmse_{name}"] = round(site_mean_nrmse(df_sub, col), 4)
            row[f"city_nrmse_{name}"] = round(city_nrmse(df_sub, col), 4)
            row[f"bias_{name}"] = round(bias_pct(df_sub, col), 4)
            row[f"mae_{name}"] = round(mae_per_site(df_sub, col), 4)
        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(OUT / "metrics/round60_compare_summary.csv", index=False, encoding="utf-8-sig")

    print(f"\n{'Metric':<25} {'Round58':>10} {'Round59':>10} {'Round60':>10}")
    print("-" * 58)
    for _, row in summary_df.iterrows():
        p = row["period"]
        for metric in ["sm_nrmse", "city_nrmse", "bias", "mae"]:
            b = row.get(f"{metric}_Round58", np.nan)
            n = row.get(f"{metric}_Round59", np.nan)
            x = row.get(f"{metric}_Round60", np.nan)
            b_str = f"{b:.4f}" if not np.isnan(b) else "N/A"
            n_str = f"{n:.4f}" if not np.isnan(n) else "N/A"
            x_str = f"{x:.4f}" if not np.isnan(x) else "N/A"
            print(f"  {metric}_{p:<20} {b_str:>10} {n_str:>10} {x_str:>10}")

    # Delta summary
    print(f"\n{'Metric':<25} {'R59-R58':>10} {'R60-R58':>10}")
    print("-" * 48)
    for _, row in summary_df.iterrows():
        p = row["period"]
        for metric in ["sm_nrmse", "city_nrmse", "bias"]:
            b = row.get(f"{metric}_Round58", np.nan)
            n = row.get(f"{metric}_Round59", np.nan)
            x = row.get(f"{metric}_Round60", np.nan)
            d59 = n - b if not (np.isnan(n) or np.isnan(b)) else np.nan
            d60 = x - b if not (np.isnan(x) or np.isnan(b)) else np.nan
            d59_str = f"{d59:+.4f}" if not np.isnan(d59) else "N/A"
            d60_str = f"{d60:+.4f}" if not np.isnan(d60) else "N/A"
            print(f"  {metric}_{p:<20} {d59_str:>10} {d60_str:>10}")

    # ── Hourly ──────────────────────────────────────────────────────
    print("\n[2] 逐小时对比")
    hourly_rows = []
    for h in sorted(merged["hour"].unique()):
        hdf = merged[merged["hour"] == h]
        row = {"hour": int(h)}
        for name, col in pred_cols.items():
            row[f"sm_nrmse_{name}"] = round(site_mean_nrmse(hdf, col), 4)
            row[f"city_nrmse_{name}"] = round(city_nrmse(hdf, col), 4)
            row[f"bias_{name}"] = round(bias_pct(hdf, col), 4)
        hourly_rows.append(row)

    hourly_df = pd.DataFrame(hourly_rows)
    hourly_df.to_csv(OUT / "metrics/round60_compare_hourly.csv", index=False, encoding="utf-8-sig")

    hours_of_interest = [6, 7, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    print(f"\n{'Hour':>5} | {'sm_nrmse_R58':>12} {'sm_nrmse_R59':>12} {'sm_nrmse_R60':>12} | "
          f"{'city_R58':>8} {'city_R59':>8} {'city_R60':>8} | "
          f"{'bias_R58':>8} {'bias_R59':>8} {'bias_R60':>8}")
    print("-" * 110)
    for _, row in hourly_df[hourly_df["hour"].isin(hours_of_interest)].iterrows():
        print(
            f"{int(row['hour']):>5} | "
            f"{row['sm_nrmse_Round58']:>12.4f} {row['sm_nrmse_Round59']:>12.4f} {row['sm_nrmse_Round60']:>12.4f} | "
            f"{row['city_nrmse_Round58']:>8.4f} {row['city_nrmse_Round59']:>8.4f} {row['city_nrmse_Round60']:>8.4f} | "
            f"{row['bias_Round58']:>8.2f} {row['bias_Round59']:>8.2f} {row['bias_Round60']:>8.2f}"
        )

    # ── Site ──────────────────────────────────────────────────────
    print("\n[3] 站点对比 (6-19h)")
    site_rows = []
    for sid, sdf in merged[merged["hour"].between(6, 19)].groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        row = {
            "site_id": str(sid),
            "capacity_mw": round(cap, 4),
        }
        for name, col in pred_cols.items():
            row[f"sm_nrmse_{name}"] = round(rmse(sdf["power_mw"].values, sdf[col].values) / cap * 100, 4)
            row[f"bias_{name}"] = round(bias_pct(sdf, col), 4) if not np.isnan(bias_pct(sdf, col)) else np.nan
        site_rows.append(row)

    site_df = pd.DataFrame(site_rows)
    site_df.to_csv(OUT / "metrics/round60_compare_site.csv", index=False, encoding="utf-8-sig")

    sites_of_interest = ["S012", "S019", "S023", "S032", "S053", "S071", "S115", "S116",
                          "S022", "S050", "S004", "S017"]
    print(f"\n{'Site':>6} | {'cap_MW':>8} | {'sm_R58':>8} {'sm_R59':>8} {'sm_R60':>8} | "
          f"{'delta_R59':>8} {'delta_R60':>8} | {'bias_R58':>8} {'bias_R60':>8}")
    print("-" * 100)
    for _, row in site_df[site_df["site_id"].isin(sites_of_interest)].iterrows():
        d59 = row["sm_nrmse_Round59"] - row["sm_nrmse_Round58"]
        d60 = row["sm_nrmse_Round60"] - row["sm_nrmse_Round58"]
        print(
            f"{row['site_id']:>6} | {row['capacity_mw']:>8.2f} | "
            f"{row['sm_nrmse_Round58']:>8.2f} {row['sm_nrmse_Round59']:>8.2f} {row['sm_nrmse_Round60']:>8.2f} | "
            f"{d59:>+8.2f} {d60:>+8.2f} | "
            f"{row['bias_Round58']:>8.2f} {row['bias_Round60']:>8.2f}"
        )

    # Degradation check
    site_df["delta_r60_vs_r58"] = site_df["sm_nrmse_Round60"] - site_df["sm_nrmse_Round58"]
    degraded = site_df[site_df["delta_r60_vs_r58"] > 1.0].sort_values("delta_r60_vs_r58", ascending=False)
    improved = site_df[site_df["delta_r60_vs_r58"] < -1.0].sort_values("delta_r60_vs_r58")
    print(f"\n[4] 变差保护 (R60 vs R58, threshold=+1.0pp)")
    print(f"  变差 > +1.0pp: {len(degraded)} 站点")
    if len(degraded) > 0:
        print(degraded[["site_id", "sm_nrmse_Round58", "sm_nrmse_Round60", "delta_r60_vs_r58"]].to_string(index=False))
    print(f"  改善 > -1.0pp: {len(improved)} 站点")
    if len(improved) > 0:
        print(improved[["site_id", "sm_nrmse_Round58", "sm_nrmse_Round60", "delta_r60_vs_r58"]].head(10).to_string(index=False))

    print(f"\n[OK] round60_compare_*.csv saved")
    return summary_df, hourly_df, site_df


if __name__ == "__main__":
    main()
