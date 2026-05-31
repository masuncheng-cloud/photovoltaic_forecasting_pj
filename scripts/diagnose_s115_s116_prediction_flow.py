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


def _normalize_time(df: pd.DataFrame) -> pd.DataFrame:
    """统一添加 _time 和 _hour 列。"""
    df = df.copy()
    if "timestamp" in df.columns:
        df["_time"] = pd.to_datetime(df["timestamp"], errors="coerce")
    elif "time" in df.columns:
        df["_time"] = pd.to_datetime(df["time"], errors="coerce")
    else:
        df["_time"] = pd.NaT

    if df["_time"].notna().any():
        df["_hour"] = df["_time"].dt.hour
    else:
        df["_hour"] = np.nan
    return df


def _build_scopes(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """构建 scope 分组。"""
    scopes = {"all": df}
    if "split" in df.columns:
        for split_val in df["split"].unique():
            scopes[f"split_{split_val}"] = df[df["split"] == split_val].copy()
        test_df = df[df["split"] == "test"].copy()
        if "_hour" in test_df.columns:
            scopes["test_6_19"] = test_df[test_df["_hour"].between(6, 19)]
            scopes["test_10_14"] = test_df[test_df["_hour"].between(10, 14)]
        scopes["train_valid"] = df[df["split"].isin(["train", "valid"])].copy()
    elif "_hour" in df.columns:
        scopes["hours_6_19"] = df[df["_hour"].between(6, 19)]
        scopes["hours_10_14"] = df[df["_hour"].between(10, 14)]
    return {k: v for k, v in scopes.items() if not v.empty}


def summarize_frame(path: Path, df: pd.DataFrame) -> list[dict]:
    """对每个 station 逐 scope 汇总统计。"""
    rows = []
    id_col = None
    for col in ["station_id", "site_id"]:
        if col in df.columns:
            id_col = col
            break
    if id_col is None:
        return rows

    df = _normalize_time(df)
    df[id_col] = df[id_col].astype(str)

    # Per-scope 全站汇总
    scopes = _build_scopes(df)
    for scope_name, scope_df in scopes.items():
        row = _summarize_one(scope_name, "", scope_df, path)
        rows.append(row)

    # Per-station per-scope
    for sid in TARGETS:
        sid_df = df[df[id_col] == sid]
        if sid_df.empty:
            continue
        for scope_name, scope_df in _build_scopes(sid_df).items():
            row = _summarize_one(scope_name, sid, scope_df, path)
            rows.append(row)

    return rows


def _summarize_one(scope_name: str, station_id: str, df: pd.DataFrame, path: Path) -> dict:
    """汇总一个 (station, scope) 的统计。"""
    row = {
        "file": str(path.relative_to(ROOT)),
        "station_id": station_id,
        "scope": scope_name,
        "rows": len(df),
        "mtime": path.stat().st_mtime if path.exists() else np.nan,
    }
    STAT_COLS = [
        "latitude", "longitude", "lat", "lon",
        "has_geo",
        "solar_elevation_deg", "solar_altitude_deg",
        "clear_sky_ghi", "clearsky_ghi",
        "g_blend_pred",
        "scene_v151", "scene",
        "power_mw",
        "power_pred", "power_pred_cal", "power_pred_final",
    ]
    for col in STAT_COLS:
        if col not in df.columns:
            continue
        s = df[col]
        if s.dtype == object or str(s.dtype) == "string":
            vc = s.astype(str).value_counts(dropna=False).head(8)
            row[f"{col}_values"] = json.dumps(dict(vc), ensure_ascii=False)
        else:
            sn = pd.to_numeric(s, errors="coerce")
            row[f"{col}_n"] = int(sn.notna().sum())
            row[f"{col}_mean"] = float(sn.mean()) if sn.notna().any() else np.nan
            row[f"{col}_max"] = float(sn.max()) if sn.notna().any() else np.nan
            row[f"{col}_zero_ratio"] = float(
                (sn.fillna(0).abs() < 1e-12).mean()
            ) if len(sn) else np.nan
    return row


all_rows = []
for f in FILES:
    path = ROOT / f
    if not path.exists():
        all_rows.append({"file": f, "station_id": "", "scope": "MISSING", "rows": 0})
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
            all_rows.append({"file": f, "station_id": "", "scope": "no_s115_s116", "rows": len(df)})
    except Exception as exc:
        all_rows.append({"file": f, "station_id": "", "scope": "ERROR", "rows": 0, "error": repr(exc)})

out = pd.DataFrame(all_rows)
out.to_csv(OUT, index=False, encoding="utf-8-sig")
print(f"[OK] written {OUT}, rows={len(out)}")

# ── 打印关键列 ──────────────────────────────────────────────────────────────
show_cols = [c for c in [
    "file", "station_id", "scope", "rows",
    "has_geo_n", "has_geo_mean",
    "solar_elevation_deg_mean", "solar_elevation_deg_max",
    "clear_sky_ghi_mean", "clear_sky_ghi_max",
    "g_blend_pred_mean", "g_blend_pred_max",
    "scene_v151_values",
    "power_mw_mean",
    "power_pred_mean", "power_pred_max",
    "power_pred_final_mean", "power_pred_final_max",
] if c in out.columns]

print("\n" + "=" * 120)
print("S115/S116 产物链路摘要")
print("=" * 120)
# 只打印包含 S115/S116 的行或全站 test scope
mask = (out["station_id"].isin(TARGETS)) | (
    (out["station_id"] == "") & out["scope"].isin(["test_10_14", "test_6_19", "test"])
)
print(out[show_cols][mask].to_string(index=False))
print("=" * 120)

# ── 诊断判定 ───────────────────────────────────────────────────────────────
print("\n=== 诊断判定 ===")

file_aliases = {
    "distributed_predictions_v159.pkl": "v159",
    "distributed_predictions_final_full.pkl": "canonical_full",
    "distributed_predictions_final_eval.pkl": "canonical_eval",
    "distributed_predictions_final_round36.pkl": "round36_final",
    "distributed_predictions_final_eval_round36.pkl": "round36_eval",
}

PRED_COLS = ["power_pred_final", "power_pred_cal", "power_pred"]

for sid in TARGETS:
    print(f"\n  ─ {sid} ─")
    for fname_key, fname_alias in file_aliases.items():
        sub = out[out["file"].str.contains(fname_key, na=False) & (out["station_id"] == sid)]
        if sub.empty:
            print(f"    {fname_alias}: 无 {sid} 数据")
            continue

        # 优先用 test_10_14，其次 test_6_19，再次 test
        t = sub[sub["scope"] == "test_10_14"]
        if t.empty:
            t = sub[sub["scope"] == "test_6_19"]
        if t.empty:
            t = sub[sub["scope"] == "test"]

        if t.empty:
            print(f"    {fname_alias}: 无 test scope")
            continue

        row = t.iloc[0]

        scene_raw = row.get("scene_v151_values", "{}")
        try:
            scene_dict = json.loads(scene_raw)
        except Exception:
            scene_dict = {}
        scene_all_night = (set(scene_dict.keys()) <= {"night"}) if scene_dict else "N/A"

        gblend_max = row.get("g_blend_pred_max", np.nan)
        gblend_mean = row.get("g_blend_pred_mean", np.nan)

        pred_vals = {}
        for pc in PRED_COLS:
            v = row.get(f"{pc}_mean", np.nan)
            if not np.isnan(v):
                pred_vals[pc] = v
        all_zero = all(abs(v) < 1e-12 for v in pred_vals.values()) if pred_vals else True

        print(f"    {fname_alias} test_10_14:")
        print(f"      scene_v151 = {scene_dict}")
        print(f"      all_night = {scene_all_night}")
        print(f"      g_blend_pred: mean={gblend_mean:.2f}, max={gblend_max:.2f}")
        if pred_vals:
            for pc, v in pred_vals.items():
                print(f"      {pc}: mean={v:.4f}")
        else:
            print(f"      power_pred_*: 全部 NaN")
        print(f"      all_zero_pred = {all_zero}")

print("\n=== 判定结论 ===")
for sid in TARGETS:
    print(f"\n  {sid}:")
    v159_r = _get_best_row(out, sid, "distributed_predictions_v159.pkl")
    can_r = _get_best_row(out, sid, "distributed_predictions_final_full.pkl")

    def row_summary(r):
        if r is None:
            return "无数据"
        scene_raw = r.get("scene_v151_values", "{}")
        try:
            sd = json.loads(scene_raw)
        except Exception:
            sd = {}
        all_night = (set(sd.keys()) <= {"night"}) if sd else "N/A"
        gblend_max = r.get("g_blend_pred_max", np.nan)
        pred_vals = [r.get(f"{pc}_mean", np.nan) for pc in PRED_COLS]
        has_nonzero = any(not np.isnan(v) and abs(v) > 1e-12 for v in pred_vals)
        return f"all_night={all_night}, gblend_max={gblend_max:.2f}, pred>0={has_nonzero}"

    v_str = row_summary(v159_r)
    c_str = row_summary(can_r)
    print(f"    v159:        {v_str}")
    print(f"    canonical:    {c_str}")

    if v159_r is not None and can_r is not None:
        v_scene_raw = v159_r.get("scene_v151_values", "{}")
        c_scene_raw = can_r.get("scene_v151_values", "{}")
        try:
            v_sd = json.loads(v_scene_raw)
            c_sd = json.loads(c_scene_raw)
            v_all_night = (set(v_sd.keys()) <= {"night"}) if v_sd else False
            c_all_night = (set(c_sd.keys()) <= {"night"}) if c_sd else False
        except Exception:
            v_all_night = c_all_night = None

        v_nonzero = any(
            not np.isnan(v159_r.get(f"{pc}_mean", np.nan)) and
            abs(v159_r.get(f"{pc}_mean", 0)) > 1e-12
            for pc in PRED_COLS
        )
        c_nonzero = any(
            not np.isnan(can_r.get(f"{pc}_mean", np.nan)) and
            abs(can_r.get(f"{pc}_mean", 0)) > 1e-12
            for pc in PRED_COLS
        )

        if not v_all_night and v_nonzero and c_all_night and not c_nonzero:
            print(f"    → 情况 A: v159正常，canonical回退（后处理/校准/同步覆盖）")
        elif not v_all_night and v_nonzero and not c_all_night and c_nonzero:
            print(f"    → 正常: v159和canonical都正常，scene有白天成分，pred非0")
        elif v_all_night or not v_nonzero:
            print(f"    → 情况 C: v159本身异常，需要 geo-refresh 或 full")
        else:
            print(f"    → 待进一步诊断（情况 D 或矛盾）")
    else:
        print(f"    → 数据不足，无法判定")


def _get_best_row(df: pd.DataFrame, sid: str, fname_contains: str) -> dict | None:
    """获取 best 可用 row（优先 test_10_14）。"""
    sub = df[df["file"].str.contains(fname_contains, na=False) & (df["station_id"] == sid)]
    if sub.empty:
        return None
    for scope in ["test_10_14", "test_6_19", "test"]:
        t = sub[sub["scope"] == scope]
        if not t.empty:
            return t.iloc[0].to_dict()
    return sub.iloc[0].to_dict()
