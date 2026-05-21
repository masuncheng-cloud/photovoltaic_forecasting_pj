#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
叠加城市级 P1 修正到 dawn/dusk 修正后的预测
==========================================
策略：
  - 基础：distributed_predictions_fixed_full.pkl（已含 P0 + 站点级修正，city bias ≈ -21%）
  - Dawn/Dusk：站点级 floor 修正（已有）
  - P1：城市级聚合乘因子（新增）

输出：distributed_predictions_fixed_full_v2.pkl
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
TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)

PRED_PATH = TABLES_DIR / "distributed_predictions_fixed_full.pkl"
OUTPUT_PATH = TABLES_DIR / "distributed_predictions_fixed_full_v2.pkl"
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}
DAWN_DUSK_HOURS = [6, 7, 16, 17, 18, 19]

GHI_BINS = [0, 100, 200, 300, 450, 600, 800, 99999]
FACTOR_CLIP = (0.70, 1.40)
P1_MIN_SAMPLES = 20
K_SHRINKAGE = 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clipped_mape(y_true, y_pred, clip_factor=0.05):
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    denom = np.maximum(y_true[m], clip_factor * np.median(y_true[m]))
    return float(np.mean(np.abs(y_true[m] - y_pred[m]) / denom) * 100)


def raw_mape(y_true, y_pred):
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.mean(np.abs(y_true[m] - y_pred[m]) / y_true[m]) * 100)


def wape(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.sum(np.abs(y_true[m] - y_pred[m])) / np.sum(np.abs(y_true[m])) * 100)


def city_rel_err(yt, yp):
    mask = np.isfinite(yt) & np.isfinite(yp) & (yt > 0)
    yt_s = float(np.nansum(yt[mask]))
    if not np.isfinite(yt_s) or yt_s <= 0:
        return np.nan
    return float(np.abs(np.nansum(yp[mask]) - yt_s) / yt_s * 100)


# ---------------------------------------------------------------------------
# P1 factor
# ---------------------------------------------------------------------------

def fit_p1(df, valid_mask):
    df = df.copy()
    df["_ghi_bin"] = pd.cut(
        pd.to_numeric(df.get("g_blend_pred", pd.Series(0, index=df.index)), errors="coerce").fillna(0),
        bins=GHI_BINS, labels=False, include_lowest=True).astype(int)
    df["_month"] = pd.to_numeric(pd.to_datetime(df["time"]).dt.month, errors="coerce").astype("Int64")

    vdf = df[valid_mask & df["power_mw"].notna() & (df["power_mw"] > 0)].copy()
    if len(vdf) == 0:
        return None, {}

    # 全局因子
    all_actual = float(vdf["power_mw"].sum())
    all_p0 = float(vdf["power_pred"].sum())
    global_factor = float(np.clip(all_actual / max(all_p0, 0.5), *FACTOR_CLIP))
    print(f"  [P1] 全局因子: {global_factor:.4f}")

    # Raw factors
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
        rows.append({
            "ghi_bin": int(gb), "month": int(mo), "n": int(n),
            "raw": round(factor, 4) if np.isfinite(factor) else np.nan,
            "passed": passed, "has_data": True
        })
    fdf = pd.DataFrame(rows)

    # Month-neighbor median
    def mo_med(fdf_in, gb, mo_t):
        neighs = [mo_t - 1, mo_t, mo_t + 1]
        cands = fdf_in[(fdf_in["ghi_bin"] == gb) & fdf_in["month"].isin(neighs) & fdf_in["passed"]]["raw"]
        return float(np.nanmedian(cands)) if len(cands) > 0 else np.nan

    # GHI-bin median
    ghi_med = fdf[fdf["passed"]].groupby("ghi_bin")["raw"].median().to_dict()
    for gb in range(len(GHI_BINS) - 1):
        if gb not in ghi_med:
            ghi_med[gb] = global_factor

    # Final with shrinkage
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
        final.append({
            "ghi_bin": gb, "month": mo,
            "raw": r["raw"], "final": round(float(np.clip(ff, *FACTOR_CLIP)), 4)
        })

    fdf_out = pd.DataFrame(final)
    lookup = {(int(r["ghi_bin"]), int(r["month"])): float(r["final"]) for _, r in fdf_out.iterrows()}
    return lookup, ghi_med


def load_dawn_dusk_params():
    import json
    params_path = METRICS_DIR / "dawn_dusk_floor_params.json"
    with open(params_path, encoding="utf-8") as f:
        params = json.load(f)

    def _parse(d):
        result = {}
        for k, v in d.items():
            if "," in k:
                parts = k.strip("()").split(", ")
                if len(parts) == 2:
                    try:
                        key = (int(parts[0]), parts[1].strip("'\""))
                    except:
                        key = (int(parts[0]), parts[1].strip("'\" "))
                elif len(parts) == 3:
                    key = (int(parts[0]), parts[1].strip("'\" "), parts[2].strip("'\" "))
                else:
                    continue
                result[key] = v
            else:
                result[int(k)] = v
        return result

    return (
        _parse(params["level1"]),
        _parse(params["level2"]),
        _parse(params["level3"]),
        _parse(params["level4"]),
        _parse(params["level5"]),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("叠加城市级 P1 修正")
    print("=" * 60)

    # Load
    print("\n[1] 加载数据 …")
    df = pd.read_pickle(PRED_PATH)
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    df["date"] = df["time"].dt.date
    df["_month"] = df["time"].dt.month

    sm = pd.read_csv(PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "site_master.csv")
    sid_to_county = dict(zip(sm["site_id"], sm["county"]))
    sid_to_bucket = dict(zip(sm["site_id"], sm["capacity_bucket"]))
    sid_to_coastal = dict(zip(sm["site_id"], sm["coastal_flag"]))

    test_mask = (df["split"] == "test") & (~df["site_id"].isin(BAD_SITES))
    valid_mask = (df["split"] == "valid") & (~df["site_id"].isin(BAD_SITES))
    print(f"  测试集: {test_mask.sum():,}, 验证集: {valid_mask.sum():,}")

    # Baseline check
    test_base = df[test_mask & df["power_mw"] > 0]
    if len(test_base) > 0:
        city = test_base.groupby("time").agg(yt=("power_mw","sum"), yp=("power_pred","sum")).reset_index()
        city = city[city["yt"] > 0]
        bias0 = (city["yp"].sum() - city["yt"].sum()) / city["yt"].sum() * 100
        print(f"  基准城市偏差: {bias0:+.1f}%")

    # P1
    print("\n[2] P1 因子 (valid 集) …")
    p1_lookup, ghi_median = fit_p1(df, valid_mask)

    # Dawn/dusk
    print("\n[3] Dawn/Dusk floor 参数 …")
    level1, level2, level3, level4, level5 = load_dawn_dusk_params()

    # Apply to test
    print("\n[4] 应用修正到测试集 …")
    result = df.copy()
    result["power_pred_original"] = result["power_pred"].copy()
    result["p1_factor"] = 1.0
    result["dawn_dusk_applied"] = False
    result["p1_applied"] = False

    test_idx = result[test_mask].index

    # Compute ghi_bin and month for test set
    result["_ghi_bin"] = pd.cut(
        pd.to_numeric(result.get("g_blend_pred", pd.Series(0, index=result.index)), errors="coerce").fillna(0),
        bins=GHI_BINS, labels=False, include_lowest=True).astype(int)

    # Apply P1 factors per (ghi_bin, month)
    for (gb, mo), fac in p1_lookup.items():
        mask = (result["_ghi_bin"] == gb) & (result["_month"] == mo)
        result.loc[mask, "p1_factor"] = fac
        result.loc[mask & test_mask, "p1_applied"] = True
    for gb, fac in ghi_median.items():
        mask = (result["_ghi_bin"] == gb) & (result["p1_factor"] == 1.0)
        result.loc[mask, "p1_factor"] = fac

    # Load true baseline (no corrections)
    print("\n[4a] 加载真实基准（无修正） …")
    orig_path = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "distributed_predictions.pkl"
    df_orig = pd.read_pickle(orig_path)
    df_orig["time"] = pd.to_datetime(df_orig["time"])
    orig_map = df_orig.set_index(["time", "site_id"])["power_pred"].to_dict()
    result["power_pred_baseline_true"] = result.apply(
        lambda r: orig_map.get((pd.Timestamp(r["time"]), r["site_id"]), np.nan), axis=1
    )

    print(f"  真实基准已加载，样本匹配率: {result['power_pred_baseline_true'].notna().sum():,} / {len(result):,}")
    print(f"  P1 因子范围: {result['p1_factor'].min():.4f} – {result['p1_factor'].max():.4f}")

    # ── Vectorized P1 + Dawn/Dusk application ─────────────────────────
    print("\n[4b] 向量化应用 P1 + Dawn/Dusk …")
    n_test = test_mask.sum()
    print(f"  测试集样本: {n_test:,}")

    # 1) Apply P1 factor to baseline
    result["power_pred"] = result["power_pred_baseline_true"] * result["p1_factor"]

    # 2) Dawn/Dusk floor correction (vectorized by fallback level)
    is_dd_hour = result["hour"].isin(DAWN_DUSK_HOURS)

    # Build fallback-ratio lookup with site_master info
    # Ensure columns exist
    if "county" not in result.columns:
        result["county"] = result["site_id"].map(sid_to_county).fillna("unknown")
    if "capacity_bucket" not in result.columns:
        result["capacity_bucket"] = result["site_id"].map(sid_to_bucket).fillna("unknown")
    if "coastal_flag" not in result.columns:
        result["coastal_flag"] = result["site_id"].map(sid_to_coastal).fillna(0).astype(int)
    if "p_base" not in result.columns:
        result["p_base"] = 0.0

    # Compute floor ratio per row via layered fallback
    p_base_arr = pd.to_numeric(result["p_base"], errors="coerce").fillna(0).to_numpy()
    cap_arr = pd.to_numeric(result["capacity_mw"], errors="coerce").fillna(1e6).to_numpy()
    pred_arr = result["power_pred"].values.copy()  # mutable copy

    def fallback_ratio_vectorized(h_arr, sid_arr, county_arr, bucket_arr, coastal_arr,
                                  level1, level2, level3, level4, level5):
        ratios = np.full(len(h_arr), np.nan)
        for i in range(len(h_arr)):
            h, sid, cty, bkt, cfl = int(h_arr[i]), sid_arr[i], county_arr[i], bucket_arr[i], int(coastal_arr[i])
            ratios[i] = (level1.get((h, sid)) or
                         level2.get((h, cty, bkt)) or
                         level3.get((h, cty)) or
                         level4.get((h, cfl)) or
                         level5.get(h) or np.nan)
        return ratios

    # Compute ratios only for dawn/dusk hours
    dd_mask = is_dd_hour.values
    ratio_arr = np.full(len(result), np.nan)
    if dd_mask.any():
        print(f"  Dawn/Dusk 样本: {dd_mask.sum():,}，逐行计算 floor_ratio …")
        h_vals = result.loc[dd_mask, "hour"].values
        sid_vals = result.loc[dd_mask, "site_id"].values
        cty_vals = result.loc[dd_mask, "county"].values
        bkt_vals = result.loc[dd_mask, "capacity_bucket"].values
        cfl_vals = result.loc[dd_mask, "coastal_flag"].values
        ratio_arr[dd_mask] = fallback_ratio_vectorized(
            h_vals, sid_vals, cty_vals, bkt_vals, cfl_vals,
            level1, level2, level3, level4, level5)

    # Apply floor: only where ratio is finite and pred < floor
    floor_vals = p_base_arr * ratio_arr
    apply_mask = np.isfinite(ratio_arr) & (pred_arr < floor_vals)
    n_dd = int(apply_mask.sum())
    pred_arr[apply_mask] = np.minimum(floor_vals[apply_mask], cap_arr[apply_mask])

    result["power_pred"] = pred_arr
    result["dawn_dusk_applied"] = apply_mask

    print(f"  Dawn/Dusk 修正: {n_dd:,} 样本 ({n_dd/n_test*100:.1f}%)")
    print(f"  P1 因子范围 (test): {result.loc[test_mask, 'p1_factor'].min():.4f} – {result.loc[test_mask, 'p1_factor'].max():.4f}")

    # Guard: ensure no prediction exceeds capacity
    cap_final = pd.to_numeric(result["capacity_mw"], errors="coerce").fillna(1e6).to_numpy()
    over_cap = (pred_arr > cap_final) & test_mask.values
    if over_cap.any():
        print(f"  ⚠ 修正后超容量样本: {over_cap.sum():,} → clip 到容量上限")
        result.loc[over_cap.values, "power_pred"] = cap_final[over_cap]

    # Evaluate
    print("\n[5] 逐小时评估 …")
    test_eval = result[test_mask & (result["power_mw"] > 0)].copy()
    test_eval["hour"] = pd.to_datetime(test_eval["time"]).dt.hour

    rows = []
    for h in range(6, 20):
        sub = test_eval[test_eval["hour"] == h]
        if len(sub) == 0:
            continue
        yt = sub["power_mw"].values.astype(float)
        yp0 = sub["power_pred_baseline_true"].values.astype(float)
        yp1 = sub["power_pred"].values.astype(float)

        n = len(sub)
        cre0 = city_rel_err(yt, yp0)
        cre1 = city_rel_err(yt, yp1)
        clip0 = clipped_mape(yt, yp0)
        clip1 = clipped_mape(yt, yp1)
        mape0 = raw_mape(yt, yp0)
        mape1 = raw_mape(yt, yp1)
        wape0 = wape(yt, yp0)
        wape1 = wape(yt, yp1)

        rows.append({
            "hour": h, "n": n,
            "city_rel_err_before": round(cre0, 2) if np.isfinite(cre0) else np.nan,
            "city_rel_err_after": round(cre1, 2) if np.isfinite(cre1) else np.nan,
            "delta_cre": round((cre1 or 0) - (cre0 or 0), 2),
            "clip_before": round(clip0, 2) if np.isfinite(clip0) else np.nan,
            "clip_after": round(clip1, 2) if np.isfinite(clip1) else np.nan,
            "mape_before": round(mape0, 2) if np.isfinite(mape0) else np.nan,
            "mape_after": round(mape1, 2) if np.isfinite(mape1) else np.nan,
            "delta_mape": round((mape1 or 0) - (mape0 or 0), 2),
            "wape_before": round(wape0, 2) if np.isfinite(wape0) else np.nan,
            "wape_after": round(wape1, 2) if np.isfinite(wape1) else np.nan,
        })

    eval_df = pd.DataFrame(rows)
    print(eval_df.to_string(index=False))

    eval_df.to_csv(METRICS_DIR / "combined_fix_ablation.csv", index=False, encoding="utf-8-sig")
    print(f"\n  已保存: {METRICS_DIR / 'combined_fix_ablation.csv'}")

    # Save
    print("\n[6] 保存 …")
    result.to_pickle(OUTPUT_PATH)
    print(f"  已保存: {OUTPUT_PATH}")

    # Summary
    print("\n" + "=" * 60)
    print("修正总结")
    print("=" * 60)
    dd = eval_df[eval_df["hour"].isin(DAWN_DUSK_HOURS)]
    all_e = eval_df

    def avg(x):
        return float(np.nanmean([v for v in x if np.isfinite(v)]))

    print(f"\n早晚时段 (h={DAWN_DUSK_HOURS[0]}-{DAWN_DUSK_HOURS[-1]}):")
    print(f"  city_rel_err: {avg(dd['city_rel_err_before']):.1f}% → {avg(dd['city_rel_err_after']):.1f}%  "
          f"(Δ {avg(dd['delta_cre']):+.1f}%)")
    print(f"  raw MAPE:     {avg(dd['mape_before']):.1f}% → {avg(dd['mape_after']):.1f}%  "
          f"(Δ {avg(dd['delta_mape']):+.1f}%)")
    print(f"  WAPE:         {avg(dd['wape_before']):.1f}% → {avg(dd['wape_after']):.1f}%")

    print(f"\n全部时段 (h=6-19):")
    print(f"  city_rel_err: {avg(all_e['city_rel_err_before']):.1f}% → {avg(all_e['city_rel_err_after']):.1f}%  "
          f"(Δ {avg(all_e['delta_cre']):+.1f}%)")
    print(f"  raw MAPE:     {avg(all_e['mape_before']):.1f}% → {avg(all_e['mape_after']):.1f}%  "
          f"(Δ {avg(all_e['delta_mape']):+.1f}%)")
    print(f"  WAPE:         {avg(all_e['wape_before']):.1f}% → {avg(all_e['wape_after']):.1f}%")

    print("\nDone.")


if __name__ == "__main__":
    main()
