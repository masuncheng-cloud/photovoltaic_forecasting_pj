#!/usr/bin/env python3
"""
Compare retrain outputs against the verified backup for Round 14.

This script:
1. Reads current final PKL and backup final PKL
2. Computes key metrics for both (overall NRMSE, midday site NRMSE, MAE, RMSE)
3. Compares against acceptance thresholds
4. Checks audit grade and final==best condition
5. Restores from backup if any threshold exceeded or conditions not met
6. Outputs round14_retrain_decision.json and round14_retrain_vs_verified_best.csv
"""

import json
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path("/home/ac/data16t/msc/photovoltaic_forecasting_pj")
sys.path_insert(0, str(PROJECT_ROOT))

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
# Metric computation
# =============================================================================

def compute_overall_metrics(df: pd.DataFrame) -> dict:
    """Compute overall metrics from test set 6-19h."""
    eval_df = df[
        df["split"].eq("test") &
        df["hour"].between(6, 19) &
        df["power_mw"].notna() &
        df["power_pred"].notna()
    ].copy()

    y = eval_df["power_mw"].astype(float).values
    p = eval_df["power_pred"].astype(float).values
    actual_sum = float(np.sum(y))
    pred_sum = float(np.sum(p))
    mae = float(np.mean(np.abs(p - y)))
    rmse = float(np.sqrt(np.mean((p - y) ** 2)))
    cap_mean = float(eval_df["capacity_mw"].mean())
    nrmse = rmse / cap_mean * 100
    bias = (pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100
    pred_actual = pred_sum / max(actual_sum, 1e-9)

    return {
        "rows": len(eval_df),
        "n_sites": int(eval_df["site_id"].nunique()),
        "actual_mwh": round(actual_sum, 4),
        "pred_mwh": round(pred_sum, 4),
        "mae_mw": round(mae, 6),
        "rmse_mw": round(rmse, 6),
        "nrmse_pct": round(nrmse, 6),
        "bias_pct": round(bias, 6),
        "pred_actual_ratio": round(pred_actual, 6),
    }


def compute_midday_metrics(df: pd.DataFrame) -> dict:
    """Compute 10-14h midday metrics."""
    eval_df = df[
        df["split"].eq("test") &
        df["hour"].between(10, 14) &
        df["power_mw"].notna() &
        df["power_pred"].notna()
    ].copy()

    # Site mean NRMSE: per-site RMSE/capacity*100, then mean across sites
    site_rows = []
    for sid, g in eval_df.groupby("site_id"):
        y = g["power_mw"].astype(float).values
        p = g["power_pred"].astype(float).values
        c = max(float(g["capacity_mw"].mean()), 1e-9)
        rmse = float(np.sqrt(np.mean((p - y) ** 2)))
        site_rows.append({"site_id": sid, "site_nrmse": rmse / c * 100})
    site_nrmse_df = pd.DataFrame(site_rows)
    site_mean_nrmse = float(site_nrmse_df["site_nrmse"].mean()) if len(site_nrmse_df) > 0 else float("nan")

    # City NRMSE: |sum(pred) - sum(actual)| / sum(capacity_mw) * 100
    y_all = eval_df["power_mw"].astype(float).values
    p_all = eval_df["power_pred"].astype(float).values
    c_all = eval_df["capacity_mw"].astype(float).values
    mask = np.isfinite(y_all) & np.isfinite(p_all) & np.isfinite(c_all) & (c_all > 0)
    if mask.sum() > 0:
        city_actual = float(np.nansum(y_all[mask]))
        city_pred = float(np.nansum(p_all[mask]))
        city_cap = float(np.nansum(c_all[mask]))
        city_nrmse = float(np.abs(city_actual - city_pred)) / max(city_cap, 1e-9) * 100
    else:
        city_nrmse = float("nan")

    return {
        "site_mean_nrmse_pct": round(site_mean_nrmse, 6),
        "city_nrmse_pct": round(city_nrmse, 6),
        "rows": len(eval_df),
        "n_sites": int(eval_df["site_id"].nunique()),
    }


# =============================================================================
# Restore from backup
# =============================================================================

BACKUP_PAIRS = [
    # (backup_path, original_path)
    ("verified_backup_round14/tables/distributed_predictions_final_eval.pkl",
     "tables/distributed_predictions_final_eval.pkl"),
    ("verified_backup_round14/tables/distributed_predictions_final_full.pkl",
     "tables/distributed_predictions_final_full.pkl"),
    ("verified_backup_round14/tables/best_predictions_eval.pkl",
     "tables/best_predictions_eval.pkl"),
    ("verified_backup_round14/tables/best_predictions_full.pkl",
     "tables/best_predictions_full.pkl"),
]

METRICS_BACKUP_PAIRS = [
    ("verified_backup_round14/metrics/round10_overall_nrmse_summary.csv",
     "metrics/round10_overall_nrmse_summary.csv"),
    ("verified_backup_round14/metrics/分布式光伏预测_逐小时平均NRMSE.csv",
     "metrics/分布式光伏预测_逐小时平均NRMSE.csv"),
]

DASHBOARD_BACKUP_FILES = [
    "verified_backup_round14/interactive_dashboard/hourly_prediction_summary.json",
    "verified_backup_round14/interactive_dashboard/error_threshold_summary.json",
    "verified_backup_round14/interactive_dashboard/sample_requirement_bins.json",
    "verified_backup_round14/interactive_dashboard/sample_requirement_summary.json",
    "verified_backup_round14/interactive_dashboard/scatter_site_sample_nrmse.json",
    "verified_backup_round14/interactive_dashboard/scatter_site_hour.json",
    "verified_backup_round14/interactive_dashboard/season_days.json",
    "verified_backup_round14/interactive_dashboard/midday_city_by_date.json",
    "verified_backup_round14/interactive_dashboard/site_metrics.json",
    "verified_backup_round14/interactive_dashboard/city_series.json",
    "verified_backup_round14/interactive_dashboard/index.json",
]

DOCS_REPORT_FILES = [
    ("verified_backup_round14/docs/训练过程与结果严谨性验证报告.md",
     "docs/训练过程与结果严谨性验证报告.md"),
]


def restore_from_backup(root: Path) -> list[str]:
    """Copy all backup files back to their original locations."""
    restored = []
    for backup_rel, orig_rel in BACKUP_PAIRS:
        backup_path = root / backup_rel
        orig_path = root / orig_rel
        if backup_path.exists():
            orig_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, orig_path)
            restored.append(str(orig_rel))

    for backup_rel, orig_rel in METRICS_BACKUP_PAIRS:
        backup_path = root / backup_rel
        orig_path = root / orig_rel
        if backup_path.exists():
            orig_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, orig_path)
            restored.append(str(orig_rel))

    for backup_rel in DASHBOARD_BACKUP_FILES:
        backup_path = root / backup_rel
        orig_path = root / backup_rel.replace("verified_backup_round14/", "")
        if backup_path.exists():
            orig_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, orig_path)
            restored.append(str(backup_rel.replace("verified_backup_round14/", "")))

    for backup_rel, orig_rel in DOCS_REPORT_FILES:
        backup_path = root / backup_rel
        orig_path = root / orig_rel
        if backup_path.exists():
            orig_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, orig_path)
            restored.append(str(orig_rel))

    return restored


# =============================================================================
# Main comparison logic
# =============================================================================

def main():
    root = PROJECT_ROOT / "output" / "pv_pipeline"
    metrics_dir = root / "metrics"
    tables_dir = root / "tables"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    # Paths
    current_final_path = tables_dir / "distributed_predictions_final_eval.pkl"
    backup_final_path = root / "verified_backup_round14/tables/distributed_predictions_final_eval.pkl"
    current_best_path = tables_dir / "best_predictions_eval.pkl"
    audit_summary_path = metrics_dir / "audit_summary.json"
    round10_check_path = metrics_dir / "round10_final_is_best_check.csv"

    # Thresholds (retrain must not be worse than backup by more than)
    THRESH_OVERALL_NRMSE = 0.05    # percentage points
    THRESH_MIDDAY_SITE_NRMSE = 0.05  # percentage points
    THRESH_MAE = 0.005             # MW
    THRESH_RMSE = 0.005            # MW

    print("=" * 70)
    print("Round14: Retrain vs Verified Backup Comparison")
    print("=" * 70)

    start_time = time.time()

    # Check if current files exist
    current_exists = current_final_path.exists()
    backup_exists = backup_final_path.exists()

    print(f"\nCurrent final PKL: {current_exists} ({current_final_path})")
    print(f"Backup final PKL:  {backup_exists} ({backup_final_path})")

    # Read current and backup
    df_current = safe_read_pickle(current_final_path) if current_exists else None
    df_backup = safe_read_pickle(backup_final_path) if backup_exists else None

    # Check audit grade
    audit_grade = "A"
    audit_grade_a = False
    if audit_summary_path.exists():
        try:
            audit_data = json.loads(audit_summary_path.read_text(encoding="utf-8"))
            audit_grade = audit_data.get("grade", "C")
            audit_grade_a = (audit_grade == "A")
        except Exception:
            audit_grade = "C"
    print(f"\nAudit grade: {audit_grade} (Grade A required: {audit_grade_a})")

    # Check final == best
    final_equals_best = False
    if df_current is not None:
        df_best = safe_read_pickle(current_best_path)
        if df_best is not None:
            common = df_current.set_index(["time", "site_id"]).index.intersection(
                df_best.set_index(["time", "site_id"]).index
            )
            if len(common) > 0:
                f_pred = df_current.set_index(["time", "site_id"]).loc[common, "power_pred"]
                b_pred = df_best.set_index(["time", "site_id"]).loc[common, "power_pred"]
                diff = (f_pred - b_pred).abs()
                final_equals_best = float(diff.max()) < 1e-6
    print(f"Final equals best: {final_equals_best}")

    # Compute metrics for current and backup
    current_metrics = compute_overall_metrics(df_current) if df_current is not None else None
    backup_metrics = compute_overall_metrics(df_backup) if df_backup is not None else None
    current_midday = compute_midday_metrics(df_current) if df_current is not None else None
    backup_midday = compute_midday_metrics(df_backup) if df_backup is not None else None

    print("\n--- Overall Metrics ---")
    if current_metrics:
        print(f"  Current: rows={current_metrics['rows']}, sites={current_metrics['n_sites']}, "
              f"MAE={current_metrics['mae_mw']:.6f}, RMSE={current_metrics['rmse_mw']:.6f}, "
              f"NRMSE={current_metrics['nrmse_pct']:.4f}%")
    else:
        print("  Current: NOT AVAILABLE")
    if backup_metrics:
        print(f"  Backup:  rows={backup_metrics['rows']}, sites={backup_metrics['n_sites']}, "
              f"MAE={backup_metrics['mae_mw']:.6f}, RMSE={backup_metrics['rmse_mw']:.6f}, "
              f"NRMSE={backup_metrics['nrmse_pct']:.4f}%")
    else:
        print("  Backup:  NOT AVAILABLE")

    print("\n--- Midday (10-14h) Metrics ---")
    if current_midday:
        print(f"  Current: site_mean_nrmse={current_midday['site_mean_nrmse_pct']:.4f}%, "
              f"city_nrmse={current_midday['city_nrmse_pct']:.4f}%")
    else:
        print("  Current: NOT AVAILABLE")
    if backup_midday:
        print(f"  Backup:  site_mean_nrmse={backup_midday['site_mean_nrmse_pct']:.4f}%, "
              f"city_nrmse={backup_midday['city_nrmse_pct']:.4f}%")
    else:
        print("  Backup:  NOT AVAILABLE")

    # Determine if restore is needed
    reasons = []

    if df_current is None:
        reasons.append("current final PKL does not exist")
    if df_backup is None:
        reasons.append("backup final PKL does not exist")

    nrmse_exceeded = False
    midday_exceeded = False
    mae_exceeded = False
    rmse_exceeded = False

    if current_metrics is not None and backup_metrics is not None:
        nrmse_delta = current_metrics["nrmse_pct"] - backup_metrics["nrmse_pct"]
        midday_delta = current_midday["site_mean_nrmse_pct"] - backup_midday["site_mean_nrmse_pct"] if (current_midday and backup_midday) else 0
        mae_delta = current_metrics["mae_mw"] - backup_metrics["mae_mw"]
        rmse_delta = current_metrics["rmse_mw"] - backup_metrics["rmse_mw"]

        print(f"\n--- Threshold Checks (delta = current - backup) ---")
        print(f"  overall_NRMSE delta: {nrmse_delta:+.4f} pp  (threshold: +{THRESH_OVERALL_NRMSE:.2f} pp)")
        print(f"  midday site_NRMSE delta: {midday_delta:+.4f} pp  (threshold: +{THRESH_MIDDAY_SITE_NRMSE:.2f} pp)")
        print(f"  MAE delta: {mae_delta:+.6f} MW  (threshold: +{THRESH_MAE:.4f} MW)")
        print(f"  RMSE delta: {rmse_delta:+.6f} MW  (threshold: +{THRESH_RMSE:.4f} MW)")

        if nrmse_delta > THRESH_OVERALL_NRMSE:
            nrmse_exceeded = True
            reasons.append(f"overall_NRMSE degraded by {nrmse_delta:.4f} pp > {THRESH_OVERALL_NRMSE:.2f} pp")
        if midday_delta > THRESH_MIDDAY_SITE_NRMSE:
            midday_exceeded = True
            reasons.append(f"midday site_NRMSE degraded by {midday_delta:.4f} pp > {THRESH_MIDDAY_SITE_NRMSE:.2f} pp")
        if mae_delta > THRESH_MAE:
            mae_exceeded = True
            reasons.append(f"MAE degraded by {mae_delta:.6f} MW > {THRESH_MAE:.4f} MW")
        if rmse_delta > THRESH_RMSE:
            rmse_exceeded = True
            reasons.append(f"RMSE degraded by {rmse_delta:.6f} MW > {THRESH_RMSE:.4f} MW")
    elif df_current is not None and df_backup is None:
        # No backup to compare, accept current (as long as it reads fine)
        pass

    if not final_equals_best:
        reasons.append("final != best (power_pred mismatch)")

    if not audit_grade_a:
        reasons.append(f"audit grade is {audit_grade}, not A")

    should_restore = len(reasons) > 0

    print("\n" + "=" * 70)
    if should_restore:
        print("[RESTORED] Backup restoration triggered:")
        for r in reasons:
            print(f"  - {r}")
        restored_files = restore_from_backup(root)
        print(f"\nRestored {len(restored_files)} files:")
        for f in restored_files:
            print(f"  {f}")
        accepted = False
        reason = " | ".join(reasons)
    else:
        print("[ACCEPTED] Retrain results accepted")
        print("  All thresholds passed, final==best, audit Grade A")
        accepted = True
        reason = "all checks passed"

    elapsed = time.time() - start_time

    # Write decision JSON
    decision = {
        "accepted": accepted,
        "reason": reason,
        "current_overall_nrmse": current_metrics["nrmse_pct"] if current_metrics else None,
        "backup_overall_nrmse": backup_metrics["nrmse_pct"] if backup_metrics else None,
        "current_midday_site_nrmse": current_midday["site_mean_nrmse_pct"] if current_midday else None,
        "backup_midday_site_nrmse": backup_midday["site_mean_nrmse_pct"] if backup_midday else None,
        "current_mae_mw": current_metrics["mae_mw"] if current_metrics else None,
        "backup_mae_mw": backup_metrics["mae_mw"] if backup_metrics else None,
        "current_rmse_mw": current_metrics["rmse_mw"] if current_metrics else None,
        "backup_rmse_mw": backup_metrics["rmse_mw"] if backup_metrics else None,
        "current_bias_pct": current_metrics["bias_pct"] if current_metrics else None,
        "backup_bias_pct": backup_metrics["bias_pct"] if backup_metrics else None,
        "current_pred_actual_ratio": current_metrics["pred_actual_ratio"] if current_metrics else None,
        "backup_pred_actual_ratio": backup_metrics["pred_actual_ratio"] if backup_metrics else None,
        "current_rows": current_metrics["rows"] if current_metrics else None,
        "backup_rows": backup_metrics["rows"] if backup_metrics else None,
        "current_n_sites": current_metrics["n_sites"] if current_metrics else None,
        "backup_n_sites": backup_metrics["n_sites"] if backup_metrics else None,
        "current_midday_city_nrmse": current_midday["city_nrmse_pct"] if current_midday else None,
        "backup_midday_city_nrmse": backup_midday["city_nrmse_pct"] if backup_midday else None,
        "restored_from_backup": should_restore,
        "retrain_hours": round(elapsed, 2),
        "audit_grade": audit_grade,
        "final_equals_best": final_equals_best,
        "thresholds": {
            "overall_nrmse_pp": THRESH_OVERALL_NRMSE,
            "midday_site_nrmse_pp": THRESH_MIDDAY_SITE_NRMSE,
            "mae_mw": THRESH_MAE,
            "rmse_mw": THRESH_RMSE,
        },
    }

    decision_path = metrics_dir / "round14_retrain_decision.json"
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    with open(decision_path, "w", encoding="utf-8") as f:
        json.dump(decision, f, ensure_ascii=False, indent=2)
    print(f"\nDecision JSON written: {decision_path}")

    # Write comparison CSV
    rows = []
    # Overall
    if current_metrics and backup_metrics:
        nrmse_delta = current_metrics["nrmse_pct"] - backup_metrics["nrmse_pct"]
        rows.append({
            "metric": "overall_nrmse_pct",
            "current": round(current_metrics["nrmse_pct"], 4),
            "backup": round(backup_metrics["nrmse_pct"], 4),
            "delta": round(nrmse_delta, 4),
            "threshold": THRESH_OVERALL_NRMSE,
            "passed": abs(nrmse_delta) <= THRESH_OVERALL_NRMSE,
            "exceeded": nrmse_delta > THRESH_OVERALL_NRMSE,
        })
        rows.append({
            "metric": "mae_mw",
            "current": round(current_metrics["mae_mw"], 6),
            "backup": round(backup_metrics["mae_mw"], 6),
            "delta": round(current_metrics["mae_mw"] - backup_metrics["mae_mw"], 6),
            "threshold": THRESH_MAE,
            "passed": abs(current_metrics["mae_mw"] - backup_metrics["mae_mw"]) <= THRESH_MAE,
            "exceeded": (current_metrics["mae_mw"] - backup_metrics["mae_mw"]) > THRESH_MAE,
        })
        rows.append({
            "metric": "rmse_mw",
            "current": round(current_metrics["rmse_mw"], 6),
            "backup": round(backup_metrics["rmse_mw"], 6),
            "delta": round(current_metrics["rmse_mw"] - backup_metrics["rmse_mw"], 6),
            "threshold": THRESH_RMSE,
            "passed": abs(current_metrics["rmse_mw"] - backup_metrics["rmse_mw"]) <= THRESH_RMSE,
            "exceeded": (current_metrics["rmse_mw"] - backup_metrics["rmse_mw"]) > THRESH_RMSE,
        })
        rows.append({
            "metric": "bias_pct",
            "current": round(current_metrics["bias_pct"], 4),
            "backup": round(backup_metrics["bias_pct"], 4),
            "delta": round(current_metrics["bias_pct"] - backup_metrics["bias_pct"], 4),
            "threshold": None,
            "passed": True,
            "exceeded": False,
        })
        rows.append({
            "metric": "pred_actual_ratio",
            "current": round(current_metrics["pred_actual_ratio"], 6),
            "backup": round(backup_metrics["pred_actual_ratio"], 6),
            "delta": round(current_metrics["pred_actual_ratio"] - backup_metrics["pred_actual_ratio"], 6),
            "threshold": None,
            "passed": True,
            "exceeded": False,
        })
        rows.append({
            "metric": "rows",
            "current": current_metrics["rows"],
            "backup": backup_metrics["rows"],
            "delta": current_metrics["rows"] - backup_metrics["rows"],
            "threshold": None,
            "passed": current_metrics["rows"] == backup_metrics["rows"],
            "exceeded": False,
        })
        rows.append({
            "metric": "n_sites",
            "current": current_metrics["n_sites"],
            "backup": backup_metrics["n_sites"],
            "delta": current_metrics["n_sites"] - backup_metrics["n_sites"],
            "threshold": None,
            "passed": current_metrics["n_sites"] == backup_metrics["n_sites"],
            "exceeded": False,
        })
    # Midday
    if current_midday and backup_midday:
        midday_delta = current_midday["site_mean_nrmse_pct"] - backup_midday["site_mean_nrmse_pct"]
        rows.append({
            "metric": "midday_10_14h_site_mean_nrmse_pct",
            "current": round(current_midday["site_mean_nrmse_pct"], 4),
            "backup": round(backup_midday["site_mean_nrmse_pct"], 4),
            "delta": round(midday_delta, 4),
            "threshold": THRESH_MIDDAY_SITE_NRMSE,
            "passed": abs(midday_delta) <= THRESH_MIDDAY_SITE_NRMSE,
            "exceeded": midday_delta > THRESH_MIDDAY_SITE_NRMSE,
        })
        rows.append({
            "metric": "midday_10_14h_city_nrmse_pct",
            "current": round(current_midday["city_nrmse_pct"], 4),
            "backup": round(backup_midday["city_nrmse_pct"], 4),
            "delta": round(current_midday["city_nrmse_pct"] - backup_midday["city_nrmse_pct"], 4),
            "threshold": None,
            "passed": True,
            "exceeded": False,
        })
    # Conditions
    rows.append({
        "metric": "final_equals_best",
        "current": final_equals_best,
        "backup": True,
        "delta": None,
        "threshold": None,
        "passed": final_equals_best,
        "exceeded": not final_equals_best,
    })
    rows.append({
        "metric": "audit_grade_A",
        "current": audit_grade_a,
        "backup": True,
        "delta": None,
        "threshold": None,
        "passed": audit_grade_a,
        "exceeded": not audit_grade_a,
    })

    comparison_df = pd.DataFrame(rows)
    comparison_path = metrics_dir / "round14_retrain_vs_verified_best.csv"
    comparison_df.to_csv(comparison_path, index=False, encoding="utf-8")
    print(f"Comparison CSV written: {comparison_path}")

    print(f"\n{'=' * 70}")
    if accepted:
        print("[ACCEPTED] Retrain results accepted")
    else:
        print("[RESTORED] Backup restored — retrain did not improve")
    print(f"Total time: {elapsed:.2f}s")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    import sys
    main()
