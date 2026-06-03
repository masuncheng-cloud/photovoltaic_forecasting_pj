#!/usr/bin/env python3
"""
recheck_round59_compare_metrics.py
==================================
独立复核 Round59 对比指标，使用 Round58 确认后的公式口径。

核心公式（来自 Round58）：
- site_mean_nrmse: 每个站点 rmse/capacity，取平均
- city_nrmse: 逐小时 rmse/hour_cap，再平均（hourly_nrmse_consistent.csv 的口径）
- bias_pct: (pred_sum - actual_sum) / actual_sum * 100

对比：
- Round58 baseline
- Round59 current (baseline eval pkl vs current eval pkl)

输出：
  output/pv_pipeline/validation/round60_recheck_round59_compare.csv
  output/pv_pipeline/validation/round60_recheck_round59_hourly.csv
  output/pv_pipeline/validation/round60_recheck_round59_site.csv
  output/pv_pipeline/validation/round60_recheck_round59_report.md
"""

from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
VALIDATION = OUT / "validation"
VALIDATION.mkdir(parents=True, exist_ok=True)


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    if len(a) == 0:
        return np.nan
    return float(np.sqrt(np.mean((p - a) ** 2)))


def site_mean_nrmse(df, pred_col):
    """Mean of per-site NRMSE, each normalized by its own capacity."""
    vals = []
    for sid, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].dropna().iloc[0])
        if cap > 0:
            r = rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100
            vals.append(r)
    return float(np.nanmean(vals)) if vals else np.nan


def city_nrmse_per_hour_avg(df, pred_col):
    """
    Per-hour city NRMSE averaged.
    For each hour: RMSE(per-hour actuals, per-hour preds) / per_hour_active_capacity * 100
    Then average across hours.
    This is the formula used by hourly_nrmse_consistent.csv.
    """
    vals = []
    for h, hdf in df.groupby("hour"):
        # Capacity sum of active sites for this hour (unique per site)
        cap_h = float(hdf.groupby("site_id")["capacity_mw"].first().sum())
        if cap_h <= 0:
            continue
        r = rmse(hdf["power_mw"].values, hdf[pred_col].values) / cap_h * 100
        vals.append(r)
    return float(np.nanmean(vals)) if vals else np.nan


def city_nrmse_overall(df, pred_col):
    """Overall city NRMSE: RMSE over all rows / total city capacity."""
    cap_total = float(df.groupby("site_id")["capacity_mw"].first().sum())
    if cap_total <= 0:
        return np.nan
    a = df["power_mw"].values
    p = df[pred_col].values
    return rmse(a, p) / cap_total * 100


def bias_pct(df, pred_col):
    a = float(df["power_mw"].sum())
    p = float(df[pred_col].sum())
    if abs(a) < 1e-12:
        return np.nan
    return (p - a) / a * 100


def mae_per_site(df, pred_col):
    """Mean of per-site MAE."""
    vals = []
    for sid, sdf in df.groupby("site_id"):
        a = sdf["power_mw"].values
        p = sdf[pred_col].values
        vals.append(float(np.mean(np.abs(p - a))))
    return float(np.nanmean(vals)) if vals else np.nan


def load_and_prep(path):
    df = pd.read_pickle(path)
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    return df


def main():
    print("=" * 60)
    print("Round60 独立复核 Round59 对比口径")
    print("=" * 60)

    # Load eval pkls
    r58_path = OUT / "baselines/round58/distributed_predictions_final_eval.pkl"
    r59_path = OUT / "baselines/round59/distributed_predictions_final_eval.pkl"
    current_path = OUT / "predictions/distributed_predictions_final_eval.pkl"

    r58 = load_and_prep(r58_path)
    r59 = load_and_prep(r59_path)
    current = load_and_prep(current_path)

    print(f"Round58 eval: {len(r58)} rows, {r58['site_id'].nunique()} sites")
    print(f"Round59 backup eval: {len(r59)} rows")
    print(f"Current eval: {len(current)} rows")

    # Filter 6-19h
    r58_6_19 = r58[r58["hour"].between(6, 19)].copy()
    r59_6_19 = r59[r59["hour"].between(6, 19)].copy()
    current_6_19 = current[current["hour"].between(6, 19)].copy()
    r58_10_14 = r58_6_19[r58_6_19["hour"].between(10, 14)].copy()
    r59_10_14 = r59_6_19[r59_6_19["hour"].between(10, 14)].copy()
    current_10_14 = current_6_19[current_6_19["hour"].between(10, 14)].copy()

    # ── Summary comparison ────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("SUMMARY: 6-19h test set (using Round58 confirmed formula)")
    print("=" * 80)

    # The two eval pkls should be the same (Round59 backed up to round59/)
    # But power_pred_final may differ
    pred_r58 = "power_pred_final"
    pred_r59 = "power_pred_final"

    # Use Round58 eval pkl as reference, compare power_pred_final column
    # Actually: Round58 and Round59 have different power_pred_final values
    # Round58 has original model output, Round59 has site-calibrated output
    # We compare: r58's pred vs r59's pred, against same actual

    # Merge on time+site to align
    merged = r58_6_19[["time", "site_id", "hour", "power_mw", "capacity_mw", "power_pred_final"]].merge(
        r59_6_19[["time", "site_id", "power_pred_final"]].rename(columns={"power_pred_final": "pred_r59"}),
        on=["time", "site_id"], how="inner"
    )
    print(f"Merged 6-19: {len(merged)} rows")

    merged_10_14 = r58_10_14[["time", "site_id", "hour", "power_mw", "capacity_mw", "power_pred_final"]].merge(
        r59_10_14[["time", "site_id", "power_pred_final"]].rename(columns={"power_pred_final": "pred_r59"}),
        on=["time", "site_id"], how="inner"
    )

    summary_rows = []

    for label, df_sub, df_sub_10_14 in [
        ("6-19", merged, merged_10_14),
    ]:
        sm_base = site_mean_nrmse(df_sub, pred_r58)
        sm_r59 = site_mean_nrmse(df_sub, "pred_r59")
        c_base = city_nrmse_per_hour_avg(df_sub, pred_r58)
        c_r59 = city_nrmse_per_hour_avg(df_sub, "pred_r59")
        c_base_all = city_nrmse_overall(df_sub, pred_r58)
        c_r59_all = city_nrmse_overall(df_sub, "pred_r59")
        mae_base = mae_per_site(df_sub, pred_r58)
        mae_r59 = mae_per_site(df_sub, "pred_r59")
        bias_base = bias_pct(df_sub, pred_r58)
        bias_r59 = bias_pct(df_sub, "pred_r59")
        bias_10_base = bias_pct(df_sub_10_14, pred_r58)
        bias_10_r59 = bias_pct(df_sub_10_14, "pred_r59")

        summary_rows.append({
            "period": label,
            "site_mean_nrmse_base": round(sm_base, 4),
            "site_mean_nrmse_r59": round(sm_r59, 4),
            "site_mean_nrmse_delta": round(sm_r59 - sm_base, 4),
            "city_nrmse_per_hour_avg_base": round(c_base, 4),
            "city_nrmse_per_hour_avg_r59": round(c_r59, 4),
            "city_nrmse_per_hour_avg_delta": round(c_r59 - c_base, 4),
            "city_nrmse_overall_base": round(c_base_all, 4),
            "city_nrmse_overall_r59": round(c_r59_all, 4),
            "city_nrmse_overall_delta": round(c_r59_all - c_base_all, 4),
            "mae_base": round(mae_base, 4),
            "mae_r59": round(mae_r59, 4),
            "mae_delta": round(mae_r59 - mae_base, 4),
            "bias_base": round(bias_base, 4),
            "bias_r59": round(bias_r59, 4),
            "bias_delta": round(bias_r59 - bias_base, 4),
            "bias_10_14_base": round(bias_10_base, 4),
            "bias_10_14_r59": round(bias_10_r59, 4),
        })

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(VALIDATION / "round60_recheck_round59_compare.csv", index=False, encoding="utf-8-sig")

    print(f"\n{'Metric':<35} {'Round58':>12} {'Round59':>12} {'Delta':>10}")
    print("-" * 72)
    for _, row in summary_df.iterrows():
        p = row["period"]
        for metric, base_col, r59_col, delta_col in [
            ("site_mean_nrmse", "site_mean_nrmse_base", "site_mean_nrmse_r59", "site_mean_nrmse_delta"),
            ("city_nrmse_per_hour_avg", "city_nrmse_per_hour_avg_base", "city_nrmse_per_hour_avg_r59", "city_nrmse_per_hour_avg_delta"),
            ("city_nrmse_overall", "city_nrmse_overall_base", "city_nrmse_overall_r59", "city_nrmse_overall_delta"),
            ("mae", "mae_base", "mae_r59", "mae_delta"),
            ("bias_6_19", "bias_base", "bias_r59", "bias_delta"),
            ("bias_10_14", "bias_10_14_base", "bias_10_14_r59", None),
        ]:
            b = row.get(base_col, np.nan)
            r = row.get(r59_col, np.nan)
            d = row.get(delta_col, np.nan) if delta_col else np.nan
            delta_str = f"{d:+.4f}" if not np.isnan(d) else "N/A"
            print(f"  {metric:<33} {b:>12.4f} {r:>12.4f} {delta_str:>10}")

    # ── Hourly comparison ─────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("HOURLY: city_nrmse_per_hour_avg")
    print("=" * 80)

    hourly_rows = []
    hours_of_interest = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    for h in hours_of_interest:
        hdf = merged[merged["hour"] == h]
        cap_h = float(hdf.groupby("site_id")["capacity_mw"].first().sum())
        c_b = rmse(hdf["power_mw"].values, hdf["power_pred_final"].values) / cap_h * 100 if cap_h > 0 else np.nan
        c_59 = rmse(hdf["power_mw"].values, hdf["pred_r59"].values) / cap_h * 100 if cap_h > 0 else np.nan
        sm_b = site_mean_nrmse(hdf, pred_r58)
        sm_59 = site_mean_nrmse(hdf, "pred_r59")
        bias_b = bias_pct(hdf, pred_r58)
        bias_59 = bias_pct(hdf, "pred_r59")
        hourly_rows.append({
            "hour": h,
            "city_nrmse_base": round(c_b, 4),
            "city_nrmse_r59": round(c_59, 4),
            "city_nrmse_delta": round(c_59 - c_b, 4),
            "site_mean_nrmse_base": round(sm_b, 4),
            "site_mean_nrmse_r59": round(sm_59, 4),
            "site_mean_nrmse_delta": round(sm_59 - sm_b, 4),
            "bias_base": round(bias_b, 4),
            "bias_r59": round(bias_59, 4),
            "bias_delta": round(bias_59 - bias_b, 4),
        })

    hourly_df = pd.DataFrame(hourly_rows)
    hourly_df.to_csv(VALIDATION / "round60_recheck_round59_hourly.csv", index=False, encoding="utf-8-sig")

    print(f"\n{'Hour':>5} {'city_nrmse_base':>16} {'city_nrmse_r59':>16} {'delta':>8} | {'sm_nrmse_base':>14} {'sm_nrmse_r59':>14} {'delta':>8} | {'bias_base':>10} {'bias_r59':>10} {'delta':>8}")
    print("-" * 120)
    for _, row in hourly_df.iterrows():
        h = int(row["hour"])
        print(
            f"{h:>5} "
            f"{row['city_nrmse_base']:>16.4f} {row['city_nrmse_r59']:>16.4f} {row['city_nrmse_delta']:>+8.4f} | "
            f"{row['site_mean_nrmse_base']:>14.4f} {row['site_mean_nrmse_r59']:>14.4f} {row['site_mean_nrmse_delta']:>+8.4f} | "
            f"{row['bias_base']:>10.2f} {row['bias_r59']:>10.2f} {row['bias_delta']:>+8.2f}"
        )

    # ── Site comparison ─────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("SITE: 6-19h site_mean_nrmse")
    print("=" * 80)

    site_rows = []
    for sid, sdf in merged.groupby("site_id"):
        cap_s = float(sdf["capacity_mw"].iloc[0])
        if cap_s <= 0:
            continue
        sm_b = rmse(sdf["power_mw"].values, sdf["power_pred_final"].values) / cap_s * 100
        sm_59 = rmse(sdf["power_mw"].values, sdf["pred_r59"].values) / cap_s * 100
        bias_b = bias_pct(sdf, pred_r58)
        bias_59 = bias_pct(sdf, "pred_r59")
        site_rows.append({
            "site_id": str(sid),
            "capacity_mw": round(cap_s, 4),
            "site_mean_nrmse_base": round(sm_b, 4),
            "site_mean_nrmse_r59": round(sm_59, 4),
            "site_mean_nrmse_delta": round(sm_59 - sm_b, 4),
            "bias_base": round(bias_b, 4) if not np.isnan(bias_b) else np.nan,
            "bias_r59": round(bias_59, 4) if not np.isnan(bias_59) else np.nan,
            "bias_delta": round(bias_59 - bias_b, 4) if not (np.isnan(bias_b) or np.isnan(bias_59)) else np.nan,
        })

    site_df = pd.DataFrame(site_rows)
    site_df.to_csv(VALIDATION / "round60_recheck_round59_site.csv", index=False, encoding="utf-8-sig")

    # Degradation check
    degraded = site_df[site_df["site_mean_nrmse_delta"] > 1.0].sort_values("site_mean_nrmse_delta", ascending=False)
    improved = site_df[site_df["site_mean_nrmse_delta"] < -1.0].sort_values("site_mean_nrmse_delta")
    print(f"\n变差 > +1.0pp: {len(degraded)} 站点")
    if len(degraded) > 0:
        print(degraded[["site_id", "site_mean_nrmse_base", "site_mean_nrmse_r59", "site_mean_nrmse_delta"]].to_string(index=False))
    print(f"\n改善 > 1.0pp: {len(improved)} 站点")
    if len(improved) > 0:
        print(improved[["site_id", "site_mean_nrmse_base", "site_mean_nrmse_r59", "site_mean_nrmse_delta"]].head(10).to_string(index=False))

    # ── Key finding ──────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("KEY FINDING")
    print("=" * 80)

    c_nrmse_58 = summary_df["city_nrmse_per_hour_avg_base"].iloc[0]
    c_nrmse_59 = summary_df["city_nrmse_per_hour_avg_r59"].iloc[0]
    c_nrmse_old_59 = 0.2398  # from round59 compare script (wrong formula)

    print(f"\nRound59 旧口径 (compare_round58_round59_metrics.py):")
    print(f"  city_nrmse_6_19 = {c_nrmse_old_59:.4f}% (使用 all-rows RMSE / 总容量)")
    print(f"\nRound58/Round60 新口径 (hourly_nrmse_consistent.csv 公式):")
    print(f"  Round58 city_nrmse_6_19 = {c_nrmse_58:.4f}% (使用 per-hour RMSE / hour_cap 平均)")
    print(f"  Round59 city_nrmse_6_19 = {c_nrmse_59:.4f}%")
    print(f"  Round59 vs Round58 Delta = {c_nrmse_59 - c_nrmse_58:+.4f}pp")
    print(f"\n结论: compare_round58_round59_metrics.py 使用了错误的 city_nrmse 公式。")
    print(f"正确公式: per-hour RMSE/capacity 再平均，而非 all-rows RMSE/capacity。")

    # ── Generate report ──────────────────────────────────────────────
    report = f"""# Round60 独立复核 Round59 对比口径报告

## 1. 复核目的

复核 `compare_round58_round59_metrics.py` 中的 city NRMSE 计算公式是否与 Round58 确认口径一致。

## 2. 口径对比

| 口径 | 方法 | Round58 city_nrmse_6_19 |
|------|------|--------------------------|
| Round59 旧脚本 | all-rows RMSE / 总容量 | {c_nrmse_old_59:.4f}% |
| Round58 确认口径 | per-hour RMSE / hour_cap 平均 | {c_nrmse_58:.4f}% |

量级差异: Round59 报告为 0.24%，实际应为 {c_nrmse_58:.2f}%（差异 16 倍）。

## 3. 复核结论

**compare_round58_round59_metrics.py 中的 city_nrmse 公式错误。**

- 旧公式: `RMSE(all_rows) / total_city_capacity`
- 正确公式: `mean( RMSE(per_hour) / per_hour_capacity )`

正确公式与 `hourly_nrmse_consistent.csv` 一致，是 Round57-58 确认的标准口径。

## 4. Round59 真实效果（使用正确公式）

| 指标 | Round58 | Round59 | Delta |
|------|---------|---------|-------|
| site_mean_nrmse_6_19 | {summary_df['site_mean_nrmse_base'].iloc[0]:.4f}% | {summary_df['site_mean_nrmse_r59'].iloc[0]:.4f}% | {summary_df['site_mean_nrmse_delta'].iloc[0]:+.4f}pp |
| city_nrmse_per_hour_avg_6_19 | {c_nrmse_58:.4f}% | {c_nrmse_59:.4f}% | {c_nrmse_59-c_nrmse_58:+.4f}pp |
| city_nrmse_overall_6_19 | {summary_df['city_nrmse_overall_base'].iloc[0]:.4f}% | {summary_df['city_nrmse_overall_r59'].iloc[0]:.4f}% | {summary_df['city_nrmse_overall_delta'].iloc[0]:+.4f}pp |
| bias_6_19 | {summary_df['bias_base'].iloc[0]:.4f}% | {summary_df['bias_r59'].iloc[0]:.4f}% | {summary_df['bias_delta'].iloc[0]:+.4f}pp |
| bias_10_14 | {summary_df['bias_10_14_base'].iloc[0]:.4f}% | {summary_df['bias_10_14_r59'].iloc[0]:.4f}% | {summary_df['bias_10_14_r59'].iloc[0]-summary_df['bias_10_14_base'].iloc[0]:+.4f}pp |

## 5. 下一步

修改 `compare_round58_round59_metrics.py`，将 city_nrmse 改为 per-hour 平均口径。
"""

    report_path = VALIDATION / "round60_recheck_round59_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n[OK] 报告 → {report_path}")

    print("\n[OK] CSVs saved:")
    print(f"  {VALIDATION / 'round60_recheck_round59_compare.csv'}")
    print(f"  {VALIDATION / 'round60_recheck_round59_hourly.csv'}")
    print(f"  {VALIDATION / 'round60_recheck_round59_site.csv'}")


if __name__ == "__main__":
    main()
