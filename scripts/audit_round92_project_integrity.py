#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pv_pipeline"


REQUIRED_FILES = [
    "README.md",
    "requirements.txt",
    "configs/pipeline.yaml",
    "scripts/run_full_pipeline.py",
    "scripts/common_paths.py",
    "scripts/metrics_common.py",
    "scripts/post_training_finalize_outputs.py",
    "scripts/posttrain_validation.py",
    "scripts/check_pipeline_consistency.py",
    "scripts/check_dashboard_prediction_values.py",
    "scripts/check_no_future_in_outputs.py",
    "scripts/export_interactive_dashboard_data.py",
    "stages/01_data/build_site_master.py",
    "stages/01_data/prepare_meteo_and_power.py",
    "stages/02_irradiance/train_inverse_model.py",
    "stages/02_irradiance/train_irradiance_blend.py",
    "stages/03_power/train_distributed_model_v159.py",
    "stages/04_evaluation/evaluate_layers.py",
    "stages/05_visualization/interactive_forecast_dashboard.html",
]

REQUIRED_OUTPUTS_AFTER_TRAIN = [
    "predictions/distributed_predictions_final_full.pkl",
    "predictions/distributed_predictions_final_eval.pkl",
    "metrics/hourly_nrmse_consistent.csv",
    "metrics/site_metrics_consistent.csv",
    "interactive_dashboard/index.json",
    "interactive_dashboard/metadata.json",
    "interactive_dashboard/city_series.json",
    "interactive_dashboard/full_history_coverage_check.json",
    "manifest.json",
]

FORBIDDEN_MAIN_REFERENCES = [
    "train_round63",
    "train_round64",
    "train_round67",
    "train_round70",
    "train_round71",
    "train_round72",
    "train_round73",
    "apply_round59",
    "apply_round60",
    "select_round64",
    "select_round71",
]


def exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def main():
    report = {
        "status": "PASS",
        "missing_required_files": [],
        "missing_outputs_after_train": [],
        "main_entry": "scripts/run_full_pipeline.py",
        "final_prediction_column_expected": "power_pred_final",
        "forbidden_main_references": [],
        "notes": [],
    }

    for rel in REQUIRED_FILES:
        if not exists(rel):
            report["missing_required_files"].append(rel)

    if report["missing_required_files"]:
        report["status"] = "FAIL"

    run_full = ROOT / "scripts" / "run_full_pipeline.py"
    run_text = read_text(run_full)
    for bad in FORBIDDEN_MAIN_REFERENCES:
        if bad in run_text:
            report["forbidden_main_references"].append(bad)

    if report["forbidden_main_references"]:
        report["status"] = "WARN"

    if OUT.exists():
        for rel in REQUIRED_OUTPUTS_AFTER_TRAIN:
            if not (OUT / rel).exists():
                report["missing_outputs_after_train"].append(rel)
    else:
        report["notes"].append("output/pv_pipeline does not exist yet; this is acceptable before full retrain.")

    scripts = sorted(p.name for p in (ROOT / "scripts").glob("*.py"))
    report["script_count"] = len(scripts)
    report["round_script_count"] = len([s for s in scripts if "round" in s.lower()])
    report["round_scripts"] = [s for s in scripts if "round" in s.lower()]

    out_path = OUT / "validation" / "round92_project_integrity_audit.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
