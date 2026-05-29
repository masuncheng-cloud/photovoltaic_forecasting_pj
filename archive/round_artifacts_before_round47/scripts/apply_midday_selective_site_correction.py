#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10-14 点选择性站点小时修正。

核心思想：
  1. 以 MiddaySiteCalibrated 为基础版本。
  2. 只在 train/valid 上学习参数。
  3. 对每个 (site_id, hour) 尝试多个候选：
     - 原始 power_pred
     - 乘以系数 k
     - 与 pred_baseline 做混合后再乘以 k
  4. 在 valid 上只有当站点小时 NRMSE 明确下降时，才采用该修正。
  5. 对样本少的站点小时不动。
  6. test 只用于最后输出评估，不参与参数选择。

输出：
  distributed_predictions_midday_selective_site_corrected_full.pkl
  distributed_predictions_midday_selective_site_corrected_eval.pkl
  midday_selective_site_correction_params.csv
  midday_selective_site_correction_valid_ablation.csv
  midday_selective_site_correction_test_hourly_nrmse.csv
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

IN_BASE = TABLES_DIR / "distributed_predictions_midday_site_calibrated_full.pkl"
IN_FALLBACK = TABLES_DIR / "distributed_predictions_fixed_full.pkl"
OUT_FULL = TABLES_DIR / "distributed_predictions_midday_selective_site_corrected_full.pkl"
OUT_EVAL = TABLES_DIR / "distributed_predictions_midday_selective_site_corrected_eval.pkl"
OUT_PARAMS = METRICS_DIR / "midday_selective_site_correction_params.csv"
OUT_VALID = METRICS_DIR / "midday_selective_site_correction_valid_ablation.csv"
OUT_TEST = METRICS_DIR / "midday_selective_site_correction_test_hourly_nrmse.csv"


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour
    if "date" not in out.columns:
        out["date"] = out["time"].dt.date
    return out


def nrmse_pct(y, p, c) -> float:
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(c, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (c > 0)
    if not m.any():
        return np.nan
    rmse = float(np.sqrt(np.mean((y[m] - p[m]) ** 2)))
    cap = float(np.nanmean(c[m]))
    return rmse / cap * 100.0 if cap > 0 else np.nan


def make_candidate_pred(g: pd.DataFrame, alpha: float, k: float) -> pd.Series:
    ml = pd.to_numeric(g["power_pred"], errors="coerce")
    cap = pd.to_numeric(g["capacity_mw"], errors="coerce").fillna(0.0)
    if "pred_baseline" in g.columns:
        bl = pd.to_numeric(g["pred_baseline"], errors="coerce")
        pred = alpha * ml + (1.0 - alpha) * bl.fillna(ml)
    else:
        pred = ml
    pred = pred * k
    return pred.clip(lower=0.0, upper=cap)


def learn_params(df: pd.DataFrame) -> pd.DataFrame:
    work = df[
        df["hour"].isin(MIDDAY_HOURS)
        & (~df["site_id"].isin(BAD_SITES))
        & (pd.to_numeric(df["power_mw"], errors="coerce") > 0)
    ].copy()

    valid = work[work["split"] == "valid"].copy()
    if valid.empty:
        raise RuntimeError("valid 为空，无法学习选择性站点小时修正")

    alpha_grid = [0.0, 0.1, 0.2, 0.35, 0.5, 0.7, 0.85, 1.0]
    k_grid = [0.88, 0.92, 0.96, 1.00, 1.04, 1.08, 1.12]
    min_valid_rows = 30
    min_improve_pp = 0.15

    rows = []
    for (sid, h), vg in valid.groupby(["site_id", "hour"]):
        if len(vg) < min_valid_rows:
            continue

        base_n = nrmse_pct(vg["power_mw"], vg["power_pred"], vg["capacity_mw"])
        if not np.isfinite(base_n):
            continue

        best = {
            "alpha": 1.0,
            "k": 1.0,
            "valid_before_nrmse_pct": base_n,
            "valid_after_nrmse_pct": base_n,
            "improvement_pp": 0.0,
        }

        for alpha in alpha_grid:
            for k in k_grid:
                pred = make_candidate_pred(vg, alpha=alpha, k=k)
                cand_n = nrmse_pct(vg["power_mw"], pred, vg["capacity_mw"])
                if not np.isfinite(cand_n):
                    continue
                if cand_n < best["valid_after_nrmse_pct"]:
                    best.update({
                        "alpha": alpha,
                        "k": k,
                        "valid_after_nrmse_pct": cand_n,
                        "improvement_pp": base_n - cand_n,
                    })

        # 只有 valid 上明确改善才采用；否则该站点小时不修正。
        if best["improvement_pp"] >= min_improve_pp:
            rows.append({
                "site_id": sid,
                "hour": int(h),
                "valid_rows": int(len(vg)),
                "alpha": float(best["alpha"]),
                "k": float(best["k"]),
                "valid_before_nrmse_pct": round(float(best["valid_before_nrmse_pct"]), 4),
                "valid_after_nrmse_pct": round(float(best["valid_after_nrmse_pct"]), 4),
                "improvement_pp": round(float(best["improvement_pp"]), 4),
            })

    params = pd.DataFrame(rows)
    return params


def apply_params(df: pd.DataFrame, params: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["_row_order"] = np.arange(len(out))
    if params.empty:
        out["midday_selective_applied"] = False
        return out.drop(columns=["_row_order"])

    p = params[["site_id", "hour", "alpha", "k"]].copy()
    out = out.merge(p, on=["site_id", "hour"], how="left")

    mask = out["hour"].isin(MIDDAY_HOURS) & out["alpha"].notna() & out["k"].notna()
    if mask.any():
        ml = pd.to_numeric(out.loc[mask, "power_pred"], errors="coerce")
        cap = pd.to_numeric(out.loc[mask, "capacity_mw"], errors="coerce").fillna(0.0)
        alpha = pd.to_numeric(out.loc[mask, "alpha"], errors="coerce").fillna(1.0)
        k = pd.to_numeric(out.loc[mask, "k"], errors="coerce").fillna(1.0)
        if "pred_baseline" in out.columns:
            bl = pd.to_numeric(out.loc[mask, "pred_baseline"], errors="coerce")
            cand = alpha * ml + (1.0 - alpha) * bl.fillna(ml)
        else:
            cand = ml
        cand = (cand * k).clip(lower=0.0, upper=cap)
        out.loc[mask, "power_pred"] = cand

    out["midday_selective_applied"] = mask
    out = out.sort_values("_row_order").drop(columns=["_row_order", "alpha", "k"])
    return out


def valid_ablation(df_before: pd.DataFrame, df_after: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for h in MIDDAY_HOURS:
        b = df_before[
            (df_before["split"] == "valid")
            & (df_before["hour"] == h)
            & (~df_before["site_id"].isin(BAD_SITES))
            & (pd.to_numeric(df_before["power_mw"], errors="coerce") > 0)
        ]
        a = df_after[
            (df_after["split"] == "valid")
            & (df_after["hour"] == h)
            & (~df_after["site_id"].isin(BAD_SITES))
            & (pd.to_numeric(df_after["power_mw"], errors="coerce") > 0)
        ]
        if len(b) == 0 or len(a) == 0:
            continue
        before = hourly_nrmse_metrics(b)
        after = hourly_nrmse_metrics(a)
        br = before[before["hour"] == h].iloc[0]
        ar = after[after["hour"] == h].iloc[0]
        rows.append({
            "hour": int(h),
            "valid_rows": int(len(a)),
            "before_site_nrmse_mean_pct": float(br["site_nrmse_mean_pct"]),
            "after_site_nrmse_mean_pct": float(ar["site_nrmse_mean_pct"]),
            "improvement_pp": float(br["site_nrmse_mean_pct"] - ar["site_nrmse_mean_pct"]),
            "before_city_nrmse_pct": float(br["city_nrmse_pct"]),
            "after_city_nrmse_pct": float(ar["city_nrmse_pct"]),
        })
    return pd.DataFrame(rows)


def main():
    print("=" * 80)
    print("10-14 点选择性站点小时修正")
    print("=" * 80)

    in_path = IN_BASE if IN_BASE.exists() else IN_FALLBACK
    if not in_path.exists():
        raise FileNotFoundError(f"找不到输入文件: {in_path}")

    print(f"读取: {in_path}")
    df = ensure_columns(safe_pickle_load(in_path))

    params = learn_params(df)
    params.to_csv(OUT_PARAMS, index=False, encoding="utf-8-sig")
    print(f"采用修正的站点小时数量: {len(params)}")
    print(f"保存参数: {OUT_PARAMS}")

    df_corr = apply_params(df, params)
    ab = valid_ablation(df, df_corr)
    ab.to_csv(OUT_VALID, index=False, encoding="utf-8-sig")
    print("\nvalid 消融:")
    print(ab.to_string(index=False))

    eval_df = build_eval_frame(
        df_corr,
        pred_col="power_pred",
        split="test",
        hours=tuple(range(6, 20)),
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=53,
    )

    write_prediction_pickle_atomic(
        df_corr,
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
    print(f"\n保存: {OUT_FULL}")
    print(f"保存: {OUT_EVAL}")
    print("\ntest 10-14 NRMSE（仅最终查看）:")
    print(hmet[hmet["hour"].isin(MIDDAY_HOURS)].to_string(index=False))


if __name__ == "__main__":
    main()
