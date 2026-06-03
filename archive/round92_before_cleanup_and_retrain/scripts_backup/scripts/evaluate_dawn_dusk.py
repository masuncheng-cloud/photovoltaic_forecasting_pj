#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
黎明/黄昏专项评估
==================
对早晚 ramp 时段做专项分析，输出专项指标。
"""
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}


def wape(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred) & (y_true > 0)
    if not mask.any():
        return np.nan
    return float(np.sum(np.abs(y_true[mask] - y_pred[mask])) / np.sum(np.abs(y_true[mask])) * 100)


def mae(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask])))


def city_rel_err(y_true_sum, y_pred_sum):
    if not np.isfinite(y_true_sum) or y_true_sum <= 0:
        return np.nan
    return float(np.abs(y_pred_sum - y_true_sum) / y_true_sum * 100)


def main():
    print("=" * 60)
    print("黎明/黄昏专项评估")
    print("=" * 60)

    # 加载数据
    pkl_path = OUT_DIR / "distributed_predictions_fixed.pkl"
    if not pkl_path.exists():
        print(f"[ERROR] 文件不存在: {pkl_path}")
        return

    print(f"\n读取: {pkl_path}")
    df = pd.read_pickle(pkl_path)

    # 添加时间字段
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour

    # 筛选有效样本
    df = df[
        (df["hour"] >= 6) & (df["hour"] <= 19) &
        (df["power_mw"] > 0) &
        (~df["site_id"].isin(BAD_SITES)) &
        df["power_mw"].notna() &
        df["power_pred"].notna()
    ].copy()

    # 添加原始预测值
    if "power_pred_original" not in df.columns:
        df["power_pred_original"] = df["power_pred"].copy()

    print(f"有效样本: {len(df):,}")

    # 黎明/黄昏时段
    dawn_hours = [6, 7]
    dusk_hours = [17, 18, 19]
    ramp_hours = dawn_hours + dusk_hours

    # 按时段分组
    dawn_df = df[df["hour"].isin(dawn_hours)]
    dusk_df = df[df["hour"].isin(dusk_hours)]
    ramp_df = df[df["hour"].isin(ramp_hours)]
    midday_df = df[(df["hour"] >= 10) & (df["hour"] <= 14)]

    rows = []

    for period_name, period_df in [
        ("dawn (6-7)", dawn_df),
        ("dusk (17-19)", dusk_df),
        ("ramp (6-7, 17-19)", ramp_df),
        ("midday (10-14)", midday_df),
    ]:
        if len(period_df) == 0:
            continue

        # 原始预测
        yt = period_df["power_mw"].values.astype(float)
        yp_orig = period_df["power_pred_original"].values.astype(float)
        yp_fix = period_df["power_pred"].values.astype(float)

        yt_sum = yt.sum()
        yp_orig_sum = yp_orig.sum()
        yp_fix_sum = yp_fix.sum()

        row = {
            "period": period_name,
            "n_samples": len(period_df),
            "before_WAPE": round(wape(yt, yp_orig), 4),
            "after_WAPE": round(wape(yt, yp_fix), 4),
            "before_MAE": round(mae(yt, yp_orig), 4),
            "after_MAE": round(mae(yt, yp_fix), 4),
            "before_city_rel_err": round(city_rel_err(yt_sum, yp_orig_sum), 4),
            "after_city_rel_err": round(city_rel_err(yt_sum, yp_fix_sum), 4),
            "city_rel_err_improvement": round(
                city_rel_err(yt_sum, yp_orig_sum) - city_rel_err(yt_sum, yp_fix_sum), 4
            ),
        }

        rows.append(row)

    result_df = pd.DataFrame(rows)

    # 保存
    output_path = METRICS_DIR / "dawn_dusk_error_before_after.csv"
    result_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n保存: {output_path}")

    print("\n黎明/黄昏专项评估结果:")
    print(result_df.to_string(index=False))

    # 按时段分析
    print("\n逐小时分析:")
    for h in ramp_hours:
        hour_df = df[df["hour"] == h]
        if len(hour_df) == 0:
            continue

        yt = hour_df["power_mw"].values.astype(float)
        yp_orig = hour_df["power_pred_original"].values.astype(float)
        yp_fix = hour_df["power_pred"].values.astype(float)

        yt_sum = yt.sum()
        rel_orig = city_rel_err(yt_sum, yp_orig.sum())
        rel_fix = city_rel_err(yt_sum, yp_fix.sum())

        print(f"  Hour {h:02d}: city_rel_err {rel_orig:.2f}% -> {rel_fix:.2f}% (improvement: {rel_orig - rel_fix:+.2f}%)")

    print("\n" + "=" * 60)
    print("黎明/黄昏专项评估完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
