#!/usr/bin/env python3
"""
diagnose_round71_drift_and_error_sources.py
===========================================
Round71 第一步：诊断季节漂移、月份误差和站点误差。
只有诊断条件成立，才允许训练对应候选。

输出：
    output/pv_pipeline/round71/round71_drift_by_split_month.csv
    output/pv_pipeline/round71/round71_error_by_hour_month.csv
    output/pv_pipeline/round71/round71_error_by_site_month.csv
    output/pv_pipeline/round71/round71_high_error_site_diagnosis.csv
    output/pv_pipeline/round71/round71_diagnosis_summary.json
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round71"


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def compute_metrics_for_df(df, pred_col, actual_col):
    """计算一个 df 的各项指标。"""
    if len(df) == 0:
        return {}
    cap_sum = float(df.drop_duplicates("site_id")["capacity_mw"].sum())
    agg = df.groupby("time", as_index=False).agg(
        a=(actual_col, "sum"), p=(pred_col, "sum")
    )
    city_nrmse = rmse(agg["a"].values, agg["p"].values) / cap_sum * 100 if cap_sum > 0 else np.nan
    a_sum = float(df[actual_col].sum())
    p_sum = float(df[pred_col].sum())
    bias_pct = (p_sum - a_sum) / a_sum * 100 if abs(a_sum) > 1e-9 else np.nan
    abs_bias_pct = abs(bias_pct)
    n_sites = int(df["site_id"].nunique())
    n_rows = len(df)
    pos_rate = float((df[actual_col] > 0).mean())
    inactive_rate = float((df[actual_col] <= 0).mean())
    actual_mean = float(df[actual_col].mean())
    pred_mean = float(df[pred_col].mean())
    return {
        "n_rows": n_rows, "n_sites": n_sites,
        "positive_rate": round(pos_rate, 4),
        "inactive_rate": round(inactive_rate, 4),
        "actual_mean_mw": round(actual_mean, 4),
        "pred_mean_mw": round(pred_mean, 4),
        "bias_pct": round(bias_pct, 4),
        "abs_bias_pct": round(abs_bias_pct, 4),
        "city_nrmse_pct": round(city_nrmse, 4),
    }


def main():
    parser = argparse.ArgumentParser(description="Round71 诊断脚本")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    if args.config is None:
        args.config = str(PROJECT_ROOT / "configs" / "round71_conservative_residual.yaml")
    cfg = yaml.safe_load(open(args.config))

    OUT.mkdir(parents=True, exist_ok=True)

    # ── 读取数据 ──────────────────────────────────────────────────────────────
    input_path = PROJECT_ROOT / cfg["paths"]["input_pred"]
    print(f"[INFO] 读取: {input_path}")
    df = pd.read_pickle(input_path)
    df["time"] = pd.to_datetime(df["time"])
    df["month"] = df["time"].dt.month
    df["hour"] = pd.to_datetime(df["time"]).dt.hour
    print(f"  总行数: {len(df):,}")

    # 过滤
    df = df[df["split"] != "future"].copy()
    df = df[df["hour"].between(6, 19)].copy()
    df = df[df["capacity_mw"] > 0].copy()
    print(f"  过滤后: {len(df):,}  行")

    bl_col = cfg["baseline_col"]
    actual_col = cfg["target_col"]

    # ── 1. 按 split + month 统计 ───────────────────────────────────────────
    print("\n[1] 按 split+month 统计...")
    drift_rows = []
    for (split_name, month), g in df.groupby(["split", "month"]):
        m = compute_metrics_for_df(g, bl_col, actual_col)
        drift_rows.append({
            "split": split_name, "month": month, **m
        })
    drift_df = pd.DataFrame(drift_rows)
    drift_df.to_csv(OUT / "round71_drift_by_split_month.csv",
                    index=False, encoding="utf-8-sig")
    print(f"[OK] {OUT / 'round71_drift_by_split_month.csv'}")
    print(drift_df.to_string(index=False))

    # ── 2. 按 hour + month 统计 ────────────────────────────────────────────
    print("\n[2] 按 hour+month 统计...")
    hour_month_rows = []
    for (month, hour), g in df[df["split"].isin(["valid", "test"])].groupby(["month", "hour"]):
        m = compute_metrics_for_df(g, bl_col, actual_col)
        hour_month_rows.append({"month": month, "hour": hour, **m})
    hour_month_df = pd.DataFrame(hour_month_rows)
    hour_month_df.to_csv(OUT / "round71_error_by_hour_month.csv",
                         index=False, encoding="utf-8-sig")
    print(f"[OK] {OUT / 'round71_error_by_hour_month.csv'}")

    # ── 3. 按 site_id + month 统计 ─────────────────────────────────────────
    print("\n[3] 按 site+month 统计...")
    site_month_rows = []
    for (month, site_id), g in df[df["split"].isin(["valid", "test"])].groupby(["month", "site_id"]):
        m = compute_metrics_for_df(g, bl_col, actual_col)
        cap = float(g["capacity_mw"].iloc[0])
        if cap > 0:
            site_rmses = []
            for _, sg in g.groupby("time"):
                a = sg[actual_col].sum()
                p = sg[bl_col].sum()
                if len(a) > 0:
                    site_rmses.append((float(a) - float(p)) ** 2)
            site_bias = float((g[actual_col] - g[bl_col]).mean())
            site_month_rows.append({
                "month": month, "site_id": site_id,
                "capacity_mw": cap,
                "n_rows": len(g),
                **m,
            })
    site_month_df = pd.DataFrame(site_month_rows)
    site_month_df.to_csv(OUT / "round71_error_by_site_month.csv",
                         index=False, encoding="utf-8-sig")
    print(f"[OK] {OUT / 'round71_error_by_site_month.csv'}")

    # ── 4. 高误差站点归因 ─────────────────────────────────────────────────
    print("\n[4] 高误差站点归因...")

    # 用 valid 站点 NRMSE
    site_metrics_valid = []
    for sid, g in df[df["split"] == "valid"].groupby("site_id"):
        cap = float(g["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        site_rmse = rmse(g[actual_col].values, g[bl_col].values) / cap * 100
        zero_ratio = float((g[actual_col] <= 0).mean())
        actual_mean = float(g[actual_col].mean())
        pred_mean = float(g[bl_col].mean())
        a_sum = float(g[actual_col].sum())
        p_sum = float(g[bl_col].sum())
        bias = (p_sum - a_sum) / a_sum * 100 if abs(a_sum) > 1e-9 else 0.0

        site_metrics_valid.append({
            "site_id": sid, "capacity_mw": cap,
            "nrmse_valid": round(site_rmse, 4),
            "zero_ratio_valid": round(zero_ratio, 4),
            "actual_mean": round(actual_mean, 4),
            "pred_mean": round(pred_mean, 4),
            "bias_pct": round(bias, 4),
            "n_samples_valid": len(g),
        })

    site_metrics_df = pd.DataFrame(site_metrics_valid)
    if len(site_metrics_df) > 0:
        nrmse_top15 = set(site_metrics_df.nlargest(15, "nrmse_valid")["site_id"])
        nrmse_above_12 = set(site_metrics_df[site_metrics_df["nrmse_valid"] > 12]["site_id"])
        high_error_sites = nrmse_top15 | nrmse_above_12

        site_metrics_df["is_high_error"] = site_metrics_df["site_id"].isin(high_error_sites)
        site_metrics_df["label_zero_ratio_high"] = site_metrics_df["zero_ratio_valid"] > 0.3
        site_metrics_df["label_capacity_small"] = site_metrics_df["capacity_mw"] < 0.05
        site_metrics_df["label_capacity_large"] = site_metrics_df["capacity_mw"] > 0.15
        site_metrics_df["label_bias_positive"] = site_metrics_df["bias_pct"] > 1.0
        site_metrics_df["label_bias_negative"] = site_metrics_df["bias_pct"] < -1.0
        site_metrics_df["label_samples_low"] = site_metrics_df["n_samples_valid"] < 500

        site_metrics_df.to_csv(OUT / "round71_high_error_site_diagnosis.csv",
                               index=False, encoding="utf-8-sig")
        print(f"[OK] {OUT / 'round71_high_error_site_diagnosis.csv'}")
        print(f"  高误差站点数: {len(high_error_sites)}")

    # ── 5. 诊断条件判断 ───────────────────────────────────────────────────
    print("\n[5] 诊断条件判断...")
    thresh = cfg.get("diagnosis_thresholds", {})
    conditions = {}

    # 条件 A：季节漂移
    # 比较 test (9-12月) vs valid (7-8月) 的 abs_bias 或 NRMSE
    test_df = df[df["split"] == "test"].copy()
    valid_df_d = df[df["split"] == "valid"].copy()

    if len(test_df) > 0 and len(valid_df_d) > 0:
        test_metrics = compute_metrics_for_df(test_df, bl_col, actual_col)
        valid_metrics = compute_metrics_for_df(valid_df_d, bl_col, actual_col)

        # 9-12月 vs 7-8月
        test_summer = test_df[test_df["month"].isin([9, 10, 11, 12])]
        test_metrics_by_month = {}
        valid_metrics_by_month = {}
        for m in [7, 8, 9, 10, 11, 12]:
            g_test = test_df[test_df["month"] == m]
            g_valid = valid_df_d[valid_df_d["month"] == m]
            if len(g_test) > 0:
                test_metrics_by_month[m] = compute_metrics_for_df(g_test, bl_col, actual_col)
            if len(g_valid) > 0:
                valid_metrics_by_month[m] = compute_metrics_for_df(g_valid, bl_col, actual_col)

        # 计算季节漂移
        valid_avg_nrmse = np.mean([v["city_nrmse_pct"] for v in valid_metrics_by_month.values()]) \
            if valid_metrics_by_month else np.nan
        test_avg_nrmse = np.mean([v["city_nrmse_pct"] for v in test_metrics_by_month.values()]) \
            if test_metrics_by_month else np.nan
        valid_avg_abs_bias = np.mean([v["abs_bias_pct"] for v in valid_metrics_by_month.values()]) \
            if valid_metrics_by_month else np.nan
        test_avg_abs_bias = np.mean([v["abs_bias_pct"] for v in test_metrics_by_month.values()]) \
            if test_metrics_by_month else np.nan

        cond_a_nrmse = bool(abs(test_avg_nrmse - valid_avg_nrmse) >= thresh.get("season_drift_min_pp", 1.0)) \
            if not np.isnan(valid_avg_nrmse) and not np.isnan(test_avg_nrmse) else False
        cond_a_bias = bool(abs(test_avg_abs_bias - valid_avg_abs_bias) >= thresh.get("season_drift_min_pp", 1.0)) \
            if not np.isnan(valid_avg_abs_bias) and not np.isnan(test_avg_abs_bias) else False
        conditions["A_seasonal_drift"] = {
            "成立": cond_a_nrmse or cond_a_bias,
            "test_avg_nrmse": round(test_avg_nrmse, 4) if not np.isnan(test_avg_nrmse) else None,
            "valid_avg_nrmse": round(valid_avg_nrmse, 4) if not np.isnan(valid_avg_nrmse) else None,
            "test_avg_abs_bias": round(test_avg_abs_bias, 4) if not np.isnan(test_avg_abs_bias) else None,
            "valid_avg_abs_bias": round(valid_avg_abs_bias, 4) if not np.isnan(valid_avg_abs_bias) else None,
            "nrmse_drift_pp": round(test_avg_nrmse - valid_avg_nrmse, 4) if not np.isnan(test_avg_nrmse) and not np.isnan(valid_avg_nrmse) else None,
            "bias_drift_pp": round(test_avg_abs_bias - valid_avg_abs_bias, 4) if not np.isnan(test_avg_abs_bias) and not np.isnan(valid_avg_abs_bias) else None,
            "允许训练": cond_a_nrmse or cond_a_bias,
        }
        print(f"  条件A(季节漂移): {'成立 ✓' if conditions['A_seasonal_drift']['成立'] else '不成立 ✗'}")
        if conditions["A_seasonal_drift"]["nrmse_drift_pp"] is not None:
            print(f"    NRMSE漂移: {conditions['A_seasonal_drift']['nrmse_drift_pp']:+.3f}pp")
        if conditions["A_seasonal_drift"]["bias_drift_pp"] is not None:
            print(f"    Bias漂移: {conditions['A_seasonal_drift']['bias_drift_pp']:+.3f}pp")
    else:
        conditions["A_seasonal_drift"] = {"成立": False, "允许训练": False}

    # 条件 B：近期样本更接近 test
    # 比较 train 早期样本 vs 近期样本的分布
    train_df = df[df["split"] == "train"].copy()
    if len(train_df) > 0:
        early_train = train_df[train_df["month"].isin([1, 2, 3, 4])]
        recent_train = train_df[train_df["month"].isin([5, 6])]

        if len(early_train) > 0 and len(recent_train) > 0:
            early_pr = float((early_train[actual_col] > 0).mean())
            recent_pr = float((recent_train[actual_col] > 0).mean())
            test_pr = float((test_df[actual_col] > 0).mean()) if len(test_df) > 0 else np.nan
            valid_pr = float((valid_df_d[actual_col] > 0).mean())

            # 近期样本的正样本率更接近 test/valid
            recent_closer = abs(recent_pr - test_pr) < abs(early_pr - test_pr) if not np.isnan(test_pr) else False
            conditions["B_recency"] = {
                "成立": recent_closer,
                "early_positive_rate": round(early_pr, 4),
                "recent_positive_rate": round(recent_pr, 4),
                "valid_positive_rate": round(valid_pr, 4) if not np.isnan(valid_pr) else None,
                "test_positive_rate": round(test_pr, 4) if not np.isnan(test_pr) else None,
                "允许训练": recent_closer,
            }
            print(f"  条件B(近期样本): {'成立 ✓' if conditions['B_recency']['成立'] else '不成立 ✗'}")
            print(f"    早期正样本率: {early_pr:.3f}  近期: {recent_pr:.3f}  valid: {valid_pr:.3f if not np.isnan(valid_pr) else 0:.3f}  test: {test_pr:.3f if not np.isnan(test_pr) else 0:.3f}")
        else:
            conditions["B_recency"] = {"成立": False, "允许训练": False}
    else:
        conditions["B_recency"] = {"成立": False, "允许训练": False}

    # 条件 C：10-14 点高估
    focus_hours = cfg.get("focus_hours", [10, 11, 12, 13, 14])
    if len(test_df) > 0:
        noon_test = test_df[test_df["hour"].isin(focus_hours)]
        all_test = test_df
        noon_bias = float((noon_test[bl_col].sum() - noon_test[actual_col].sum()) /
                          noon_test[actual_col].sum() * 100) \
            if noon_test[actual_col].sum() > 1e-9 else 0.0
        all_bias = float((all_test[bl_col].sum() - all_test[actual_col].sum()) /
                         all_test[actual_col].sum() * 100) \
            if all_test[actual_col].sum() > 1e-9 else 0.0

        cond_c_bias = noon_bias > thresh.get("noon_bias_high_min_pp", 1.0)
        cond_c_higher = noon_bias > all_bias + thresh.get("noon_bias_high_min_pp", 1.0)
        conditions["C_noon_bias"] = {
            "成立": cond_c_bias or cond_c_higher,
            "noon_bias_pct": round(noon_bias, 4),
            "all_bias_pct": round(all_bias, 4),
            "noon_vs_all_bias_delta": round(noon_bias - all_bias, 4),
            "允许训练": cond_c_bias or cond_c_higher,
        }
        print(f"  条件C(10-14点高估): {'成立 ✓' if conditions['C_noon_bias']['成立'] else '不成立 ✗'}")
        print(f"    noon_bias: {noon_bias:.3f}%  all_bias: {all_bias:.3f}%")
    else:
        conditions["C_noon_bias"] = {"成立": False, "允许训练": False}

    # ── 6. 综合诊断结果 ──────────────────────────────────────────────────────
    summary = {
        "round71_diagnosis": True,
        "conditions": conditions,
        "train_samples": int(len(train_df)),
        "valid_samples": int(len(valid_df_d)),
        "test_samples": int(len(test_df)),
        "high_error_sites": len(high_error_sites) if len(site_metrics_df) > 0 else 0,
        "recommended_candidates": [],
        "halt_reason": None,
    }

    if conditions["A_seasonal_drift"]["允许训练"]:
        summary["recommended_candidates"].append("seasonal_residual_lgb")
    if conditions["B_recency"]["允许训练"]:
        summary["recommended_candidates"].append("recency_residual_lgb")
    if conditions["C_noon_bias"]["允许训练"]:
        summary["recommended_candidates"].append("noon_conservative_residual")

    if len(summary["recommended_candidates"]) == 0:
        summary["halt_reason"] = ("所有诊断条件均不成立，"
                                  "现有特征下无足够依据训练新候选，"
                                  "建议保留 Round68 final 并进入新增气象数据阶段。")

    summary_path = OUT / "round71_diagnosis_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] 诊断摘要: {summary_path}")
    print(f"\n推荐候选: {summary['recommended_candidates']}")
    if summary["halt_reason"]:
        print(f"终止原因: {summary['halt_reason']}")

    print("\n[OK] diagnose_round71 完成!")


if __name__ == "__main__":
    main()
