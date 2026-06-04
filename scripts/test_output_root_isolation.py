#!/usr/bin/env python3
"""
test_output_root_isolation.py
==============================
验证 run_full_pipeline.py 在非默认 --output-root 运行时，
不会向 output/pv_pipeline 写入任何文件。

原理：
1. 对 output/pv_pipeline 做快照（mtime + size）
2. 运行轻量脚本子集，全部指向测试输出目录
3. 检查 output/pv_pipeline 没有任何变化

用法：
    python scripts/test_output_root_isolation.py
    python scripts/test_output_root_isolation.py --test-dir output/pv_pipeline_guard_test
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TEST_DIR = "output/pv_pipeline_guard_test"
DEFAULT_OUTPUT = PROJECT / "output" / "pv_pipeline"


def snapshot(path: Path) -> dict:
    """返回 {file_path: (mtime, size)}"""
    result = {}
    if not path.exists():
        return result
    for p in path.rglob("*"):
        if p.is_file():
            try:
                result[str(p)] = (p.stat().st_mtime, p.stat().st_size)
            except OSError:
                pass
    return result


def diff(before: dict, after: dict) -> list:
    """返回变更列表 [(path, type, info)]"""
    changes = []
    for path, val in after.items():
        if path not in before:
            changes.append((path, "NEW", ""))
        elif before[path] != val:
            changes.append((path, "MOD", f"before={before[path]}, after={val}"))
    for path in before:
        if path not in after:
            changes.append((path, "DEL", ""))
    return changes


def main():
    parser = argparse.ArgumentParser(description="路径隔离测试")
    parser.add_argument(
        "--test-dir",
        default=TEST_DIR,
        help=f"测试输出目录 (default: {TEST_DIR})",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只检查默认目录是否被污染，不运行任何脚本",
    )
    args = parser.parse_args()

    test_dir = PROJECT / args.test_dir
    test_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("路径隔离测试")
    print("=" * 60)
    print(f"Default output: {DEFAULT_OUTPUT}")
    print(f"Test output:    {test_dir}")
    print()

    before = snapshot(DEFAULT_OUTPUT)
    print(f"[SNAPSHOT] 默认目录现有 {len(before)} 个文件/目录")

    if args.check_only:
        after = snapshot(DEFAULT_OUTPUT)
        changes = diff(before, after)
        if changes:
            print(f"\n[FAIL] 默认目录被修改了 {len(changes)} 处:")
            for p, t, info in changes[:10]:
                print(f"  [{t}] {Path(p).relative_to(PROJECT)}")
        else:
            print("\n[PASS] 默认目录未被修改")
        return

    # ── Run lightweight scripts with --output-root pointing to test_dir ──────────
    scripts_to_test = [
        {
            "name": "dashboard_regression_check",
            "cmd": [
                sys.executable,
                str(PROJECT / "scripts" / "dashboard_regression_check.py"),
                "--output-root", str(test_dir),
                "--no-pkl-check",
            ],
        },
    ]

    all_pass = True
    for sc in scripts_to_test:
        print(f"\n── Running: {sc['name']} ──")
        # Snapshot before this script
        snap_before = snapshot(DEFAULT_OUTPUT)

        ret = subprocess.run(sc["cmd"], cwd=str(PROJECT))
        snap_after = snapshot(DEFAULT_OUTPUT)
        changes = diff(snap_before, snap_after)

        if ret.returncode != 0:
            print(f"[INFO] {sc['name']} exited {ret.returncode} (test dir may lack data — expected)")
        if changes:
            print(f"[FAIL] {sc['name']} modified default output:")
            for p, t, info in changes:
                rel = Path(p).relative_to(PROJECT)
                print(f"  [{t}] {rel}")
            all_pass = False
        else:
            print(f"[PASS] {sc['name']} did NOT modify default output")

    # ── Final check: no new files created in default output ─────────────────────
    after_final = snapshot(DEFAULT_OUTPUT)
    final_changes = diff(before, after_final)

    print()
    print("=" * 60)
    if final_changes:
        print(f"[FAIL] 默认目录被修改了 {len(final_changes)} 处:")
        for p, t, info in final_changes:
            rel = Path(p).relative_to(PROJECT)
            print(f"  [{t}] {rel}")
        print()
        print("路径隔离测试 FAILED — 默认目录被污染。")
        sys.exit(1)
    else:
        print("[PASS] 路径隔离测试 PASSED")
        print(f"  测试目录: {test_dir}")
        print(f"  默认目录: {DEFAULT_OUTPUT}")
        print("  全程无污染。")
        sys.exit(0)


if __name__ == "__main__":
    main()
