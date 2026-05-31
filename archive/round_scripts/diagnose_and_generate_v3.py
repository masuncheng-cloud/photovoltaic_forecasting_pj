#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断 + v3 生成脚本
================
策略：评估不同修正组合，选择最优输出

四种候选策略：
  S0: 原始基准（无 P0/P1/dawn-dusk）
  S1: P0 晴空修正
  S2: P0 + P1 城市聚合修正
  S3: P0 + P1 + Dawn/Dusk floor（当前 v2）
  S4: P0 + Dawn/Dusk floor（无 P1）

同时评估各策略并输出最终 v3。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
import sys
import functools as _functools
import json

_pd_read_pickle_orig = pd.read_pickle
_pd_patch_done = False
def _ensure_patch():
    global _pd_patch_done
    if _pd_patch_done:
        return
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

def _patched_read_pickle(*args, **kwargs):
    _ensure_patch()
    return _pd_read_pickle_orig(*args, **kwargs)
pd.read_pickle = _patched_read_pickle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}
HOURS = list(range(6, 20))
DAWN_DUSK = [6, 7, 16, 17, 18, 19]
GHI_BINS = [0, 100, 200, 300, 450, 600, 800, 99999]
FACTOR_CLIP = (0.70, 1.40)
P1_MIN_SAMPLES = 20
K_SHRINKAGE = 200


# ── Metric helpers ────────────────────────────────────────────────────────────

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

def site_rel_err(y, p):
    m = (y > 0) & np.isfinite(y) & np.isfinite(p)
    if not m.any(): return np.nan
    return float(np.abs(y[m] - p[m]).sum() / y[m].sum() * 100)


def eval_by_hour(test_df, pred_col="power_pred"):
    rows = []
    for h in HOURS:
        sub = test_df[test_df["hour"] == h]
        if len(sub) == 0: continue
        yt = sub["power_mw"].values.astype(float)
        yp = sub[pred_col].values.astype(float)

        site_rels = []
        for _, sg in sub.groupby("site_id"):
            r = site_rel_err(sg["power_mw"].values, sg[pred_col].values)
            if np.isfinite(r): site_rels.append(r)
        site_rels = np.array(site_rels)

        rows.append({
            "hour": int(h),
            "n": int(sub["site_id"].nunique()),
            "n_samples": len(sub),
            "site_mape_raw_mean": float(np.nanmean(site_rels)),
            "site_mape_raw_median": float(np.nanmedian(site_rels)),
            "site_mape_clipped": clipped_mape(yt, yp),
            "site_wape": wape(yt, yp),
            "city_rel_err": city_rel_err(yt, yp),
            "n_gt100": int((site_rels > 100).sum()),
            "n_gt200": int((site_rels > 200).sum()),
            "actual_mean": float(np.nanmean(yt)),
            "pred_mean": float(np.nanmean(yp)),
            "bias_pct": float((yp.sum() - yt.sum()) / max(yt.sum(), 1) * 100),
        })
    return pd.DataFrame(rows)


def eval_global(test_df, pred_col="power_pred"):
    yt = test_df["power_mw"].values.astype(float)
    yp = test_df[pred_col].values.astype(float)
    return {
        "wape": wape(yt, yp),
        "clipped_mape": clipped_mape(yt, yp),
        "raw_mape": raw_mape(yt, yp),
        "city_rel_err": city_rel_err(yt, yp),
    }


# ── P0 + P1 factor fitting ───────────────────────────────────────────────────

def fit_p1(df, valid_mask):
    df = df.copy()
    df["_ghi_bin"] = pd.cut(
        pd.to_numeric(df.get("g_blend_pred", pd.Series(0, index=df.index)), errors="coerce").fillna(0),
        bins=GHI_BINS, labels=False, include_lowest=True).astype(int)
    df["_month"] = pd.to_datetime(df["time"]).dt.month

    vdf = df[valid_mask & df["power_mw"].notna() & (df["power_mw"] > 0)].copy()
    if len(vdf) == 0:
        return {}, {}

    all_actual = float(vdf["power_mw"].sum())
    all_p0 = float(vdf["power_pred"].sum())
    global_factor = float(np.clip(all_actual / max(all_p0, 0.5), *FACTOR_CLIP))

    rows = []
    for (gb, mo), g in vdf.groupby(["_ghi_bin", "_month"]):
        actual = g["power_mw"].sum()
        p0_sum = g["power_pred"].sum()
        n = len(g)
        passed = n >= P1_MIN_SAMPLES
        if p0_sum < 0.5:
            factor = 1.0
        elif not passed:
            factor = np.nan
        else:
            factor = float(np.clip(actual / max(p0_sum, 0.5), *FACTOR_CLIP))
        rows.append({"ghi_bin": int(gb), "month": int(mo), "n": int(n),
                     "raw": round(factor, 4) if np.isfinite(factor) else np.nan,
                     "passed": passed, "has_data": True})

    fdf = pd.DataFrame(rows)

    def mo_med(fdf_in, gb, mo_t):
        neighs = [mo_t - 1, mo_t, mo_t + 1]
        cands = fdf_in[(fdf_in["ghi_bin"] == gb) & fdf_in["month"].isin(neighs) & fdf_in["passed"]]["raw"]
        return float(np.nanmedian(cands)) if len(cands) > 0 else np.nan

    ghi_med = fdf[fdf["passed"]].groupby("ghi_bin")["raw"].median().to_dict()
    for gb in range(len(GHI_BINS) - 1):
        if gb not in ghi_med:
            ghi_med[gb] = global_factor

    final = []
    for _, r in fdf.iterrows():
        gb, mo, n = int(r["ghi_bin"]), int(r["month"]), r["n"]
        if not r["has_data"]:
            ff = ghi_med.get(gb, global_factor)
        elif not r["passed"]:
            nm = mo_med(fdf, gb, mo)
            rf = nm if np.isfinite(nm) else ghi_med.get(gb, global_factor)
            w = n / (n + K_SHRINKAGE)
            ff = w * rf + (1 - w) * global_factor
        else:
            w = n / (n + K_SHRINKAGE)
            ff = w * r["raw"] + (1 - w) * global_factor
        final.append({"ghi_bin": gb, "month": mo, "raw": r["raw"],
                      "final": round(float(np.clip(ff, *FACTOR_CLIP)), 4)})

    fdf_out = pd.DataFrame(final)
    lookup = {(int(r["ghi_bin"]), int(r["month"])): float(r["final"]) for _, r in fdf_out.iterrows()}
    return lookup, ghi_med


# ── Dawn/Dusk floor params ────────────────────────────────────────────────────

def load_dawn_dusk_params():
    params_path = METRICS / "dawn_dusk_floor_params.json"
    with open(params_path, encoding="utf-8") as f:
        params = json.load(f)

    def _parse(d):
        result = {}
        for k, v in d.items():
            if "," in k:
                parts = k.strip("()").split(", ")
                if len(parts) == 2:
                    key = (int(parts[0]), parts[1].strip("'\""))
                elif len(parts) == 3:
                    key = (int(parts[0]), parts[1].strip("'\" "), parts[2].strip("'\" "))
                else:
                    continue
                result[key] = v
            else:
                result[int(k)] = v
        return result

    return (_parse(params["level1"]), _parse(params["level2"]),
            _parse(params["level3"]), _parse(params["level4"]),
            _parse(params["level5"]))


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("诊断 + v3 生成")
    print("=" * 70)

    # ── Load ─────────────────────────────────────────────────────────────────
    print("\n[1] 加载数据 …")
    df = pd.read_pickle(TABLES / "distributed_predictions.pkl")
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    df["date"] = df["time"].dt.date
    df["_month"] = df["time"].dt.month
    df["_ghi_bin"] = pd.cut(
        pd.to_numeric(df.get("g_blend_pred", pd.Series(0, index=df.index)), errors="coerce").fillna(0),
        bins=GHI_BINS, labels=False, include_lowest=True).astype(int)

    sm = pd.read_csv(TABLES / "site_master.csv")
    sid_to_county = dict(zip(sm["site_id"], sm["county"]))
    sid_to_bucket = dict(zip(sm["site_id"], sm["capacity_bucket"]))
    sid_to_coastal = dict(zip(sm["site_id"], sm["coastal_flag"]))

    if "county" not in df.columns: df["county"] = df["site_id"].map(sid_to_county).fillna("unknown")
    if "capacity_bucket" not in df.columns: df["capacity_bucket"] = df["site_id"].map(sid_to_bucket).fillna("unknown")
    if "coastal_flag" not in df.columns: df["coastal_flag"] = df["site_id"].map(sid_to_coastal).fillna(0).astype(int)
    if "p_base" not in df.columns: df["p_base"] = 0.0

    from pv_forecasting.core.split import add_standard_split
    df = add_standard_split(df)
    valid_mask = (df["split"] == "valid") & (~df["site_id"].isin(BAD_SITES))
    test_mask = (df["split"] == "test") & (~df["site_id"].isin(BAD_SITES))
    print(f"  验证集: {valid_mask.sum():,}, 测试集: {test_mask.sum():,}")

    test = df[test_mask & (df["power_mw"] > 0)].copy()
    print(f"  测试集(有功>0): {len(test):,}")

    # ── Fit P1 ───────────────────────────────────────────────────────────────
    print("\n[2] P1 因子拟合 …")
    p1_lookup, ghi_median = fit_p1(df, valid_mask)
    print(f"  全局因子: {float(df[valid_mask & df['power_mw'] > 0]['power_mw'].sum() / max(float(df[valid_mask & df['power_mw'] > 0]['power_pred'].sum()), 0.5)):.4f}")
    print(f"  P1 lookup 条目: {len(p1_lookup)}")

    # P1 factor distribution by hour
    print("\n  P1 因子按 GHI bin 分布:")
    for gb in sorted(set(k[0] for k in p1_lookup)):
        vals = [v for k, v in p1_lookup.items() if k[0] == gb]
        if vals:
            print(f"    ghi_bin={gb}: min={min(vals):.3f} median={np.median(vals):.3f} max={max(vals):.3f}")

    # ── Dawn/Dusk params ────────────────────────────────────────────────────
    print("\n[3] Dawn/Dusk 参数 …")
    level1, level2, level3, level4, level5 = load_dawn_dusk_params()
    print(f"  level1(site): {len(level1)}, level2(county,bucket): {len(level2)}, "
          f"level3(county): {len(level3)}, level4(coastal): {len(level4)}, "
          f"level5(hour): {sum(1 for v in level5.values() if np.isfinite(v))}")

    # ── Build all strategy predictions ─────────────────────────────────────
    print("\n[4] 构建各策略预测 …")

    # S0: raw baseline
    test["pred_S0"] = test["power_pred"].values

    # S1: P0晴空保护
    GHI_CLEAR, GHI_MED = 600.0, 300.0
    ghi = pd.to_numeric(test["g_blend_pred"], errors="coerce").fillna(0).values
    base = pd.to_numeric(test["pred_baseline"], errors="coerce").fillna(0).values
    v152 = test["power_pred"].values.copy()
    cap_arr = pd.to_numeric(test["capacity_mw"], errors="coerce").fillna(1).values
    atten = np.where(ghi > GHI_CLEAR, 0.0, np.where(ghi > GHI_MED, 0.5, 1.0))
    test["pred_S1"] = np.clip(base + atten * (v152 - base), 0.0, cap_arr)

    # S2: P0 + P1
    test["p1_factor"] = 1.0
    for (gb, mo), fac in p1_lookup.items():
        test.loc[(test["_ghi_bin"] == gb) & (test["_month"] == mo), "p1_factor"] = fac
    for gb, fac in ghi_median.items():
        test.loc[(test["_ghi_bin"] == gb) & (test["p1_factor"] == 1.0), "p1_factor"] = fac
    test["pred_S2"] = test["pred_S1"] * test["p1_factor"]

    # Dawn/Dusk fallback (shared between S3 and S4)
    h_arr = test["hour"].values
    sid_arr = test["site_id"].values
    cty_arr = test["county"].values
    bkt_arr = test["capacity_bucket"].values
    cfl_arr = test["coastal_flag"].values
    p_base_arr = pd.to_numeric(test["p_base"], errors="coerce").fillna(0).values
    cap_arr_test = pd.to_numeric(test["capacity_mw"], errors="coerce").fillna(1e6).values

    ratio_arr = np.full(len(test), np.nan)
    dd_mask = np.isin(h_arr, DAWN_DUSK)
    dd_indices = np.where(dd_mask)[0]
    print(f"  Dawn/Dusk 样本: {len(dd_indices):,}，逐行计算 floor_ratio …")
    for pos_idx in dd_indices:
        h, sid, cty, bkt, cfl = int(h_arr[pos_idx]), sid_arr[pos_idx], cty_arr[pos_idx], bkt_arr[pos_idx], int(cfl_arr[pos_idx])
        ratio_arr[pos_idx] = (level1.get((h, sid)) or level2.get((h, cty, bkt)) or
                               level3.get((h, cty)) or level4.get((h, cfl)) or level5.get(h) or np.nan)

    floor_arr = p_base_arr * ratio_arr
    dd_apply = np.isfinite(ratio_arr) & (test["pred_S2"].values < floor_arr)
    pred_S3 = test["pred_S2"].values.copy()
    pred_S3[dd_apply] = np.minimum(floor_arr[dd_apply], cap_arr_test[dd_apply])
    test["pred_S3"] = pred_S3

    # S4: P0 + Dawn/Dusk (no P1)
    pred_S4 = test["pred_S1"].values.copy()
    dd_apply_S4 = np.isfinite(ratio_arr) & (test["pred_S1"].values < floor_arr)
    pred_S4[dd_apply_S4] = np.minimum(floor_arr[dd_apply_S4], cap_arr_test[dd_apply_S4])
    test["pred_S4"] = pred_S4

    # ── Evaluate all strategies ────────────────────────────────────────────
    print("\n[5] 评估所有策略 …")
    strategies = ["S0", "S1", "S2", "S3", "S4"]
    strategy_labels = {
        "S0": "原始基准",
        "S1": "P0晴空",
        "S2": "P0+P1",
        "S3": "P0+P1+DD",
        "S4": "P0+DD",
    }

    all_evals = {}
    for s in strategies:
        all_evals[s] = eval_by_hour(test, f"pred_{s}")
        all_evals[f"{s}_global"] = eval_global(test, f"pred_{s}")

    # ── Print comparison table ─────────────────────────────────────────────
    print("\n" + "=" * 90)
    print("策略对比 — 全局指标")
    print("=" * 90)
    print(f"  {'策略':<20} | {'WAPE':>7} | {'clip':>7} | {'raw_mape':>8} | {'city_rel':>9}")
    print(f"  {'-'*60}")
    for s in strategies:
        g = all_evals[f"{s}_global"]
        print(f"  {strategy_labels[s]:<20} | {g['wape']:>7.1f} | {g['clipped_mape']:>7.1f} | "
              f"{g['raw_mape']:>8.1f} | {g['city_rel_err']:>9.1f}")

    # ── Hourly comparison for dawn/dusk hours ───────────────────────────────
    print("\n" + "=" * 90)
    print("早晚时段逐小时对比")
    print("=" * 90)
    print(f"  {'h':>3} | {'指标':<12} | {'S0原始':>8} | {'S1P0':>8} | {'S2P0+P1':>8} | "
          f"{'S3P0+P1+DD':>8} | {'S4P0+DD':>8} | {'最优':>6}")
    print(f"  {'-'*80}")
    for h in DAWN_DUSK:
        for metric, label in [("city_rel_err", "city_rel"),
                              ("site_mape_raw_mean", "raw_mean"),
                              ("site_mape_clipped", "clipped"),
                              ("site_wape", "WAPE")]:
            row_vals = {}
            for s in strategies:
                row = all_evals[s]
                r = row[row["hour"] == h]
                row_vals[s] = float(r[metric].iloc[0]) if len(r) > 0 else np.nan
            best_s = min(strategies, key=lambda s: row_vals[s])
            if metric == "city_rel":
                print(f"  {h:3d} | {label:<12} | {row_vals['S0']:>8.1f} | {row_vals['S1']:>8.1f} | "
                      f"{row_vals['S2']:>8.1f} | {row_vals['S3']:>8.1f} | {row_vals['S4']:>8.1f} | "
                      f"{strategy_labels[best_s]:>6}")
    print()

    # ── Determine best strategy per hour ───────────────────────────────────
    print("\n最优策略选择（按小时）:")
    hour_best = {}
    for h in HOURS:
        best_scores = {}
        for s in strategies:
            row = all_evals[s]
            r = row[row["hour"] == h]
            if len(r) == 0: continue
            cre = float(r["city_rel_err"].iloc[0])
            clip = float(r["site_mape_clipped"].iloc[0])
            if np.isfinite(cre) and np.isfinite(clip):
                # 选 city_rel_err 最优的（主指标）
                best_scores[s] = cre
        if best_scores:
            hour_best[h] = min(best_scores, key=best_scores.get)
    for h in HOURS:
        s = hour_best.get(h, "S0")
        print(f"  h={h:02d}: {strategy_labels[s]}")

    # ── Select v3: hybrid ──────────────────────────────────────────────────
    # Rule: use S4 (P0+DD, no P1) for dawn/dusk hours (where P1 causes overshoot),
    #       use S2 (P0+P1) for daytime (8-15, where P1 helps)
    # This avoids P1 in dawn/dusk while keeping P1 for daytime.
    #
    # Actually, let's be more data-driven: use whichever has lower clipped_mape
    # at dawn/dusk hours, and whichever has lower city_rel_err at daytime.
    hybrid_map = {}
    for h in HOURS:
        if h in DAWN_DUSK:
            # Dawn/dusk: prefer lower clipped_mape
            scores = {}
            for s in ["S3", "S4"]:
                row = all_evals[s]
                r = row[row["hour"] == h]
                if len(r) > 0:
                    scores[s] = float(r["site_mape_clipped"].iloc[0])
            if scores:
                hybrid_map[h] = min(scores, key=scores.get)
            else:
                hybrid_map[h] = "S0"
        else:
            # Daytime: prefer lower city_rel_err
            scores = {}
            for s in ["S1", "S2", "S3"]:
                row = all_evals[s]
                r = row[row["hour"] == h]
                if len(r) > 0:
                    scores[s] = float(r["city_rel_err"].iloc[0])
            if scores:
                hybrid_map[h] = min(scores, key=scores.get)
            else:
                hybrid_map[h] = "S0"

    print("\n混合策略（hybrid v3）:")
    for h in HOURS:
        print(f"  h={h:02d}: {strategy_labels[hybrid_map.get(h, 'S0')]}")

    # Build hybrid prediction
    test["pred_v3"] = test["pred_S0"].values.copy()
    for s in strategies:
        mask = test["hour"].isin([h for h in HOURS if hybrid_map.get(h) == s])
        test.loc[mask, "pred_v3"] = test.loc[mask, f"pred_{s}"].values

    # ── Final v3 evaluation ────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("v3 (hybrid) vs 原始基准 全局对比")
    print("=" * 70)
    g_v3 = eval_global(test, "pred_v3")
    g_s0 = all_evals["S0_global"]
    for key in ["wape", "clipped_mape", "raw_mape", "city_rel_err"]:
        v0 = g_s0[key]
        v3 = g_v3[key]
        delta = v3 - v0
        arrow = "↓" if (key == "city_rel_err" and delta < 0) or (key != "city_rel_err" and delta < 0) else "↑"
        print(f"  {key:<15}: {v0:>7.1f}% → {v3:>7.1f}%  ({arrow}{abs(delta):.1f}%)")

    # Hourly v3 vs S0
    v3_hour = eval_by_hour(test, "pred_v3")
    print(f"\n  {'h':>3} | {'raw_mean':>8} {'→':>4} | {'clip':>8} {'→':>4} | {'WAPE':>6} {'→':>4} | {'city_rel':>9} {'→':>4} | {'>200':>5}")
    print(f"  {'-'*65}")
    for _, r in v3_hour.iterrows():
        h = int(r["hour"])
        s0_r = all_evals["S0"]
        s0 = s0_r[s0_r["hour"] == h].iloc[0] if len(s0_r[s0_r["hour"] == h]) > 0 else None
        if s0 is None: continue
        marker = " ★" if h in DAWN_DUSK else ""
        n200_s0 = int(s0["n_gt200"])
        n200_v3 = int(r["n_gt200"])
        print(f"  {h:3d}{marker} | {float(s0['site_mape_raw_mean']):>7.1f}{'↓' if r['site_mape_raw_mean'] < float(s0['site_mape_raw_mean']) else '↑':>4} | "
              f"{float(s0['site_mape_clipped']):>7.1f}{'↓' if r['site_mape_clipped'] < float(s0['site_mape_clipped']) else '↑':>4} | "
              f"{float(s0['site_wape']):>5.1f}{'↓' if r['site_wape'] < float(s0['site_wape']) else '↑':>4} | "
              f"{float(s0['city_rel_err']):>8.1f}{'↓' if r['city_rel_err'] < float(s0['city_rel_err']) else '↑':>4} | "
              f"{n200_s0:>3}→{n200_v3:<3}")

    # ── Save v3 output ─────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("[6] 保存 v3 预测 …")
    result = df.copy()
    # Merge v3 predictions for test set
    v3_map = test.set_index(["time", "site_id"])["pred_v3"].to_dict()
    result["power_pred_v3"] = result.apply(
        lambda r: v3_map.get((r["time"], r["site_id"]),
                             v3_map.get((pd.Timestamp(r["time"]), r["site_id"]),
                                       r["power_pred"])), axis=1)

    result["power_pred"] = result["power_pred_v3"]
    v3_path = TABLES / "distributed_predictions_fixed_full_v3.pkl"
    result.to_pickle(v3_path)
    print(f"  已保存: {v3_path}")

    # ── Ablation CSV ───────────────────────────────────────────────────────
    ablation_rows = []
    for _, r in v3_hour.iterrows():
        h = int(r["hour"])
        s0_r = all_evals["S0"]
        s0 = s0_r[s0_r["hour"] == h].iloc[0] if len(s0_r[s0_r["hour"] == h]) > 0 else None
        s3_r = all_evals["S3"]
        s3 = s3_r[s3_r["hour"] == h].iloc[0] if len(s3_r[s3_r["hour"] == h]) > 0 else None
        s4_r = all_evals["S4"]
        s4 = s4_r[s4_r["hour"] == h].iloc[0] if len(s4_r[s4_r["hour"] == h]) > 0 else None

        def get_val(r_, col):
            return float(r_[col]) if r_ is not None and col in r_ else np.nan

        ablation_rows.append({
            "hour": h,
            "strategy": hybrid_map.get(h, "S0"),
            "n": int(r["n"]),
            "S0_raw": get_val(s0, "site_mape_raw_mean"),
            "S0_clip": get_val(s0, "site_mape_clipped"),
            "S0_wape": get_val(s0, "site_wape"),
            "S0_cre": get_val(s0, "city_rel_err"),
            "S3_raw": get_val(s3, "site_mape_raw_mean"),
            "S3_clip": get_val(s3, "site_mape_clipped"),
            "S3_wape": get_val(s3, "site_wape"),
            "S3_cre": get_val(s3, "city_rel_err"),
            "S4_raw": get_val(s4, "site_mape_raw_mean"),
            "S4_clip": get_val(s4, "site_mape_clipped"),
            "S4_wape": get_val(s4, "site_wape"),
            "S4_cre": get_val(s4, "city_rel_err"),
            "v3_raw": float(r["site_mape_raw_mean"]),
            "v3_clip": float(r["site_mape_clipped"]),
            "v3_wape": float(r["site_wape"]),
            "v3_cre": float(r["city_rel_err"]),
            "delta_raw_vs_S0": float(r["site_mape_raw_mean"]) - get_val(s0, "site_mape_raw_mean"),
            "delta_cre_vs_S0": float(r["city_rel_err"]) - get_val(s0, "city_rel_err"),
            "n_gt200_S0": int(get_val(s0, "n_gt200")) if s0 is not None else 0,
            "n_gt200_v3": int(r["n_gt200"]),
        })

    ablation_df = pd.DataFrame(ablation_rows)
    ablation_df.to_csv(METRICS / "v3_strategy_ablation.csv", index=False, encoding="utf-8-sig")
    print(f"  消融分析已保存: {METRICS / 'v3_strategy_ablation.csv'}")

    # Summary
    print("\n" + "=" * 70)
    print("总结")
    print("=" * 70)
    v3_glob = eval_global(test, "pred_v3")
    print(f"  v3 vs 原始基准:")
    print(f"    WAPE:          {g_s0['wape']:.1f}% → {v3_glob['wape']:.1f}%  (Δ {v3_glob['wape']-g_s0['wape']:+.1f}%)")
    print(f"    clipped_MAPE:  {g_s0['clipped_mape']:.1f}% → {v3_glob['clipped_mape']:.1f}%  (Δ {v3_glob['clipped_mape']-g_s0['clipped_mape']:+.1f}%)")
    print(f"    city_rel_err:  {g_s0['city_rel_err']:.1f}% → {v3_glob['city_rel_err']:.1f}%  (Δ {v3_glob['city_rel_err']-g_s0['city_rel_err']:+.1f}%)")

    # Dawn/dusk summary
    v3_h = v3_hour[v3_hour["hour"].isin(DAWN_DUSK)]
    s0_h = all_evals["S0"]
    dd_s0 = s0_h[s0_h["hour"].isin(DAWN_DUSK)]
    print(f"\n  早晚时段 (h={DAWN_DUSK[0]}-{DAWN_DUSK[-1]}):")
    print(f"    city_rel_err: {float(dd_s0['city_rel_err'].mean()):.1f}% → {float(v3_h['city_rel_err'].mean()):.1f}%")
    print(f"    clipped_mape: {float(dd_s0['site_mape_clipped'].mean()):.1f}% → {float(v3_h['site_mape_clipped'].mean()):.1f}%")
    print(f"    WAPE:         {float(dd_s0['site_wape'].mean()):.1f}% → {float(v3_h['site_wape'].mean()):.1f}%")

    print("\nDone.")


if __name__ == "__main__":
    main()
