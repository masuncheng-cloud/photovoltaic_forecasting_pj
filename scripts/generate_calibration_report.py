#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成校准报告和校准参数摘要
============================
确保校准保护机制真正生效，并输出每站点校准状态。
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}

# 校准参数约束
CAL_A_MIN, CAL_A_MAX = 0.95, 1.30
CAL_B_MIN, CAL_B_MAX = -0.10, 0.20
CAL_IMPROVEMENT_THRESHOLD = 0.98
CAL_MIN_ACTIVE_ROWS = 30


def mape(y_true, y_pred):
    mask = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / y_true[mask]) * 100)


def wape(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred) & (y_true > 0)
    if not mask.any():
        return np.nan
    return float(np.sum(np.abs(y_true[mask] - y_pred[mask])) / np.sum(np.abs(y_true[mask])) * 100)


def per_site_calibration(df):
    """
    逐站点校准：
    1. 只用训练集拟合校准参数
    2. 用验证集判断是否启用
    3. 输出每站点启用状态
    """
    print("=" * 60)
    print("Per-site Calibration")
    print("=" * 60)

    # 只使用训练集数据
    df_train = df[df["split"] == "train"].copy()
    df_valid = df[df["split"] == "valid"].copy()

    print(f"训练集样本: {len(df_train):,}")
    print(f"验证集样本: {len(df_valid):,}")

    site_ids = sorted(df_train["site_id"].unique())
    calibration_results = []

    for sid in site_ids:
        if sid in BAD_SITES:
            continue

        train_sub = df_train[df_train["site_id"] == sid]
        valid_sub = df_valid[df_valid["site_id"] == sid]

        if len(train_sub) < CAL_MIN_ACTIVE_ROWS or len(valid_sub) < 10:
            calibration_results.append({
                "site_id": sid,
                "a": 1.0, "b": 0.0,
                "enabled": False,
                "reason": "insufficient_samples",
                "train_samples": len(train_sub),
                "valid_samples": len(valid_sub),
                "valid_wape_before": np.nan,
                "valid_wape_after": np.nan,
                "valid_improvement": np.nan,
            })
            continue

        # 训练集上学习参数
        y_train = train_sub["power_mw"].values.astype(float)
        p_train = train_sub["power_pred"].values.astype(float)

        best_a, best_b = 1.0, 0.0
        best_score = float("inf")

        # 网格搜索最优 (a, b)
        for a in np.linspace(CAL_A_MIN, CAL_A_MAX, 8):
            for b in np.linspace(CAL_B_MIN, CAL_B_MAX, 8):
                p_cal = np.clip(a * p_train + b, 0.0, None)
                score = wape(y_train, p_cal)
                if score < best_score:
                    best_score = score
                    best_a, best_b = a, b

        # 验证集上评估
        y_valid = valid_sub["power_mw"].values.astype(float)
        p_valid = valid_sub["power_pred"].values.astype(float)

        wape_before = wape(y_valid, p_valid)
        p_valid_cal = np.clip(best_a * p_valid + best_b, 0.0, None)
        wape_after = wape(y_valid, p_valid_cal)

        # 判断是否启用：改善 >= 2%
        if wape_before > 0:
            improvement = (wape_before - wape_after) / wape_before
        else:
            improvement = 0

        enabled = improvement >= (1 - CAL_IMPROVEMENT_THRESHOLD) and improvement > 0

        if enabled:
            reason = f"improvement_{improvement:.1%}"
        else:
            reason = f"no_improvement_{improvement:.1%}"

        calibration_results.append({
            "site_id": sid,
            "a": round(best_a, 4),
            "b": round(best_b, 4),
            "enabled": enabled,
            "reason": reason,
            "train_samples": len(train_sub),
            "valid_samples": len(valid_sub),
            "valid_wape_before": round(wape_before, 4) if not np.isnan(wape_before) else np.nan,
            "valid_wape_after": round(wape_after, 4) if not np.isnan(wape_after) else np.nan,
            "valid_improvement": round(improvement * 100, 2) if not np.isnan(improvement) else np.nan,
        })

    result_df = pd.DataFrame(calibration_results)

    # 统计
    n_enabled = result_df["enabled"].sum()
    n_disabled = len(result_df) - n_enabled
    print(f"\n校准启用站点: {n_enabled} / {len(result_df)}")
    print(f"校准禁用站点: {n_disabled}")

    if n_enabled > 0:
        enabled_df = result_df[result_df["enabled"]]
        print(f"\n启用校准的站点:")
        print(enabled_df[["site_id", "a", "b", "valid_improvement"]].to_string(index=False))

    return result_df


def main():
    print("=" * 60)
    print("生成校准报告")
    print("=" * 60)

    # 加载预测数据
    pkl_path = OUT_DIR / "distributed_predictions_fixed.pkl"
    if not pkl_path.exists():
        pkl_path = OUT_DIR / "distributed_predictions_v159.pkl"

    print(f"\n读取: {pkl_path}")
    df = pd.read_pickle(pkl_path)

    # 添加时间字段
    if "hour" not in df.columns:
        df["time"] = pd.to_datetime(df["time"])
        df["hour"] = df["time"].dt.hour
    if "split" not in df.columns:
        from pv_forecasting.core.split import add_standard_split
        df = add_standard_split(df)

    # 执行校准
    cal_df = per_site_calibration(df)

    # 保存校准消融表
    cal_df.to_csv(METRICS_DIR / "calibration_ablation_by_site.csv", index=False, encoding="utf-8-sig")
    print(f"\n保存: {METRICS_DIR / 'calibration_ablation_by_site.csv'}")

    # 保存校准参数摘要
    with open(METRICS_DIR / "calibration_param_summary.txt", "w") as f:
        f.write("=" * 60 + "\n")
        f.write("Per-site Calibration Summary\n")
        f.write("=" * 60 + "\n\n")

        f.write(f"Total sites: {len(cal_df)}\n")
        f.write(f"Enabled: {cal_df['enabled'].sum()}\n")
        f.write(f"Disabled: {(~cal_df['enabled']).sum()}\n\n")

        if cal_df["enabled"].any():
            enabled_df = cal_df[cal_df["enabled"]]
            f.write("Enabled calibration parameters:\n")
            f.write(f"  a mean: {enabled_df['a'].mean():.4f}\n")
            f.write(f"  a std: {enabled_df['a'].std():.4f}\n")
            f.write(f"  b mean: {enabled_df['b'].mean():.4f}\n")
            f.write(f"  b std: {enabled_df['b'].std():.4f}\n")
            f.write(f"  mean improvement: {enabled_df['valid_improvement'].mean():.2f}%\n")

    print(f"保存: {METRICS_DIR / 'calibration_param_summary.txt'}")

    # 更新 predictions 文件中的 calibration_enabled 字段
    cal_enabled_map = dict(zip(cal_df["site_id"], cal_df["enabled"]))

    df["calibration_enabled"] = df["site_id"].map(cal_enabled_map).fillna(False)

    # 保存更新后的 predictions
    df.to_pickle(pkl_path)
    print(f"更新: {pkl_path} (添加 calibration_enabled 字段)")

    print("\n" + "=" * 60)
    print("校准报告生成完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
