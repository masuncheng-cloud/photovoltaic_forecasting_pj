#!/usr/bin/env python3
"""
Round 14 Final Delivery Check.

Performs the final delivery check and writes results to:
output/pv_pipeline/metrics/round14_final_delivery_check.csv

Checks all items and prints a clear status at the end.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path("/home/ac/data16t/msc/photovoltaic_forecasting_pj")
sys.path.insert(0, str(PROJECT_ROOT))

# =============================================================================
# Pandas StringDtype pickle compatibility patch
# =============================================================================

def patch_pandas_string_dtype_pickle():
    """Patch pandas StringDtype pickle compatibility for older artifacts."""
    try:
        from pandas import StringDtype
        original_init = getattr(StringDtype, "__init__", None)

        def _patched_init__(self, storage=None, na_value=None):
            try:
                if original_init is not None:
                    original_init(self, storage=storage, na_value=na_value)
            except TypeError:
                try:
                    original_init(self, storage=storage)
                except TypeError:
                    try:
                        original_init(self)
                    except TypeError:
                        pass

        if not getattr(StringDtype, "_pv_pickle_patch_applied", False):
            StringDtype.__init__ = _patched_init__
            StringDtype._pv_pickle_patch_applied = True
    except Exception:
        pass


def safe_read_pickle(path: Path) -> pd.DataFrame | None:
    """Read a pickle file with StringDtype compatibility patch."""
    if not path.exists():
        return None
    patch_pandas_string_dtype_pickle()
    try:
        return pd.read_pickle(path)
    except Exception as e:
        print(f"  [WARN] Failed to read {path}: {e}")
        return None


# =============================================================================
# Check functions
# =============================================================================

def check_core_final_eval_readable(tables_dir: Path) -> tuple[bool, str]:
    """pd.read_pickle(distributed_predictions_final_eval.pkl) succeeds."""
    path = tables_dir / "distributed_predictions_final_eval.pkl"
    df = safe_read_pickle(path)
    passed = df is not None and len(df) > 0
    detail = f"rows={len(df)}" if df is not None else "file missing or unreadable"
    return passed, detail


def check_core_best_eval_readable(tables_dir: Path) -> tuple[bool, str]:
    """pd.read_pickle(best_predictions_eval.pkl) succeeds."""
    path = tables_dir / "best_predictions_eval.pkl"
    df = safe_read_pickle(path)
    passed = df is not None and len(df) > 0
    detail = f"rows={len(df)}" if df is not None else "file missing or unreadable"
    return passed, detail


def check_final_equals_best(tables_dir: Path) -> tuple[bool, str]:
    """Compare power_pred columns between final and best."""
    final_path = tables_dir / "distributed_predictions_final_eval.pkl"
    best_path = tables_dir / "best_predictions_eval.pkl"
    final_df = safe_read_pickle(final_path)
    best_df = safe_read_pickle(best_path)
    if final_df is None or best_df is None:
        return False, "final or best unreadable"
    try:
        common = final_df.set_index(["time", "site_id"]).index.intersection(
            best_df.set_index(["time", "site_id"]).index
        )
        if len(common) == 0:
            return False, "no common (time, site_id) keys"
        f_pred = final_df.set_index(["time", "site_id"]).loc[common, "power_pred"]
        b_pred = best_df.set_index(["time", "site_id"]).loc[common, "power_pred"]
        diff = (f_pred - b_pred).abs()
        max_diff = float(diff.max()) if len(diff) > 0 else 0.0
        passed = max_diff < 1e-6
        return passed, f"max_diff={max_diff:.8f}"
    except Exception as e:
        return False, f"error: {e}"


def check_audit_grade_a(metrics_dir: Path) -> tuple[bool, str]:
    """audit_summary.json grade == 'A'."""
    path = metrics_dir / "audit_summary.json"
    if not path.exists():
        return False, "audit_summary.json missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        grade = data.get("grade", "C")
        passed = (grade == "A")
        return passed, f"grade={grade}"
    except Exception as e:
        return False, f"error: {e}"


def check_project_report_exists(project_root: Path) -> tuple[bool, str]:
    """光伏功率预测项目.md exists."""
    path = project_root / "光伏功率预测项目.md"
    passed = path.exists()
    size = path.stat().st_size if path.exists() else 0
    return passed, f"size={size:,} bytes" if passed else "file missing"


def check_project_report_no_wape(project_root: Path) -> tuple[bool, str]:
    """Report does not contain WAPE or MAPE as primary metric."""
    path = project_root / "光伏功率预测项目.md"
    if not path.exists():
        return False, "report file missing"
    try:
        content = path.read_text(encoding="utf-8")
        has_wape = "WAPE" in content
        has_mape = "MAPE" in content
        # It's ok to mention WAPE/MAPE as context, but NRMSE should be the main metric
        # We check: NRMSE should be present and described as main/primary
        has_nrmse_main = "NRMSE" in content and ("主要指标" in content or "主要评估指标" in content)
        passed = not has_wape and not has_mape and has_nrmse_main
        issues = []
        if has_wape:
            issues.append("WAPE")
        if has_mape:
            issues.append("MAPE")
        if not has_nrmse_main:
            issues.append("NRMSE not marked as main")
        detail = "; ".join(issues) if issues else "NRMSE is main metric, no WAPE/MAPE"
        return passed, detail
    except Exception as e:
        return False, f"error: {e}"


def check_hourly_table_14_rows(metrics_dir: Path) -> tuple[bool, str]:
    """分布式光伏预测_逐小时平均NRMSE.csv has hours 6-19 (14 rows)."""
    path = metrics_dir / "分布式光伏预测_逐小时平均NRMSE.csv"
    if not path.exists():
        return False, "file missing"
    try:
        df = pd.read_csv(path)
        if "hour" not in df.columns:
            return False, "no 'hour' column"
        hours = set(df["hour"].astype(int).tolist())
        expected = set(range(6, 20))  # 6 through 19 inclusive
        passed = (hours == expected)
        detail = f"rows={len(df)}, hours={sorted(hours)}"
        return passed, detail
    except Exception as e:
        return False, f"error: {e}"


def check_dashboard_index_exists(dashboard_dir: Path) -> tuple[bool, str]:
    """interactive_dashboard/index.json exists."""
    path = dashboard_dir / "index.json"
    passed = path.exists()
    size = path.stat().st_size if path.exists() else 0
    return passed, f"size={size:,} bytes" if passed else "file missing"


def check_max_full_history_ge_20000(dashboard_dir: Path) -> tuple[bool, str]:
    """max full_history_rows >= 20000 in scatter JSON."""
    path = dashboard_dir / "scatter_site_sample_nrmse.json"
    if not path.exists():
        return False, "scatter file missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data:
            return False, "scatter is empty"
        max_val = max(int(s.get("full_history_rows") or 0) for s in data)
        passed = max_val >= 20000
        return passed, f"max_full_history_rows={max_val:,}"
    except Exception as e:
        return False, f"error: {e}"


def check_archive_manifest_exists(root: Path) -> tuple[bool, str]:
    """archive_round14/archive_manifest.csv exists."""
    path = root / "archive_round14" / "archive_manifest.csv"
    passed = path.exists()
    size = path.stat().st_size if path.exists() else 0
    return passed, f"size={size:,} bytes" if passed else "file missing"


def check_backup_manifest_exists(root: Path) -> tuple[bool, str]:
    """verified_backup_round14/backup_manifest.csv exists."""
    path = root / "verified_backup_round14" / "backup_manifest.csv"
    passed = path.exists()
    size = path.stat().st_size if path.exists() else 0
    return passed, f"size={size:,} bytes" if passed else "file missing"


def check_round14_decision_exists(metrics_dir: Path) -> tuple[bool, str]:
    """metrics/round14_retrain_decision.json exists."""
    path = metrics_dir / "round14_retrain_decision.json"
    passed = path.exists()
    size = path.stat().st_size if path.exists() else 0
    return passed, f"size={size:,} bytes" if passed else "file missing"


def check_round14_decision_accepted(metrics_dir: Path) -> tuple[bool, str]:
    """round14_retrain_decision.json accepted == True."""
    path = metrics_dir / "round14_retrain_decision.json"
    if not path.exists():
        return False, "decision file missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        accepted = data.get("accepted", False)
        reason = data.get("reason", "unknown")
        passed = (accepted is True)
        return passed, f"accepted={accepted}, reason={reason[:60]}"
    except Exception as e:
        return False, f"error: {e}"


# =============================================================================
# Main
# =============================================================================

def main():
    root = PROJECT_ROOT / "output" / "pv_pipeline"
    tables_dir = root / "tables"
    metrics_dir = root / "metrics"
    dashboard_dir = root / "interactive_dashboard"
    project_root = PROJECT_ROOT

    print("=" * 70)
    print("Round14 Final Delivery Check")
    print("=" * 70)

    checks = [
        ("core_final_eval_readable", check_core_final_eval_readable(tables_dir)),
        ("core_best_eval_readable", check_core_best_eval_readable(tables_dir)),
        ("final_equals_best", check_final_equals_best(tables_dir)),
        ("audit_grade_a", check_audit_grade_a(metrics_dir)),
        ("project_report_exists", check_project_report_exists(project_root)),
        ("project_report_no_wape", check_project_report_no_wape(project_root)),
        ("hourly_table_14_rows", check_hourly_table_14_rows(metrics_dir)),
        ("dashboard_index_exists", check_dashboard_index_exists(dashboard_dir)),
        ("max_full_history_ge_20000", check_max_full_history_ge_20000(dashboard_dir)),
        ("archive_manifest_exists", check_archive_manifest_exists(root)),
        ("backup_manifest_exists", check_backup_manifest_exists(root)),
        ("round14_decision_exists", check_round14_decision_exists(metrics_dir)),
        ("round14_decision_accepted", check_round14_decision_accepted(metrics_dir)),
    ]

    rows = []
    for check_item, (passed, detail) in checks:
        rows.append({
            "check_item": check_item,
            "passed": passed,
            "detail": detail,
        })

    df_results = pd.DataFrame(rows)
    output_path = metrics_dir / "round14_final_delivery_check.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df_results.to_csv(output_path, index=False, encoding="utf-8")

    print(f"\n{'check_item':<40} {'passed':<8} detail")
    print("-" * 90)
    for _, r in df_results.iterrows():
        icon = "OK" if r["passed"] else "FAIL"
        print(f"{r['check_item']:<40} [{icon}]  {r['detail']}")

    n_passed = df_results["passed"].sum()
    n_total = len(df_results)
    n_failed = n_total - n_passed

    print(f"\n{'=' * 70}")
    if n_failed == 0:
        print(f"[OK] Round14 final delivery package is ready ({n_passed}/{n_total} checks passed)")
    else:
        print(f"[FAIL] Some checks failed ({n_failed}/{n_total} failed):")
        for _, r in df_results[df_results["passed"] == False].iterrows():
            print(f"  - {r['check_item']}: {r['detail']}")
    print(f"{'=' * 70}")

    print(f"\nResults written to: {output_path}")


if __name__ == "__main__":
    main()
