#!/usr/bin/env python3
"""
Round98_1 完整性守卫负向测试。
测试以下内容：

1. 构造一个 LFS 指针 pkl，确认 is_lfs_pointer() 返回 True。
2. check_dashboard_integrity.py 遇到 LFS 指针时快速 fail，不超时。
3. check_pipeline_consistency.py --stage pretrain 遇到旧 LFS 指针不 fail。
4. check_pipeline_consistency.py --stage posttrain 遇到 LFS 指针必须 fail。
5. run_full_pipeline.py --dry-run 明确显示 pretrain/posttrain 两套检查。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def test_is_lfs_pointer():
    """测试 1: is_lfs_pointer() 能正确识别 Git LFS 指针"""
    print()
    print("=" * 60)
    print("测试 1: is_lfs_pointer() 识别 Git LFS 指针")
    print("=" * 60)

    from pv_forecasting.core.file_checks import is_lfs_pointer, describe_file_state

    # 创建临时 LFS 指针文件
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
        lfs_content = b"version https://git-lfs.github.com/spec/v1\noid sha256:abc123\nsize 12345\n"
        f.write(lfs_content)
        lfs_path = f.name

    # 创建临时真实文件（大于 1024 bytes）
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
        f.write(b"\x00" * 2048)
        real_path = f.name

    # 创建临时正常小文件
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
        f.write(b"pickle data content here")
        small_path = f.name

    # 创建临时目录（模拟不存在的文件）
    fake_path = "/tmp/this_file_does_not_exist_123456.pkl"

    try:
        assert is_lfs_pointer(lfs_path) is True, "LFS 指针文件应返回 True"
        print(f"  PASS: LFS 指针文件 → {is_lfs_pointer(lfs_path)}")

        assert is_lfs_pointer(real_path) is False, "真实大文件应返回 False"
        print(f"  PASS: 真实大文件 → {is_lfs_pointer(real_path)}")

        assert is_lfs_pointer(small_path) is False, "正常小文件（非 LFS）应返回 False"
        print(f"  PASS: 正常小文件 → {is_lfs_pointer(small_path)}")

        assert is_lfs_pointer(fake_path) is False, "不存在的文件应返回 False"
        print(f"  PASS: 不存在文件 → {is_lfs_pointer(fake_path)}")

        # describe_file_state
        assert describe_file_state(lfs_path) == "lfs_pointer"
        print(f"  PASS: describe_file_state(LFS) = {describe_file_state(lfs_path)}")
        assert describe_file_state(fake_path) == "missing"
        print(f"  PASS: describe_file_state(missing) = {describe_file_state(fake_path)}")

        print()
        print("✅ 测试 1 通过: is_lfs_pointer() 正确识别 Git LFS 指针")
        return True
    finally:
        os.unlink(lfs_path)
        os.unlink(real_path)
        os.unlink(small_path)


def test_dashboard_integrity_rejects_lfs():
    """测试 2: check_dashboard_integrity.py 遇到 LFS 指针时快速 fail"""
    print()
    print("=" * 60)
    print("测试 2: check_dashboard_integrity.py 遇到 LFS 指针快速 fail")
    print("=" * 60)

    # 创建临时 dashboard 目录，PKL 是 LFS 指针
    with tempfile.TemporaryDirectory() as tmpdir:
        dashboard_root = Path(tmpdir)
        # PKL 路径必须与 check_dashboard_integrity 的 lookup 一致
        # output_root = dashboard_root.parent; pred_dir = output_root / "predictions"
        # 所以要把 PKL 放在 dashboard_root.parent / "predictions" / ...
        output_root = dashboard_root.parent  # e.g. /tmp
        pred_dir = output_root / "predictions"
        pred_dir.mkdir()
        lfs_pkl = pred_dir / "distributed_predictions_final_full.pkl"
        lfs_pkl.write_bytes(
            b"version https://git-lfs.github.com/spec/v1\n"
            b"oid sha256:deadbeef\n"
            b"size 999999\n"
        )

        # 写最小 metadata.json
        meta = {"prediction_column": "power_pred_final", "contains_future": False}
        (dashboard_root / "metadata.json").write_text(
            '{"prediction_column":"power_pred_final","contains_future":false,"optional_blocks":{}}',
            encoding="utf-8"
        )

        # 写 index.json
        (dashboard_root / "index.json").write_text(
            '{"total_rows": 100}', encoding="utf-8"
        )

        # 不创建 site_series / typical_sites.json / hourly_prediction_summary.json
        # 但我们只关心 PKL 检查

        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "check_dashboard_integrity.py"),
            "--dashboard-root", str(dashboard_root),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        output = result.stdout + result.stderr
        has_lfs_error = "Git LFS 指针" in output or "LFS" in output
        print(f"  exit code: {result.returncode}")
        print(f"  输出片段: {output[:300]}")

        if result.returncode != 0 and has_lfs_error:
            print()
            print("✅ 测试 2 通过: check_dashboard_integrity.py 遇到 LFS 指针快速 fail")
            return True
        else:
            print()
            print(f"❌ 测试 2 失败: returncode={result.returncode}, has_lfs_error={has_lfs_error}")
            return False


def test_pipeline_pretrain_ignores_lfs():
    """测试 3: check_pipeline_consistency.py --stage pretrain 遇到 LFS 指针不 fail"""
    print()
    print("=" * 60)
    print("测试 3: --stage pretrain 遇到 LFS 指针不 fail")
    print("=" * 60)

    # 这个测试依赖实际文件状态，如果文件不是 LFS 指针则跳过
    preds_dir = PROJECT_ROOT / "output" / "pv_pipeline" / "predictions"
    lfs_pkl = preds_dir / "distributed_predictions_final_full.pkl"

    if not lfs_pkl.exists():
        print("  SKIP: distributed_predictions_final_full.pkl 不存在，跳过")
        return True

    from pv_forecasting.core.file_checks import is_lfs_pointer
    if not is_lfs_pointer(lfs_pkl):
        print("  SKIP: distributed_predictions_final_full.pkl 不是 LFS 指针，跳过")
        return True

    print(f"  发现旧 PKL 是 LFS 指针: {lfs_pkl}")
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "check_pipeline_consistency.py"),
        "--stage", "pretrain",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    output = result.stdout + result.stderr
    print(f"  exit code: {result.returncode}")
    print(f"  输出片段: {output[:500]}")

    if result.returncode == 0:
        print()
        print("✅ 测试 3 通过: --stage pretrain 不被 LFS 指针阻塞")
        return True
    else:
        print()
        print("❌ 测试 3 失败: --stage pretrain 被 LFS 指针阻塞了（不应该）")
        return False


def test_pipeline_posttrain_rejects_lfs():
    """测试 4: check_pipeline_consistency.py --stage posttrain 遇到 LFS 指针必须 fail"""
    print()
    print("=" * 60)
    print("测试 4: --stage posttrain 遇到 LFS 指针必须 fail")
    print("=" * 60)

    preds_dir = PROJECT_ROOT / "output" / "pv_pipeline" / "predictions"
    lfs_pkl = preds_dir / "distributed_predictions_final_full.pkl"

    if not lfs_pkl.exists():
        print("  SKIP: distributed_predictions_final_full.pkl 不存在，跳过")
        return True

    from pv_forecasting.core.file_checks import is_lfs_pointer
    if not is_lfs_pointer(lfs_pkl):
        print("  SKIP: distributed_predictions_final_full.pkl 不是 LFS 指针，跳过")
        return True

    print(f"  发现旧 PKL 是 LFS 指针: {lfs_pkl}")
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "check_pipeline_consistency.py"),
        "--stage", "posttrain",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    output = result.stdout + result.stderr
    print(f"  exit code: {result.returncode}")
    print(f"  输出片段: {output[:500]}")

    has_lfs_error = "LFS" in output or "Git LFS" in output
    if result.returncode != 0 and has_lfs_error:
        print()
        print("✅ 测试 4 通过: --stage posttrain 正确拒绝 LFS 指针")
        return True
    else:
        print()
        print(f"❌ 测试 4 失败: returncode={result.returncode}, has_lfs_error={has_lfs_error}")
        return False


def test_dry_run_shows_pretrain_posttrain():
    """测试 5: run_full_pipeline.py --dry-run 显示 pretrain/posttrain 检查"""
    print()
    print("=" * 60)
    print("测试 5: --dry-run 显示 pretrain/posttrain 两套检查")
    print("=" * 60)

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_full_pipeline.py"),
        "--dry-run",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    output = result.stdout + result.stderr
    print(f"  exit code: {result.returncode}")
    print(f"  输出片段:")
    for line in output.split("\n"):
        if "pretrain" in line.lower() or "posttrain" in line.lower() or "[DRY-RUN]" in line:
            print(f"    {line.strip()}")

    has_pretrain = "[DRY-RUN] pretrain checks:" in output
    has_posttrain = "[DRY-RUN] posttrain hooks" in output
    has_stage_pretrain = "--stage pretrain" in output
    has_stage_posttrain = "--stage posttrain" in output

    if has_pretrain and has_posttrain and has_stage_pretrain and has_stage_posttrain:
        print()
        print("✅ 测试 5 通过: --dry-run 明确显示 pretrain/posttrain 两套检查")
        return True
    else:
        print()
        print(f"❌ 测试 5 失败: pretrain={has_pretrain}, posttrain={has_posttrain}, "
              f"stage_pretrain={has_stage_pretrain}, stage_posttrain={has_stage_posttrain}")
        return False


def main():
    print()
    print("=" * 60)
    print("Round98_1 完整性守卫负向测试")
    print("=" * 60)
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"Python: {sys.executable}")

    results = {}

    results["test1_is_lfs_pointer"] = test_is_lfs_pointer()
    results["test2_dashboard_rejects_lfs"] = test_dashboard_integrity_rejects_lfs()
    results["test3_pretrain_ignores_lfs"] = test_pipeline_pretrain_ignores_lfs()
    results["test4_posttrain_rejects_lfs"] = test_pipeline_posttrain_rejects_lfs()
    results["test5_dry_run_shows_stages"] = test_dry_run_shows_pretrain_posttrain()

    print()
    print("=" * 60)
    print("测试汇总")
    print("=" * 60)
    for name, passed in results.items():
        icon = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {icon}: {name}")

    passed_count = sum(1 for v in results.values() if v)
    total_count = len(results)
    print()
    if passed_count == total_count:
        print(f"✅ 全部 {total_count} 项测试通过！")
        sys.exit(0)
    else:
        print(f"❌ {passed_count}/{total_count} 项测试通过，{total_count - passed_count} 项失败。")
        sys.exit(1)


if __name__ == "__main__":
    main()
