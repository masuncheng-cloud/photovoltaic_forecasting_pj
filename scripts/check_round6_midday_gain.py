#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round6 脚本七：Round6 增量验收
==============================-
对比 Round6 final vs MiddaySiteCalibrated（安全基准）。
若最大单小时恶化 > 0.2pp 则失败退出。
若平均改善 <= 0 则仅发出警告。
"""
from __future__ import annotations

from pathlib import Path
import sys
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


def eval_from_full(path):
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
    safe_path = TABLES / "distributed_predictions_midday_site_calibrated_full.pkl"
    final_path = TABLES / "distributed_predictions_final_full.pkl"
    if not safe_path.exists():
        raise FileNotFoundError(safe_path)
    if not final_path.exists():
        raise FileNotFoundError(final_path)

    safe_eval = eval_from_full(safe_path)
    final_eval = eval_from_full(final_path)

    safe_h = hourly_nrmse_metrics(safe_eval)
    final_h = hourly_nrmse_metrics(final_eval)

    rows = []
    for h in MIDDAY:
        s = safe_h[safe_h["hour"] == h]
        f = final_h[final_h["hour"] == h]
        if s.empty or f.empty:
            continue
        s = s.iloc[0]
        f = f.iloc[0]
        before = float(s["site_nrmse_mean_pct"])
        after = float(f["site_nrmse_mean_pct"])
        rows.append({
            "hour": h,
            "safe_site_nrmse_pct": round(before, 4),
            "final_site_nrmse_pct": round(after, 4),
            "improvement_pp": round(before - after, 4),
            "safe_city_nrmse_pct": round(float(s["city_nrmse_pct"]), 4),
            "final_city_nrmse_pct": round(float(f["city_nrmse_pct"]), 4),
        })

    out = pd.DataFrame(rows)
    out.to_csv(METRICS / "round6_midday_gain_vs_safe.csv", index=False, encoding="utf-8-sig")
    print(out.to_string(index=False))

    improved = int((out["improvement_pp"] > 0).sum())
    avg_drop = float(out["improvement_pp"].mean())
    worst_degrade = float((-out["improvement_pp"]).max())
    city_worse = float((out["final_city_nrmse_pct"] - out["safe_city_nrmse_pct"]).mean())

    print()
    print(f"改善小时数: {improved}/5")
    print(f"平均改善: {avg_drop:.4f} pp")
    print(f"最大单小时恶化: {worst_degrade:.4f} pp")
    print(f"城市 NRMSE 平均变化: {city_worse:.4f} pp")

    if worst_degrade > 0.2:
        raise SystemExit("[FAIL] Round6 造成单小时明显恶化")

    if avg_drop <= 0:
        print("[WARN] Round6 未带来增量提升，但安全回退有效。")
        return

    if improved >= 2 and avg_drop >= 0.1:
        print("[OK] Round6 有小幅增量改善")
    else:
        print("[WARN] Round6 改善很小，建议继续数据侧核查")


if __name__ == "__main__":
    main()
