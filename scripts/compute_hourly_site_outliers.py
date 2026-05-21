#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§2 站点小时异常表
================
识别并分类问题站点小时组合（低功率分母型 / 系统性低估型 / 数据质量型）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
import sys

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
HOURS = list(range(6, 20))
MIN_SAMPLES = 10  # 最少样本数才参与判断


def wape(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.sum(np.abs(y_true[m] - y_pred[m])) / np.sum(np.abs(y_true[m])) * 100)


def mape(y_true, y_pred):
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.mean(np.abs(y_true[m] - y_pred[m]) / y_true[m]) * 100)


def classify_site_hour(row):
    """三类问题分类"""
    rel_err = row["avg_rel_err_raw"]
    wape_v = row["wape"]
    bias = row["bias_pct"]
    actual_mean = row["actual_mean"]
    n = row["n_samples"]
    capacity = row["capacity_mw"]

    if n < MIN_SAMPLES:
        return "insufficient_samples", "样本不足，无法判断"

    # 触发阈值
    is_high_rel = rel_err > 100
    is_high_wape = wape_v > 80
    is_high_bias = abs(bias) > 80
    is_low_power = actual_mean < 0.05 * capacity if np.isfinite(actual_mean) and np.isfinite(capacity) else False

    if is_high_rel and is_low_power and not is_high_bias:
        return "low_power_denominator", "低功率分母放大效应"
    elif is_high_bias and bias < -50:
        return "systematic_underestimate", "系统性低估"
    elif is_high_rel and is_high_wape:
        # 进一步区分
        if is_low_power:
            return "low_power_denominator", "低功率分母放大效应"
        elif bias < -30:
            return "systematic_underestimate", "系统性低估"
        else:
            return "data_quality", "数据质量异常"
    elif is_high_bias and abs(bias) > 50:
        return "systematic_bias", "系统性偏差"
    else:
        return "normal", "正常"


def main():
    print("=" * 60)
    print("§2 站点小时异常表")
    print("=" * 60)

    df = pd.read_pickle(PRED_PATH)
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    df["date"] = df["time"].dt.date

    test = df[
        (df["split"] == "test") &
        (~df["site_id"].isin(BAD_SITES)) &
        (df["hour"].isin(HOURS)) &
        (df["power_mw"] > 0)
    ].copy()

    sm = pd.read_csv(PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "site_master.csv")
    sid_to_name = dict(zip(sm["site_id"], sm["site_short_name"]))
    sid_to_county = dict(zip(sm["site_id"], sm["county"]))
    sid_to_cap = dict(zip(sm["site_id"], sm["capacity_mw"]))

    print(f"\n测试集: {len(test):,} 行, {test['site_id'].nunique()} 站点")

    rows = []
    for (sid, h), g in test.groupby(["site_id", "hour"]):
        n = len(g)
        yt = g["power_mw"].values.astype(float)
        yp = g["power_pred"].values.astype(float)
        cap = float(sid_to_cap.get(sid, np.nan))
        county = sid_to_county.get(sid, "")

        actual_mean = float(np.nanmean(yt))
        pred_mean = float(np.nanmean(yp))
        actual_sum = float(np.nansum(yt))
        pred_sum = float(np.nansum(yp))

        bias_pct = (pred_sum - actual_sum) / max(actual_sum, 1e-6) * 100

        # raw rel err: per date then average
        date_rels = []
        for _, dg in g.groupby("date"):
            if dg["power_mw"].sum() > 0:
                re = float(np.abs(dg["power_pred"].sum() - dg["power_mw"].sum()) / dg["power_mw"].sum() * 100)
                date_rels.append(re)
        avg_rel_err_raw = float(np.nanmean(date_rels)) if date_rels else np.nan

        wape_v = wape(yt, yp)
        mape_v = mape(yt, yp)
        is_low_power = actual_mean < 0.05 * cap if np.isfinite(actual_mean) and cap > 0 else False

        rows.append({
            "hour": int(h),
            "site_id": sid,
            "site_name": sid_to_name.get(sid, sid),
            "county": county,
            "capacity_mw": cap,
            "n_samples": n,
            "actual_mean": actual_mean,
            "pred_mean": pred_mean,
            "bias_pct": round(bias_pct, 2),
            "avg_rel_err_raw": round(avg_rel_err_raw, 2) if np.isfinite(avg_rel_err_raw) else np.nan,
            "wape": round(wape_v, 2) if np.isfinite(wape_v) else np.nan,
            "mape": round(mape_v, 2) if np.isfinite(mape_v) else np.nan,
            "is_low_power_site_hour": is_low_power,
            # 问题判定
            "is_problem": (
                (avg_rel_err_raw > 100 and n >= MIN_SAMPLES) or
                (wape_v > 80 and n >= MIN_SAMPLES) or
                (abs(bias_pct) > 80 and n >= MIN_SAMPLES)
            ),
        })

    df_out = pd.DataFrame(rows)
    df_out["problem_type"], df_out["problem_reason"] = zip(*df_out.apply(classify_site_hour, axis=1))

    # 排序
    df_out = df_out.sort_values(["hour", "site_id"]).reset_index(drop=True)

    # 问题站点汇总
    problem_df = df_out[df_out["is_problem"] == True].copy()
    print(f"\n问题站点小时组合: {len(problem_df)} 个")

    # 按类型分组
    print("\n按问题类型分组:")
    for ptype in problem_df["problem_type"].unique():
        sub = problem_df[problem_df["problem_type"] == ptype]
        print(f"  {ptype}: {len(sub)} 个")
        # 打印最严重的几个
        worst = sub.nlargest(5, "avg_rel_err_raw")
        for _, r in worst.iterrows():
            print(f"    {r['site_name']}(h={r['hour']:02d}): rel_err={r['avg_rel_err_raw']:.1f}%, "
                  f"bias={r['bias_pct']:+.1f}%, actual_mean={r['actual_mean']:.3f}MW, "
                  f"cap={r['capacity_mw']:.2f}MW, reason={r['problem_reason']}")

    # 按小时汇总
    print("\n按小时汇总问题数量:")
    hour_summary = problem_df.groupby("hour").size().reset_index(name="n_problem_sites")
    for _, r in hour_summary.iterrows():
        print(f"  h={int(r['hour']):02d}: {int(r['n_problem_sites'])} 个问题站点")

    out = OUT_DIR / "hourly_site_outlier_table.csv"
    df_out.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n已保存: {out}")
    print(f"  总行数: {len(df_out)}, 问题行数: {len(problem_df)}")

    # 问题站点专项 CSV
    out_prob = OUT_DIR / "hourly_site_outlier_problem_only.csv"
    problem_df.to_csv(out_prob, index=False, encoding="utf-8-sig")
    print(f"已保存 (仅问题): {out_prob}")

    print("\nDone.")


if __name__ == "__main__":
    main()
