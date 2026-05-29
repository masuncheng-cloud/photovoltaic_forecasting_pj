#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load
from pv_forecasting.core.evaluation import hourly_nrmse_metrics

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

MIDDAY = [10, 11, 12, 13, 14]


def site_hour_nrmse(g: pd.DataFrame) -> float:
    y = pd.to_numeric(g["power_mw"], errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(g["power_pred"], errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(g["capacity_mw"], errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (c > 0)
    if not m.any():
        return np.nan
    return float(np.sqrt(np.mean((y[m] - p[m]) ** 2)) / np.nanmean(c[m]) * 100.0)


def main():
    final_path = TABLES / "distributed_predictions_final_eval.pkl"
    if not final_path.exists():
        raise FileNotFoundError(final_path)

    df = safe_pickle_load(final_path)
    df = df[df["hour"].isin(MIDDAY)].copy()

    base = hourly_nrmse_metrics(df)
    base_mid = base[base["hour"].isin(MIDDAY)][["hour", "site_nrmse_mean_pct", "city_nrmse_pct"]].copy()
    base_avg = float(base_mid["site_nrmse_mean_pct"].mean())

    rows = []
    for sid in sorted(df["site_id"].unique()):
        sub = df[df["site_id"] != sid].copy()
        h = hourly_nrmse_metrics(sub)
        h = h[h["hour"].isin(MIDDAY)]
        avg_after_drop = float(h["site_nrmse_mean_pct"].mean())
        rows.append({
            "site_id": sid,
            "base_midday_avg_nrmse_pct": round(base_avg, 4),
            "avg_nrmse_after_drop_site_pct": round(avg_after_drop, 4),
            "drop_contribution_pp": round(base_avg - avg_after_drop, 4),
        })

    contrib = pd.DataFrame(rows).sort_values("drop_contribution_pp", ascending=False)
    contrib.to_csv(METRICS / "round9_midday_site_drop_contribution.csv", index=False, encoding="utf-8-sig")

    detail_rows = []
    for (sid, h), g in df.groupby(["site_id", "hour"]):
        y = pd.to_numeric(g["power_mw"], errors="coerce")
        p = pd.to_numeric(g["power_pred"], errors="coerce")
        actual = float(y.sum())
        pred = float(p.sum())
        detail_rows.append({
            "site_id": sid,
            "hour": int(h),
            "rows": len(g),
            "capacity_mw": round(float(pd.to_numeric(g["capacity_mw"], errors="coerce").mean()), 4),
            "site_hour_nrmse_pct": round(site_hour_nrmse(g), 4),
            "actual_sum_mwh": round(actual, 4),
            "pred_sum_mwh": round(pred, 4),
            "pred_actual_ratio": round(pred / actual, 4) if actual > 0 else np.nan,
        })

    detail = pd.DataFrame(detail_rows).sort_values("site_hour_nrmse_pct", ascending=False)
    detail.to_csv(METRICS / "round9_midday_site_hour_nrmse_detail.csv", index=False, encoding="utf-8-sig")

    print("=" * 70)
    print("10-14 点当前逐小时 NRMSE:")
    print(base_mid.to_string(index=False))
    print()
    print(f"10-14 点当前平均站点 NRMSE: {base_avg:.4f}%")
    print()
    print("=" * 70)
    print("站点贡献 Top 20 (剔除后 NRMSE 下降越多，贡献越大):")
    print(contrib.head(20).to_string(index=False))
    print()
    print("=" * 70)
    print("站点小时 NRMSE Top 30:")
    print(detail.head(30).to_string(index=False))
    print()
    print(f"[OK] 贡献表 -> {METRICS / 'round9_midday_site_drop_contribution.csv'}")
    print(f"[OK] 明细表 -> {METRICS / 'round9_midday_site_hour_nrmse_detail.csv'}")


if __name__ == "__main__":
    main()
