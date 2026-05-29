#!/usr/bin/env python3
"""审计早晚临界小时（6/7/18/19）的预测是否为 0，定位根因在 PKL 还是在导出环节。"""
from pathlib import Path
import json
import numpy as np
import pandas as pd


ROOT = Path("output/pv_pipeline")
TABLE_DIR = ROOT / "tables"
DASH_DIR = ROOT / "interactive_dashboard"
OUT_DIR = ROOT / "metrics"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def find_latest_final_pkl():
    candidates = sorted(TABLE_DIR.glob("distributed_predictions_final_round*.pkl"))
    if candidates:
        return candidates[-1]
    for name in [
        "distributed_predictions_final_full.pkl",
        "distributed_predictions_final.pkl",
    ]:
        p = TABLE_DIR / name
        if p.exists():
            return p
    raise FileNotFoundError("未找到 distributed_predictions_final*.pkl")


def resolve_pred_col(df):
    for c in ["power_pred_final", "pred_mw", "power_pred_cal", "pred_calibrated", "power_pred"]:
        if c in df.columns:
            return c
    raise KeyError(f"未找到预测列，当前列：{list(df.columns)[:80]}")


def main():
    pkl = find_latest_final_pkl()
    df = pd.read_pickle(pkl).copy()
    pred_col = resolve_pred_col(df)

    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    if "date" not in df.columns:
        df["date"] = df["time"].dt.strftime("%Y-%m-%d")

    # 只审计可视化默认口径：非 future、6-19 点
    if "split" in df.columns:
        df = df[df["split"].isin(["train", "valid", "test"])].copy()
    df = df[df["hour"].between(6, 19)].copy()

    df["actual_mw"] = pd.to_numeric(df.get("power_mw"), errors="coerce")
    df["pred_mw"] = pd.to_numeric(df[pred_col], errors="coerce")

    edge = df[df["hour"].isin([6, 7, 18, 19])].copy()
    edge["pred_is_nan"] = edge["pred_mw"].isna()
    edge["pred_is_zero"] = edge["pred_mw"].fillna(np.nan).eq(0)
    edge["actual_positive"] = edge["actual_mw"].fillna(0).gt(0)

    by_time = (
        edge.groupby(["time", "date", "hour"], as_index=False)
        .agg(
            site_rows=("site_id", "size"),
            site_count=("site_id", "nunique"),
            actual_city_mw=("actual_mw", "sum"),
            pred_city_mw=("pred_mw", "sum"),
            pred_nan_sites=("pred_is_nan", "sum"),
            pred_zero_sites=("pred_is_zero", "sum"),
            actual_positive_sites=("actual_positive", "sum"),
            capacity_sum_mw=("capacity_mw", "sum"),
        )
    )
    by_time["pred_city_is_zero"] = by_time["pred_city_mw"].abs() <= 1e-9
    by_time["actual_city_positive"] = by_time["actual_city_mw"] > 1e-9
    by_time["suspicious_city_zero"] = by_time["pred_city_is_zero"] & by_time["actual_city_positive"]
    by_time["zero_site_ratio_pct"] = by_time["pred_zero_sites"] / by_time["site_rows"].clip(lower=1) * 100

    by_hour = (
        by_time.groupby("hour", as_index=False)
        .agg(
            timestamps=("time", "size"),
            suspicious_city_zero_count=("suspicious_city_zero", "sum"),
            suspicious_city_zero_ratio_pct=("suspicious_city_zero", "mean"),
            mean_actual_city_mw=("actual_city_mw", "mean"),
            mean_pred_city_mw=("pred_city_mw", "mean"),
            mean_zero_site_ratio_pct=("zero_site_ratio_pct", "mean"),
            mean_pred_nan_sites=("pred_nan_sites", "mean"),
        )
    )
    by_hour["suspicious_city_zero_ratio_pct"] *= 100

    by_time.to_csv(OUT_DIR / "round39_edge_hour_zero_by_time.csv", index=False, encoding="utf-8-sig")
    by_hour.to_csv(OUT_DIR / "round39_edge_hour_zero_by_hour.csv", index=False, encoding="utf-8-sig")

    # 与 dashboard city_series 对比，判断是否导出环节导致
    city_json = DASH_DIR / "city_series.json"
    if city_json.exists():
        city = pd.read_json(city_json)
        city["time"] = pd.to_datetime(city["time"])
        cmp = by_time.merge(
            city[["time", "actual_mw", "pred_mw"]],
            on="time",
            how="left",
            suffixes=("_pkl", "_dashboard"),
        )
        cmp["actual_diff"] = cmp["actual_city_mw"] - cmp["actual_mw"]
        cmp["pred_diff"] = cmp["pred_city_mw"] - cmp["pred_mw"]
        cmp.to_csv(OUT_DIR / "round39_edge_hour_pkl_vs_dashboard.csv", index=False, encoding="utf-8-sig")

    print("[OK] pkl:", pkl)
    print("[OK] pred_col:", pred_col)
    print(by_hour.to_string(index=False))
    print("[OK] wrote:")
    print(" -", OUT_DIR / "round39_edge_hour_zero_by_time.csv")
    print(" -", OUT_DIR / "round39_edge_hour_zero_by_hour.csv")
    print(" -", OUT_DIR / "round39_edge_hour_pkl_vs_dashboard.csv")


if __name__ == "__main__":
    main()
