#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验收：本轮选择性修正是否比当前 MiddaySiteCalibrated 继续改善。

对比：
  - 基准：MiddaySiteCalibrated（分布式_predictions_midday_site_calibrated_eval.pkl）
  - 当前：Final（分布式_predictions_final_eval.pkl）

验收标准：
  - 10-14 点至少 3/5 小时站点 NRMSE 下降
  - 平均下降 >= 0.3pp 或相对下降 >= 2%
  - 无单小时恶化超过 0.2pp
  - 城市 NRMSE 10-14 平均不得恶化超过 0.5pp

如果验收失败，不中止流水线，仅打印警告。
"""
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

MIDDAY = [10, 11, 12, 13, 14]
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}


def eval_from_full(path: Path) -> pd.DataFrame:
    df = safe_pickle_load(path)
    return build_eval_frame(
        df,
        split="test",
        hours=tuple(range(6, 20)),
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=53,
    )


def main():
    base_path = TABLES / "distributed_predictions_midday_site_calibrated_full.pkl"
    final_path = TABLES / "distributed_predictions_final_full.pkl"
    if not base_path.exists():
        raise FileNotFoundError(base_path)
    if not final_path.exists():
        raise FileNotFoundError(final_path)

    base_eval = eval_from_full(base_path)
    final_eval = eval_from_full(final_path)

    base_h = hourly_nrmse_metrics(base_eval)
    final_h = hourly_nrmse_metrics(final_eval)

    rows = []
    for h in MIDDAY:
        b = base_h[base_h["hour"] == h].iloc[0]
        f = final_h[final_h["hour"] == h].iloc[0]
        before = float(b["site_nrmse_mean_pct"])
        after = float(f["site_nrmse_mean_pct"])
        rows.append({
            "hour": h,
            "midday_site_calibrated_site_nrmse_pct": round(before, 4),
            "final_site_nrmse_pct": round(after, 4),
            "improvement_pp": round(before - after, 4),
            "relative_improvement_pct": round((before - after) / before * 100.0, 3) if before > 0 else np.nan,
            "midday_site_calibrated_city_nrmse_pct": round(float(b["city_nrmse_pct"]), 4),
            "final_city_nrmse_pct": round(float(f["city_nrmse_pct"]), 4),
        })

    out = pd.DataFrame(rows)
    out.to_csv(METRICS / "midday_next_step_gain_vs_site_calibrated.csv", index=False, encoding="utf-8-sig")
    print(out.to_string(index=False))

    improved_hours = int((out["improvement_pp"] > 0).sum())
    avg_drop = float(out["improvement_pp"].mean())
    rel_drop = (
        float(out["midday_site_calibrated_site_nrmse_pct"].mean() - out["final_site_nrmse_pct"].mean())
        / float(out["midday_site_calibrated_site_nrmse_pct"].mean())
        * 100.0
    )
    worst_degrade = float((-out["improvement_pp"]).clip(lower=0).max())

    avg_city_drop = float((out["midday_site_calibrated_city_nrmse_pct"] - out["final_city_nrmse_pct"]).mean())

    print()
    print(f"改善小时数: {improved_hours}/5")
    print(f"平均站点 NRMSE 下降: {avg_drop:.4f} pp")
    print(f"相对下降: {rel_drop:.3f}%")
    print(f"最大单小时恶化: {worst_degrade:.4f} pp")
    print(f"城市 NRMSE 平均变化: {avg_city_drop:+.4f} pp（负=改善）")

    ok = True
    reasons = []
    if improved_hours < 3:
        ok = False
        reasons.append(f"改善小时数不足 3/5（当前 {improved_hours}/5）")
    if not (avg_drop >= 0.3 or rel_drop >= 2.0):
        ok = False
        reasons.append(f"平均改善不足（需 >=0.3pp 或 >=2%，当前 {avg_drop:.3f}pp / {rel_drop:.3f}%）")
    if worst_degrade > 0.2:
        ok = False
        reasons.append(f"存在单小时恶化超过 0.2pp（最大 {worst_degrade:.4f}pp）")
    if avg_city_drop < -0.5:
        ok = False
        reasons.append(f"城市 NRMSE 恶化超过 0.5pp（当前 {avg_city_drop:.4f}pp）")

    if not ok:
        print()
        print("[WARN] 本轮选择性修正未达到继续改善目标：" + "；".join(reasons))
        print("       最终选择器将自动保留 MiddaySiteCalibrated，项目结果安全。")
        sys.exit(0)

    print()
    print("[OK] 本轮相对 MiddaySiteCalibrated 继续改善")


if __name__ == "__main__":
    main()
