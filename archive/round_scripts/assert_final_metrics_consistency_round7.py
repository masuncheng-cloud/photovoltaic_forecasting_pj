#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round7 脚本二：metrics 一致性断言
==================================
读取最新 final_eval.pkl 和核心 CSV，检查是否一致。
若发现 13.32/14.72 等旧结果残留，直接失败。
"""
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load
from pv_forecasting.core.evaluation import hourly_nrmse_metrics

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"

FINAL_EVAL = TABLES / "distributed_predictions_final_eval.pkl"
HOURLY_CSV = METRICS / "分布式光伏预测_逐小时平均NRMSE.csv"
VS_FIXED = METRICS / "midday_nrmse_current_vs_fixed.csv"
VS_SAFE = METRICS / "round6_midday_gain_vs_safe.csv"
SUMMARY_MD = DOCS / "当前最终结果摘要.md"

MIDDAY = [10, 11, 12, 13, 14]


def main():
    final = safe_pickle_load(FINAL_EVAL)
    h = hourly_nrmse_metrics(final)
    h = h[h["hour"].isin(MIDDAY)].copy()
    truth = {
        int(r["hour"]): round(float(r["site_nrmse_mean_pct"]), 2)
        for _, r in h.iterrows()
    }

    errors = []

    # 检查逐小时 CSV
    hourly = pd.read_csv(HOURLY_CSV)
    for hour, val in truth.items():
        row = hourly[hourly["hour"] == hour]
        if row.empty:
            errors.append(f"hourly csv 缺少 hour={hour}")
            continue
        csv_val = round(float(row.iloc[0]["site_nrmse_mean_pct"]), 2)
        if abs(csv_val - val) > 0.01:
            errors.append(f"hourly csv hour={hour} 不一致: csv={csv_val}, final={val}")

    # 检查 vs_safe
    if VS_SAFE.exists():
        safe = pd.read_csv(VS_SAFE)
        for hour, val in truth.items():
            row = safe[safe["hour"] == hour]
            if row.empty:
                continue
            final_val = round(float(row.iloc[0]["final_site_nrmse_pct"]), 2)
            if abs(final_val - val) > 0.01:
                errors.append(f"vs_safe hour={hour} 不一致: csv={final_val}, final={val}")

    # 检查 vs_fixed
    if VS_FIXED.exists():
        fixed = pd.read_csv(VS_FIXED)
        for hour, val in truth.items():
            row = fixed[fixed["hour"] == hour]
            if row.empty:
                continue
            final_val = round(float(row.iloc[0]["final_site_nrmse_pct"]), 2)
            if abs(final_val - val) > 0.01:
                errors.append(f"vs_fixed hour={hour} 不一致: csv={final_val}, final={val}")

    # 检查摘要 MD
    if SUMMARY_MD.exists():
        text = SUMMARY_MD.read_text(encoding="utf-8")
        for hour, val in truth.items():
            if f"{val:.2f}" not in text:
                errors.append(f"当前最终结果摘要.md 可能未包含 hour={hour} 最新值 {val:.2f}")

    if errors:
        print("[FAIL] final metrics consistency failed:")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)

    print("[OK] final metrics consistency passed.")
    print(truth)


if __name__ == "__main__":
    main()
