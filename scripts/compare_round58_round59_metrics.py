#!/usr/bin/env python3
"""
compare_round58_round59_metrics.py
=================================
对比 Round58 baseline 和 Round59 在 test 集上的预测效果。

baseline: output/pv_pipeline/baselines/round58/distributed_predictions_final_eval.pkl
round59:  output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl

输出：
  output/pv_pipeline/metrics/round59_compare_summary.csv
  output/pv_pipeline/metrics/round59_compare_hourly.csv
  output/pv_pipeline/metrics/round59_compare_site.csv
  docs/Round59_预测精度提升执行报告.md
"""

from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"


def _rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    if len(a) == 0:
        return np.nan
    return float(np.sqrt(np.mean((p - a) ** 2)))


def _mae(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    if len(a) == 0:
        return np.nan
    return float(np.mean(np.abs(p - a)))


def site_mean_nrmse(df, pred_col):
    """Mean of per-site NRMSE, each normalized by its own capacity."""
    rows = []
    for sid, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        a = sdf["power_mw"].values
        p = sdf[pred_col].values
        r = _rmse(a, p) / cap * 100
        rows.append(r)
    return float(np.mean(rows)) if rows else np.nan


def city_nrmse(df, pred_col):
    """
    Per-hour city NRMSE averaged.
    For each hour: RMSE(hour_actual, hour_pred) / hour_active_capacity * 100
    Then average across hours.
    This matches the formula used by hourly_nrmse_consistent.csv.
    """
    vals = []
    for h, hdf in df.groupby("hour"):
        cap_h = float(hdf.groupby("site_id")["capacity_mw"].first().sum())
        if cap_h <= 0:
            continue
        r = _rmse(hdf["power_mw"].values, hdf[pred_col].values) / cap_h * 100
        vals.append(r)
    return float(np.nanmean(vals)) if vals else np.nan


def site_mean_mae(df, pred_col):
    rows = []
    for sid, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        a = sdf["power_mw"].values
        p = sdf[pred_col].values
        rows.append(_mae(a, p))
    return float(np.mean(rows)) if rows else np.nan


def bias_pct(df, pred_col):
    a_sum = float(df["power_mw"].sum())
    p_sum = float(df[pred_col].sum())
    if a_sum <= 0:
        return np.nan
    return (p_sum - a_sum) / a_sum * 100


def main():
    print("=" * 60)
    print("Round58 vs Round59 对比报告")
    print("=" * 60)

    # Load data
    base_eval = pd.read_pickle(
        OUT / "baselines/round58/distributed_predictions_final_eval.pkl"
    )
    base_eval["time"] = pd.to_datetime(base_eval["time"])
    base_eval["hour"] = base_eval["time"].dt.hour

    r59_eval = pd.read_pickle(
        OUT / "predictions/distributed_predictions_final_eval.pkl"
    )
    r59_eval["time"] = pd.to_datetime(r59_eval["time"])
    if "hour" not in r59_eval.columns:
        r59_eval["hour"] = r59_eval["time"].dt.hour

    print(f"Baseline eval: {len(base_eval)} rows, {base_eval['site_id'].nunique()} sites")
    print(f"Round59 eval: {len(r59_eval)} rows, {r59_eval['site_id'].nunique()} sites")

    # Merge for aligned comparison
    base_eval = base_eval.rename(columns={"power_pred_final": "pred_base"})
    r59_eval = r59_eval.rename(columns={"power_pred_final": "pred_r59"})
    merged = base_eval[["time", "site_id", "hour", "power_mw", "capacity_mw", "pred_base"]].merge(
        r59_eval[["time", "site_id", "pred_r59"]],
        on=["time", "site_id"],
        how="inner"
    )
    print(f"Merged eval: {len(merged)} rows")

    # ── 1. Overall summary ────────────────────────────────────────────
    print("\n[1] 总体指标对比 (6-19h test)")

    df_all = merged[merged["hour"].between(6, 19)].copy()
    df_10_14 = df_all[df_all["hour"].between(10, 14)].copy()

    summary = {}

    # 6-19 overall
    for label, df_subset in [("6-19", df_all), ("10-14", df_10_14)]:
        cap = float(df_subset.groupby("site_id")["capacity_mw"].first().sum())

        sm_nrmse_base = site_mean_nrmse(df_subset, "pred_base")
        sm_nrmse_r59 = site_mean_nrmse(df_subset, "pred_r59")
        c_nrmse_base = city_nrmse(df_subset, "pred_base")
        c_nrmse_r59 = city_nrmse(df_subset, "pred_r59")
        mae_base = site_mean_mae(df_subset, "pred_base")
        mae_r59 = site_mean_mae(df_subset, "pred_r59")
        rmse_base = _rmse(df_subset["power_mw"].values, df_subset["pred_base"].values)
        rmse_r59 = _rmse(df_subset["power_mw"].values, df_subset["pred_r59"].values)
        bias_base = bias_pct(df_subset, "pred_base")
        bias_r59 = bias_pct(df_subset, "pred_r59")

        summary[label] = {
            "period": label,
            "site_mean_nrmse_percent_base": round(sm_nrmse_base, 4),
            "site_mean_nrmse_percent_r59": round(sm_nrmse_r59, 4),
            "site_mean_nrmse_delta": round(sm_nrmse_r59 - sm_nrmse_base, 4),
            "city_nrmse_percent_base": round(c_nrmse_base, 4),
            "city_nrmse_percent_r59": round(c_nrmse_r59, 4),
            "city_nrmse_delta": round(c_nrmse_r59 - c_nrmse_base, 4),
            "mae_base": round(mae_base, 4),
            "mae_r59": round(mae_r59, 4),
            "mae_delta": round(mae_r59 - mae_base, 4),
            "rmse_base": round(rmse_base, 4),
            "rmse_r59": round(rmse_r59, 4),
            "rmse_delta": round(rmse_r59 - rmse_base, 4),
            "bias_base": round(bias_base, 4),
            "bias_r59": round(bias_r59, 4),
            "bias_delta": round(bias_r59 - bias_base, 4),
        }

    summary_df = pd.DataFrame(list(summary.values()))
    summary_df.to_csv(OUT / "metrics/round59_compare_summary.csv", index=False, encoding="utf-8-sig")
    print(summary_df.to_string(index=False))

    # ── 2. Hourly comparison ──────────────────────────────────────────
    print("\n[2] 逐小时对比 (test)")

    hourly_rows = []
    for hour in sorted(merged["hour"].unique()):
        hdf = merged[merged["hour"] == hour].copy()
        cap_h = float(hdf.groupby("site_id")["capacity_mw"].first().sum())

        sm_nrmse_b = site_mean_nrmse(hdf, "pred_base")
        sm_nrmse_59 = site_mean_nrmse(hdf, "pred_r59")
        c_nrmse_b = city_nrmse(hdf, "pred_base")
        c_nrmse_59 = city_nrmse(hdf, "pred_r59")
        bias_b = bias_pct(hdf, "pred_base")
        bias_59 = bias_pct(hdf, "pred_r59")

        hourly_rows.append({
            "hour": int(hour),
            "sm_nrmse_base": round(sm_nrmse_b, 4),
            "sm_nrmse_r59": round(sm_nrmse_59, 4),
            "sm_nrmse_delta": round(sm_nrmse_59 - sm_nrmse_b, 4),
            "c_nrmse_base": round(c_nrmse_b, 4),
            "c_nrmse_r59": round(c_nrmse_59, 4),
            "c_nrmse_delta": round(c_nrmse_59 - c_nrmse_b, 4),
            "bias_base": round(bias_b, 4),
            "bias_r59": round(bias_59, 4),
            "bias_delta": round(bias_59 - bias_b, 4),
        })

    hourly_df = pd.DataFrame(hourly_rows)
    hourly_df.to_csv(OUT / "metrics/round59_compare_hourly.csv", index=False, encoding="utf-8-sig")

    # Highlight hours of interest
    hours_of_interest = [6, 7, 10, 11, 12, 13, 14, 17, 18, 19]
    print("\n重点小时:")
    print(f"{'Hour':>5} {'sm_nrmse_base':>14} {'sm_nrmse_r59':>14} {'delta':>8} {'c_nrmse_base':>14} {'c_nrmse_r59':>14} {'delta':>8} {'bias_base':>10} {'bias_r59':>10} {'delta':>8}")
    for _, row in hourly_df[hourly_df["hour"].isin(hours_of_interest)].iterrows():
        print(
            f"{int(row['hour']):>5} "
            f"{row['sm_nrmse_base']:>14.4f} {row['sm_nrmse_r59']:>14.4f} {row['sm_nrmse_delta']:>+8.4f} "
            f"{row['c_nrmse_base']:>14.4f} {row['c_nrmse_r59']:>14.4f} {row['c_nrmse_delta']:>+8.4f} "
            f"{row['bias_base']:>10.2f} {row['bias_r59']:>10.2f} {row['bias_delta']:>+8.2f}"
        )

    # ── 3. Site comparison ────────────────────────────────────────────
    print("\n[3] 站点对比 (6-19h test)")

    site_rows = []
    for sid, sdf in merged[merged["hour"].between(6, 19)].groupby("site_id"):
        cap_s = float(sdf["capacity_mw"].iloc[0])
        if cap_s <= 0:
            continue
        a = sdf["power_mw"].values
        p_b = sdf["pred_base"].values
        p_59 = sdf["pred_r59"].values

        sm_nrmse_b = _rmse(a, p_b) / cap_s * 100
        sm_nrmse_59 = _rmse(a, p_59) / cap_s * 100
        bias_b = bias_pct(sdf, "pred_base")
        bias_59 = bias_pct(sdf, "pred_r59")

        site_rows.append({
            "site_id": str(sid),
            "capacity_mw": round(cap_s, 4),
            "sm_nrmse_base": round(sm_nrmse_b, 4),
            "sm_nrmse_r59": round(sm_nrmse_59, 4),
            "sm_nrmse_delta": round(sm_nrmse_59 - sm_nrmse_b, 4),
            "bias_base": round(bias_b, 4) if not np.isnan(bias_b) else np.nan,
            "bias_r59": round(bias_59, 4) if not np.isnan(bias_59) else np.nan,
            "bias_delta": round(bias_59 - bias_b, 4) if not (np.isnan(bias_b) or np.isnan(bias_59)) else np.nan,
        })

    site_df = pd.DataFrame(site_rows)
    site_df.to_csv(OUT / "metrics/round59_compare_site.csv", index=False, encoding="utf-8-sig")

    # Highlight sites of interest
    sites_of_interest = ["S012", "S019", "S023", "S032", "S053", "S071", "S115", "S116"]
    print(f"\n重点站点:")
    print(f"{'Site':>6} {'cap_MW':>8} {'sm_nrmse_base':>14} {'sm_nrmse_r59':>14} {'delta':>8} {'bias_base':>10} {'bias_r59':>10} {'delta':>8}")
    for _, row in site_df[site_df["site_id"].isin(sites_of_interest)].iterrows():
        print(
            f"{row['site_id']:>6} "
            f"{row['capacity_mw']:>8.4f} "
            f"{row['sm_nrmse_base']:>14.4f} {row['sm_nrmse_r59']:>14.4f} {row['sm_nrmse_delta']:>+8.4f} "
            f"{row['bias_base']:>10.2f} {row['bias_r59']:>10.2f} {row['bias_delta']:>+8.2f}"
        )

    # ── 4. Degradation protection ────────────────────────────────────
    print("\n[4] 变差保护检查 (阈值: site NRMSE +1.0pp)")

    degraded = site_df[site_df["sm_nrmse_delta"] > 1.0].sort_values("sm_nrmse_delta", ascending=False)
    print(f"变差超过 1.0pp 的站点: {len(degraded)} 个")
    if len(degraded) > 0:
        print(degraded[["site_id", "sm_nrmse_base", "sm_nrmse_r59", "sm_nrmse_delta"]].to_string(index=False))

    improved = site_df[site_df["sm_nrmse_delta"] < -1.0].sort_values("sm_nrmse_delta")
    print(f"改善超过 1.0pp 的站点: {len(improved)} 个")
    if len(improved) > 0:
        print(improved[["site_id", "sm_nrmse_base", "sm_nrmse_r59", "sm_nrmse_delta"]].head(10).to_string(index=False))

    # ── 5. Valid set comparison (for reference) ─────────────────────
    print("\n[5] Valid 集选择回顾")
    sel_df = pd.read_csv(OUT / "calibration/round59_model_selection_valid.csv")
    print(sel_df.to_string(index=False))

    # ── Save summary data for report ─────────────────────────────────
    return summary_df, hourly_df, site_df, degraded


if __name__ == "__main__":
    summary_df, hourly_df, site_df, degraded = main()
    print("\n[OK] 对比报告 CSVs 已保存")
