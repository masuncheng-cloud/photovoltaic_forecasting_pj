#!/usr/bin/env python3
"""
audit_training_pipeline_flow.py
===============================
训练链路审计工具。

两种执行级别：
  --level quick（默认）：只检查 manifest 中列出的 canonical 文件，输出站点级诊断，不扫描历史文件
  --level full          ：允许扫描更多中间产物，用于排查疑难问题

用法：
    python scripts/audit_training_pipeline_flow.py
    python scripts/audit_training_pipeline_flow.py --level quick
    python scripts/audit_training_pipeline_flow.py --level full
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scripts.common_paths import load_config, output_root
except ImportError:
    def load_config(cfg_path=None):
        import yaml
        path = Path(cfg_path) if cfg_path else PROJECT_ROOT / "configs" / "pipeline.yaml"
        with open(path) as f:
            return yaml.safe_load(f)
    def output_root(cfg):
        return PROJECT_ROOT / cfg.get("data", {}).get("output_root", "output/pv_pipeline")


def audit_quick(cfg: dict) -> list[dict]:
    """快速审计：只检查 manifest canonical 文件 + 站点元数据。"""
    results = []
    out = output_root(cfg)

    manifest_path = out / "manifest.json"
    if not manifest_path.exists():
        results.append({"check": "manifest_exists", "status": "FAIL", "detail": "manifest.json 不存在"})
        return results

    try:
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        results.append({"check": "manifest_exists", "status": "PASS", "detail": "manifest.json 存在"})
    except Exception as e:
        results.append({"check": "manifest_json_valid", "status": "FAIL", "detail": str(e)})
        return results

    # 检查 canonical artifacts
    arts = m.get("artifacts", {})
    for art_name, art_rel in arts.items():
        art_path = PROJECT_ROOT / art_rel
        if art_path.exists():
            results.append({"check": f"artifact_{art_name}", "status": "PASS", "detail": f"{art_rel} 存在"})
        else:
            results.append({"check": f"artifact_{art_name}", "status": "FAIL", "detail": f"{art_rel} 缺失"})

    # 检查站点元数据中的 S115/S116
    sm_path = out / "tables" / "site_master.csv"
    if sm_path.exists():
        try:
            sm = pd.read_csv(sm_path)
            lat_col = "lat" if "lat" in sm.columns else "latitude"
            lon_col = "lon" if "lon" in sm.columns else "longitude"
            for sid in ["S115", "S116"]:
                row = sm[sm["site_id"] == sid]
                if len(row) == 0:
                    results.append({"check": f"geo_{sid}_in_site_master", "status": "WARN", "detail": f"{sid} 不在 site_master.csv"})
                else:
                    lat = row[lat_col].values[0]
                    lon = row[lon_col].values[0]
                    if pd.isna(lat) or pd.isna(lon):
                        results.append({"check": f"geo_{sid}_coordinates", "status": "FAIL", "detail": f"{sid} lat/lon 为空"})
                    else:
                        results.append({"check": f"geo_{sid}_coordinates", "status": "PASS",
                                       "detail": f"{sid} lat={lat:.4f}, lon={lon:.4f}"})
        except Exception as e:
            results.append({"check": "site_master_readable", "status": "FAIL", "detail": str(e)})
    else:
        results.append({"check": "site_master_exists", "status": "FAIL", "detail": "site_master.csv 不存在"})

    return results


def audit_full(cfg: dict) -> list[dict]:
    """完整审计：检查更多中间产物和历史文件。"""
    results = []
    out = output_root(cfg)

    # 先做 quick 审计
    results.extend(audit_quick(cfg))

    # 检查 predictions 目录中的历史文件
    preds_dir = out / "predictions"
    if preds_dir.exists():
        pkl_files = list(preds_dir.glob("*.pkl"))
        results.append({
            "check": "predictions_pkl_count",
            "status": "PASS",
            "detail": f"predictions 目录有 {len(pkl_files)} 个 pkl 文件"
        })

    # 检查 metrics 目录
    metrics_dir = out / "metrics"
    if metrics_dir.exists():
        csv_files = list(metrics_dir.glob("*.csv"))
        results.append({
            "check": "metrics_csv_count",
            "status": "PASS",
            "detail": f"metrics 目录有 {len(csv_files)} 个 csv 文件"
        })

        # 检查 consistent 文件
        for fname in ["hourly_nrmse_consistent.csv", "site_metrics_consistent.csv"]:
            p = metrics_dir / fname
            if p.exists():
                results.append({"check": f"metric_{fname}", "status": "PASS", "detail": f"{fname} 存在"})
            else:
                results.append({"check": f"metric_{fname}", "status": "WARN", "detail": f"{fname} 不存在"})

    # 检查 dashboard
    dash_dir = out / "interactive_dashboard"
    if dash_dir.exists():
        idx = dash_dir / "index.json"
        if idx.exists():
            try:
                idx_data = json.loads(idx.read_text(encoding="utf-8"))
                results.append({
                    "check": "dashboard_index_valid",
                    "status": "PASS",
                    "detail": f"dashboard index 有效，{idx_data.get('total_sites', '?')} 个站点"
                })
            except Exception as e:
                results.append({"check": "dashboard_index_valid", "status": "FAIL", "detail": str(e)})
        else:
            results.append({"check": "dashboard_index_exists", "status": "FAIL", "detail": "index.json 不存在"})

        site_series = dash_dir / "site_series"
        if site_series.exists():
            n_sites = len(list(site_series.glob("S*.json")))
            results.append({"check": "dashboard_site_series_count", "status": "PASS", "detail": f"{n_sites} 个站点 JSON"})

    # 验证 final pkl 的完整性
    final_pkl = out / "predictions" / "distributed_predictions_final_full.pkl"
    if final_pkl.exists():
        try:
            df = pd.read_pickle(final_pkl)
            n_sites = df["site_id"].nunique()
            has_split = "split" in df.columns
            has_pred_col = "power_pred_final" in df.columns
            results.append({
                "check": "final_pkl_structure",
                "status": "PASS",
                "detail": f"{n_sites} 站, split={'有' if has_split else '无'}, power_pred_final={'有' if has_pred_col else '无'}"
            })
            # 检查 S115/S116
            for sid in ["S115", "S116"]:
                site_df = df[df["site_id"] == sid]
                if site_df.empty:
                    results.append({"check": f"final_pkl_{sid}", "status": "WARN", "detail": f"{sid} 不在 final pkl 中"})
                else:
                    has_lat = "latitude" in df.columns and site_df["latitude"].notna().any()
                    results.append({
                        "check": f"final_pkl_{sid}_geo",
                        "status": "PASS" if has_lat else "WARN",
                        "detail": f"{sid} 在 final pkl 中，latitude={'有效' if has_lat else '无效'}"
                    })
        except Exception as e:
            results.append({"check": "final_pkl_readable", "status": "FAIL", "detail": str(e)})
    else:
        results.append({"check": "final_pkl_exists", "status": "FAIL", "detail": "distributed_predictions_final_full.pkl 不存在"})

    return results


def main():
    parser = argparse.ArgumentParser(description="训练链路审计")
    parser.add_argument("--level", type=str, choices=["quick", "full"], default="quick",
                        help="审计级别: quick（默认，只检查 manifest canonical 文件）或 full（排查疑难问题）")
    parser.add_argument("--config", type=str, default=None, help="pipeline.yaml 路径")
    parser.add_argument("--output", type=str, default=None, help="输出 CSV 路径")
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(f"[FAIL] 配置未找到: {e}")
        sys.exit(1)

    print("=" * 60)
    print(f"训练链路审计 — level={args.level}")
    print("=" * 60)

    if args.level == "quick":
        results = audit_quick(cfg)
    else:
        results = audit_full(cfg)

    # 汇总
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    n_warn = sum(1 for r in results if r["status"] == "WARN")

    print(f"\n审计结果: {len(results)} 项 | {n_pass} PASS | {n_fail} FAIL | {n_warn} WARN")
    print()
    for r in results:
        icon = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠"}.get(r["status"], "?")
        print(f"  [{icon} {r['status']}] {r['check']}: {r['detail']}")

    # 写出 CSV
    out_path = args.output
    if out_path:
        out_df = pd.DataFrame(results)
        out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"\n[OK] 审计结果 → {out_path}")
    else:
        out_dir = output_root(cfg)
        out_path = out_dir / "validation" / f"pipeline_audit_{args.level}.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_df = pd.DataFrame(results)
        out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"\n[OK] 审计结果 → {out_path}")

    sys.exit(1 if n_fail > 0 else 0)


if __name__ == "__main__":
    main()
