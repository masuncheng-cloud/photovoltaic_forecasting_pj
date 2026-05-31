#!/usr/bin/env python3
"""
diagnose_s115_s116_prediction_flow.py
====================================
诊断 S115/S116 在各产物层级中的 scene_v151 / g_blend_pred / power_pred_final 状态。

目的：判断异常发生在 v159 → final_round36 → canonical_final 中的哪一步。

用法：
    python scripts/diagnose_s115_s116_prediction_flow.py
"""

from pathlib import Path
import json
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline/validation/round56_s115_s116_prediction_flow.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

TARGETS = ["S115", "S116"]

FILES = [
    "output/pv_pipeline/tables/distributed_predictions_v159.pkl",
    "output/pv_pipeline/tables/distributed_predictions_final_round36.pkl",
    "output/pv_pipeline/tables/distributed_predictions_final_eval_round36.pkl",
    "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl",
    "output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl",
    "output/pv_pipeline/metrics/site_metrics_consistent.csv",
    "output/pv_pipeline/metrics/hourly_nrmse_consistent.csv",
]


def summarize_frame(path: Path, df: pd.DataFrame):
    rows = []

    # 支持 site_id 和 station_id
    id_col = None
    for col in ["station_id", "site_id"]:
        if col in df.columns:
            id_col = col
            break
    if id_col is None:
        return rows

    sdf_all = df[df[id_col].astype(str).isin(TARGETS)].copy()
    if sdf_all.empty:
        return rows

    # 统一 time 列
    if "timestamp" in sdf_all.columns:
        sdf_all["_time"] = pd.to_datetime(sdf_all["timestamp"], errors="coerce")
    elif "time" in sdf_all.columns:
        sdf_all["_time"] = pd.to_datetime(sdf_all["time"], errors="coerce")
    else:
        sdf_all["_time"] = pd.NaT

    if "_time" in sdf_all.columns and "_time" not in sdf_all.columns or "_time" not in sdf_all.columns:
        sdf_all["_hour"] = sdf_all["_time"].dt.hour
    else:
        sdf_all["_hour"] = np.nan

    scopes = {
        "all": sdf_all,
    }
    if "split" in sdf_all.columns:
        scopes["test"] = sdf_all[sdf_all["split"] == "test"].copy()
        scopes["test_6_19"] = sdf_all[
            (sdf_all["split"] == "test") & (sdf_all["_hour"].between(6, 19))
        ].copy()
        scopes["test_10_14"] = sdf_all[
            (sdf_all["split"] == "test") & (sdf_all["_hour"].between(10, 14))
        ].copy()
        scopes["train_valid"] = sdf_all[sdf_all["split"].isin(["train", "valid"])].copy()
    elif "_hour" in sdf_all.columns:
        scopes["test_6_19"] = sdf_all[sdf_all["_hour"].between(6, 19)].copy()
        scopes["test_10_14"] = sdf_all[sdf_all["_hour"].between(10, 14)].copy()

    for label, part in scopes.items():
        if part.empty:
            continue
        row = {
            "file": str(path.relative_to(ROOT)),
            "station_id": "",  # 填到循环里
            "scope": label,
            "rows": len(part),
            "mtime": path.stat().st_mtime if path.exists() else np.nan,
        }

        for col in [
            "station_name", "site_name", "capacity_mw",
            "latitude", "longitude", "lat", "lon",
            "has_geo",
            "solar_elevation_deg", "solar_altitude_deg",
            "clear_sky_ghi", "clearsky_ghi",
            "g_blend_pred",
            "scene_v151", "scene",
            "power_mw",
            "power_pred", "power_pred_cal", "power_pred_final",
        ]:
            if col not in part.columns:
                continue
            s = part[col]
            if s.dtype == object or str(s.dtype) == "string":
                vc = s.astype(str).value_counts(dropna=False).head(8).to_dict()
                row[f"{col}_values"] = json.dumps(vc, ensure_ascii=False)
            else:
                sn = pd.to_numeric(s, errors="coerce")
                row[f"{col}_non_null"] = int(sn.notna().sum())
                row[f"{col}_zero_ratio"] = float(
                    (sn.fillna(0).abs() < 1e-12).mean()
                ) if len(sn) else np.nan
                row[f"{col}_min"] = float(sn.min()) if sn.notna().any() else np.nan
                row[f"{col}_mean"] = float(sn.mean()) if sn.notna().any() else np.nan
                row[f"{col}_max"] = float(sn.max()) if sn.notna().any() else np.nan
        rows.append(row)

    # Per-station breakdown for key scopes
    for scope_label, part_scope in scopes.items():
        if part_scope.empty:
            continue
        for sid, sdf in part_scope.groupby(id_col):
            sid = str(sid)
            row = {
                "file": str(path.relative_to(ROOT)),
                "station_id": sid,
                "scope": scope_label,
                "rows": len(sdf),
                "mtime": path.stat().st_mtime if path.exists() else np.nan,
            }
            for col in [
                "has_geo",
                "solar_elevation_deg",
                "clear_sky_ghi", "clearsky_ghi",
                "g_blend_pred",
                "scene_v151", "scene",
                "power_mw",
                "power_pred", "power_pred_cal", "power_pred_final",
            ]:
                if col not in sdf.columns:
                    continue
                s = sdf[col]
                if s.dtype == object or str(s.dtype) == "string":
                    vc = s.astype(str).value_counts(dropna=False).head(8).to_dict()
                    row[f"{col}_values"] = json.dumps(vc, ensure_ascii=False)
                else:
                    sn = pd.to_numeric(s, errors="coerce")
                    row[f"{col}_non_null"] = int(sn.notna().sum())
                    row[f"{col}_zero_ratio"] = float(
                        (sn.fillna(0).abs() < 1e-12).mean()
                    ) if len(sn) else np.nan
                    row[f"{col}_mean"] = float(sn.mean()) if sn.notna().any() else np.nan
                    row[f"{col}_max"] = float(sn.max()) if sn.notna().any() else np.nan
            rows.append(row)

    return rows


all_rows = []
for f in FILES:
    path = ROOT / f
    if not path.exists():
        all_rows.append({
            "file": f, "station_id": "", "scope": "MISSING", "rows": 0
        })
        continue
    try:
        if path.suffix == ".pkl":
            df = pd.read_pickle(path)
        elif path.suffix == ".csv":
            df = pd.read_csv(path)
        else:
            continue
        rows = summarize_frame(path, df)
        if rows:
            all_rows.extend(rows)
        else:
            # 无 S115/S116 数据
            all_rows.append({
                "file": f, "station_id": "", "scope": "no_s115_s116", "rows": len(df)
            })
    except Exception as exc:
        all_rows.append({
            "file": f, "station_id": "", "scope": "ERROR", "rows": 0,
            "error": repr(exc)
        })

out = pd.DataFrame(all_rows)
out.to_csv(OUT, index=False, encoding="utf-8-sig")
print(f"[OK] written {OUT}, rows={len(out)}")

# 打印关键列
show_cols = [c for c in [
    "file", "station_id", "scope", "rows",
    "has_geo_mean", "has_geo_non_null",
    "solar_elevation_deg_mean", "solar_elevation_deg_max",
    "clear_sky_ghi_mean", "clear_sky_ghi_max",
    "clearsky_ghi_mean", "clearsky_ghi_max",
    "g_blend_pred_mean", "g_blend_pred_max",
    "scene_v151_values",
    "power_mw_mean",
    "power_pred_mean", "power_pred_max",
    "power_pred_final_mean", "power_pred_final_max",
    "power_pred_cal_mean", "power_pred_cal_max",
] if c in out.columns]

print("\n" + "=" * 120)
print("S115/S116 产物链路摘要")
print("=" * 120)
print(out[show_cols].to_string(index=False))
print("=" * 120)

# 诊断判定
print("\n=== 诊断判定 ===")
pred_cols = ["power_pred_final", "power_pred_cal", "power_pred"]
scene_cols = ["scene_v151", "scene"]
geo_cols = ["has_geo", "solar_elevation_deg", "clear_sky_ghi", "clearsky_ghi", "g_blend_pred"]

for f_rel in [
    "output/pv_pipeline/tables/distributed_predictions_v159.pkl",
    "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl",
    "output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl",
]:
    fpath = ROOT / f_rel
    fname = fpath.name
    sub = out[out["file"].str.contains(fpath.name, na=False)]
    if sub.empty:
        print(f"  {fname}: 未找到数据")
        continue

    for sid in TARGETS:
        s_rows = sub[sub["station_id"] == sid]
        if s_rows.empty:
            print(f"  {fname} {sid}: 无数据")
            continue

        # test scope
        t = s_rows[s_rows["scope"] == "test_10_14"]
        if t.empty:
            t = s_rows[s_rows["scope"] == "test_6_19"]
        if t.empty:
            t = s_rows[s_rows["scope"] == "test"]

        if t.empty:
            print(f"  {fname} {sid}: 无 test scope 数据")
            continue

        t = t.iloc[0]

        # 提取 scene_v151
        scene_vals = t.get("scene_v151_values", "{}")
        try:
            scene_dict = json.loads(scene_vals)
        except Exception:
            scene_dict = {}
        scene_all_night = set(scene_dict.keys()) <= {"night"} if scene_dict else None

        # 提取 g_blend_pred
        gblend_mean = t.get("g_blend_pred_mean", np.nan)
        gblend_max = t.get("g_blend_pred_max", np.nan)

        # 提取 pred_final
        pred_vals = {}
        for pc in pred_cols:
            v = t.get(f"{pc}_mean", np.nan)
            if not np.isnan(v):
                pred_vals[pc] = v

        all_zero = all(abs(v) < 1e-12 for v in pred_vals.values())

        print(f"\n  {fname} {sid} (test_10_14):")
        print(f"    scene_v151: {scene_dict or 'N/A'}  → all_night={scene_all_night}")
        print(f"    g_blend_pred: mean={gblend_mean}, max={gblend_max}")
        if pred_vals:
            for pc, v in pred_vals.items():
                print(f"    {pc}: mean={v:.4f}")
        else:
            print(f"    power_pred_*: all NaN")
        print(f"    all_zero_pred: {all_zero}")

print("\n=== 判定结论 ===")
v159_sub = out[out["file"].str.contains("distributed_predictions_v159", na=False)]
canonical_sub = out[out["file"].str.contains("distributed_predictions_final_full", na=False)]

for sid in TARGETS:
    v159_t = v159_sub[(v159_sub["station_id"] == sid) & (v159_sub["scope"] == "test_10_14")]
    can_t = canonical_sub[(canonical_sub["station_id"] == sid) & (canonical_sub["scope"] == "test_10_14")]

    v159_night = False
    v159_gblend_ok = False
    v159_pred_ok = False
    can_night = False
    can_gblend_ok = False
    can_pred_ok = False

    if not v159_t.empty:
        row = v159_t.iloc[0]
        sv = row.get("scene_v151_values", "{}")
        try:
            sd = json.loads(sv)
            v159_night = set(sd.keys()) <= {"night"} if sd else False
        except Exception:
            pass
        v159_gblend_ok = bool(row.get("g_blend_pred_max", 0) > 1e-9)
        for pc in pred_cols:
            if not np.isnan(row.get(f"{pc}_mean", np.nan)):
                v159_pred_ok = True
                break

    if not can_t.empty:
        row = can_t.iloc[0]
        sv = row.get("scene_v151_values", "{}")
        try:
            sd = json.loads(sv)
            can_night = set(sd.keys()) <= {"night"} if sd else False
        except Exception:
            pass
        can_gblend_ok = bool(row.get("g_blend_pred_max", 0) > 1e-9)
        for pc in pred_cols:
            if not np.isnan(row.get(f"{pc}_mean", np.nan)):
                can_pred_ok = True
                break

    print(f"\n  {sid}:")
    print(f"    v159:        scene_all_night={v159_night}, gblend>0={v159_gblend_ok}, pred>0={v159_pred_ok}")
    print(f"    canonical:    scene_all_night={can_night}, gblend>0={can_gblend_ok}, pred>0={can_pred_ok}")

    # 判定
    if not v159_night and v159_pred_ok and can_night and not can_pred_ok:
        print(f"    → 情况 A: v159正常，但canonical回退了（后处理/校准/同步覆盖）")
    elif not v159_night and v159_pred_ok and not can_night and can_pred_ok:
        print(f"    → B: v159和canonical都正常，dashboard异常")
    elif v159_night or not v159_pred_ok:
        print(f"    → 情况 C: v159本身异常，需要 geo-refresh 或 full")
    elif not v159_night and v159_pred_ok and can_night and can_pred_ok:
        print(f"    → 情况 B 变体: 两者都正常（scene_all_night但pred>0）")
    else:
        print(f"    → 需进一步诊断（情况 D 或矛盾）")
