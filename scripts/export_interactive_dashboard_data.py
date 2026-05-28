#!/usr/bin/env python3
"""
Export interactive dashboard data. Auto-detects the latest distributed_predictions_final_roundXX.pkl.

Usage:
    python scripts/export_interactive_dashboard_data.py \
      --output-root output/pv_pipeline \
      --dashboard-root output/pv_pipeline/interactive_dashboard

Outputs:
    output/pv_pipeline/interactive_dashboard/
        metadata.json
        index.json
        city_series.json
        site_metrics.json
        scatter_site_hour.json
        error_threshold_summary.json
        season_days.json
        midday_city_by_date.json
        site_series/
            S001.json, S002.json, ...
"""

import argparse
import json
import os
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Use anaconda python when available
PYTHON_BIN = "/home/mjj/anaconda3/bin/python3"
import sys
if os.path.exists(PYTHON_BIN):
    sys.executable = PYTHON_BIN

# ============================================================
# SHARED FILTER FUNCTIONS
# ============================================================
HISTORY_SPLITS = ["train", "valid", "test"]
EVAL_SPLIT = "test"
EVAL_HOURS = list(range(6, 20))


def build_history_frame(df: pd.DataFrame) -> pd.DataFrame:
    """可视化历史展示口径：只保留 train/valid/test，不包含 future。"""
    out = df[df["split"].isin(HISTORY_SPLITS)].copy()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour
    if "date" not in out.columns:
        out["date"] = out["time"].dt.strftime("%Y-%m-%d")
    return out


def build_eval_frame_for_dashboard(df: pd.DataFrame) -> pd.DataFrame:
    """可视化评估口径：只用 test 集 6-19 点，有真实值和预测值。"""
    out = build_history_frame(df)
    out = out[
        out["split"].eq(EVAL_SPLIT)
        & out["hour"].isin(EVAL_HOURS)
        & out["power_mw"].notna()
        & out["power_pred"].notna()
        & out["capacity_mw"].notna()
        & (out["capacity_mw"] > 0)
    ].copy()
    return out


def is_all_zero_history(row) -> bool:
    """判断站点是否全0（正功率样本数为0或0值占比>=99.999%）。"""
    return (
        (row.get("full_history_positive_rows") or 0) <= 0
        or (row.get("full_history_zero_ratio_pct") or 0) >= 99.999
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Export interactive dashboard data")
    parser.add_argument(
        "--output-root",
        type=str,
        default="output/pv_pipeline",
        help="Root directory of pv_pipeline output",
    )
    parser.add_argument(
        "--dashboard-root",
        type=str,
        default="output/pv_pipeline/interactive_dashboard",
        help="Output directory for dashboard JSON files",
    )
    return parser.parse_args()


def derive_split(df: pd.DataFrame) -> pd.DataFrame:
    """从时间列推导 split（Round33 方案统一口径）。"""
    if "split" in df.columns and df["split"].notna().any():
        return df
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    TRAIN_END = pd.Timestamp("2025-07-01")
    VALID_END  = pd.Timestamp("2025-09-01")
    TEST_END   = pd.Timestamp("2026-01-01")
    df["split"] = "future"
    df.loc[df["time"] < TRAIN_END, "split"] = "train"
    df.loc[(df["time"] >= TRAIN_END) & (df["time"] < VALID_END), "split"] = "valid"
    df.loc[(df["time"] >= VALID_END) & (df["time"] < TEST_END), "split"] = "test"
    return df


def resolve_prediction_column(df: pd.DataFrame) -> str:
    """Resolve the best prediction column available in the dataframe, in priority order."""
    candidates = [
        "power_pred_final",
        "pred_calibrated",
        "power_pred_cal",
        "power_pred",
    ]
    for col in candidates:
        if col in df.columns:
            return col
    raise KeyError(f"None of {candidates} found in dataframe columns: {list(df.columns)}")


def find_latest_prediction_file(output_root):
    """Auto-detect the latest distributed_predictions_final_roundXX.pkl.

    Returns (Path, round_name_str) where round_name_str is like "Round36".
    """
    import re
    tables_dir = Path(output_root) / "tables"
    candidates = []
    for p in tables_dir.glob("distributed_predictions_final_round*.pkl"):
        m = re.search(r"round(\d+)", p.name, re.IGNORECASE)
        if m:
            candidates.append((int(m.group(1)), p))

    if candidates:
        candidates.sort(reverse=True, key=lambda x: x[0])
        num, path = candidates[0]
        return path, f"Round{num}"

    fallback = [
        tables_dir / "distributed_predictions_final.pkl",
        tables_dir / "distributed_predictions_final_full.pkl",
        tables_dir / "distributed_predictions_v159.pkl",
    ]
    for p in fallback:
        if p.exists():
            return p, "unknown"

    raise FileNotFoundError(
        "找不到 distributed_predictions_final_roundXX.pkl 或 fallback 预测文件"
    )


def load_predictions(output_root):
    """Load prediction data by auto-detecting the latest round file.

    Priority:
      1. distributed_predictions_final_roundXX.pkl (highest round number wins)
      2. distributed_predictions_final_full.pkl (fallback)
      3. distributed_predictions_v159.pkl (last resort)
    """
    tables_dir = Path(output_root) / "tables"
    pred_path, round_name = find_latest_prediction_file(output_root)
    print(f"  [AUTO] Detected latest: {pred_path.name} ({round_name})")

    with open(pred_path, "rb") as f:
        df = pickle.load(f)

    # ── resolve prediction column ──────────────────────────────────────────────
    pred_col = resolve_prediction_column(df)
    print(f"  [AUTO] Prediction column: {pred_col}")

    # ── ensure standard columns exist ────────────────────────────────────────
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    if "date" not in df.columns:
        df["date"] = df["time"].dt.strftime("%Y-%m-%d")

    # derive split if missing
    if "split" not in df.columns or df["split"].notna().sum() == 0:
        print("  [INFO] 'split' column missing or empty, deriving from time...")
        df = derive_split(df)

    # ── load site validity for the detected round ──────────────────────────────
    metrics_dir = Path(output_root) / "metrics"
    validity_map = {}
    # Try round-specific validity file first, then generic fallback
    for pattern in [f"round{''.join(filter(str.isdigit, round_name))}_site_validity.csv",
                    "round36_site_validity.csv",
                    "round34_site_validity.csv"]:
        vpath = metrics_dir / pattern
        if vpath.exists():
            vd = pd.read_csv(vpath)
            for _, row in vd.iterrows():
                validity_map[str(row["site_id"])] = {
                    "site_status": row.get("site_status", "正常评价"),
                    "exclude_from_ranking": row.get("exclude_from_ranking", "否"),
                    "exclude_reason": row.get("exclude_reason", ""),
                }
            print(f"  Loading site validity: {vpath.name}")
            break

    df["_site_status"] = df["site_id"].astype(str).map(
        lambda s: validity_map.get(s, {}).get("site_status", "正常评价")
    )
    df["_exclude_from_ranking"] = df["site_id"].astype(str).map(
        lambda s: validity_map.get(s, {}).get("exclude_from_ranking", "否")
    )
    df["_exclude_reason"] = df["site_id"].astype(str).map(
        lambda s: validity_map.get(s, {}).get("exclude_reason", "")
    )

    print(f"  Loaded {len(df):,} rows, splits: {df['split'].value_counts().to_dict()}")
    return df, round_name, pred_col


def load_site_master(output_root):
    """Load site master CSV for site names and metadata."""
    sm_path = Path(output_root) / "tables" / "site_master.csv"
    if not sm_path.exists():
        print(f"  WARNING: site_master.csv not found at {sm_path}, using site_id only")
        return None
    sm = pd.read_csv(sm_path)
    # Build a name lookup
    if "site_id" in sm.columns and "site_full_name" in sm.columns:
        return sm.set_index("site_id")["site_full_name"].to_dict()
    elif "site_id" in sm.columns and "site_name_norm" in sm.columns:
        return sm.set_index("site_id")["site_name_norm"].to_dict()
    return None


def export_index(df, site_names, dashboard_root, round_name="unknown", pred_col="power_pred"):
    """Export index.json with overview metadata."""
    history_df = build_history_frame(df)
    dates = pd.to_datetime(history_df["date"]).dropna().unique()
    min_date = pd.to_datetime(dates).min().strftime("%Y-%m-%d")
    max_date = pd.to_datetime(dates).max().strftime("%Y-%m-%d")

    # Overall stats — use history only, daytime, non-null
    active = history_df[
        history_df["hour"].between(6, 19)
        & history_df["power_mw"].notna()
        & history_df[pred_col].notna()
    ]

    # Compute eval stats
    eval_df = build_eval_frame_for_dashboard(history_df)
    n_eval_sites = int(eval_df["site_id"].nunique())
    n_valid_sites = int(history_df["site_id"].nunique()) - n_eval_sites

    # Count zero sites in test period
    test_day = eval_df.copy()
    zero_test_sites = test_day.groupby("site_id").apply(
        lambda g: (pd.to_numeric(g["power_mw"], errors="coerce").fillna(0) > 0).sum() == 0,
        include_groups=False
    )
    zero_site_ids = sorted(zero_test_sites[zero_test_sites].index.tolist())
    zero_note = f"，测试期零发电站点{len(zero_site_ids)}个（{','.join(str(s) for s in zero_site_ids)}）" if zero_site_ids else ""

    index_data = {
        "title": "光伏功率预测交互式结果展示",
        "description": f"展示连云港光伏电站真实功率与预测功率对比（{round_name} 版本）",
        "data_source": (
            f"output/pv_pipeline/tables/（{round_name}，预测列：{pred_col}）"
        ),
        "prediction_column": pred_col,
        "round": round_name,
        "data_scope": "train/valid/test only; future excluded (默认不展示未来数据)",
        "口径说明": (
            f"统计口径：test 6-19点；指标口径：NRMSE%=RMSE/capacity_sum_mw×100%；"
            f"有效评价站点{n_eval_sites}个，测试期异常站点{n_valid_sites}个{zero_note}"
        ),
        "min_date": min_date,
        "max_date": max_date,
        "default_start_date": min_date,
        "default_end_date": max_date,
        "total_rows": int(len(history_df)),
        "total_sites": int(history_df["site_id"].nunique()),
        "date_range": f"{min_date} ~ {max_date}",
        "hourly_prediction_summary": "hourly_prediction_summary.json",
        "invalid_zero_sites": "invalid_zero_sites.json",
        "note": (
            "页面只用于展示当前 final/best 预测结果，不参与模型训练和模型选择。"
            "若选择非test日期，显示历史展示口径，非最终测试评价口径。"
        ),
    }

    out_path = Path(dashboard_root) / "index.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
    print(f"  [OK] index.json ({index_data['total_sites']} sites, {min_date}~{max_date})")


def write_metadata(dashboard_root, round_name, pred_col, source_path):
    """Write metadata.json for the dashboard page to display version info."""
    history_dir = Path(dashboard_root) / "site_series"
    n_sites = len(list(history_dir.glob("*.json"))) if history_dir.exists() else 0
    meta = {
        "round": round_name,
        "prediction_column": pred_col,
        "actual_column": "power_mw",
        "source_file": str(source_path),
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "test_period": "2025-09-01~2025-12-31",
        "hours": "6-19",
        "exclude_future": True,
        "data_root": "output/pv_pipeline/interactive_dashboard",
        "total_site_files": n_sites,
    }
    out_path = Path(dashboard_root) / "metadata.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"  [OK] metadata.json ({round_name}, {pred_col})")
    return meta


def export_city_series(df, dashboard_root):
    """Export city_series.json with city-level aggregated data."""
    df_f = build_history_frame(df)
    df_f = df_f[
        df_f["hour"].between(6, 19)
        & df_f["power_mw"].notna()
        & df_f["power_pred"].notna()
    ].copy()

    city = df_f.groupby("time").agg(
        actual_mw=("power_mw", "sum"),
        pred_mw=("power_pred", "sum"),
        n_sites=("site_id", "nunique"),
        sample_count=("site_id", "size"),
        capacity_sum_mw=("capacity_mw", "sum"),
    ).reset_index()

    city["abs_error_mw"] = (city["pred_mw"] - city["actual_mw"]).abs()
    city["city_nrmse_point_pct"] = (
        city["abs_error_mw"] / city["capacity_sum_mw"].clip(lower=1e-9) * 100
    )
    city["date"] = pd.to_datetime(city["time"]).dt.strftime("%Y-%m-%d")
    city["hour"] = pd.to_datetime(city["time"]).dt.hour

    # Add split info (use first occurrence per time)
    split_map = df.groupby("time")["split"].first().to_dict()
    city["split"] = city["time"].map(split_map).fillna("unknown")

    cols = ["time", "date", "hour", "split", "actual_mw", "pred_mw",
            "n_sites", "sample_count", "capacity_sum_mw", "abs_error_mw", "city_nrmse_point_pct"]

    records = city[cols].to_dict(orient="records")
    for r in records:
        r["time"] = pd.Timestamp(r["time"]).strftime("%Y-%m-%d %H:%M:%S")
        r["actual_mw"] = round(float(r["actual_mw"]), 4)
        r["pred_mw"] = round(float(r["pred_mw"]), 4)
        r["abs_error_mw"] = round(float(r["abs_error_mw"]), 4)
        r["city_nrmse_point_pct"] = round(float(r["city_nrmse_point_pct"]), 4)
        r["capacity_sum_mw"] = round(float(r["capacity_sum_mw"]), 4)

    out_path = Path(dashboard_root) / "city_series.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  [OK] city_series.json ({len(records):,} rows)")
    return city


def export_site_series(df, site_names, dashboard_root):
    """Export per-site time series JSON files（Round34 版本：使用 power_pred_final）。"""
    # 解析预测列
    from pv_forecasting.core.eval_frame import resolve_prediction_column
    pred_col = resolve_prediction_column(df)
    print(f"  [INFO] site_series 预测列: {pred_col}")

    df_f = build_history_frame(df)
    df_f = df_f[
        df_f["hour"].between(6, 19)
        & df_f["power_mw"].notna()
        & df_f[pred_col].notna()
    ].copy()

    site_dir = Path(dashboard_root) / "site_series"
    site_dir.mkdir(parents=True, exist_ok=True)

    site_ids = sorted(df_f["site_id"].unique())
    for sid in site_ids:
        sdf = df_f[df_f["site_id"] == sid].sort_values("time")

        records = []
        for _, row in sdf.iterrows():
            pred_val = float(row[pred_col])
            actual_val = float(row["power_mw"])
            cap_val = float(row["capacity_mw"])
            rec = {
                "time": pd.Timestamp(row["time"]).strftime("%Y-%m-%d %H:%M:%S"),
                "date": str(row["date"]),
                "hour": int(row["hour"]),
                "split": str(row["split"]),
                "site_id": str(row["site_id"]),
                "site_name": site_names.get(sid, sid) if site_names else str(sid),
                "actual_mw": round(actual_val, 4),
                "pred_mw": round(pred_val, 4),
                "capacity_mw": round(cap_val, 4),
                "abs_error_mw": round(float(abs(pred_val - actual_val)), 4),
                "point_nrmse_pct": round(
                    float(abs(pred_val - actual_val) / max(cap_val, 1e-9) * 100), 4
                ),
                # Round34: 使用 power_pred_final
                "site_status": str(row.get("_site_status", "正常评价")),
                "exclude_from_ranking": str(row.get("_exclude_from_ranking", "否")),
                "is_future": False,
                "pred_col_used": pred_col,
            }
            records.append(rec)

        out_path = site_dir / f"{sid}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"  [OK] site_series/ ({len(site_ids)} files, Round34 使用 {pred_col})")
    return site_ids


def compute_site_test_daytime_zero_stats(df: pd.DataFrame) -> pd.DataFrame:
    """计算站点级测试集 6-19 点 0值占比。

    统计口径：
    - split == test
    - hour in 6..19
    - power_mw notna
    """
    out = df.copy()

    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], errors="coerce")

    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour

    out = out[
        out["split"].eq("test")
        & out["hour"].between(6, 19)
        & out["power_mw"].notna()
    ].copy()

    if out.empty:
        return pd.DataFrame(columns=[
            "site_id",
            "test_daytime_rows_6_19",
            "test_daytime_positive_rows_6_19",
            "test_daytime_zero_rows_6_19",
            "test_daytime_zero_ratio_6_19_pct",
        ])

    stats = out.groupby("site_id").agg(
        test_daytime_rows_6_19=("power_mw", "size"),
        test_daytime_positive_rows_6_19=("power_mw", lambda s: int((s.fillna(0) > 0).sum())),
        test_daytime_zero_rows_6_19=("power_mw", lambda s: int((s.fillna(0) == 0).sum())),
    ).reset_index()

    stats["test_daytime_zero_ratio_6_19_pct"] = (
        stats["test_daytime_zero_rows_6_19"]
        / stats["test_daytime_rows_6_19"].clip(lower=1)
        * 100
    ).round(4)

    return stats


def export_site_metrics(df, site_names, dashboard_root, test_daytime_zero_stats=None):
    """Export site_metrics.json with per-site statistics and categories."""
    # Full-history stats: train/valid/test only (no future), no hour/power filter
    full_df = build_history_frame(df)
    if "time" in full_df.columns and not pd.api.types.is_datetime64_any_dtype(full_df["time"]):
        full_df["time"] = pd.to_datetime(full_df["time"], errors="coerce")

    full_hist = (
        full_df.groupby("site_id")
        .agg(
            full_history_rows=("site_id", "size"),
            full_history_non_null_rows=("power_mw", lambda s: int(s.notna().sum())),
            full_history_positive_rows=("power_mw", lambda s: int((s.fillna(0) > 0).sum())),
            full_history_zero_rows=("power_mw", lambda s: int((s.fillna(0) == 0).sum())),
            full_history_start_date=("time", "min"),
            full_history_end_date=("time", "max"),
        )
        .reset_index()
    )
    full_hist["full_history_zero_ratio_pct"] = (
        full_hist["full_history_zero_rows"]
        / full_hist["full_history_rows"].clip(lower=1)
        * 100
    ).round(4)
    full_hist["full_history_start_date"] = full_hist["full_history_start_date"].dt.strftime("%Y-%m-%d")
    full_hist["full_history_end_date"] = full_hist["full_history_end_date"].dt.strftime("%Y-%m-%d")

    # Daytime test-set stats for MAE/RMSE/NRMSE (test 6-19h, non-null)
    eval_df = build_eval_frame_for_dashboard(df)

    rows = []
    for sid, sdf in eval_df.groupby("site_id"):
        rows.append({
            "site_id": sid,
            "site_name": site_names.get(sid, sid) if site_names else sid,
            "county": str(sdf["county"].iloc[0]) if "county" in sdf.columns else "",
            "capacity_mw": round(float(sdf["capacity_mw"].mean()), 4),
            "rows": int(len(sdf)),
            "positive_rows": int((sdf["power_mw"] > 0).sum()),
            "zero_rows": int((sdf["power_mw"] == 0).sum()),
            "zero_ratio_pct": round(float((sdf["power_mw"] == 0).sum() / len(sdf) * 100), 4),
            "mae_mw": round(float((sdf["power_pred"] - sdf["power_mw"]).abs().mean()), 4),
            "rmse_mw": round(
                float(np.sqrt(((sdf["power_pred"] - sdf["power_mw"]) ** 2).mean())), 4
            ),
            "nrmse_pct": round(
                float(
                    np.sqrt(((sdf["power_pred"] - sdf["power_mw"]) ** 2).mean())
                    / max(sdf["capacity_mw"].mean(), 1e-9)
                    * 100
                ), 4
            ),
            "bias_pct": round(
                float(
                    (sdf["power_pred"].sum() - sdf["power_mw"].sum())
                    / max(sdf["power_mw"].sum(), 1e-9)
                    * 100
                ), 4
            ),
            "pred_actual_ratio": round(
                float(sdf["power_pred"].sum() / max(sdf["power_mw"].sum(), 1e-9)), 4
            ),
        })

    metrics_df = pd.DataFrame(rows)
    # Merge full-history fields
    metrics_df = metrics_df.merge(full_hist[[
        "site_id", "full_history_rows", "full_history_non_null_rows",
        "full_history_positive_rows", "full_history_zero_rows",
        "full_history_zero_ratio_pct", "full_history_start_date", "full_history_end_date",
    ]], on="site_id", how="left")

    # Merge Round33 site validity (site_status, exclude_reason)
    if "_site_status" in df.columns:
        site_status_map = df.groupby("site_id")["_site_status"].first().reset_index()
        site_status_map.columns = ["site_id", "site_status"]
        metrics_df = metrics_df.merge(site_status_map, on="site_id", how="left")
        metrics_df["site_status"] = metrics_df["site_status"].fillna("正常评价")
    if "_exclude_from_ranking" in df.columns:
        ex_map = df.groupby("site_id")["_exclude_from_ranking"].first().reset_index()
        ex_map.columns = ["site_id", "exclude_from_ranking"]
        metrics_df = metrics_df.merge(ex_map, on="site_id", how="left")
        metrics_df["exclude_from_ranking"] = metrics_df["exclude_from_ranking"].fillna("否")
    if "_exclude_reason" in df.columns:
        reason_map = df.groupby("site_id")["_exclude_reason"].first().reset_index()
        reason_map.columns = ["site_id", "exclude_reason"]
        metrics_df = metrics_df.merge(reason_map, on="site_id", how="left")
        metrics_df["exclude_reason"] = metrics_df["exclude_reason"].fillna("")

    # Merge test 6-19 zero ratio stats
    if test_daytime_zero_stats is not None and not test_daytime_zero_stats.empty:
        metrics_df = metrics_df.merge(test_daytime_zero_stats, on="site_id", how="left")
        for c in ["test_daytime_rows_6_19", "test_daytime_positive_rows_6_19", "test_daytime_zero_rows_6_19"]:
            if c in metrics_df.columns:
                metrics_df[c] = metrics_df[c].fillna(0).astype(int)
        if "test_daytime_zero_ratio_6_19_pct" in metrics_df.columns:
            metrics_df["test_daytime_zero_ratio_6_19_pct"] = (
                metrics_df["test_daytime_zero_ratio_6_19_pct"].fillna(0).round(4)
            )

    # ---- Mark all-zero / no-positive sites ----
    metrics_df["is_all_zero_history"] = metrics_df.apply(is_all_zero_history, axis=1)

    # ---- Typical site classification (uses only valid sites, i.e. test 6-19h rows) ----
    rows_q20 = np.percentile(metrics_df["rows"], 20)
    min_rows = max(200, rows_q20)

    valid_metrics_df = metrics_df[~metrics_df["is_all_zero_history"]].copy()
    # Round33: 只从有效评价站点中选择典型站点（排除测试期异常站点）
    if "exclude_from_ranking" in valid_metrics_df.columns:
        valid_metrics_df = valid_metrics_df[valid_metrics_df["exclude_from_ranking"] != "是"].copy()
    best_candidates = valid_metrics_df[
        (valid_metrics_df["rows"] >= min_rows) & (valid_metrics_df["positive_rows"] >= 100)
    ].copy()
    best_candidates["_sort_nrmse"] = best_candidates["nrmse_pct"]

    # best: lowest nrmse
    best_df = best_candidates.nsmallest(5, "_sort_nrmse")
    # worst: highest nrmse
    worst_df = best_candidates.nlargest(5, "_sort_nrmse")

    # normal: smallest |pred/actual - 1| AND below median nrmse
    remaining = best_candidates.drop(best_df.index).drop(worst_df.index)
    nrmse_median = remaining["nrmse_pct"].median()
    normal_df = remaining[
        remaining["nrmse_pct"] < nrmse_median
    ].copy()
    normal_df["_sort_ratio_diff"] = (normal_df["pred_actual_ratio"] - 1.0).abs()
    normal_df = normal_df.nsmallest(5, "_sort_ratio_diff")

    # low_sample: smallest rows
    low_sample_df = valid_metrics_df.nsmallest(5, "rows")

    category_map = {}
    for _, row in best_df.iterrows():
        category_map[row["site_id"]] = ("best", "预测最好")
    for _, row in worst_df.iterrows():
        category_map[row["site_id"]] = ("worst", "预测最差")
    for _, row in normal_df.iterrows():
        category_map[row["site_id"]] = ("normal", "相对正确")
    for _, row in low_sample_df.iterrows():
        category_map[row["site_id"]] = ("low_sample", "样本少")

    # Priority: low_sample > worst > best > normal; invalid_zero has its own bucket
    final_map = {}
    for sid in metrics_df["site_id"]:
        if sid in category_map:
            final_map[sid] = category_map[sid]

    for sid in metrics_df["site_id"]:
        if sid not in final_map:
            if metrics_df[metrics_df["site_id"] == sid]["is_all_zero_history"].iloc[0]:
                final_map[sid] = ("invalid_zero", "无有效发电样本")
            else:
                final_map[sid] = ("other", "其他")

    # Apply
    metrics_df["category"] = metrics_df["site_id"].map(lambda s: final_map[s][0])
    metrics_df["category_label"] = metrics_df["site_id"].map(lambda s: final_map[s][1])

    # Drop temp columns and sort
    # Round33 新增字段：站点有效性分类（来自 round33_site_validity.csv）
    if "_site_status" in metrics_df.columns:
        metrics_df["site_status"] = metrics_df["_site_status"]
    if "_exclude_from_ranking" in metrics_df.columns:
        metrics_df["exclude_from_ranking"] = metrics_df["_exclude_from_ranking"]
    if "_exclude_reason" in metrics_df.columns:
        metrics_df["exclude_reason"] = metrics_df["_exclude_reason"]

    out_cols = [
        "site_id", "site_name", "county", "capacity_mw",
        "rows", "positive_rows", "zero_rows", "zero_ratio_pct",
        "mae_mw", "rmse_mw", "nrmse_pct", "bias_pct",
        "pred_actual_ratio", "category", "category_label",
        "full_history_rows", "full_history_non_null_rows",
        "full_history_positive_rows", "full_history_zero_rows",
        "full_history_zero_ratio_pct", "full_history_start_date", "full_history_end_date",
        "is_all_zero_history",
        "test_daytime_rows_6_19",
        "test_daytime_positive_rows_6_19",
        "test_daytime_zero_rows_6_19",
        "test_daytime_zero_ratio_6_19_pct",
        # Round33 新增
        "site_status", "exclude_from_ranking", "exclude_reason",
    ]
    metrics_df = metrics_df[out_cols]

    records = metrics_df.to_dict(orient="records")
    out_path = Path(dashboard_root) / "site_metrics.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  [OK] site_metrics.json ({len(records)} sites)")
    return metrics_df


def export_midday_city(df, dashboard_root):
    """Export midday_city_by_date.json for 10-14h city-level daily stats."""
    df_f = build_history_frame(df)
    df_f = df_f[
        df_f["hour"].between(10, 14)
        & df_f["power_mw"].notna()
        & df_f["power_pred"].notna()
    ].copy()

    daily = df_f.groupby("date").agg(
        actual_mwh=("power_mw", "sum"),
        pred_mwh=("power_pred", "sum"),
        capacity_mw_sum=("capacity_mw", "sum"),
        sample_count=("site_id", "size"),
        n_sites=("site_id", "nunique"),
    ).reset_index()

    mae_vals = df_f.groupby("date").apply(
        lambda g: (g["power_pred"] - g["power_mw"]).abs().mean(), include_groups=False
    )
    rmse_vals = df_f.groupby("date").apply(
        lambda g: np.sqrt(((g["power_pred"] - g["power_mw"]) ** 2).mean()), include_groups=False
    )
    daily["mae_mw"] = mae_vals.reindex(daily["date"]).values
    daily["rmse_mw"] = rmse_vals.reindex(daily["date"]).values

    cap_mean_map = df_f.groupby("date")["capacity_mw"].mean().to_dict()
    daily["nrmse_pct"] = daily.apply(
        lambda r: round(r["rmse_mw"] / max(cap_mean_map.get(r["date"], 1), 1e-9) * 100, 4), axis=1
    )
    daily["bias_pct"] = daily.apply(
        lambda r: round(
            (r["pred_mwh"] - r["actual_mwh"]) / max(r["actual_mwh"], 1e-9) * 100, 4
        ), axis=1
    )
    daily["pred_actual_ratio"] = daily.apply(
        lambda r: round(r["pred_mwh"] / max(r["actual_mwh"], 1e-9), 4), axis=1
    )

    daily["actual_mwh"] = daily["actual_mwh"].round(4)
    daily["pred_mwh"] = daily["pred_mwh"].round(4)
    daily["mae_mw"] = daily["mae_mw"].round(4)
    daily["rmse_mw"] = daily["rmse_mw"].round(4)
    daily["capacity_mw_sum"] = daily["capacity_mw_sum"].round(4)

    records = daily.to_dict(orient="records")
    for r in records:
        r["date"] = str(r["date"])

    out_path = Path(dashboard_root) / "midday_city_by_date.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  [OK] midday_city_by_date.json ({len(records)} days)")


def export_season_days(df, dashboard_root):
    """Export season_days.json with one representative day per season."""
    df_f = build_history_frame(df)
    df_f = df_f[
        df_f["hour"].between(6, 19)
        & df_f["power_mw"].notna()
        & df_f["power_pred"].notna()
    ].copy()

    df_f["month"] = pd.to_datetime(df_f["date"]).dt.month

    season_map = {
        "spring": (3, 4, 5),
        "summer": (6, 7, 8),
        "autumn": (9, 10, 11),
        "winter": (12, 1, 2),
    }
    season_labels = {
        "spring": "春季",
        "summer": "夏季",
        "autumn": "秋季",
        "winter": "冬季",
    }

    results = []
    for season, months in season_map.items():
        season_df = df_f[df_f["month"].isin(months)]
        if season_df.empty:
            results.append({
                "season": season,
                "season_label": season_labels[season],
                "available": False,
                "reason": f"当前 final 数据中没有 {'、'.join(str(m) for m in months)} 月记录",
            })
            continue

        daily_stats = season_df.groupby("date").agg(
            actual_mwh=("power_mw", "sum"),
            pred_mwh=("power_pred", "sum"),
            n_sites=("site_id", "nunique"),
            sample_count=("site_id", "size"),
        ).reset_index()

        if daily_stats.empty:
            results.append({
                "season": season,
                "season_label": season_labels[season],
                "available": False,
                "reason": f"当前 final 数据中没有 {'、'.join(str(m) for m in months)} 月记录",
            })
            continue

        # Prefer dates with more site coverage
        median_sites = daily_stats["n_sites"].median()
        candidate = daily_stats[daily_stats["n_sites"] >= median_sites].copy()

        if candidate.empty:
            candidate = daily_stats

        # Choose day whose actual_mwh is closest to median
        median_mwh = candidate["actual_mwh"].median()
        candidate = candidate.copy()
        candidate["dist_to_median"] = (candidate["actual_mwh"] - median_mwh).abs()
        best_date = candidate.loc[candidate["dist_to_median"].idxmin()]

        results.append({
            "season": season,
            "season_label": season_labels[season],
            "available": True,
            "date": str(best_date["date"]),
            "actual_mwh": round(float(best_date["actual_mwh"]), 4),
            "pred_mwh": round(float(best_date["pred_mwh"]), 4),
            "n_sites": int(best_date["n_sites"]),
            "sample_count": int(best_date["sample_count"]),
            "reason": f"选择 {str(best_date['date'])} (日发电量 {round(float(best_date['actual_mwh']), 1)} MWh，接近季节中位数)",
        })

    out_path = Path(dashboard_root) / "season_days.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"  [OK] season_days.json")
    return results


def load_site_master_full(output_root):
    """Load full site master CSV for site names and metadata."""
    sm_path = Path(output_root) / "tables" / "site_master.csv"
    if not sm_path.exists():
        return None
    sm = pd.read_csv(sm_path)
    cols_needed = ["site_id", "site_short_name", "site_full_name", "county", "capacity_mw"]
    cols_exist = [c for c in cols_needed if c in sm.columns]
    if "site_id" not in sm.columns:
        return None
    return sm[cols_exist].set_index("site_id")


def build_site_name_lookup(sm_df):
    """Build site name lookup dict."""
    if sm_df is None:
        return None
    lookup = {}
    for sid, row in sm_df.iterrows():
        name = (row.get("site_short_name") or "").strip()
        if not name:
            name = (row.get("site_full_name") or "").strip()
        if not name:
            name = str(sid)
        lookup[sid] = name
    return lookup


def export_scatter_site_sample_nrmse(df, site_names, sm_df, metrics_df, dashboard_root, test_daytime_zero_stats=None):
    """Export scatter_site_sample_nrmse.json: each point = one site.

    - Sample counts use train/valid/test only (no future).
    - NRMSE uses test 6-19h.
    - All-zero / no-positive sites are excluded from this file.
    """
    # ---- Full-history stats: train/valid/test only (no future) ----
    full_hist = build_history_frame(df)
    full_hist["time"] = pd.to_datetime(full_hist["time"], errors="coerce")
    full_hist_agg = full_hist.groupby("site_id").agg(
        full_history_rows=("site_id", "size"),
        full_history_non_null_rows=("power_mw", lambda s: int(s.notna().sum())),
        full_history_positive_rows=("power_mw", lambda s: int((s.fillna(0) > 0).sum())),
        full_history_zero_rows=("power_mw", lambda s: int((s.fillna(0) == 0).sum())),
        full_history_start_date=("time", "min"),
        full_history_end_date=("time", "max"),
    ).reset_index()
    full_hist_agg["full_history_zero_ratio_pct"] = (
        full_hist_agg["full_history_zero_rows"] /
        full_hist_agg["full_history_rows"].clip(lower=1) * 100
    ).round(4)
    full_hist_agg["full_history_start_date"] = (
        pd.to_datetime(full_hist_agg["full_history_start_date"], errors="coerce")
        .dt.strftime("%Y-%m-%d")
        .fillna("")
    )
    full_hist_agg["full_history_end_date"] = (
        pd.to_datetime(full_hist_agg["full_history_end_date"], errors="coerce")
        .dt.strftime("%Y-%m-%d")
        .fillna("")
    )

    # Build category lookup
    cat_map = dict(zip(metrics_df["site_id"], metrics_df["category_label"]))

    # Sample counts: use train/valid from history (no future)
    tv = build_history_frame(df)
    tv = tv[tv["split"].isin(["train", "valid"])].copy()

    train_rows = tv[tv["split"].eq("train")].groupby("site_id").size().rename("train_rows")
    valid_rows = tv[tv["split"].eq("valid")].groupby("site_id").size().rename("valid_rows")

    tv_agg = tv.groupby("site_id").agg(
        train_valid_rows=("power_mw", "size"),
        train_valid_positive_rows=("power_mw", lambda s: (s.fillna(0) > 0).sum()),
        train_valid_zero_rows=("power_mw", lambda s: (s.fillna(0) == 0).sum()),
        capacity_mw_tv=("capacity_mw", "mean"),
    ).reset_index()
    tv_agg["train_valid_zero_ratio_pct"] = (
        tv_agg["train_valid_zero_rows"] / tv_agg["train_valid_rows"].clip(lower=1) * 100
    )
    tv_agg = tv_agg.merge(train_rows.reset_index(), on="site_id", how="left")
    tv_agg = tv_agg.merge(valid_rows.reset_index(), on="site_id", how="left")
    tv_agg["train_rows"] = tv_agg["train_rows"].fillna(0).astype(int)
    tv_agg["valid_rows"] = tv_agg["valid_rows"].fillna(0).astype(int)
    tv_agg["train_valid_positive_rows"] = tv_agg["train_valid_positive_rows"].astype(int)

    # Test NRMSE per site (test 6-19h, non-null)
    test_eval = build_eval_frame_for_dashboard(df)

    def rmse(y, p):
        return np.sqrt(np.mean((p - y) ** 2))

    test_rows = []
    for sid, g in test_eval.groupby("site_id"):
        y = g["power_mw"].astype(float).values
        p = g["power_pred"].astype(float).values
        c = max(float(g["capacity_mw"].mean()), 1e-9)
        actual_sum = float(np.sum(y))
        pred_sum = float(np.sum(p))
        rmse_mw = rmse(y, p)
        test_rows.append({
            "site_id": sid,
            "test_rows": int(len(g)),
            "test_positive_rows": int((g["power_mw"].fillna(0) > 0).sum()),
            "test_mae_mw": float(np.mean(np.abs(p - y))),
            "test_rmse_mw": float(rmse_mw),
            "test_nrmse_pct": float(rmse_mw / c * 100),
            "test_bias_pct": float((pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100),
            "test_pred_actual_ratio": float(pred_sum / max(actual_sum, 1e-9)),
        })
    test_df = pd.DataFrame(test_rows)

    # Merge
    merged = tv_agg.merge(test_df, on="site_id", how="inner")
    merged = merged.merge(full_hist_agg, on="site_id", how="left")
    merged["capacity_mw"] = merged["capacity_mw_tv"]

    # Merge test 6-19 zero ratio stats
    if test_daytime_zero_stats is not None and not test_daytime_zero_stats.empty:
        merged = merged.merge(test_daytime_zero_stats, on="site_id", how="left")
        for c in ["test_daytime_rows_6_19", "test_daytime_positive_rows_6_19", "test_daytime_zero_rows_6_19"]:
            if c in merged.columns:
                merged[c] = merged[c].fillna(0).astype(int)
        if "test_daytime_zero_ratio_6_19_pct" in merged.columns:
            merged["test_daytime_zero_ratio_6_19_pct"] = (
                merged["test_daytime_zero_ratio_6_19_pct"].fillna(0).round(4)
            )

    # Site names
    if sm_df is not None:
        name_map = {}
        for sid, row in sm_df.iterrows():
            name = (str(row.get("site_short_name") or "") or "").strip()
            if not name:
                name = (str(row.get("site_full_name") or "") or "").strip()
            if not name:
                name = str(sid)
            name_map[sid] = name
        merged["site_name"] = merged["site_id"].map(name_map).fillna(merged["site_id"])
        merged["county"] = merged["site_id"].map(
            lambda s: str(sm_df.loc[s, "county"]) if s in sm_df.index and pd.notna(sm_df.loc[s, "county"]) else ""
        )
    else:
        merged["site_name"] = merged["site_id"].map(lambda s: site_names.get(s, s) if site_names else s)
        merged["county"] = ""

    merged["category_label"] = merged["site_id"].map(lambda s: cat_map.get(s, "其他"))

    # Mark and filter out all-zero / no-positive sites
    merged["is_all_zero_history"] = merged.apply(is_all_zero_history, axis=1)
    # keep for return so caller can use it; write only valid sites to file
    valid_merged = merged[~merged["is_all_zero_history"]].copy()

    # Round numeric cols
    for col in ["test_mae_mw", "test_rmse_mw", "test_nrmse_pct", "test_bias_pct",
                "test_pred_actual_ratio", "train_valid_zero_ratio_pct"]:
        if col in valid_merged.columns:
            valid_merged[col] = valid_merged[col].round(4)
    for col in ["capacity_mw"]:
        if col in valid_merged.columns:
            valid_merged[col] = valid_merged[col].round(4)

    # Sort: category then nrmse
    cat_order = {"预测最好": 0, "预测最差": 1, "相对正确": 2, "样本少": 3, "其他": 4}
    valid_merged["_cat_order"] = valid_merged["category_label"].map(lambda c: cat_order.get(c, 5))
    valid_merged = valid_merged.sort_values(["_cat_order", "test_nrmse_pct"]).drop(columns=["_cat_order"])

    # Return both: valid records (for downstream) and full merged df (for invalid_zero extraction)
    records = valid_merged.to_dict(orient="records")
    out_path = Path(dashboard_root) / "scatter_site_sample_nrmse.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  [OK] scatter_site_sample_nrmse.json ({len(records)} valid sites, all-zero sites excluded)")
    return records  # valid records list for downstream use


def export_sample_requirement_summary(scatter_data, dashboard_root):
    """Export sample_requirement_summary.json with full-history sample size fields."""
    thresholds = [5, 10, 15, 20, 25]
    total = len(scatter_data)
    notes_base = (
        "经验估计：在当前数据和当前模型下，达到指定NRMSE阈值的站点通常具备的历史样本量分布。"
        "历史样本量仅包含 train/valid/test，不包含 future；"
        "0值占比100%或无正功率样本的站点已从统计中剔除。"
        "样本量不是唯一决定因素，容量、站点映射、异常0值、限电、遮挡和气象插值都会影响最终NRMSE。"
    )
    results = []
    for thresh in thresholds:
        qualified = [s for s in scatter_data if s.get("test_nrmse_pct", 9999) <= thresh]
        q_count = len(qualified)

        # Full-history rows statistics
        full_hist_vals = sorted([
            s.get("full_history_rows", 0) or 0
            for s in qualified
        ])
        full_hist_pos_vals = sorted([
            s.get("full_history_positive_rows", 0) or 0
            for s in qualified
        ])
        # Auxiliary: train/valid positive rows
        tv_pos_vals = sorted([s.get("train_valid_positive_rows", 0) or 0 for s in qualified])

        def pctile(sorted_vals, p):
            if not sorted_vals:
                return None
            idx = int((len(sorted_vals) - 1) * p)
            return int(sorted_vals[idx])

        if q_count == 0:
            results.append({
                "threshold_pct": thresh,
                "qualified_sites": 0,
                "total_sites": total,
                "qualified_ratio_pct": 0.0,
                "min_full_history_rows": None,
                "p25_full_history_rows": None,
                "median_full_history_rows": None,
                "p75_full_history_rows": None,
                "max_full_history_rows": None,
                "median_full_history_positive_rows": None,
                "median_train_valid_positive_rows": None,
                "note": notes_base,
            })
            continue

        n = len(full_hist_vals)
        results.append({
            "threshold_pct": thresh,
            "qualified_sites": q_count,
            "total_sites": total,
            "qualified_ratio_pct": round(q_count / total * 100, 2),
            "min_full_history_rows": int(min(full_hist_vals)),
            "p25_full_history_rows": pctile(full_hist_vals, 0.25),
            "median_full_history_rows": pctile(full_hist_vals, 0.50),
            "p75_full_history_rows": pctile(full_hist_vals, 0.75),
            "max_full_history_rows": int(max(full_hist_vals)),
            "median_full_history_positive_rows": pctile(full_hist_pos_vals, 0.50),
            "median_train_valid_positive_rows": pctile(tv_pos_vals, 0.50),
            "note": notes_base,
        })

    out_path = Path(dashboard_root) / "sample_requirement_summary.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"  [OK] sample_requirement_summary.json ({len(results)} thresholds)")
    return results


def export_invalid_zero_sites(metrics_df, dashboard_root, df=None):
    """Export invalid_zero_sites.json: history-zero OR test-period-zero sites."""
    # Step 1: history-zero (is_all_zero_history)
    invalid = metrics_df[metrics_df.get("is_all_zero_history", pd.Series(False)) == True].copy()
    invalid_ids = set(invalid["site_id"].astype(str).tolist())

    # Step 2: also detect test-period 100% zero (S003/S044/S076/S077 etc.)
    if df is not None:
        test_day = df[
            df["split"].eq("test")
            & df["hour"].isin(EVAL_HOURS)
            & df["power_mw"].notna()
        ].copy()
        if not test_day.empty:
            test_pos = test_day.groupby("site_id").apply(
                lambda g: (pd.to_numeric(g["power_mw"], errors="coerce").fillna(0) > 0).sum(),
                include_groups=False
            )
            test_zero_ids = set(test_pos[test_pos == 0].index.astype(str).tolist())
            # Merge with metrics_df data for these sites
            extra = metrics_df[metrics_df["site_id"].astype(str).isin(test_zero_ids - invalid_ids)].copy()
            if not extra.empty:
                invalid = pd.concat([invalid, extra], ignore_index=True)

    cols = [
        "site_id", "site_name", "county", "capacity_mw",
        "full_history_rows", "full_history_positive_rows",
        "full_history_zero_rows", "full_history_zero_ratio_pct",
        "full_history_start_date", "full_history_end_date",
        "rows", "positive_rows",  # test 6-19h stats
        "mae_mw", "rmse_mw", "nrmse_pct", "pred_actual_ratio",
    ]
    cols = [c for c in cols if c in invalid.columns]

    records = invalid[cols].to_dict(orient="records")
    out_path = Path(dashboard_root) / "invalid_zero_sites.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  [OK] invalid_zero_sites.json ({len(records)} sites)")
    return records


def export_sample_requirement_bins(scatter_data, dashboard_root):
    """Export sample_requirement_bins.json using full_history_rows as binning key."""
    bins_def = [
        (0, 5000, "0-5000"),
        (5000, 10000, "5000-10000"),
        (10000, 15000, "10000-15000"),
        (15000, 20000, "15000-20000"),
        (20000, 26000, "20000-26000"),
        (26000, 28000, "26000-28000"),
        (28000, float("inf"), "28000+"),
    ]

    rows = []
    for lo, hi, label in bins_def:
        bucket = [s for s in scatter_data if lo <= (s.get("full_history_rows") or 0) < hi]
        if not bucket:
            rows.append({
                "sample_bin": label,
                "site_count": 0,
                "median_full_history_rows": None,
                "median_full_history_positive_rows": None,
                "median_train_valid_positive_rows": None,
                "mean_nrmse_pct": None,
                "median_nrmse_pct": None,
                "p25_nrmse_pct": None,
                "p75_nrmse_pct": None,
                "best_nrmse_pct": None,
                "worst_nrmse_pct": None,
            })
            continue

        nrmse_vals = sorted([s.get("test_nrmse_pct") for s in bucket if s.get("test_nrmse_pct") is not None])
        full_hist = [s.get("full_history_rows") for s in bucket]
        full_pos = [s.get("full_history_positive_rows") for s in bucket]
        tv_pos = [s.get("train_valid_positive_rows") for s in bucket]
        n = len(nrmse_vals)

        def med(vals):
            vals_s = sorted([v for v in vals if v is not None])
            return int(np.median(vals_s)) if vals_s else None

        rows.append({
            "sample_bin": label,
            "site_count": len(bucket),
            "median_full_history_rows": med(full_hist),
            "median_full_history_positive_rows": med(full_pos),
            "median_train_valid_positive_rows": med(tv_pos),
            "mean_nrmse_pct": round(float(np.mean(nrmse_vals)), 4) if nrmse_vals else None,
            "median_nrmse_pct": round(float(nrmse_vals[n // 2]), 4),
            "p25_nrmse_pct": round(float(nrmse_vals[n // 4]), 4),
            "p75_nrmse_pct": round(float(nrmse_vals[3 * n // 4]), 4),
            "best_nrmse_pct": round(float(nrmse_vals[0]), 4),
            "worst_nrmse_pct": round(float(nrmse_vals[-1]), 4),
        })

    out_path = Path(dashboard_root) / "sample_requirement_bins.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"  [OK] sample_requirement_bins.json ({len(rows)} bins)")
    return rows


def compute_hourly_summary_from_final(df: pd.DataFrame) -> pd.DataFrame:
    """Compute hourly NRMSE summary from final eval DataFrame (fallback when CSV missing)."""
    eval_df = df.copy()
    eval_df["time"] = pd.to_datetime(eval_df["time"])
    eval_df["hour"] = eval_df["time"].dt.hour
    eval_df = eval_df[
        eval_df["split"].eq("test") &
        eval_df["hour"].between(6, 19) &
        eval_df["power_mw"].notna() &
        eval_df["power_pred"].notna()
    ].copy()

    # Per-site NRMSE per hour → average across sites
    site_rows = []
    for (hour, site_id), g in eval_df.groupby(["hour", "site_id"]):
        y = g["power_mw"].astype(float).to_numpy()
        p = g["power_pred"].astype(float).to_numpy()
        c = max(float(g["capacity_mw"].mean()), 1e-9)
        rmse = float(np.sqrt(np.mean((p - y) ** 2)))
        site_rows.append({
            "hour": int(hour),
            "site_id": site_id,
            "site_nrmse_pct": rmse / c * 100,
        })

    site_hour = pd.DataFrame(site_rows)
    site_avg = site_hour.groupby("hour")["site_nrmse_pct"].mean().reset_index()
    site_avg = site_avg.rename(columns={"site_nrmse_pct": "site_nrmse_mean_pct"})

    # City-level NRMSE per hour
    city_rows = []
    for hour, g in eval_df.groupby("hour"):
        city_by_time = g.groupby("time").agg(
            actual=("power_mw", "sum"),
            pred=("power_pred", "sum"),
            capacity=("capacity_mw", "sum"),
        ).reset_index()
        y = city_by_time["actual"].astype(float).to_numpy()
        p = city_by_time["pred"].astype(float).to_numpy()
        c = max(float(city_by_time["capacity"].mean()), 1e-9)
        rmse = float(np.sqrt(np.mean((p - y) ** 2)))
        city_rows.append({
            "hour": int(hour),
            "city_nrmse_pct": rmse / c * 100,
        })
    city_hour = pd.DataFrame(city_rows)

    # Sample count per hour
    rows_hour = eval_df.groupby("hour").size().reset_index(name="rows")

    hourly = rows_hour.merge(site_avg, on="hour", how="left").merge(city_hour, on="hour", how="left")
    return hourly


def export_hourly_prediction_summary(output_root, dashboard_root, final_df=None, round_name="unknown") -> list:
    """Export hourly_prediction_summary.json.

    Priority: round-specific CSV → generic CSV → compute from final_df.
    """
    metrics_dir = Path(output_root) / "metrics"
    # Try round-specific CSV first
    rn = "".join(filter(str.isdigit, round_name))
    csv_candidates = [
        metrics_dir / f"round{rn}_city_hourly_nrmse.csv",
        metrics_dir / "分布式光伏预测_逐小时平均NRMSE.csv",
    ]
    csv_path = None
    for cp in csv_candidates:
        if cp.exists():
            csv_path = cp
            break

    if csv_path:
        print(f"  Loading existing hourly CSV: {csv_path}")
        hourly = pd.read_csv(csv_path)
        rename_map = {
            "小时": "hour",
            "小时（时）": "hour",
            "样本数": "rows",
            "样本数（行）": "rows",
            "站点平均NRMSE（%）": "site_nrmse_mean_pct",
            "站点平均 NRMSE（%）": "site_nrmse_mean_pct",
            "城市NRMSE（%）": "city_nrmse_pct",
            "城市 NRMSE（%）": "city_nrmse_pct",
        }
        hourly = hourly.rename(columns={k: v for k, v in rename_map.items() if k in hourly.columns})
        if "hour" not in hourly.columns and "Hour" in hourly.columns:
            hourly = hourly.rename(columns={"Hour": "hour"})
        # If CSV has per-date rows (many rows), group by hour
        if "hour" in hourly.columns and len(hourly) > 20:
            hourly = hourly[hourly["hour"].between(6, 19)]
            hourly = hourly.groupby("hour", as_index=False).agg(
                rows=("rows", "sum"),
                site_nrmse_mean_pct=("site_nrmse_mean_pct", "mean"),
                city_nrmse_pct=("city_nrmse_pct", "mean"),
            )
        elif "hour" in hourly.columns:
            hourly = hourly[hourly["hour"].between(6, 19)].copy()
    elif final_df is not None:
        print(f"  CSV not found, computing hourly summary from final_df...")
        hourly = compute_hourly_summary_from_final(final_df)
    else:
        print(f"  WARNING: hourly CSV not found and no final_df provided, skipping hourly export")
        return []

    # Filter to 6-19h
    if "hour" in hourly.columns:
        hourly = hourly[hourly["hour"].between(6, 19)].copy()
        hourly = hourly.sort_values("hour")

    # Ensure required columns exist
    for col in ["hour", "rows", "site_nrmse_mean_pct", "city_nrmse_pct"]:
        if col not in hourly.columns:
            hourly[col] = None

    # Format
    hourly["hour"] = hourly["hour"].astype(int)
    hourly["rows"] = hourly["rows"].fillna(0).astype(int)
    hourly["site_nrmse_mean_pct"] = hourly["site_nrmse_mean_pct"].astype(float).round(2)
    hourly["city_nrmse_pct"] = hourly["city_nrmse_pct"].astype(float).round(3)

    out_path = Path(dashboard_root) / "hourly_prediction_summary.json"
    records = hourly[["hour", "rows", "site_nrmse_mean_pct", "city_nrmse_pct"]].to_dict(orient="records")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  [OK] hourly_prediction_summary.json ({len(records)} rows, 6-19h)")
    return records


def export_scatter_site_hour(df, site_names, metrics_df, dashboard_root):
    """Export scatter_site_hour.json: each point = site_id + hour."""
    df_f = build_history_frame(df)
    df_f = df_f[
        df_f["hour"].between(6, 19)
        & df_f["power_mw"].notna()
        & df_f["power_pred"].notna()
    ].copy()

    # Build category label lookup
    cat_map = dict(zip(metrics_df["site_id"], metrics_df["category_label"]))

    rows = []
    for (sid, hour), gdf in df_f.groupby(["site_id", "hour"]):
        cap_mean = gdf["capacity_mw"].mean()
        rows.append({
            "site_id": sid,
            "site_name": site_names.get(sid, sid) if site_names else sid,
            "hour": int(hour),
            "sample_count": int(len(gdf)),
            "capacity_mw": round(float(cap_mean), 4),
            "mae_mw": round(float((gdf["power_pred"] - gdf["power_mw"]).abs().mean()), 4),
            "rmse_mw": round(
                float(np.sqrt(((gdf["power_pred"] - gdf["power_mw"]) ** 2).mean())), 4
            ),
            "nrmse_pct": round(
                float(
                    np.sqrt(((gdf["power_pred"] - gdf["power_mw"]) ** 2).mean())
                    / max(cap_mean, 1e-9)
                    * 100
                ), 4
            ),
            "bias_pct": round(
                float(
                    (gdf["power_pred"].sum() - gdf["power_mw"].sum())
                    / max(gdf["power_mw"].sum(), 1e-9)
                    * 100
                ), 4
            ),
            "pred_actual_ratio": round(
                float(gdf["power_pred"].sum() / max(gdf["power_mw"].sum(), 1e-9)), 4
            ),
            "category_label": cat_map.get(sid, "其他"),
        })

    out_path = Path(dashboard_root) / "scatter_site_hour.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"  [OK] scatter_site_hour.json ({len(rows)} points)")
    return rows


def export_error_threshold_summary(scatter_data, dashboard_root):
    """Export error_threshold_summary.json."""
    thresholds = [5, 10, 15, 20, 25]
    total_points = len(scatter_data)

    results = []
    for thresh in thresholds:
        qualified = [p for p in scatter_data if p["nrmse_pct"] <= thresh]
        q_count = len(qualified)
        if q_count > 0:
            sample_counts = [p["sample_count"] for p in qualified]
            q = sorted(sample_counts)
            n = len(q)
            results.append({
                "threshold_pct": thresh,
                "qualified_points": q_count,
                "total_points": total_points,
                "qualified_ratio_pct": round(q_count / total_points * 100, 2),
                "min_sample_count": int(min(q)),
                "p25_sample_count": int(q[n // 4]),
                "median_sample_count": int(q[n // 2]),
                "p75_sample_count": int(q[3 * n // 4]),
                "note": (
                    "该表表示在当前数据和模型结果中，达到指定误差阈值的站点-小时组合"
                    "通常具备的样本量分布，不代表样本量是唯一决定因素。"
                ),
            })
        else:
            results.append({
                "threshold_pct": thresh,
                "qualified_points": 0,
                "total_points": total_points,
                "qualified_ratio_pct": 0.0,
                "min_sample_count": None,
                "p25_sample_count": None,
                "median_sample_count": None,
                "p75_sample_count": None,
                "note": "该表表示在当前数据和模型结果中，达到指定误差阈值的站点-小时组合通常具备的样本量分布，不代表样本量是唯一决定因素。",
            })

    out_path = Path(dashboard_root) / "error_threshold_summary.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"  [OK] error_threshold_summary.json")


# ============================================================
# DATA INTEGRITY VALIDATION
# ============================================================
def validate_dashboard_actual_values(df: pd.DataFrame, dashboard_root, output_root):
    """校验 site_series/*.json 中的 actual_mw 与 final_full/power_mw 是否一致。"""
    site_dir = Path(dashboard_root) / "site_series"
    rows = []

    if "time" in df.columns:
        source = df.copy()
        source["time"] = pd.to_datetime(source["time"], errors="coerce")
    else:
        raise ValueError("prediction df missing time column")

    source = source[
        source["split"].isin(["train", "valid", "test"])
        & source["hour"].between(6, 19)
        & source["power_mw"].notna()
    ].copy()

    source_key = source.set_index(["site_id", "time"])["power_mw"]

    for path in sorted(site_dir.glob("*.json")):
        site_id = path.stem
        js = pd.read_json(path)
        if js.empty:
            rows.append({
                "site_id": site_id,
                "json_rows": 0,
                "matched_rows": 0,
                "missing_in_source": 0,
                "max_abs_diff": None,
                "status": "FAIL_EMPTY_JSON",
            })
            continue

        js["time"] = pd.to_datetime(js["time"], errors="coerce")
        js["site_id"] = site_id

        merged = js[["site_id", "time", "actual_mw"]].merge(
            source[["site_id", "time", "power_mw"]],
            on=["site_id", "time"],
            how="left",
        )

        missing = int(merged["power_mw"].isna().sum())
        matched = int(merged["power_mw"].notna().sum())

        if matched > 0:
            diff = (merged["actual_mw"].astype(float) - merged["power_mw"].astype(float)).abs()
            max_diff = float(diff.max())
            bad_rows = int((diff > 1e-9).sum())
        else:
            max_diff = None
            bad_rows = len(merged)

        status = "PASS" if missing == 0 and bad_rows == 0 else "FAIL"

        rows.append({
            "site_id": site_id,
            "json_rows": int(len(js)),
            "matched_rows": matched,
            "missing_in_source": missing,
            "bad_value_rows": bad_rows,
            "max_abs_diff": max_diff,
            "status": status,
        })

    result = pd.DataFrame(rows)
    metrics_path = Path(output_root) / "metrics" / "dashboard_actual_value_consistency.csv"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(metrics_path, index=False, encoding="utf-8-sig")

    summary = {
        "checked_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "distributed_predictions_final_full.pkl power_mw",
        "dashboard_site_series": "interactive_dashboard/site_series/*.json actual_mw",
        "site_count": int(len(result)),
        "fail_count": int((result["status"] != "PASS").sum()) if len(result) else 0,
        "max_abs_diff": float(result["max_abs_diff"].dropna().max()) if result["max_abs_diff"].notna().any() else 0.0,
        "status": "PASS" if len(result) and (result["status"] == "PASS").all() else "FAIL",
    }

    out_json = Path(dashboard_root) / "data_integrity_check.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    if summary["status"] != "PASS":
        bad = result[result["status"] != "PASS"].head(10)
        raise RuntimeError(
            "Dashboard actual_mw differs from source power_mw. "
            f"See {metrics_path}. Bad examples: {bad.to_dict(orient='records')}"
        )

    print(f"  [OK] dashboard actual value consistency: {summary['site_count']} sites, max_diff={summary['max_abs_diff']}")
    return summary


def validate_against_power_clean(dashboard_root, output_root):
    """二次校验：与 power_clean.pkl 再做比对。"""
    clean_path = Path(output_root) / "tables" / "power_clean.pkl"
    if not clean_path.exists():
        print(f"  [WARN] power_clean.pkl not found, skip clean validation")
        return None

    power_clean = pd.read_pickle(clean_path)
    power_clean["time"] = pd.to_datetime(power_clean["time"], errors="coerce")
    power_clean = power_clean[
        power_clean["site_id"].notna()
        & power_clean["time"].notna()
        & power_clean["power_mw"].notna()
    ].copy()

    site_dir = Path(dashboard_root) / "site_series"
    rows = []

    for path in sorted(site_dir.glob("*.json")):
        site_id = path.stem
        js = pd.read_json(path)
        if js.empty:
            continue
        js["time"] = pd.to_datetime(js["time"], errors="coerce")
        js["site_id"] = site_id

        clean_site = power_clean[power_clean["site_id"].astype(str).eq(site_id)]
        merged = js[["site_id", "time", "actual_mw"]].merge(
            clean_site[["site_id", "time", "power_mw"]],
            on=["site_id", "time"],
            how="left",
        )

        diff = (merged["actual_mw"].astype(float) - merged["power_mw"].astype(float)).abs()
        rows.append({
            "site_id": site_id,
            "json_rows": len(js),
            "matched_rows": int(merged["power_mw"].notna().sum()),
            "missing_in_power_clean": int(merged["power_mw"].isna().sum()),
            "max_abs_diff_power_clean": float(diff.max()) if diff.notna().any() else None,
            "bad_rows": int((diff > 1e-9).sum()) if diff.notna().any() else len(js),
        })

    result = pd.DataFrame(rows)
    out = Path(output_root) / "metrics" / "dashboard_vs_power_clean_consistency.csv"
    result.to_csv(out, index=False, encoding="utf-8-sig")

    bad = result[
        (result["missing_in_power_clean"] > 0)
        | (result["bad_rows"] > 0)
    ]
    if len(bad):
        raise RuntimeError(f"Dashboard values differ from power_clean. See {out}")

    print(f"  [OK] dashboard actual values match power_clean: {len(result)} sites")
    return result


def main():
    args = parse_args()
    dashboard_root = args.dashboard_root
    output_root = args.output_root

    print(f"\n=== Auto Export Interactive Dashboard Data ===")
    print(f"  Output root : {output_root}")
    print(f"  Dashboard dir: {dashboard_root}")

    # ── Clean output directory (only json/csv, keep subdirs) ──────────────────────
    dash_dir = Path(dashboard_root)
    if dash_dir.exists():
        for p in dash_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in [".json", ".csv"]:
                p.unlink()
    dash_dir.mkdir(parents=True, exist_ok=True)

    # Load data (auto-detects latest round)
    print("\n[1] Loading prediction data...")
    df, round_name, pred_col = load_predictions(output_root)
    pred_path, _ = find_latest_prediction_file(output_root)
    print(f"  Shape: {df.shape}, sites: {df['site_id'].nunique()}")
    print(f"  Splits: {sorted(df['split'].unique().tolist())}")

    # Load site master for names
    print("\n[2] Loading site master...")
    sm_df = load_site_master_full(output_root)
    site_names = build_site_name_lookup(sm_df)
    if site_names:
        print(f"  Loaded {len(site_names)} site names")
    else:
        print("  No site names found, will use site_id")
        site_names = None

    # Export all data files
    print("\n[3] Exporting index.json...")
    export_index(df, site_names, dashboard_root, round_name, pred_col)

    print("\n[4] Exporting city_series.json...")
    city = export_city_series(df, dashboard_root)

    print("\n[5] Exporting site_series/...")
    site_ids = export_site_series(df, site_names, dashboard_root)

    print("\n[6] Exporting site_metrics.json...")
    print("\n[6b] Computing test 6-19 zero ratio stats...")
    test_daytime_zero_stats = compute_site_test_daytime_zero_stats(df)
    metrics_path = Path(output_root) / "metrics" / "site_test_daytime_zero_ratio_summary.csv"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    test_daytime_zero_stats.to_csv(metrics_path, index=False, encoding="utf-8-sig")
    print(f"  [OK] site_test_daytime_zero_ratio_summary.csv ({len(test_daytime_zero_stats)} sites)")
    metrics_df = export_site_metrics(df, site_names, dashboard_root, test_daytime_zero_stats)

    print("\n[7] Exporting midday_city_by_date.json...")
    export_midday_city(df, dashboard_root)

    print("\n[8] Exporting season_days.json...")
    export_season_days(df, dashboard_root)

    print("\n[9] Exporting scatter_site_hour.json...")
    scatter_data = export_scatter_site_hour(df, site_names, metrics_df, dashboard_root)

    print("\n[9b] Exporting scatter_site_sample_nrmse.json...")
    sm_df = load_site_master_full(output_root)
    scatter_site = export_scatter_site_sample_nrmse(df, site_names, sm_df, metrics_df, dashboard_root, test_daytime_zero_stats)

    print("\n[9c] Exporting invalid_zero_sites.json...")
    invalid_zero_sites = export_invalid_zero_sites(metrics_df, dashboard_root, df)

    print("\n[9d] Exporting sample_requirement_summary.json...")
    sample_req_summary = export_sample_requirement_summary(scatter_site, dashboard_root)

    print("\n[9d] Exporting sample_requirement_bins.json...")
    sample_req_bins = export_sample_requirement_bins(scatter_site, dashboard_root)

    print("\n[10] Exporting error_threshold_summary.json...")
    export_error_threshold_summary(scatter_data, dashboard_root)

    print("\n[10b] Exporting hourly_prediction_summary.json...")
    hourly_summary = export_hourly_prediction_summary(output_root, dashboard_root, df, round_name)

    # Validation
    print("\n[11] Validating outputs...")
    assert len(city) > 0, "city_series is empty"
    assert len(metrics_df) > 0, "site_metrics is empty"
    assert len(scatter_data) > 0, "scatter is empty"
    assert len(site_ids) > 0, "no site series files"
    assert isinstance(scatter_site, list) and len(scatter_site) > 0, "scatter_site_sample_nrmse is empty"
    assert len(sample_req_summary) == 5, f"expected 5 thresholds, got {len(sample_req_summary)}"
    assert len(sample_req_bins) > 0, "sample_requirement_bins is empty"
    assert "train_valid_positive_rows" in scatter_site[0], "missing train_valid_positive_rows field"
    assert "full_history_rows" in scatter_site[0], "missing full_history_rows field"
    assert "full_history_positive_rows" in scatter_site[0], "missing full_history_positive_rows field"
    assert "full_history_zero_ratio_pct" in scatter_site[0], "missing full_history_zero_ratio_pct field"
    assert "full_history_start_date" in scatter_site[0], "missing full_history_start_date field"
    assert "full_history_end_date" in scatter_site[0], "missing full_history_end_date field"
    assert "test_nrmse_pct" in scatter_site[0], "missing test_nrmse_pct field"
    assert "median_full_history_rows" in sample_req_summary[0], "missing median_full_history_rows in summary"
    assert len(hourly_summary) == 14, f"hourly_summary expected 14 rows (6-19h), got {len(hourly_summary)}"
    assert "hour" in hourly_summary[0], "missing hour field"
    assert "rows" in hourly_summary[0], "missing rows field"
    assert "site_nrmse_mean_pct" in hourly_summary[0], "missing site_nrmse_mean_pct field"
    assert "city_nrmse_pct" in hourly_summary[0], "missing city_nrmse_pct field"
    # Verify future is excluded from city_series
    future_in_city = any(r.get("split") == "future" for r in city.to_dict(orient="records"))
    assert not future_in_city, "city_series still contains future rows"
    # Verify all-zero sites excluded from scatter
    bad_scatter = [
        r for r in scatter_site
        if (r.get("full_history_positive_rows") or 0) <= 0
        or (r.get("full_history_zero_ratio_pct") or 0) >= 99.999
    ]
    assert not bad_scatter, f"scatter contains all-zero sites: {[r.get('site_id') for r in bad_scatter]}"
    assert isinstance(invalid_zero_sites, list), "invalid_zero_sites.json not valid"
    total_actual = city["actual_mw"].sum()
    total_pred = city["pred_mw"].sum()
    assert total_actual > 0, "actual_mw all zero"
    assert total_pred > 0, "pred_mw all zero"
    print(f"  All assertions passed.")

    # [11b] Validate dashboard actual_mw against source pkl
    print("\n[11b] Validating dashboard actual values...")
    integrity_summary = validate_dashboard_actual_values(df, dashboard_root, output_root)
    assert integrity_summary["status"] == "PASS", f"integrity check failed: {integrity_summary}"
    assert integrity_summary["max_abs_diff"] <= 1e-9, f"max_abs_diff too large: {integrity_summary['max_abs_diff']}"

    # [11c] Secondary validation against power_clean.pkl
    print("\n[11c] Validating against power_clean.pkl...")
    validate_against_power_clean(dashboard_root, output_root)

    # [11d] Write metadata.json
    print("\n[11d] Writing metadata.json...")
    meta = write_metadata(dashboard_root, round_name, pred_col, pred_path)

    # Summary
    history_df = build_history_frame(df)
    history_dates = pd.to_datetime(history_df["date"]).dropna().unique()
    min_date = pd.to_datetime(history_dates).min().strftime("%Y-%m-%d")
    max_date = pd.to_datetime(history_dates).max().strftime("%Y-%m-%d")
    site_series_dir = Path(dashboard_root) / "site_series"
    site_series_count = len(list(site_series_dir.glob("*.json")))

    print(f"\n[OK] interactive dashboard data exported")
    print(f"     round        = {round_name}")
    print(f"     pred_col    = {pred_col}")
    print(f"     rows        = {len(history_df[history_df['hour'].between(6,19)]):,}")
    print(f"     sites       = {len(site_ids)}")
    print(f"     date_range  = {min_date} ~ {max_date}")
    print(f"     city_series = {len(city):,} rows")
    print(f"     site_series = {site_series_count} files")
    print(f"     scatter_pts (site-hour) = {len(scatter_data)}")
    print(f"     scatter_pts (site)      = {len(scatter_site)}")
    print(f"     invalid_zero_sites      = {len(invalid_zero_sites)}")
    print(f"     hourly_prediction_summary = {len(hourly_summary)} rows (6-19h)")
    print(f"\nDashboard root: {dashboard_root}")
    print(f"Run: python -m http.server 8060")
    print(f"Open: http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html")


if __name__ == "__main__":
    main()
