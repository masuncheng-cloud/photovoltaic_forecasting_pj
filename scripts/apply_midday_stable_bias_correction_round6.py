#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round6 脚本五：正午稳定偏差保守修正
====================================
只对 train/valid 均显示稳定极端偏差的站点小时做保守修正。
系数 k 向 1.0 收缩（0.55x），限制在 [0.70, 1.25]。
仅在 valid 真正改善（>0.20pp）时才应用。
"""
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load, write_prediction_pickle_atomic
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics

TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)

MIDDAY_HOURS = [10, 11, 12, 13, 14]
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}

IN_PATH = TABLES_DIR / "distributed_predictions_metadata_overridden_full.pkl"
FALLBACK_PATH = TABLES_DIR / "distributed_predictions_midday_site_calibrated_full.pkl"
OUT_FULL = TABLES_DIR / "distributed_predictions_round6_stable_bias_full.pkl"
OUT_EVAL = TABLES_DIR / "distributed_predictions_round6_stable_bias_eval.pkl"
OUT_PARAMS = METRICS_DIR / "round6_stable_bias_correction_params.csv"
OUT_VALID = METRICS_DIR / "round6_stable_bias_valid_ablation.csv"
OUT_TEST = METRICS_DIR / "round6_stable_bias_test_hourly_nrmse.csv"


def ensure_columns(df):
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour
    return out


def nrmse_pct(g, pred_col="power_pred"):
    y = pd.to_numeric(g["power_mw"], errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(g[pred_col], errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(g["capacity_mw"], errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (y > 0) & (c > 0)
    if not m.any():
        return np.nan
    return float(np.sqrt(np.mean((y[m] - p[m]) ** 2)) / np.nanmean(c[m]) * 100.0)


def pred_actual_ratio(g, pred_col="power_pred"):
    y = pd.to_numeric(g["power_mw"], errors="coerce")
    p = pd.to_numeric(g[pred_col], errors="coerce")
    m = y.notna() & p.notna() & (y > 0)
    if not m.any():
        return np.nan
    actual = float(y[m].sum())
    pred = float(p[m].sum())
    return pred / actual if actual > 0 else np.nan


def learn_train_k(g):
    y = pd.to_numeric(g["power_mw"], errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(g["power_pred"], errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & (y > 0) & (p > 0)
    if m.sum() < 80:
        return np.nan
    denom = float(np.sum(p[m] ** 2))
    if denom <= 1e-9:
        return np.nan
    k = float(np.sum(y[m] * p[m]) / denom)
    return float(np.clip(k, 0.55, 1.45))


def apply_k(g, k):
    out = g.copy()
    cap = pd.to_numeric(out["capacity_mw"], errors="coerce").fillna(0)
    pred = pd.to_numeric(out["power_pred"], errors="coerce") * k
    out["power_pred_candidate"] = pred.clip(lower=0, upper=cap)
    return out


def learn_params(df):
    work = df[
        df["hour"].isin(MIDDAY_HOURS)
        & (~df["site_id"].isin(BAD_SITES))
        & (pd.to_numeric(df["power_mw"], errors="coerce") > 0)
    ].copy()

    rows = []
    for (sid, h), g in work.groupby(["site_id", "hour"]):
        train = g[g["split"] == "train"]
        valid = g[g["split"] == "valid"]
        if len(train) < 80 or len(valid) < 30:
            continue

        train_ratio = pred_actual_ratio(train)
        valid_ratio = pred_actual_ratio(valid)
        if not np.isfinite(train_ratio) or not np.isfinite(valid_ratio):
            continue

        stable_over = train_ratio > 1.35 and valid_ratio > 1.35
        stable_under = train_ratio < 0.75 and valid_ratio < 0.75
        if not (stable_over or stable_under):
            continue

        k_raw = learn_train_k(train)
        if not np.isfinite(k_raw):
            continue

        # 保守收缩：k = 1 + 0.55 * (k_raw - 1)
        k = 1.0 + 0.55 * (k_raw - 1.0)
        k = float(np.clip(k, 0.70, 1.25))

        valid_before = nrmse_pct(valid)
        valid_cand = apply_k(valid, k)
        valid_after = nrmse_pct(valid_cand, "power_pred_candidate")
        if not np.isfinite(valid_before) or not np.isfinite(valid_after):
            continue

        improve = valid_before - valid_after
        if improve < 0.20:
            continue

        rows.append({
            "site_id": sid,
            "hour": int(h),
            "train_rows": int(len(train)),
            "valid_rows": int(len(valid)),
            "bias_class": "stable_over_prediction" if stable_over else "stable_under_prediction",
            "train_ratio": round(float(train_ratio), 4),
            "valid_ratio": round(float(valid_ratio), 4),
            "k_raw_train": round(float(k_raw), 4),
            "k_final": round(float(k), 4),
            "valid_before_nrmse_pct": round(float(valid_before), 4),
            "valid_after_nrmse_pct": round(float(valid_after), 4),
            "valid_improvement_pp": round(float(improve), 4),
        })

    return pd.DataFrame(rows)


def apply_params(df, params):
    out = df.copy()
    out["_row_order"] = np.arange(len(out))
    if params.empty:
        out["round6_stable_bias_applied"] = False
        return out.drop(columns=["_row_order"])

    p = params[["site_id", "hour", "k_final"]].copy()
    out = out.merge(p, on=["site_id", "hour"], how="left")
    mask = out["hour"].isin(MIDDAY_HOURS) & out["k_final"].notna()
    cap = pd.to_numeric(out.loc[mask, "capacity_mw"], errors="coerce").fillna(0)
    pred = pd.to_numeric(out.loc[mask, "power_pred"], errors="coerce")
    k_vals = pd.to_numeric(out.loc[mask, "k_final"], errors="coerce")
    out.loc[mask, "power_pred"] = (pred * k_vals).clip(lower=0, upper=cap)
    out["round6_stable_bias_applied"] = False
    out.loc[mask, "round6_stable_bias_applied"] = True
    out = out.sort_values("_row_order").drop(columns=["_row_order", "k_final"])
    return out


def valid_ablation(before, after):
    rows = []
    for h in MIDDAY_HOURS:
        b = before[(before["split"] == "valid") & (before["hour"] == h)]
        a = after[(after["split"] == "valid") & (after["hour"] == h)]
        if b.empty or a.empty:
            continue
        bm = hourly_nrmse_metrics(b)
        am = hourly_nrmse_metrics(a)
        br = bm[bm["hour"] == h]
        ar = am[am["hour"] == h]
        if br.empty or ar.empty:
            continue
        rows.append({
            "hour": h,
            "before_site_nrmse_mean_pct": float(br.iloc[0]["site_nrmse_mean_pct"]),
            "after_site_nrmse_mean_pct": float(ar.iloc[0]["site_nrmse_mean_pct"]),
            "improvement_pp": float(br.iloc[0]["site_nrmse_mean_pct"] - ar.iloc[0]["site_nrmse_mean_pct"]),
            "before_city_nrmse_pct": float(br.iloc[0]["city_nrmse_pct"]),
            "after_city_nrmse_pct": float(ar.iloc[0]["city_nrmse_pct"]),
        })
    return pd.DataFrame(rows)


def main():
    in_path = IN_PATH if IN_PATH.exists() else FALLBACK_PATH
    if not in_path.exists():
        raise FileNotFoundError(in_path)

    print(f"读取: {in_path}")
    df = ensure_columns(safe_pickle_load(in_path))
    params = learn_params(df)
    params.to_csv(OUT_PARAMS, index=False, encoding="utf-8-sig")
    print(f"稳定偏差修正参数数量: {len(params)}")
    if not params.empty:
        print(params.to_string(index=False))

    corrected = apply_params(df, params)
    ab = valid_ablation(df, corrected)
    ab.to_csv(OUT_VALID, index=False, encoding="utf-8-sig")
    print("valid 消融:")
    print(ab.to_string(index=False))

    eval_df = build_eval_frame(
        corrected,
        split="test",
        hours=tuple(range(6, 20)),
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=53,
    )

    write_prediction_pickle_atomic(
        corrected,
        OUT_FULL,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
    )
    write_prediction_pickle_atomic(
        eval_df,
        OUT_EVAL,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
        hour_range=(6, 19),
    )

    hmet = hourly_nrmse_metrics(eval_df)
    hmet[hmet["hour"].isin(MIDDAY_HOURS)].to_csv(OUT_TEST, index=False, encoding="utf-8-sig")
    print("test 10-14 NRMSE，仅最终查看:")
    print(hmet[hmet["hour"].isin(MIDDAY_HOURS)].to_string(index=False))


if __name__ == "__main__":
    main()
