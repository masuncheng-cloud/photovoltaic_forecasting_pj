#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复包E v2: 修复后全量评估（修正版）
===================================
修正点：
  - 统一使用 split=="test"（引用 split.py），不再手写日期筛选
  - 逐小时评估新增 WAPE、clipped_MAPE、bias 前后对比
  - 明确区分站点级预测列和城市级聚合预测列

修复前: distributed_predictions_v159.pkl (或 distributed_predictions.pkl)
修复后: distributed_predictions_fixed.pkl
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
import sys

# ─────────────────────────────────────────────
# pandas 3.x pickle 兼容 patch
# ─────────────────────────────────────────────
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
OUTPUT_ROOT = PROJECT_ROOT / "output" / "pv_pipeline"
TABLES_DIR = OUTPUT_ROOT / "tables"
METRICS_DIR = OUTPUT_ROOT / "metrics"
SITE_MASTER_PATH = TABLES_DIR / "site_master.csv"

BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}


def mape_raw(y_true, y_pred):
    mask = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any(): return np.nan
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / y_true[mask]) * 100)


def mape_clipped(y_true, y_pred, cap, floor_ratio=0.05):
    mask = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any(): return np.nan
    denom = np.maximum(y_true[mask], floor_ratio * cap[mask])
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / denom) * 100)


def wape(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred) & (y_true > 0)
    if not mask.any(): return np.nan
    return float(np.sum(np.abs(y_true[mask] - y_pred[mask])) / np.sum(np.abs(y_true[mask])) * 100)


def mae(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any(): return np.nan
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask])))


def rmse(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any(): return np.nan
    return float(np.sqrt(np.mean((y_true[mask] - y_pred[mask]) ** 2)))


def nrmse(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any(): return np.nan
    rng = y_true[mask].max() - y_true[mask].min()
    if rng == 0: return np.nan
    return float(np.sqrt(np.mean((y_true[mask] - y_pred[mask]) ** 2)) / rng)


def correlation(y_true, y_pred):
    mask = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any(): return np.nan
    return float(np.corrcoef(y_true[mask], y_pred[mask])[0, 1])


def bias_pct(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred) & (y_true > 0)
    if not mask.any(): return np.nan
    return float((np.sum(y_pred[mask]) - np.sum(y_true[mask])) / np.sum(y_true[mask]) * 100)


def compute_all_metrics(df, pred_col):
    y_true = pd.to_numeric(df["power_mw"], errors="coerce").fillna(0).to_numpy()
    y_pred = pd.to_numeric(df[pred_col], errors="coerce").fillna(0).to_numpy()
    elev = pd.to_numeric(df.get("solar_elevation_deg", pd.Series(0, index=df.index)),
                         errors="coerce").fillna(0).to_numpy()
    cap = pd.to_numeric(df.get("capacity_mw", pd.Series(1, index=df.index)),
                        errors="coerce").fillna(1).to_numpy()
    return {
        "MAPE_raw": mape_raw(y_true, y_pred),
        "MAPE_clipped": mape_clipped(y_true, y_pred, cap),
        "MAE": mae(y_true, y_pred),
        "RMSE": rmse(y_true, y_pred),
        "NRMSE": nrmse(y_true, y_pred),
        "Corr": correlation(y_true, y_pred),
        "WAPE": wape(y_true, y_pred),
        "bias_pct": bias_pct(y_true, y_pred),
        "pred_actual_ratio": float(np.sum(y_pred) / np.sum(y_true)) if np.sum(y_true) > 0 else np.nan,
        "n_samples": int((y_true > 0).sum()),
    }


def build_metric_compare(before, after):
    rows = []
    for metric in sorted(set(before) | set(after)):
        if metric == "n_samples": continue
        b, a = before.get(metric), after.get(metric)
        imp_abs = imp_pct = None
        if pd.notna(b) and pd.notna(a):
            if metric.lower() == "corr":
                imp_abs = a - b
                imp_pct = (a - b) / abs(b) * 100 if b != 0 else None
            else:
                imp_abs = b - a
                imp_pct = (b - a) / abs(b) * 100 if b != 0 else None
        rows.append({
            "metric": metric,
            "before": round(b, 4) if pd.notna(b) else None,
            "after": round(a, 4) if pd.notna(a) else None,
            "improvement_abs": round(imp_abs, 4) if imp_abs is not None else None,
            "improvement_pct": round(imp_pct, 2) if imp_pct is not None else None,
        })
    return pd.DataFrame(rows)


def _detect_is_full_table(df):
    """检测是否为完整表（未过滤小时）"""
    if "hour" not in df.columns:
        df["hour"] = pd.to_datetime(df["time"]).dt.hour
    # 如果 hour 范围包含 0-5 或 20-23，说明是完整表
    if df["hour"].min() < 6 or df["hour"].max() > 19:
        return True
    # 如果 row count 超过 eval 预期，也是完整表
    return False


def load_predictions():
    """加载修复前后预测，优先使用 eval 子集表"""
    # 修复前：使用原始预测（需要内部过滤）
    for bp in [TABLES_DIR / "distributed_predictions_v159.pkl",
               TABLES_DIR / "distributed_predictions.pkl"]:
        if bp.exists():
            before_path = bp
            break
    # 修复后：优先读最终表
    for ap in [TABLES_DIR / "distributed_predictions_final_eval.pkl",
               TABLES_DIR / "distributed_predictions_fixed_eval.pkl",
               TABLES_DIR / "distributed_predictions_fixed.pkl"]:
        if ap.exists():
            after_path = ap
            break
    print(f"修复前: {before_path}")
    print(f"修复后: {after_path}")
    df_before = pd.read_pickle(before_path)
    df_after = pd.read_pickle(after_path)

    is_full_after = _detect_is_full_table(df_after)
    if is_full_after:
        print("[WARN] 读取的是完整表，将内部重新应用评估过滤条件")
    else:
        print("[INFO] 使用评估子集表进行评估")

    if "power_pred_original" not in df_before.columns:
        df_before["power_pred_original"] = df_before["power_pred"]
    if "power_pred_original" not in df_after.columns:
        df_after["power_pred_original"] = df_after["power_pred"]
    return df_before, df_after, is_full_after


def prepare_data(df, is_full_table=False):
    """准备评估数据：统一 split + 评估过滤
    如果 is_full_table=True（读取了完整表），则内部重新应用评估过滤。
    """
    from pv_forecasting.core.split import add_standard_split
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    df["year"] = df["time"].dt.year
    df["month"] = df["time"].dt.month
    df["date"] = df["time"].dt.date
    df = add_standard_split(df)

    if is_full_table:
        # 读取了完整表，内部重新应用评估过滤
        df = df[
            (df["split"] == "test")
            & df["hour"].between(6, 19)
            & df["power_mw"].notna()
            & (df["power_mw"] > 0)
            & (~df["site_id"].isin(BAD_SITES))
        ].copy()
        print(f"  [内部重过滤后] {len(df):,} 行")
    else:
        # 读取的是 eval 子集表，只做 split 筛选
        df = df[df["split"] == "test"].copy()
    return df


def add_scene_label(df):
    df = df.copy()
    if "hour" not in df.columns:
        df["hour"] = pd.to_datetime(df["time"]).dt.hour

    def scene(h):
        if h in (6, 7): return "dawn"
        if h in (8, 9): return "morning"
        if h in (10, 11, 12, 13, 14): return "midday"
        if h in (15, 16): return "afternoon"
        if h in (17, 18, 19): return "dusk"
        return "night"
    df["scene_label_eval"] = df["hour"].map(scene)
    return df


def add_site_master_info(df):
    if SITE_MASTER_PATH.exists():
        sm = pd.read_csv(SITE_MASTER_PATH)
        info = sm[["site_id", "site_short_name", "county"]].drop_duplicates("site_id")
        if "county" in df.columns:
            df = df.drop(columns=["county"])
        df = df.merge(info, on="site_id", how="left")
    return df


def choose_pred_col(df, kind):
    if kind == "after":
        for c in ["power_pred_site_fixed", "power_pred_fixed", "power_pred"]:
            if c in df.columns:
                return c
    elif kind == "before":
        for c in ["power_pred_original", "power_pred_before", "power_pred"]:
            if c in df.columns:
                return c
    return "power_pred"


def evaluate_global(df_before, df_after):
    print("\n" + "=" * 60 + "\n全局评估\n" + "=" * 60)
    bc = choose_pred_col(df_before, "before")
    ac = choose_pred_col(df_after, "after")
    print(f"修复前列: {bc}  |  修复后列: {ac}")
    result = build_metric_compare(compute_all_metrics(df_before, bc), compute_all_metrics(df_after, ac))
    if not result.empty:
        print(result.to_string(index=False))
    return result


def evaluate_by_site(df_before, df_after):
    print("\n" + "=" * 60 + "\n按站点评估\n" + "=" * 60)
    rows = []
    for sid in sorted(set(df_before["site_id"].unique()) | set(df_after["site_id"].unique())):
        db, da = df_before[df_before["site_id"] == sid], df_after[df_after["site_id"] == sid]
        if not len(db) and not len(da): continue
        r = {"site_id": sid}
        if len(db): m = compute_all_metrics(db, "power_pred"); r.update({
            "before_MAPE_raw": m.get("MAPE_raw"), "before_MAPE_clipped": m.get("MAPE_clipped"),
            "before_WAPE": m.get("WAPE"), "before_MAE": m.get("MAE"),
            "before_bias_pct": m.get("bias_pct")})
        if len(da): m = compute_all_metrics(da, "power_pred"); r.update({
            "after_MAPE_raw": m.get("MAPE_raw"), "after_MAPE_clipped": m.get("MAPE_clipped"),
            "after_WAPE": m.get("WAPE"), "after_MAE": m.get("MAE"),
            "after_bias_pct": m.get("bias_pct")})
        if "before_MAPE_raw" in r and "after_MAPE_raw" in r:
            r["MAPE_raw_improvement"] = r["before_MAPE_raw"] - r["after_MAPE_raw"]
            r["MAPE_clipped_improvement"] = r["before_MAPE_clipped"] - r["after_MAPE_clipped"]
        if "before_WAPE" in r and "after_WAPE" in r:
            r["WAPE_improvement"] = r["before_WAPE"] - r["after_WAPE"]
        r["n_samples_before"] = len(db); r["n_samples_after"] = len(da)
        rows.append(r)
    result = pd.DataFrame(rows).sort_values("site_id").reset_index(drop=True)
    return result


def evaluate_by_county(df_before, df_after):
    print("\n" + "=" * 60 + "\n按县域评估\n" + "=" * 60)
    df_before = add_site_master_info(df_before)
    df_after = add_site_master_info(df_after)
    rows = []
    for c in sorted(set(df_before["county"].dropna().unique()) | set(df_after["county"].dropna().unique())):
        db, da = df_before[df_before["county"] == c], df_after[df_after["county"] == c]
        if not len(db) and not len(da): continue
        r = {"county": c}
        if len(db): m = compute_all_metrics(db, "power_pred"); r.update({
            "before_MAPE_raw": m.get("MAPE_raw"), "before_MAPE_clipped": m.get("MAPE_clipped"),
            "before_WAPE": m.get("WAPE"), "before_bias_pct": m.get("bias_pct")})
        if len(da): m = compute_all_metrics(da, "power_pred"); r.update({
            "after_MAPE_raw": m.get("MAPE_raw"), "after_MAPE_clipped": m.get("MAPE_clipped"),
            "after_WAPE": m.get("WAPE"), "after_bias_pct": m.get("bias_pct")})
        if "before_MAPE_raw" in r and "after_MAPE_raw" in r:
            r["MAPE_raw_improvement"] = r["before_MAPE_raw"] - r["after_MAPE_raw"]
            r["MAPE_clipped_improvement"] = r["before_MAPE_clipped"] - r["after_MAPE_clipped"]
        if "before_WAPE" in r and "after_WAPE" in r:
            r["WAPE_improvement"] = r["before_WAPE"] - r["after_WAPE"]
        r["n_sites_before"] = db["site_id"].nunique(); r["n_sites_after"] = da["site_id"].nunique()
        rows.append(r)
    return pd.DataFrame(rows).sort_values("county").reset_index(drop=True)


def evaluate_by_scene(df_before, df_after):
    print("\n" + "=" * 60 + "\n按场景评估\n" + "=" * 60)
    df_before = add_scene_label(df_before)
    df_after = add_scene_label(df_after)
    rows = []
    for s in ["dawn", "morning", "midday", "afternoon", "dusk", "night"]:
        db, da = df_before[df_before["scene_label_eval"] == s], df_after[df_after["scene_label_eval"] == s]
        if not len(db) and not len(da): continue
        r = {"scene": s}
        if len(db): m = compute_all_metrics(db, "power_pred"); r.update({
            "before_MAPE_raw": m.get("MAPE_raw"), "before_MAPE_clipped": m.get("MAPE_clipped"),
            "before_WAPE": m.get("WAPE"), "before_bias_pct": m.get("bias_pct")})
        if len(da): m = compute_all_metrics(da, "power_pred"); r.update({
            "after_MAPE_raw": m.get("MAPE_raw"), "after_MAPE_clipped": m.get("MAPE_clipped"),
            "after_WAPE": m.get("WAPE"), "after_bias_pct": m.get("bias_pct")})
        if "before_MAPE_raw" in r and "after_MAPE_raw" in r:
            r["MAPE_raw_improvement"] = r["before_MAPE_raw"] - r["after_MAPE_raw"]
            r["MAPE_clipped_improvement"] = r["before_MAPE_clipped"] - r["after_MAPE_clipped"]
        if "before_WAPE" in r and "after_WAPE" in r:
            r["WAPE_improvement"] = r["before_WAPE"] - r["after_WAPE"]
        r["n_samples_before"] = len(db); r["n_samples_after"] = len(da)
        rows.append(r)
    return pd.DataFrame(rows)


def evaluate_by_hour(df_before, df_after):
    print("\n" + "=" * 60 + "\n按时段评估（逐小时）\n" + "=" * 60)
    rows = []
    for h in range(6, 20):
        db, da = df_before[df_before["hour"] == h], df_after[df_after["hour"] == h]
        if not len(db) and not len(da): continue
        r = {"hour": h}
        if len(db):
            ca_b = db["power_mw"].sum(); cp_b = db["power_pred"].sum()
            r["city_actual_before"] = ca_b; r["city_pred_before"] = cp_b
            r["city_rel_err_before"] = abs(cp_b - ca_b) / ca_b * 100 if ca_b > 0 else np.nan
            m = compute_all_metrics(db, "power_pred")
            r.update({"before_MAPE_raw": m.get("MAPE_raw"), "before_MAPE_clipped": m.get("MAPE_clipped"),
                     "before_WAPE": m.get("WAPE"), "before_MAE": m.get("MAE"),
                     "before_bias_pct": m.get("bias_pct"), "before_Corr": m.get("Corr")})
        if len(da):
            ca_a = da["power_mw"].sum(); cp_a = da["power_pred"].sum()
            r["city_actual_after"] = ca_a; r["city_pred_after"] = cp_a
            r["city_rel_err_after"] = abs(cp_a - ca_a) / ca_a * 100 if ca_a > 0 else np.nan
            m = compute_all_metrics(da, "power_pred")
            r.update({"after_MAPE_raw": m.get("MAPE_raw"), "after_MAPE_clipped": m.get("MAPE_clipped"),
                     "after_WAPE": m.get("WAPE"), "after_MAE": m.get("MAE"),
                     "after_bias_pct": m.get("bias_pct"), "after_Corr": m.get("Corr")})
        if "city_rel_err_before" in r and "city_rel_err_after" in r:
            r["city_rel_err_improvement"] = r["city_rel_err_before"] - r["city_rel_err_after"]
            r["city_rel_improved"] = r["city_rel_err_after"] < r["city_rel_err_before"]
        for metric in ["WAPE", "MAPE_clipped", "MAPE_raw"]:
            bk, ak = f"before_{metric}", f"after_{metric}"
            if bk in r and ak in r:
                r[f"{metric}_improvement"] = r[bk] - r[ak]
                r[f"{metric}_improved"] = r[ak] < r[bk]
        r["n_samples_before"] = len(db); r["n_samples_after"] = len(da)
        rows.append(r)
    return pd.DataFrame(rows)


def evaluate_by_period(df_before, df_after):
    print("\n" + "=" * 60 + "\n按时段汇总\n" + "=" * 60)
    period_map = {
        "dawn (6-7)": [6, 7], "morning (8-9)": [8, 9],
        "midday (10-14)": [10, 11, 12, 13, 14],
        "afternoon (15-16)": [15, 16], "dusk (17-19)": [17, 18, 19],
    }
    rows = []
    for name, hrs in period_map.items():
        db, da = df_before[df_before["hour"].isin(hrs)], df_after[df_after["hour"].isin(hrs)]
        if not len(db) and not len(da): continue
        r = {"period": name, "hours": str(hrs)}
        if len(db):
            ca_b = db["power_mw"].sum(); cp_b = db["power_pred"].sum()
            r["city_rel_err_before"] = abs(cp_b - ca_b) / ca_b * 100 if ca_b > 0 else np.nan
            m = compute_all_metrics(db, "power_pred")
            r["before_MAPE_raw"] = m.get("MAPE_raw"); r["before_MAPE_clipped"] = m.get("MAPE_clipped")
            r["before_WAPE"] = m.get("WAPE")
        if len(da):
            ca_a = da["power_mw"].sum(); cp_a = da["power_pred"].sum()
            r["city_rel_err_after"] = abs(cp_a - ca_a) / ca_a * 100 if ca_a > 0 else np.nan
            m = compute_all_metrics(da, "power_pred")
            r["after_MAPE_raw"] = m.get("MAPE_raw"); r["after_MAPE_clipped"] = m.get("MAPE_clipped")
            r["after_WAPE"] = m.get("WAPE")
        if "city_rel_err_before" in r and "city_rel_err_after" in r:
            r["city_rel_err_improvement"] = r["city_rel_err_before"] - r["city_rel_err_after"]
        r["n_samples_before"] = len(db); r["n_samples_after"] = len(da)
        rows.append(r)
    # 总计
    ca_b = df_before["power_mw"].sum(); cp_b = df_before["power_pred"].sum()
    ca_a = df_after["power_mw"].sum(); cp_a = df_after["power_pred"].sum()
    rows.append({"period": "Overall", "hours": "6-19",
                 "city_rel_err_before": abs(cp_b - ca_b) / ca_b * 100 if ca_b > 0 else np.nan,
                 "city_rel_err_after": abs(cp_a - ca_a) / ca_a * 100 if ca_a > 0 else np.nan,
                 "n_samples_before": len(df_before), "n_samples_after": len(df_after)})
    return pd.DataFrame(rows)


def evaluate_city_hourly(df_before, df_after):
    print("\n" + "=" * 60 + "\n城市逐小时聚合评估\n" + "=" * 60)
    agg_b = df_before.groupby(["date", "hour"]).agg(
        city_actual=("power_mw", "sum"),
        city_pred_before=("power_pred", "sum"),
        n_sites=("site_id", "nunique")).reset_index()
    agg_a = df_after.groupby(["date", "hour"]).agg(
        city_pred_after=("power_pred", "sum")).reset_index()
    merged = agg_b.merge(agg_a, on=["date", "hour"], how="outer")
    rows = []
    for h in range(6, 20):
        sub = merged[merged["hour"] == h]
        if not len(sub): continue
        am = sub["city_actual"].mean()
        pb = sub["city_pred_before"].mean()
        pa = sub.get("city_pred_after", pd.Series()).mean()
        if pd.isna(pa): pa = np.nan
        rb = abs(pb - am) / am * 100 if am > 0 else np.nan
        ra = abs(pa - am) / am * 100 if am > 0 and not np.isnan(pa) else np.nan
        rows.append({"hour": h, "city_actual_mean": am, "city_pred_before_mean": pb,
                     "city_pred_after_mean": pa, "city_rel_err_before": rb,
                     "city_rel_err_after": ra,
                     "city_rel_err_improvement": rb - ra if not np.isnan(ra) else np.nan,
                     "n_dates": len(sub)})
    return pd.DataFrame(rows)


def main():
    print("=" * 60 + "\n修复后全量评估 (v2)\n" + "=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    METRICS_DIR.mkdir(parents=True, exist_ok=True)

    print("\n加载数据...")
    df_before, df_after, is_full = load_predictions()
    print(f"修复前: {len(df_before):,} 行  |  修复后: {len(df_after):,} 行")

    print("\n准备数据（split=='test'）...")
    df_before = prepare_data(df_before, is_full_table=True)
    df_after = prepare_data(df_after, is_full_table=is_full)
    print(f"筛选后 修复前: {len(df_before):,}  |  修复后: {len(df_after):,}")

    METRICS_DIR.mkdir(parents=True, exist_ok=True)

    # 评估
    df_global = evaluate_global(df_before, df_after)
    df_global.to_csv(METRICS_DIR / "distributed_metrics_fixed.csv", index=False, encoding="utf-8-sig")
    print(f"\n已保存: {METRICS_DIR / 'distributed_metrics_fixed.csv'}")

    df_site = evaluate_by_site(df_before, df_after)
    df_site.to_csv(METRICS_DIR / "distributed_metrics_by_site_fixed.csv", index=False, encoding="utf-8-sig")
    print(f"已保存: {METRICS_DIR / 'distributed_metrics_by_site_fixed.csv'}")

    df_county = evaluate_by_county(df_before, df_after)
    df_county.to_csv(METRICS_DIR / "distributed_metrics_by_county_fixed.csv", index=False, encoding="utf-8-sig")
    print(f"已保存: {METRICS_DIR / 'distributed_metrics_by_county_fixed.csv'}")

    df_scene = evaluate_by_scene(df_before, df_after)
    df_scene.to_csv(METRICS_DIR / "distributed_metrics_by_scene_fixed.csv", index=False, encoding="utf-8-sig")
    print(f"已保存: {METRICS_DIR / 'distributed_metrics_by_scene_fixed.csv'}")

    df_hour = evaluate_by_hour(df_before, df_after)
    df_hour.to_csv(METRICS_DIR / "distributed_metrics_by_hour_fixed.csv", index=False, encoding="utf-8-sig")
    print(f"已保存: {METRICS_DIR / 'distributed_metrics_by_hour_fixed.csv'}")

    df_period = evaluate_by_period(df_before, df_after)
    df_period.to_csv(METRICS_DIR / "period_error_before_after.csv", index=False, encoding="utf-8-sig")
    print(f"已保存: {METRICS_DIR / 'period_error_before_after.csv'}")

    df_city = evaluate_city_hourly(df_before, df_after)
    df_city.to_csv(METRICS_DIR / "city_hourly_total_error_before_after.csv", index=False, encoding="utf-8-sig")
    print(f"已保存: {METRICS_DIR / 'city_hourly_total_error_before_after.csv'}")

    print("\n" + "=" * 60 + "\n摘要\n" + "=" * 60)
    cols = ["metric", "before", "after", "improvement_abs", "improvement_pct"]
    print(df_global[[c for c in cols if c in df_global.columns]].to_string(index=False))
    print()
    print(df_period.to_string(index=False))

    print("\n" + "=" * 60 + "\n评估完成\n" + "=" * 60)


if __name__ == "__main__":
    main()
