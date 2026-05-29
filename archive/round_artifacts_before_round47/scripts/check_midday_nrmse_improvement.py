#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10-14 点站点 NRMSE 改善验收：当前 final vs fixed
=====================================================

验收标准（相对于 fixed 版本）：
  10-14 点中至少 3 个小时站点平均 NRMSE 下降。
  10-14 点平均站点 NRMSE 至少下降 5% 相对比例，或下降 0.8 个百分点。
  不允许任一小时比 fixed 恶化超过 0.3 个百分点。

不再以周二版为基准，只比较"当前版本 vs 修复前版本"是否改善。
"""
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

MIDDAY = [10, 11, 12, 13, 14]
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}


def load_eval(path_eval: Path, path_full: Path | None = None) -> pd.DataFrame:
    if path_eval.exists():
        return safe_pickle_load(path_eval)
    if path_full is None or not path_full.exists():
        raise FileNotFoundError(f"找不到 eval 或 full: {path_eval}, {path_full}")
    df = safe_pickle_load(path_full)
    return build_eval_frame(
        df,
        split="test",
        hours=tuple(range(6, 20)),
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=53,
    )


def main():
    print("=" * 70)
    print("10-14 点站点 NRMSE 改善验收：当前 final vs fixed")
    print("=" * 70)

    fixed_eval = load_eval(
        TABLES / "distributed_predictions_fixed_eval.pkl",
        TABLES / "distributed_predictions_fixed_full.pkl",
    )
    final_eval = load_eval(
        TABLES / "distributed_predictions_final_eval.pkl",
        TABLES / "distributed_predictions_final_full.pkl",
    )

    fixed_h = hourly_nrmse_metrics(fixed_eval)
    final_h = hourly_nrmse_metrics(final_eval)

    rows = []
    for h in MIDDAY:
        f0 = fixed_h[fixed_h["hour"] == h]
        f1 = final_h[final_h["hour"] == h]
        if f0.empty or f1.empty:
            continue
        before = float(f0.iloc[0]["site_nrmse_mean_pct"])
        after = float(f1.iloc[0]["site_nrmse_mean_pct"])
        city_before = float(f0.iloc[0]["city_nrmse_pct"])
        city_after = float(f1.iloc[0]["city_nrmse_pct"])
        rows.append({
            "hour": h,
            "fixed_site_nrmse_pct": round(before, 4),
            "final_site_nrmse_pct": round(after, 4),
            "improvement_pct_point": round(before - after, 4),
            "relative_improvement_pct": round((before - after) / before * 100.0, 2) if before > 0 else np.nan,
            "fixed_city_nrmse_pct": round(city_before, 4),
            "final_city_nrmse_pct": round(city_after, 4),
        })

    out = pd.DataFrame(rows)
    out.to_csv(METRICS / "midday_nrmse_current_vs_fixed.csv", index=False, encoding="utf-8-sig")
    print("\n逐小时对比:")
    print(out.to_string(index=False))

    improved_hours = int((out["improvement_pct_point"] > 0).sum())
    avg_before = float(out["fixed_site_nrmse_pct"].mean())
    avg_after = float(out["final_site_nrmse_pct"].mean())
    avg_drop = avg_before - avg_after
    rel_drop = avg_drop / avg_before * 100.0 if avg_before > 0 else np.nan
    worst_degradation = float((-out["improvement_pct_point"]).max())

    print()
    print(f"改善小时数: {improved_hours}/5")
    print(f"10-14 平均站点 NRMSE: {avg_before:.4f}% -> {avg_after:.4f}%")
    print(f"平均下降: {avg_drop:.4f} 个百分点，相对下降 {rel_drop:.2f}%")
    print(f"最大单小时恶化: {worst_degradation:.4f} 个百分点")

    ok = True
    reasons = []
    if improved_hours < 3:
        ok = False
        reasons.append(f"改善小时数 {improved_hours}/5 < 3")
    if not (rel_drop >= 5.0 or avg_drop >= 0.8):
        ok = False
        reasons.append(f"10-14 平均站点 NRMSE 改善不足（{rel_drop:.2f}%，{avg_drop:.4f}pp）")
    if worst_degradation > 0.3:
        ok = False
        reasons.append(f"存在单小时明显恶化（{worst_degradation:.4f}pp > 0.3pp）")

    if not ok:
        print("[FAIL] " + "；".join(reasons))
        sys.exit(1)

    print("[OK] 10-14 点站点 NRMSE 改善验收通过")


if __name__ == "__main__":
    main()
