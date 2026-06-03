#!/usr/bin/env python3
"""
cleanup_round_experiment_artifacts.py
================================
清理实验过程中产生的临时文件。

用法：
  python scripts/cleanup_round_experiment_artifacts.py --dry-run  # 查看但不删除
  python scripts/cleanup_round_experiment_artifacts.py --apply     # 执行删除

严禁删除的文件/目录：
  - output/pv_pipeline/baselines/round61/
  - docs/Round61_稳定基线说明.md
  - docs/Round61_城市总量校准与站点稳定性保护报告.md
  - docs/Round63_离线分场景残差模型实验报告.md
  - docs/Round64_安全残差融合与训练链路收口报告.md
  - 所有 *.pkl 模型文件
  - 所有 roundNN/*.pkl 预测文件
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

# Patterns that are ALWAYS protected (never delete)
PROTECTED_PATTERNS = [
    "baselines/round61/",
    "Round61_稳定基线说明",
    "Round61_城市总量校准与站点稳定性保护报告",
    "Round63_离线分场景残差模型实验报告",
    "Round64_安全残差融合与训练链路收口报告",
]

# Patterns to CLEAN (temporary artifacts)
CLEAN_PATTERNS = [
    "*.tmp",
    "*_tmp*",
    "docs/*草稿*",
    "docs/*临时*",
    "docs/*draft*",
    "docs/*temp*",
]

# Directories to check for cleanup candidates
CHECK_DIRS = [
    ROOT / "output/pv_pipeline",
]


def is_protected(path_str):
    for pat in PROTECTED_PATTERNS:
        if pat in path_str:
            return True
    return False


def find_cleanup_candidates(dry_run=True):
    """Find files matching CLEAN_PATTERNS but NOT in PROTECTED_PATTERNS."""
    candidates = []
    protected = []
    for check_dir in CHECK_DIRS:
        if not check_dir.exists():
            continue
        for p in check_dir.rglob("*"):
            if not p.is_file():
                continue
            rel = str(p.relative_to(ROOT))
            # Skip pkl/joblib/model files
            if any(rel.endswith(ext) for ext in [".pkl", ".joblib", ".parquet", ".npy", ".npz", ".model", ".pth", ".pt"]):
                continue
            # Check if protected
            if is_protected(rel):
                protected.append(rel)
                continue
            # Check if matches cleanup patterns
            for pat in CLEAN_PATTERNS:
                import fnmatch
                if fnmatch.fnmatch(p.name, pat) or fnmatch.fnmatch(rel, pat):
                    candidates.append(rel)
                    break
    return sorted(candidates), sorted(protected)


def main():
    dry_run = "--dry-run" in sys.argv
    apply = "--apply" in sys.argv

    if not dry_run and not apply:
        print("Usage:")
        print("  python cleanup_round_experiment_artifacts.py --dry-run  # 查看")
        print("  python cleanup_round_experiment_artifacts.py --apply     # 删除")
        sys.exit(1)

    candidates, protected = find_cleanup_candidates()
    protected_not_cleaned = [p for p in protected]

    if dry_run:
        print("=" * 60)
        print("Dry-run: 以下文件将被删除（如果用 --apply）")
        print("=" * 60)
        if candidates:
            for p in candidates:
                print(f"  DELETE: {p}")
        else:
            print("  (无符合条件的文件)")
        print()
        print("以下文件被保护，不会删除：")
        for p in protected_not_cleaned:
            print(f"  PROTECTED: {p}")
    elif apply:
        print("=" * 60)
        print("执行清理...")
        print("=" * 60)
        if not candidates:
            print("无文件可删除")
        for p in candidates:
            fp = ROOT / p
            try:
                fp.unlink()
                print(f"  DELETED: {p}")
            except Exception as e:
                print(f"  FAILED: {p} ({e})")
        print(f"\n共删除 {sum(1 for p in candidates if not (ROOT/p).exists())}/{len(candidates)} 个文件")


if __name__ == "__main__":
    main()
