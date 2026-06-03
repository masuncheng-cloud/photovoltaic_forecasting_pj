#!/usr/bin/env python3
"""
create_round61_baseline_manifest.py
=================================
生成 Round61 稳定基线的 manifest 和文件清单。
"""

from pathlib import Path
import hashlib
import json
import subprocess
from datetime import datetime
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "output/pv_pipeline/baselines/round61"
BASE.mkdir(parents=True, exist_ok=True)

FILES = [
    "configs/pipeline.yaml",
    "configs/site_quality_policy.yaml",
    "configs/manual_station_geo_overrides.csv",
    "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl",
    "output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl",
    "output/pv_pipeline/metrics/hourly_nrmse_consistent.csv",
    "output/pv_pipeline/metrics/site_metrics_consistent.csv",
    "output/pv_pipeline/metrics/round61_compare_summary.csv",
    "output/pv_pipeline/metrics/round61_compare_hourly.csv",
    "output/pv_pipeline/metrics/round61_compare_site.csv",
    "output/pv_pipeline/manifest.json",
    "docs/Round61_城市总量校准与站点稳定性保护报告.md",
    "scripts/train_city_total_calibrator.py",
    "scripts/apply_round61_city_calibration.py",
    "scripts/select_round61_final_prediction.py",
    "scripts/compare_round58_59_60_61_metrics.py",
]


def sha256(path):
    p = Path(path)
    if not p.exists():
        return "FILE_NOT_FOUND"
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True).strip()
    except Exception as e:
        return f"ERROR: {e}"


print("=" * 60)
print("生成 Round61 baseline manifest")
print("=" * 60)

rows = []
for f in FILES:
    p = ROOT / f
    exists = p.exists()
    size = p.stat().st_size if exists else None
    sha = sha256(p) if exists else None
    rows.append({
        "path": f,
        "exists": exists,
        "size_bytes": size,
        "size_mb": round(size / 1024 / 1024, 2) if size else None,
        "sha256": sha,
    })
    status = "[OK]" if exists else "[MISSING]"
    size_str = f"{size/1024/1024:.1f}MB" if size else "N/A"
    print(f"  {status} {f} ({size_str})")

df = pd.DataFrame(rows)
df.to_csv(BASE / "round61_baseline_files.csv", index=False, encoding="utf-8-sig")
print(f"\n[OK] Files list: {BASE / 'round61_baseline_files.csv'}")

manifest = {
    "baseline": "round61",
    "created_at": datetime.now().isoformat(timespec="seconds"),
    "git_branch": git("git branch --show-current"),
    "git_commit": git("git rev-parse HEAD"),
    "git_status_short": git("git status --short"),
    "final_prediction_column": "power_pred_final",
    "pred_source": "power_pred_round61_city_safe (with site-level and hour-level guard)",
    "eval_scope": {
        "split": "test",
        "hours": "6-19",
        "exclude_future": True,
        "nrmse_site_denominator": "station capacity_mw",
        "nrmse_city_denominator": "sum participating station capacity_mw (per-timestamp, per-hour average)",
    },
    "key_result_summary": {
        "city_nrmse_6_19": "3.9531%",
        "city_nrmse_10_14": "6.2359%",
        "site_mean_nrmse_6_19": "11.4095%",
        "bias_6_19": "+1.42%",
        "bias_10_14": "+8.40%",
        "worse_than_1pp_sites": 0,
    },
    "calibration_layers": {
        "layer1": "Round60 hour_scene calibrator (conservative, with valid rollback)",
        "layer2": "Round60 site calibrator (conservative, with valid rollback)",
        "layer3": "Round61 city_total calibrator (hourly, with valid rollback + site/hour guard)",
    },
    "files": rows,
    "restore_note": (
        "Use 'git checkout round61-stable-20260601' to restore code, "
        "then restore artifacts from round61_baseline_files.csv. "
        "Full pkl files are NOT committed to git (too large); "
        "they must be restored from the round61_baseline_files list."
    ),
}

m_path = BASE / "round61_baseline_manifest.json"
m_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[OK] Manifest: {m_path}")

# Generate stable baseline doc
doc = """# Round61 稳定基线说明

## 基线说明

Round61 是当前稳定版本。该版本综合了 Round58 的城市总量精度和 Round60 的站点稳定性保护机制：

- 城市总量 NRMSE 基本回到 Round58 水平（city_nrmse_6_19: 3.9531%）
- 变差超过 +1pp 的站点数为 0
- 含三层校准：hour_scene → site → city_total

## 关键指标（test 6-19h）

| 指标 | 值 |
|------|---:|
| city_nrmse_6_19 | 3.9531% |
| city_nrmse_10_14 | 6.2359% |
| site_mean_nrmse_6_19 | 11.4095% |
| bias_6_19 | +1.42% |
| bias_10_14 | +8.40% |
| 变差 > +1pp 站点数 | 0 |

## 预测来源

`power_pred_final` = `power_pred_round61_city_safe`

含三层后处理校准：
1. Round60 hour_scene calibrator（保守，valid 回退）
2. Round60 site calibrator（保守，valid 回退）
3. Round61 city_total calibrator（小时级，站点/小时保护）

## 回退方式

如果后续实验导致结果恶化，可回退：

```bash
# 恢复代码
git checkout round61-stable-20260601

# 恢复产物（需手动从备份目录复制）
# 产物位于: output/pv_pipeline/baselines/round61/
```

完整文件清单见 `round61_baseline_files.csv`。
"""

(ROOT / "docs/Round61_稳定基线说明.md").write_text(doc, encoding="utf-8")
print(f"[OK] Stable baseline doc: {ROOT / 'docs/Round61_稳定基线说明.md'}")

print(f"\n{'='*60}")
print(f"[OK] Round61 baseline manifest complete")
print(f"  Manifest: {BASE / 'round61_baseline_manifest.json'}")
print(f"  Files CSV: {BASE / 'round61_baseline_files.csv'}")
print(f"  Stable doc: {ROOT / 'docs/Round61_稳定基线说明.md'}")
print(f"{'='*60}")
