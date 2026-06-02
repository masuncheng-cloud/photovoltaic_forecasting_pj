#!/usr/bin/env python3
"""
rollback_round64_promotion.py
==================================
将正式预测回滚到备份版本。

用法：
  python scripts/rollback_round64_promotion.py --latest-backup
  python scripts/rollback_round64_promotion.py --backup-file output/pv_pipeline/backups/distributed_predictions_final_full_before_round64_20260601_145012.pkl
"""

from pathlib import Path
import shutil
import json
import argparse
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
BACKUP_DIR = ROOT / "output/pv_pipeline/backups"
FINAL_FULL = OUT / "predictions" / "distributed_predictions_final_full.pkl"
FINAL_EVAL = OUT / "predictions" / "distributed_predictions_final_eval.pkl"


def list_backups():
    backups = sorted(BACKUP_DIR.glob("distributed_predictions_final_full_before_round64_*.pkl"))
    return backups


def rollback(backup_full: Path, backup_eval: Path):
    print("=" * 60)
    print("Round64 Promotion Rollback")
    print("=" * 60)

    # Check backups exist
    if not backup_full.exists():
        print(f"[FAIL] Backup not found: {backup_full}")
        sys.exit(1)

    # Restore full
    shutil.copy2(backup_full, FINAL_FULL)
    print(f"[RESTORE] {FINAL_FULL.relative_to(ROOT)} <- {backup_full.relative_to(ROOT)}")

    # Restore eval if backup exists
    if backup_eval.exists():
        shutil.copy2(backup_eval, FINAL_EVAL)
        print(f"[RESTORE] {FINAL_EVAL.relative_to(ROOT)} <- {backup_eval.relative_to(ROOT)}")
    else:
        print(f"[WARN] No eval backup found, generating from full...")
        df = pd.read_pickle(FINAL_FULL)
        df_eval = df[df["split"].isin(["valid", "test"])].copy()
        df_eval.to_pickle(FINAL_EVAL)
        print(f"[WRITE] {FINAL_EVAL.relative_to(ROOT)} ({len(df_eval)} rows)")

    # Update manifest
    manifest_path = OUT / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["rollback_note"] = f"Rolled back from Round64 promotion. Backup: {backup_full.name}"
        manifest["rolled_back_at"] = pd.Timestamp.now().isoformat()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[UPDATE] {manifest_path.relative_to(ROOT)}")

    # Re-export dashboard
    print(f"\n[INFO] Ready to re-export Round61 dashboard with:")
    print(f"  python scripts/export_interactive_dashboard_data.py \\")
    print(f"    --dashboard-root output/pv_pipeline/interactive_dashboard \\")
    print(f"    --label 'Round61 final (rolled back)' \\")
    print(f"    --exclude-future")

    print(f"\n{'='*60}")
    print(f"[OK] Rollback complete")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Rollback Round64 promotion")
    parser.add_argument("--latest-backup", action="store_true",
                       help="Use the most recent backup")
    parser.add_argument("--backup-full", type=str, default=None,
                       help="Path to full pkl backup")
    parser.add_argument("--backup-eval", type=str, default=None,
                       help="Path to eval pkl backup (auto-derived if omitted)")
    args = parser.parse_args()

    if args.latest_backup:
        backups = list_backups()
        if not backups:
            print("[FAIL] No backups found")
            sys.exit(1)
        backup_full = backups[-1]
        # Try to find matching eval backup
        ts = backup_full.stem.replace("distributed_predictions_final_full_before_round64_", "")
        backup_eval = BACKUP_DIR / f"distributed_predictions_final_eval_before_round64_{ts}.pkl"
        print(f"[INFO] Latest backup: {backup_full.name}")
        if backup_eval.exists():
            print(f"[INFO] Eval backup: {backup_eval.name}")
        else:
            print(f"[INFO] No eval backup found (will regenerate)")
    elif args.backup_full:
        backup_full = Path(args.backup_full)
        backup_eval = Path(args.backup_eval) if args.backup_eval else None
        if backup_eval:
            backup_eval = Path(args.backup_eval)
    else:
        # Interactive: list backups
        backups = list_backups()
        if not backups:
            print("[FAIL] No backups found")
            sys.exit(1)
        print("Available backups:")
        for b in reversed(backups):
            ts = b.stem.replace("distributed_predictions_final_full_before_round64_", "")
            eval_b = BACKUP_DIR / f"distributed_predictions_final_eval_before_round64_{ts}.pkl"
            print(f"  {b.name}  (eval exists: {eval_b.exists()})")
        print("\nUse --backup-full <path> to specify which to restore")
        sys.exit(0)

    rollback(backup_full, backup_eval if backup_eval else BACKUP_DIR / backup_full.name.replace("full", "eval"))


if __name__ == "__main__":
    main()
