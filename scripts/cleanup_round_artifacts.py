#!/usr/bin/env python3
"""
Clean up and archive historical round artifacts.
Moves residual round directories to an archive folder without deleting them.

Usage:
    # Dry run (see what would be moved)
    python scripts/cleanup_round_artifacts.py --output-root output/pv_pipeline --mode dry-run

    # Actually archive
    python scripts/cleanup_round_artifacts.py --output-root output/pv_pipeline --mode archive

Modes:
    dry-run  — list items that would be archived, no changes
    archive  — move items to archive directory
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PROTECTED_PATHS = {
    "models",
    "predictions",
    "metrics",
    "tables",
    "interactive_dashboard",
    "validation",
    "docs",
    "manifest.json",
    "archive",
}

PROTECTED_PREFIXES = [
    "archive/",
    "validation/",
    "docs/",
    "models/",
    "predictions/",
    "metrics/",
    "tables/",
    "interactive_dashboard/",
]

RESIDUAL_PATTERNS = [
    "round",
    "baseline",
    "backup",
    "candidate",
    "experiment",
]


def is_protected(path: Path, root: Path) -> bool:
    name = path.name
    if name in PROTECTED_PATHS:
        return True
    for prefix in PROTECTED_PREFIXES:
        try:
            path.relative_to(root / prefix)
            return True
        except ValueError:
            pass
    return False


def is_residual(path: Path) -> bool:
    name = path.name.lower()
    for pat in RESIDUAL_PATTERNS:
        if pat in name:
            return True
    return False


def scan(output_root: Path) -> list[Path]:
    candidates = []
    for child in sorted(output_root.iterdir()):
        if is_protected(child, output_root):
            continue
        if child.is_dir() and is_residual(child):
            candidates.append(child)
        elif child.is_file() and is_residual(child):
            candidates.append(child)
    return candidates


def main():
    parser = argparse.ArgumentParser(description="历史轮次残留物清理与归档")
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

    candidates = scan(output_root)

    print("=" * 60)
    print(f"Round Artifact Cleanup (mode: {args.mode})")
    print(f"Output root: {output_root}")
    print("=" * 60)

    if not candidates:
        print("\n[OK] No residual round artifacts found.")
        sys.exit(0)

    print(f"\nFound {len(candidates)} candidates:\n")
    for p in candidates:
        rel = p.relative_to(output_root)
        if p.is_dir():
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            size_str = _format_size(size)
        else:
            size_str = _format_size(p.stat().st_size)
        print(f"  {rel} ({size_str})")

    if args.mode == "dry-run":
        print(f"\n[OK] Dry run complete. Run with --mode archive to move these.")
        sys.exit(0)

    # Archive
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = output_root / "archive" / f"round93_3_pretrain_cleanup_{ts}"
    archive_dir.mkdir(parents=True, exist_ok=True)

    moved = []
    for p in candidates:
        dest = archive_dir / p.name
        print(f"\nMoving {p.relative_to(output_root)} → {dest.relative_to(output_root)}")
        shutil.move(str(p), str(dest))
        moved.append((p.name, dest.relative_to(output_root)))

    print()
    print("=" * 60)
    print(f"[OK] Archived {len(moved)} items to:")
    print(f"     {archive_dir.relative_to(PROJECT_ROOT)}")
    print("=" * 60)

    # Write archive log
    log_path = archive_dir / "archive_manifest.txt"
    log_lines = [f"Archived at {ts}\n\n"]
    for orig, dest in moved:
        log_lines.append(f"{orig} -> {dest}\n")
    log_path.write_text("".join(log_lines), encoding="utf-8")
    print(f"[OK] Manifest → {log_path.relative_to(PROJECT_ROOT)}")


def _format_size(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


if __name__ == "__main__":
    main()
