#!/usr/bin/env python3
"""
Clean up and archive redundant output files from historical rounds.
Moves old round metrics files to an archive directory without deleting them.

Usage:
    # Dry run (see what would be moved)
    python scripts/cleanup_redundant_outputs.py --output-root output/pv_pipeline --mode dry-run

    # Actually archive
    python scripts/cleanup_redundant_outputs.py --output-root output/pv_pipeline --mode archive

Modes:
    dry-run  — list items that would be archived, no changes
    archive  — move items to archive directory
"""

from __future__ import annotations

import argparse
import fnmatch
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Patterns that match redundant historical files to archive.
# These are relative to output_root.
ARCHIVE_PATTERNS = [
    "metrics/round*.csv",
    "metrics/*_round*.csv",
    "metrics/*before_round*.csv",
    "metrics/*candidate*.csv",
    "metrics/*rollback*.csv",
    "metrics/*compare*.csv",
    "metrics/*drift*.csv",
    "metrics/*pretrain_audit*.csv",
    "metrics/*dashboard_update_stamp_check*.csv",
    "metrics/round*_dashboard_regression_check.csv",
    "round*/**",
    "archive_before_round*/**",
    "interactive_dashboard_round*_candidate/**",
    "baselines/**",
    "backups/**",
]

# Top-level directories that are protected and must never be moved.
PROTECTED_TOP = {
    "models",
    "predictions",
    "tables",
    "metrics",
    "interactive_dashboard",
    "validation",
    "docs",
    "figures",
    "logs",
    "archive",
    "manifest.json",
}


def rel_match(rel: str, pattern: str) -> bool:
    """Match a relative path against a fnmatch pattern."""
    return fnmatch.fnmatch(rel, pattern)


def collect_targets(output_root: Path) -> list[Path]:
    """Find all redundant files under output_root matching ARCHIVE_PATTERNS."""
    targets: list[Path] = []
    for path in output_root.rglob("*"):
        if not path.exists() or not path.is_file():
            continue
        rel = path.relative_to(output_root).as_posix()
        # Skip archive directory itself
        if rel.startswith("archive/") or rel.startswith("archive\\"):
            continue
        if path.is_dir() and path.name == "archive":
            continue
        if any(rel_match(rel, pat) for pat in ARCHIVE_PATTERNS):
            targets.append(path)
    return sorted(set(targets))


def main():
    parser = argparse.ArgumentParser(description="清理历史轮次冗余输出文件并归档")
    parser.add_argument(
        "--output-root",
        type=str,
        default="output/pv_pipeline",
        help="Output root (default: output/pv_pipeline)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["dry-run", "archive"],
        default="dry-run",
        help="'dry-run' to list only, 'archive' to move (default: dry-run)",
    )
    args = parser.parse_args()

    output_root = PROJECT_ROOT / args.output_root
    if not output_root.exists():
        print(f"[FAIL] Output root does not exist: {output_root}")
        sys.exit(1)

    targets = collect_targets(output_root)

    print("=" * 60)
    print(f"Redundant Output Cleanup (mode: {args.mode})")
    print(f"Output root: {output_root}")
    print(f"Patterns: {ARCHIVE_PATTERNS}")
    print("=" * 60)

    if not targets:
        print("\n[OK] No redundant output files found.")
        sys.exit(0)

    print(f"\nFound {len(targets)} candidates to archive:\n")
    for p in targets:
        print(f"  {p.relative_to(output_root)}")

    if args.mode == "dry-run":
        print(f"\n[DRY-RUN] {len(targets)} files would be archived. Run with --mode archive to proceed.")
        sys.exit(0)

    # Archive
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_root = output_root / "archive" / f"round93_4_cleanup_{stamp}"
    archive_root.mkdir(parents=True, exist_ok=True)

    moved = []
    for p in targets:
        rel = p.relative_to(output_root)
        dst = archive_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dst))
        moved.append((str(rel), str(dst.relative_to(output_root))))

    print()
    print("=" * 60)
    print(f"[OK] Archived {len(moved)} files to:")
    print(f"     {archive_root.relative_to(PROJECT_ROOT)}")
    print("=" * 60)

    # Write manifest
    log_path = archive_root / "archive_manifest.txt"
    lines = [f"Archived at {stamp}\n\n"]
    for orig, dest in moved:
        lines.append(f"{orig} -> {dest}\n")
    log_path.write_text("".join(lines), encoding="utf-8")
    print(f"[OK] Manifest -> {log_path.relative_to(PROJECT_ROOT)}")

    # Report sizes
    total_size = sum(
        f.stat().st_size for f in archive_root.rglob("*") if f.is_file()
    )
    print(f"Total archived size: {_format_size(total_size)}")


def _format_size(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


if __name__ == "__main__":
    main()
