#!/usr/bin/env python3
"""
diagnose_geo_feature_flow.py
============================
诊断 S115/S116 经纬度到最终预测特征的传递链路。
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path("/home/ac/data16t/msc/photovoltaic_forecasting_pj")
TARGETS = {"S115", "S116"}
OUT = ROOT / "output/pv_pipeline/validation/round54_geo_feature_flow.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

rows = []

def inspect_df(path, df):
    # 支持 site_id 或 station_id
    id_col = "site_id" if "site_id" in df.columns else "station_id" if "station_id" in df.columns else None
    if id_col is None:
        return
    hit = df[df[id_col].astype(str).isin(TARGETS)].copy()
    if hit.empty:
        return
    for sid, sdf in hit.groupby(id_col):
        sid = str(sid)
        row = {
            "file": str(path.relative_to(ROOT)),
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

# 扫描所有 pkl 和 CSV
for path in sorted(ROOT.rglob("*.pkl")):
    if "archive" in path.parts or "site_series" in path.parts:
        continue
    try:
        inspect_df(path, pd.read_pickle(path))
    except Exception:
        pass

for path in sorted(ROOT.rglob("*.csv")):
    if "archive" in path.parts or path.name.startswith("."):
        continue
    try:
        inspect_df(path, pd.read_csv(path))
    except Exception:
        pass

# 特殊：manual geo overrides
override_path = ROOT / "configs/manual_station_geo_overrides.csv"
if override_path.exists():
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

out_df = pd.DataFrame(rows)
out_df.to_csv(OUT, index=False, encoding="utf-8-sig")
print(f"[OK] written {OUT}, rows={len(out_df)}")

# 打印摘要
key_cols = ["file", "station_id", "rows",
             "latitude", "longitude", "lat", "lon",
             "has_geo", "has_geo_mean",
             "clear_sky_ghi_max", "g_blend_pred_max",
             "solar_elevation_deg_max", "scene_v151",
             "scene_v151_counts"]
cols = [c for c in key_cols if c in out_df.columns]
print("\n=== 链路摘要 ===")
print(out_df[cols].to_string(index=False))
