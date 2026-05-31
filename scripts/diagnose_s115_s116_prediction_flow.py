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
    ("v159",          "output/pv_pipeline/tables/distributed_predictions_v159.pkl"),
    ("round36_final", "output/pv_pipeline/tables/distributed_predictions_final_round36.pkl"),
    ("round36_eval",  "output/pv_pipeline/tables/distributed_predictions_final_eval_round36.pkl"),
    ("canonical_full","output/pv_pipeline/predictions/distributed_predictions_final_full.pkl"),
    ("canonical_eval","output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl"),
]


def load_and_normalize(path: Path) -> tuple[pd.DataFrame, dict]:
    """加载 pkl/csv，返回 (df, meta)。meta 包含 id_col / has_split / scopes。"""
    meta = {}
    if path.suffix == ".pkl":
        df = pd.read_pickle(path)
    elif path.suffix == ".csv":
        df = pd.read_csv(path)
    else:
        return pd.DataFrame(), meta

    # id 列
    for col in ["station_id", "site_id"]:
        if col in df.columns:
            df[col] = df[col].astype(str)
            meta["id_col"] = col
            break

    # time 列
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

    # split 列
    meta["has_split"] = "split" in df.columns
    if meta["has_split"]:
        df["split"] = df["split"].astype(str)

    return df, meta


def build_scopes(df: pd.DataFrame, meta: dict) -> dict[str, pd.DataFrame]:
    """构建 scope 分组。"""
    scopes = {}
    if meta.get("has_split"):
        scopes["all"] = df
        for sp in ["train", "valid", "test", "future"]:
            sub = df[df.get("split", pd.Series()) == sp]
            if not sub.empty:
                scopes[f"test"] = sub
                break
        t = scopes.get("test", df)
        scopes["test"] = t
        if "_hour" in df.columns:
            scopes["test_6_19"] = t[t["_hour"].between(6, 19)]
            scopes["test_10_14"] = t[t["_hour"].between(10, 14)]
    else:
        scopes["all"] = df
        if "_hour" in df.columns:
            scopes["hours_6_19"] = df[df["_hour"].between(6, 19)]
            scopes["hours_10_14"] = df[df["_hour"].between(10, 14)]
    return {k: v for k, v in scopes.items() if not v.empty}


def summarize_scope(scope_df: pd.DataFrame) -> dict:
    """汇总一个 scope 的关键统计。"""
    row = {"rows": len(scope_df)}
    PRED_COLS = ["power_pred_final", "power_pred_cal", "power_pred"]
    for col in ["has_geo", "solar_elevation_deg", "clear_sky_ghi", "clearsky_ghi",
                "g_blend_pred", "scene_v151", "scene", "power_mw"] + PRED_COLS:
        if col not in scope_df.columns:
            continue
        s = scope_df[col]
        if s.dtype == object or str(s.dtype) == "string":
            vc = s.astype(str).value_counts(dropna=False).head(6)
            row[f"{col}_values"] = dict(vc)
        else:
            sn = pd.to_numeric(s, errors="coerce")
            row[f"{col}_n"] = int(sn.notna().sum())
            row[f"{col}_mean"] = float(sn.mean()) if sn.notna().any() else np.nan
            row[f"{col}_max"] = float(sn.max()) if sn.notna().any() else np.nan
            row[f"{col}_zero_ratio"] = float(
                (sn.fillna(0).abs() < 1e-9).mean()
            ) if len(sn) else np.nan
    return row


def diagnose() -> pd.DataFrame:
    """执行全链路诊断。"""
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
            df, meta = load_and_normalize(path)
            id_col = meta.get("id_col")
            if id_col is None:
                all_rows.append({
                    "file_alias": alias, "file": rel_path,
                    "station_id": "", "scope": "NO_ID_COL", "rows": len(df)
                })
                continue

            scopes = build_scopes(df, meta)

            # 全站 per-scope
            for scope_name, scope_df in scopes.items():
                summary = summarize_scope(scope_df)
                row = {
                    "file_alias": alias,
                    "file": str(path.relative_to(ROOT)),
                    "station_id": "ALL",
                    "scope": scope_name,
                }
                row.update(summary)
                all_rows.append(row)

            # S115/S116 per-scope
            for sid in TARGETS:
                sid_df = df[df[id_col] == sid]
                if sid_df.empty:
                    all_rows.append({
                        "file_alias": alias, "file": str(path.relative_to(ROOT)),
                        "station_id": sid, "scope": "NO_DATA", "rows": 0
                    })
                    continue
                for scope_name, scope_df in scopes.items():
                    # 对 v159 等无 split 的文件，scopes 来自全站，这里对站点再过滤
                    if meta.get("has_split"):
                        sub = sid_df
                    else:
                        sub = sid_df
                    summary = summarize_scope(sub)
                    row = {
                        "file_alias": alias,
                        "file": str(path.relative_to(ROOT)),
                        "station_id": sid,
                        "scope": scope_name,
                    }
                    row.update(summary)
                    all_rows.append(row)
        except Exception as exc:
            all_rows.append({
                "file_alias": alias, "file": rel_path,
                "station_id": "", "scope": "ERROR", "rows": 0,
                "error": repr(exc)
            })

    return pd.DataFrame(all_rows)


def print_diagnosis(df: pd.DataFrame):
    """打印诊断结果和判定。"""
    PRED_COLS = ["power_pred_final", "power_pred_cal", "power_pred"]

    # 打印摘要表
    key_cols = [
        "file_alias", "station_id", "scope", "rows",
        "g_blend_pred_mean", "g_blend_pred_max",
        "scene_v151_values",
        "power_pred_final_mean", "power_pred_final_max",
    ]
    key_cols = [c for c in key_cols if c in df.columns]

    # 过滤有意义行
    mask = (df["station_id"].isin(TARGETS + ["ALL"])) & ~df["scope"].isin(["MISSING", "NO_ID_COL", "ERROR"])
    sub = df[key_cols][mask].copy()
    sub["scene_v151_values"] = sub["scene_v151_values"].apply(
        lambda x: str(x) if isinstance(x, dict) else x
    )

    print("\n" + "=" * 140)
    print("S115/S116 产物链路摘要")
    print("=" * 140)
    pd.set_option("display.max_colwidth", 40)
    pd.set_option("display.width", 200)
    print(sub.to_string(index=False))
    print("=" * 140)

    # 判定
    print("\n=== 判定结论 ===")
    for sid in TARGETS:
        print(f"\n  {sid}:")
        for alias, _ in FILES:
            rows = df[(df["file_alias"] == alias) & (df["station_id"] == sid)]
            if rows.empty:
                continue

            # 找最佳 scope（优先 test_10_14）
            best_scope = None
            best_row = None
            for sc in ["test_10_14", "test_6_19", "test", "hours_10_14", "hours_6_19", "all"]:
                match = rows[rows["scope"] == sc]
                if not match.empty:
                    best_scope = sc
                    best_row = match.iloc[0]
                    break
            if best_row is None:
                best_row = rows.iloc[0]
                best_scope = rows.iloc[0]["scope"]

            scene_vals = best_row.get("scene_v151_values", {})
            if isinstance(scene_vals, dict):
                scene_keys = set(scene_vals.keys())
            else:
                scene_keys = set()

            scene_all_night = scene_keys <= {"night"} if scene_keys else False

            gblend_max = best_row.get("g_blend_pred_max", np.nan)
            gblend_mean = best_row.get("g_blend_pred_mean", np.nan)

            pred_nonzero = False
            for pc in PRED_COLS:
                v = best_row.get(f"{pc}_mean", np.nan)
                if not np.isnan(v) and abs(v) > 1e-9:
                    pred_nonzero = True
                    break

            rows_count = best_row.get("rows", 0)

            print(f"    {alias:20s} [{best_scope}] rows={rows_count}: "
                  f"scene={dict(scene_vals) if scene_vals else 'N/A'} "
                  f"all_night={scene_all_night} "
                  f"gblend_max={float(gblend_max):.1f} "
                  f"pred>0={pred_nonzero}")

        # 总体判定
        v159_r = df[(df["file_alias"] == "v159") & (df["station_id"] == sid)]
        can_r  = df[(df["file_alias"] == "canonical_full") & (df["station_id"] == sid)]

        def get_state(r):
            if r.empty:
                return None
            # best scope
            for sc in ["test_10_14", "test_6_19", "test", "hours_10_14", "hours_6_19", "all"]:
                m = r[r["scope"] == sc]
                if not m.empty:
                    r = m.iloc[0]
                    break
            sv = r.get("scene_v151_values", {})
            if isinstance(sv, dict):
                sk = set(sv.keys())
            else:
                sk = set()
            all_night = bool(sk <= {"night"}) if sk else False
            gblend_ok = bool(r.get("g_blend_pred_max", 0) > 1e-9)
            pred_ok = False
            for pc in PRED_COLS:
                v = r.get(f"{pc}_mean", np.nan)
                if not np.isnan(v) and abs(v) > 1e-9:
                    pred_ok = True
                    break
            return dict(all_night=all_night, gblend_ok=gblend_ok, pred_ok=pred_ok, rows=r.get("rows", 0))

        vs = get_state(v159_r)
        cs = get_state(can_r)

        print(f"\n  汇总:")
        print(f"    v159:       {vs}")
        print(f"    canonical:  {cs}")

        if vs is None or cs is None:
            print(f"    → 数据不足，无法判定")
        elif not vs["all_night"] and vs["pred_ok"] and cs["all_night"] and not cs["pred_ok"]:
            print(f"    → 情况 A: v159正常，canonical回退（后处理/校准/同步覆盖）")
        elif not vs["all_night"] and vs["pred_ok"] and not cs["all_night"] and cs["pred_ok"]:
            print(f"    → 正常: v159和canonical都正常，pred非0，scene有白天成分")
        elif vs["all_night"] or not vs["pred_ok"]:
            print(f"    → 情况 C: v159本身异常，需要 geo-refresh 或 full 重训")
        else:
            print(f"    → 待进一步诊断")


def main():
    df = diagnose()
    out = df[~df["scope"].isin(["MISSING", "ERROR", "NO_ID_COL"])]
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"[OK] written {OUT}, rows={len(out)}")
    print_diagnosis(df)


if __name__ == "__main__":
    main()
