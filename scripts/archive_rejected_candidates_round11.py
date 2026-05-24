#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round11：将已被拒绝的候选产物归档到 archive_round11/rejected_candidates/"""
from __future__ import annotations

from pathlib import Path
import json
import shutil
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output" / "pv_pipeline"
METRICS = OUT / "metrics"
TABLES = OUT / "tables"
MODELS = TABLES.parent / "models"
ARCHIVE = OUT / "archive_round11" / "rejected_candidates"
ARCHIVE.mkdir(parents=True, exist_ok=True)

REJECTED_PATTERNS = {
    "midday_specialist_round9": [
        "distributed_predictions_midday_specialist_round9",
        "distributed_model_midday_specialist_round9",
        "round9_specialist",
    ],
}


def _move_file(path: Path, rows: list):
    if not path.exists() or not path.is_file():
        return
    rel_parent = path.parent.relative_to(OUT)
    dest_dir = ARCHIVE / rel_parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    if dest.exists():
        dest.unlink()
    shutil.move(str(path), str(dest))
    rows.append({
        "original_path": str(path.relative_to(PROJECT_ROOT)),
        "archived_path": str(dest.relative_to(PROJECT_ROOT)),
        "size_mb": round(dest.stat().st_size / 1024 / 1024, 3),
    })


def main():
    rows = []
    for decision_path in sorted(METRICS.glob("round10_candidate_decision_*.json")):
        data = json.loads(decision_path.read_text(encoding="utf-8"))
        name = data.get("candidate_name", "")
        if data.get("accepted", False):
            continue

        patterns = REJECTED_PATTERNS.get(name, [name])

        dest_decision_dir = ARCHIVE / "metrics"
        dest_decision_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(decision_path, dest_decision_dir / decision_path.name)

        for base in [TABLES, METRICS]:
            if not base.exists():
                continue
            for path in base.iterdir():
                if not path.is_file():
                    continue
                if any(p in path.name for p in patterns):
                    _move_file(path, rows)

        if MODELS.exists():
            for path in MODELS.iterdir():
                if not path.is_file():
                    continue
                if any(p in path.name for p in patterns):
                    _move_file(path, rows)

    manifest = pd.DataFrame(rows)
    manifest_path = ARCHIVE / "archive_rejected_candidates_manifest.csv"
    manifest.to_csv(manifest_path, index=False, encoding="utf-8-sig")

    print(f"已归档文件数: {len(rows)}")
    if not manifest.empty:
        print(manifest.to_string(index=False))
    else:
        print("无文件需要归档。")


if __name__ == "__main__":
    main()
