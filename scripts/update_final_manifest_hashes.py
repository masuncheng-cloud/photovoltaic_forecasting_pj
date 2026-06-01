#!/usr/bin/env python3
"""
update_final_manifest_hashes.py
==================================
读取 manifest.json，对所有正式关键产物重算 SHA256，更新后写回。

支持参数：
  --dry-run   # 只计算并显示，不写入
  --apply     # 计算并写入 manifest
"""

from pathlib import Path
import json
import hashlib
import pandas as pd
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"


def sha256(p: Path) -> dict:
    h = hashlib.sha256()
    size = p.stat().st_size
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return {"sha256": h.hexdigest(), "bytes": size, "exists": True}


def main():
    parser = argparse.ArgumentParser(description="Update manifest SHA256 hashes")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    apply = not args.dry_run

    print("=" * 60)
    print(f"Update Manifest Hashes ({'apply' if apply else 'dry-run'})")
    print("=" * 60)

    manifest_path = OUT / "manifest.json"
    if not manifest_path.exists():
        print(f"[FAIL] manifest.json not found: {manifest_path}")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Key artifacts to hash
    artifacts = [
        ("final_full_pkl", OUT / "predictions" / "distributed_predictions_final_full.pkl"),
        ("final_eval_pkl", OUT / "predictions" / "distributed_predictions_final_eval.pkl"),
        ("dashboard_metadata", OUT / "interactive_dashboard" / "metadata.json"),
    ]

    # Auto-find metrics files
    metrics_dir = OUT / "metrics"
    for p in sorted(metrics_dir.glob("*hour*.csv")):
        artifacts.append((f"metrics_{p.stem}", p))
    for p in sorted(metrics_dir.glob("*site*.csv")):
        if "hour" not in p.stem:
            artifacts.append((f"metrics_{p.stem}", p))

    rows = []
    artifact_hashes = {}
    all_ok = True

    for name, path in artifacts:
        if path.exists():
            info = sha256(path)
            artifact_hashes[name] = info["sha256"]
            rows.append({
                "artifact": name,
                "path": str(path.relative_to(ROOT)),
                "sha256": info["sha256"],
                "bytes": info["bytes"],
                "exists": True,
            })
            print(f"[OK] {name}: {info['sha256'][:16]}... ({info['bytes']:,} bytes)")
        else:
            rows.append({
                "artifact": name,
                "path": str(path.relative_to(ROOT)),
                "sha256": None,
                "bytes": 0,
                "exists": False,
            })
            artifact_hashes[name] = None
            print(f"[SKIP] {name}: not found")
            all_ok = False

    # Save CSV
    out_dir = OUT / "round67"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "round67_manifest_hash_update.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] CSV: {csv_path}")

    # Save JSON
    result = {
        "timestamp": pd.Timestamp.now().isoformat(),
        "mode": "apply" if apply else "dry-run",
        "artifacts": rows,
        "all_exist": all_ok,
    }
    json_path = out_dir / "round67_manifest_hash_update.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[OK] JSON: {json_path}")

    # Build full artifact_hashes dict (all files we can hash)
    full_hashes = dict(artifact_hashes)  # from all found files
    # Write back to manifest — ONLY update artifact_hashes, NEVER touch artifacts
    if apply:
        manifest["artifact_hashes"] = full_hashes
        manifest["final_round"] = manifest.get("final_round", "Round64")
        manifest["prediction_column"] = manifest.get("prediction_column", "power_pred_final")
        manifest["exclude_future"] = manifest.get("exclude_future", True)
        manifest["hashes_updated_at"] = pd.Timestamp.now().isoformat()
        # Ensure artifacts field (file paths) is preserved
        if "artifacts" not in manifest or not isinstance(manifest.get("artifacts"), dict):
            manifest["artifacts"] = {}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[UPDATE] {manifest_path} — artifact_hashes updated ({len(full_hashes)} files)")
    else:
        print(f"\n[DRY-RUN] Would update artifact_hashes ({len(full_hashes)} files)")

    print(f"\n{'='*60}")
    if not all_ok:
        print("[WARN] Some artifacts not found")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
