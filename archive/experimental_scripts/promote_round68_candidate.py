#!/usr/bin/env python3
"""
promote_round68_candidate.py
==================================
将 Round68 lgb_safe_blend 升级为正式 final 预测。

用法：
  python scripts/promote_round68_candidate.py --dry-run --exclude-future
  python scripts/promote_round68_candidate.py --apply --exclude-future

执行步骤：
  1. 重建 Round68 lgb_safe_blend 预测
  2. 备份当前 final pkl
  3. 合并 train (from current) + valid+test (from round68 blend)
  4. 写入新正式 pkl
  5. 备份 manifest 更新
"""

from pathlib import Path
import shutil
import json
import hashlib
import pandas as pd
import numpy as np
import pickle
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
FINAL_FULL = OUT / "predictions" / "distributed_predictions_final_full.pkl"
FINAL_EVAL = OUT / "predictions" / "distributed_predictions_final_eval.pkl"
BACKUP_DIR = ROOT / "output/pv_pipeline/backups"
MANIFEST = OUT / "manifest.json"
ROUND67_TBL = OUT / "round67" / "round67_training_table.parquet"
MODEL_STORE = OUT / "round67" / "round67_model_files" / "model_store.pkl"
WEIGHTS_CSV = OUT / "round68" / "round68_lgb_safe_blend_weights.csv"
FINAL_COL = "power_pred_final"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def reconstruct_round68_blend(df):
    """重建 Round68 lgb_safe_blend 预测。"""
    print("[INFO] Reconstructing Round68 lgb_safe_blend predictions...")

    # Feature columns
    exclude = {"site_id", "time", "split", "hour", "time_block", "site_group",
               "y_norm", "power_mw", "capacity_mw", "power_pred_final",
               "baseline_norm", "cap_group", "zero_group"}
    feat_cols = [c for c in df.columns if c not in exclude]

    # Load model store
    with open(MODEL_STORE, "rb") as f:
        store = pickle.load(f)
    models = store["models"]

    # baseline = round64_final
    df["pred_round64_final"] = df["power_pred_final"].values

    # Reconstruct lgb predictions
    df["pred_lgb_combined"] = np.nan
    for model_name, blocks in models.items():
        if model_name != "lgb":
            continue
        for block, model_obj in blocks.items():
            mask = df["time_block"] == block
            if mask.sum() == 0:
                continue
            X = (pd.DataFrame(df.loc[mask, feat_cols])
                   .apply(pd.to_numeric, errors="coerce")
                   .fillna(0).values.astype(float))
            pred_norm = model_obj.predict(X)
            cap = df.loc[mask, "capacity_mw"].values.astype(float)
            df.loc[mask, "pred_lgb_combined"] = np.clip(pred_norm * cap, 0, cap)
    df["pred_lgb_combined"] = df["pred_lgb_combined"].fillna(df["pred_round64_final"])

    # Load weights
    weights_df = pd.read_csv(WEIGHTS_CSV)
    weight_lookup = {
        (str(row["site_id"]), row["time_block"]): row["best_weight"]
        for _, row in weights_df.iterrows()
    }

    # Apply blend
    df["blend_weight"] = df.apply(
        lambda r: weight_lookup.get((str(r["site_id"]), r["time_block"]), 0.0), axis=1
    )
    df["power_pred_round68_lgb_safe_blend"] = (
        df["pred_round64_final"] +
        df["blend_weight"] * (df["pred_lgb_combined"] - df["pred_round64_final"])
    )

    print(f"  Round64 final: mean={df['pred_round64_final'].mean():.4f}")
    print(f"  LGB combined: mean={df['pred_lgb_combined'].mean():.4f}")
    print(f"  Safe blend: mean={df['power_pred_round68_lgb_safe_blend'].mean():.4f}")
    print(f"  Blend weights: min={df['blend_weight'].min():.2f}, max={df['blend_weight'].max():.2f}, mean={df['blend_weight'].mean():.3f}")

    # Keep only needed columns
    keep_cols = [c for c in df.columns if c not in {
        "pred_round64_final", "pred_lgb_combined", "blend_weight"
    }]
    return df[keep_cols]


def promote(apply: bool, exclude_future: bool):
    print("=" * 60)
    mode = "apply" if apply else "dry-run"
    print(f"Round68 lgb_safe_blend Promotion ({mode})")
    print("=" * 60)

    # ── 1. Load training table and reconstruct blend ──────────────────
    if not ROUND67_TBL.exists():
        print(f"[FAIL] Source table not found: {ROUND67_TBL}")
        sys.exit(1)

    df = pd.read_parquet(ROUND67_TBL)
    df["time"] = pd.to_datetime(df["time"])
    print(f"[INFO] Loaded training table: {len(df)} rows, splits: {df['split'].value_counts().to_dict()}")

    df = reconstruct_round68_blend(df)

    BLEND_COL = "power_pred_round68_lgb_safe_blend"
    if BLEND_COL not in df.columns:
        print(f"[FAIL] Blend column {BLEND_COL} not found")
        sys.exit(1)

    # ── 2. Future check ──────────────────────────────────────────────
    if exclude_future:
        future_count = int((df["split"] == "future").sum())
        print(f"[INFO] Future rows in blend: {future_count}")
        if future_count > 0:
            print(f"[FAIL] Blend contains {future_count} future rows — aborting")
            sys.exit(1)

    # ── 3. Load current full pkl ────────────────────────────────────
    if FINAL_FULL.exists():
        df_full_old = pd.read_pickle(FINAL_FULL)
        print(f"[INFO] Existing full pkl: {len(df_full_old)} rows")
    else:
        df_full_old = None
        print("[WARN] No existing full pkl found")

    # ── 4. Build new full pkl ────────────────────────────────────────
    # Strategy: keep train from current full, replace valid/test with round68 blend
    if df_full_old is not None:
        df_train = df_full_old[df_full_old["split"] == "train"].copy()
        df_full_new = pd.concat([
            df_train,
            df[df["split"].isin(["valid", "test"])].copy()
        ], ignore_index=True)
    else:
        df_full_new = df[df["split"].isin(["valid", "test"])].copy()

    # Write power_pred_final = round68 blend
    df_full_new[FINAL_COL] = df_full_new[BLEND_COL]

    # Filter future if requested
    if exclude_future:
        future_in_new = int((df_full_new["split"] == "future").sum())
        if future_in_new > 0:
            print(f"[FAIL] New full would contain {future_in_new} future rows — aborting")
            sys.exit(1)
        df_full_new = df_full_new[df_full_new["split"] != "future"].copy()

    df_full_new = df_full_new.reset_index(drop=True)

    # ── 5. Build eval pkl ───────────────────────────────────────────
    df_eval_new = df_full_new[df_full_new["split"].isin(["valid", "test"])].copy().reset_index(drop=True)

    print(f"\n[INFO] New full: {len(df_full_new)} rows, splits: {df_full_new['split'].value_counts().to_dict()}")
    print(f"[INFO] New eval: {len(df_eval_new)} rows")

    ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")

    # ── 6. Backup ───────────────────────────────────────────────────
    backup_full = BACKUP_DIR / f"distributed_predictions_final_full_before_round68_{ts}.pkl"
    backup_eval = BACKUP_DIR / f"distributed_predictions_final_eval_before_round68_{ts}.pkl"

    if apply:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        if FINAL_FULL.exists():
            shutil.copy2(FINAL_FULL, backup_full)
            print(f"[BACKUP] {backup_full.relative_to(ROOT)}")
        if FINAL_EVAL.exists():
            shutil.copy2(FINAL_EVAL, backup_eval)
            print(f"[BACKUP] {backup_eval.relative_to(ROOT)}")

        # Save backup info
        backup_meta = {
            "ts": ts,
            "backup_full": str(backup_full.relative_to(ROOT)),
            "backup_eval": str(backup_eval.relative_to(ROOT)),
            "source_sha_full": sha256(FINAL_FULL) if FINAL_FULL.exists() else None,
            "source_sha_eval": sha256(FINAL_EVAL) if FINAL_EVAL.exists() else None,
        }
        round69_dir = OUT / "round69"
        round69_dir.mkdir(exist_ok=True)
        (round69_dir / "round69_backup_files.json").write_text(
            json.dumps(backup_meta, ensure_ascii=False, indent=2)
        )
    else:
        print(f"[DRY-RUN] Would backup to: {backup_full.relative_to(ROOT)}")
        print(f"[DRY-RUN] Would backup to: {backup_eval.relative_to(ROOT)}")

    # ── 7. Write pkl files ──────────────────────────────────────────
    if apply:
        FINAL_FULL.parent.mkdir(parents=True, exist_ok=True)
        df_full_new.to_pickle(FINAL_FULL)
        print(f"[WRITE] {FINAL_FULL.relative_to(ROOT)}")

        df_eval_new.to_pickle(FINAL_EVAL)
        print(f"[WRITE] {FINAL_EVAL.relative_to(ROOT)}")
    else:
        print(f"[DRY-RUN] Would write: {FINAL_FULL.relative_to(ROOT)} ({len(df_full_new)} rows)")
        print(f"[DRY-RUN] Would write: {FINAL_EVAL.relative_to(ROOT)} ({len(df_eval_new)} rows)")

    # ── 8. Update manifest ─────────────────────────────────────────
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    else:
        manifest = {}

    manifest.update({
        "final_prediction_column": FINAL_COL,
        "source_round": "Round68 lgb_safe_blend",
        "source_column": BLEND_COL,
        "promoted_at": pd.Timestamp.now().isoformat(),
        "exclude_future": exclude_future,
        "full_sha256": sha256(FINAL_FULL) if apply else None,
        "eval_sha256": sha256(FINAL_EVAL) if apply else None,
        "full_rows": len(df_full_new),
        "eval_rows": len(df_eval_new),
        "full_splits": df_full_new["split"].value_counts().to_dict(),
        "eval_splits": df_eval_new["split"].value_counts().to_dict(),
    })

    if apply:
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[UPDATE] {MANIFEST.relative_to(ROOT)}")
    else:
        print(f"[DRY-RUN] Would update manifest")
        print(f"  Keys: {list(manifest.keys())}")

    # ── 9. Summary ──────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"[{'APPLY' if apply else 'DRY-RUN'}] Round68 promotion {'executed' if apply else 'previewed'}")
    print(f"{'='*60}")
    if not apply:
        print(f"  To apply: python scripts/promote_round68_candidate.py --apply --exclude-future")

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
        "blend_col": BLEND_COL,
    }


def main():
    parser = argparse.ArgumentParser(description="Promote Round68 lgb_safe_blend to final")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run only")
    parser.add_argument("--apply", action="store_true", help="Apply changes")
    parser.add_argument("--exclude-future", action="store_true", default=True,
                       help="Filter out future data (default: True)")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.print_help()
        return

    result = promote(apply=args.apply, exclude_future=args.exclude_future)

    if args.apply:
        report = f"""# Round68 候选正式升级 Apply 报告

**日期**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}
**模式**: apply
**升级列**: {result['blend_col']}

## 执行结果

- 备份: {result['backup_full']}, {result['backup_eval']}
- New full: {result['full_rows']} rows, splits: {result['full_splits']}
- New eval: {result['eval_rows']} rows, splits: {result['eval_splits']}
- future 过滤: {result['future_filtered']}
- 时间戳: {result['ts']}
"""
        round69_dir = OUT / "round69"
        round69_dir.mkdir(exist_ok=True)
        (round69_dir / "round69_promote_round68_apply_report.md").write_text(report, encoding="utf-8")
        print(f"\n[OK] Apply report: {round69_dir / 'round69_promote_round68_apply_report.md'}")


if __name__ == "__main__":
    main()
