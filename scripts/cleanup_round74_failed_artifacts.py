#!/usr/bin/env python3
"""
cleanup_round74_failed_artifacts.py
=================================
归档并清理 Round70-Round73 失败实验产物。

保留：predictions/, interactive_dashboard/, metrics/, manifest.json, baselines/round61/, Round68_*.md, Round69_*.md
归档：round70-73 输出目录及报告
"""

import argparse
import os
import shutil
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round74"
ARCHIVE = PROJECT_ROOT / "archive" / "failed_experiments_round74"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    if args.apply:
        ARCHIVE.mkdir(parents=True, exist_ok=True)

    # 要归档的项目
    to_archive = [
        # 目录
        ("round_dir", PROJECT_ROOT / "output" / "pv_pipeline" / "round70"),
        ("round_dir", PROJECT_ROOT / "output" / "pv_pipeline" / "round71"),
        ("round_dir", PROJECT_ROOT / "output" / "pv_pipeline" / "round72"),
        ("round_dir", PROJECT_ROOT / "output" / "pv_pipeline" / "round73"),
        # 报告
        ("doc", PROJECT_ROOT / "docs" / "Round70_训练样本口径重构与状态专家模型性能提升报告.md"),
        ("doc", PROJECT_ROOT / "docs" / "Round71_季节适配与保守残差提升报告.md"),
        ("doc", PROJECT_ROOT / "docs" / "Round72_重建全历史一致基线并重新训练残差模型报告.md"),
        ("doc", PROJECT_ROOT / "docs" / "Round73_回退最优版本并重构训练框架提升报告.md"),
        # 候选 pkl（round73目录下）
        ("cand_pkl", PROJECT_ROOT / "output" / "pv_pipeline" / "round73" / "round73_candidates.pkl"),
        # archive 中已有的 round70-72 目录，也移到 round74 统一归档
        ("prev_archive", PROJECT_ROOT / "archive" / "failed_experiments" / "round70"),
        ("prev_archive", PROJECT_ROOT / "archive" / "failed_experiments" / "round71"),
        ("prev_archive", PROJECT_ROOT / "archive" / "failed_experiments" / "round72"),
    ]

    rows = []
    for kind, path in to_archive:
        exists = path.exists()
        archived = False
        dest = ""
        action = "skip"
        if exists and args.apply:
            dest_name = path.name
            dest = ARCHIVE / dest_name
            if path.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(path, dest)
            else:
                shutil.copy2(path, dest)
            action = "archive_and_delete"
            archived = True
        elif exists and args.dry_run:
            dest = ARCHIVE / path.name
            action = "archive_and_delete"
        elif not exists:
            action = "not_found"
        rows.append({
            "kind": kind, "path": str(path), "exists": exists,
            "action": action, "destination": str(dest) if dest else "",
        })

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "round74_cleanup_plan.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] {OUT / 'round74_cleanup_plan.csv'}")

    if args.dry_run:
        print(f"\n[DRY RUN] 以下将被归档并删除:")
        for _, r in df[df["exists"]].iterrows():
            print(f"  [{r['kind']}] {r['path']}")
            print(f"    → {r['destination']}")
        print(f"\n总计: {df['exists'].sum()} 项")
    elif args.apply:
        deleted = 0
        for _, r in df[df["archived"] == True].iterrows():
            path = Path(r["path"])
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                deleted += 1
        print(f"[APPLY] 已归档并删除 {deleted} 项到 {ARCHIVE}")
        df.to_csv(OUT / "round74_cleanup_apply_log.csv", index=False, encoding="utf-8-sig")
        print(f"[OK] {OUT / 'round74_cleanup_apply_log.csv'}")
    print(df[df["exists"]].to_string(index=False))


if __name__ == "__main__":
    main()
