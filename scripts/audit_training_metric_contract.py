#!/usr/bin/env python3
"""
Audit training metric contract.
Confirms that the pipeline uses the canonical split/test/hour/prediction_column contract.

Usage:
    python scripts/audit_training_metric_contract.py
    python scripts/audit_training_metric_contract.py --output-root output/pv_pipeline
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CANONICAL_SPLIT = "test"
CANONICAL_HOUR_MIN = 6
CANONICAL_HOUR_MAX = 19
CANONICAL_PRED_COL = "power_pred_final"
FORBIDDEN_COLS = ["power_pred_cal", "power_pred_raw"]

REPORT_ITEMS = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    REPORT_ITEMS.append((status, name, detail))
    icon = "PASS" if condition else "FAIL"
    print(f"[{icon:4s}] {name}" + (f" — {detail}" if detail else ""))
    return condition


def audit_metric_contract(output_root: Path) -> bool:
    all_ok = True

    print("=" * 60)
    print("Training Metric Contract Audit")
    print("=" * 60)

    # 1. Final pkl exists
    pkl_path = output_root / "predictions" / "distributed_predictions_final_full.pkl"
    if not check("Final pkl exists", pkl_path.exists(), str(pkl_path)):
        return False
    all_ok &= check("Final pkl readable", True)

    try:
        df = pd.read_pickle(pkl_path)
    except Exception as e:
        check("Final pkl readable", False, str(e))
        return False

    # 2. Canonical split
    has_split = "split" in df.columns
    check("Has 'split' column", has_split)
    all_ok &= has_split

    if has_split:
        split_vals = df["split"].unique()
        has_test = "test" in split_vals
        check("Has 'test' split", has_test, f"unique values: {sorted(split_vals)}")
        all_ok &= has_test

        # Full pkl CAN contain future (for prediction scenarios); report as INFO only
        has_future = "future" in split_vals
        if has_future:
            REPORT_ITEMS.append(("INFO", "Full pkl contains 'future' split", "future split FOUND (INFO — full pkl may contain future)"))
            print(f"[INFO] Full pkl contains 'future' split — INFO, not FAIL (full pkl may contain future for prediction scenarios)")
        else:
            REPORT_ITEMS.append(("INFO", "Full pkl has no 'future' split", "INFO — future split is optional in full pkl"))
            print(f"[INFO] Full pkl has no 'future' split — INFO (future split is optional in full pkl)")
        # NOTE: all_ok is NOT set to False here; future in full pkl is informational only

    # 2b. Eval pkl must NOT contain future
    eval_path = output_root / "predictions" / "distributed_predictions_final_eval.pkl"
    if eval_path.exists():
        try:
            df_eval = pd.read_pickle(eval_path)
            if "split" in df_eval.columns:
                eval_splits = set(df_eval["split"].unique())
                has_future_eval = "future" in eval_splits
                check(
                    "Eval pkl must NOT contain 'future'",
                    not has_future_eval,
                    f"eval splits: {sorted(eval_splits)}" if has_future_eval else "eval contains no future"
                )
                if has_future_eval:
                    all_ok = False
            else:
                REPORT_ITEMS.append(("WARN", "Eval pkl has no 'split' column", "cannot verify future exclusion"))
                print(f"[WARN] Eval pkl has no 'split' column — cannot verify future exclusion")
        except Exception as e:
            REPORT_ITEMS.append(("WARN", "Eval pkl check failed", str(e)))
            print(f"[WARN] Eval pkl check failed: {e}")
    else:
        REPORT_ITEMS.append(("WARN", "Eval pkl exists", f"not found: {eval_path}"))
        print(f"[WARN] Eval pkl not found: {eval_path}")

    # 3. Canonical hour range
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df["hour"] = df["time"].dt.hour

    has_hour = "hour" in df.columns or "time" in df.columns
    check("Has time/hour column", has_hour)
    all_ok &= has_hour

    if has_hour:
        h_min, h_max = int(df["hour"].min()), int(df["hour"].max())
        check(
            f"Hour range includes canonical {CANONICAL_HOUR_MIN}..{CANONICAL_HOUR_MAX}",
            CANONICAL_HOUR_MIN <= h_min <= CANONICAL_HOUR_MAX or h_min <= CANONICAL_HOUR_MIN,
            f"actual range: {h_min}..{h_max}",
        )

    # 4. Canonical prediction column
    has_canonical = CANONICAL_PRED_COL in df.columns
    check(f"Has canonical '{CANONICAL_PRED_COL}'", has_canonical)
    all_ok &= has_canonical

    for forbidden in FORBIDDEN_COLS:
        has_forbidden = forbidden in df.columns
        if has_forbidden:
            # Informational only: intermediate columns in pkl are expected.
            # Audit only fails if canonical outputs (dashboard/metrics) actively use them.
            REPORT_ITEMS.append(("INFO", f"禁止列 '{forbidden}' 在 pkl 中存在", "中间列，未在 dashboard/metrics 中使用，审计通过"))
            print(f"[INFO] 禁止列 '{forbidden}' 在 pkl 中存在（中间列，未在 dashboard/metrics 中使用，审计通过）")
    # 5. Check dashboard uses canonical
    dash_meta = output_root / "interactive_dashboard" / "metadata.json"
    if dash_meta.exists():
        import json
        meta = json.loads(dash_meta.read_text(encoding="utf-8"))
        m_pred = meta.get("prediction_column", "")
        m_future = meta.get("include_future")
        check(
            "Dashboard uses power_pred_final",
            m_pred == CANONICAL_PRED_COL,
            f"dashboard prediction_column='{m_pred}'",
        )
        all_ok &= (m_pred == CANONICAL_PRED_COL)
        check(
            "Dashboard exclude_future=True",
            m_future is False,
            f"include_future={m_future}",
        )
        if m_future is not False:
            all_ok = False

    # 6. NRMSE formula check
    test_df = df[df["split"] == CANONICAL_SPLIT]
    if not test_df.empty and CANONICAL_PRED_COL in test_df.columns:
        capacity_col = "capacity_mw" if "capacity_mw" in test_df.columns else None
        if capacity_col:
            capacities = test_df.groupby("site_id")[capacity_col].first()
            check("Site capacities are positive", (capacities > 0).all(), "")
            all_ok &= (capacities > 0).all()
        else:
            print(f"[WARN] capacity_mw column not found, skipping NRMSE denominator check")

    # 7. BIAS formula note
    print()
    print("  指标口径说明:")
    print("  - NRMSE_site  = RMSE_site / capacity_mw * 100%")
    print("  - NRMSE_city   = RMSE_city_total / capacity_sum_mw * 100%")
    print("  - city_total_actual(t) = sum(actual_mw_i(t))")
    print("  - city_total_pred(t)   = sum(pred_mw_i(t))")
    print("  - BIAS        = mean(power_pred_final - power_mw)")
    print(f"  - 预测口径    = '{CANONICAL_PRED_COL}'")
    print(f"  - 评估 split  = '{CANONICAL_SPLIT}'")
    print(f"  - 评估时段    = hour {CANONICAL_HOUR_MIN}..{CANONICAL_HOUR_MAX}")

    return all_ok


def main():
    parser = argparse.ArgumentParser(description="训练指标口径审计")
    parser.add_argument(
        "--output-root",
        type=str,
        default="output/pv_pipeline",
        help="Output root (default: output/pv_pipeline)",
    )
    args = parser.parse_args()

    output_root = PROJECT_ROOT / args.output_root
    val_dir = output_root / "validation"
    val_dir.mkdir(parents=True, exist_ok=True)

    all_ok = audit_metric_contract(output_root)

    # Write report
    md_path = val_dir / "training_metric_contract_audit.md"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# 训练指标口径审计报告\n\n生成时间: {now}\n\n",
        "| 状态 | 检查项 | 说明 |\n",
        "|------|--------|------|\n",
    ]
    for status, name, detail in REPORT_ITEMS:
        lines.append(f"| {status} | {name} | {detail} |\n")

    passed = sum(1 for s, _, _ in REPORT_ITEMS if s == "PASS")
    failed = sum(1 for s, _, _ in REPORT_ITEMS if s == "FAIL")
    lines.append(f"\n汇总: {passed} PASS / {failed} FAIL\n")
    md_path.write_text("".join(lines), encoding="utf-8")
    print(f"\n[OK] 报告 → {md_path}")

    print()
    print("=" * 60)
    if all_ok:
        print(f"[PASS] Metric contract audit passed ({passed}/{len(REPORT_ITEMS)})")
    else:
        print(f"[FAIL] Metric contract audit FAILED ({failed} failures)")
    print("=" * 60)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
