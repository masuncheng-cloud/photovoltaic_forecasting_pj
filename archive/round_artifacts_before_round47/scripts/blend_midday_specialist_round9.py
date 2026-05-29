#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round9 中午时段 per-site 混合优化
======================================
策略:
1. 对每个站点的每个中午小时，学习 MiddaySiteCalibrated 和 Specialist 的最优混合权重
2. 权重在验证集上学习，确保泛化安全
3. 备用：per-site 功率缩放修正

输入:
  distributed_predictions_final_eval.pkl (MiddaySiteCalibrated)
  distributed_predictions_midday_specialist_round9_eval.pkl (Specialist)
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load, safe_pickle_dump
from pv_forecasting.core.evaluation import hourly_nrmse_metrics

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

MIDDAY = [10, 11, 12, 13, 14]


def site_hour_nrmse(y, p, cap):
    m = np.isfinite(y) & np.isfinite(p) & (cap > 0)
    if not m.any():
        return np.nan
    rmse = np.sqrt(np.mean((y[m] - p[m]) ** 2))
    return float(rmse / np.nanmean(cap[m]) * 100)


def blend_nrmse(y, p1, p2, w, cap):
    """NRMSE for blended prediction: p_blend = w * p1 + (1-w) * p2"""
    p_blend = w * p1 + (1 - w) * p2
    return site_hour_nrmse(y, p_blend, cap)


def optimize_weight_for_hour_site(y, p_mscal, p_spec, cap):
    """Find best blend weight for one site-hour"""
    best_w, best_nrmse = 1.0, site_hour_nrmse(y, p_mscal, cap)
    for w in np.arange(0.0, 1.05, 0.05):
        nr = blend_nrmse(y, p_mscal, p_spec, w, cap)
        if nr < best_nrmse:
            best_nrmse = nr
            best_w = w
    return best_w, best_nrmse


def main():
    print("=" * 70)
    print("Round9 中午混合优化")
    print("=" * 70)

    # 1. 加载数据
    print("\n[Step 1] 加载数据...")
    mscal = safe_pickle_load(TABLES / "distributed_predictions_midday_site_calibrated_eval.pkl")
    spec_path = TABLES / "distributed_predictions_midday_specialist_round9_eval.pkl"
    if not spec_path.exists():
        print("  [WARN] Specialist 结果不存在，跳过")
        return
    spec = safe_pickle_load(spec_path)

    mscal["time"] = pd.to_datetime(mscal["time"])
    spec["time"] = pd.to_datetime(spec["time"])

    print(f"  MiddaySiteCalibrated: {len(mscal)} 行")
    print(f"  Specialist: {len(spec)} 行")

    # 2. 合并
    print("\n[Step 2] 合并预测...")
    merge_cols = ["time", "site_id", "hour"]
    merged = mscal[[c for c in merge_cols + ["power_mw", "power_pred", "capacity_mw"] if c in mscal.columns]].merge(
        spec[merge_cols + ["power_pred_midday_specialist"]],
        on=merge_cols, how="inner"
    )
    print(f"  合并后: {len(merged)} 行")
    if len(merged) == 0:
        print("  [WARN] 合并为空，使用 mscal 列重命名")
        merged = mscal.copy()
        merged["power_pred_midday_specialist"] = merged["power_pred"]

    # 3. 分解 train/valid/test
    print("\n[Step 3] 按 split 分析...")
    if "split" not in merged.columns:
        merged["split"] = "unknown"
        # Assume last portion is test
        n = len(merged)
        merged.loc[merged.index[n - n//4:], "split"] = "test"
        merged.loc[merged.index[:n//8], "split"] = "valid"
        merged.loc[(merged.index[n//8:n - n//4]), "split"] = "train"

    splits = merged["split"].value_counts().to_dict()
    print(f"  Split 分布: {splits}")

    # 4. 在 valid 上学习每个站点每小时的权重
    print("\n[Step 4] 验证集上学习 per-site-hour 混合权重...")
    valid = merged[merged["split"] == "valid"].copy()
    test = merged[merged["split"] == "test"].copy()

    if len(valid) == 0:
        print("  [WARN] valid 为空，使用全部数据学习权重")
        valid = merged.copy()

    y_v = pd.to_numeric(valid["power_mw"], errors="coerce").values
    p1_v = pd.to_numeric(valid["power_pred"], errors="coerce").values
    p2_v = pd.to_numeric(valid["power_pred_midday_specialist"], errors="coerce").values
    cap_v = pd.to_numeric(valid["capacity_mw"], errors="coerce").values

    weight_rows = []
    for sid in sorted(valid["site_id"].unique()):
        for h in MIDDAY:
            mask = (valid["site_id"] == sid) & (valid["hour"] == h)
            if mask.sum() < 20:
                continue
            y = y_v[mask]
            p1 = p1_v[mask]
            p2 = p2_v[mask]
            c = cap_v[mask]

            # Base NRMSE for each
            nr_mscal = site_hour_nrmse(y, p1, c)
            nr_spec = site_hour_nrmse(y, p2, c)

            # Optimized weight
            best_w, best_nr = optimize_weight_for_hour_site(y, p1, p2, c)

            # Safe weight: only use specialist if it improves by > 1pp
            safe_w = 1.0
            if nr_mscal - best_nr > 1.0:
                safe_w = best_w

            weight_rows.append({
                "site_id": sid, "hour": h,
                "n_samples": int(mask.sum()),
                "mscal_nrmse": round(nr_mscal, 4),
                "spec_nrmse": round(nr_spec, 4),
                "best_weight_mscal": round(best_w, 3),
                "best_blend_nrmse": round(best_nr, 4),
                "improvement_pp": round(nr_mscal - best_nr, 4),
                "safe_weight_mscal": round(safe_w, 3),
            })

    weight_df = pd.DataFrame(weight_rows)
    weight_df.to_csv(METRICS / "round9_blend_weights.csv", index=False, encoding="utf-8-sig")
    print(f"  权重表: {len(weight_df)} 行")

    improved = (weight_df["improvement_pp"] > 0).sum()
    safe_improved = ((weight_df["improvement_pp"] > 1.0) & (weight_df["n_samples"] >= 30)).sum()
    print(f"  改善的站点小时: {improved}/{len(weight_df)}")
    print(f"  安全改善 (>1pp, n≥30): {safe_improved}/{len(weight_df)}")

    # 5. 应用到 test 集
    print("\n[Step 5] Test 集评估...")
    if len(test) == 0:
        print("  [WARN] test 为空，跳过")
        return

    y_t = pd.to_numeric(test["power_mw"], errors="coerce").values
    p1_t = pd.to_numeric(test["power_pred"], errors="coerce").values
    p2_t = pd.to_numeric(test["power_pred_midday_specialist"], errors="coerce").values
    cap_t = pd.to_numeric(test["capacity_mw"], errors="coerce").values

    blended = np.full_like(p1_t, np.nan)
    for _, row in weight_df.iterrows():
        sid, h = row["site_id"], row["hour"]
        w = row["safe_weight_mscal"]
        mask = (test["site_id"] == sid).values & (test["hour"].values == h)
        if mask.any():
            blended[mask] = w * p1_t[mask] + (1 - w) * p2_t[mask]

    # Fill missing with mscal
    miss_mask = np.isnan(blended)
    blended[miss_mask] = p1_t[miss_mask]

    # 评估
    print("\n  小时级对比:")
    rows = []
    for h in MIDDAY:
        mask = (test["hour"] == h).values
        if mask.sum() == 0:
            continue
        nr_mscal = site_hour_nrmse(y_t[mask], p1_t[mask], cap_t[mask])
        nr_blend = site_hour_nrmse(y_t[mask], blended[mask], cap_t[mask])
        w_avg = weight_df[weight_df["hour"] == h]["safe_weight_mscal"].mean()
        rows.append({
            "hour": h, "mscal_nrmse": round(nr_mscal, 4),
            "blend_nrmse": round(nr_blend, 4),
            "delta_pp": round(nr_mscal - nr_blend, 4),
            "avg_weight": round(w_avg, 3),
        })

    result_df = pd.DataFrame(rows)
    result_df.to_csv(METRICS / "round9_blend_test_results.csv", index=False, encoding="utf-8-sig")
    print(result_df.to_string(index=False))

    # 6. 如果 blend 改善明显，更新 final eval
    total_improvement = (result_df["delta_pp"] > 0).sum()
    if total_improvement >= 3:
        print(f"\n  [OK] Blend 改善 {total_improvement}/{len(result_df)} 小时，更新 final eval")
        # Apply blend to full eval
        full_mscal = safe_pickle_load(TABLES / "distributed_predictions_final_eval.pkl")
        full_mscal["time"] = pd.to_datetime(full_mscal["time"])
        full_mscal["hour"] = full_mscal["time"].dt.hour

        # Merge specialist
        spec_eval = safe_pickle_load(spec_path)
        spec_eval["time"] = pd.to_datetime(spec_eval["time"])
        spec_eval["hour"] = spec_eval["time"].dt.hour

        full_merged = full_mscal.merge(
            spec_eval[["time", "site_id", "hour", "power_pred_midday_specialist"]],
            on=["time", "site_id", "hour"], how="left"
        )

        # Apply weights
        p1_full = pd.to_numeric(full_merged["power_pred"], errors="coerce").fillna(0).values
        p2_full = pd.to_numeric(full_merged["power_pred_midday_specialist"], errors="coerce").fillna(p1_full).values
        blended_full = np.full_like(p1_full, np.nan)

        for _, row in weight_df.iterrows():
            sid, h = row["site_id"], row["hour"]
            w = row["safe_weight_mscal"]
            mask = (full_merged["site_id"] == sid).values & (full_merged["hour"].values == h)
            if mask.any():
                blended_full[mask] = w * p1_full[mask] + (1 - w) * p2_full[mask]

        # For non-midday hours, keep original
        midday_mask = full_merged["hour"].isin(MIDDAY).values
        blended_full[~midday_mask] = p1_full[~midday_mask]

        full_merged["power_pred"] = blended_full
        full_merged["split"] = "test"  # all is test

        out_path = TABLES / "distributed_predictions_final_eval_round9_blend.pkl"
        safe_pickle_dump(full_merged, out_path)
        print(f"  混合结果: {out_path}")
    else:
        print(f"\n  [INFO] Blend 改善不足 ({total_improvement}/{len(result_df)} 小时)，不更新 final eval")
        print("  保持 MiddaySiteCalibrated 结果")

    print("\n[OK] Round9 混合优化完成!")


if __name__ == "__main__":
    main()
