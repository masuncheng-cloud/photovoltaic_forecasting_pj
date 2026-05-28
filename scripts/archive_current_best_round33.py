"""
archive_current_best_round33.py
备份 Round33 重训前的当前最优结果，用于回退。
"""
import os
import sys
import json
import shutil
import hashlib
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "output", "pv_pipeline")
BACKUP_DIR = os.path.join(PROJECT_ROOT, "output", "pv_pipeline", "archive_before_round33")
os.makedirs(BACKUP_DIR, exist_ok=True)

METRICS_SRC = os.path.join(SRC_DIR, "metrics")
METRICS_BACKUP = os.path.join(BACKUP_DIR, "metrics")
os.makedirs(METRICS_BACKUP, exist_ok=True)

DOCS_BACKUP = os.path.join(BACKUP_DIR, "docs")
os.makedirs(DOCS_BACKUP, exist_ok=True)

PRED_BACKUP = os.path.join(BACKUP_DIR, "predictions")
os.makedirs(PRED_BACKUP, exist_ok=True)

TABLES_BACKUP = os.path.join(BACKUP_DIR, "tables")
os.makedirs(TABLES_BACKUP, exist_ok=True)

MODELS_BACKUP = os.path.join(BACKUP_DIR, "models")
os.makedirs(MODELS_BACKUP, exist_ok=True)

METEO_BACKUP = os.path.join(BACKUP_DIR, "site_data")
os.makedirs(METEO_BACKUP, exist_ok=True)

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def backup_file(src_path, dest_dir, sub_path):
    if not os.path.exists(src_path):
        return {"status": "MISSING", "path": sub_path, "size_bytes": 0}
    dest_path = os.path.join(dest_dir, sub_path)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    shutil.copy2(src_path, dest_path)
    size = os.path.getsize(src_path)
    hash_val = sha256(src_path)
    return {
        "status": "OK",
        "path": sub_path,
        "size_bytes": size,
        "sha256": hash_val,
        "mtime": datetime.fromtimestamp(os.path.getmtime(src_path)).isoformat(),
    }

manifest = {
    "created_at": datetime.now().isoformat(),
    "round": "round33_before_retrain",
    "files": [],
}

# 1. Predictions
pred_files = [
    "tables/distributed_predictions_final_full.pkl",
    "tables/distributed_predictions_final_eval.pkl",
]
for f in pred_files:
    src = os.path.join(SRC_DIR, f)
    result = backup_file(src, BACKUP_DIR, f)
    manifest["files"].append(result)
    print(f"  [{result['status']}] {f} ({result.get('size_bytes',0)/1024/1024:.1f} MB)")

# 2. Models
model_files = [
    "models/distributed_model.pkl",
    "models/distributed_model_v159.pkl",
    "models/distributed_model_baseline.pkl",
]
for f in model_files:
    src = os.path.join(SRC_DIR, f)
    if os.path.exists(src):
        result = backup_file(src, BACKUP_DIR, f)
        manifest["files"].append(result)
        print(f"  [{result['status']}] {f} ({result.get('size_bytes',0)/1024/1024:.1f} MB)")

# 3. Site data
site_files = [
    "tables/power_clean.pkl",
    "tables/power_long_raw.pkl",
    "tables/site_master.csv",
    "tables/site_meteo.pkl",
    "tables/site_irradiance.pkl",
]
for f in site_files:
    src = os.path.join(SRC_DIR, f)
    if os.path.exists(src):
        result = backup_file(src, BACKUP_DIR, f)
        manifest["files"].append(result)
        print(f"  [{result['status']}] {f} ({result.get('size_bytes',0)/1024/1024:.1f} MB)")

# 4. Metrics CSV
if os.path.exists(METRICS_SRC):
    for fname in os.listdir(METRICS_SRC):
        if fname.endswith(".csv") or fname.endswith(".json") or fname.endswith(".txt"):
            src = os.path.join(METRICS_SRC, fname)
            result = backup_file(src, METRICS_BACKUP, fname)
            manifest["files"].append({"backup_dir": "metrics", **result})

# 5. Docs
docs_dir = os.path.join(PROJECT_ROOT, "docs")
docs_backup_dir = os.path.join(BACKUP_DIR, "project_docs")
os.makedirs(docs_backup_dir, exist_ok=True)
if os.path.exists(docs_dir):
    for fname in os.listdir(docs_dir):
        if fname.endswith(".md"):
            src = os.path.join(docs_dir, fname)
            result = backup_file(src, docs_backup_dir, fname)
            manifest["files"].append({"backup_dir": "project_docs", **result})

# 6. Root project report
root_report = os.path.join(PROJECT_ROOT, "光伏功率预测项目.md")
if os.path.exists(root_report):
    result = backup_file(root_report, BACKUP_DIR, "光伏功率预测项目.md")
    manifest["files"].append(result)
    print(f"  [{result['status']}] 光伏功率预测项目.md")

# 7. Interactive dashboard HTML
html_src = os.path.join(PROJECT_ROOT, "stages", "05_visualization", "interactive_forecast_dashboard.html")
html_backup_dir = os.path.join(BACKUP_DIR, "visualization")
os.makedirs(html_backup_dir, exist_ok=True)
if os.path.exists(html_src):
    result = backup_file(html_src, html_backup_dir, "interactive_forecast_dashboard.html")
    manifest["files"].append(result)
    print(f"  [{result['status']}] interactive_forecast_dashboard.html")

# Write manifest
manifest_path = os.path.join(BACKUP_DIR, "archive_manifest.json")
with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
print(f"\n备份完成！清单已写入: {manifest_path}")
print(f"备份目录: {BACKUP_DIR}")
ok_count = sum(1 for x in manifest["files"] if x.get("status") == "OK")
missing_count = sum(1 for x in manifest["files"] if x.get("status") == "MISSING")
print(f"成功备份: {ok_count} | 缺失: {missing_count}")
