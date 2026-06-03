"""
metrics_common.py
================
统一指标口径工具。

所有报告、评估脚本、可视化导出必须使用本模块的函数，
禁止在多处重复实现 RMSE/NRMSE/BIAS 计算逻辑。

口径说明：
  - 站点 NRMSE = RMSE / capacity_mw × 100（%）
  - 城市 NRMSE = RMSE / sum(capacity_mw) × 100（%）
  - 评估集：split == test, hour in [6..19], 非空
  - 不允许用 test 选择模型或校准参数
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np
import pandas as pd


# ─── 基础误差函数 ────────────────────────────────────────────────────────────

def mae(actual: np.ndarray | pd.Series, pred: np.ndarray | pd.Series) -> float:
    """Mean Absolute Error。"""
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    if len(a) == 0:
        return float("nan")
    return float(np.mean(np.abs(p - a)))


def rmse(actual: np.ndarray | pd.Series, pred: np.ndarray | pd.Series) -> float:
    """Root Mean Squared Error。"""
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    if len(a) == 0:
        return float("nan")
    return float(math.sqrt(float(np.mean((p - a) ** 2))))


def nrmse_percent(
    actual: np.ndarray | pd.Series,
    pred: np.ndarray | pd.Series,
    capacity_mw: float,
) -> float:
    """
    Normalized RMSE as percentage.

    NRMSE(%) = RMSE(actual, pred) / capacity_mw × 100

    Args:
        actual: 真实值（MW）
        pred:   预测值（MW）
        capacity_mw: 额定装机容量（MW），必须 > 0
    """
    if capacity_mw <= 0 or math.isnan(float(capacity_mw)):
        return float("nan")
    return rmse(actual, pred) / float(capacity_mw) * 100.0


def bias_percent(actual: np.ndarray | pd.Series, pred: np.ndarray | pd.Series) -> float:
    """
    Bias as percentage of actual total.

    BIAS(%) = (sum(pred) - sum(actual)) / sum(actual) × 100
    """
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    a_sum = float(np.nansum(a))
    p_sum = float(np.nansum(p))
    if abs(a_sum) < 1e-12:
        return float("nan")
    return (p_sum - a_sum) / a_sum * 100.0


def pred_actual_ratio(actual: np.ndarray | pd.Series, pred: np.ndarray | pd.Series) -> float:
    """pred_sum / actual_sum。"""
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    a_sum = float(np.nansum(a))
    if abs(a_sum) < 1e-12:
        return float("nan")
    return float(np.nansum(p)) / a_sum


# ─── 评估集构建 ──────────────────────────────────────────────────────────────

def build_eval_frame(
    df: pd.DataFrame,
    *,
    pred_col: str = "power_pred_final",
    actual_col: str = "power_mw",
    capacity_col: str = "capacity_mw",
    split_col: str = "split",
    eval_split: str = "test",
    start_hour: int = 6,
    end_hour: int = 19,
    exclude_future: bool = True,
    future_value: str = "future",
) -> pd.DataFrame:
    """
    构建评估用 DataFrame。

    Args:
        df: 包含 power_mw, power_pred_final, split, hour 的 DataFrame。
        pred_col: 预测列名。
        actual_col: 真实功率列名。
        capacity_col: 容量列名。
        split_col: split 列名。
        eval_split: 评估用的 split 值（默认 test）。
        start_hour: 评估起始小时（含）。
        end_hour: 评估结束小时（含）。
        exclude_future: 是否排除 future split。
        future_value: future split 的值。

    Returns:
        过滤后的评估 DataFrame（含 actual_mw, pred_mw, capacity_mw 列）。
    """
    work = df.copy()

    # 1. 时间列标准化
    if "time" in work.columns:
        work["time"] = pd.to_datetime(work["time"], errors="coerce")
        if "hour" not in work.columns:
            work["hour"] = work["time"].dt.hour

    # 2. split 过滤
    if split_col in work.columns:
        if exclude_future and future_value in work[split_col].values:
            work = work[work[split_col] != future_value]
        work = work[work[split_col] == eval_split]

    # 3. 小时过滤
    if "hour" in work.columns:
        work = work[work["hour"].between(start_hour, end_hour)]

    # 4. 数值类型
    work["actual_mw"] = pd.to_numeric(work[actual_col], errors="coerce")
    work["pred_mw"] = pd.to_numeric(work[pred_col], errors="coerce")
    work["capacity_mw"] = pd.to_numeric(work[capacity_col], errors="coerce")

    # 5. 非空过滤
    work = work[
        work["actual_mw"].notna()
        & work["pred_mw"].notna()
        & work["capacity_mw"].notna()
        & (work["capacity_mw"] > 0)
    ].copy()

    return work.reset_index(drop=True)


# ─── 站点级指标 ──────────────────────────────────────────────────────────────

def site_metrics(
    eval_df: pd.DataFrame,
    pred_col: str = "pred_mw",
    actual_col: str = "actual_mw",
    capacity_col: str = "capacity_mw",
    site_col: str = "site_id",
) -> pd.DataFrame:
    """
    计算每个站点的测试误差指标。

    Args:
        eval_df: build_eval_frame() 的输出。
        pred_col: 预测列（应为 pred_mw）。
        actual_col: 真实列（应为 actual_mw）。
        capacity_col: 容量列（应为 capacity_mw）。
        site_col: 站点 ID 列。

    Returns:
        DataFrame，含 site_id, mae_mw, rmse_mw, nrmse_pct, bias_pct, pred_actual_ratio。
    """
    rows = []
    for sid, g in eval_df.groupby(site_col):
        cap = float(g[capacity_col].mean())
        a = g[actual_col].values
        p = g[pred_col].values
        rows.append({
            site_col: sid,
            "mae_mw": mae(a, p),
            "rmse_mw": rmse(a, p),
            "nrmse_pct": nrmse_percent(a, p, cap),
            "bias_pct": bias_percent(a, p),
            "pred_actual_ratio": pred_actual_ratio(a, p),
        })
    return pd.DataFrame(rows)


# ─── 逐小时站点平均 NRMSE ────────────────────────────────────────────────────

def hourly_site_mean_nrmse(
    eval_df: pd.DataFrame,
    pred_col: str = "pred_mw",
    actual_col: str = "actual_mw",
    capacity_col: str = "capacity_mw",
    site_col: str = "site_id",
    hour_col: str = "hour",
) -> pd.DataFrame:
    """
    逐小时 NRMSE。

    对每个 (hour, site) 计算 RMSE / capacity，再按 hour 取站点均值。

    Returns:
        DataFrame，含 hour, sample_count, site_mean_nrmse_percent。
    """
    rows = []
    for hour, hg in eval_df.groupby(hour_col):
        site_vals = []
        for sid, sg in hg.groupby(site_col):
            cap = float(sg[capacity_col].mean())
            if cap <= 0:
                continue
            site_vals.append(nrmse_percent(sg[actual_col], sg[pred_col], cap))
        site_vals = [v for v in site_vals if not math.isnan(v)]
        rows.append({
            "hour": int(hour),
            "sample_count": int(len(hg)),
            "site_mean_nrmse_percent": float(np.mean(site_vals)) if site_vals else float("nan"),
        })
    return pd.DataFrame(rows).sort_values("hour").reset_index(drop=True)


# ─── 逐小时城市 NRMSE ────────────────────────────────────────────────────────

def hourly_city_nrmse(
    eval_df: pd.DataFrame,
    pred_col: str = "pred_mw",
    actual_col: str = "actual_mw",
    capacity_col: str = "capacity_mw",
    site_col: str = "site_id",
    hour_col: str = "hour",
) -> pd.DataFrame:
    """
    逐小时城市 NRMSE。

    每小时将所有站点同一时间点功率求和，再算城市级 RMSE。

    Returns:
        DataFrame，含 hour, city_nrmse_percent。
    """
    capacity_sum = float(
        eval_df[[site_col, capacity_col]]
        .drop_duplicates(subset=[site_col])[capacity_col]
        .sum()
    )
    if capacity_sum <= 0:
        return pd.DataFrame(columns=["hour", "city_nrmse_percent"])

    rows = []
    for hour, hg in eval_df.groupby(hour_col):
        agg = hg.groupby("time", as_index=False).agg(
            actual=(actual_col, "sum"),
            pred=(pred_col, "sum"),
        )
        rows.append({
            "hour": int(hour),
            "city_nrmse_percent": nrmse_percent(
                agg["actual"].values, agg["pred"].values, capacity_sum
            ),
        })
    return pd.DataFrame(rows).sort_values("hour").reset_index(drop=True)


# ─── 最终预测列强约束断言 ────────────────────────────────────────────────────

def assert_final_prediction_ready(
    df: pd.DataFrame,
    pred_col: str = "power_pred_final",
    actual_col: str = "power_mw",
    split_col: str = "split",
) -> None:
    """
    断言最终预测列就绪。

    Raises:
        KeyError: 缺少必要列。
        ValueError: 列全为空。
    """
    if pred_col not in df.columns:
        raise KeyError(f"final prediction column missing: {pred_col}")
    if df[pred_col].isna().all():
        raise ValueError(f"{pred_col} is all NaN — prediction pipeline failed")
    if actual_col not in df.columns:
        raise KeyError(f"actual power column missing: {actual_col}")
    if split_col not in df.columns:
        raise KeyError(f"split column missing: {split_col}")
    if "future" in df[split_col].values and (
        df.loc[df[split_col] == "future", pred_col].notna().all()
    ):
        # future 有预测值是可以的，但必须明确
        pass
