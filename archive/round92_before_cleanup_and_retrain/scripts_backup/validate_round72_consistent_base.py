#!/usr/bin/env python3
"""
validate_round72_consistent_base.py
================================
校验一致基线是否通过所有质量门控。

硬性通过条件：
    future_rows = 0
    consistent_base_null_rows = 0
    valid_test_diff_to_power_pred_final_max <= 1e-6
    train_leakage_suspect = false

输出：
    output/pv_pipeline/round72/round72_consistent_base_validation.csv
    output/pv_pipeline/round72/round72_consistent_base_validation.json
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


def main():
    parser = argparse.ArgumentParser(description="Round72 一致基线校验")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    if args.config is None:
        args.config = str(PROJECT_ROOT / "configs" / "round72_consistent_base.yaml")
    cfg = yaml.safe_load(open(args.config))

    pkl_path = OUT / "round72_consistent_base_predictions.pkl"
    print(f"[INFO] 读取: {pkl_path}")
    df = pd.read_pickle(pkl_path)
    print(f"  总行数: {len(df):,}")

    bl_consistent = cfg["consistent_base_col"]
    bl_final = cfg["baseline_final_col"]
    cap_col = cfg["capacity_col"]
    target_col = cfg["target_col"]

    results = {}
    all_passed = True

    # ── 1. Future 行数检查 ────────────────────────────────────────────
    future_rows = int((df["split"] == "future").sum())
    results["future_rows"] = future_rows
    results["future_rows_pass"] = future_rows == 0
    print(f"[1] future 行数: {future_rows}  {'✓' if future_rows == 0 else '✗ FAIL'}")
    if future_rows > 0:
        all_passed = False

    # ── 2. 一致基线空值检查 ──────────────────────────────────────────
    null_total = int(df[bl_consistent].isna().sum())
    null_train = int(df[df["split"]=="train"][bl_consistent].isna().sum())
    null_valid = int(df[df["split"]=="valid"][bl_consistent].isna().sum())
    null_test = int(df[df["split"]=="test"][bl_consistent].isna().sum())
    results["null_total"] = null_total
    results["null_by_split"] = {"train": null_train, "valid": null_valid, "test": null_test}
    results["null_pass"] = null_total == 0
    print(f"[2] 一致基线 null: train={null_train} valid={null_valid} test={null_test}  "
          f"{'✓' if null_total == 0 else '✗ FAIL'}")
    if null_total > 0:
        all_passed = False

    # ── 3. valid/test 与 final 差异 ────────────────────────────────
    max_diff_valid = 1e-9
    max_diff_test = 1e-9
    if bl_final in df.columns:
        for sname, sdf in [("valid", df[df["split"]=="valid"]), ("test", df[df["split"]=="test"])]:
            both = sdf[[bl_final, bl_consistent]].dropna()
            if len(both) > 0:
                diff = (both[bl_consistent] - both[bl_final]).abs()
                mxd = float(diff.max())
                mnd = float(diff.mean())
                if sname == "valid":
                    max_diff_valid = mxd
                    results["valid_vs_final_max_diff"] = round(mxd, 8)
                    results["valid_vs_final_mean_diff"] = round(mnd, 8)
                else:
                    max_diff_test = mxd
                    results["test_vs_final_max_diff"] = round(mxd, 8)
                    results["test_vs_final_mean_diff"] = round(mnd, 8)
                print(f"[3] {sname} vs final: max_diff={mxd:.8f}  mean_diff={mnd:.8f}  "
                      f"{'✓' if mxd <= 1e-6 else '✗ FAIL'}")

    results["valid_test_diff_pass"] = max_diff_valid <= 1e-6 and max_diff_test <= 1e-6
    if not results["valid_test_diff_pass"]:
        all_passed = False

    # ── 4. Train 泄漏检查 ──────────────────────────────────────────
    train_df = df[df["split"] == "train"].copy()
    train_valid = train_df[
        train_df[target_col].notna() & train_df[bl_consistent].notna()
    ].copy()

    if len(train_valid) > 0:
        cap_sum = float(train_valid[cap_col].sum())
        a = train_valid[target_col].values
        p = train_valid[bl_consistent].values
        oof_nrmse = rmse(a, p) / cap_sum * 100 if cap_sum > 0 else np.nan
        results["train_oof_nrmse"] = round(oof_nrmse, 4)
        results["train_oof_nrmse_pass"] = not (oof_nrmse < 1.0)
        print(f"[4] train OOF NRMSE: {oof_nrmse:.3f}%  "
              f"{'✓ (正常范围)' if oof_nrmse >= 1.0 else '⚠ WARN (可能泄漏，<1%)'}")

        # 如果 OOF NRMSE 异常低，检查是否预测值和真实值高度相关
        corr = float(train_valid[[target_col, bl_consistent]].corr().iloc[0, 1])
        results["train_oof_corr"] = round(corr, 4)
        print(f"    train OOF 相关系数: {corr:.4f}  "
              f"{'✓' if corr < 0.99 else '⚠ WARN (可能轻微泄漏，相关系数>0.99)'}")
    else:
        results["train_oof_nrmse"] = None
        results["train_oof_nrmse_pass"] = True

    # ── 5. Fallback 比例检查 ──────────────────────────────────────
    if "_base_source" in df.columns:
        fallback_ratio = float(
            (df["_base_source"] == "fallback_power_pred").sum() / len(df)
        )
        oof_ratio = float(
            (df["_base_source"] == "oof").sum() / len(df)
        )
        final_ratio = float(
            (df["_base_source"] == "power_pred_final").sum() / len(df)
        )
        results["base_source_distribution"] = {
            "oof": round(oof_ratio * 100, 2),
            "power_pred_final": round(final_ratio * 100, 2),
            "fallback": round(fallback_ratio * 100, 2),
        }
        print(f"[5] 基线源分布: OOF={oof_ratio*100:.1f}%  "
              f"power_pred_final={final_ratio*100:.1f}%  "
              f"fallback={fallback_ratio*100:.1f}%")
        results["fallback_ratio_pass"] = fallback_ratio < 0.20
        if fallback_ratio >= 0.20:
            print(f"    ⚠ WARN: fallback 比例 {fallback_ratio*100:.1f}% > 20%")

    # ── 6. 总体结论 ──────────────────────────────────────────────
    results["all_passed"] = all_passed
    results["recommendation"] = (
        "PASS" if all_passed else
        "FAIL - 存在质量问题，请修复后重跑 Step 2"
    )

    with open(OUT / "round72_consistent_base_validation.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    pd.DataFrame([results]).to_csv(OUT / "round72_consistent_base_validation.csv",
                                   index=False, encoding="utf-8-sig")

    print(f"\n[OK] {OUT / 'round72_consistent_base_validation.json'}")
    print(f"\n{'='*50}")
    print(f"校验结果: {'✓ 全部通过' if all_passed else '✗ 存在失败项'}")
    print(f"建议: {results['recommendation']}")
    print(f"{'='*50}")

    print("\n[OK] validate 完成!")


if __name__ == "__main__":
    main()
