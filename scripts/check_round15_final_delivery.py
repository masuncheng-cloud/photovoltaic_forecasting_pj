#!/usr/bin/env python3
"""
Step 3: Enhanced Final Delivery Check (Round15)
================================================
生成 `output/pv_pipeline/metrics/round15_final_delivery_check.csv`，
包含 check_name / passed / detail / severity 四个字段。

执行：
    python scripts/check_round15_final_delivery.py
"""

import csv
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = PROJECT_ROOT / "output" / "pv_pipeline"
OUT_CSV = ROOT / "metrics" / "round15_final_delivery_check.csv"


def _patch_string_dtype():
    import pandas
    sd = pandas.StringDtype
    orig = sd.__init__
    def patched(self, storage=None, validate=True):
        try:
            orig(self, storage=storage, validate=validate)
        except TypeError:
            try:
                orig(self, storage)
            except TypeError:
                orig(self)
    sd.__init__ = patched


_patch_string_dtype()

import pandas as pd
import numpy as np
import json


def check(name: str, passed: bool, detail: str, severity: str) -> dict:
    return {"check_name": name, "passed": passed, "detail": detail, "severity": severity}


def run():
    rows = []

    # --- 1. Core prediction files readable ---
    for fname, label in [
        ("tables/distributed_predictions_final_eval.pkl", "final_eval"),
        ("tables/distributed_predictions_final_full.pkl", "final_full"),
        ("tables/best_predictions_eval.pkl", "best_eval"),
        ("tables/best_predictions_full.pkl", "best_full"),
    ]:
        p = ROOT / fname
        try:
            df = pd.read_pickle(p)
            n = len(df)
            rows.append(check(f"{label}_readable", True,
                              f"{fname} readable, {n:,} rows", "CRITICAL"))
        except Exception as e:
            rows.append(check(f"{label}_readable", False,
                              f"read failed: {e}", "CRITICAL"))

    # --- 2. final == best ---
    try:
        fp = pd.read_pickle(ROOT / "tables/distributed_predictions_final_eval.pkl")
        bp = pd.read_pickle(ROOT / "tables/best_predictions_eval.pkl")
        # Compare power_pred columns
        fp_test = fp[fp["split"] == "test"]
        bp_test = bp[bp["split"] == "test"]
        # Align by index
        common_idx = fp_test.index.intersection(bp_test.index)
        diff = (fp_test.loc[common_idx, "power_pred"].astype(float)
                - bp_test.loc[common_idx, "power_pred"].astype(float)).abs().max()
        identical = float(diff) < 1e-6
        rows.append(check("final_equals_best", identical,
                          f"max power_pred diff={diff:.8f}", "CRITICAL"))
    except Exception as e:
        rows.append(check("final_equals_best", False, f"compare failed: {e}", "CRITICAL"))

    # --- 3. Audit Grade A ---
    try:
        audit = json.loads((ROOT / "metrics/audit_summary.json").read_text(encoding="utf-8"))
        grade = audit.get("grade", "C")
        fail_count = audit.get("fail_count", 999)
        warn_count = audit.get("warn_count", 999)
        rows.append(check("audit_grade_a", grade == "A",
                          f"grade={grade}", "CRITICAL"))
        rows.append(check("audit_fail_zero", fail_count == 0,
                          f"fail_count={fail_count}", "CRITICAL"))
        rows.append(check("audit_warn_zero", warn_count == 0,
                          f"warn_count={warn_count}", "CRITICAL"))
    except Exception as e:
        rows.append(check("audit_grade_a", False, f"read failed: {e}", "CRITICAL"))
        rows.append(check("audit_fail_zero", False, f"read failed: {e}", "CRITICAL"))
        rows.append(check("audit_warn_zero", False, f"read failed: {e}", "CRITICAL"))

    # --- 4. Project report checks ---
    report_path = PROJECT_ROOT / "光伏功率预测项目.md"
    try:
        text = report_path.read_text(encoding="utf-8")
        rows.append(check("project_report_exists", True,
                          f"{report_path.name} exists, {len(text):,} chars", "CRITICAL"))
        rows.append(check("project_report_no_wape_main_metric",
                          "WAPE" not in text.upper().replace(" ", "") or
                          text.upper().count("WAPE") == 0,
                          "WAPE not found in report", "CRITICAL"))
        rows.append(check("project_report_no_mape_main_metric",
                          "MAPE" not in text.upper().replace(" ", "") or
                          text.upper().count("MAPE") == 0,
                          "MAPE not found in report", "CRITICAL"))
        rows.append(check("project_report_has_raw_power_stats",
                          "原始功率长表总行数" in text,
                          "Section 1.2 has power stats table", "IMPORTANT"))
        rows.append(check("project_report_no_lightgbm_claim_if_missing_dep",
                          "LightGBM" not in text,
                          "LightGBM claim removed", "IMPORTANT"))
        rows.append(check("project_report_test_usage_clear",
                          "仅用于最终评估" in text or "test 集仅用于" in text,
                          "Test set usage clarified", "IMPORTANT"))
    except Exception as e:
        rows.append(check("project_report_exists", False, f"read failed: {e}", "CRITICAL"))
        rows.append(check("project_report_no_wape_main_metric", False,
                          f"read failed: {e}", "CRITICAL"))

    # --- 5. Hourly table ---
    try:
        hourly = pd.read_csv(ROOT / "metrics/分布式光伏预测_逐小时平均NRMSE.csv")
        hours = sorted(hourly["hour"].tolist())
        has_6_19 = hours == list(range(6, 20))
        rows.append(check("hourly_table_has_14_rows",
                          has_6_19 and len(hourly) == 14,
                          f"hours={hours}, rows={len(hourly)}", "IMPORTANT"))
    except Exception as e:
        rows.append(check("hourly_table_has_14_rows", False,
                          f"read failed: {e}", "IMPORTANT"))

    # --- 6. Dashboard ---
    dash_index = ROOT / "interactive_dashboard/index.json"
    rows.append(check("interactive_dashboard_index_exists", dash_index.exists(),
                      str(dash_index.relative_to(PROJECT_ROOT)), "IMPORTANT"))

    try:
        scatter_raw = json.loads((ROOT / "interactive_dashboard/scatter_site_sample_nrmse.json")
                                .read_text(encoding="utf-8"))
        if isinstance(scatter_raw, list):
            max_fh = max((s.get("full_history_rows", 0) for s in scatter_raw), default=0)
        else:
            max_fh = scatter_raw.get("max_full_history_rows", 0)
        rows.append(check("full_history_rows_ge_20000", max_fh >= 20000,
                          f"max_full_history_rows={max_fh}", "IMPORTANT"))
    except Exception as e:
        rows.append(check("full_history_rows_ge_20000", False,
                          f"read failed: {e}", "IMPORTANT"))

    # --- 7. Archive manifests ---
    rows.append(check("archive_round15_manifest_exists",
                      (ROOT / "archive_round15/archive_manifest.csv").exists(),
                      str(ROOT / "archive_round15/archive_manifest.csv"), "IMPORTANT"))
    rows.append(check("backup_round14_manifest_exists",
                      (ROOT / "verified_backup_round14/backup_manifest.csv").exists(),
                      str(ROOT / "verified_backup_round14/backup_manifest.csv"), "IMPORTANT"))

    # --- 8. ZIP checks ---
    zip_path = PROJECT_ROOT / "dist" / "photovoltaic_forecasting_pj_round15_delivery.zip"
    if zip_path.exists():
        rows.append(check("zip_exists", True, str(zip_path), "IMPORTANT"))
        try:
            bad_in_zip = []
            with zipfile.ZipFile(zip_path) as z:
                for name in z.namelist():
                    for pattern in [".git/", "__MACOSX/", ".DS_Store",
                                    "__pycache__/", "auto_push_test.txt",
                                    "test_auto_push.txt", "auto_sync.log", "截屏"]:
                        if pattern in name:
                            bad_in_zip.append(name)
                            break
            rows.append(check("zip_exclude_git", ".git/" not in str(bad_in_zip),
                              f".git/ in zip: {'.git/' in str(bad_in_zip)}", "IMPORTANT"))
            rows.append(check("zip_exclude_macosx", "__MACOSX/" not in str(bad_in_zip),
                              f"__MACOSX/ in zip: {'__MACOSX/' in str(bad_in_zip)}", "IMPORTANT"))
            rows.append(check("zip_exclude_test_push_files",
                              "auto_push_test.txt" not in str(bad_in_zip),
                              f"test files in zip: {bad_in_zip}", "IMPORTANT"))
        except Exception as e:
            rows.append(check("zip_exclude_git", False, f"read zip failed: {e}", "IMPORTANT"))
    else:
        rows.append(check("zip_exists", False,
                          f"{zip_path} not found — run build script first", "IMPORTANT"))
        for n in ["zip_exclude_git", "zip_exclude_macosx", "zip_exclude_test_push_files"]:
            rows.append(check(n, True, "zip does not exist yet", "INFO"))

    # --- Write CSV ---
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["check_name", "passed", "detail", "severity"])
        writer.writeheader()
        writer.writerows(rows)

    # --- Summary ---
    df = pd.DataFrame(rows)
    total = len(df)
    passed_all = df["passed"].all()
    errors = df[(df["severity"] == "CRITICAL") & (~df["passed"].astype(bool))]
    warnings = df[(df["severity"] == "IMPORTANT") & (~df["passed"].astype(bool))]

    print(f"\n=== Round15 Final Delivery Check ===")
    print(f"  Total checks: {total}")
    print(f"  Passed: {df['passed'].sum()}")
    print(f"  Failed (CRITICAL): {len(errors)}")
    print(f"  Failed (IMPORTANT): {len(warnings)}")
    print(f"  Output: {OUT_CSV}")

    if not errors.empty:
        print(f"\n  CRITICAL failures:")
        for _, r in errors.iterrows():
            print(f"    [FAIL] {r['check_name']}: {r['detail']}")

    critical_ok = errors.empty
    print(f"\n[{'OK' if critical_ok else 'FAIL'}] Round15 final delivery check")
    if not warnings.empty:
        print(f"  IMPORTANT warnings: {len(warnings)}")
        for _, r in warnings.iterrows():
            print(f"    [WARN] {r['check_name']}: {r['detail']}")
    if critical_ok:
        return 0
    else:
        print(f"  CRITICAL failures: {len(errors)}")
        for _, r in errors.iterrows():
            print(f"    [FAIL] {r['check_name']}: {r['detail']}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
