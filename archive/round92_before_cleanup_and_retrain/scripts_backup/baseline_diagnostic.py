#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Baseline 诊断：对比 distributed_predictions.pkl vs fixed_full.pkl
了解各版本的差异。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
import functools as _functools

_pd_patch_done = False
def _ensure_patch():
    global _pd_patch_done
    if _pd_patch_done: return
    _pd_patch_done = True
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

_pd_read_pickle_orig = pd.read_pickle
def _patched_read_pickle(*args, **kwargs):
    _ensure_patch()
    return _pd_read_pickle_orig(*args, **kwargs)
pd.read_pickle = _patched_read_pickle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}
HOURS = list(range(6, 20))
DAWN_DUSK = [6, 7, 16, 17, 18, 19]

def raw_mape(y, p):
    m = (y > 0) & np.isfinite(y) & np.isfinite(p)
    if not m.any(): return np.nan
    return float(np.mean(np.abs(y[m] - p[m]) / y[m]) * 100)

def clipped_mape(y, p, cf=0.05):
    m = (y > 0) & np.isfinite(y) & np.isfinite(p)
    if not m.any(): return np.nan
    denom = np.maximum(y[m], cf * np.median(y[m]))
    return float(np.mean(np.abs(y[m] - p[m]) / denom) * 100)

def wape(y, p):
    m = np.isfinite(y) & np.isfinite(p)
    if not m.any(): return np.nan
    return float(np.sum(np.abs(y[m] - p[m])) / np.sum(np.abs(y[m])) * 100)

def city_rel_err(y, p):
    m = np.isfinite(y) & np.isfinite(p) & (y > 0)
    yt = float(np.nansum(y[m]))
    if not np.isfinite(yt) or yt <= 0: return np.nan
    return float(np.abs(np.nansum(p[m]) - yt) / yt * 100)


def main():
    print("=" * 70)
    print("Baseline 诊断")
    print("=" * 70)

    # Load fixed_full to get the split column
    df_fixed = pd.read_pickle(TABLES / "distributed_predictions_fixed_full.pkl")
    df_fixed["time"] = pd.to_datetime(df_fixed["time"])
    df_fixed["hour"] = df_fixed["time"].dt.hour

    # Load raw predictions
    df_raw = pd.read_pickle(TABLES / "distributed_predictions.pkl")
    df_raw["time"] = pd.to_datetime(df_raw["time"])

    # Filter test set using split from fixed_full
    mask = (
        (df_fixed["split"] == "test") &
        (~df_fixed["site_id"].isin(BAD_SITES)) &
        (df_fixed["hour"].isin(HOURS)) &
        (df_fixed["power_mw"] > 0)
    )
    fixed_test = df_fixed[mask].copy()

    # Match raw predictions by (time, site_id)
    raw_map = df_raw.set_index(["time", "site_id"])["power_pred"].to_dict()
    fixed_test["power_pred_raw"] = fixed_test.apply(
        lambda r: raw_map.get((r["time"], r["site_id"]),
                             raw_map.get((pd.Timestamp(r["time"]), r["site_id"]), np.nan)), axis=1)

    # Check column alignment
    n_common = fixed_test["power_pred_raw"].notna().sum()
    print(f"行数: fixed_full={len(fixed_test):,}, raw匹配={n_common:,}")

    # Check power_pred differences
    diff_mask = fixed_test["power_pred_raw"].notna()
    raw_vals = fixed_test.loc[diff_mask, "power_pred_raw"].values
    fixed_vals = fixed_test.loc[diff_mask, "power_pred"].values
    diffs = fixed_vals - raw_vals
    rel_diffs = diffs / np.maximum(raw_vals, 0.001)

    print(f"预测不同的样本: {(np.abs(diffs) > 0.001).sum():,} / {diff_mask.sum():,}")
    print(f"  fixed/raw 比率: mean={np.nanmean(rel_diffs):.4f}, "
          f"median={np.nanmedian(rel_diffs):.4f}, "
          f"p25={np.nanpercentile(rel_diffs,25):.4f}, "
          f"p75={np.nanpercentile(rel_diffs,75):.4f}")
    print(f"  fixed > raw: {(rel_diffs > 0).sum():,}")
    print(f"  fixed < raw: {(rel_diffs < 0).sum():,}")

    # Global comparison
    print(f"\n全局指标对比:")
    yt = fixed_test["power_mw"].values.astype(float)
    for pred_col, label in [("power_pred_raw", "raw模型"), ("power_pred", "fixed_full")]:
        yp = fixed_test[pred_col].values.astype(float)
        m = np.isfinite(yp)
        if m.sum() > 0:
            print(f"  {label}: WAPE={wape(yt[m], yp[m]):.1f}%, "
                  f"clip={clipped_mape(yt[m], yp[m]):.1f}%, "
                  f"city_rel={city_rel_err(yt[m], yp[m]):.1f}%")

    print("\nDone.")


if __name__ == "__main__":
    main()
