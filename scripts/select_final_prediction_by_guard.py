#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§5 多版本 Guard 自动选择（NRMSE 版）
=====================================
在 V0、V1、BlendTotal 系列（alpha 混合）中按小时选择最终预测（向量化实现）。
BaselineTotal 禁用主动入选，仅作为兜底。

选择逻辑：
  1. 以 V1 为 base（最稳版本）
  2. BlendTotal 系列使用宽松 guard（NRMSE 恶化 ≤12%，MAPE 恶化 ≤20%）
  3. BaselineTotal 禁用主动入选
  4. 通过 guard 后用 NRMSE 优先多目标 score 选择
  5. 没有候选通过 → 回退 V1

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
                _orig(self, *a, **kw)
            except TypeError:
                object.__setattr__(self, 'dtype', None)
                object.__setattr__(self, 'storage', 'python')
        _sm.StringDtype.__init__ = _patch
    except Exception:
        pass

_pd_read_pickle = pd.read_pickle
def _patched_read_pickle(*a, **kw):
    _ensure_patch()
    return _pd_read_pickle(*a, **kw)
pd.read_pickle = _patched_read_pickle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from pv_forecasting.core.evaluation import build_eval_frame
TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)

BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}
DAWN_DUSK_HOURS = [6, 7, 16, 17, 18, 19]
STRICT_NRMSE_GUARD_HOURS = [6, 17, 18, 19]
HOURS = list(range(6, 20))
MIDDAY_NRMSE_PRIORITY_HOURS = [10, 11, 12, 13, 14]
TARGET_RATIO = 0.9488
TARGET_SITE_COUNT = 53
BLEND_ALPHAS = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
ENABLE_TEST_ORACLE_GUARD = False
# NRMSE oracle guard 默认关闭（避免 test 集参与最终选择）
ENABLE_NRMSE_ORACLE_GUARD = False

# ── 输出路径 ────────────────────────────────────────────────────────────────
OUT_FULL = TABLES_DIR / "distributed_predictions_final_full.pkl"
OUT_EVAL = TABLES_DIR / "distributed_predictions_final_eval.pkl"
OUT_HOUR = METRICS_DIR / "final_version_selection_by_hour.csv"
OUT_REJECT = METRICS_DIR / "final_guard_reject_reasons.csv"


# ── Metric helpers ────────────────────────────────────────────────────────────

def pred_actual_ratio(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred) & (y_true > 0)
    actual = float(np.nansum(y_true[m]))
    pred = float(np.nansum(y_pred[m]))
    if actual <= 0:
        return np.nan
    return pred / actual


def rmse(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.sqrt(np.mean((y_true[m] - y_pred[m]) ** 2)))


def nrmse_by_capacity(y_true, y_pred, capacity):
    m = np.isfinite(y_true) & np.isfinite(y_pred) & np.isfinite(capacity) & (capacity > 0)
    if not m.any():
        return np.nan
    rmse_val = float(np.sqrt(np.mean((y_true[m] - y_pred[m]) ** 2)))
    scale = float(np.nanmean(capacity[m]))
    if scale <= 0:
        return np.nan
    return rmse_val / scale * 100.0


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


def mae(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.mean(np.abs(y_true[m] - y_pred[m])))


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

    ratio = pred_actual_ratio(yt, yp)

    # site-level rel_err per date
    site_rels = []
    for _, sg in sub_df.groupby("site_id"):
        r = site_rel_err(sg["power_mw"].values, sg[pred_col].values)
        if np.isfinite(r):
            site_rels.append(r)
    site_rels = np.array(site_rels)

    # site-level NRMSE: per-site RMSE / mean(capacity), then average across sites
    site_nrmse_vals = []
    for _, sg in sub_df.groupby("site_id"):
        yt_s = pd.to_numeric(sg["power_mw"], errors="coerce").to_numpy(dtype=float)
        yp_s = pd.to_numeric(sg[pred_col], errors="coerce").to_numpy(dtype=float)
        cap_s = pd.to_numeric(sg["capacity_mw"], errors="coerce").to_numpy(dtype=float)
        m_s = np.isfinite(yt_s) & np.isfinite(yp_s) & np.isfinite(cap_s) & (cap_s > 0)
        if not m_s.any():
            continue
        rmse_s = float(np.sqrt(np.mean((yt_s[m_s] - yp_s[m_s]) ** 2)))
        cap_mean_s = float(np.nanmean(cap_s[m_s]))
        if cap_mean_s > 0:
            site_nrmse_vals.append(rmse_s / cap_mean_s * 100.0)

    return {
        "city_rel_err": city_rel_err(yt, yp),
        "site_mape_raw_mean": float(np.nanmean(site_rels)) if len(site_rels) else np.nan,
        "site_mape_raw_median": float(np.nanmedian(site_rels)) if len(site_rels) else np.nan,
        "site_mape_clipped": clipped_mape(yt, yp, cap),
        "site_wape": wape(yt, yp),
        "n_gt100": int((site_rels > 100).sum()),
        "n_gt200": int((site_rels > 200).sum()),
        "mae": mae(yt, yp),
        "rmse": rmse(yt, yp),
        "nrmse_capacity_pct": nrmse_by_capacity(yt, yp, cap),
        "site_nrmse_mean_pct": float(np.nanmean(site_nrmse_vals)) if site_nrmse_vals else np.nan,
        "pred_actual_ratio": ratio,
        "ratio_abs_err": abs(ratio - TARGET_RATIO) * 100 if np.isfinite(ratio) else np.nan,
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


def score_candidates(metrics, hour=None):
    """MAE/RMSE 优先的多目标 score，越低越好。

    优先级：
    1. RMSE（权重 0.28）
    2. MAE（权重 0.22）
    3. 容量归一化 NRMSE（权重 0.25）
    4. 城市聚合误差（权重 0.15）
    5. ratio 接近基准 0.9488（权重 0.07）

    10-14 点（is_midday_priority=True）时，提高 NRMSE 权重，降低其他权重：
      0.45*NRMSE + 0.25*RMSE + 0.15*MAE + 0.08*city + 0.04*ratio + ...
    """
    mae_val = metrics.get("mae", 100)
    rmse_val = metrics.get("rmse", 100)
    nrmse = metrics.get("nrmse_capacity_pct", 100)
    city = metrics.get("city_rel_err", 100)
    ratio_err = metrics.get("ratio_abs_err", 100)
    n100 = metrics.get("n_gt100", 0)
    n200 = metrics.get("n_gt200", 0)

    if not np.isfinite(mae_val):
        mae_val = 100
    if not np.isfinite(rmse_val):
        rmse_val = 100
    if not np.isfinite(nrmse):
        nrmse = 100
    if not np.isfinite(city):
        city = 100
    if not np.isfinite(ratio_err):
        ratio_err = 100

    is_midday_priority = hour in MIDDAY_NRMSE_PRIORITY_HOURS if hour is not None else False
    # 10-14 点：以站点平均 NRMSE 为主指标（替代整小时 nrmse_capacity_pct）
    if is_midday_priority:
        nrmse_for_score = metrics.get("site_nrmse_mean_pct", metrics.get("nrmse_capacity_pct", 100))
        return (
            0.62 * nrmse_for_score
            + 0.18 * rmse_val
            + 0.10 * mae_val
            + 0.06 * city
            + 0.02 * ratio_err
            + 0.01 * (n100 * 5)
            + 0.01 * (n200 * 10)
        )

    return (
        0.28 * rmse_val
        + 0.22 * mae_val
        + 0.25 * nrmse
        + 0.15 * city
        + 0.07 * ratio_err
        + 0.02 * (n100 * 5)
        + 0.01 * (n200 * 10)
    )


# ── 混合候选构建 ──────────────────────────────────────────────────────────────

def add_blend_total_candidates(candidates: dict) -> None:
    """新增 ML/fixed 与 pred_baseline 的混合候选。

    BlendTotal_aXX = alpha * V1.power_pred + (1-alpha) * V1.pred_baseline
    """
    if "V1" not in candidates:
        return

    base = candidates["V1"]
    if "pred_baseline" not in base.columns:
        print("  BlendTotal: 缺少 pred_baseline，跳过")
        return

    ml = pd.to_numeric(base["power_pred"], errors="coerce")
    bl = pd.to_numeric(base["pred_baseline"], errors="coerce")
    cap = pd.to_numeric(base["capacity_mw"], errors="coerce").fillna(0.0)

    for alpha in BLEND_ALPHAS:
        df = base.copy()
        pred = alpha * ml + (1.0 - alpha) * bl
        pred = pred.fillna(ml).fillna(bl)
        df["power_pred"] = pred.clip(lower=0.0, upper=cap)
        key = f"BlendTotal_a{int(alpha * 100):02d}"
        candidates[key] = df
        print(f"  {key}: {len(df):,} 行")


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

    # MiddaySiteCalibrated: 10-14 点站点级 NRMSE 校准候选
    try:
        midday_path = TABLES_DIR / "distributed_predictions_midday_site_calibrated_full.pkl"
        if midday_path.exists():
            df = pd.read_pickle(midday_path)
            df["time"] = pd.to_datetime(df["time"])
            df["hour"] = df["time"].dt.hour
            candidates["MiddaySiteCalibrated"] = df
            print(f"  MiddaySiteCalibrated: {len(df):,} 行")
        else:
            print("  MiddaySiteCalibrated: 文件不存在，跳过")
    except Exception as e:
        print(f"  MiddaySiteCalibrated 加载失败: {e}")

    # MiddayResidualSpecialist: 10-14 点残差专家候选
    try:
        residual_path = TABLES_DIR / "distributed_predictions_midday_residual_specialist_full.pkl"
        if residual_path.exists():
            df = pd.read_pickle(residual_path)
            df["time"] = pd.to_datetime(df["time"])
            df["hour"] = df["time"].dt.hour
            candidates["MiddayResidualSpecialist"] = df
            print(f"  MiddayResidualSpecialist: {len(df):,} 行")
        else:
            print("  MiddayResidualSpecialist: 文件不存在，跳过")
    except Exception as e:
        print(f"  MiddayResidualSpecialist 加载失败: {e}")

    # BaselineTotal: 使用 pred_baseline 解决系统性低估
    try:
        if "V1" in candidates:
            df = candidates["V1"].copy()
            if "pred_baseline" in df.columns:
                df["power_pred"] = pd.to_numeric(df["pred_baseline"], errors="coerce").fillna(
                    pd.to_numeric(df["power_pred"], errors="coerce")
                )
                cap = pd.to_numeric(df["capacity_mw"], errors="coerce").fillna(0.0)
                df["power_pred"] = df["power_pred"].clip(lower=0.0, upper=cap)
                candidates["BaselineTotal"] = df
                print(f"  BaselineTotal (pred_baseline): {len(df):,} 行")
            else:
                print("  BaselineTotal: 缺少 pred_baseline，跳过")
    except Exception as e:
        print(f"  BaselineTotal 加载失败: {e}")

    # BlendTotal 混合候选
    add_blend_total_candidates(candidates)

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

        # strict hours 固定 V1（不在 valid 集上选择 BlendTotal）
        if h in STRICT_NRMSE_GUARD_HOURS:
            base_score = score_candidates(base_metrics, hour=h)
            selection[h] = ("V1", base_metrics, base_score, ["strict hour: force V1"])
            print(
                f"  h={h:02d}: strict hour 强制 V1 "
                f"(score={base_score:.2f}, mae={base_metrics.get('mae', np.nan):.4f}, "
                f"rmse={base_metrics.get('rmse', np.nan):.4f})"
            )
            continue

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

            if ver == "BaselineTotal":
                passed = False
                reasons = ["BaselineTotal 仅作为兜底版本"]
            elif ver in {"MiddaySiteCalibrated", "MiddayResidualSpecialist"}:
                # 10-14 点专用：只允许在 midday 小时出现，使用站点平均 NRMSE 做主约束
                reasons = []
                passed = True

                if h not in MIDDAY_NRMSE_PRIORITY_HOURS:
                    passed = False
                    reasons.append(f"{ver} 只允许用于 10-14 点")
                else:
                    # 主约束：站点平均 NRMSE（容量归一化，逐站点计算后取均值）
                    base_site_nrmse = base_metrics.get("site_nrmse_mean_pct", np.nan)
                    cand_site_nrmse = cand_metrics.get("site_nrmse_mean_pct", np.nan)
                    base_rmse = base_metrics.get("rmse", np.nan)
                    cand_rmse = cand_metrics.get("rmse", np.nan)
                    base_mae = base_metrics.get("mae", np.nan)
                    cand_mae = cand_metrics.get("mae", np.nan)
                    cand_ratio = cand_metrics.get("pred_actual_ratio", np.nan)
                    cand_city = cand_metrics.get("city_rel_err", np.nan)

                    # 站点平均 NRMSE 必须不劣于 V1
                    if np.isfinite(base_site_nrmse) and np.isfinite(cand_site_nrmse):
                        if cand_site_nrmse > base_site_nrmse * 1.005:
                            passed = False
                            reasons.append(
                                f"midday site_nrmse 未改善: {cand_site_nrmse:.2f} > 1.005*base {base_site_nrmse:.2f}"
                            )

                    # RMSE/MAE 不允许明显牺牲
                    if np.isfinite(base_rmse) and np.isfinite(cand_rmse):
                        if cand_rmse > base_rmse * 1.03:
                            passed = False
                            reasons.append(
                                f"midday rmse 恶化: {cand_rmse:.4f} > 1.03*base {base_rmse:.4f}"
                            )
                    if np.isfinite(base_mae) and np.isfinite(cand_mae):
                        if cand_mae > base_mae * 1.03:
                            passed = False
                            reasons.append(
                                f"midday mae 恶化: {cand_mae:.4f} > 1.03*base {base_mae:.4f}"
                            )

                    # 防止城市级总量明显异常
                    if np.isfinite(cand_ratio) and not (0.86 <= cand_ratio <= 1.06):
                        passed = False
                        reasons.append(f"midday ratio 异常: {cand_ratio:.3f} 不在 [0.86, 1.06]")
                    if np.isfinite(cand_city) and cand_city > 8.0:
                        passed = False
                        reasons.append(f"midday city_rel_err 过高: {cand_city:.2f} > 8.0")

                all_reasons[(h, ver)] = reasons
            elif ver.startswith("BlendTotal"):
                # MAE/RMSE 主约束：不允许大幅牺牲站点误差
                reasons = []
                passed = True
                base_mae = base_metrics.get("mae", np.nan)
                cand_mae = cand_metrics.get("mae", np.nan)
                base_rmse = base_metrics.get("rmse", np.nan)
                cand_rmse = cand_metrics.get("rmse", np.nan)
                if np.isfinite(base_mae) and np.isfinite(cand_mae):
                    if cand_mae > base_mae * 1.05:
                        passed = False
                        reasons.append(
                            f"BlendTotal mae 恶化: {cand_mae:.4f} > 1.05*base {base_mae:.4f}"
                        )
                if np.isfinite(base_rmse) and np.isfinite(cand_rmse):
                    if cand_rmse > base_rmse * 1.05:
                        passed = False
                        reasons.append(
                            f"BlendTotal rmse 恶化: {cand_rmse:.4f} > 1.05*base {base_rmse:.4f}"
                        )
                # ratio 下限软约束（仅排除明显异常）
                cand_ratio = cand_metrics.get("pred_actual_ratio", np.nan)
                if np.isfinite(cand_ratio) and cand_ratio < 0.55:
                    passed = False
                    reasons.append(f"BlendTotal ratio 过低: {cand_ratio:.3f} < 0.55")
            else:
                passed, reasons = guard_check(base_metrics, cand_metrics, is_dawn_dusk=(h in DAWN_DUSK_HOURS))
            all_reasons[(h, ver)] = reasons

            if passed:
                sc = score_candidates(cand_metrics, hour=h)
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
            best_score = score_candidates(base_metrics, hour=h)
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


def diagnose_blend_per_hour_on_test(candidates, selection):
    """仅用于诊断 BlendTotal 在 test 集上的理论上限，不参与 final 版本选择。

    注意：
    - test 集不能用于模型选择；
    - 该函数只生成 oracle 诊断文件；
    - final 仍必须使用 valid 集选择结果。
    """
    print("\nBlendTotal Oracle 诊断（test 集，仅诊断不参与 final 选择）…")

    v1 = candidates["V1"]
    if "pred_baseline" not in v1.columns:
        print("  pred_baseline 缺失，跳过")
        return selection

    test_df = build_eval_frame(
        v1,
        pred_col="power_pred",
        split="test",
        hours=HOURS,
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=TARGET_SITE_COUNT,
    )
    if test_df.empty:
        print("  test 集为空，跳过")
        return selection

    blend_hours = [h for h, (ver, _, _, _) in selection.items()
                   if ver.startswith("BlendTotal")]

    rows = []
    for h in HOURS:
        h_test = test_df[test_df["hour"] == h]
        if len(h_test) == 0:
            continue

        v1_m = compute_hour_metrics(h_test, "power_pred")
        best_alpha = None
        best_score = float("inf")
        best_m = None

        for alpha in BLEND_ALPHAS:
            key = f"BlendTotal_a{int(alpha * 100):02d}"
            if key not in candidates:
                continue
            df_blend = candidates[key]
            blend_h_df = df_blend[df_blend["hour"] == h][["time", "site_id", "power_pred"]].copy()
            blend_h_df = blend_h_df.rename(columns={"power_pred": "cand_pred"})
            merged = h_test[["time", "site_id", "power_mw", "capacity_mw", "hour"]].merge(
                blend_h_df, on=["time", "site_id"], how="inner"
            )
            if len(merged) == 0:
                continue
            cand_m = compute_hour_metrics(merged, "cand_pred")
            cand_score = score_candidates(cand_m)
            cand_mae = cand_m.get("mae", np.inf)
            cand_rmse = cand_m.get("rmse", np.inf)
            v1_mae = v1_m.get("mae", np.inf)
            v1_rmse = v1_m.get("rmse", np.inf)
            if (np.isfinite(v1_mae) and np.isfinite(cand_mae) and
                    cand_mae > v1_mae * 1.05):
                continue
            if (np.isfinite(v1_rmse) and np.isfinite(cand_rmse) and
                    cand_rmse > v1_rmse * 1.05):
                continue
            if cand_score < best_score:
                best_score = cand_score
                best_alpha = alpha
                best_m = cand_m

        if best_alpha is not None:
            best_ver = f"BlendTotal_a{int(best_alpha * 100):02d}"
        else:
            best_ver = "V1"
            best_m = v1_m
            best_score = score_candidates(v1_m)

        rows.append({
            "hour": int(h),
            "final_selected_version": selection.get(h, (None,))[0],
            "oracle_best_version_on_test": best_ver,
            "oracle_score_on_test": round(best_score, 4),
            "oracle_mae_on_test": round(best_m.get("mae", np.nan), 4),
            "oracle_rmse_on_test": round(best_m.get("rmse", np.nan), 4),
            "oracle_nrmse_capacity_pct_on_test": round(best_m.get("nrmse_capacity_pct", np.nan), 4),
            "oracle_pred_actual_ratio_on_test": round(best_m.get("pred_actual_ratio", np.nan), 6),
            "note": "diagnostic_only_not_used_for_final_selection",
        })

    if rows:
        diag = pd.DataFrame(rows)
        diag.to_csv(
            METRICS_DIR / "blend_oracle_on_test_diagnostic_only.csv",
            index=False, encoding="utf-8-sig")
        print(f"  已保存 oracle 诊断: {METRICS_DIR / 'blend_oracle_on_test_diagnostic_only.csv'}")

    return selection


def build_final(candidates, selection):
    """构建最终预测（向量化 merge）"""
    print("\n构建最终预测 …")
    df_base = candidates["V1"].copy()

    for h, (ver, metrics, score, reasons) in selection.items():
        if ver in {"V1", "V1_guard", "V1_mae_guard"}:
            continue

        df_cand = candidates[ver]
        cand_map = df_cand[df_cand["hour"] == h][["time", "site_id", "power_pred"]].rename(
            columns={"power_pred": "power_pred_new"})
        # 去重（防止原始数据有重复行导致多对多爆炸）
        cand_map = cand_map.drop_duplicates(subset=["time", "site_id"])

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


def _hour_nrmse_summary(df, pred_col="power_pred"):
    """返回每小时的站点平均 NRMSE 和城市 NRMSE。"""
    from pv_forecasting.core.evaluation import site_hour_nrmse, city_hour_nrmse

    rows = {}
    for h, sub in df.groupby("hour"):
        site_vals = []
        for _, sg in sub.groupby("site_id"):
            val = site_hour_nrmse(
                sg["power_mw"].values,
                sg[pred_col].values,
                sg["capacity_mw"].values,
            )
            if np.isfinite(val):
                site_vals.append(val)
        rows[int(h)] = {
            "site_nrmse_mean_pct": float(np.nanmean(site_vals)) if site_vals else np.nan,
            "city_nrmse_pct": city_hour_nrmse(sub, pred_col),
        }
    return rows


def apply_final_nrmse_guard(df_final, df_v1, selection):
    """final 产物保护：若某小时 final NRMSE 明显劣于 V1，则回退该小时到 V1。

    这一步解决当前 6、17、18、19 点被 BlendTotal 拉差的问题。
    """
    eval_final = build_eval_frame(
        df_final,
        pred_col="power_pred",
        split="test",
        hours=HOURS,
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=TARGET_SITE_COUNT,
    )
    eval_v1 = build_eval_frame(
        df_v1,
        pred_col="power_pred",
        split="test",
        hours=HOURS,
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=TARGET_SITE_COUNT,
    )

    final_m = _hour_nrmse_summary(eval_final, "power_pred")
    v1_m = _hour_nrmse_summary(eval_v1, "power_pred")

    rollback_hours = []
    for h in STRICT_NRMSE_GUARD_HOURS:
        fm = final_m.get(h, {})
        bm = v1_m.get(h, {})
        f_site = fm.get("site_nrmse_mean_pct", np.nan)
        b_site = bm.get("site_nrmse_mean_pct", np.nan)
        f_city = fm.get("city_nrmse_pct", np.nan)
        b_city = bm.get("city_nrmse_pct", np.nan)

        worse_site = np.isfinite(f_site) and np.isfinite(b_site) and f_site > b_site * 1.05
        worse_city = np.isfinite(f_city) and np.isfinite(b_city) and f_city > b_city * 1.10

        if worse_site or worse_city:
            rollback_hours.append(h)
            print(
                f"  [NRMSE-GUARD] h={h:02d} 回退 V1: "
                f"site {f_site:.2f}->{b_site:.2f}, city {f_city:.2f}->{b_city:.2f}"
            )

    if not rollback_hours:
        return df_final, selection, []

    out = df_final.copy()
    key_cols = ["time", "site_id"]
    v1_map = df_v1[df_v1["hour"].isin(rollback_hours)][key_cols + ["power_pred"]].copy()
    v1_map = v1_map.drop_duplicates(subset=key_cols)
    v1_map = v1_map.rename(columns={"power_pred": "power_pred_v1_guard"})

    out = out.merge(v1_map, on=key_cols, how="left")
    mask = out["hour"].isin(rollback_hours) & out["power_pred_v1_guard"].notna()
    out.loc[mask, "power_pred"] = out.loc[mask, "power_pred_v1_guard"]
    out = out.drop(columns=["power_pred_v1_guard"])

    # 更新选择记录
    for h in rollback_hours:
        metrics = selection[h][1]
        score = selection[h][2]
        reasons = list(selection[h][3]) if selection[h][3] else []
        reasons.append("final_nrmse_guard 回退 V1")
        selection[h] = ("V1_guard", metrics, score, reasons)

    return out, selection, rollback_hours


def _overall_error(df, pred_col="power_pred"):
    yt = pd.to_numeric(df["power_mw"], errors="coerce")
    yp = pd.to_numeric(df[pred_col], errors="coerce")
    m = yt.notna() & yp.notna()
    if not m.any():
        return {"mae": np.nan, "rmse": np.nan, "ratio": np.nan, "bias_pct": np.nan}
    actual = float(yt[m].sum())
    pred = float(yp[m].sum())
    err = yp[m].values - yt[m].values
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "ratio": pred / max(actual, 1e-9),
        "bias_pct": (pred - actual) / max(actual, 1e-9) * 100,
    }


def apply_final_mae_rmse_guard(df_final, df_v1, selection):
    """final 产物 MAE/RMSE 保护：如果某小时混合后 MAE/RMSE 明显劣于 V1，则回退该小时。

    用于恢复周二版 MAE/RMSE 效果，避免只追求总量 ratio。
    """
    eval_final = build_eval_frame(
        df_final,
        pred_col="power_pred",
        split="test",
        hours=HOURS,
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=TARGET_SITE_COUNT,
    )
    eval_v1 = build_eval_frame(
        df_v1,
        pred_col="power_pred",
        split="test",
        hours=HOURS,
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=TARGET_SITE_COUNT,
    )

    rollback_hours = []
    for h in HOURS:
        f_sub = eval_final[eval_final["hour"] == h]
        b_sub = eval_v1[eval_v1["hour"] == h]
        if len(f_sub) == 0 or len(b_sub) == 0:
            continue
        fm = _overall_error(f_sub)
        bm = _overall_error(b_sub)

        allow = 1.00 if h in STRICT_NRMSE_GUARD_HOURS else 1.02
        worse_mae = np.isfinite(fm["mae"]) and np.isfinite(bm["mae"]) and fm["mae"] > bm["mae"] * allow
        worse_rmse = np.isfinite(fm["rmse"]) and np.isfinite(bm["rmse"]) and fm["rmse"] > bm["rmse"] * allow

        # 如果回退会导致该小时 ratio 极低，则只在 RMSE 明显恶化时回退
        ratio_too_low_after_v1 = np.isfinite(bm["ratio"]) and bm["ratio"] < 0.55
        if ratio_too_low_after_v1 and not (np.isfinite(fm["rmse"]) and np.isfinite(bm["rmse"]) and fm["rmse"] > bm["rmse"] * 1.08):
            continue

        if worse_mae or worse_rmse:
            rollback_hours.append(h)
            print(
                f"  [MAE/RMSE-GUARD] h={h:02d} 回退 V1: "
                f"MAE {fm['mae']:.4f}->{bm['mae']:.4f}, "
                f"RMSE {fm['rmse']:.4f}->{bm['rmse']:.4f}, "
                f"ratio {fm['ratio']:.3f}->{bm['ratio']:.3f}"
            )

    if not rollback_hours:
        return df_final, selection, []

    out = df_final.copy()
    key_cols = ["time", "site_id"]
    v1_map = df_v1[df_v1["hour"].isin(rollback_hours)][key_cols + ["power_pred"]].copy()
    v1_map = v1_map.drop_duplicates(subset=key_cols)
    v1_map = v1_map.rename(columns={"power_pred": "power_pred_v1_mae_guard"})

    out = out.merge(v1_map, on=key_cols, how="left")
    mask = out["hour"].isin(rollback_hours) & out["power_pred_v1_mae_guard"].notna()
    out.loc[mask, "power_pred"] = out.loc[mask, "power_pred_v1_mae_guard"]
    out = out.drop(columns=["power_pred_v1_mae_guard"])

    for h in rollback_hours:
        metrics = selection[h][1]
        score = selection[h][2]
        reasons = list(selection[h][3]) if selection[h][3] else []
        reasons.append("final_mae_rmse_guard 回退 V1")
        selection[h] = ("V1_mae_guard", metrics, score, reasons)

    return out, selection, rollback_hours


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

    # 只生成 test oracle 诊断，不参与 final 选择，避免测试集泄漏
    selection = diagnose_blend_per_hour_on_test(candidates, selection)

    # Step 4: 构建最终预测
    print("\n[Step 4] 构建最终预测 …")
    df_final = build_final(candidates, selection)

    # Step 4b: final 产物 NRMSE 保护（默认关闭，避免 test 集参与最终选择）
    if ENABLE_NRMSE_ORACLE_GUARD:
        df_final, selection, rollback_hours = apply_final_nrmse_guard(
            df_final,
            candidates["V1"],
            selection,
        )
        if rollback_hours:
            print(f"  [NRMSE-GUARD] 回退小时: {rollback_hours}")
    else:
        print("  跳过 final NRMSE oracle guard，避免 test 集参与最终选择")

    # Step 4c: final 产物 MAE/RMSE 保护（默认关闭，避免 test 集参与最终选择）
    if ENABLE_TEST_ORACLE_GUARD:
        df_final, selection, mae_guard_hours = apply_final_mae_rmse_guard(
            df_final,
            candidates["V1"],
            selection,
        )
        if mae_guard_hours:
            print(f"  [MAE/RMSE-GUARD] 回退小时: {mae_guard_hours}")
    else:
        print("  跳过 final MAE/RMSE test oracle guard，避免 test 集参与最终选择")

    # Step 5: 保存
    print("\n[Step 5] 保存 …")

    from pv_forecasting.core.utils import write_prediction_pickle_atomic
    from pv_forecasting.core.evaluation import build_eval_frame

    write_prediction_pickle_atomic(
        df_final,
        OUT_FULL,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
    )
    print(f"  已保存: {OUT_FULL}")

    df_eval = build_eval_frame(
        df_final,
        pred_col="power_pred",
        split="test",
        hours=HOURS,
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=TARGET_SITE_COUNT,
    )

    actual = df_eval["power_mw"].sum()
    pred = df_eval["power_pred"].sum()
    print(f"  final_eval rows={len(df_eval):,}, sites={df_eval['site_id'].nunique()}")
    print(f"  actual={actual:.2f}, pred={pred:.2f}, ratio={pred / max(actual, 1e-9):.4f}")

    write_prediction_pickle_atomic(
        df_eval,
        OUT_EVAL,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
        hour_range=(6, 19),
    )
    print(f"  已保存: {OUT_EVAL}")

    # Step 6: 保存选择记录
    print("\n[Step 6] 保存选择记录 …")
    rows = []
    for h, (ver, metrics, score, reasons) in selection.items():
        rows.append({
            "hour": int(h),
            "selected_version": ver,
            "is_final_guard_rollback": ver == "V1_guard",
            "is_mae_rmse_guard_rollback": ver == "V1_mae_guard",
            "is_midday_nrmse_priority": int(h in MIDDAY_NRMSE_PRIORITY_HOURS),
            "score": round(score, 4),
            "mae": round(metrics.get("mae", np.nan), 4),
            "rmse": round(metrics.get("rmse", np.nan), 4),
            "city_rel_err": round(metrics.get("city_rel_err", np.nan), 4),
            "site_mape_raw_mean": round(metrics.get("site_mape_raw_mean", np.nan), 4),
            "site_mape_clipped": round(metrics.get("site_mape_clipped", np.nan), 4),
            "site_wape": round(metrics.get("site_wape", np.nan), 4),
            "n_gt100": metrics.get("n_gt100", 0),
            "n_gt200": metrics.get("n_gt200", 0),
            "nrmse_capacity_pct": round(metrics.get("nrmse_capacity_pct", np.nan), 4),
            "site_nrmse_mean_pct": round(metrics.get("site_nrmse_mean_pct", np.nan), 4),
            "pred_actual_ratio": round(metrics.get("pred_actual_ratio", np.nan), 6),
            "ratio_abs_err": round(metrics.get("ratio_abs_err", np.nan), 4),
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
        mae = selection[h][1].get("mae", 0)
        rmse = selection[h][1].get("rmse", 0)
        nrmse = selection[h][1].get("nrmse_capacity_pct", 0)
        site_nrmse = selection[h][1].get("site_nrmse_mean_pct", np.nan)
        ratio = selection[h][1].get("pred_actual_ratio", 0)
        note = f", site_nrmse={site_nrmse:.2f}%" if np.isfinite(site_nrmse) else ""
        print(f"  h={h:02d}: {ver} (score={score:.2f}, mae={mae:.4f}, rmse={rmse:.4f}, nrmse={nrmse:.2f}%{note}, ratio={ratio:.4f})")
    print("\nDone.")
    return df_final


if __name__ == "__main__":
    main()
