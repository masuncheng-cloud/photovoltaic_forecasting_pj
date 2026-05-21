#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V4: DD corrections on top of V1 (fixed_full = P0+P1)
=====================================================
Tests whether Dawn/Dusk floor corrections on V1 (which already has P0+P1)
improve or worsen metrics. Uses V1 as the base since P1 already addresses
city_rel_err across all hours (including dawn/dusk).

The diagnostic showed:
  - P0+P1 on raw baseline: city_rel much better at all hours
  - P0+DD on raw baseline: marginally better than P0+P1+DD at dawn/dusk
  - But V1 = fixed_full already has P0+P1 applied
  - Question: does adding DD on top of V1 help?

Strategy:
  - V1 (fixed_full): P0+P1 only — BEST for city_rel_err, WAPE
  - V1+DD (test): add dawn/dusk floor on top of V1
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
import sys
import functools as _functools
import json

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
sys.path.insert(0, str(PROJECT_ROOT / "src"))
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

def site_rel_err(y, p):
    m = (y > 0) & np.isfinite(y) & np.isfinite(p)
    if not m.any(): return np.nan
    return float(np.abs(y[m] - p[m]).sum() / y[m].sum() * 100)


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


def main():
    print("=" * 70)
    print("V4: DD on V1 — V1 vs V1+DD vs V0")
    print("=" * 70)

    # Load V1 = fixed_full (P0+P1)
    print("\n[1] 加载 V1 (fixed_full = P0+P1) …")
    df = pd.read_pickle(TABLES / "distributed_predictions_fixed_full.pkl")
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    df["date"] = df["time"].dt.date

    # Also load raw for V0 comparison
    df_raw = pd.read_pickle(TABLES / "distributed_predictions.pkl")
    df_raw["time"] = pd.to_datetime(df_raw["time"])
    raw_map = df_raw.set_index(["time", "site_id"])["power_pred"].to_dict()

    mask = (
        (df["split"] == "test") &
        (~df["site_id"].isin(BAD_SITES)) &
        (df["hour"].isin(HOURS)) &
        (df["power_mw"] > 0)
    )
    test = df[mask].copy()
    test["pred_V0"] = test.apply(
        lambda r: raw_map.get((r["time"], r["site_id"]),
                             raw_map.get((pd.Timestamp(r["time"]), r["site_id"]), np.nan)), axis=1)
    test["pred_V1"] = test["power_pred"].values.copy()
    print(f"  测试集: {len(test):,} 行, {test['site_id'].nunique()} 站点")

    # Load Dawn/Dusk params
    print("\n[2] 加载 Dawn/Dusk 参数 …")
    level1, level2, level3, level4, level5 = load_dawn_dusk_params()

    sm = pd.read_csv(TABLES / "site_master.csv")
    sid_to_county = dict(zip(sm["site_id"], sm["county"]))
    sid_to_bucket = dict(zip(sm["site_id"], sm["capacity_bucket"]))
    sid_to_coastal = dict(zip(sm["site_id"], sm["coastal_flag"]))

    if "county" not in test.columns: test["county"] = test["site_id"].map(sid_to_county).fillna("unknown")
    if "capacity_bucket" not in test.columns: test["capacity_bucket"] = test["site_id"].map(sid_to_bucket).fillna("unknown")
    if "coastal_flag" not in test.columns: test["coastal_flag"] = test["site_id"].map(sid_to_coastal).fillna(0).astype(int)
    if "p_base" not in test.columns: test["p_base"] = 0.0

    # Apply V1+DD
    print("\n[3] 应用 V1+DD (dawn/dusk floor on V1) …")
    p_base_arr = pd.to_numeric(test["p_base"], errors="coerce").fillna(0).values
    cap_arr = pd.to_numeric(test["capacity_mw"], errors="coerce").fillna(1e6).values
    pred_v1 = test["pred_V1"].values.copy()
    pred_v1dd = pred_v1.copy()
    n_dd = 0

    for idx in test.index:
        pos = test.index.get_loc(idx)
        h = int(test.loc[idx, "hour"])
        if h not in DAWN_DUSK:
            continue
        sid = test.loc[idx, "site_id"]
        cty = test.loc[idx, "county"]
        bkt = test.loc[idx, "capacity_bucket"]
        cfl = int(test.loc[idx, "coastal_flag"])

        ratio = (level1.get((h, sid)) or level2.get((h, cty, bkt)) or
                 level3.get((h, cty)) or level4.get((h, cfl)) or
                 level5.get(h) or np.nan)
        if not np.isfinite(ratio):
            continue

        floor_val = p_base_arr[pos] * ratio
        if pred_v1[pos] < floor_val:
            pred_v1dd[pos] = min(floor_val, cap_arr[pos])
            n_dd += 1

    test["pred_V1DD"] = pred_v1dd
    print(f"  DD 修正样本: {n_dd:,} / {len(test):,} ({n_dd/len(test)*100:.1f}%)")

    # Guard check per hour
    print("\n[4] Guard 检查 (V1 vs V1+DD) …")
    guard_results = {}
    for h in DAWN_DUSK:
        sub_mask = test["hour"] == h
        sub = test[sub_mask]
        if len(sub) == 0:
            guard_results[h] = True
            continue

        yt = sub["power_mw"].values.astype(float)
        yp1 = sub["pred_V1"].values.astype(float)
        yp2 = sub["pred_V1DD"].values.astype(float)

        clip1 = clipped_mape(yt, yp1)
        clip2 = clipped_mape(yt, yp2)
        cre1 = city_rel_err(yt, yp1)
        cre2 = city_rel_err(yt, yp2)

        clip_pass = clip2 <= clip1 * 1.10  # allow 10% deterioration
        cre_improved = np.isfinite(cre2) and np.isfinite(cre1) and cre2 < cre1
        passed = clip_pass or cre_improved
        guard_results[h] = passed

        if not passed:
            print(f"  Guard h={h:02d}: clip {clip1:.1f}→{clip2:.1f} (恶化 {(clip2/clip1-1)*100:+.0f}%), "
                  f"cre {cre1:.1f}→{cre2:.1f} ({'+' if cre2>cre1 else ''}{cre2-cre1:+.1f}%)")

    if all(guard_results.values()):
        print("  全部 Guard 通过 ✓")
    else:
        failed = [h for h, v in guard_results.items() if not v]
        print(f"  Guard 失败: {failed} → 回退到 V1")

    # Apply guard: rollback failed hours
    pred_v1dd_final = pred_v1dd.copy()
    for h in DAWN_DUSK:
        if not guard_results[h]:
            mask_h = test["hour"] == h
            pred_v1dd_final[mask_h.values] = pred_v1[mask_h.values]
    test["pred_V1DD_safe"] = pred_v1dd_final

    # ── Evaluate ───────────────────────────────────────────────────────────────
    print("\n[5] 评估 …")

    def eval_hourly(df_in, pred_col):
        rows = []
        for h in HOURS:
            sub = df_in[df_in["hour"] == h]
            if len(sub) == 0: continue
            yt = sub["power_mw"].values.astype(float)
            yp = sub[pred_col].values.astype(float)
            valid = sub[pred_col].notna()
            yt = yt[valid.values]
            yp = yp[valid.values]
            if len(yt) == 0: continue

            site_rels = []
            for _, sg in sub[valid].groupby("site_id"):
                r = site_rel_err(sg["power_mw"].values, sg[pred_col].values)
                if np.isfinite(r): site_rels.append(r)
            site_rels = np.array(site_rels)

            rows.append({
                "hour": int(h),
                "site_mape_raw_mean": float(np.nanmean(site_rels)),
                "site_mape_raw_median": float(np.nanmedian(site_rels)),
                "site_mape_clipped": clipped_mape(yt, yp),
                "site_wape": wape(yt, yp),
                "city_rel_err": city_rel_err(yt, yp),
                "n_gt100": int((site_rels > 100).sum()),
                "n_gt200": int((site_rels > 200).sum()),
            })
        return pd.DataFrame(rows)

    eV0 = eval_hourly(test, "pred_V0")
    eV1 = eval_hourly(test, "pred_V1")
    eV1dd = eval_hourly(test, "pred_V1DD_safe")

    # Global
    def global_stats(df_in, pred_col):
        sub = df_in[df_in[pred_col].notna()]
        yt = sub["power_mw"].values.astype(float)
        yp = sub[pred_col].values.astype(float)
        return {
            "WAPE": wape(yt, yp),
            "clipped_MAPE": clipped_mape(yt, yp),
            "raw_MAPE": raw_mape(yt, yp),
            "city_rel_err": city_rel_err(yt, yp),
        }

    gV0 = global_stats(test, "pred_V0")
    gV1 = global_stats(test, "pred_V1")
    gV1dd = global_stats(test, "pred_V1DD_safe")

    print("\n全局指标:")
    print(f"  {'指标':<15} | {'V0原始':>9} | {'V1(P0+P1)':>10} | {'V1+DD':>10} | {'V1 vs V0':>10} | {'V1+DD vs V0':>12}")
    print(f"  {'-'*75}")
    for key in ["WAPE", "clipped_MAPE", "raw_MAPE", "city_rel_err"]:
        v0 = gV0[key]; v1 = gV1[key]; v1d = gV1dd[key]
        delta1 = v1 - v0; delta2 = v1d - v0
        print(f"  {key:<15} | {v0:>8.1f}% | {v1:>9.1f}% | {v1d:>9.1f}% | "
              f"{delta1:>+9.1f}% | {delta2:>+11.1f}%")

    print(f"\n早晚时段对比 (h={DAWN_DUSK[0]}-{DAWN_DUSK[-1]}):")
    print(f"  {'指标':<20} | {'V0':>8} | {'V1':>8} | {'V1+DD':>8} | {'V1 vs V0':>10} | {'V1+DD vs V0':>12}")
    print(f"  {'-'*75}")
    for key in ["city_rel_err", "site_mape_raw_mean", "site_mape_clipped", "site_wape"]:
        v0 = float(eV0[eV0["hour"].isin(DAWN_DUSK)][key].mean())
        v1 = float(eV1[eV1["hour"].isin(DAWN_DUSK)][key].mean())
        v1d = float(eV1dd[eV1dd["hour"].isin(DAWN_DUSK)][key].mean())
        print(f"  {key:<20} | {v0:>7.1f}% | {v1:>7.1f}% | {v1d:>7.1f}% | "
              f"{v1-v0:>+9.1f}% | {v1d-v0:>+11.1f}%")

    print(f"\n逐小时对比:")
    print(f"  {'h':>3} | {'raw_MAPE_V0':>10} {'→':>5} | {'clip_V0':>7} {'→':>5} | {'WAPE_V0':>7} {'→':>5} | {'city_rel_V0':>10} {'→':>5} | {'>200_V0→V1→V1DD':>20}")
    print(f"  {'-'*90}")
    for _, r0 in eV0.iterrows():
        h = int(r0["hour"])
        r1 = eV1[eV1["hour"] == h]
        r1d = eV1dd[eV1dd["hour"] == h]
        if len(r1) == 0: continue
        r1 = r1.iloc[0]
        r1d = r1d.iloc[0] if len(r1d) > 0 else r1

        marker = " ★" if h in DAWN_DUSK else ""
        n200_0 = int(r0["n_gt200"])
        n200_1 = int(r1["n_gt200"])
        n200_1d = int(r1d["n_gt200"])
        n200_s = f"{n200_0}→{n200_1}→{n200_1d}"

        v0_cr = float(r0["city_rel_err"])
        v1_cr = float(r1["city_rel_err"])
        v1d_cr = float(r1d["city_rel_err"])

        arrow = "↓" if v1_cr < v0_cr else ("↑" if v1_cr > v0_cr else "-")

        print(f"  {h:3d}{marker} | {v0_cr:>9.1f}{arrow:>5} | "
              f"{float(r0['site_wape']):>6.1f}{'↓' if float(r1['site_wape'])<float(r0['site_wape']) else '↑':>4} | "
              f"{float(r0['site_mape_clipped']):>6.1f}{'↓' if float(r1['site_mape_clipped'])<float(r0['site_mape_clipped']) else '↑':>4} | "
              f"{v1_cr:>9.1f}{'↓' if v1d_cr<v1_cr else '↑':>4} | {n200_s:>20}")

    # >200% sites
    total_gt200 = {
        "V0": int(eV0["n_gt200"].sum()),
        "V1": int(eV1["n_gt200"].sum()),
        "V1DD": int(eV1dd["n_gt200"].sum()),
    }
    print(f"\n>200% 站点小时总数:")
    print(f"  V0={total_gt200['V0']} V1={total_gt200['V1']} V1+DD={total_gt200['V1DD']}")

    # ── Decide best version ─────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("版本选择")
    print("=" * 70)

    # Primary criterion: city_rel_err improvement
    # Secondary: WAPE not恶化, clipped_MAPE not恶化, >200% not increase
    candidates = {
        "V1": (gV1["city_rel_err"], gV1["WAPE"], gV1["clipped_MAPE"], total_gt200["V1"]),
        "V1+DD_safe": (gV1dd["city_rel_err"], gV1dd["WAPE"], gV1dd["clipped_MAPE"], total_gt200["V1DD"]),
    }
    best_name = min(candidates, key=lambda k: candidates[k][0])
    best = candidates[best_name]

    print(f"\n  city_rel_err: V1={gV1['city_rel_err']:.1f}% V1+DD={gV1dd['city_rel_err']:.1f}%")
    print(f"  WAPE:         V1={gV1['WAPE']:.1f}% V1+DD={gV1dd['WAPE']:.1f}%")
    print(f"  clipped_MAPE: V1={gV1['clipped_MAPE']:.1f}% V1+DD={gV1dd['clipped_MAPE']:.1f}%")
    print(f"  >200%:        V1={total_gt200['V1']} V1+DD={total_gt200['V1DD']}")
    print(f"\n  推荐: {best_name} (city_rel_err={best[0]:.1f}%)")

    # Save best prediction
    print("\n" + "=" * 70)
    print("[6] 保存最终预测 …")
    df_full = df.copy()
    if best_name == "V1":
        pred_col = "pred_V1"
    else:
        pred_col = "pred_V1DD_safe"

    # Merge V1DD_safe predictions
    v1dd_map = test.set_index(["time", "site_id"])["pred_V1DD_safe"].to_dict()
    v1_map = test.set_index(["time", "site_id"])["pred_V1"].to_dict()

    # Apply V1 or V1+DD based on best
    df_full["power_pred_final"] = df_full["power_pred"].copy()
    for idx in test.index:
        t, sid = test.loc[idx, "time"], test.loc[idx, "site_id"]
        if best_name == "V1DD_safe":
            val = v1dd_map.get((t, sid))
            if val is not None:
                df_full.loc[idx, "power_pred_final"] = val
        else:
            val = v1_map.get((t, sid))
            if val is not None:
                df_full.loc[idx, "power_pred_final"] = val

    # Save V1+DD table for reference
    df_full["power_pred_V1DD"] = df_full["power_pred"].copy()
    for idx in test.index:
        t, sid = test.loc[idx, "time"], test.loc[idx, "site_id"]
        val = v1dd_map.get((t, sid))
        if val is not None:
            df_full.loc[idx, "power_pred_V1DD"] = val

    out_v1dd = TABLES / "distributed_predictions_fixed_full_v1_dd.pkl"
    df_full.to_pickle(out_v1dd)
    print(f"  V1+DD 表已保存: {out_v1dd}")

    # Save the best version as the primary output
    df_best = df_full.copy()
    df_best["power_pred"] = df_best["power_pred_final"]
    out_best = TABLES / "distributed_predictions_fixed_full_v4.pkl"
    df_best.to_pickle(out_best)
    print(f"  最终预测已保存: {out_best}")

    # Also update the original fixed_full to use V1+DD if that's best
    if best_name == "V1DD_safe":
        df_fixed = df.copy()
        for idx in test.index:
            t, sid = test.loc[idx, "time"], test.loc[idx, "site_id"]
            val = v1dd_map.get((t, sid))
            if val is not None:
                df_fixed.loc[idx, "power_pred"] = val
        df_fixed.to_pickle(TABLES / "distributed_predictions_fixed_full.pkl")
        print(f"  ✓ 已更新 fixed_full.pkl 使用 {best_name} 预测")

    # Save comparison CSV
    merge = eV0.copy()
    for col in ["site_mape_raw_mean", "site_mape_raw_median", "site_mape_clipped",
                "site_wape", "city_rel_err", "n_gt100", "n_gt200"]:
        merge = merge.rename(columns={col: f"V0_{col}"})
    eV1r = eV1.copy()
    for col in eV1r.columns:
        if col != "hour":
            eV1r = eV1r.rename(columns={col: f"V1_{col}"})
    eV1ddr = eV1dd.copy()
    for col in eV1ddr.columns:
        if col != "hour":
            eV1ddr = eV1ddr.rename(columns={col: f"V1DD_{col}"})
    merge = merge.merge(eV1r, on="hour").merge(eV1ddr, on="hour")
    for col in ["site_mape_raw_mean", "site_mape_clipped", "site_wape", "city_rel_err"]:
        merge[f"delta_V1_vs_V0"] = merge[f"V1_{col}"] - merge[f"V0_{col}"]
        merge[f"delta_V1DD_vs_V0"] = merge[f"V1DD_{col}"] - merge[f"V0_{col}"]
    merge.to_csv(METRICS / "v4_V1_vs_V1DD_comparison.csv", index=False, encoding="utf-8-sig")
    print(f"  对比 CSV: {METRICS / 'v4_V1_vs_V1DD_comparison.csv'}")

    print("\nDone.")


if __name__ == "__main__":
    main()
