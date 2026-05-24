#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round10：检查 final 是否比 best 差，若是则自动回退"""
from __future__ import annotations

from pathlib import Path
import sys, shutil
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

FINAL_EVAL = TABLES / "distributed_predictions_final_eval.pkl"
FINAL_FULL = TABLES / "distributed_predictions_final_full.pkl"
BEST_EVAL = TABLES / "best_predictions_eval.pkl"
BEST_FULL = TABLES / "best_predictions_full.pkl"


def _nrmse(df):
    y = pd.to_numeric(df["power_mw"], errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(df["power_pred"], errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(df["capacity_mw"], errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (c > 0)
    if not m.any():
        return np.nan
    return float(np.sqrt(np.mean((y[m] - p[m]) ** 2)) / np.nanmean(c[m]) * 100.0)


def main():
    if not BEST_EVAL.exists():
        raise FileNotFoundError(
            "best_predictions_eval.pkl 不存在，请先运行 save_current_best_round10.py"
        )

    final = safe_pickle_load(FINAL_EVAL)
    best = safe_pickle_load(BEST_EVAL)

    final_n = _nrmse(final)
    best_n = _nrmse(best)

    if final_n > best_n + 1e-6:
        shutil.copy2(BEST_EVAL, FINAL_EVAL)
        shutil.copy2(BEST_FULL, FINAL_FULL)
        status = "rolled_back"
    else:
        status = "ok"

    out = pd.DataFrame([{
        "final_overall_nrmse_pct": round(final_n, 6),
        "best_overall_nrmse_pct": round(best_n, 6),
        "delta_pp": round(final_n - best_n, 6),
        "status": status,
    }])
    out.to_csv(METRICS / "round10_final_is_best_check.csv", index=False, encoding="utf-8-sig")
    print(out.to_string(index=False))

    if status == "rolled_back":
        raise SystemExit("[WARN] final was worse than best, rolled back.")
    else:
        print("[OK] final is best, no rollback needed.")


if __name__ == "__main__":
    main()
