#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Before/After 对比报告
比较原始基准 vs v2 修正后的关键指标
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
import functools as _functools

_pd_patched = False
def _ensure_patch():
    global _pd_patched
    if _pd_patched: return
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
    yp = float(np.nansum(p[m]))
    return float(np.abs(yp - yt) / yt * 100)


def site_rel_err(y, p):
    m = (y > 0) & np.isfinite(y) & np.isfinite(p)
    if not m.any(): return np.nan
    return float(np.abs(y[m] - p[m]).sum() / y[m].sum() * 100)


def load_and_filter(path, label):
    df = pd.read_pickle(path)
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    df["date"] = df["time"].dt.date
    t = df[(df["split"] == "test") & (~df["site_id"].isin(BAD_SITES)) &
           (df["hour"].isin(HOURS)) & (df["power_mw"] > 0)].copy()
    print(f"  [{label}] {len(t):,} 行, {t['site_id'].nunique()} 站点, {t['date'].nunique()} 天")
    return t


def compute_hourly(test_df):
    rows = []
    for h in HOURS:
        sub = test_df[test_df["hour"] == h]
        if len(sub) == 0:
            continue
        yt = sub["power_mw"].values.astype(float)
        yp = sub["power_pred"].values.astype(float)

        site_rels = [site_rel_err(sg["power_mw"].values, sg["power_pred"].values)
                     for _, sg in sub.groupby("site_id")]
        site_rels = np.array([r for r in site_rels if np.isfinite(r)])

        rows.append({
            "hour": int(h),
            "n": int(sub["site_id"].nunique()),
            "site_mape_raw_mean": float(np.nanmean(site_rels)),
            "site_mape_raw_median": float(np.nanmedian(site_rels)),
            "site_mape_raw_p90": float(np.nanpercentile(site_rels, 90)),
            "site_mape_clipped": clipped_mape(yt, yp),
            "site_wape": wape(yt, yp),
            "city_rel_err": city_rel_err(yt, yp),
            "n_gt100": int((site_rels > 100).sum()),
            "n_gt200": int((site_rels > 200).sum()),
            "city_actual_mw": float(sub["power_mw"].sum() / sub["date"].nunique()),
            "city_pred_mw": float(sub["power_pred"].sum() / sub["date"].nunique()),
            "bias_pct": float((sub["power_pred"].sum() - sub["power_mw"].sum()) /
                               max(sub["power_mw"].sum(), 1) * 100),
        })
    return pd.DataFrame(rows)


def compute_global(test_df):
    yt = test_df["power_mw"].values.astype(float)
    yp = test_df["power_pred"].values.astype(float)
    return {
        "global_wape": wape(yt, yp),
        "global_clipped_mape": clipped_mape(yt, yp),
        "global_raw_mape": raw_mape(yt, yp),
        "global_city_rel_err": city_rel_err(yt, yp),
        "total_sites": int(test_df["site_id"].nunique()),
        "total_dates": int(test_df["date"].nunique()),
        "total_samples": len(test_df),
    }


def main():
    print("=" * 70)
    print("逐小时误差修复 — Before / After 对比报告")
    print("=" * 70)

    # 加载
    print("\n加载预测表 …")
    df_before = load_and_filter(TABLES / "distributed_predictions_fixed_full.pkl", "修复前")
    df_after = load_and_filter(TABLES / "distributed_predictions_fixed_full_v2.pkl", "修复后")

    # 全局
    print("\n全局指标:")
    gb = compute_global(df_before)
    ga = compute_global(df_after)
    print(f"  {'指标':<25} | {'修复前':>10} | {'修复后':>10} | {'变化':>10}")
    print(f"  {'-'*60}")
    for key in ["global_wape", "global_clipped_mape", "global_raw_mape", "global_city_rel_err"]:
        v_b = gb[key]
        v_a = ga[key]
        delta = v_a - v_b
        arrow = "↓" if (key != "global_city_rel_err" and delta < 0) else \
                ("↓" if (key == "global_city_rel_err" and delta < 0) else "↑")
        print(f"  {key:<25} | {v_b:>10.1f}% | {v_a:>10.1f}% | {arrow}{abs(delta):>8.1f}%")

    # 逐小时对比
    print("\n逐小时对比:")
    hb = compute_hourly(df_before).rename(columns={
        c: f"{c}_before" for c in compute_hourly(df_before).columns if c != "hour"
    })
    ha = compute_hourly(df_after).rename(columns={
        c: f"{c}_after" for c in compute_hourly(df_after).columns if c != "hour"
    })
    merged = hb.merge(ha, on="hour")

    def delta_col(c):
        return f"delta_{c.replace('_after','')}"

    cols_to_show = [
        ("site_mape_raw_mean", "site_raw_mean"),
        ("site_mape_raw_median", "site_raw_median"),
        ("site_mape_clipped", "clip_mape"),
        ("site_wape", "WAPE"),
        ("city_rel_err", "city_rel_err"),
        ("n_gt100", ">100%站点"),
        ("n_gt200", ">200%站点"),
    ]

    print(f"\n  {'h':>3} | {'站点raw均值':>10} {'→':>4} | {'clipped_mape':>10} {'→':>4} | {'WAPE':>7} {'→':>4} | {'city_rel':>9} {'→':>4} | {'>100':>5} | {'>200':>5}")
    print(f"  {'-'*80}")
    for _, r in merged.iterrows():
        h = int(r["hour"])
        m_b, m_a = r["site_mape_raw_mean_before"], r["site_mape_raw_mean_after"]
        cl_b, cl_a = r["site_mape_clipped_before"], r["site_mape_clipped_after"]
        w_b, w_a = r["site_wape_before"], r["site_wape_after"]
        cr_b, cr_a = r["city_rel_err_before"], r["city_rel_err_after"]
        n100_b, n100_a = int(r["n_gt100_before"]), int(r["n_gt100_after"])
        n200_b, n200_a = int(r["n_gt200_before"]), int(r["n_gt200_after"])

        m_arrow = "↓" if m_a < m_b else ("-" if m_a == m_b else "↑")
        cl_arrow = "↓" if cl_a < cl_b else ("-" if cl_a == cl_b else "↑")
        w_arrow = "↓" if w_a < w_b else ("-" if w_a == w_b else "↑")
        cr_arrow = "↓" if cr_a < cr_b else ("-" if cr_a == cr_b else "↑")
        n100_s = f"{n100_b}→{n100_a}"
        n200_s = f"{n200_b}→{n200_a}"

        marker = " ★" if h in DAWN_DUSK else ""
        print(f"  {h:3d}{marker} | {m_b:>7.1f}{m_arrow:>4} | {cl_b:>7.1f}{cl_arrow:>4} | "
              f"{w_b:>4.1f}{w_arrow:>4} | {cr_b:>6.1f}{cr_arrow:>4} | {n100_s:>5} | {n200_s:>5}")

    # 保存详细对比 CSV
    csv_rows = []
    for _, r in merged.iterrows():
        h = int(r["hour"])
        for metric, label in cols_to_show:
            b = r.get(f"{metric}_before", np.nan)
            a = r.get(f"{metric}_after", np.nan)
            csv_rows.append({
                "hour": h,
                "metric": label,
                "before": round(float(b), 2) if np.isfinite(b) else np.nan,
                "after": round(float(a), 2) if np.isfinite(a) else np.nan,
                "delta": round(float(a - b), 2) if np.isfinite(b) and np.isfinite(a) else np.nan,
            })
    comp_df = pd.DataFrame(csv_rows)
    comp_df.to_csv(METRICS / "before_after_comparison.csv", index=False, encoding="utf-8-sig")
    print(f"\n  详细对比已保存: {METRICS / 'before_after_comparison.csv'}")

    # 关键指标达标检查
    print("\n" + "=" * 70)
    print("验收标准检查")
    print("=" * 70)
    target_map = {6: ("6点 city_rel_err", 92.13, 80.0),
                  7: ("7点 city_rel_err", 68.09, 55.0),
                  17: ("17点 city_rel_err", 67.96, 55.0),
                  18: ("18点 city_rel_err", 83.87, 70.0),
                  19: ("19点 city_rel_err", 89.49, 80.0)}

    m = merged.set_index("hour")
    n200_before_total = int(m.loc[6:19, "n_gt200_before"].sum())
    n200_after_total = int(m.loc[6:19, "n_gt200_after"].sum())

    print(f"\n  {'目标':<25} | {'修复前':>10} | {'修复后':>10} | {'目标':>10} | {'达标':>6}")
    print(f"  {'-'*65}")
    for h, (name, before_val, target) in target_map.items():
        if h in m.index:
            after_val = float(m.loc[h, "city_rel_err_after"])
            before_val_from_csv = float(m.loc[h, "city_rel_err_before"])
            ok = "✓" if after_val < target else "✗"
            print(f"  {name:<25} | {before_val_from_csv:>10.1f}% | {after_val:>10.1f}% | "
                  f"<{target:>9.1f}% | {ok:>6}")
        else:
            print(f"  {name:<25} | {'N/A':>10} | {'N/A':>10} | <{target:>9.1f}% | ✗")

    print(f"\n  {'>200%站点总数(6-19h)':<25} | {n200_before_total:>10d} | {n200_after_total:>10d} | "
          f"减少30%: {int(n200_before_total*0.7):>10d} | "
          f"{'✓' if n200_after_total <= int(n200_before_total*0.7) else '✗'}")

    # 全局 WAPE 不恶化
    gw_before = gb["global_wape"]
    gw_after = ga["global_wape"]
    gw_ok = gw_after <= gw_before * 1.01
    print(f"  {'全局WAPE不恶化':<25} | {gw_before:>10.1f}% | {gw_after:>10.1f}% | "
          f"<={gw_before*1.01:>9.1f}% | {'✓' if gw_ok else '✗'}")

    # 全局 clipped MAPE
    gcl_before = gb["global_clipped_mape"]
    gcl_after = ga["global_clipped_mape"]
    gcl_ok = gcl_after <= gcl_before * 1.01
    print(f"  {'全局clipped不恶化':<25} | {gcl_before:>10.1f}% | {gcl_after:>10.1f}% | "
          f"<={gcl_before*1.01:>9.1f}% | {'✓' if gcl_ok else '✗'}")

    # 中午 10-14 点 WAPE 不恶化超过 1%
    mw_b = float(m.loc[[10,11,12,13,14], "site_wape_before"].mean())
    mw_a = float(m.loc[[10,11,12,13,14], "site_wape_after"].mean())
    mw_ok = mw_a <= mw_b * 1.01
    print(f"  {'中午(10-14)WAPE不恶化1%':<25} | {mw_b:>10.1f}% | {mw_a:>10.1f}% | "
          f"<={mw_b*1.01:>9.1f}% | {'✓' if mw_ok else '✗'}")

    print("\n" + "=" * 70)
    print("修复总结")
    print("=" * 70)
    dawn_before = float(m[m["hour"].isin([6,7])]["city_rel_err_before"].mean())
    dawn_after = float(m[m["hour"].isin([6,7])]["city_rel_err_after"].mean())
    dusk_before = float(m[m["hour"].isin([17,18,19])]["city_rel_err_before"].mean())
    dusk_after = float(m[m["hour"].isin([17,18,19])]["city_rel_err_after"].mean())

    print(f"\n  【早间 h=6-7】")
    print(f"    city_rel_err: {dawn_before:.1f}% → {dawn_after:.1f}%  (Δ {dawn_after-dawn_before:+.1f}%)")
    print(f"  【晚间 h=17-19】")
    print(f"    city_rel_err: {dusk_before:.1f}% → {dusk_after:.1f}%  (Δ {dusk_after-dusk_before:+.1f}%)")
    print(f"  【全天 h=6-19】")
    all_b = float(m["city_rel_err_before"].mean())
    all_a = float(m["city_rel_err_after"].mean())
    print(f"    city_rel_err: {all_b:.1f}% → {all_a:.1f}%  (Δ {all_a-all_b:+.1f}%)")
    print(f"    WAPE: {gb['global_wape']:.1f}% → {ga['global_wape']:.1f}%  (Δ {ga['global_wape']-gb['global_wape']:+.1f}%)")
    print(f"    clipped MAPE: {gb['global_clipped_mape']:.1f}% → {ga['global_clipped_mape']:.1f}%  "
          f"(Δ {ga['global_clipped_mape']-gb['global_clipped_mape']:+.1f}%)")
    print(f"  【>200%站点数】: {n200_before_total} → {n200_after_total}  "
          f"(减少 {n200_before_total-n200_after_total}, {n200_before_total>0 and (n200_before_total-n200_after_total)/n200_before_total*100:.0f}%)")

    print("\nDone.")


if __name__ == "__main__":
    main()
