#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round7 脚本三：整体流程验收
=============================
检查核心源码、表、metrics/docs 是否齐全，
输出 round7_end_to_end_deliverables_check.csv。
"""
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"


def check_file(path: Path, required: bool = True) -> dict:
    return {
        "item": str(path.relative_to(PROJECT_ROOT)),
        "exists": path.exists(),
        "required": required,
        "size_mb": round(path.stat().st_size / 1024 / 1024, 3) if path.exists() else 0,
        "status": "OK" if path.exists() or not required else "MISSING",
    }


def main():
    checks = []

    required_files = [
        PROJECT_ROOT / "scripts" / "train_fixed.py",
        PROJECT_ROOT / "scripts" / "select_final_prediction_by_guard.py",
        PROJECT_ROOT / "scripts" / "apply_midday_site_nrmse_calibration.py",
        PROJECT_ROOT / "scripts" / "diagnose_site_capacity_mapping_round6.py",
        PROJECT_ROOT / "scripts" / "diagnose_midday_bias_stability_round6.py",
        PROJECT_ROOT / "scripts" / "regenerate_final_metrics_round7.py",
        PROJECT_ROOT / "scripts" / "assert_final_metrics_consistency_round7.py",
        PROJECT_ROOT / "src" / "pv_forecasting" / "core" / "evaluation.py",
        TABLES / "distributed_predictions_final_full.pkl",
        TABLES / "distributed_predictions_final_eval.pkl",
        METRICS / "final_version_selection_by_hour.csv",
        METRICS / "分布式光伏预测_逐小时平均NRMSE.csv",
        METRICS / "round6_watch_site_diagnosis.csv",
        METRICS / "round7_final_overall_metrics.csv",
        DOCS / "当前最终结果摘要.md",
    ]

    for f in required_files:
        checks.append(check_file(f, required=True))

    final_eval_path = TABLES / "distributed_predictions_final_eval.pkl"
    if final_eval_path.exists():
        try:
            df = safe_pickle_load(final_eval_path)
            if "hour" not in df.columns:
                df["time"] = pd.to_datetime(df["time"])
                df["hour"] = df["time"].dt.hour
            checks.append({
                "item": "final_eval_rows",
                "exists": True,
                "required": True,
                "size_mb": 0,
                "status": "OK" if len(df) > 0 else "EMPTY",
                "detail": len(df),
            })
            checks.append({
                "item": "final_eval_site_count",
                "exists": True,
                "required": True,
                "size_mb": 0,
                "status": "OK" if df["site_id"].nunique() == 53 else "WARN",
                "detail": df["site_id"].nunique(),
            })
            hmin, hmax = int(df["hour"].min()), int(df["hour"].max())
            checks.append({
                "item": "final_eval_hour_range",
                "exists": True,
                "required": True,
                "size_mb": 0,
                "status": "OK" if hmin >= 6 and hmax <= 19 else "WARN",
                "detail": f"{hmin}-{hmax}",
            })
        except Exception as exc:
            checks.append({
                "item": "final_eval_readable",
                "exists": True,
                "required": True,
                "size_mb": 0,
                "status": "FAIL",
                "detail": str(exc),
            })

    out = pd.DataFrame(checks)
    out.to_csv(METRICS / "round7_end_to_end_deliverables_check.csv", index=False, encoding="utf-8-sig")
    print(out.to_string(index=False))

    bad = out[(out["required"] == True) & (~out["status"].isin(["OK"]))]
    if not bad.empty:
        print("[FAIL] 存在未通过检查项")
        raise SystemExit(1)
    print("[OK] end-to-end deliverables check passed.")


if __name__ == "__main__":
    main()
