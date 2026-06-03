#!/usr/bin/env python3
"""
audit_prediction_column_consistency.py
====================================
诊断当前预测列在 train/valid/test 上的缺失和口径错位。

输出：
    output/pv_pipeline/round72/round72_prediction_column_audit.csv
    output/pv_pipeline/round72/round72_prediction_column_audit_summary.json
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round72"


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def compute_metrics_for_slice(df, pred_col, actual_col="power_mw"):
    """计算一个切片的各项指标。"""
    if pred_col not in df.columns:
        return {}
    valid = df[[actual_col, pred_col]].dropna()
    if len(valid) == 0:
        return {}
    a, p = valid[actual_col].values, valid[pred_col].values
    cap_sum = float(df["capacity_mw"].sum())
    nrmse = rmse(a, p) / cap_sum * 100 if cap_sum > 0 else np.nan
    a_sum = float(a.sum())
    p_sum = float(p.sum())
    bias = (p_sum - a_sum) / a_sum * 100 if abs(a_sum) > 1e-9 else np.nan
    mae = float(np.nanmean(np.abs(p - a)))
    return {
        "n_rows": len(df),
        "non_null": len(valid),
        "null": len(df) - len(valid),
        "null_ratio": round((len(df) - len(valid)) / len(df) * 100, 2),
        "mean_pred": round(float(p.mean()), 4),
        "mean_actual": round(float(a.mean()), 4),
        "mae": round(mae, 4),
        "rmse": round(rmse(a, p), 4),
        "nrmse_pct": round(nrmse, 4),
        "bias_pct": round(bias, 4),
    }


def main():
    parser = argparse.ArgumentParser(description="Round72 预测列一致性审计")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    if args.config is None:
        args.config = str(PROJECT_ROOT / "configs" / "round72_consistent_base.yaml")
    cfg = yaml.safe_load(open(args.config))

    OUT.mkdir(parents=True, exist_ok=True)

    input_path = PROJECT_ROOT / cfg["input_pkl"]
    print(f"[INFO] 读取: {input_path}")
    df = pd.read_pickle(input_path)
    df["time"] = pd.to_datetime(df["time"])
    print(f"  总行数: {len(df):,}")

    # 只看 6-19 点
    df = df[df["time"].dt.hour.between(6, 19)].copy()
    print(f"  过滤后: {len(df):,}")

    # 目标预测列
    target_cols = [
        "power_pred",
        "power_pred_final",
        "power_pred_round61_city_safe",
        "power_pred_round60_safe",
        "pred_baseline",
        "power_pred_cal",
        "power_pred_raw",
    ]

    # 审计每一列
    audit_rows = []
    for col in target_cols:
        for split_name in ["train", "valid", "test"]:
            sub = df[df["split"] == split_name]
            if len(sub) == 0:
                continue
            m = compute_metrics_for_slice(sub, col)
            if m:
                row = {"split": split_name, "column": col}
                row.update(m)
                audit_rows.append(row)
            else:
                audit_rows.append({
                    "split": split_name, "column": col,
                    "n_rows": len(sub), "non_null": 0, "null": len(sub),
                    "null_ratio": 100.0,
                    "mean_pred": None, "mean_actual": None,
                    "mae": None, "rmse": None, "nrmse_pct": None, "bias_pct": None,
                })

    audit_df = pd.DataFrame(audit_rows)
    audit_df.to_csv(OUT / "round72_prediction_column_audit.csv",
                    index=False, encoding="utf-8-sig")
    print(f"\n[OK] {OUT / 'round72_prediction_column_audit.csv'}")

    # Pivot 表：列×split 的 non_null_ratio
    pivot = audit_df.pivot_table(
        index="column", columns="split",
        values="non_null", aggfunc="first"
    )
    print("\n预测列非空行数（按 split）:")
    print(pivot.to_string())

    # 关键问题回答
    final_in_train = audit_df[
        (audit_df["column"] == "power_pred_final") & (audit_df["split"] == "train")
    ]
    final_null_ratio = float(final_in_train["null_ratio"].iloc[0]) if len(final_in_train) > 0 else 100.0

    # 一致可用列（train/valid/test 均有非空数据）
    pivot_full = audit_df.pivot_table(index="column", columns="split", values="non_null")
    consistent_cols = []
    for col in pivot_full.index:
        row = pivot_full.loc[col]
        if all(row.get(s, 0) > 0 for s in ["train", "valid", "test"]):
            consistent_cols.append(col)

    summary = {
        "total_rows": int(len(df)),
        "final_null_in_train_pct": final_null_ratio,
        "key_findings": {
            "power_pred_final_missing_in_train": final_null_ratio == 100.0,
            "train_valid_test_consistent_columns": sorted(consistent_cols),
            "recommendation": (
                "power_pred_final 在 train 为空，需用 OOF 构造一致基线。"
                if final_null_ratio == 100.0 else
                "power_pred_final 在 train 有数据，可直接使用。"
            ),
        },
    }

    with open(OUT / "round72_prediction_column_audit_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] {OUT / 'round72_prediction_column_audit_summary.json'}")
    print(f"\n关键发现:")
    print(f"  power_pred_final 在 train 为空: {summary['key_findings']['power_pred_final_missing_in_train']}")
    print(f"  全 split 一致可用列: {summary['key_findings']['train_valid_test_consistent_columns']}")
    print(f"  建议: {summary['key_findings']['recommendation']}")
    print(f"  train/valid/test 全一致列: {consistent_cols}")

    print("\n[OK] audit 完成!")


if __name__ == "__main__":
    main()
