#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§1 稳健逐小时误差统计
====================
同时展示 raw MAPE、clipped MAPE、WAPE、city_total_rel_err、容量加权 MAPE。
仅在测试集上运行，不涉及参数学习。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
import sys

# pandas 3.x pickle 兼容
import functools as _functools
_pd_patched = False

def _ensure_patch():
    global _pd_patched
    if _pd_patched:
        return
    _pd_patched = True
    try:
        import pandas.core.arrays.string_ as _sm
        _orig = _sm.StringDtype.__init__
        @_functools.wraps(_orig)
        def _patch(self, *args, **kwargs):
            try:
                _orig(self)
            except TypeError:
                object.__setattr__(self, 'dtype', None)
                object.__setattr__(self, 'storage', 'python')
        _sm.StringDtype.__init__ = _patch
    except Exception:
        pass

_pd_read_pickle = pd.read_pickle
def _patched_read_pickle(*args, **kwargs):
    _ensure_patch()
    return _pd_read_pickle(*args, **kwargs)
pd.read_pickle = _patched_read_pickle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PRED_PATH = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "distributed_predictions_final_full.pkl"
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}
CLIP_DENOM_FACTOR = 0.05   # clipped MAPE 分母 = max(y, factor * capacity)
HOURS = list(range(6, 20))


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def mape(y_true, y_pred):
    """raw MAPE(%)"""
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.mean(np.abs(y_true[m] - y_pred[m]) / y_true[m]) * 100)


def clipped_mape(y_true, y_pred, capacity=None, clip_factor=0.05):
    """clipped MAPE(%): 分母 = max(y, clip_factor * capacity, 0.01)"""
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    if capacity is not None:
        cap_arr = np.asarray(capacity, dtype=float)
        denom = np.maximum.reduce([
            y_true[m],
            clip_factor * cap_arr[m],
            np.full(y_true[m].shape, 0.01)
        ])
    else:
        denom = np.maximum(y_true[m], clip_factor * np.median(y_true[m]))
    return float(np.mean(np.abs(y_true[m] - y_pred[m]) / denom) * 100)


def wape(y_true, y_pred):
    """WAPE(%): sum(|e|) / sum(|y|)"""
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.sum(np.abs(y_true[m] - y_pred[m])) / np.sum(np.abs(y_true[m])) * 100)


def city_rel_err(y_true, y_pred):
    """City total relative error(%): |sum(pred)-sum(actual)| / sum(actual)"""
    mask = np.isfinite(y_true) & np.isfinite(y_pred) & (y_true > 0)
    yt_s = float(np.nansum(y_true[mask]))
    if not np.isfinite(yt_s) or yt_s <= 0:
        return np.nan
    yp_s = float(np.nansum(y_pred[mask]))
    return float(np.abs(yp_s - yt_s) / yt_s * 100)


def capacity_weighted_mape(y_true, y_pred, capacity):
    """容量加权 MAPE"""
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred) & np.isfinite(capacity)
    if not m.any():
        return np.nan
    rel = np.abs(y_true[m] - y_pred[m]) / y_true[m]
    cap = capacity[m]
    return float(np.sum(cap * rel) / np.sum(cap) * 100)


def site_rel_err(y_true, y_pred):
    """单站点相对误差"""
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.abs(y_true[m] - y_pred[m]).sum() / y_true[m].sum() * 100)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("§1 稳健逐小时误差统计")
    print("=" * 60)

    print(f"\n读取: {PRED_PATH}")
    df = pd.read_pickle(PRED_PATH)
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    df["date"] = df["time"].dt.date

    # Filter
    test = df[
        (df["split"] == "test") &
        (~df["site_id"].isin(BAD_SITES)) &
        (df["hour"].isin(HOURS)) &
        (df["power_mw"] > 0)
    ].copy()
    print(f"测试集筛选后: {len(test):,} 行, {test['site_id'].nunique()} 站点, "
          f"{test['date'].nunique()} 天, {test['date'].min()} ~ {test['date'].max()}")

    # Site master
    sm = pd.read_csv(PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "site_master.csv")
    sid_to_name = dict(zip(sm["site_id"], sm["site_short_name"]))

    # ── Per-hour summary ──────────────────────────────────────────────────
    print("\n计算逐小时统计 …")

    hour_rows = []
    for h in HOURS:
        sub = test[test["hour"] == h]
        if len(sub) == 0:
            continue

        yt = sub["power_mw"].values.astype(float)
        yp = sub["power_pred"].values.astype(float)
        cap = sub["capacity_mw"].values.astype(float)

        # city-level (per date first, then average)
        date_rows = []
        for date, dg in sub.groupby("date"):
            if dg["power_mw"].sum() <= 0:
                continue
            date_rows.append({
                "date": date,
                "city_rel_err": city_rel_err(dg["power_mw"].values, dg["power_pred"].values),
                "city_wape": wape(dg["power_mw"].values, dg["power_pred"].values),
                "city_mape": mape(dg["power_mw"].values, dg["power_pred"].values),
            })
        date_df = pd.DataFrame(date_rows)

        # site-level per date-hour then average
        site_rels = []
        site_rel_list = []
        for sid, sg in sub.groupby("site_id"):
            re = site_rel_err(sg["power_mw"].values, sg["power_pred"].values)
            if np.isfinite(re):
                site_rels.append(re)
        site_rels = np.array(site_rels)

        n_gt100 = int((site_rels > 100).sum())
        n_gt200 = int((site_rels > 200).sum())

        worst_idx = int(np.nanargmax(site_rels))
        worst_sid = sub.groupby("site_id")["site_id"].first().iloc[worst_idx] if len(sub["site_id"].unique()) > 0 else ""
        worst_name = sid_to_name.get(worst_sid, worst_sid)
        worst_val = float(np.nanmax(site_rels))

        hour_rows.append({
            "hour": int(h),
            "n_dates": int(date_df["city_rel_err"].count()),
            "n_sites": sub["site_id"].nunique(),
            "n_samples": len(sub),
            # site-level
            "site_mape_raw_mean": float(np.nanmean(site_rels)),
            "site_mape_raw_median": float(np.nanmedian(site_rels)),
            "site_mape_raw_p75": float(np.nanpercentile(site_rels, 75)),
            "site_mape_raw_p90": float(np.nanpercentile(site_rels, 90)),
            "site_mape_clipped_mean": clipped_mape(yt, yp, cap),
            "site_wape_mean": wape(yt, yp),
            "capacity_weighted_mape": capacity_weighted_mape(yt, yp, cap),
            # city-level
            "city_total_rel_err_mean": float(date_df["city_rel_err"].mean()),
            "city_total_rel_err_median": float(date_df["city_rel_err"].median()),
            "city_total_rel_err_p75": float(date_df["city_rel_err"].quantile(0.75)),
            "city_total_rel_err_p90": float(date_df["city_rel_err"].quantile(0.90)),
            "city_wape_mean": float(date_df["city_wape"].mean()),
            "city_wape_median": float(date_df["city_wape"].median()),
            "city_mape_mean": float(date_df["city_mape"].mean()),
            # outlier counts
            "n_site_hour_gt_100": n_gt100,
            "n_site_hour_gt_200": n_gt200,
            # worst
            "worst_site": worst_name,
            "worst_site_err": worst_val,
            # power scale
            "city_actual_mean_mw": float(sub["power_mw"].sum() / max(sub["date"].nunique(), 1)),
            "city_pred_mean_mw": float(sub["power_pred"].sum() / max(sub["date"].nunique(), 1)),
            "bias_pct": float((sub["power_pred"].sum() - sub["power_mw"].sum()) / max(sub["power_mw"].sum(), 1) * 100),
        })

    hour_df = pd.DataFrame(hour_rows).sort_values("hour").reset_index(drop=True)

    out_hourly = OUT_DIR / "hourly_relative_error_robust.csv"
    hour_df.to_csv(out_hourly, index=False, encoding="utf-8-sig")
    print(f"已保存: {out_hourly}")

    # ── Per-date × per-hour detail ────────────────────────────────────────
    print("计算逐日逐时细节 …")
    detail_rows = []
    for (date, hour), g in test.groupby(["date", "hour"]):
        yt = g["power_mw"].values.astype(float)
        yp = g["power_pred"].values.astype(float)
        cap = g["capacity_mw"].values.astype(float)
        detail_rows.append({
            "date": str(date),
            "hour": int(hour),
            "n_sites": g["site_id"].nunique(),
            "city_actual_mw": float(g["power_mw"].sum()),
            "city_pred_mw": float(g["power_pred"].sum()),
            "city_rel_err_pct": city_rel_err(yt, yp),
            "city_wape_pct": wape(yt, yp),
            "city_mape_pct": mape(yt, yp),
            "capacity_weighted_mape_pct": capacity_weighted_mape(yt, yp, cap),
            "site_mape_raw_mean": float(np.nanmean([
                site_rel_err(sg["power_mw"].values, sg["power_pred"].values)
                for _, sg in g.groupby("site_id")
            ])),
        })
    detail_df = pd.DataFrame(detail_rows).sort_values(["date", "hour"]).reset_index(drop=True)
    out_detail = OUT_DIR / "hourly_relative_error_robust_detail.csv"
    detail_df.to_csv(out_detail, index=False, encoding="utf-8-sig")
    print(f"已保存: {out_detail}")

    # ── Print summary table ────────────────────────────────────────────────
    print("\n" + "=" * 100)
    print("逐小时误差指标总览")
    print("=" * 100)
    print(f"{'h':>3} | {'n':>5} | {'site_raw_mean':>13} | {'site_raw_med':>12} | "
          f"{'site_raw_p90':>12} | {'clip_mape':>11} | {'WAPE':>7} | "
          f"{'city_rel_err':>13} | {'cap_w_mape':>11} | {'>100':>5} | {'>200':>5} | {'worst':>12}")
    print("-" * 100)
    for _, r in hour_df.iterrows():
        h = int(r["hour"])
        n = int(r["n_sites"])
        print(
            f"{h:3d} | {n:5d} | "
            f"{r['site_mape_raw_mean']:>13.1f} | "
            f"{r['site_mape_raw_median']:>12.1f} | "
            f"{r['site_mape_raw_p90']:>12.1f} | "
            f"{r['site_mape_clipped_mean']:>11.1f} | "
            f"{r['site_wape_mean']:>7.1f} | "
            f"{r['city_total_rel_err_mean']:>13.1f} | "
            f"{r['capacity_weighted_mape']:>11.1f} | "
            f"{int(r['n_site_hour_gt_100']):>5d} | "
            f"{int(r['n_site_hour_gt_200']):>5d} | "
            f"{r['worst_site']:>12s}"
        )

    print("\n" + "=" * 70)
    print("时段汇总")
    print("=" * 70)
    period_map = {
        "dawn": [6, 7],
        "morning": [8, 9],
        "midday": list(range(10, 15)),
        "afternoon": [15, 16],
        "dusk": [17, 18, 19],
    }
    for period, hrs in period_map.items():
        sub = hour_df[hour_df["hour"].isin(hrs)]
        if len(sub) == 0:
            continue
        print(
            f"  {period:>10} ({hrs[0]}-{hrs[-1]}h): "
            f"city_rel_err={sub['city_total_rel_err_mean'].mean():.1f}%  "
            f"site_raw_mean={sub['site_mape_raw_mean'].mean():.1f}%  "
            f"site_raw_med={sub['site_mape_raw_median'].mean():.1f}%  "
            f"WAPE={sub['site_wape_mean'].mean():.1f}%  "
            f"clip_mape={sub['site_mape_clipped_mean'].mean():.1f}%"
        )

    print("\nDone.")
    return hour_df


if __name__ == "__main__":
    main()
