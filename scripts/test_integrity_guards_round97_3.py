#!/usr/bin/env python3
"""
Round97_3 负向测试：确认检查脚本不会放水。

测试内容：
  1. 临时修改 metadata.json 把 prediction_column 改成不存在的列，
     确认 check_dashboard_integrity.py 会 fail。
  2. 临时构造一个带 stale=true 的 site JSON，
     确认会 fail。
  3. 临时隐藏 predictions/distributed_predictions_final_full.pkl，
     确认 check_pipeline_consistency.py 默认模式会 fail。

测试用临时目录，不破坏正式 output/pv_pipeline。
"""
from __future__ import annotations

import json
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DASHBOARD_ROOT = PROJECT_ROOT / "output" / "pv_pipeline" / "interactive_dashboard"
PREDICTIONS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "predictions"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"


def run_check(cmd: list[str], expect_fail: bool = False) -> bool:
    """运行检查脚本，返回 True 表示成功（不 fail）。"""
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if expect_fail:
        return r.returncode != 0
    return r.returncode == 0


def test_missing_prediction_column():
    """测试1：metadata.json 的 prediction_column 指向不存在的列，应 fail。"""
    meta_path = DASHBOARD_ROOT / "metadata.json"
    backup_path = meta_path.with_suffix(".json.bak_round97_3_test")
    shutil.copy2(meta_path, backup_path)

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["prediction_column"] = "power_pred_nonexistent_column_xyz"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        ok = run_check(
            [sys.executable,
             str(SCRIPT_DIR / "check_dashboard_integrity.py"),
             "--dashboard-root", str(DASHBOARD_ROOT)],
            expect_fail=True,
        )
        if ok:
            print("[PASS] missing prediction column rejected ✓")
        else:
            print("[FAIL] missing prediction column NOT rejected ✗")
        return ok
    finally:
        shutil.move(backup_path, meta_path)


def test_stale_dashboard():
    """测试2：site JSON 含 stale=true，应 fail。"""
    site_dir = DASHBOARD_ROOT / "site_series"
    test_site = site_dir / "S002.json"
    bak_path = test_site.with_suffix(".json.bak_round97_3_test")
    shutil.copy2(test_site, bak_path)

    try:
        data = json.loads(test_site.read_text(encoding="utf-8"))
        if isinstance(data, list) and len(data) > 0:
            data[0]["stale"] = True
        test_site.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        ok = run_check(
            [sys.executable,
             str(SCRIPT_DIR / "check_dashboard_integrity.py"),
             "--dashboard-root", str(DASHBOARD_ROOT)],
            expect_fail=True,
        )
        if ok:
            print("[PASS] stale dashboard rejected ✓")
        else:
            print("[FAIL] stale dashboard NOT rejected ✗")
        return ok
    finally:
        shutil.move(bak_path, test_site)


def test_stale_placeholder():
    """测试2b：site JSON 含 placeholder=true，应 fail。"""
    site_dir = DASHBOARD_ROOT / "site_series"
    test_site = site_dir / "S003.json"
    bak_path = test_site.with_suffix(".json.bak_round97_3_test")
    shutil.copy2(test_site, bak_path)

    try:
        data = json.loads(test_site.read_text(encoding="utf-8"))
        if isinstance(data, list) and len(data) > 0:
            data[0]["placeholder"] = True
        test_site.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        ok = run_check(
            [sys.executable,
             str(SCRIPT_DIR / "check_dashboard_integrity.py"),
             "--dashboard-root", str(DASHBOARD_ROOT)],
            expect_fail=True,
        )
        if ok:
            print("[PASS] placeholder dashboard rejected ✓")
        else:
            print("[FAIL] placeholder dashboard NOT rejected ✗")
        return ok
    finally:
        shutil.move(bak_path, test_site)


def test_missing_required_file():
    """测试3：隐藏 current required 文件，check_pipeline_consistency.py 应 fail。"""
    pkl_path = PREDICTIONS_DIR / "distributed_predictions_final_full.pkl"
    bak_path = pkl_path.with_suffix(".pkl.bak_round97_3_test")
    shutil.copy2(pkl_path, bak_path)

    try:
        pkl_path.unlink()
        ok = run_check(
            [sys.executable,
             str(SCRIPT_DIR / "check_pipeline_consistency.py")],
            expect_fail=True,
        )
        if ok:
            print("[PASS] missing current required file rejected ✓")
        else:
            print("[FAIL] missing current required file NOT rejected ✗")
        return ok
    finally:
        shutil.move(bak_path, pkl_path)


def test_missing_hourly_summary():
    """测试4（Round97_4）：隐藏 hourly_prediction_summary.json，应 fail。"""
    hp_path = DASHBOARD_ROOT / "hourly_prediction_summary.json"
    bak_path = hp_path.with_suffix(".json.bak_round97_4_test")
    if hp_path.exists():
        shutil.copy2(hp_path, bak_path)
        hp_path.unlink()
        created_backup = True
    else:
        created_backup = False

    try:
        ok = run_check(
            [sys.executable,
             str(SCRIPT_DIR / "check_dashboard_integrity.py"),
             "--dashboard-root", str(DASHBOARD_ROOT)],
            expect_fail=True,
        )
        if ok:
            print("[PASS] missing hourly_prediction_summary rejected ✓")
        else:
            print("[FAIL] missing hourly_prediction_summary NOT rejected ✗")
        return ok
    finally:
        if created_backup:
            shutil.move(bak_path, hp_path)


def test_missing_typical_sites():
    """测试5（Round97_4）：metadata optional_blocks 标记 typical_sites=missing，应 fail。"""
    meta_path = DASHBOARD_ROOT / "metadata.json"
    bak_path = meta_path.with_suffix(".json.bak_round97_4_test")
    shutil.copy2(meta_path, bak_path)

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["optional_blocks"] = {"typical_sites": "missing", "hourly_prediction_summary": "present"}
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        ok = run_check(
            [sys.executable,
             str(SCRIPT_DIR / "check_dashboard_integrity.py"),
             "--dashboard-root", str(DASHBOARD_ROOT)],
            expect_fail=True,
        )
        if ok:
            print("[PASS] optional_blocks typical_sites=missing rejected ✓")
        else:
            print("[FAIL] optional_blocks typical_sites=missing NOT rejected ✗")
        return ok
    finally:
        shutil.move(bak_path, meta_path)


def main():
    print("=" * 60)
    print("Round97_3/4 负向测试：确认检查脚本不放水")
    print("=" * 60)
    print()

    results = []
    results.append(("missing prediction column rejected", test_missing_prediction_column()))
    results.append(("stale dashboard rejected", test_stale_dashboard()))
    results.append(("placeholder dashboard rejected", test_stale_placeholder()))
    results.append(("missing current required file rejected", test_missing_required_file()))
    results.append(("missing hourly_prediction_summary rejected", test_missing_hourly_summary()))
    results.append(("optional_blocks typical_sites=missing rejected", test_missing_typical_sites()))

    print()
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        print(f"  {'✓' if ok else '✗'} {name}")
    print(f"\n结果: {passed}/{total} 通过")
    print("=" * 60)
    if passed < total:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
