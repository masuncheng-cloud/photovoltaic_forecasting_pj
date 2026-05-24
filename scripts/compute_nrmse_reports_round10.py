#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round10：生成完整 NRMSE 报告（站点小时级 + 小时整体 + 全局整体）"""
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

FINAL_EVAL = TABLES / "distributed_predictions_final_eval.pkl"
BEST_EVAL = TABLES / "best_predictions_eval.pkl"


def _ensure_hour(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour
    return out


def _nrmse(y, p, c) -> float:
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(c, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (c > 0)
    if not m.any():
        return np.nan
    return float(np.sqrt(np.mean((y[m] - p[m]) ** 2)) / np.nanmean(c[m]) * 100.0)


def _mae(y, p) -> float:
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p)
    return float(np.mean(np.abs(y[m] - p[m]))) if m.any() else np.nan


def _rmse(y, p) -> float:
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p)
    return float(np.sqrt(np.mean((y[m] - p[m]) ** 2))) if m.any() else np.nan


def _overall_summary(df: pd.DataFrame, label: str) -> dict:
    y = pd.to_numeric(df["power_mw"], errors="coerce")
    p = pd.to_numeric(df["power_pred"], errors="coerce")
    c = pd.to_numeric(df["capacity_mw"], errors="coerce")
    actual = float(y.sum())
    pred = float(p.sum())
    return {
        "version": label,
        "rows": int(len(df)),
        "n_sites": int(df["site_id"].nunique()),
        "actual_mwh": round(actual, 4),
        "pred_mwh": round(pred, 4),
        "pred_actual_ratio": round(pred / actual, 6) if actual > 0 else np.nan,
        "bias_pct": round((pred / actual - 1.0) * 100.0, 4) if actual > 0 else np.nan,
        "mae_mw": round(_mae(y, p), 6),
        "rmse_mw": round(_rmse(y, p), 6),
        "overall_nrmse_pct": round(_nrmse(y, p, c), 6),
    }


def _build_reports(df: pd.DataFrame, label: str):
    site_hour_rows = []
    for (sid, h), g in df.groupby(["site_id", "hour"]):
        site_hour_rows.append({
            "version": label,
            "site_id": sid,
            "hour": int(h),
            "rows": int(len(g)),
            "capacity_mw": round(float(pd.to_numeric(g["capacity_mw"], errors="coerce").mean()), 6),
            "site_hour_nrmse_pct": round(_nrmse(g["power_mw"], g["power_pred"], g["capacity_mw"]), 6),
            "mae_mw": round(_mae(g["power_mw"], g["power_pred"]), 6),
            "rmse_mw": round(_rmse(g["power_mw"], g["power_pred"]), 6),
        })

    hour_rows = []
    for h, g in df.groupby("hour"):
        hour_rows.append({
            "version": label,
            "hour": int(h),
            "rows": int(len(g)),
            "n_sites": int(g["site_id"].nunique()),
            "hour_overall_nrmse_pct": round(_nrmse(g["power_mw"], g["power_pred"], g["capacity_mw"]), 6),
            "hour_mae_mw": round(_mae(g["power_mw"], g["power_pred"]), 6),
            "hour_rmse_mw": round(_rmse(g["power_mw"], g["power_pred"]), 6),
        })

    return pd.DataFrame(site_hour_rows), pd.DataFrame(hour_rows), _overall_summary(df, label)


def main():
    if not FINAL_EVAL.exists():
        raise FileNotFoundError(FINAL_EVAL)

    final = _ensure_hour(safe_pickle_load(FINAL_EVAL))

    all_sh, all_hh, all_ss = [], [], []

    sh, hh, ss = _build_reports(final, "final")
    all_sh.append(sh)
    all_hh.append(hh)
    all_ss.append(ss)

    if BEST_EVAL.exists():
        best = _ensure_hour(safe_pickle_load(BEST_EVAL))
        sh, hh, ss = _build_reports(best, "best")
        all_sh.append(sh)
        all_hh.append(hh)
        all_ss.append(ss)

    site_hour = pd.concat(all_sh, ignore_index=True)
    hour_overall = pd.concat(all_hh, ignore_index=True)
    summary = pd.DataFrame(all_ss)

    site_hour.to_csv(METRICS / "round10_site_hour_nrmse.csv", index=False, encoding="utf-8-sig")
    hour_overall.to_csv(METRICS / "round10_hour_overall_nrmse.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(METRICS / "round10_overall_nrmse_summary.csv", index=False, encoding="utf-8-sig")

    if {"final", "best"}.issubset(set(summary["version"])):
        f_row = summary[summary["version"] == "final"].iloc[0]
        b_row = summary[summary["version"] == "best"].iloc[0]
        cmp_rows = []
        for metric in ["overall_nrmse_pct", "mae_mw", "rmse_mw", "bias_pct"]:
            if metric in f_row.index and metric in b_row.index:
                cmp_rows.append({
                    "metric": metric,
                    "best": b_row[metric],
                    "final": f_row[metric],
                    "delta_final_minus_best": round(float(f_row[metric]) - float(b_row[metric]), 6),
                })
        if cmp_rows:
            pd.DataFrame(cmp_rows).to_csv(
                METRICS / "round10_final_vs_best_nrmse.csv", index=False, encoding="utf-8-sig"
            )

    print("[OK] Round10 NRMSE reports generated.")
    print(summary.to_string(index=False))
    print()
    print(f"Files written:")
    print(f"  {METRICS / 'round10_site_hour_nrmse.csv'}")
    print(f"  {METRICS / 'round10_hour_overall_nrmse.csv'}")
    print(f"  {METRICS / 'round10_overall_nrmse_summary.csv'}")


if __name__ == "__main__":
    main()
