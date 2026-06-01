#!/usr/bin/env python3
"""
cleanup_output_pv_pipeline_whitelist.py
=====================================
以白名单方式清理 output/pv_pipeline/，将非白名单目录归档。

白名单目录（KEEP）：
    predictions, metrics, interactive_dashboard, docs, figures,
    figures_dashboard, tables, validation, logs, baselines, backups,
    manifest.json

非白名单：
    - 所有 round* 目录 → 归档
    - archive_before_round36, calibration, diagnostics, cache → 归档
    - interactive_dashboard_round64_candidate → 归档
    - models/ → 归档（已过期）
    - 根目录 .py 脚本 → 归档
    - 垃圾文件(.DS_Store, __MACOSX, ._*, *🍒*) → 直接删除
"""

import argparse
import datetime
import os
import re
import shutil
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = PROJECT_ROOT / "output" / "pv_pipeline"
OUT_VALIDATION = OUT_ROOT / "validation"


# ── 白名单定义 ───────────────────────────────────────────────
KEEP_DIRS = {
    "predictions",
    "metrics",
    "interactive_dashboard",
    "docs",
    "figures",
    "figures_dashboard",
    "tables",
    "validation",
    "logs",
    "baselines",
    "backups",
}

KEEP_FILES = {
    "manifest.json",
}

# 垃圾文件模式（直接删除，不需要归档）
JUNK_PATTERNS = {
    ".DS_Store",
    "__MACOSX",
}
JUNK_GLOB = ["*.tmp", ".*", "*临时*", "*未命名*", "*🍒*"]


def find_junk(root: Path):
    """返回需要直接删除的垃圾文件列表。"""
    junk = []
    for pat in JUNK_GLOB:
        for p in root.rglob(pat):
            if p.is_file():
                junk.append(p)
    # 明确路径
    for name in JUNK_PATTERNS:
        for p in root.rglob(name):
            if p.is_file():
                junk.append(p)
    seen = set()
    unique = []
    for p in junk:
        if str(p) not in seen:
            seen.add(str(p))
            unique.append(p)
    return unique


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--output-root",
        type=str,
        default=str(PROJECT_ROOT / "output" / "pv_pipeline"),
    )
    parser.add_argument(
        "--archive-root",
        type=str,
        default=None,
    )
    args = parser.parse_args()

    output_root = Path(args.output_root)
    archive_root_str = args.archive_root or (
        str(PROJECT_ROOT / "archive" / "old_output_pv_pipeline")
    )
    archive_root = Path(archive_root_str)

    # 生成带时间戳的归档子目录
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_sub = archive_root / ts
    if args.apply:
        archive_root.mkdir(parents=True, exist_ok=True)
        archive_sub.mkdir(parents=True, exist_ok=True)
        root_scripts_dir = archive_sub / "root_scripts"
        root_scripts_dir.mkdir(parents=True, exist_ok=True)
    else:
        root_scripts_dir = archive_sub / "root_scripts"

    OUT_VALIDATION.mkdir(parents=True, exist_ok=True)

    rows = []
    moved_dirs = 0
    moved_scripts = 0
    deleted_junk = 0

    # ── 1. 处理子目录 ─────────────────────────────────────────
    for entry in sorted(output_root.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if name in KEEP_DIRS:
            rows.append({
                "type": "dir", "name": name, "action": "KEEP", "size_mb": None,
                "note": "whitelist",
            })
        elif name.startswith("round") or name in [
            "archive_before_round36", "calibration", "diagnostics",
            "cache", "interactive_dashboard_round64_candidate", "models",
            "round63", "round64", "round66", "round67", "round68",
            "round69", "round70", "round71", "round72", "round73", "round74",
        ]:
            size_mb = round(sum(p.stat().st_size for p in entry.rglob("*") if p.is_file()) / 1e6, 1)
            if args.apply:
                dest = archive_sub / name
                shutil.copytree(entry, dest, dirs_exist_ok=True)
                shutil.rmtree(entry)
            rows.append({
                "type": "dir", "name": name, "action": "ARCHIVE",
                "size_mb": size_mb, "note": f"→ {archive_sub.name}/{name}",
            })
            moved_dirs += 1
        else:
            # 未知目录，打印信息（不自动处理）
            rows.append({
                "type": "dir", "name": name, "action": "UNKNOWN",
                "size_mb": None, "note": "not in whitelist, not auto-archived",
            })

    # ── 2. 处理根目录文件 ────────────────────────────────────
    for entry in sorted(output_root.iterdir()):
        if not entry.is_file():
            continue
        name = entry.name
        if name in KEEP_FILES:
            rows.append({
                "type": "file", "name": name, "action": "KEEP",
                "size_mb": round(entry.stat().st_size / 1e6, 3),
                "note": "whitelist",
            })
        elif name.endswith(".py"):
            size_mb = round(entry.stat().st_size / 1e6, 3)
            if args.apply:
                dest = root_scripts_dir / name
                shutil.copy2(entry, dest)
                entry.unlink()
            rows.append({
                "type": "file", "name": name, "action": "ARCHIVE_SCRIPT",
                "size_mb": size_mb, "note": f"→ {archive_sub.name}/root_scripts/{name}",
            })
            moved_scripts += 1
        else:
            rows.append({
                "type": "file", "name": name, "action": "UNKNOWN_FILE",
                "size_mb": round(entry.stat().st_size / 1e6, 3),
                "note": "not auto-archived",
            })

    # ── 3. 垃圾文件 ─────────────────────────────────────────
    junk_files = find_junk(output_root)
    for p in junk_files:
        size_mb = round(p.stat().st_size / 1e6, 3) if p.exists() else 0
        if args.apply:
            p.unlink()
        rows.append({
            "type": "junk", "name": str(p.relative_to(output_root)),
            "action": "DELETE", "size_mb": size_mb, "note": "junk file",
        })
        deleted_junk += 1

    df = pd.DataFrame(rows)
    plan_path = OUT_VALIDATION / "round75_output_cleanup_plan.csv"
    df.to_csv(plan_path, index=False, encoding="utf-8-sig")
    print(f"[OK] {plan_path}")

    if args.dry_run:
        print(f"\n{'='*60}")
        print(f"DRY RUN — 以下操作将被执行：")
        print(f"  归档目录: {moved_dirs} 个")
        print(f"  归档脚本: {moved_scripts} 个")
        print(f"  删除垃圾: {deleted_junk} 个")
        print(f"  归档位置: {archive_sub}")
        print(f"{'='*60}")
        print("\n目录操作:")
        for _, r in df[df["type"] == "dir"].iterrows():
            print(f"  [{r['action']:15s}] {r['name']}  {r.get('size_mb','') or ''}MB  {r['note']}")
        print("\n根目录脚本:")
        for _, r in df[df["type"] == "file"].iterrows():
            print(f"  [{r['action']:15s}] {r['name']}  {r.get('size_mb','') or ''}MB")
        print("\n垃圾文件:")
        for _, r in df[df["type"] == "junk"].iterrows():
            print(f"  [{r['action']:8s}] {r['name']}")
    elif args.apply:
        apply_log = df.copy()
        apply_log["applied_at"] = datetime.datetime.now().isoformat()
        apply_log.to_csv(OUT_VALIDATION / "round75_output_cleanup_apply_log.csv",
                         index=False, encoding="utf-8-sig")
        print(f"[APPLY] 完成")
        print(f"  归档目录: {moved_dirs} 个 → {archive_sub}")
        print(f"  归档脚本: {moved_scripts} 个")
        print(f"  删除垃圾: {deleted_junk} 个")
        print(f"[OK] {OUT_VALIDATION / 'round75_output_cleanup_apply_log.csv'}")


if __name__ == "__main__":
    main()
