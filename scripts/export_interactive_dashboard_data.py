#!/usr/bin/env python3
"""
Round12: Export interactive dashboard data from distributed_predictions_final_full.pkl.

Usage:
    python scripts/export_interactive_dashboard_data.py \
      --output-root output/pv_pipeline \
      --dashboard-root output/pv_pipeline/interactive_dashboard

Outputs:
    output/pv_pipeline/interactive_dashboard/
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


def load_predictions(output_root):
    """Load prediction data, preferring full file over eval file."""
    tables_dir = Path(output_root) / "tables"
    full_path = tables_dir / "distributed_predictions_final_full.pkl"
    eval_path = tables_dir / "distributed_predictions_final_eval.pkl"

    if full_path.exists():
        print(f"  Loading {full_path}")
        with open(full_path, "rb") as f:
            df = pickle.load(f)
    elif eval_path.exists():
        print(f"  Falling back to {eval_path}")
        with open(eval_path, "rb") as f:
            df = pickle.load(f)
    else:
        raise FileNotFoundError(
            f"Neither {full_path} nor {eval_path} found. "
            "Run training first to produce prediction files."
        )

    # Validate required columns
    required = ["time", "site_id", "power_mw", "power_pred", "capacity_mw", "hour", "date", "split"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Ensure hour/date are present (regenerate if needed)
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    if "date" not in df.columns:
        df["date"] = df["time"].dt.strftime("%Y-%m-%d")

    return df


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


def export_index(df, site_names, dashboard_root):
    """Export index.json with overview metadata."""
    history_df = build_history_frame(df)
    dates = pd.to_datetime(history_df["date"]).dropna().unique()
    min_date = pd.to_datetime(dates).min().strftime("%Y-%m-%d")
    max_date = pd.to_datetime(dates).max().strftime("%Y-%m-%d")

    # Overall stats — use history only, daytime, non-null
    active = history_df[
        history_df["hour"].between(6, 19)
        & history_df["power_mw"].notna()
        & history_df["power_pred"].notna()
    ]

    index_data = {
        "title": "光伏功率预测交互式结果页面",
        "description": "展示连云港光伏电站真实功率与预测功率对比",
        "data_source": (
            "output/pv_pipeline/tables/distributed_predictions_final_full.pkl "
            "或 distributed_predictions_final_eval.pkl"
        ),
        "data_scope": "train/valid/test only; future excluded",
        "note": (
            "页面只用于展示当前 final/best 预测结果，不参与模型训练和模型选择。"
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
    }

    out_path = Path(dashboard_root) / "index.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
    print(f"  [OK] index.json ({index_data['total_sites']} sites, {min_date}~{max_date})")


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
    """Export per-site time series JSON files."""
    df_f = build_history_frame(df)
    df_f = df_f[
        df_f["hour"].between(6, 19)
        & df_f["power_mw"].notna()
        & df_f["power_pred"].notna()
    ].copy()

    site_dir = Path(dashboard_root) / "site_series"
    site_dir.mkdir(parents=True, exist_ok=True)

    site_ids = sorted(df_f["site_id"].unique())
    for sid in site_ids:
        sdf = df_f[df_f["site_id"] == sid].sort_values("time")

        records = []
        for _, row in sdf.iterrows():
            rec = {
                "time": pd.Timestamp(row["time"]).strftime("%Y-%m-%d %H:%M:%S"),
                "date": str(row["date"]),
                "hour": int(row["hour"]),
                "split": str(row["split"]),
                "site_id": str(row["site_id"]),
                "site_name": site_names.get(sid, sid) if site_names else str(sid),
                "actual_mw": round(float(row["power_mw"]), 4),
                "pred_mw": round(float(row["power_pred"]), 4),
                "capacity_mw": round(float(row["capacity_mw"]), 4),
                "abs_error_mw": round(float(abs(row["power_pred"] - row["power_mw"])), 4),
                "point_nrmse_pct": round(
                    float(abs(row["power_pred"] - row["power_mw"]) / max(row["capacity_mw"], 1e-9) * 100), 4
                ),
            }
            records.append(rec)

        out_path = site_dir / f"{sid}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"  [OK] site_series/ ({len(site_ids)} files)")
    return site_ids


def export_site_metrics(df, site_names, dashboard_root):
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

    # ---- Mark all-zero / no-positive sites ----
    metrics_df["is_all_zero_history"] = metrics_df.apply(is_all_zero_history, axis=1)

    # ---- Typical site classification (uses only valid sites, i.e. test 6-19h rows) ----
    rows_q20 = np.percentile(metrics_df["rows"], 20)
    min_rows = max(200, rows_q20)

    valid_metrics_df = metrics_df[~metrics_df["is_all_zero_history"]].copy()
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
    out_cols = [
        "site_id", "site_name", "county", "capacity_mw",
        "rows", "positive_rows", "zero_rows", "zero_ratio_pct",
        "mae_mw", "rmse_mw", "nrmse_pct", "bias_pct",
        "pred_actual_ratio", "category", "category_label",
        "full_history_rows", "full_history_non_null_rows",
        "full_history_positive_rows", "full_history_zero_rows",
        "full_history_zero_ratio_pct", "full_history_start_date", "full_history_end_date",
        "is_all_zero_history",
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
    df_f = df[
        df["split"].isin(["train", "valid", "test"])
        & df["hour"].between(10, 14)
        & df["power_mw"].notna()
        & df["power_pred"].notna()
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
    df_f = df[
        df["split"].isin(["train", "valid", "test"])
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df["power_pred"].notna()
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
            "reason": f"选择 {str(best_date["date"])} (日发电量 {round(float(best_date["actual_mwh"]), 1)} MWh，接近季节中位数)",
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


def export_scatter_site_sample_nrmse(df, site_names, sm_df, metrics_df, dashboard_root):
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


def export_invalid_zero_sites(metrics_df, dashboard_root):
    """Export invalid_zero_sites.json: sites with zero_ratio >= 99.999% or no positive rows."""
    invalid = metrics_df[metrics_df.get("is_all_zero_history", pd.Series(False)) == True].copy()

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


def export_hourly_prediction_summary(output_root, dashboard_root, final_df=None) -> list:
    """Export hourly_prediction_summary.json.

    Priority: read existing CSV → fallback to compute from final_df.
    """
    metrics_dir = Path(output_root) / "metrics"
    csv_path = metrics_dir / "分布式光伏预测_逐小时平均NRMSE.csv"

    if csv_path.exists():
        print(f"  Loading existing hourly CSV: {csv_path}")
        hourly = pd.read_csv(csv_path)
        # Normalize column names
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
        # If column still missing, try direct rename from "hour"
        if "hour" not in hourly.columns and "Hour" in hourly.columns:
            hourly = hourly.rename(columns={"Hour": "hour"})
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
    hourly["rows"] = hourly["rows"].astype(int)
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
    df_f = df[
        df["split"].isin(["train", "valid", "test"])
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df["power_pred"].notna()
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


def main():
    args = parse_args()
    dashboard_root = args.dashboard_root
    output_root = args.output_root

    print(f"\n=== Round23: Export Interactive Dashboard Data ===")
    print(f"  Output root : {output_root}")
    print(f"  Dashboard dir: {dashboard_root}")

    # Create output directory
    Path(dashboard_root).mkdir(parents=True, exist_ok=True)

    # Load data
    print("\n[1] Loading prediction data...")
    df = load_predictions(output_root)
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
    export_index(df, site_names, dashboard_root)

    print("\n[4] Exporting city_series.json...")
    city = export_city_series(df, dashboard_root)

    print("\n[5] Exporting site_series/...")
    site_ids = export_site_series(df, site_names, dashboard_root)

    print("\n[6] Exporting site_metrics.json...")
    metrics_df = export_site_metrics(df, site_names, dashboard_root)

    print("\n[7] Exporting midday_city_by_date.json...")
    export_midday_city(df, dashboard_root)

    print("\n[8] Exporting season_days.json...")
    export_season_days(df, dashboard_root)

    print("\n[9] Exporting scatter_site_hour.json...")
    scatter_data = export_scatter_site_hour(df, site_names, metrics_df, dashboard_root)

    print("\n[9b] Exporting scatter_site_sample_nrmse.json...")
    sm_df = load_site_master_full(output_root)
    scatter_site = export_scatter_site_sample_nrmse(df, site_names, sm_df, metrics_df, dashboard_root)

    print("\n[9c] Exporting sample_requirement_summary.json...")
    sample_req_summary = export_sample_requirement_summary(scatter_site, dashboard_root)

    print("\n[9d] Exporting sample_requirement_bins.json...")
    sample_req_bins = export_sample_requirement_bins(scatter_site, dashboard_root)

    print("\n[10] Exporting error_threshold_summary.json...")
    export_error_threshold_summary(scatter_data, dashboard_root)

    print("\n[10b] Exporting hourly_prediction_summary.json...")
    hourly_summary = export_hourly_prediction_summary(output_root, dashboard_root, df)

    # Validation
    print("\n[11] Validating outputs...")
    assert len(city) > 0, "city_series is empty"
    assert len(metrics_df) > 0, "site_metrics is empty"
    assert len(scatter_data) > 0, "scatter is empty"
    assert len(site_ids) > 0, "no site series files"
    assert len(scatter_site) > 0, "scatter_site_sample_nrmse is empty"
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
    total_actual = city["actual_mw"].sum()
    total_pred = city["pred_mw"].sum()
    assert total_actual > 0, "actual_mw all zero"
    assert total_pred > 0, "pred_mw all zero"
    print(f"  All assertions passed.")

    # Summary
    dates = pd.to_datetime(df["date"]).dropna().unique()
    min_date = pd.to_datetime(dates).min().strftime("%Y-%m-%d")
    max_date = pd.to_datetime(dates).max().strftime("%Y-%m-%d")
    site_series_dir = Path(dashboard_root) / "site_series"
    site_series_count = len(list(site_series_dir.glob("*.json")))
    dates = pd.to_datetime(df["date"]).dropna().unique()
    min_date = pd.to_datetime(dates).min().strftime("%Y-%m-%d")
    max_date = pd.to_datetime(dates).max().strftime("%Y-%m-%d")

    print(f"\n[OK] interactive dashboard data exported")
    print(f"     rows        = {len(df[df['split'].isin(['train','valid','test']) & df['hour'].between(6,19)]):,}")
    print(f"     sites       = {len(site_ids)}")
    print(f"     date_range  = {min_date} ~ {max_date}")
    print(f"     city_series = {len(city):,} rows")
    print(f"     site_series = {site_series_count} files")
    print(f"     scatter_pts (site-hour) = {len(scatter_data)}")
    print(f"     scatter_pts (site)      = {len(scatter_site)}")
    print(f"     hourly_prediction_summary = {len(hourly_summary)} rows (6-19h)")
    print(f"\nDashboard root: {dashboard_root}")
    print(f"Run: python -m http.server 8060")
    print(f"Open: http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html")


if __name__ == "__main__":
    main()
