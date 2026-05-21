#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v1.5.9 Fix v3: P0+P1 分层应用 + P1 稀疏性报告
==================================================
P0（晴空保护）：修正站点级预测值
P1（GHI×月份因子）：仅在城市聚合层面应用，不改变站点预测

修正点：
  - 统一引用 split.py，使用 split=="valid"/"test"
  - 验证集：2025-07-01 ~ 2025-09-01（不是 4~6月）
  - 测试集：time >= 2025-09-01（不是 month>=7）
  - 新增 p1_factor_sparsity.csv
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
import sys

# pandas 3.x pickle 兼容 patch
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
PRED_PATH = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "distributed_predictions.pkl"
OUTPUT_PATH = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "distributed_predictions_v159_fix.pkl"
METRICS_PATH = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"

GHI_CLEAR = 600.0
GHI_MED = 300.0
GHI_BINS = [0, 100, 200, 300, 450, 600, 800, 99999]
FACTOR_CLIP = (0.70, 1.40)
P1_MIN_SAMPLES = 20
# P1 正则化：样本数收缩参数
K_SHRINKAGE = 200
# P1 因子上限（按小时）
FACTOR_MAX_PER_HOUR = {
    6: 1.20, 7: 1.30, 16: 1.30, 17: 1.30, 18: 1.20, 19: 1.20
}


def apply_p0(df):
    df = df.copy()
    ghi = pd.to_numeric(df["g_blend_pred"], errors="coerce").fillna(0).to_numpy()
    base = pd.to_numeric(df["pred_baseline"], errors="coerce").fillna(0).to_numpy()
    v152 = pd.to_numeric(df["power_pred"], errors="coerce").fillna(0).to_numpy()
    cap = pd.to_numeric(df["capacity_mw"], errors="coerce").fillna(1).to_numpy()
    delta = v152 - base
    atten = np.where(ghi > GHI_CLEAR, 0.0, np.where(ghi > GHI_MED, 0.5, 1.0))
    df["power_pred_p0"] = np.clip(base + atten * delta, 0.0, cap)
    print(f"[P0] 晴空: 晴空={(ghi>GHI_CLEAR).sum():,}  中等={((ghi>GHI_MED)&(ghi<=GHI_CLEAR)).sum():,}  低辐照={(ghi<=GHI_MED).sum():,}")
    return df


def fit_p1(df, valid_mask):
    df = df.copy()
    df["_ghi_bin"] = pd.cut(
        pd.to_numeric(df["g_blend_pred"], errors="coerce").fillna(0),
        bins=GHI_BINS, labels=False, include_lowest=True).astype(int)
    df["_month"] = pd.to_numeric(
        pd.to_datetime(df["time"]).dt.month, errors="coerce").astype("Int64")

    vdf = df[valid_mask & df["power_mw"].notna() & (df["power_mw"] > 0)].copy()
    if len(vdf) == 0:
        return None, None, None

    # ── 全局因子（用于样本数收缩）──────────────────────────────────────
    all_actual = float(vdf["power_mw"].sum())
    all_p0 = float(vdf["power_pred_p0"].sum())
    global_factor = float(np.clip(all_actual / max(all_p0, 0.5), *FACTOR_CLIP))
    print(f"  [P1改进] 全局因子 (用于收缩): {global_factor:.4f}, valid样本: {len(vdf):,}")

    # ── 月份邻域中位数（用于平滑）──────────────────────────────────────
    # 先构建原始因子表
    raw_rows = []
    for (gb, mo), g in vdf.groupby(["_ghi_bin", "_month"]):
        actual = g["power_mw"].sum()
        p0_sum = g["power_pred_p0"].sum()
        n = len(g)
        passed = n >= P1_MIN_SAMPLES
        if p0_sum < 0.5:
            factor = 1.0
        elif not passed:
            factor = np.nan
        else:
            factor = float(np.clip(actual / p0_sum, *FACTOR_CLIP))
        raw_rows.append({"ghi_bin": int(gb), "month": int(mo), "n_samples": int(n),
                         "p0_sum": float(p0_sum), "actual_sum": float(actual),
                         "raw_factor": round(factor, 4) if np.isfinite(factor) else np.nan,
                         "passed_threshold": passed, "has_data": True})
    fdf = pd.DataFrame(raw_rows)

    # 月份邻域平滑：按 (ghi_bin, month_neighbor) 计算中位数
    def month_neighbor_median(fdf_in, gb, mo_target):
        """取 mo-1, mo, mo+1 的中位数"""
        neighbors = [mo_target - 1, mo_target, mo_target + 1]
        candidates = fdf_in[
            (fdf_in["ghi_bin"] == gb) &
            (fdf_in["month"].isin(neighbors)) &
            (fdf_in["passed_threshold"])
        ]["raw_factor"]
        if len(candidates) == 0:
            return np.nan
        return float(np.nanmedian(candidates))

    # ghi_bin 级中位数（全局 fallback）
    ghi_median = fdf[fdf["passed_threshold"]].groupby("ghi_bin")["raw_factor"].median().to_dict()
    for gb in range(len(GHI_BINS) - 1):
        if gb not in ghi_median:
            ghi_median[gb] = global_factor

    # ── 最终因子计算（样本数收缩 + 月份邻域平滑 + 小时上限）────────────
    final_rows = []
    for _, r in fdf.iterrows():
        gb = int(r["ghi_bin"])
        mo = int(r["month"])
        n = r["n_samples"]

        if not r["has_data"]:
            final_factor = ghi_median.get(gb, global_factor)
            fallback_reason = "no_data"
        elif not r["passed_threshold"]:
            # 低样本：用月份邻域中位数 + 收缩
            neighbor_med = month_neighbor_median(fdf, gb, mo)
            if np.isfinite(neighbor_med):
                # 收缩
                raw_factor_for_shrink = neighbor_med
                w = n / (n + K_SHRINKAGE)
                final_factor = w * raw_factor_for_shrink + (1 - w) * global_factor
                fallback_reason = "low_samples_month_neighbor_shrink"
            else:
                final_factor = ghi_median.get(gb, global_factor)
                fallback_reason = "low_samples_ghi_median"
        else:
            # 充足样本：直接收缩
            raw = r["raw_factor"]
            w = n / (n + K_SHRINKAGE)
            final_factor = w * raw + (1 - w) * global_factor
            fallback_reason = "full_shrinkage"

        # 小时上限
        # 注：因子在城市聚合层面应用，这里仅记录，apply 时按测试集 hour 应用
        final_rows.append({
            "ghi_bin": gb, "month": mo,
            "n_samples": n,
            "raw_factor": r["raw_factor"],
            "final_factor": round(final_factor, 4),
            "fallback_reason": fallback_reason
        })

    fdf_out = pd.DataFrame(final_rows)

    print(f"  [P1改进] 通过阈值: {fdf_out['passed_threshold'].sum() if 'passed_threshold' in fdf_out.columns else 'N/A'}")
    print(f"  [P1改进] 各 fallback 原因分布:")
    print(fdf_out["fallback_reason"].value_counts().to_string().replace("^", "    "))

    # 构建 lookup
    lookup_exact = {(int(r["ghi_bin"]), int(r["month"])): float(r["final_factor"])
                    for _, r in fdf_out.iterrows()}
    return lookup_exact, ghi_median, fdf_out


def get_p1_vectorized(df, lookup_exact, median_by_ghi):
    if lookup_exact is None:
        return pd.Series(1.0, index=df.index)
    factors = pd.Series(1.0, index=df.index)
    for (gb, mo), fac in lookup_exact.items():
        factors[(df["_ghi_bin"] == gb) & (df["_month"] == mo)] = fac
    for gb, fac in median_by_ghi.items():
        mask = (factors == 1.0) & (df["_ghi_bin"] == gb)
        factors[mask] = fac
    return factors


def compute_metrics_v2(df, test_mask, lookup_exact, median_by_ghi):
    test = df[test_mask].copy()
    test["_ghi_bin"] = pd.cut(
        pd.to_numeric(test["g_blend_pred"], errors="coerce").fillna(0),
        bins=GHI_BINS, labels=False, include_lowest=True).astype(int)
    test["_month"] = pd.to_numeric(
        pd.to_datetime(test["time"]).dt.month, errors="coerce").astype("Int64")
    factors = get_p1_vectorized(test, lookup_exact, median_by_ghi)
    cap_arr = pd.to_numeric(test["capacity_mw"], errors="coerce").fillna(1).to_numpy()
    test["_pred_p1"] = np.clip(test["power_pred_p0"].to_numpy() * factors.to_numpy(), 0, cap_arr)
    pos = test[test["power_mw"].notna() & (test["power_mw"] > 0)]
    site_mape = np.mean(np.abs(pos["power_mw"] - pos["power_pred_p0"]) / pos["power_mw"]) * 100
    site_bias = (pos["power_pred_p0"].sum() - pos["power_mw"].sum()) / pos["power_mw"].sum() * 100
    print(f"\n  站点级 (P0): MAPE={site_mape:.1f}%, bias={site_bias:+.1f}%")
    city = pos.groupby("time").agg(actual=("power_mw","sum"), p0=("power_pred_p0","sum"),
                                    p1=("_pred_p1","sum")).reset_index()
    city = city[city["actual"] > 0]
    m_p0 = np.mean(np.abs(city["actual"] - city["p0"]) / city["actual"]) * 100
    m_p1 = np.mean(np.abs(city["actual"] - city["p1"]) / city["actual"]) * 100
    b_p0 = (city["p0"].sum() - city["actual"].sum()) / city["actual"].sum() * 100
    b_p1 = (city["p1"].sum() - city["actual"].sum()) / city["actual"].sum() * 100
    mae_p1 = np.mean(np.abs(city["actual"] - city["p1"]))
    print(f"  城市级 (P0):   MAPE={m_p0:.1f}%, bias={b_p0:+.1f}%")
    print(f"  城市级 (P0+P1): MAPE={m_p1:.1f}%, bias={b_p1:+.1f}%, MAE={mae_p1:.2f}MW")
    return {"site_mape": site_mape, "site_bias": site_bias,
            "city_mape_p0": m_p0, "city_bias_p0": b_p0,
            "city_mape_p1": m_p1, "city_bias_p1": b_p1, "city_mae_p1": mae_p1}


def hourly_city_comparison(df, test_mask, lookup_exact, median_by_ghi):
    test = df[test_mask].copy()
    test["_ghi_bin"] = pd.cut(pd.to_numeric(test["g_blend_pred"], errors="coerce").fillna(0),
        bins=GHI_BINS, labels=False, include_lowest=True).astype(int)
    test["_month"] = pd.to_numeric(pd.to_datetime(test["time"]).dt.month, errors="coerce").astype("Int64")
    factors = get_p1_vectorized(test, lookup_exact, median_by_ghi)
    cap_arr = pd.to_numeric(test["capacity_mw"], errors="coerce").fillna(1).to_numpy()
    test["_pred_p1"] = np.clip(test["power_pred_p0"].to_numpy() * factors.to_numpy(), 0, cap_arr)
    test["hour"] = pd.to_datetime(test["time"]).dt.hour
    pos = test[test["power_mw"].notna() & (test["power_mw"] > 0)]
    print("\n逐小时城市 MAPE:")
    print(f"  {'时':>4} | {'v1.5.8':>8} | {'P0':>8} | {'P0+P1':>8} | {'改善':>6}")
    print("  " + "-" * 45)
    for h in range(6, 20):
        sub = pos[pos["hour"] == h]
        if not len(sub): continue
        city = sub.groupby("time").agg(actual=("power_mw","sum"), p158=("power_pred","sum"),
                                        p0=("power_pred_p0","sum"), p1=("_pred_p1","sum")).reset_index()
        city = city[city["actual"] > 0]
        if not len(city): continue
        m158 = np.mean(np.abs(city["actual"] - city["p158"]) / city["actual"]) * 100
        m0 = np.mean(np.abs(city["actual"] - city["p0"]) / city["actual"]) * 100
        m1 = np.mean(np.abs(city["actual"] - city["p1"]) / city["actual"]) * 100
        best, imp = min(m158, m0, m1), m158 - min(m158, m0, m1)
        print(f"  {h:02d}时 | {m158:>8.1f} | {m0:>8.1f} | {m1:>8.1f} | {imp:>+6.1f}")


def monthly_bias(df, test_mask, lookup_exact, median_by_ghi):
    test = df[test_mask].copy()
    test["_ghi_bin"] = pd.cut(pd.to_numeric(test["g_blend_pred"], errors="coerce").fillna(0),
        bins=GHI_BINS, labels=False, include_lowest=True).astype(int)
    test["_month"] = pd.to_numeric(pd.to_datetime(test["time"]).dt.month, errors="coerce").astype("Int64")
    factors = get_p1_vectorized(test, lookup_exact, median_by_ghi)
    cap_arr = pd.to_numeric(test["capacity_mw"], errors="coerce").fillna(1).to_numpy()
    test["_pred_p1"] = np.clip(test["power_pred_p0"].to_numpy() * factors.to_numpy(), 0, cap_arr)
    pos = test[test["power_mw"].notna() & (test["power_mw"] > 0)]
    print("\n逐月系统性偏差:")
    print(f"  {'月份':>8} | {'v1.5.8':>8} | {'P0':>8} | {'P0+P1':>8}")
    print("  " + "-" * 38)
    for mo in range(7, 13):
        sub = pos[pos["_month"] == mo]
        if not len(sub): continue
        city = sub.groupby("time").agg(actual=("power_mw","sum"), p158=("power_pred","sum"),
                                        p0=("power_pred_p0","sum"), p1=("_pred_p1","sum")).reset_index()
        city = city[city["actual"] > 0]
        if not len(city): continue
        b158 = (city["p158"].sum() - city["actual"].sum()) / city["actual"].sum() * 100
        b0 = (city["p0"].sum() - city["actual"].sum()) / city["actual"].sum() * 100
        b1 = (city["p1"].sum() - city["actual"].sum()) / city["actual"].sum() * 100
        print(f"  2025-{mo:02d} | {b158:>+7.1f}% | {b0:>+7.1f}% | {b1:>+7.1f}%")


def generate_hourly_csv(df, test_mask, lookup_exact, median_by_ghi):
    test = df[test_mask].copy()
    test["_ghi_bin"] = pd.cut(pd.to_numeric(test["g_blend_pred"], errors="coerce").fillna(0),
        bins=GHI_BINS, labels=False, include_lowest=True).astype(int)
    test["_month"] = pd.to_numeric(pd.to_datetime(test["time"]).dt.month, errors="coerce").astype("Int64")
    factors = get_p1_vectorized(test, lookup_exact, median_by_ghi)
    cap_arr = pd.to_numeric(test["capacity_mw"], errors="coerce").fillna(1).to_numpy()
    test["_pred_p1"] = np.clip(test["power_pred_p0"].to_numpy() * factors.to_numpy(), 0, cap_arr)
    test["date"] = pd.to_datetime(test["time"]).dt.date
    test["hour"] = pd.to_datetime(test["time"]).dt.hour
    sm = pd.read_csv(PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "site_master.csv")
    site_info = sm[["site_id", "site_short_name", "county"]].drop_duplicates("site_id")
    city_agg = test[test["power_mw"] > 0].groupby(["date", "hour"]).agg(
        city_actual=("power_mw","sum"), city_p0=("power_pred_p0","sum"), city_p1=("_pred_p1","sum")).reset_index()
    city_scale = city_agg.groupby("hour")["city_actual"].agg(lambda x: x.max() - x.min())

    def mape_fn(y, p):
        m = (y > 0) & np.isfinite(y) & np.isfinite(p)
        return float(np.mean(np.abs(y[m] - p[m]) / y[m]) * 100) if m.any() else np.nan

    def nrmse_fn(y, p, scale):
        m = np.isfinite(y) & np.isfinite(p)
        if not m.any() or not np.isfinite(scale) or scale == 0: return np.nan
        return np.sqrt(np.mean((y[m] - p[m]) ** 2)) / scale

    rows_site = []
    for (sid, h), g in test.groupby(["site_id", "hour"]):
        yt = g["power_mw"].values; yp = g["power_pred_p0"].values
        rows_site.append({"level": "site_hourly", "site_id": sid, "hour": int(h), "n_samples": len(g),
                          "NRMSE": nrmse_fn(yt, yp, yt.max()-yt.min()) if len(g) > 1 else np.nan,
                          "MAPE(%)": mape_fn(yt, yp)})
    site_hourly = pd.DataFrame(rows_site).merge(site_info, on="site_id", how="left")
    site_hourly["date"] = pd.NA; site_hourly["site_short_name"] = site_hourly.get("site_short_name", pd.NA)
    site_hourly["county"] = site_hourly.get("county", pd.NA)

    rows_city = []
    for (date, hour), g in test.groupby(["date", "hour"]):
        scale = city_scale.get(hour, np.nan)
        yt = g["power_mw"].values; yp0 = g["power_pred_p0"].values; yp1 = g["_pred_p1"].values
        for label, yp_arr, lname in [("P0", yp0, "city_hourly_P0"), ("P0+P1", yp1, "city_hourly_P0P1")]:
            rows_city.append({"level": lname, "site_id": "city", "hour": int(hour), "n_samples": g["site_id"].nunique(),
                             "NRMSE": nrmse_fn(yt, yp_arr, scale),
                             "MAPE(%)": mape_fn(yt, yp_arr),
                             "date": date, "site_short_name": "全市", "county": pd.NA})
    city_hourly = pd.DataFrame(rows_city).sort_values(["date", "hour"]).reset_index(drop=True)
    cols = ["level", "site_id", "site_short_name", "county", "date", "hour", "n_samples", "NRMSE", "MAPE(%)"]
    combined = pd.concat([site_hourly[cols], city_hourly[cols]], ignore_index=True).sort_values(
        ["level", "site_id", "hour", "date"]).reset_index(drop=True)
    combined["n_samples"] = combined["n_samples"].astype(int)
    out = METRICS_PATH / "v159_fix_逐小时NRMSE_MAPE.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\nCSV已保存: {out}")
    return combined


def main():
    print("=" * 60 + "\nv1.5.9 Fix v3: P0+P1 分层应用 + P1稀疏性报告\n" + "=" * 60)
    from pv_forecasting.core.split import add_standard_split

    print(f"\n读取: {PRED_PATH}")
    pred = pd.read_pickle(PRED_PATH)
    pred["time"] = pd.to_datetime(pred["time"])
    print(f"总行: {len(pred):,}")
    pred["year"] = pred["time"].dt.year
    pred["month"] = pred["time"].dt.month
    BAD = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}

    pred = add_standard_split(pred)
    valid_mask = (pred["split"] == "valid") & ~pred["site_id"].isin(BAD)
    test_mask = (pred["split"] == "test") & ~pred["site_id"].isin(BAD)
    print(f"验证集 (split==valid, 2025-07~08): {valid_mask.sum():,} 行")
    print(f"测试集 (split==test, 2025-09+): {test_mask.sum():,} 行")

    print("\n" + "─" * 40 + "\n基准 v1.5.8 (测试集)")
    pos = pred[test_mask & pred["power_mw"].notna() & (pred["power_mw"] > 0)]
    m158 = np.mean(np.abs(pos["power_mw"] - pos["power_pred"]) / pos["power_mw"]) * 100
    b158 = (pos["power_pred"].sum() - pos["power_mw"].sum()) / pos["power_mw"].sum() * 100
    print(f"  站点级: MAPE={m158:.1f}%, bias={b158:+.1f}%")

    print("\n" + "─" * 40 + "\nP0: 晴空保护")
    df = apply_p0(pred)
    pos0 = df[test_mask & df["power_mw"].notna() & (df["power_mw"] > 0)]
    m0s = np.mean(np.abs(pos0["power_mw"] - pos0["power_pred_p0"]) / pos0["power_mw"]) * 100
    b0s = (pos0["power_pred_p0"].sum() - pos0["power_mw"].sum()) / pos0["power_mw"].sum() * 100
    print(f"  站点级: MAPE={m0s:.1f}%, bias={b0s:+.1f}%")

    print("\n" + "─" * 40 + "\nP1: GHI×月份 因子 (城市聚合层面)")
    lookup_exact, median_by_ghi, sparsity_df = fit_p1(df, valid_mask)
    sparsity_out = METRICS_PATH / "p1_factor_sparsity.csv"
    sparsity_out.parent.mkdir(parents=True, exist_ok=True)
    sparsity_df.to_csv(sparsity_out, index=False, encoding="utf-8-sig")
    print(f"\nP1稀疏性报告: {sparsity_out}")

    print("\n" + "─" * 40 + "\n分层评估")
    compute_metrics_v2(df, test_mask, lookup_exact, median_by_ghi)
    hourly_city_comparison(df, test_mask, lookup_exact, median_by_ghi)
    monthly_bias(df, test_mask, lookup_exact, median_by_ghi)

    pred["power_pred"] = df["power_pred_p0"]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    pred.to_pickle(OUTPUT_PATH)
    print(f"\nP0站点预测已保存: {OUTPUT_PATH}")
    generate_hourly_csv(df, test_mask, lookup_exact, median_by_ghi)


if __name__ == "__main__":
    main()
