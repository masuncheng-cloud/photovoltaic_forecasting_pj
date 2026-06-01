#!/usr/bin/env python3
"""
archive_failed_round_experiments.py
===============================
归档 Round70-72 实验产物，避免污染正式链路。

输出：
    output/pv_pipeline/round73/round73_archive_failed_experiments.csv
"""

import argparse
import os
import shutil
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round73"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    archive_root = PROJECT_ROOT / "archive" / "failed_experiments"
    if args.apply:
        archive_root.mkdir(parents=True, exist_ok=True)

    # 要归档的路径
    to_archive = [
        ("round_output", PROJECT_ROOT / "output" / "pv_pipeline" / "round70"),
        ("round_output", PROJECT_ROOT / "output" / "pv_pipeline" / "round71"),
        ("round_output", PROJECT_ROOT / "output" / "pv_pipeline" / "round72"),
        ("docs", PROJECT_ROOT / "docs" / "Round70_训练样本口径重构与状态专家模型性能提升报告.md"),
        ("docs", PROJECT_ROOT / "docs" / "Round71_季节适配与保守残差提升报告.md"),
        ("docs", PROJECT_ROOT / "docs" / "Round72_重建全历史一致基线并重新训练残差模型报告.md"),
        ("candidates_pkl", PROJECT_ROOT / "output" / "pv_pipeline" / "round70" / "round70_candidates.pkl"),
        ("candidates_pkl", PROJECT_ROOT / "output" / "pv_pipeline" / "round71" / "round71_candidates.pkl"),
        ("candidates_pkl", PROJECT_ROOT / "output" / "pv_pipeline" / "round72" / "round72_residual_candidates.pkl"),
    ]

    rows = []
    for kind, path in to_archive:
        exists = path.exists()
        archived = False
        dest = None
        if exists and args.apply:
            dest = archive_root / path.name
            shutil.copy2(path, dest)
            archived = True
        elif exists and args.dry_run:
            dest = archive_root / path.name
        rows.append({
            "kind": kind, "path": str(path), "exists": exists,
            "archived": archived, "destination": str(dest) if dest else "",
        })

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "round73_archive_failed_experiments.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] {OUT / 'round73_archive_failed_experiments.csv'}")
    if args.dry_run:
        print("[DRY RUN] 以下文件将被归档:")
        for _, r in df[df["exists"]].iterrows():
            print(f"  {r['kind']}: {r['path']} → {r['destination']}")
    elif args.apply:
        print(f"[APPLY] 已归档 {df['archived'].sum()} 个文件到 {archive_root}")
    print(df[df["exists"]].to_string(index=False))


if __name__ == "__main__":
    main()
