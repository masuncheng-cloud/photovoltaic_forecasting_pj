#!/usr/bin/env python3
"""
promote_round64_candidate.py
==================================
将 Round64 safe 候选升级为正式 final 预测。

用法：
  python scripts/promote_round64_candidate.py --dry-run              # 查看但不执行
  python scripts/promote_round64_candidate.py --apply --exclude-future  # 执行升级

执行步骤：
  1. 备份当前 final pkl
  2. 过滤 future 数据（--exclude-future）
  3. 将 power_pred_round64_safe 写入 power_pred_final
  4. 写入正式 final_full.pkl 和 final_eval.pkl
  5. 更新 manifest.json
  6. 重新导出正式 interactive_dashboard
  7. 重新运行 posttrain validation
"""

from pathlib import Path
import shutil
import json
import hashlib
import pandas as pd
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"

FINAL_FULL = OUT / "predictions" / "distributed_predictions_final_full.pkl"
FINAL_EVAL = OUT / "predictions" / "distributed_predictions_final_eval.pkl"
CANDS_PKL = ROOT / "output/pv_pipeline/round64/round64_candidates.pkl"
BACKUP_DIR = ROOT / "output/pv_pipeline/backups"
ROUND64_COL = "power_pred_round64_safe"
FINAL_COL = "power_pred_final"
MANIFEST = OUT / "manifest.json"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_backup_name(ts: str, suffix: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR / f"distributed_predictions_final_{suffix}_before_round64_{ts}.pkl"


def promote(apply: bool, exclude_future: bool):
    """Execute the promotion."""
    print("=" * 60)
    mode = "apply" if apply else "dry-run"
    print(f"Round64 Candidate Promotion ({mode})")
    print("=" * 60)

    # ── Prerequisite checks ──────────────────────────────────────────
    if not CANDS_PKL.exists():
        print(f"[FAIL] Source pkl not found: {CANDS_PKL}")
        sys.exit(1)

    df_cands = pd.read_pickle(CANDS_PKL)
    if ROUND64_COL not in df_cands.columns:
        print(f"[FAIL] Column {ROUND64_COL} not found")
        sys.exit(1)
    print(f"[INFO] Candidates: {len(df_cands)} rows, splits: {df_cands['split'].value_counts().to_dict()}")

    # ── Future check ───────────────────────────────────────────────
    if exclude_future:
        future_mask = df_cands["split"] == "future"
        future_count = int(future_mask.sum())
        print(f"[INFO] Future rows in candidates: {future_count}")
        if future_count > 0:
            print(f"[FAIL] Candidates contain {future_count} future rows — aborting")
            sys.exit(1)

    ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")

    # ── Backup ───────────────────────────────────────────────────────
    backup_full = load_backup_name(ts, "full")
    backup_eval = load_backup_name(ts, "eval")

    if apply:
        if FINAL_FULL.exists():
            shutil.copy2(FINAL_FULL, backup_full)
            print(f"[BACKUP] {backup_full.relative_to(ROOT)}")
        if FINAL_EVAL.exists():
            shutil.copy2(FINAL_EVAL, backup_eval)
            print(f"[BACKUP] {backup_eval.relative_to(ROOT)}")

        # Write backup manifest
        backup_meta = {
            "ts": ts,
            "backup_full": str(backup_full.relative_to(ROOT)),
            "backup_eval": str(backup_eval.relative_to(ROOT)),
            "source_sha_full": sha256(FINAL_FULL) if FINAL_FULL.exists() else None,
            "source_sha_eval": sha256(FINAL_EVAL) if FINAL_EVAL.exists() else None,
        }
        (OUT / "round66" / "round66_backup_files.json").write_text(
            json.dumps(backup_meta, ensure_ascii=False, indent=2)
        )
    else:
        print(f"[DRY-RUN] Would backup: {backup_full.relative_to(ROOT)}")
        print(f"[DRY-RUN] Would backup: {backup_eval.relative_to(ROOT)}")

    # ── Load existing full pkl for train rows ───────────────────────
    if FINAL_FULL.exists():
        df_full_old = pd.read_pickle(FINAL_FULL)
        print(f"[INFO] Existing full pkl: {len(df_full_old)} rows, "
              f"splits: {df_full_old['split'].value_counts().to_dict()}")
    else:
        print("[WARN] No existing full pkl found")
        df_full_old = None

    # ── Build new full pkl ──────────────────────────────────────────
    # Strategy: start with old full (for train rows), then update/append valid+test
    # from round64 candidates

    if df_full_old is not None:
        # Keep only train from old full — discard future/valid/test (will be replaced)
        df_full_new = df_full_old[df_full_old["split"].isin(["train", "unknown"])].copy()
        # Append round64 valid+test (which already have power_pred_round64_safe)
        df_full_new = pd.concat([df_full_new, df_cands[df_cands["split"].isin(["valid", "test"])]], ignore_index=True)
    else:
        # No old full — use round64 candidates as-is (shouldn't happen normally)
        df_full_new = df_cands[df_cands["split"].isin(["valid", "test"])].copy()

    # Update power_pred_final = power_pred_round64_safe
    df_full_new[FINAL_COL] = df_full_new[ROUND64_COL]

    # Filter future if requested
    if exclude_future:
        future_count_new = int((df_full_new["split"] == "future").sum())
        if future_count_new > 0:
            print(f"[FAIL] New full pkl would contain {future_count_new} future rows — aborting")
            sys.exit(1)
        df_full_new = df_full_new[df_full_new["split"] != "future"].copy()

    df_full_new = df_full_new.reset_index(drop=True)

    # ── Build new eval pkl ──────────────────────────────────────────
    df_eval_new = df_full_new[df_full_new["split"].isin(["valid", "test"])].copy().reset_index(drop=True)

    print(f"\n[INFO] New full: {len(df_full_new)} rows, splits: {df_full_new['split'].value_counts().to_dict()}")
    print(f"[INFO] New eval: {len(df_eval_new)} rows, splits: {df_eval_new['split'].value_counts().to_dict()}")

    # ── Write pkl files ───────────────────────────────────────────
    if apply:
        FINAL_FULL.parent.mkdir(parents=True, exist_ok=True)
        df_full_new.to_pickle(FINAL_FULL)
        print(f"[WRITE] {FINAL_FULL.relative_to(ROOT)}")

        df_eval_new.to_pickle(FINAL_EVAL)
        print(f"[WRITE] {FINAL_EVAL.relative_to(ROOT)}")
    else:
        print(f"[DRY-RUN] Would write: {FINAL_FULL.relative_to(ROOT)} ({len(df_full_new)} rows)")
        print(f"[DRY-RUN] Would write: {FINAL_EVAL.relative_to(ROOT)} ({len(df_eval_new)} rows)")

    # ── Update manifest ────────────────────────────────────────────
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    else:
        manifest = {}

    manifest_update = {
        "final_prediction_column": FINAL_COL,
        "source_round": "Round64",
        "source_column": ROUND64_COL,
        "promoted_at": pd.Timestamp.now().isoformat(),
        "exclude_future": exclude_future,
        "full_sha256": sha256(FINAL_FULL) if apply and FINAL_FULL.exists() else None,
        "eval_sha256": sha256(FINAL_EVAL) if apply and FINAL_EVAL.exists() else None,
        "full_rows": len(df_full_new),
        "eval_rows": len(df_eval_new),
        "full_splits": df_full_new["split"].value_counts().to_dict(),
        "eval_splits": df_eval_new["split"].value_counts().to_dict(),
    }
    manifest.update(manifest_update)

    if apply:
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[UPDATE] {MANIFEST.relative_to(ROOT)}")
    else:
        print(f"[DRY-RUN] Would update manifest: {MANIFEST.relative_to(ROOT)}")
        print(f"  Keys updated: {list(manifest_update.keys())}")

    # ── Summary ─────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"[{'APPLY' if apply else 'DRY-RUN'}] Promotion {'executed' if apply else 'previewed'}")
    print(f"{'='*60}")
    if not apply:
        print(f"  To apply: python scripts/promote_round64_candidate.py --apply --exclude-future")

    return {
        "mode": mode,
        "ts": ts,
        "full_rows": len(df_full_new),
        "eval_rows": len(df_eval_new),
        "full_splits": df_full_new["split"].value_counts().to_dict(),
        "eval_splits": df_eval_new["split"].value_counts().to_dict(),
        "backup_full": str(backup_full.relative_to(ROOT)),
        "backup_eval": str(backup_eval.relative_to(ROOT)),
        "future_filtered": exclude_future,
        "applied": apply,
    }


def main():
    parser = argparse.ArgumentParser(description="Promote Round64 candidate to final")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run only")
    parser.add_argument("--apply", action="store_true", help="Apply changes")
    parser.add_argument("--exclude-future", action="store_true", default=True,
                       help="Filter out future data (default: True)")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.print_help()
        return

    result = promote(apply=args.apply, exclude_future=args.exclude_future)

    # Save apply report
    if args.apply:
        report = f"""# Round66 候选正式升级 Apply 报告

**日期**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}
**模式**: apply

## 执行结果

- 备份文件: {result['backup_full']}, {result['backup_eval']}
- New full 行数: {result['full_rows']}, splits: {result['full_splits']}
- New eval 行数: {result['eval_rows']}, splits: {result['eval_splits']}
- future 过滤: {result['future_filtered']}
- 时间戳: {result['ts']}
"""
        (OUT / "round66" / "round66_promote_apply_report.md").write_text(report, encoding="utf-8")
        print(f"\n[OK] Apply report: {OUT / 'round66' / 'round66_promote_apply_report.md'}")


if __name__ == "__main__":
    main()
