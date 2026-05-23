#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断 10-14 点最差站点/小时。
输出：
  midday_worst_site_hours_final.csv   — 所有站点小时
  midday_worst_site_hours_top30.csv   — Top30 最差
"""
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load
from pv_forecasting.core.evaluation import build_eval_frame

TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)

MIDDAY_HOURS = [10, 11, 12, 13, 14]
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}


def site_hour_metrics(df: pd.DataFrame, pred_col: str = "power_pred") -> pd.DataFrame:
    rows = []
    for (sid, h), g in df.groupby(["site_id", "hour"]):
        y = pd.to_numeric(g["power_mw"], errors="coerce").to_numpy(dtype=float)
        p = pd.to_numeric(g[pred_col], errors="coerce").to_numpy(dtype=float)
        c = pd.to_numeric(g["capacity_mw"], errors="coerce").to_numpy(dtype=float)
        m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (c > 0)
        if not m.any():
            continue
        rmse = float(np.sqrt(np.mean((y[m] - p[m]) ** 2)))
        mae = float(np.mean(np.abs(y[m] - p[m])))
        cap = float(np.nanmean(c[m]))
        actual = float(np.sum(y[m]))
        pred = float(np.sum(p[m]))
        rows.append({
            "site_id": sid,
            "hour": int(h),
            "rows": int(m.sum()),
            "capacity_mw": round(cap, 4),
            "actual_sum_mwh": round(actual, 4),
            "pred_sum_mwh": round(pred, 4),
            "pred_actual_ratio": round(pred / actual, 4) if actual > 0 else np.nan,
            "mae_mw": round(mae, 4),
            "rmse_mw": round(rmse, 4),
            "site_nrmse_pct": round(rmse / cap * 100.0, 4) if cap > 0 else np.nan,
            "bias_mwh": round(pred - actual, 4),
            "bias_pct": round((pred - actual) / actual * 100.0, 4) if actual > 0 else np.nan,
        })
    return pd.DataFrame(rows)


def main():
    final_path = TABLES_DIR / "distributed_predictions_final_eval.pkl"
    if not final_path.exists():
        raise FileNotFoundError(final_path)

    df = safe_pickle_load(final_path)
    eval_df = build_eval_frame(
        df,
        split="test",
        hours=tuple(range(6, 20)),
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=53,
    )
    eval_df = eval_df[eval_df["hour"].isin(MIDDAY_HOURS)].copy()

    out = site_hour_metrics(eval_df).sort_values(
        ["site_nrmse_pct", "rows"],
        ascending=[False, False],
    )
    out.to_csv(METRICS_DIR / "midday_worst_site_hours_final.csv", index=False, encoding="utf-8-sig")

    top = out.head(30)
    top.to_csv(METRICS_DIR / "midday_worst_site_hours_top30.csv", index=False, encoding="utf-8-sig")

    print("10-14 点最差站点小时 Top 30:")
    print(top.to_string(index=False))
    print(f"\n总计: {len(out)} 个站点小时对")
    print(f"已保存: midday_worst_site_hours_final.csv ({len(out)} 行)")
    print(f"已保存: midday_worst_site_hours_top30.csv ({len(top)} 行)")


if __name__ == "__main__":
    main()
