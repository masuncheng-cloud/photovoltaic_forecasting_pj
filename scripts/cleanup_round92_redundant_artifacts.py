#!/usr/bin/env python3
"""
Round92 冗余清理脚本。
将非正式脚本和过期 output 目录移动到 archive/round92_cleanup_removed/<timestamp>/。
正式 STEPS 依赖的脚本不会被移动。
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
ARCHIVE = ROOT / "archive" / "round92_cleanup_removed" / STAMP


# 正式 pipeline STEPS 引用的脚本（必须保留）
FORMAL_STEP_SCRIPTS = {
    "build_site_master.py",
    "apply_manual_geo_overrides.py",
    "pretrain_audit_round36.py",
    "train_distributed_model_v159.py",
    "build_round36_predictions.py",
    "build_site_validity_round36.py",
    "apply_round36_calibration.py",
    "compute_round36_metrics.py",
    "post_training_finalize_outputs.py",
    "posttrain_validation.py",
    "check_dashboard_prediction_values.py",
    "export_interactive_dashboard_data.py",
    "update_dashboard_after_training.py",
}

# 正式 pipeline 依赖的辅助脚本（必须保留）
FORMAL_AUX_SCRIPTS = {
    "__init__.py",
    "run_full_pipeline.py",
    "common_paths.py",
    "metrics_common.py",
    "pipeline_cache.py",
    "check_pipeline_consistency.py",
    "check_dashboard_actual_values.py",
    "check_dashboard_auto_update_stamp.py",
    "check_dashboard_data_freshness.py",
    "check_no_future_in_outputs.py",
    "check_post_training_auto_finalize.py",
    "generate_site_parameters.py",
    "apply_site_metadata_overrides.py",
    "audit_training_pipeline_flow.py",
    "audit_training_process_and_results.py",
    "audit_prediction_column_consistency.py",
    "audit_edge_hour_zero_predictions.py",
    # Round92 新增
    "audit_round92_project_integrity.py",
    "cleanup_round92_redundant_artifacts.py",
}

KEEP_SCRIPTS = FORMAL_STEP_SCRIPTS | FORMAL_AUX_SCRIPTS

# output/pv_pipeline 下必须保留的目录
KEEP_OUTPUT_DIRS = {
    "predictions",
    "metrics",
    "models",
    "tables",
    "interactive_dashboard",
    "logs",
    "docs",
    "validation",
    "figures",
}


def move_to_archive(path: Path):
    if not path.exists():
        return
    rel = path.relative_to(ROOT)
    dst = ARCHIVE / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dst))
    print(f"[MOVED] {rel} -> archive/round92_cleanup_removed/{STAMP}/{rel}")


def remove_junk():
    """删除系统垃圾文件（排除 archive/）。"""
    for sub in [ROOT / "scripts", ROOT / "stages", ROOT / "src"]:
        if not sub.exists():
            continue
        for p in sub.rglob(".DS_Store"):
            move_to_archive(p)
        for p in sub.rglob("__pycache__"):
            move_to_archive(p)
        for p in sub.rglob("*.pyc"):
            move_to_archive(p)
    for p in ROOT.glob(".DS_Store"):
        move_to_archive(p)


def archive_round_scripts():
    """
    归档不在正式保留列表中的 round 相关脚本。
    包含 'round'/'compare'/'candidate'/'diagnose' 但不在 KEEP_SCRIPTS 中的脚本将被归档。
    """
    scripts_dir = ROOT / "scripts"
    if not scripts_dir.exists():
        return

    archived = []
    kept = []
    for p in scripts_dir.glob("*.py"):
        name = p.name
        if name in KEEP_SCRIPTS:
            kept.append(name)
            continue
        lower = name.lower()
        if any(kw in lower for kw in [
            "round", "compare", "candidate", "diagnose",
            "stale", "failed", "cleanup", "archive_legacy",
            "verify", "recheck", "fix_round",
        ]):
            move_to_archive(p)
            archived.append(name)
        else:
            kept.append(name)

    print(f"\n[scripts] kept={len(kept)} archived={len(archived)}")
    if archived:
        print(f"  archived: {archived[:10]}{'...' if len(archived) > 10 else ''}")


def archive_output_round_dirs():
    """
    归档 output/pv_pipeline 下非正式保留目录。
    """
    out = ROOT / "output" / "pv_pipeline"
    if not out.exists():
        return

    archived = []
    kept_dirs = []
    for p in list(out.iterdir()):
        if not p.is_dir():
            continue
        name = p.name
        if name in KEEP_OUTPUT_DIRS:
            kept_dirs.append(name)
            continue
        lower = name.lower()
        if (
            lower.startswith("round")
            or lower.startswith("archive")
            or lower.startswith("backup")
            or lower in {"backups", "baselines", "cache", "diagnostics", "calibration"}
            or "candidate" in lower
            or "old" in lower
        ):
            move_to_archive(p)
            archived.append(name)
        else:
            kept_dirs.append(name)

    print(f"\n[output/pv_pipeline] kept_dirs={len(kept_dirs)} archived={len(archived)}")
    if archived:
        print(f"  archived: {archived}")
    if kept_dirs:
        print(f"  kept: {kept_dirs}")


def archive_root_cursor_md():
    """归档根目录下的 Cursor 临时方案文件。"""
    for p in ROOT.glob("Cursor*.md"):
        move_to_archive(p)


def main():
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    print(f"=== Round92 清理 ===")
    print(f"Archive: {ARCHIVE.relative_to(ROOT)}")

    print("\n[1/4] 删除系统垃圾...")
    remove_junk()

    print("\n[2/4] 归档 round 相关非正式脚本...")
    archive_round_scripts()

    print("\n[3/4] 归档 output 旧目录...")
    archive_output_round_dirs()

    print("\n[4/4] 归档根目录 Cursor 方案文件...")
    archive_root_cursor_md()

    print(f"\n[OK] 清理完成")
    print(f"      归档位置: {ARCHIVE.relative_to(ROOT)}")
    print(f"\n如需回退，执行:")
    print(f"  cp -a {ARCHIVE}/* {ROOT}/")


if __name__ == "__main__":
    main()
