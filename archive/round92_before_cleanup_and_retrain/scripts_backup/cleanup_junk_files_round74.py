#!/usr/bin/env python3
"""
cleanup_junk_files_round74.py
==========================
清理异常残留文件（🍒、__MACOSX、.DS_Store、._* 等）。

默认 dry-run；--apply 时才真正删除。
不清理：.pkl、predictions/、interactive_dashboard/ 当前正式目录、metrics/、configs/、scripts/ 中非临时文件。
"""

import argparse
import os
import re
import shutil
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round74"

# 明确要清理的模式
JUNK_PATTERNS = [
    "__MACOSX",
    ".DS_Store",
    "._*",           # Mac metadata
    "*🍒*",
    "*未命名*",
    "*临时*",
    "*.tmp",
    "*.bak",
]

# 保护路径（不清理）
PROTECTED_PREFIXES = [
    str(PROJECT_ROOT / "output" / "pv_pipeline" / "predictions"),
    str(PROJECT_ROOT / "output" / "pv_pipeline" / "interactive_dashboard"),
    str(PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"),
    str(PROJECT_ROOT / "configs"),
    str(PROJECT_ROOT / "pv_forecasting"),
    str(PROJECT_ROOT / "scripts"),
]


def is_protected(path_str):
    for p in PROTECTED_PREFIXES:
        if path_str.startswith(p):
            return True
    return False


def find_junk_files(root):
    found = []
    for pat in JUNK_PATTERNS:
        if "*" in pat:
            regex = "^" + re.escape(pat).replace(r"\*", ".*") + "$"
            for p in root.rglob("*"):
                if p.is_file() and re.match(regex, p.name):
                    found.append(p)
        else:
            for p in root.rglob(pat):
                if p.is_file():
                    found.append(p)
    # 去重（glob 可能重复匹配）
    seen = set()
    unique = []
    for p in found:
        if str(p) not in seen:
            seen.add(str(p))
            unique.append(p)
    return unique


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    junk = find_junk_files(PROJECT_ROOT)
    rows = []
    for p in junk:
        if is_protected(str(p)):
            action = "PROTECTED_SKIP"
        elif args.apply:
            action = "DELETED"
            p.unlink()
        else:
            action = "TO_DELETE"
        rows.append({
            "path": str(p.relative_to(PROJECT_ROOT)),
            "size_bytes": p.stat().st_size if p.exists() else 0,
            "action": action,
        })

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "round74_junk_cleanup_plan.csv", index=False, encoding="utf-8-sig")
    print(f"[OK] {OUT / 'round74_junk_cleanup_plan.csv'}")

    if args.dry_run:
        print(f"\n[DRY RUN] 发现 {len(junk)} 个异常文件:")
        protected = df[df["action"] == "PROTECTED_SKIP"]
        to_del = df[df["action"] == "TO_DELETE"]
        print(f"  保护跳过: {len(protected)}")
        print(f"  将删除:   {len(to_del)}")
        for _, r in to_del.head(30).iterrows():
            print(f"    {r['path']}")
        if len(to_del) > 30:
            print(f"    ... 还有 {len(to_del)-30} 个")
    elif args.apply:
        deleted = int((df["action"] == "DELETED").sum())
        print(f"[APPLY] 已删除 {deleted} 个异常文件")
        df.to_csv(OUT / "round74_junk_cleanup_apply_log.csv", index=False, encoding="utf-8-sig")
        print(f"[OK] {OUT / 'round74_junk_cleanup_apply_log.csv'}")


if __name__ == "__main__":
    main()
