#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round10：初始化当前最优版本保护机制"""
from __future__ import annotations

from pathlib import Path
import shutil, json
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

FINAL_EVAL = TABLES / "distributed_predictions_final_eval.pkl"
FINAL_FULL = TABLES / "distributed_predictions_final_full.pkl"
BEST_EVAL = TABLES / "best_predictions_eval.pkl"
BEST_FULL = TABLES / "best_predictions_full.pkl"
BEST_META = METRICS / "round10_best_version_meta.json"


def main():
    for f in [FINAL_EVAL, FINAL_FULL]:
        if not f.exists():
            raise FileNotFoundError(f)

    init = False
    if not BEST_EVAL.exists():
        shutil.copy2(FINAL_EVAL, BEST_EVAL)
        init = True
    if not BEST_FULL.exists():
        shutil.copy2(FINAL_FULL, BEST_FULL)
        init = True

    meta = {
        "best_eval": str(BEST_EVAL.relative_to(PROJECT_ROOT)),
        "best_full": str(BEST_FULL.relative_to(PROJECT_ROOT)),
        "initialized_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if init else None,
        "note": "best_predictions_* 是当前最优保护版本，后续候选只有更优才允许覆盖。",
    }
    BEST_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[OK] current best initialized/protected")
    print(f"  best_eval: {BEST_EVAL}")
    print(f"  best_full: {BEST_FULL}")
    print(f"  meta: {BEST_META}")


if __name__ == "__main__":
    main()
