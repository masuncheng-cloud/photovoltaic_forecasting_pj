#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10-14 点中午残差专家校正
========================

目标：
  在不使用 test 集调参的前提下，继续降低 10-14 点站点平均 NRMSE。

方法：
  1. 读取 midday_site_calibrated_full 作为中午初始预测（不存在则读 fixed_full）。
  2. 仅用 train 学习残差：
       residual_norm = (power_mw - power_pred) / capacity_mw
  3. 分层学习残差中位数：
       (site_id, hour, month) → (site_id, hour) → (hour, capacity_bucket) → (hour)
  4. 用 valid 选择残差强度 lambda 和 clip 范围。
  5. 应用到 full 表，输出新的候选版本。
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

IN_FIXED = TABLES_DIR / "distributed_predictions_fixed_full.pkl"
IN_MIDDAY = TABLES_DIR / "distributed_predictions_midday_site_calibrated_full.pkl"

OUT_FULL = TABLES_DIR / "distributed_predictions_midday_residual_specialist_full.pkl"
OUT_EVAL = TABLES_DIR / "distributed_predictions_midday_residual_specialist_eval.pkl"
OUT_PARAMS = METRICS_DIR / "midday_residual_specialist_params.csv"
OUT_VALID = METRICS_DIR / "midday_residual_specialist_valid_ablation.csv"


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour
    if "date" not in out.columns:
        out["date"] = out["time"].dt.date
    out["month"] = out["time"].dt.month
    return out


def add_capacity_bucket(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    cap = pd.to_numeric(out["capacity_mw"], errors="coerce")
    try:
        out["capacity_bucket"] = pd.qcut(cap.rank(method="first"), q=5, labels=False, duplicates="drop")
    except Exception:
        out["capacity_bucket"] = 0
    out["capacity_bucket"] = out["capacity_bucket"].fillna(0).astype(int)
    return out


def site_nrmse_mean(df: pd.DataFrame, pred_col: str = "power_pred") -> float:
    vals = []
    for _, sg in df.groupby("site_id"):
        y = pd.to_numeric(sg["power_mw"], errors="coerce").to_numpy(dtype=float)
        p = pd.to_numeric(sg[pred_col], errors="coerce").to_numpy(dtype=float)
        c = pd.to_numeric(sg["capacity_mw"], errors="coerce").to_numpy(dtype=float)
        m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (c > 0)
        if not m.any():
            continue
        rmse = float(np.sqrt(np.mean((y[m] - p[m]) ** 2)))
        cm = float(np.nanmean(c[m]))
        if cm > 0:
            vals.append(rmse / cm * 100.0)
    return float(np.nanmean(vals)) if vals else np.nan


def learn_residual_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    train = df[
        (df["split"] == "train")
        & (df["hour"].isin(MIDDAY_HOURS))
        & (~df["site_id"].isin(BAD_SITES))
        & (pd.to_numeric(df["power_mw"], errors="coerce") > 0)
        & (pd.to_numeric(df["capacity_mw"], errors="coerce") > 0)
    ].copy()
    if train.empty:
        raise RuntimeError("train 集中午样本为空，无法学习残差参数")

    cap = pd.to_numeric(train["capacity_mw"], errors="coerce")
    y = pd.to_numeric(train["power_mw"], errors="coerce")
    p = pd.to_numeric(train["power_pred"], errors="coerce")
    train["residual_norm"] = ((y - p) / cap).clip(-0.35, 0.35)

    def agg(keys, min_n):
        g = (
            train.groupby(keys, dropna=False)["residual_norm"]
            .agg(["median", "count"])
            .reset_index()
            .rename(columns={"median": "residual_norm_median", "count": "n_train"})
        )
        return g[g["n_train"] >= min_n].copy()

    return {
        "site_hour_month": agg(["site_id", "hour", "month"], 12),
        "site_hour": agg(["site_id", "hour"], 35),
        "hour_capacity": agg(["hour", "capacity_bucket"], 80),
        "hour": agg(["hour"], 120),
    }


def attach_residual(df: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    out = df.copy()
    out["_row_id"] = np.arange(len(out))

    sources = [
        ("site_hour_month", ["site_id", "hour", "month"], "r_shm", "n_shm"),
        ("site_hour", ["site_id", "hour"], "r_sh", "n_sh"),
        ("hour_capacity", ["hour", "capacity_bucket"], "r_hc", "n_hc"),
        ("hour", ["hour"], "r_h", "n_h"),
    ]

    for name, keys, r_col, n_col in sources:
        tab = tables[name].rename(
            columns={
                "residual_norm_median": r_col,
                "n_train": n_col,
            }
        )
        out = out.merge(tab[keys + [r_col, n_col]], on=keys, how="left")

    # 分层回退：优先站点-小时-月份，再站点-小时，再小时-容量桶，最后小时整体。
    out["residual_norm_hat"] = out["r_shm"]
    out["residual_source"] = "site_hour_month"

    m = out["residual_norm_hat"].isna()
    out.loc[m, "residual_norm_hat"] = out.loc[m, "r_sh"]
    out.loc[m & out["residual_norm_hat"].notna(), "residual_source"] = "site_hour"

    m = out["residual_norm_hat"].isna()
    out.loc[m, "residual_norm_hat"] = out.loc[m, "r_hc"]
    out.loc[m & out["residual_norm_hat"].notna(), "residual_source"] = "hour_capacity"

    m = out["residual_norm_hat"].isna()
    out.loc[m, "residual_norm_hat"] = out.loc[m, "r_h"]
    out.loc[m & out["residual_norm_hat"].notna(), "residual_source"] = "hour"

    out["residual_norm_hat"] = out["residual_norm_hat"].fillna(0.0)

    # 样本少时自动收缩，防止站点小样本过拟合。
    n_eff = (
        out["n_shm"]
        .fillna(out["n_sh"])
        .fillna(out["n_hc"])
        .fillna(out["n_h"])
        .fillna(0.0)
    )
    shrink = n_eff / (n_eff + 80.0)
    out["residual_norm_hat"] = out["residual_norm_hat"] * shrink

    drop_cols = ["r_shm", "n_shm", "r_sh", "n_sh", "r_hc", "n_hc", "r_h", "n_h", "_row_id"]
    return out.drop(columns=[c for c in drop_cols if c in out.columns])


def apply_candidate(df: pd.DataFrame, lam: float, clip_norm: float) -> pd.DataFrame:
    out = df.copy()
    pred = pd.to_numeric(out["power_pred"], errors="coerce")
    cap = pd.to_numeric(out["capacity_mw"], errors="coerce").fillna(0.0)
    residual = pd.to_numeric(out["residual_norm_hat"], errors="coerce").fillna(0.0)
    residual = residual.clip(-clip_norm, clip_norm)

    # residual_norm_hat = (actual - pred) / capacity → 乘回 capacity 得到绝对残差
    adjusted = pred + lam * residual * cap
    adjusted = adjusted.clip(lower=0.0, upper=cap)

    mask = out["hour"].isin(MIDDAY_HOURS)
    out.loc[mask, "power_pred"] = adjusted[mask]
    out["midday_residual_lambda"] = lam
    out["midday_residual_clip_norm"] = clip_norm
    return out


def valid_ablation(base_df: pd.DataFrame, cand_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for h in MIDDAY_HOURS:
        b = base_df[
            (base_df["split"] == "valid")
            & (base_df["hour"] == h)
            & (~base_df["site_id"].isin(BAD_SITES))
            & (pd.to_numeric(base_df["power_mw"], errors="coerce") > 0)
        ].copy()
        c = cand_df[
            (cand_df["split"] == "valid")
            & (cand_df["hour"] == h)
            & (~cand_df["site_id"].isin(BAD_SITES))
            & (pd.to_numeric(cand_df["power_mw"], errors="coerce") > 0)
        ].copy()
        if b.empty or c.empty:
            continue
        rows.append({
            "hour": h,
            "valid_rows": len(c),
            "before_site_nrmse_mean_pct": round(site_nrmse_mean(b), 4),
            "after_site_nrmse_mean_pct": round(site_nrmse_mean(c), 4),
            "improvement_pct_point": round(site_nrmse_mean(b) - site_nrmse_mean(c), 4),
        })
    return pd.DataFrame(rows)


def choose_valid_params(df_with_residual: pd.DataFrame) -> tuple[float, float, pd.DataFrame]:
    grid = []
    for lam in [0.25, 0.40, 0.55, 0.70, 0.85, 1.00]:
        for clip_norm in [0.04, 0.06, 0.08, 0.10, 0.12]:
            cand = apply_candidate(df_with_residual, lam=lam, clip_norm=clip_norm)
            vals = []
            for h in MIDDAY_HOURS:
                sub = cand[
                    (cand["split"] == "valid")
                    & (cand["hour"] == h)
                    & (~cand["site_id"].isin(BAD_SITES))
                    & (pd.to_numeric(cand["power_mw"], errors="coerce") > 0)
                ]
                if len(sub):
                    vals.append(site_nrmse_mean(sub))
            score = float(np.nanmean(vals)) if vals else np.nan
            grid.append({
                "lambda": lam,
                "clip_norm": clip_norm,
                "valid_midday_site_nrmse_mean_pct": score,
            })

    grid_df = pd.DataFrame(grid).dropna(subset=["valid_midday_site_nrmse_mean_pct"])
    if grid_df.empty:
        raise RuntimeError("valid 参数网格为空")
    best = grid_df.sort_values("valid_midday_site_nrmse_mean_pct").iloc[0]
    return float(best["lambda"]), float(best["clip_norm"]), grid_df


def main():
    print("=" * 80)
    print("10-14 点中午残差专家校正")
    print("=" * 80)

    if IN_MIDDAY.exists():
        in_path = IN_MIDDAY
        print(f"读取中午乘法校准版本: {in_path}")
    else:
        in_path = IN_FIXED
        print(f"中午乘法校准版本不存在，读取 fixed: {in_path}")

    if not in_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {in_path}")

    df = safe_pickle_load(in_path)
    df = ensure_columns(df)
    df = add_capacity_bucket(df)
    print(f"Loaded rows: {len(df):,}")
    print(f"Split: {df['split'].value_counts().to_dict()}")

    tables = learn_residual_tables(df)
    param_rows = []
    for name, tab in tables.items():
        x = tab.copy()
        x["level"] = name
        param_rows.append(x)
    params_df = pd.concat(param_rows, ignore_index=True)
    params_df.to_csv(OUT_PARAMS, index=False, encoding="utf-8-sig")
    print(f"保存残差参数: {OUT_PARAMS}")

    df_res = attach_residual(df, tables)
    best_lam, best_clip, grid_df = choose_valid_params(df_res)
    grid_df.to_csv(METRICS_DIR / "midday_residual_specialist_valid_grid.csv", index=False, encoding="utf-8-sig")
    print(f"valid 最优参数: lambda={best_lam}, clip_norm={best_clip}")

    df_cand = apply_candidate(df_res, lam=best_lam, clip_norm=best_clip)

    ab = valid_ablation(df, df_cand)
    ab.to_csv(OUT_VALID, index=False, encoding="utf-8-sig")
    print("valid 消融:")
    print(ab.to_string(index=False))

    eval_df = build_eval_frame(
        df_cand,
        pred_col="power_pred",
        split="test",
        hours=tuple(range(6, 20)),
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=53,
    )

    write_prediction_pickle_atomic(
        df_cand,
        OUT_FULL,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
    )
    write_prediction_pickle_atomic(
        eval_df,
        OUT_EVAL,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
        hour_range=(6, 19),
    )

    hmet = hourly_nrmse_metrics(eval_df)
    hmet[hmet["hour"].isin(MIDDAY_HOURS)].to_csv(
        METRICS_DIR / "midday_residual_specialist_test_hourly_nrmse.csv",
        index=False,
        encoding="utf-8-sig",
    )
    print(f"保存: {OUT_FULL}")
    print(f"保存: {OUT_EVAL}")
    print("test 中午 NRMSE，仅用于最终查看，不用于调参:")
    print(hmet[hmet["hour"].isin(MIDDAY_HOURS)].to_string(index=False))


if __name__ == "__main__":
    main()
