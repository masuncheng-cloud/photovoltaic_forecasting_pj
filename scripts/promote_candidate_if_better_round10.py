#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round10：候选晋级判断 — 只有明确更优才替换 best，否则自动回退"""
from __future__ import annotations

from pathlib import Path
import sys, shutil, argparse, json
from datetime import datetime
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

BEST_EVAL = TABLES / "best_predictions_eval.pkl"
BEST_FULL = TABLES / "best_predictions_full.pkl"
FINAL_EVAL = TABLES / "distributed_predictions_final_eval.pkl"
FINAL_FULL = TABLES / "distributed_predictions_final_full.pkl"

MIDDAY = [10, 11, 12, 13, 14]


def _ensure_hour(df):
    out = df.copy()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour
    return out


def _calc_nrmse(y, p, c):
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(c, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (c > 0)
    if not m.any():
        return np.nan
    rmse_val = float(np.sqrt(np.mean((y[m] - p[m]) ** 2)))
    cap_mean = float(np.nanmean(c[m]))
    return rmse_val / cap_mean * 100.0 if cap_mean > 0 else np.nan


def _calc_mae(y, p):
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p)
    return float(np.mean(np.abs(y[m] - p[m]))) if m.any() else np.nan


def _calc_rmse(y, p):
    y = pd.to_numeric(y, errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(p, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p)
    return float(np.sqrt(np.mean((y[m] - p[m]) ** 2))) if m.any() else np.nan


def _metrics(df):
    df = _ensure_hour(df)
    y = df["power_mw"]
    p = df["power_pred"]
    c = df["capacity_mw"]

    actual = float(pd.to_numeric(y, errors="coerce").sum())
    pred = float(pd.to_numeric(p, errors="coerce").sum())

    midday = df[df["hour"].isin(MIDDAY)].copy()

    return {
        "rows": int(len(df)),
        "n_sites": int(df["site_id"].nunique()),
        "actual_mwh": round(actual, 4),
        "pred_mwh": round(pred, 4),
        "pred_actual_ratio": round(pred / actual, 6) if actual > 0 else np.nan,
        "bias_pct": round((pred / actual - 1.0) * 100.0, 4) if actual > 0 else np.nan,
        "overall_nrmse_pct": round(_calc_nrmse(y, p, c), 6),
        "midday_overall_nrmse_pct": round(
            _calc_nrmse(midday["power_mw"], midday["power_pred"], midday["capacity_mw"]), 6
        ),
        "mae_mw": round(_calc_mae(y, p), 6),
        "rmse_mw": round(_calc_rmse(y, p), 6),
    }


def score(m):
    """综合分数，越低越好"""
    return (
        0.45 * m["midday_overall_nrmse_pct"]
        + 0.35 * m["overall_nrmse_pct"]
        + 0.10 * m["mae_mw"]
        + 0.10 * m["rmse_mw"]
    )


def main():
    parser = argparse.ArgumentParser(description="Round10 候选晋级判断")
    parser.add_argument("--candidate-eval", required=True)
    parser.add_argument("--candidate-full", required=True)
    parser.add_argument("--name", default="candidate")
    parser.add_argument("--min-overall-improve-pp", type=float, default=0.10)
    parser.add_argument("--min-midday-improve-pp", type=float, default=0.0)
    args = parser.parse_args()

    cand_eval = Path(args.candidate_eval)
    cand_full = Path(args.candidate_full)
    if not cand_eval.is_absolute():
        cand_eval = PROJECT_ROOT / cand_eval
    if not cand_full.is_absolute():
        cand_full = PROJECT_ROOT / cand_full

    for f in [BEST_EVAL, BEST_FULL, cand_eval, cand_full]:
        if not f.exists():
            raise FileNotFoundError(f)

    best_df = safe_pickle_load(BEST_EVAL)
    cand_df = safe_pickle_load(cand_eval)

    best_m = _metrics(best_df)
    cand_m = _metrics(cand_df)

    best_s = score(best_m)
    cand_s = score(cand_m)

    overall_improve = best_m["overall_nrmse_pct"] - cand_m["overall_nrmse_pct"]
    midday_improve = best_m["midday_overall_nrmse_pct"] - cand_m["midday_overall_nrmse_pct"]

    accept = overall_improve >= args.min_overall_improve_pp
    reasons = []

    if not accept:
        reasons.append(
            f"整体 NRMSE 改善不足: {overall_improve:.4f} pp < {args.min_overall_improve_pp:.4f} pp"
        )
    if midday_improve < args.min_midday_improve_pp:
        accept = False
        reasons.append(
            f"10-14 NRMSE 改善不足: {midday_improve:.4f} pp < {args.min_midday_improve_pp:.4f} pp"
        )

    decision = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "candidate_name": args.name,
        "accepted": accept,
        "reasons": reasons,
        "best_metrics": best_m,
        "candidate_metrics": cand_m,
        "best_score": best_s,
        "candidate_score": cand_s,
        "overall_improve_pp": overall_improve,
        "midday_improve_pp": midday_improve,
    }

    out_json = METRICS / f"round10_candidate_decision_{args.name}.json"
    out_json.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")

    if accept:
        shutil.copy2(cand_eval, FINAL_EVAL)
        shutil.copy2(cand_full, FINAL_FULL)
        shutil.copy2(cand_eval, BEST_EVAL)
        shutil.copy2(cand_full, BEST_FULL)
        print(f"[ACCEPT] {args.name} promoted to final and best.")
    else:
        shutil.copy2(BEST_EVAL, FINAL_EVAL)
        shutil.copy2(BEST_FULL, FINAL_FULL)
        print(f"[REJECT] {args.name} rejected. final rolled back to best.")
        for r in reasons:
            print(f"  - {r}")

    print(f"\nDecision: {out_json}")
    print(f"  best_overall={best_m['overall_nrmse_pct']:.4f}%, cand_overall={cand_m['overall_nrmse_pct']:.4f}%")
    print(f"  best_midday={best_m['midday_overall_nrmse_pct']:.4f}%, cand_midday={cand_m['midday_overall_nrmse_pct']:.4f}%")
    print(f"  best_mae={best_m['mae_mw']:.6f} MW, cand_mae={cand_m['mae_mw']:.6f} MW")
    print(f"  best_rmse={best_m['rmse_mw']:.6f} MW, cand_rmse={cand_m['rmse_mw']:.6f} MW")
    print(f"  overall_improve={overall_improve:.4f} pp, midday_improve={midday_improve:.4f} pp, accept={accept}")


if __name__ == "__main__":
    main()
