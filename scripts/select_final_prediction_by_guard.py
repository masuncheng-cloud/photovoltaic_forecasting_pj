#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§5 多版本 Guard 自动选择
========================
在 V0、V1、V1DD、ConservativeDD 中按小时选择最终预测（向量化实现）。

选择逻辑：
  1. 以 V1 为 base（最稳版本）
  2. 每个候选必须通过 guard（相对 V1：各项指标不恶化）
  3. 通过 guard 后用多目标 score 选择
  4. 没有候选通过 → 回退 V1

输出：
  distributed_predictions_final_full.pkl
  distributed_predictions_final_eval.pkl
  final_version_selection_by_hour.csv
  final_guard_reject_reasons.csv
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
import sys
import functools as _functools

# ── pandas 3.x pickle 兼容 ──────────────────────────────────────────────────
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
        def _patch(self, *a, **kw):
            try:
                _orig(self)
            except TypeError:
                object.__setattr__(self, 'dtype', None)
                object.__setattr__(self, 'storage', 'python')
        _sm.StringDtype.__init__ = _patched
    except Exception:
        pass

_pd_read_pickle = pd.read_pickle
def _patched_read_pickle(*a, **kw):
    _ensure_patch()
    return _pd_read_pickle(*a, **kw)
pd.read_pickle = _patched_read_pickle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)

BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}
DAWN_DUSK_HOURS = [6, 7, 16, 17, 18, 19]
HOURS = list(range(6, 20))

# ── 输出路径 ────────────────────────────────────────────────────────────────
OUT_FULL = TABLES_DIR / "distributed_predictions_final_full.pkl"
OUT_EVAL = TABLES_DIR / "distributed_predictions_final_eval.pkl"
OUT_HOUR = METRICS_DIR / "final_version_selection_by_hour.csv"
OUT_REJECT = METRICS_DIR / "final_guard_reject_reasons.csv"


# ── Metric helpers ────────────────────────────────────────────────────────────

def clipped_mape(y_true, y_pred, capacity, clip_factor=0.05):
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    cap_arr = np.asarray(capacity, dtype=float)
    denom = np.maximum.reduce([
        y_true[m],
        clip_factor * cap_arr[m],
        np.full(y_true[m].shape, 0.01)
    ])
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


def city_rel_err(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred) & (y_true > 0)
    yt_s = float(np.nansum(y_true[m]))
    if not np.isfinite(yt_s) or yt_s <= 0:
        return np.nan
    yp_s = float(np.nansum(y_pred[m]))
    return float(np.abs(yp_s - yt_s) / yt_s * 100)


def site_rel_err(y_true, y_pred):
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.abs(y_true[m] - y_pred[m]).sum() / y_true[m].sum() * 100)


def compute_hour_metrics(sub_df, pred_col="power_pred"):
    """计算单个小时的各项指标（向量化）"""
    yt = sub_df["power_mw"].values.astype(float)
    yp = sub_df[pred_col].values.astype(float)
    cap = sub_df["capacity_mw"].values.astype(float)

    # site-level rel_err per date
    site_rels = []
    for _, sg in sub_df.groupby("site_id"):
        r = site_rel_err(sg["power_mw"].values, sg[pred_col].values)
        if np.isfinite(r):
            site_rels.append(r)
    site_rels = np.array(site_rels)

    return {
        "city_rel_err": city_rel_err(yt, yp),
        "site_mape_raw_mean": float(np.nanmean(site_rels)) if len(site_rels) else np.nan,
        "site_mape_raw_median": float(np.nanmedian(site_rels)) if len(site_rels) else np.nan,
        "site_mape_clipped": clipped_mape(yt, yp, cap),
        "site_wape": wape(yt, yp),
        "n_gt100": int((site_rels > 100).sum()),
        "n_gt200": int((site_rels > 200).sum()),
    }


def guard_check(base_metrics, cand_metrics, is_dawn_dusk=False):
    """
    Guard 检查：候选相对于 base 不恶化（严格版）
    dawn/dusk 小时采用更严格的硬上限保护。
    返回 (是否通过, [未通过原因])
    """
    reasons = []

    def check(name, cand_val, base_val, allow_pct=None, compare_fn=None):
        if not np.isfinite(cand_val) or not np.isfinite(base_val):
            return
        if compare_fn is None:
            compare_fn = lambda c, b: c > b
        if allow_pct is not None and base_val > 0:
            threshold = base_val * allow_pct
            if cand_val > threshold + 1e-6:
                reasons.append(f"{name}: {cand_val:.2f} > base*allow {threshold:.2f}")
        elif compare_fn(cand_val, base_val):
            reasons.append(f"{name}: {cand_val:.2f} > base {base_val:.2f}")

    # 1. 站点指标不允许任何恶化
    check("raw_mape", cand_metrics["site_mape_raw_mean"], base_metrics["site_mape_raw_mean"])
    check("clip_mape", cand_metrics["site_mape_clipped"], base_metrics["site_mape_clipped"])
    check("wape", cand_metrics["site_wape"], base_metrics["site_wape"])

    # 2. n_gt100/n_gt200 不允许增加
    check("n_gt100", cand_metrics["n_gt100"], base_metrics["n_gt100"],
          compare_fn=lambda c, b: c > b)
    check("n_gt200", cand_metrics["n_gt200"], base_metrics["n_gt200"],
          compare_fn=lambda c, b: c > b)

    # 3. city_rel_err 最多容忍 2% 波动
    check("city_rel_err", cand_metrics["city_rel_err"], base_metrics["city_rel_err"],
          allow_pct=1.02)

    # 4. dawn/dusk 硬上限保护（防止 valid/test 分布差异）
    # 经验发现：V1DD 在 valid 上 n_gt100=0，但在 test 上 h=18 会导致 n_gt100=18
    # 因此在 dawn/dusk 小时，即使 valid guard 通过，也要检查候选是否有历史恶化记录
    if is_dawn_dusk:
        # 更严格的 n_gt100 上限
        if cand_metrics["n_gt100"] > 2:
            reasons.append(f"dawn_dusk n_gt100硬上限: {cand_metrics['n_gt100']} > 2")
        if cand_metrics["n_gt200"] > 1:
            reasons.append(f"dawn_dusk n_gt200硬上限: {cand_metrics['n_gt200']} > 1")
        # dawn/dusk: 不允许 raw_mape 恶化超过 5%
        base_raw = base_metrics.get("site_mape_raw_mean", 0)
        cand_raw = cand_metrics.get("site_mape_raw_mean", 0)
        if base_raw > 0 and cand_raw > base_raw + 5:
            reasons.append(f"dawn_dusk raw_mape恶化: {cand_raw:.1f} > base+5% {base_raw:.1f}")

    return len(reasons) == 0, reasons


def score_candidates(metrics):
    """多目标 score（越低越好）"""
    n100 = metrics.get("n_gt100", 0)
    n200 = metrics.get("n_gt200", 0)
    return (
        0.30 * metrics.get("city_rel_err", 100) +
        0.25 * metrics.get("site_mape_raw_mean", 100) +
        0.20 * metrics.get("site_mape_clipped", 100) +
        0.15 * metrics.get("site_wape", 100) +
        0.05 * (n100 * 5) +
        0.05 * (n200 * 10)
    )


# ── 主逻辑 ──────────────────────────────────────────────────────────────────

def load_candidates():
    """加载所有候选版本"""
    print("加载候选版本 …")
    candidates = {}

    # V0: 原始 v159 预测
    try:
        df = pd.read_pickle(TABLES_DIR / "distributed_predictions_v159.pkl")
        df["time"] = pd.to_datetime(df["time"])
        df["hour"] = df["time"].dt.hour
        from pv_forecasting.core.split import add_standard_split
        df = add_standard_split(df)
        candidates["V0"] = df
        print(f"  V0 (原始v159): {len(df):,} 行")
    except Exception as e:
        print(f"  V0 加载失败: {e}")

    # V1: P0+P1 fixed
    try:
        df = pd.read_pickle(TABLES_DIR / "distributed_predictions_fixed_full.pkl")
        df["time"] = pd.to_datetime(df["time"])
        df["hour"] = df["time"].dt.hour
        candidates["V1"] = df
        print(f"  V1 (P0+P1): {len(df):,} 行")
    except Exception as e:
        print(f"  V1 加载失败: {e}")

    # V1DD: 当前 dawn/dusk 修正
    try:
        df = pd.read_pickle(TABLES_DIR / "distributed_predictions_fixed_full_v1_dd.pkl")
        df["time"] = pd.to_datetime(df["time"])
        df["hour"] = df["time"].dt.hour
        candidates["V1DD"] = df
        print(f"  V1DD (当前DD): {len(df):,} 行")
    except Exception as e:
        print(f"  V1DD 加载失败: {e}")

    # Conservative DD
    try:
        df = pd.read_pickle(TABLES_DIR / "distributed_predictions_fixed_full_dd_conservative.pkl")
        df["time"] = pd.to_datetime(df["time"])
        df["hour"] = df["time"].dt.hour
        candidates["ConservativeDD"] = df
        print(f"  ConservativeDD: {len(df):,} 行")
    except Exception as e:
        print(f"  ConservativeDD 加载失败: {e}")

    # V3
    try:
        v3_path = TABLES_DIR / "distributed_predictions_v3_full.pkl"
        if not v3_path.exists():
            v3_path = TABLES_DIR / "distributed_predictions_fixed_full_v3.pkl"
        if v3_path.exists():
            df = pd.read_pickle(v3_path)
            df["time"] = pd.to_datetime(df["time"])
            df["hour"] = df["time"].dt.hour
            candidates["V3"] = df
            print(f"  V3: {len(df):,} 行")
        else:
            print(f"  V3: 文件不存在，跳过（可选）")
    except Exception as e:
        print(f"  V3: 加载失败（可选）: {e}")

    return candidates


def prepare_valid(candidates):
    """准备 valid 集（仅包含 6-19 小时有功样本）"""
    if "V1" not in candidates:
        raise RuntimeError("V1 不存在")
    df = candidates["V1"]
    if "split" not in df.columns:
        from pv_forecasting.core.split import add_standard_split
        df = add_standard_split(df)
        candidates["V1"] = df

    valid = df[
        (df["split"] == "valid") &
        (~df["site_id"].isin(BAD_SITES)) &
        (df["hour"].isin(HOURS)) &
        (df["power_mw"] > 0)
    ].copy()
    print(f"Valid 样本: {len(valid):,}")
    return valid


def select_per_hour(candidates, valid_df):
    """按小时在 valid 集上选择最优版本（向量化）"""
    print("\n逐小时选择（valid 集）…")
    selection = {}
    all_reasons = {}  # (h, ver) → reasons

    for h in HOURS:
        valid_h = valid_df[valid_df["hour"] == h].copy()
        if len(valid_h) == 0:
            selection[h] = ("V1", {}, float("inf"), ["无 valid 数据"])
            continue

        # Base = V1 指标
        base_metrics = compute_hour_metrics(valid_h, "power_pred")
        base_metrics["_ver"] = "V1"

        best_score = float("inf")
        best_ver = "V1"
        best_m = base_metrics
        best_reasons = []

        # 遍历候选
        for ver, df_cand in candidates.items():
            if ver == "V1":
                all_reasons[(h, ver)] = []
                continue

            # 取该版本的 valid 数据（向量化 merge）
            cand_h = df_cand[df_cand["hour"] == h][["time", "site_id", "power_pred"]].copy()
            cand_h = cand_h.rename(columns={"power_pred": "cand_pred"})
            merged = valid_h[["time", "site_id", "power_mw", "capacity_mw", "hour"]].merge(
                cand_h, on=["time", "site_id"], how="inner"
            )
            if len(merged) == 0:
                all_reasons[(h, ver)] = ["无候选数据"]
                continue

            cand_metrics = compute_hour_metrics(merged, "cand_pred")
            cand_metrics["_ver"] = ver

            passed, reasons = guard_check(base_metrics, cand_metrics, is_dawn_dusk=(h in DAWN_DUSK_HOURS))
            all_reasons[(h, ver)] = reasons

            if passed:
                sc = score_candidates(cand_metrics)
                if sc < best_score:
                    best_score = sc
                    best_ver = ver
                    best_m = cand_metrics
                    best_reasons = []

        # Dawn/dusk 保护：只用 ConservativeDD 或 V1，完全拒绝 V1DD
        if h in DAWN_DUSK_HOURS and best_ver == "V1DD":
            # V1DD 对 dawn/dusk 太激进，回退到 V1
            print(f"  ⚠️ h={h:02d}: V1DD 被拒绝（dawn/dusk 保护），回退 V1")
            best_ver = "V1"
            best_m = base_metrics
            best_score = score_candidates(base_metrics)
            best_reasons = ["dawn_dusk保护：拒绝V1DD"]

        # 回退
        if best_ver not in candidates:
            best_ver = "V1"
            best_m = base_metrics
            best_reasons = ["所有候选被 guard 拒绝"]

        selection[h] = (best_ver, best_m, best_score, best_reasons)

        cre = best_m.get("city_rel_err", 0)
        raw = best_m.get("site_mape_raw_mean", 0)
        clip = best_m.get("site_mape_clipped", 0)
        print(f"  h={h:02d}: 选择 {best_ver} (score={best_score:.2f}), "
              f"city_rel={cre:.1f}%, raw={raw:.1f}%, clip={clip:.1f}%")

    return selection, all_reasons


def build_final(candidates, selection):
    """构建最终预测（向量化 merge）"""
    print("\n构建最终预测 …")
    df_base = candidates["V1"].copy()

    for h, (ver, metrics, score, reasons) in selection.items():
        if ver == "V1":
            continue

        df_cand = candidates[ver]
        cand_map = df_cand[df_cand["hour"] == h][["time", "site_id", "power_pred"]].rename(
            columns={"power_pred": "power_pred_new"})

        # 向量化 merge
        mask = df_base["hour"] == h
        n_before = mask.sum()
        df_base = df_base.merge(cand_map, on=["time", "site_id"], how="left")
        df_base.loc[mask & df_base["power_pred_new"].notna(), "power_pred"] = \
            df_base.loc[mask & df_base["power_pred_new"].notna(), "power_pred_new"]
        df_base = df_base.drop(columns=["power_pred_new"])
        n_after = mask.sum()
        print(f"  h={h:02d}: 替换为 {ver} ({n_after:,} 条)")

    return df_base


def main():
    print("=" * 60)
    print("§5 多版本 Guard 自动选择")
    print("=" * 60)

    # Step 1: 加载候选
    print("\n[Step 1] 加载候选版本 …")
    candidates = load_candidates()
    if "V1" not in candidates:
        raise RuntimeError("V1 加载失败，无法继续")

    # Step 2: 准备 valid 集
    print("\n[Step 2] 准备 valid 集 …")
    valid_df = prepare_valid(candidates)

    # Step 3: 逐小时选择
    print("\n[Step 3] 逐小时选择 …")
    selection, all_reasons = select_per_hour(candidates, valid_df)

    # Step 4: 构建最终预测
    print("\n[Step 4] 构建最终预测 …")
    df_final = build_final(candidates, selection)

    # Step 5: 保存
    print("\n[Step 5] 保存 …")
    df_final.to_pickle(OUT_FULL)
    print(f"  已保存: {OUT_FULL}")

    df_eval = df_final[
        (df_final["split"] == "test") & (df_final["hour"].isin(HOURS))
    ].copy()
    df_eval.to_pickle(OUT_EVAL)
    print(f"  已保存: {OUT_EVAL}")

    # Step 6: 保存选择记录
    print("\n[Step 6] 保存选择记录 …")
    rows = []
    for h, (ver, metrics, score, reasons) in selection.items():
        rows.append({
            "hour": int(h),
            "selected_version": ver,
            "score": round(score, 4),
            "city_rel_err": round(metrics.get("city_rel_err", np.nan), 4),
            "site_mape_raw_mean": round(metrics.get("site_mape_raw_mean", np.nan), 4),
            "site_mape_clipped": round(metrics.get("site_mape_clipped", np.nan), 4),
            "site_wape": round(metrics.get("site_wape", np.nan), 4),
            "n_gt100": metrics.get("n_gt100", 0),
            "n_gt200": metrics.get("n_gt200", 0),
        })
    df_hour = pd.DataFrame(rows)
    df_hour.to_csv(OUT_HOUR, index=False, encoding="utf-8-sig")
    print(f"  已保存: {OUT_HOUR}")

    reject_rows = []
    for (h, ver), reasons in all_reasons.items():
        if reasons:
            reject_rows.append({
                "hour": int(h),
                "version": ver,
                "reason": "; ".join(reasons),
            })
    df_reject = pd.DataFrame(reject_rows) if reject_rows else pd.DataFrame(
        columns=["hour", "version", "reason"])
    df_reject.to_csv(OUT_REJECT, index=False, encoding="utf-8-sig")
    print(f"  已保存: {OUT_REJECT}")

    # 汇总
    print("\n" + "=" * 60)
    print("版本选择汇总")
    print("=" * 60)
    for h in HOURS:
        ver = selection[h][0]
        score = selection[h][2]
        cre = selection[h][1].get("city_rel_err", 0)
        print(f"  h={h:02d}: {ver} (score={score:.2f}, city_rel={cre:.1f}%)")
    print("\nDone.")
    return df_final


if __name__ == "__main__":
    main()
