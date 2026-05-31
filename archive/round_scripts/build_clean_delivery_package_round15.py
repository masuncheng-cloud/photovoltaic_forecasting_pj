#!/usr/bin/env python3
"""
Step 4: Build Clean Delivery Package (Round15)
==============================================
构建干净的交付压缩包，排除所有非交付杂项。

输出：
    dist/photovoltaic_forecasting_pj_round15_delivery.zip
    dist/photovoltaic_forecasting_pj_round15_delivery_manifest.csv

执行：
    python scripts/build_clean_delivery_package_round15.py
"""

import csv
import hashlib
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"
ZIP_NAME = "photovoltaic_forecasting_pj_round15_delivery.zip"
ZIP_PATH = DIST_DIR / ZIP_NAME
MANIFEST_PATH = DIST_DIR / "photovoltaic_forecasting_pj_round15_delivery_manifest.csv"

# Files/dirs to exclude from the zip
EXCLUDE_PATTERNS = [
    ".git/",
    "__MACOSX/",
    ".DS_Store",
    "*.pyc",
    "__pycache__/",
    "catboost_info/",
    "auto_push_test.txt",
    "test_auto_push.txt",
    "auto_sync.log",
    "auto_sync.py",
]
# Glob patterns for files (not dirs)
EXCLUDE_FILE_PATTERNS = [
    "auto_push_test.txt",
    "test_auto_push.txt",
    "auto_sync.log",
]

# Explicit include paths (relative to PROJECT_ROOT)
# These are always included if they exist
ALWAYS_INCLUDE = [
    # Project root
    "README.md",
    "CHANGELOG.md",
    "requirements.txt",
    # Config dirs
    "configs/",
    "config/",
    # Source dirs
    "src/",
    "stages/",
    "scripts/",
    "data/",
    # Output
    "output/pv_pipeline/tables/",
    "output/pv_pipeline/metrics/",
    "output/pv_pipeline/models/",
    "output/pv_pipeline/interactive_dashboard/",
    "output/pv_pipeline/docs/",
    "output/pv_pipeline/archive_round14/",
    "output/pv_pipeline/archive_round15/",
    "output/pv_pipeline/verified_backup_round14/",
    # Docs
    "docs/训练过程与结果严谨性验证报告.md",
    "光伏功率预测项目.md",
    # Task book
    "任务书-2026年国网江苏省电力有限公司面向生产一线的科技项目包（连云港公司）.doc",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_excluded(name: str) -> bool:
    """Check if a zip entry name should be excluded."""
    for pat in EXCLUDE_PATTERNS:
        if pat.endswith("/"):
            # Directory pattern
            if name.startswith(pat) or "/" + pat in name or name == pat.rstrip("/"):
                return True
        else:
            # File pattern
            if name == pat or name.endswith(pat):
                return True
    for fn in EXCLUDE_FILE_PATTERNS:
        if name == fn:
            return True
    return False


def should_include(path: Path, rel: str) -> bool:
    """Determine if a file should be included in the zip."""
    # Always exclude patterns
    if is_excluded(rel):
        return False
    # Explicit includes
    for inc in ALWAYS_INCLUDE:
        if inc.endswith("/"):
            # Directory - include if path is inside it
            if str(rel).startswith(inc.rstrip("/") + "/") or rel.startswith(inc):
                return True
        else:
            # File - exact match
            if rel == inc or path.name == inc:
                return True
    return False


def build_zip():
    manifest_rows = []
    included_count = 0
    excluded_count = 0

    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # Remove old zip if exists
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
        print(f"[REMOVE] Old zip: {ZIP_PATH}")

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for arc_name, src_path, reason in collect_files():
            if reason == "included":
                zf.write(src_path, arc_name)
                included_count += 1
            manifest_rows.append({
                "path": arc_name,
                "size_bytes": src_path.stat().st_size if src_path.exists() else 0,
                "sha256": sha256(src_path) if src_path.exists() else "",
                "included": reason == "included",
                "reason": reason,
            })

    # Write manifest
    with open(MANIFEST_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["path", "size_bytes", "sha256", "included", "reason"])
        writer.writeheader()
        writer.writerows(manifest_rows)

    zip_size = ZIP_PATH.stat().st_size
    print(f"\n=== Build Summary ===")
    print(f"  Included: {included_count} files")
    print(f"  Total entries: {len(manifest_rows)}")
    print(f"  Zip size: {zip_size / 1024 / 1024:.1f} MB")
    print(f"  Zip: {ZIP_PATH}")
    print(f"  Manifest: {MANIFEST_PATH}")

    # Self-check: verify no bad files in zip
    print(f"\n=== Self-check ===")
    bad_in_zip = []
    with zipfile.ZipFile(ZIP_PATH) as zf:
        for name in zf.namelist():
            if is_excluded(name):
                bad_in_zip.append(name)
    if bad_in_zip:
        print(f"[FAIL] Zip contains excluded files:")
        for n in bad_in_zip[:10]:
            print(f"    {n}")
        raise RuntimeError("Zip contains excluded files")
    else:
        print(f"[OK] Zip is clean — no .git/__MACOSX/auto_push/test files found")

    return included_count


def collect_files():
    """Walk the project and yield (arc_name, src_path, reason) tuples."""
    exclude_dirs = {".git", "__MACOSX", "__pycache__", "catboost_info", ".pytest_cache"}

    for root, dirs, files in PROJECT_ROOT.walk():
        # Prune excluded dirs
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        for fname in files:
            # Skip bad files
            if fname in {".DS_Store"} or fname.endswith(".pyc"):
                continue
            if fname in EXCLUDE_FILE_PATTERNS:
                continue

            src = root / fname
            rel = str(src.relative_to(PROJECT_ROOT))

            # Include if under a tracked directory
            if should_include(src, rel):
                yield rel, src, "included"
            else:
                # Check if it's a tracked dir/file that we want
                if is_tracked(rel):
                    yield rel, src, "included"
                else:
                    yield rel, src, "excluded_not_tracked"


def is_tracked(rel: str) -> bool:
    """Check if a path is a tracked project file (not a temp/temp file)."""
    # Any file under key project dirs is tracked
    for prefix in ["configs/", "config/", "src/", "stages/", "scripts/", "data/",
                    "output/", "docs/", "docs"]:
        if rel.startswith(prefix) or rel.startswith("docs/") and not rel.startswith("docs/Round"):
            # Special case: docs/Round* are excluded
            if rel.startswith("docs/Round"):
                return False
            return True
    # Top-level docs
    if rel.startswith("docs/"):
        if any(rel.startswith(f"docs/{x}") for x in ["训练过程", "光伏功率"]):
            return True
        return False
    # Task book
    if "任务书" in rel:
        return True
    # Markdown files in root
    if rel.endswith(".md") and rel in {"README.md", "CHANGELOG.md", "光伏功率预测项目.md"}:
        return True
    if rel == "requirements.txt":
        return True
    return False


if __name__ == "__main__":
    build_zip()
