#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round14 Step 1: 备份当前 Grade A 版本。

备份目标目录：
  output/pv_pipeline/verified_backup_round14/

备份文件：
  - distributed_predictions_final_eval.pkl
  - distributed_predictions_final_full.pkl
  - best_predictions_eval.pkl (如存在)
  - best_predictions_full.pkl (如存在)
  - round10_overall_nrmse_summary.csv
  - round10_hour_overall_nrmse.csv
  - round10_site_hour_nrmse.csv
  - 分布式光伏预测_逐小时平均NRMSE.csv
  - round11_candidate_leaderboard.csv
  - interactive_dashboard/ (整体目录)
  - docs/训练过程与结果严谨性验证报告.md
  - 光伏功率预测项目.md

输出：
  verified_backup_round14/backup_manifest.csv
"""
from __future__ import annotations

import shutil
import hashlib
import csv
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output" / "pv_pipeline"
BACKUP_DIR = OUT / "verified_backup_round14"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def backup_file(src: Path, dest_dir: Path, manifest_rows: list, base: Path = None) -> None:
    if not src.exists():
        print(f"  [SKIP] 不存在: {src}")
        manifest_rows.append({
            "source_path": str(src),
            "backup_path": "",
            "exists": False,
            "size_bytes": 0,
            "sha256": "",
            "copied_at": "",
            "status": "SKIP: not found",
        })
        return

    if base is None:
        base = OUT
    try:
        rel = src.relative_to(base)
    except ValueError:
        rel = src.relative_to(PROJECT_ROOT)

    dest = dest_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)

    size = dest.stat().st_size
    digest = sha256(dest)
    manifest_rows.append({
        "source_path": str(src),
        "backup_path": str(dest),
        "exists": True,
        "size_bytes": size,
        "sha256": digest,
        "copied_at": datetime.now().isoformat(),
        "status": "OK",
    })
    print(f"  [OK] {rel} ({size / 1024 / 1024:.1f} MB)")


def backup_dir_recursive(src_dir: Path, dest_dir: Path, manifest_rows: list, base: Path = None) -> None:
    if base is None:
        base = PROJECT_ROOT
    if not src_dir.exists():
        print(f"  [SKIP] 不存在: {src_dir}")
        return
    for src_path in src_dir.rglob("*"):
        if src_path.is_file():
            try:
                rel = src_path.relative_to(base)
            except ValueError:
                rel = src_path.relative_to(PROJECT_ROOT)
            dest = dest_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest)
            size = dest.stat().st_size
            digest = sha256(dest)
            manifest_rows.append({
                "source_path": str(src_path),
                "backup_path": str(dest),
                "exists": True,
                "size_bytes": size,
                "sha256": digest,
                "copied_at": datetime.now().isoformat(),
                "status": "OK",
            })


def main():
    print("=" * 70)
    print("Round14 Step 1: 备份当前 Grade A 版本")
    print("=" * 70)

    if BACKUP_DIR.exists():
        print(f"[WARN] 备份目录已存在: {BACKUP_DIR}")
        print("  重新创建…")
        shutil.rmtree(BACKUP_DIR)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    manifest = []

    # ── PKL 文件 ───────────────────────────────────────────────
    print("\n备份核心 PKL 文件…")
    pkl_files = [
        OUT / "tables" / "distributed_predictions_final_eval.pkl",
        OUT / "tables" / "distributed_predictions_final_full.pkl",
        OUT / "tables" / "best_predictions_eval.pkl",
        OUT / "tables" / "best_predictions_full.pkl",
    ]
    for f in pkl_files:
        backup_file(f, BACKUP_DIR, manifest)

    # ── 核心指标 CSV ───────────────────────────────────────────
    print("\n备份核心指标 CSV…")
    csv_files = [
        OUT / "metrics" / "round10_overall_nrmse_summary.csv",
        OUT / "metrics" / "round10_hour_overall_nrmse.csv",
        OUT / "metrics" / "round10_site_hour_nrmse.csv",
        OUT / "metrics" / "分布式光伏预测_逐小时平均NRMSE.csv",
        OUT / "metrics" / "round11_candidate_leaderboard.csv",
    ]
    for f in csv_files:
        backup_file(f, BACKUP_DIR, manifest)

    # ── interactive_dashboard ─────────────────────────────────
    print("\n备份 interactive_dashboard/ …")
    backup_dir_recursive(OUT / "interactive_dashboard", BACKUP_DIR, manifest, base=PROJECT_ROOT)

    # ── 审计报告 ───────────────────────────────────────────────
    print("\n备份审计报告和项目报告…")
    backup_file(PROJECT_ROOT / "docs" / "训练过程与结果严谨性验证报告.md", BACKUP_DIR, manifest, base=PROJECT_ROOT)
    backup_file(PROJECT_ROOT / "光伏功率预测项目.md", BACKUP_DIR, manifest, base=PROJECT_ROOT)

    # ── 写入 manifest ─────────────────────────────────────────
    manifest_path = BACKUP_DIR / "backup_manifest.csv"
    if manifest:
        df = __import__('pandas').DataFrame(manifest)
        df.to_csv(manifest_path, index=False, encoding="utf-8-sig")
        total = sum(r.get("size_bytes", 0) for r in manifest)
        print(f"\n[OK] 备份清单已保存: {manifest_path} ({len(manifest)} 项，{total/1024/1024:.1f} MB)")

    # ── 验收检查 ───────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("备份验收检查")
    print("=" * 70)

    ok = True
    # 必须存在的文件
    required = [
        "tables/distributed_predictions_final_eval.pkl",
        "tables/distributed_predictions_final_full.pkl",
    ]
    for rel in required:
        p = BACKUP_DIR / rel
        if not p.exists():
            print(f"  [FAIL] 必需备份文件缺失: {rel}")
            ok = False
        else:
            print(f"  [OK] {rel}")

    if not ok:
        print("\n[ABORT] 必需备份文件缺失，停止后续操作")
        raise SystemExit(1)

    # 验证备份可读
    print("\n验证备份可读性…")
    import sys
    import pandas as pd
    import numpy as np
    _src = PROJECT_ROOT / "src"
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))
    from pv_forecasting.core.utils import safe_pickle_load
    from pv_forecasting.core.evaluation import build_eval_frame

    # 验证 NRMSE
    if ok:
        try:
            import numpy as np
            from pv_forecasting.core.evaluation import build_eval_frame
            df_val = safe_pickle_load(BACKUP_DIR / "tables" / "distributed_predictions_final_eval.pkl")
            print(f"  [OK] final_eval.pkl 可读，{len(df_val):,} 行")
            ev = build_eval_frame(df_val, target_site_count=53)
            yt = pd.to_numeric(ev["power_mw"], errors="coerce")
            yp = pd.to_numeric(ev["power_pred"], errors="coerce")
            mae = float(np.mean(np.abs(yp - yt)))
            rmse = float(np.sqrt(np.mean((yp - yt) ** 2)))
            cap_mean = float(pd.to_numeric(ev["capacity_mw"], errors="coerce").mean())
            nrmse = rmse / cap_mean * 100
            actual = float(yt.sum())
            pred = float(yp.sum())
            ratio = pred / actual
            print(f"  ratio={ratio:.4f}, bias={(pred-actual)/actual*100:.2f}%")
            print(f"  NRMSE={nrmse:.4f}%, MAE={mae:.4f}, RMSE={rmse:.4f}")
            if not (19.5 <= nrmse <= 20.5):
                print(f"  [WARN] NRMSE 超出预期范围 19.5~20.5%: {nrmse:.4f}")
            else:
                print(f"  [OK] NRMSE 在预期范围内")
        except Exception as e:
            print(f"  [FAIL] NRMSE 验证失败: {e}")
            ok = False

    if ok:
        print("\n[OK] 备份完成，所有验收检查通过")
    else:
        print("\n[ABORT] 备份验收失败")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
