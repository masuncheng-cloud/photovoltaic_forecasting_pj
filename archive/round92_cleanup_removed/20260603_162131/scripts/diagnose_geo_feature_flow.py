#!/usr/bin/env python3
"""
diagnose_geo_feature_flow.py
============================
诊断 S115/S116 经纬度到最终预测特征的传递链路。

默认只检查关键文件清单，不做全项目 rglob 扫描。
使用 --deep-scan 可启用完整扫描（排查疑难问题时）。

用法：
    python scripts/diagnose_geo_feature_flow.py
    python scripts/diagnose_geo_feature_flow.py --quick
    python scripts/diagnose_geo_feature_flow.py --deep-scan
"""

import argparse
import sys
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"S115", "S116"}

# 默认只检查以下关键文件（不扫描 archive/ 和历史产物）
FILES_TO_CHECK = [
    "configs/manual_station_geo_overrides.csv",
    "output/pv_pipeline/tables/station_metadata_canonical.pkl",
    "output/pv_pipeline/tables/station_metadata_canonical.csv",
    "output/pv_pipeline/tables/site_master.csv",
    "output/pv_pipeline/tables/train_features.pkl",
    "output/pv_pipeline/tables/power_clean.pkl",
    "output/pv_pipeline/tables/distributed_predictions_final_full.pkl",
    "output/pv_pipeline/tables/distributed_predictions_v159.pkl",
    "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl",
    "output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl",
    "output/pv_pipeline/metrics/site_metrics_consistent.csv",
    "output/pv_pipeline/metrics/hourly_nrmse_consistent.csv",
]

# deep scan 额外目录
DEEP_SCAN_EXTRAS = [
    "output/pv_pipeline/tables/",
    "output/pv_pipeline/predictions/",
    "output/pv_pipeline/metrics/",
    "output/pv_pipeline/validation/",
    "output/pv_pipeline/docs/",
]

rows = []


def inspect_df(path: Path, df: pd.DataFrame):
    id_col = "site_id" if "site_id" in df.columns else "station_id" if "station_id" in df.columns else None
    if id_col is None:
        return
    hit = df[df[id_col].astype(str).isin(TARGETS)].copy()
    if hit.empty:
        return
    for sid, sdf in hit.groupby(id_col):
        sid = str(sid)
        row = {
            "file": str(path.relative_to(PROJECT_ROOT)),
            "station_id": sid,
            "rows": len(sdf),
        }
        for col in [
            "latitude", "longitude", "lat", "lon",
            "has_geo", "geo_source", "geo_confidence",
            "clear_sky_ghi", "clearsky_ghi", "g_blend_pred",
            "solar_elevation_deg", "solar_altitude_deg",
            "scene_v151", "scene",
            "power_mw", "power_pred_final", "power_pred",
        ]:
            if col in sdf.columns:
                s = sdf[col]
                if s.dtype == object or str(s.dtype) == "string":
                    vals = s.dropna().astype(str).unique()[:8]
                    row[col] = "|".join(vals)
                else:
                    row[f"{col}_nn"] = int(s.notna().sum())
                    row[f"{col}_mean"] = float(pd.to_numeric(s, errors="coerce").mean()) if s.notna().any() else np.nan
                    row[f"{col}_max"] = float(pd.to_numeric(s, errors="coerce").max()) if s.notna().any() else np.nan
        if "scene_v151" in sdf.columns:
            row["scene_v151_counts"] = str(sdf["scene_v151"].astype(str).value_counts().head(5).to_dict())
        rows.append(row)


def scan_files(file_list: list[str]):
    """扫描指定文件清单。"""
    for rel_path in file_list:
        path = PROJECT_ROOT / rel_path
        if not path.exists():
            continue
        try:
            if path.suffix == ".pkl":
                inspect_df(path, pd.read_pickle(path))
            elif path.suffix == ".csv":
                inspect_df(path, pd.read_csv(path))
        except Exception:
            pass


def deep_scan():
    """深度扫描（仅 archive/ 排除）。"""
    for extra in DEEP_SCAN_EXTRAS:
        dir_path = PROJECT_ROOT / extra
        if not dir_path.exists():
            continue
        for path in sorted(dir_path.rglob("*.pkl")):
            try:
                inspect_df(path, pd.read_pickle(path))
            except Exception:
                pass
        for path in sorted(dir_path.rglob("*.csv")):
            if path.name.startswith("."):
                continue
            try:
                inspect_df(path, pd.read_csv(path))
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="诊断 S115/S116 经纬度链路")
    parser.add_argument("--deep-scan", action="store_true",
                        help="启用深度扫描（排查疑难问题，不作为默认步骤）")
    parser.add_argument("--quick", action="store_true",
                        help="等同于默认行为：只检查关键文件清单")
    parser.add_argument("--output", type=str, default=None,
                        help="输出 CSV 路径（默认: output/pv_pipeline/validation/geo_feature_flow.csv）")
    args = parser.parse_args()

    print(f"[INFO] Project root: {PROJECT_ROOT}")
    print(f"[INFO] Targets: {TARGETS}")
    print(f"[INFO] Mode: {'deep-scan' if args.deep_scan else 'quick (default file list only)'}")
    print()

    # 扫描手动覆盖文件
    override_path = PROJECT_ROOT / "configs" / "manual_station_geo_overrides.csv"
    if override_path.exists():
        try:
            df = pd.read_csv(override_path)
            for _, row in df.iterrows():
                rows.append({
                    "file": "configs/manual_station_geo_overrides.csv",
                    "station_id": str(row["station_id"]),
                    "rows": 1,
                    "latitude": str(row.get("latitude", "")),
                    "longitude": str(row.get("longitude", "")),
                    "geo_source": str(row.get("geo_source", "")),
                    "geo_confidence": str(row.get("confidence", "")),
                })
        except Exception:
            pass

    # 默认扫描关键文件清单
    scan_files(FILES_TO_CHECK)

    # deep scan 模式额外扫描
    if args.deep_scan:
        print("[INFO] 执行深度扫描...")
        deep_scan()

    # 写出结果
    out_path = args.output or PROJECT_ROOT / "output" / "pv_pipeline" / "validation" / "geo_feature_flow.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    out_df = pd.DataFrame(rows)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] written {out_path}, rows={len(out_df)}")

    # 打印摘要
    key_cols = ["file", "station_id", "rows",
                 "latitude", "longitude", "lat", "lon",
                 "has_geo", "has_geo_mean",
                 "clear_sky_ghi_max", "g_blend_pred_max",
                 "solar_elevation_deg_max", "scene_v151",
                 "scene_v151_counts"]
    cols = [c for c in key_cols if c in out_df.columns]
    print("\n=== 链路摘要 ===")
    print(out_df[cols].to_string(index=False) if cols else "(无数据)")


if __name__ == "__main__":
    main()
