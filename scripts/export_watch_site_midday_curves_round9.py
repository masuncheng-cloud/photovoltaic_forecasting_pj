#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

WATCH = ["S012", "S055", "S050", "S032", "S019", "S053", "S116"]
MIDDAY = [10, 11, 12, 13, 14]


def main():
    final_path = TABLES / "distributed_predictions_final_eval.pkl"
    df = safe_pickle_load(final_path)
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    if "date" not in df.columns:
        df["date"] = df["time"].dt.date

    sub = df[df["site_id"].isin(WATCH) & df["hour"].isin(MIDDAY)].copy()
    keep_cols = [c for c in ["time", "date", "hour", "site_id", "site_name", "capacity_mw", "power_mw", "power_pred", "pred_baseline"] if c in sub.columns]
    sub[keep_cols].to_csv(METRICS / "round9_watch_site_midday_true_pred_detail.csv", index=False, encoding="utf-8-sig")

    avg = (
        sub.groupby(["site_id", "hour"], as_index=False)
        .agg(
            capacity_mw=("capacity_mw", "mean"),
            actual_mean_mw=("power_mw", "mean"),
            pred_mean_mw=("power_pred", "mean"),
            actual_sum_mwh=("power_mw", "sum"),
            pred_sum_mwh=("power_pred", "sum"),
            rows=("power_mw", "size"),
        )
    )
    avg["pred_actual_ratio"] = avg["pred_sum_mwh"] / avg["actual_sum_mwh"]
    avg["bias_pct"] = (avg["pred_mean_mw"] - avg["actual_mean_mw"]) / avg["capacity_mw"] * 100
    avg.to_csv(METRICS / "round9_watch_site_midday_hourly_mean_curve.csv", index=False, encoding="utf-8-sig")

    daily = (
        sub.groupby(["site_id", "date"], as_index=False)
        .agg(
            actual_midday_sum=("power_mw", "sum"),
            pred_midday_sum=("power_pred", "sum"),
            rows=("power_mw", "size"),
        )
    )
    daily["pred_actual_ratio"] = daily["pred_midday_sum"] / daily["actual_midday_sum"]
    daily.to_csv(METRICS / "round9_watch_site_midday_daily_ratio.csv", index=False, encoding="utf-8-sig")

    print("=" * 80)
    print("逐站点 10-14 点小时均值曲线:")
    print("=" * 80)
    for sid in WATCH:
        site_avg = avg[avg["site_id"] == sid].sort_values("hour")
        if len(site_avg) == 0:
            print(f"\n  {sid}: 无数据")
            continue
        print(f"\n  {sid} (容量={site_avg['capacity_mw'].iloc[0]:.3f} MW):")
        for _, row in site_avg.iterrows():
            bias_str = f"bias={row['bias_pct']:+.1f}%" if pd.notna(row['bias_pct']) else ""
            print(f"    h={int(row['hour']):02d}: actual={row['actual_mean_mw']:.3f} pred={row['pred_mean_mw']:.3f} "
                  f"ratio={row['pred_actual_ratio']:.3f} {bias_str}")

    print()
    print("[OK] 导出完成:")
    for fname in [
        "round9_watch_site_midday_true_pred_detail.csv",
        "round9_watch_site_midday_hourly_mean_curve.csv",
        "round9_watch_site_midday_daily_ratio.csv",
    ]:
        print(f"  {METRICS / fname}")


if __name__ == "__main__":
    main()
