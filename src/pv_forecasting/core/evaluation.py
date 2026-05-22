"""
core/evaluation.py
==================
统一评估口径：所有报告、逐小时误差、站点异常表必须调用本模块。

Split 口径（由 core/split.py 定义）
-----------------------------------
- train  : time < 2025-07-01
- valid  : 2025-07-01 <= time < 2025-09-01
- test   : 2025-09-01 <= time < 2026-01-01
- future : time >= 2026-01-01

评估口径（固定值，不得修改）
-----------------------------
- split              == "test"
- time               >= 2025-09-01  且  < 2026-01-01
- hour               in range(6, 20)  即 6~19
- power_mw          > 0
- site_id            NOT IN BAD_SITES  (7 个异常站点)
- 评估站点数量       固定 53 个（按正功率样本数排序）
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ── 全局常量（口径基准）───────────────────────────────────────────────────────

DEFAULT_EVAL_HOURS = tuple(range(6, 20))
DEFAULT_TEST_START = pd.Timestamp("2025-09-01")
DEFAULT_TEST_END = pd.Timestamp("2026-01-01")
DEFAULT_BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}
DEFAULT_EVAL_SITE_COUNT = 53
CLIP_DENOM_FACTOR = 0.05   # clipped MAPE 分母 = max(y, factor*capacity, 0.01)


# ── Metric helpers ─────────────────────────────────────────────────────────────

def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """raw MAPE(%)，仅 y>0 的有限值参与计算。"""
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.mean(np.abs(y_true[m] - y_pred[m]) / y_true[m]) * 100)


def clipped_mape(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    capacity: np.ndarray | None = None,
    clip_factor: float = CLIP_DENOM_FACTOR,
) -> float:
    """Clipped MAPE(%): 分母 = max(y, clip_factor*capacity, 0.01)"""
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    if capacity is not None:
        cap_arr = np.asarray(capacity, dtype=float)
        denom = np.maximum.reduce([
            y_true[m],
            clip_factor * cap_arr[m],
            np.full(y_true[m].shape, 0.01),
        ])
    else:
        denom = np.maximum(y_true[m], clip_factor * np.median(y_true[m]))
    return float(np.mean(np.abs(y_true[m] - y_pred[m]) / denom) * 100)


def wape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """WAPE(%): sum(|e|) / sum(|y|)"""
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.sum(np.abs(y_true[m] - y_pred[m])) / max(np.sum(np.abs(y_true[m])), 1e-9) * 100)


def city_rel_err(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """City total relative error(%): |sum(pred)-sum(actual)| / sum(actual)"""
    m = np.isfinite(y_true) & np.isfinite(y_pred) & (y_true > 0)
    yt_s = float(np.nansum(y_true[m]))
    if not np.isfinite(yt_s) or yt_s <= 0:
        return np.nan
    yp_s = float(np.nansum(y_pred[m]))
    return float(np.abs(yp_s - yt_s) / yt_s * 100)


def site_rel_err(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """单站点相对误差(%): sum(|e|) / sum(|y|)"""
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.abs(y_true[m] - y_pred[m]).sum() / max(y_true[m].sum(), 1e-9) * 100)


def capacity_weighted_mape(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    capacity: np.ndarray,
) -> float:
    """容量加权 MAPE(%)"""
    m = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred) & np.isfinite(capacity)
    if not m.any():
        return np.nan
    rel = np.abs(y_true[m] - y_pred[m]) / y_true[m]
    cap = np.asarray(capacity, dtype=float)[m]
    return float(np.sum(cap * rel) / max(np.sum(cap), 1e-9) * 100)


# ── Core evaluation frame builder ──────────────────────────────────────────────

def build_eval_frame(
    df: pd.DataFrame,
    pred_col: str = "power_pred",
    split: str = "test",
    hours: tuple[int, ...] | list[int] = DEFAULT_EVAL_HOURS,
    active_only: bool = True,
    bad_sites: set[str] | None = None,
    target_site_count: int | None = DEFAULT_EVAL_SITE_COUNT,
) -> pd.DataFrame:
    """构建统一的评估子集 DataFrame。

    Parameters
    ----------
    df : pd.DataFrame
        预测表，需包含 time / site_id / power_mw / power_pred / split 列。
    pred_col : str
        预测列名。
    split : str
        数据分割标识（默认 "test"）。
    hours : iterable of int
        评估小时范围（默认 6~19）。
    active_only : bool
        是否只保留 power_mw > 0 的样本。
    bad_sites : set of str, optional
        排除的异常站点集合。
    target_site_count : int, optional
        固定评估站点数量（默认 53）。按正功率样本数排序取前 N 个。
        传入 None 则不过滤站点数量。

    Returns
    -------
    pd.DataFrame
        评估子集（已通过口径过滤和站点筛选）。
    """
    bad_sites = bad_sites or DEFAULT_BAD_SITES

    out = df.copy()

    # 确保时间列
    if "time" in out.columns and not pd.api.types.is_datetime64_any_dtype(out["time"]):
        out["time"] = pd.to_datetime(out["time"])

    # 确保 hour 列
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour

    # 口径过滤
    mask = out["split"] == split
    mask &= out["hour"].isin(hours)
    mask &= ~out["site_id"].isin(bad_sites)
    if active_only:
        mask &= out["power_mw"] > 0
    # 强制测试窗口截止（避免 2026-01 之后的数据渗入评估）
    if split == "test" and "time" in out.columns:
        mask &= out["time"] >= DEFAULT_TEST_START
        mask &= out["time"] < DEFAULT_TEST_END

    eval_df = out[mask].copy()

    if target_site_count is not None and target_site_count > 0 and len(eval_df) > 0:
        try:
            from pv_forecasting.core.eval_sites import get_eval_site_ids

            keep_sites = get_eval_site_ids(
                eval_df,
                target_n=target_site_count,
                bad_sites=bad_sites,
            )
            if keep_sites:
                eval_df = eval_df[eval_df["site_id"].isin(keep_sites)].copy()
        except Exception as exc:
            print(f"[WARN] eval site filtering failed: {exc}")

    return eval_df


# ── Per-hour metrics ───────────────────────────────────────────────────────────

def hourly_relative_error(
    df: pd.DataFrame,
    pred_col: str = "power_pred",
    sid_to_name: dict | None = None,
) -> pd.DataFrame:
    """计算逐小时误差指标。

    输出字段：hour, rows, n_sites, n_dates,
             site_mape_raw_mean, site_mape_raw_median, site_mape_raw_p90,
             site_mape_clipped, site_wape, capacity_weighted_mape,
             city_total_rel_err_mean, city_total_rel_err_median,
             city_total_rel_err_p90, city_wape_mean,
             n_site_hour_gt_100, n_site_hour_gt_200,
             worst_site, worst_site_err,
             city_actual_mean_mw, city_pred_mean_mw, bias_pct
    """
    rows = []
    for h, sub in df.groupby("hour"):
        if len(sub) == 0:
            continue

        yt = sub["power_mw"].values.astype(float)
        yp = sub[pred_col].values.astype(float)
        cap = sub["capacity_mw"].values.astype(float)

        # 日级 city_rel_err
        daily_rels = []
        daily_wapes = []
        for _, dg in sub.groupby("date"):
            rel = city_rel_err(dg["power_mw"].values, dg[pred_col].values)
            if np.isfinite(rel):
                daily_rels.append(rel)
            w = wape(dg["power_mw"].values, dg[pred_col].values)
            if np.isfinite(w):
                daily_wapes.append(w)

        # 站点级相对误差
        site_rels = []
        for _, sg in sub.groupby("site_id"):
            re = site_rel_err(sg["power_mw"].values, sg[pred_col].values)
            if np.isfinite(re):
                site_rels.append(re)
        site_rels = np.array(site_rels, dtype=float)

        n_gt100 = int((site_rels > 100).sum())
        n_gt200 = int((site_rels > 200).sum())
        worst_idx = int(np.nanargmax(site_rels)) if len(site_rels) and np.any(np.isfinite(site_rels)) else 0
        worst_sid = sub["site_id"].unique()[worst_idx] if len(site_rels) else ""
        worst_name = (sid_to_name or {}).get(worst_sid, worst_sid)
        worst_val = float(np.nanmax(site_rels)) if len(site_rels) else np.nan

        rows.append({
            "hour": int(h),
            "rows": len(sub),
            "n_sites": sub["site_id"].nunique(),
            "n_dates": sub["date"].nunique(),
            "site_mape_raw_mean": round(float(np.nanmean(site_rels)), 2),
            "site_mape_raw_median": round(float(np.nanmedian(site_rels)), 2),
            "site_mape_raw_p90": round(float(np.nanpercentile(site_rels, 90)), 2),
            "site_mape_clipped": round(clipped_mape(yt, yp, cap), 2),
            "site_wape": round(wape(yt, yp), 2),
            "capacity_weighted_mape": round(capacity_weighted_mape(yt, yp, cap), 2),
            "city_total_rel_err_mean": round(float(np.mean(daily_rels)), 3) if daily_rels else np.nan,
            "city_total_rel_err_median": round(float(np.median(daily_rels)), 3) if daily_rels else np.nan,
            "city_total_rel_err_p90": round(float(np.percentile(daily_rels, 90)), 3) if daily_rels else np.nan,
            "city_wape_mean": round(float(np.mean(daily_wapes)), 3) if daily_wapes else np.nan,
            "n_site_hour_gt_100": n_gt100,
            "n_site_hour_gt_200": n_gt200,
            "worst_site": worst_name,
            "worst_site_err": round(worst_val, 1),
            "city_actual_mean_mw": round(float(sub["power_mw"].sum() / max(sub["date"].nunique(), 1)), 2),
            "city_pred_mean_mw": round(float(sub[pred_col].sum() / max(sub["date"].nunique(), 1)), 2),
            "bias_pct": round(float(
                (sub[pred_col].sum() - sub["power_mw"].sum()) / max(sub["power_mw"].sum(), 1) * 100
            ), 3),
        })

    result = pd.DataFrame(rows).sort_values("hour").reset_index(drop=True)
    return result


# ── Site × hour outliers ──────────────────────────────────────────────────────

def site_hour_outliers(
    df: pd.DataFrame,
    pred_col: str = "power_pred",
    mape_thresh: float = 100.0,
    wape_thresh: float = 50.0,
) -> pd.DataFrame:
    """找出站点-小时异常组合。

    输出字段：site_id, hour, rows, site_mape, site_wape, city_bias, scene
    """
    rows = []
    for (sid, hour), g in df.groupby(["site_id", "hour"]):
        if len(g) == 0:
            continue
        yt = g["power_mw"].values.astype(float)
        yp = g[pred_col].values.astype(float)
        re = site_rel_err(yt, yp)
        wa = wape(yt, yp)
        cb = city_rel_err(yt, yp)
        scene = g["scene_v151"].mode()[0] if "scene_v151" in g.columns else ""

        flag = ""
        if np.isfinite(re) and re > mape_thresh:
            flag += f"MAPE>{mape_thresh:.0f} "
        if np.isfinite(wa) and wa > wape_thresh:
            flag += f"WAPE>{wape_thresh:.0f}"

        rows.append({
            "site_id": sid,
            "hour": int(hour),
            "rows": len(g),
            "site_mape": round(re, 1) if np.isfinite(re) else np.nan,
            "site_wape": round(wa, 1) if np.isfinite(wa) else np.nan,
            "city_bias_pct": round(cb, 2) if np.isfinite(cb) else np.nan,
            "scene": scene,
            "flag": flag.strip(),
        })

    return pd.DataFrame(rows).sort_values(["site_mape"], ascending=False).reset_index(drop=True)


# ── Compare two prediction columns ────────────────────────────────────────────

def compare_two_versions(
    df: pd.DataFrame,
    pred_a: str,
    pred_b: str,
    version_labels: tuple[str, str] = ("V2", "V3"),
) -> pd.DataFrame:
    """对比两个版本的逐小时误差。

    Parameters
    ----------
    df : pd.DataFrame
        评估子集（通常来自 build_eval_frame）。
    pred_a, pred_b : str
        两个预测列名。
    version_labels : tuple
        版本标签，如 ("V2", "V3")。

    Returns
    -------
    pd.DataFrame
        包含逐小时对比指标的 DataFrame。
    """
    a_mape = []
    b_mape = []
    a_wape = []
    b_wape = []
    a_cre = []
    b_cre = []

    for h, sub in df.groupby("hour"):
        if len(sub) == 0:
            continue
        yt = sub["power_mw"].values.astype(float)
        a_mape.append(mape(yt, sub[pred_a].values.astype(float)))
        b_mape.append(mape(yt, sub[pred_b].values.astype(float)))
        a_wape.append(wape(yt, sub[pred_a].values.astype(float)))
        b_wape.append(wape(yt, sub[pred_b].values.astype(float)))
        a_cre.append(city_rel_err(yt, sub[pred_a].values.astype(float)))
        b_cre.append(city_rel_err(yt, sub[pred_b].values.astype(float)))

    va, vb = version_labels
    return pd.DataFrame({
        "hour": [h for h, _ in df.groupby("hour")],
        f"{va}_site_mape_mean_pct": a_mape,
        f"{vb}_site_mape_mean_pct": b_mape,
        f"{va}_wape_pct": a_wape,
        f"{vb}_wape_pct": b_wape,
        f"{va}_city_rel_err_pct": a_cre,
        f"{vb}_city_rel_err_pct": b_cre,
    })


# ════════════════════════════════════════════════════════════════════════════════
# NRMSE — 主指标（V3 版）
# ════════════════════════════════════════════════════════════════════════════════

def _to_f64(arr) -> np.ndarray:
    return np.asarray(arr, dtype=float)


def site_hour_nrmse(y_true, y_pred, capacity_mw) -> float:
    """单站点-小时 NRMSE(%)。分母 = 站点装机容量，避免早晚低功率放大。"""
    yt = _to_f64(y_true)
    yp = _to_f64(y_pred)
    cap = _to_f64(capacity_mw)
    m = np.isfinite(yt) & np.isfinite(yp) & (cap > 0)
    if not m.any():
        return np.nan
    rmse = float(np.sqrt(np.mean((yt[m] - yp[m]) ** 2)))
    return rmse / float(cap[m].mean()) * 100


def city_hour_nrmse(df, pred_col="power_pred") -> float:
    """城市小时 NRMSE(%)：先聚合城市总出力，再算 RMSE。"""
    yt = df["power_mw"].values.astype(float)
    yp = df[pred_col].values.astype(float)
    cap = df["capacity_mw"].values.astype(float)
    m = np.isfinite(yt) & np.isfinite(yp) & (cap > 0)
    if not m.any():
        return np.nan
    city_yt = float(np.nansum(yt[m]))
    city_yp = float(np.nansum(yp[m]))
    city_cap = float(np.nansum(cap[m]))
    if city_cap <= 0:
        return np.nan
    return float(np.abs(city_yt - city_yp)) / city_cap * 100


def _hour_nrmse_row(sub, pred_col) -> dict:
    yt = sub["power_mw"].values.astype(float)
    yp = sub[pred_col].values.astype(float)
    cap = sub["capacity_mw"].values.astype(float)

    # 站点级
    site_nrmses = []
    for _, sg in sub.groupby("site_id"):
        nr = site_hour_nrmse(sg["power_mw"].values, sg[pred_col].values,
                               sg["capacity_mw"].values)
        if np.isfinite(nr):
            site_nrmses.append(nr)
    site_nrmses = np.array(site_nrmses, dtype=float)

    # 城市级
    city_nr = city_hour_nrmse(sub, pred_col)
    city_bias = city_rel_err(yt, yp)

    # 辅助
    m_all = np.isfinite(yt) & np.isfinite(yp)
    wa = wape(yt, yp) if m_all.any() else np.nan
    clip_m = clipped_mape(yt, yp, cap)

    return {
        "site_nrmse_mean_pct": round(float(np.nanmean(site_nrmses)), 2) if len(site_nrmses) else np.nan,
        "site_nrmse_median_pct": round(float(np.nanmedian(site_nrmses)), 2) if len(site_nrmses) else np.nan,
        "site_nrmse_p90_pct": round(float(np.nanpercentile(site_nrmses, 90)), 2) if len(site_nrmses) else np.nan,
        "city_nrmse_pct": round(city_nr, 3) if np.isfinite(city_nr) else np.nan,
        "city_bias_pct": round(city_bias, 3) if np.isfinite(city_bias) else np.nan,
        "aux_wape_pct": round(wa, 2) if np.isfinite(wa) else np.nan,
        "aux_mape_clipped_pct": round(clip_m, 2) if np.isfinite(clip_m) else np.nan,
    }


def hourly_nrmse_metrics(df, pred_col="power_pred") -> pd.DataFrame:
    """计算逐小时 NRMSE 指标（主指标），附带辅助 WAPE/MAPE。"""
    rows = []
    for h, sub in df.groupby("hour"):
        row = {"hour": int(h), "rows": len(sub),
               "n_sites": sub["site_id"].nunique(),
               "n_dates": sub["date"].nunique()}
        row.update(_hour_nrmse_row(sub, pred_col))
        rows.append(row)
    return pd.DataFrame(rows).sort_values("hour").reset_index(drop=True)


def compare_two_versions_nrmse(
    df,
    pred_a,
    pred_b,
    version_labels=("V2", "V3"),
) -> pd.DataFrame:
    """对比两个版本的逐小时 NRMSE（主指标）。"""
    rows = []
    for h, sub in df.groupby("hour"):
        if len(sub) == 0:
            continue
        row = {"hour": int(h), "rows": len(sub)}
        row_a = _hour_nrmse_row(sub, pred_a)
        row_b = _hour_nrmse_row(sub, pred_b)
        va, vb = version_labels
        for k, v in row_a.items():
            row[f"{va}_{k}"] = v
        for k, v in row_b.items():
            row[f"{vb}_{k}"] = v
        # 综合 NRMSE score = 0.7*站点 + 0.3*城市
        score_a = 0.7 * (row_a["site_nrmse_mean_pct"] or 100) + 0.3 * (row_a["city_nrmse_pct"] or 100)
        score_b = 0.7 * (row_b["site_nrmse_mean_pct"] or 100) + 0.3 * (row_b["city_nrmse_pct"] or 100)
        row[f"{va}_nrmse_score"] = round(score_a, 4)
        row[f"{vb}_nrmse_score"] = round(score_b, 4)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("hour").reset_index(drop=True)
