#!/usr/bin/env python3
"""
diagnose_s115_s116_prediction_flow.py
====================================
诊断 S115/S116 在各产物层级中的 scene_v151 / g_blend_pred / power_pred_final 状态。

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
    ("v159",           "output/pv_pipeline/tables/distributed_predictions_v159.pkl"),
    ("round36_final",  "output/pv_pipeline/tables/distributed_predictions_final_round36.pkl"),
    ("round36_eval",   "output/pv_pipeline/tables/distributed_predictions_final_eval_round36.pkl"),
    ("canonical_full", "output/pv_pipeline/predictions/distributed_predictions_final_full.pkl"),
    ("canonical_eval", "output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl"),
]

PRED_COLS = ["power_pred_final", "power_pred_cal", "power_pred"]


def _numeric_stats(s: pd.Series) -> dict:
    sn = pd.to_numeric(s, errors="coerce")
    return {
        "n": int(sn.notna().sum()),
        "mean": float(sn.mean()) if sn.notna().any() else np.nan,
        "max": float(sn.max()) if sn.notna().any() else np.nan,
        "zero_ratio": float((sn.fillna(0).abs() < 1e-9).mean()) if len(sn) else np.nan,
    }


def summarize(df: pd.DataFrame, alias: str, scope: str) -> dict:
    id_col = "site_id" if "site_id" in df.columns else "station_id" if "station_id" in df.columns else None
    row = {
        "file_alias": alias, "scope": scope, "station_id": "ALL",
        "rows": len(df),
    }
    if id_col:
        row["n_sites"] = int(df[id_col].nunique())
    for col in ["has_geo", "solar_elevation_deg", "clear_sky_ghi", "g_blend_pred",
                "scene_v151", "power_mw"] + PRED_COLS:
        if col not in df.columns:
            continue
        s = df[col]
        if s.dtype == object or str(s.dtype) == "string":
            vc = s.astype(str).value_counts(dropna=False).head(6)
            row[f"{col}_values"] = dict(vc)
        else:
            st = _numeric_stats(s)
            row[f"{col}_n"] = st["n"]
            row[f"{col}_mean"] = st["mean"]
            row[f"{col}_max"] = st["max"]
            row[f"{col}_zero_ratio"] = st["zero_ratio"]
    return row


def per_station_summarize(df: pd.DataFrame, alias: str, scope: str) -> list[dict]:
    """对 S115/S116 逐站汇总。"""
    id_col = "site_id" if "site_id" in df.columns else "station_id" if "station_id" in df.columns else None
    if id_col is None:
        return []
    rows = []
    for sid in TARGETS:
        sdf = df[df[id_col].astype(str) == sid]
        if sdf.empty:
            continue
        row = {
            "file_alias": alias, "scope": scope, "station_id": sid,
            "rows": len(sdf),
        }
        for col in ["has_geo", "solar_elevation_deg", "clear_sky_ghi", "g_blend_pred",
                    "scene_v151", "power_mw"] + PRED_COLS:
            if col not in sdf.columns:
                continue
            s = sdf[col]
            if s.dtype == object or str(s.dtype) == "string":
                vc = s.astype(str).value_counts(dropna=False).head(6)
                row[f"{col}_values"] = dict(vc)
            else:
                st = _numeric_stats(s)
                row[f"{col}_n"] = st["n"]
                row[f"{col}_mean"] = st["mean"]
                row[f"{col}_max"] = st["max"]
                row[f"{col}_zero_ratio"] = st["zero_ratio"]
        rows.append(row)
    return rows


def diagnose() -> pd.DataFrame:
    """执行诊断。"""
    all_rows = []

    for alias, rel_path in FILES:
        path = ROOT / rel_path
        if not path.exists():
            all_rows.append({
                "file_alias": alias, "file": rel_path,
                "station_id": "", "scope": "MISSING", "rows": 0
            })
            continue
        try:
            if path.suffix == ".pkl":
                df = pd.read_pickle(path)
            else:
                df = pd.read_csv(path)
        except Exception as exc:
            all_rows.append({
                "file_alias": alias, "file": rel_path,
                "station_id": "", "scope": "ERROR", "rows": 0,
                "error": repr(exc)
            })
            continue

        # 时间列
        time_col = "timestamp" if "timestamp" in df.columns else "time"
        if time_col in df.columns:
            df["_time"] = pd.to_datetime(df[time_col], errors="coerce")
            df["_hour"] = df["_time"].dt.hour
        else:
            df["_hour"] = np.nan

        has_split = "split" in df.columns
        if has_split:
            df["split"] = df["split"].astype(str)

        # 定义 scope：对全站，先按 split 选子集，再按 hour 选
        if has_split:
            scope_defs = [
                ("all",          df),
                ("train",        df[df["split"] == "train"]),
                ("valid",        df[df["split"] == "valid"]),
                ("test",         df[df["split"] == "test"]),
                ("test_6_19",    df[(df["split"] == "test") & df["_hour"].between(6, 19)]),
                ("test_10_14",   df[(df["split"] == "test") & df["_hour"].between(10, 14)]),
            ]
        else:
            # 无 split：v159 等，用 hour 划分
            scope_defs = [
                ("all",          df),
                ("hours_6_19",   df[df["_hour"].between(6, 19)]),
                ("hours_10_14",  df[df["_hour"].between(10, 14)]),
            ]

        for scope_name, scope_df in scope_defs:
            if scope_df.empty:
                continue
            # ALL 行
            all_rows.append(summarize(scope_df, alias, scope_name))
            # S115/S116 行
            all_rows.extend(per_station_summarize(scope_df, alias, scope_name))

    return pd.DataFrame(all_rows)


def _get_state(row: dict) -> dict | None:
    """从一行数据提取诊断状态。"""
    if row is None or row.get("rows", 0) == 0:
        return None
    sv = row.get("scene_v151_values", {})
    if isinstance(sv, str):
        try:
            sv = json.loads(sv)
        except Exception:
            sv = {}
    scene_keys = set(str(k) for k in sv.keys()) if sv else set()
    all_night = bool(scene_keys <= {"night"}) if scene_keys else False

    gblend_max = row.get("g_blend_pred_max", 0)
    gblend_ok = bool(gblend_max > 1e-9) if not np.isnan(gblend_max) else False

    pred_ok = False
    for pc in PRED_COLS:
        v = row.get(f"{pc}_mean", np.nan)
        if not np.isnan(v) and abs(v) > 1e-9:
            pred_ok = True
            break

    return {
        "all_night": all_night,
        "gblend_ok": gblend_ok,
        "pred_ok": pred_ok,
        "rows": row.get("rows", 0),
    }


def print_diagnosis(df: pd.DataFrame):
    """打印诊断结果。"""
    PREF_SCOPES = ["test_10_14", "test_6_19", "test", "valid", "train",
                   "hours_10_14", "hours_6_19", "all"]

    print("\n" + "=" * 160)
    print("S115/S116 产物链路诊断摘要")
    print("=" * 160)

    # 打印 S115/S116 行（按 scope）
    key_cols = [c for c in [
        "file_alias", "station_id", "scope", "rows",
        "g_blend_pred_mean", "g_blend_pred_max",
        "scene_v151_values",
        "power_pred_final_mean", "power_pred_final_max",
        "power_pred_cal_mean", "power_pred_cal_max",
        "power_mw_mean",
    ] if c in df.columns]

    sub = df[df["station_id"].isin(TARGETS)].copy()
    # 优先打印 test scope
    sub["_scope_order"] = sub["scope"].map(
        lambda s: PREF_SCOPES.index(s) if s in PREF_SCOPES else 99
    )
    sub = sub.sort_values(["station_id", "_scope_order"])

    def fmt_scene(v):
        if isinstance(v, dict):
            return str(v)
        if isinstance(v, str):
            try:
                return str(json.loads(v))
            except Exception:
                return v
        return str(v)

    sub["scene_v151_values"] = sub["scene_v151_values"].apply(fmt_scene)

    pd.set_option("display.max_colwidth", 50)
    pd.set_option("display.width", 200)
    print(sub[key_cols].to_string(index=False))
    print("=" * 160)

    # 判定
    print("\n=== 判定结论 ===")
    for sid in TARGETS:
        print(f"\n  {sid}:")
        for alias, _ in FILES:
            rows = df[(df["file_alias"] == alias) & (df["station_id"] == sid)]
            if rows.empty:
                continue

            # 最佳 scope
            best = None
            for sc in PREF_SCOPES:
                m = rows[rows["scope"] == sc]
                if not m.empty and m.iloc[0].get("rows", 0) > 0:
                    best = m.iloc[0].to_dict()
                    break
            if best is None:
                best = rows.iloc[0].to_dict()

            st = _get_state(best)
            if st is None:
                print(f"    {alias:20s}: 无数据")
                continue

            scene_vals = best.get("scene_v151_values", {})
            if isinstance(scene_vals, str):
                try:
                    scene_vals = json.loads(scene_vals)
                except Exception:
                    scene_vals = {}
            scene_str = str(dict(scene_vals))[:60] if scene_vals else "N/A"

            print(f"    {alias:20s} [{best['scope']}] rows={st['rows']:6d}: "
                  f"scene={scene_str} "
                  f"all_night={st['all_night']} "
                  f"gblend_ok={st['gblend_ok']} "
                  f"pred_ok={st['pred_ok']}")

        # 总体判定
        vs = None
        cs = None
        for alias, _ in FILES:
            rows = df[(df["file_alias"] == alias) & (df["station_id"] == sid)]
            if rows.empty:
                continue
            for sc in PREF_SCOPES:
                m = rows[rows["scope"] == sc]
                if not m.empty and m.iloc[0].get("rows", 0) > 0:
                    r = _get_state(m.iloc[0].to_dict())
                    if r is not None:
                        if alias == "v159":
                            vs = r
                        if alias == "canonical_full":
                            cs = r
                    break

        print(f"\n  汇总 {sid}:")
        print(f"    v159:       {vs}")
        print(f"    canonical:  {cs}")

        if vs is None or cs is None:
            print(f"    → 数据不足，无法判定")
        elif vs["pred_ok"] and cs["pred_ok"] and not vs["all_night"] and not cs["all_night"]:
            print(f"    → 正常: v159 和 canonical 都正常，pred非0，scene有白天成分")
        elif vs["pred_ok"] and cs["pred_ok"] and vs["all_night"] and cs["all_night"]:
            print(f"    → 情况 D: v159 和 canonical 都是 all_night，pred却非0（矛盾）")
        elif vs["pred_ok"] and not cs["pred_ok"] and cs["all_night"]:
            print(f"    → 情况 A: v159正常，canonical回退")
        elif not vs["pred_ok"] or vs["all_night"]:
            print(f"    → 情况 C: v159本身异常（all_night={vs['all_night'] if vs else 'N/A'} pred_ok={vs['pred_ok'] if vs else 'N/A'}）")


def main():
    df = diagnose()
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"[OK] written {OUT}, rows={len(df)}")
    print_diagnosis(df)


if __name__ == "__main__":
    main()
