#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10-14 点站点级 NRMSE 专项校准
============================

只使用 valid 集学习校准参数，然后应用到 full 表。

思路：
  1. 保留当前 V1/BlendTotal 候选。
  2. 对 10-14 点，使用 valid 集学习站点级缩放系数。
  3. 校准目标：容量归一化 RMSE。
  4. 对每个 (site_id, hour) 学一个 shrinkage 后的乘法校准系数。
  5. final 选择时，10-14 点允许出现 MiddaySiteCalibrated。

输出：
  tables/distributed_predictions_midday_site_calibrated_full.pkl
  tables/distributed_predictions_midday_site_calibrated_eval.pkl
  metrics/midday_site_calibration_params.csv
  metrics/midday_site_calibration_valid_ablation.csv
"""
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load, write_prediction_pickle_atomic
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics


TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)

MIDDAY_HOURS = [10, 11, 12, 13, 14]
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}

IN_FULL = TABLES_DIR / "distributed_predictions_final_full.pkl"
if not IN_FULL.exists():
    IN_FULL = TABLES_DIR / "distributed_predictions_fixed_full.pkl"

OUT_FULL = TABLES_DIR / "distributed_predictions_midday_site_calibrated_full.pkl"
OUT_EVAL = TABLES_DIR / "distributed_predictions_midday_site_calibrated_eval.pkl"
OUT_PARAMS = METRICS_DIR / "midday_site_calibration_params.csv"
OUT_VALID = METRICS_DIR / "midday_site_calibration_valid_ablation.csv"


def _ensure_basic_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour
    if "date" not in out.columns:
        out["date"] = out["time"].dt.date
    return out


def _site_hour_scale(y_true, y_pred, cap, min_rows=40):
    """最小二乘乘法校准系数，目标 y ≈ k * pred。"""
    yt = pd.to_numeric(y_true, errors="coerce").to_numpy(dtype=float)
    yp = pd.to_numeric(y_pred, errors="coerce").to_numpy(dtype=float)
    cp = pd.to_numeric(cap, errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(yt) & np.isfinite(yp) & np.isfinite(cp) & (yt > 0) & (yp > 0) & (cp > 0)
    if int(m.sum()) < min_rows:
        return np.nan, int(m.sum())
    denom = float(np.sum(yp[m] ** 2))
    if denom <= 1e-9:
        return np.nan, int(m.sum())
    k = float(np.sum(yt[m] * yp[m]) / denom)
    return k, int(m.sum())


def _capacity_nrmse(df: pd.DataFrame, pred_col: str = "power_pred") -> float:
    """单行数据框的容量归一化 NRMSE。"""
    yt = pd.to_numeric(df["power_mw"], errors="coerce").to_numpy(dtype=float)
    yp = pd.to_numeric(df[pred_col], errors="coerce").to_numpy(dtype=float)
    cap = pd.to_numeric(df["capacity_mw"], errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(yt) & np.isfinite(yp) & np.isfinite(cap) & (cap > 0)
    if not m.any():
        return np.nan
    rmse = float(np.sqrt(np.mean((yt[m] - yp[m]) ** 2)))
    return rmse / float(np.nanmean(cap[m])) * 100.0


def _make_pred_candidate(df: pd.DataFrame, alpha: float) -> pd.Series:
    """alpha * 当前模型预测 + (1-alpha) * pred_baseline。"""
    ml = pd.to_numeric(df["power_pred"], errors="coerce")
    if "pred_baseline" not in df.columns:
        return ml.fillna(ml)
    bl = pd.to_numeric(df["pred_baseline"], errors="coerce")
    pred = alpha * ml + (1.0 - alpha) * bl
    return pred.fillna(ml).fillna(bl)


def learn_params(df: pd.DataFrame) -> pd.DataFrame:
    """在 valid 集上学习小时级、站点小时级校准参数。"""
    valid = df[
        (df["split"] == "valid")
        & (df["hour"].isin(MIDDAY_HOURS))
        & (~df["site_id"].isin(BAD_SITES))
        & (pd.to_numeric(df["power_mw"], errors="coerce") > 0)
    ].copy()

    if valid.empty:
        raise RuntimeError("valid 集为空，无法学习 midday 校准参数")

    rows = []

    # 候选 alpha：主体时段不应过度靠 baseline，保留偏 ML 的候选。
    alpha_grid = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]

    for h in MIDDAY_HOURS:
        vh = valid[valid["hour"] == h].copy()
        if vh.empty:
            continue

        # 先在 valid 上选一个小时级最优 alpha，目标是站点平均 NRMSE。
        alpha_scores = []
        for alpha in alpha_grid:
            vh[f"pred_alpha"] = _make_pred_candidate(vh, alpha)
            site_scores = []
            for _, sg in vh.groupby("site_id"):
                nr = _capacity_nrmse(sg.rename(columns={"pred_alpha": "power_pred"}), "power_pred")
                if np.isfinite(nr):
                    site_scores.append(nr)
            score = float(np.nanmean(site_scores)) if site_scores else np.nan
            alpha_scores.append((alpha, score))

        alpha_scores = [(a, s) for a, s in alpha_scores if np.isfinite(s)]
        best_alpha = min(alpha_scores, key=lambda x: x[1])[0] if alpha_scores else 1.0
        vh["pred_alpha"] = _make_pred_candidate(vh, best_alpha)

        # 小时整体 k
        hour_k, hour_n = _site_hour_scale(vh["power_mw"], vh["pred_alpha"], vh["capacity_mw"], min_rows=80)
        if not np.isfinite(hour_k):
            hour_k = 1.0

        for sid, sg in vh.groupby("site_id"):
            site_k, n = _site_hour_scale(sg["power_mw"], sg["pred_alpha"], sg["capacity_mw"], min_rows=30)

            # shrinkage：样本少时向小时整体系数收缩。
            if np.isfinite(site_k):
                weight = n / (n + 80.0)
                k = weight * site_k + (1.0 - weight) * hour_k
            else:
                weight = 0.0
                k = hour_k

            # 防止过度校准。
            k = float(np.clip(k, 0.75, 1.25))

            rows.append({
                "hour": int(h),
                "site_id": sid,
                "best_alpha": float(best_alpha),
                "hour_k": float(hour_k),
                "site_k_raw": float(site_k) if np.isfinite(site_k) else np.nan,
                "k_final": k,
                "n_valid": int(n),
                "shrink_weight": round(float(weight), 4),
            })

    params = pd.DataFrame(rows)
    if params.empty:
        raise RuntimeError("未学习到任何 midday 校准参数")
    return params


def apply_params(df: pd.DataFrame, params: pd.DataFrame) -> pd.DataFrame:
    """将 midday 校准应用到全表。"""
    out = df.copy()
    out["_row_order"] = np.arange(len(out))

    p = params[["hour", "site_id", "best_alpha", "k_final"]].copy()
    out = out.merge(p, on=["hour", "site_id"], how="left")

    # 计算 blended 预测（power_pred * alpha + pred_baseline * (1-alpha)）
    ml = pd.to_numeric(out["power_pred"], errors="coerce")
    bl = pd.to_numeric(out.get("pred_baseline", pd.Series(0.0, index=out.index)), errors="coerce")
    best_alpha_filled = out["best_alpha"].fillna(1.0)
    k_filled = out["k_final"].fillna(1.0)

    blended = best_alpha_filled * ml + (1.0 - best_alpha_filled) * bl.fillna(ml)
    blended = blended.fillna(ml)

    # 应用校准系数
    calibrated = blended * k_filled
    cap = pd.to_numeric(out["capacity_mw"], errors="coerce").fillna(0.0)
    calibrated = calibrated.clip(lower=0.0, upper=cap)

    # 只对 midday 小时应用校准
    midday_mask = out["hour"].isin(MIDDAY_HOURS) & out["best_alpha"].notna()
    out["_original_power_pred"] = out["power_pred"].copy()
    out.loc[midday_mask, "power_pred"] = calibrated[midday_mask]

    out = out.sort_values("_row_order").drop(columns=["_row_order", "best_alpha", "k_final", "_original_power_pred"])
    return out


def valid_ablation(df_before: pd.DataFrame, df_after: pd.DataFrame) -> pd.DataFrame:
    """在 valid 集上做 midday 校准前后对比。"""
    rows = []
    for h in MIDDAY_HOURS:
        b = df_before[
            (df_before["split"] == "valid")
            & (df_before["hour"] == h)
            & (~df_before["site_id"].isin(BAD_SITES))
            & (pd.to_numeric(df_before["power_mw"], errors="coerce") > 0)
        ]
        a = df_after[
            (df_after["split"] == "valid")
            & (df_after["hour"] == h)
            & (~df_after["site_id"].isin(BAD_SITES))
            & (pd.to_numeric(df_after["power_mw"], errors="coerce") > 0)
        ]
        if len(b) == 0 or len(a) == 0:
            continue
        b_met = hourly_nrmse_metrics(b.rename(columns={"power_pred": "power_pred_before"}), "power_pred_before")
        a_met = hourly_nrmse_metrics(a, "power_pred")
        b_row = b_met[b_met["hour"] == h]
        a_row = a_met[a_met["hour"] == h]
        if b_row.empty or a_row.empty:
            continue
        rows.append({
            "hour": int(h),
            "valid_rows": len(a),
            "before_site_nrmse_mean_pct": float(b_row.iloc[0]["site_nrmse_mean_pct"]) if np.isfinite(b_row.iloc[0]["site_nrmse_mean_pct"]) else np.nan,
            "after_site_nrmse_mean_pct": float(a_row.iloc[0]["site_nrmse_mean_pct"]) if np.isfinite(a_row.iloc[0]["site_nrmse_mean_pct"]) else np.nan,
            "before_city_nrmse_pct": float(b_row.iloc[0]["city_nrmse_pct"]) if np.isfinite(b_row.iloc[0]["city_nrmse_pct"]) else np.nan,
            "after_city_nrmse_pct": float(a_row.iloc[0]["city_nrmse_pct"]) if np.isfinite(a_row.iloc[0]["city_nrmse_pct"]) else np.nan,
            "site_nrmse_improvement_pct": (
                float(b_row.iloc[0]["site_nrmse_mean_pct"]) - float(a_row.iloc[0]["site_nrmse_mean_pct"])
            ) if (np.isfinite(b_row.iloc[0]["site_nrmse_mean_pct"]) and np.isfinite(a_row.iloc[0]["site_nrmse_mean_pct"])) else np.nan,
        })
    return pd.DataFrame(rows)


def main():
    print("=" * 70)
    print("10-14 点站点级 NRMSE 专项校准")
    print("=" * 70)
    print(f"读取: {IN_FULL}")

    if not IN_FULL.exists():
        print(f"[ERROR] 输入文件不存在: {IN_FULL}")
        print("请先运行 select_final_prediction_by_guard.py 生成最终预测表。")
        sys.exit(1)

    df = safe_pickle_load(IN_FULL)
    df = _ensure_basic_columns(df)

    print(f"Loaded {len(df):,} rows")
    print(f"Split 分布: {df['split'].value_counts().to_dict()}")
    print(f"Hours: {sorted(df['hour'].unique())}")

    # 学习参数
    params = learn_params(df)
    params.to_csv(OUT_PARAMS, index=False, encoding="utf-8-sig")
    print(f"\n已保存参数: {OUT_PARAMS}")
    print(f"共 {len(params)} 个 (hour, site) 校准对")
    print(f"k_final 范围: [{params['k_final'].min():.4f}, {params['k_final'].max():.4f}]")
    print(f"k_final 均值: {params['k_final'].mean():.4f}, 中位数: {params['k_final'].median():.4f}")

    # 应用参数
    df_cal = apply_params(df, params)

    # valid 消融
    ab = valid_ablation(df, df_cal)
    ab.to_csv(OUT_VALID, index=False, encoding="utf-8-sig")
    print(f"\n已保存 valid 消融: {OUT_VALID}")
    if not ab.empty:
        print(ab.to_string(index=False))
        improved = (ab["site_nrmse_improvement_pct"] > 0).sum()
        print(f"\n[AB] 10-14 点中 {improved}/{len(ab)} 个小时站点 NRMSE 改善")

    # 构建 eval 表并保存
    eval_cal = build_eval_frame(
        df_cal,
        pred_col="power_pred",
        split="test",
        hours=tuple(range(6, 20)),
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=53,
    )

    write_prediction_pickle_atomic(
        df_cal,
        OUT_FULL,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
    )
    print(f"\n已保存: {OUT_FULL}")

    write_prediction_pickle_atomic(
        eval_cal,
        OUT_EVAL,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
        hour_range=(6, 19),
    )
    print(f"已保存: {OUT_EVAL}")
    print("Done.")


if __name__ == "__main__":
    main()
