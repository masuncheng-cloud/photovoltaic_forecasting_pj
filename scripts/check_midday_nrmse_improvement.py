#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10-14 点站点级 NRMSE 专项验收
================================

验收标准：
  10、11、12、13、14 中至少 3 个小时：
    current_site_nrmse_pct <= week2_site_nrmse_pct + 0.50

说明：
  目标不是一次全部超过周二，而是先要求至少 3/5 个小时接近周二水平。
"""
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics
from pv_forecasting.core.week2_reference import WEEK2_HOURLY_NRMSE

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

MIDDAY = [10, 11, 12, 13, 14]


def main():
    print("=" * 70)
    print("10-14 点站点级 NRMSE 专项验收")
    print("=" * 70)

    final_path = TABLES / "distributed_predictions_midday_site_calibrated_eval.pkl"
    if not final_path.exists():
        final_path = TABLES / "distributed_predictions_final_eval.pkl"
        print(f"[WARN] Midday 版本不存在，使用 V1 最终版: {final_path}")

    final_df = safe_pickle_load(final_path)
    final_eval = build_eval_frame(
        final_df,
        target_site_count=53,
        hours=tuple(range(6, 20)),
        active_only=True,
    )

    h_metrics = hourly_nrmse_metrics(final_eval)

    rows = []
    ok_count = 0
    for _, r in h_metrics[h_metrics["hour"].isin(MIDDAY)].iterrows():
        hour = int(r["hour"])
        current = float(r["site_nrmse_mean_pct"])
        ref = float(WEEK2_HOURLY_NRMSE[hour]["site_nrmse_mean_pct"])
        diff = current - ref
        ok = current <= ref + 0.50
        if ok:
            ok_count += 1
        rows.append({
            "hour": hour,
            "current_site_nrmse_pct": round(current, 2),
            "week2_site_nrmse_pct": round(ref, 2),
            "diff_current_minus_week2": round(diff, 3),
            "pass_within_0_5pct": ok,
            "current_city_nrmse_pct": round(float(r["city_nrmse_pct"]), 3),
            "week2_city_nrmse_pct": round(WEEK2_HOURLY_NRMSE[hour]["city_nrmse_pct"], 3),
        })

    out = pd.DataFrame(rows)
    out.to_csv(METRICS / "midday_nrmse_acceptance.csv", index=False, encoding="utf-8-sig")
    print("\n验收表:")
    print(out.to_string(index=False))

    print(f"\n验收结果: {ok_count}/5 个小时接近周二水平（within 0.5 pct）")

    if ok_count < 3:
        print(f"\n[FAIL] 10-14 点站点 NRMSE 改善不足：只有 {ok_count}/5 个小时接近周二水平")
        print("建议：检查校准参数是否生效，或考虑回到训练层优化。")
        sys.exit(1)
    else:
        print(f"\n[OK] 10-14 点 NRMSE 验收通过：{ok_count}/5 个小时接近周二水平")


if __name__ == "__main__":
    main()
