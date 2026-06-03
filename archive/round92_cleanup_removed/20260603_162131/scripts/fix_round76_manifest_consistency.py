#!/usr/bin/env python3
"""
fix_round76_manifest_consistency.py
================================
统一 manifest.json 的版本口径，清理历史 round hash 记录。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "output" / "pv_pipeline"
MANIFEST = PIPELINE / "manifest.json"
FINAL_FULL = PIPELINE / "predictions" / "distributed_predictions_final_full.pkl"
FINAL_EVAL = PIPELINE / "predictions" / "distributed_predictions_final_eval.pkl"
DASHBOARD_META = PIPELINE / "interactive_dashboard" / "metadata.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    for p in [MANIFEST, FINAL_FULL, FINAL_EVAL, DASHBOARD_META]:
        if not p.exists():
            raise FileNotFoundError(p)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dashboard_meta = json.loads(DASHBOARD_META.read_text(encoding="utf-8"))

    # 修正核心口径
    manifest["final_round"] = "Round68 final"
    manifest["source_round"] = manifest.get("source_round") or "Round68 lgb_safe_blend"
    manifest["prediction_column"] = "power_pred_final"
    manifest["actual_column"] = "power_mw"
    manifest["exclude_future"] = True
    manifest["official_final"] = True

    # 明确正式预测文件路径
    manifest["final_prediction_files"] = {
        "full": str(FINAL_FULL.relative_to(ROOT)),
        "eval": str(FINAL_EVAL.relative_to(ROOT)),
    }

    # 明确 dashboard 口径
    manifest["dashboard"] = {
        "path": "stages/05_visualization/interactive_forecast_dashboard.html",
        "data_root": "output/pv_pipeline/interactive_dashboard",
        "metadata": "output/pv_pipeline/interactive_dashboard/metadata.json",
        "exclude_future": True,
        "round": dashboard_meta.get("round", "Round68 final"),
        "prediction_column": dashboard_meta.get("prediction_column", "power_pred_final"),
    }

    # 更新 artifact 哈希
    manifest["artifact_hashes"] = {
        "final_full_pkl": sha256_file(FINAL_FULL),
        "final_eval_pkl": sha256_file(FINAL_EVAL),
        "dashboard_metadata_json": sha256_file(DASHBOARD_META),
    }
    manifest["full_sha256"] = manifest["artifact_hashes"]["final_full_pkl"]
    manifest["eval_sha256"] = manifest["artifact_hashes"]["final_eval_pkl"]

    # 清理历史 round hash（避免把临时实验误认为交付物）
    for key in [
        "round36", "round39", "round46",
        "round58", "round59", "round60", "round61",
        "round63", "round64", "round67", "round68",
        "round69", "round70", "round71", "round72", "round73",
    ]:
        manifest.pop(f"{key}_hashes", None)

    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("[OK] manifest fixed:", MANIFEST)
    print("[OK] final_round =", manifest["final_round"])
    print("[OK] prediction_column =", manifest["prediction_column"])
    print("[OK] final_full sha256 =", manifest["artifact_hashes"]["final_full_pkl"][:16] + "...")


if __name__ == "__main__":
    main()
