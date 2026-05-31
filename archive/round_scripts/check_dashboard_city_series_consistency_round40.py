from pathlib import Path
import json
import numpy as np
import pandas as pd


ROOT = Path("output/pv_pipeline")
TABLE_DIR = ROOT / "tables"
DASH_DIR = ROOT / "interactive_dashboard"


def find_final_pkl():
    candidates = sorted(TABLE_DIR.glob("distributed_predictions_final_round*.pkl"))
    if candidates:
        return candidates[-1]
    return TABLE_DIR / "distributed_predictions_final_full.pkl"


def main():
    pkl = find_final_pkl()
    df = pd.read_pickle(pkl).copy()
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    if "split" in df.columns:
        df = df[df["split"].isin(["train", "valid", "test"])].copy()
    df = df[df["hour"].between(6, 19)].copy()
    df = df[df["power_mw"].notna() & df["power_pred_final"].notna()].copy()

    city_pkl = (
        df.groupby("time", as_index=False)
        .agg(
            actual_mw=("power_mw", "sum"),
            pred_mw=("power_pred_final", "sum"),
            n_sites=("site_id", "nunique"),
            capacity_sum_mw=("capacity_mw", "sum"),
        )
    )

    city_json = pd.read_json(DASH_DIR / "city_series.json")
    city_json["time"] = pd.to_datetime(city_json["time"])

    cmp = city_pkl.merge(
        city_json[["time", "actual_mw", "pred_mw", "n_sites", "capacity_sum_mw"]],
        on="time",
        how="outer",
        suffixes=("_pkl", "_json"),
        indicator=True,
    )

    for col in ["actual_mw", "pred_mw", "capacity_sum_mw"]:
        cmp[f"{col}_diff"] = cmp[f"{col}_pkl"] - cmp[f"{col}_json"]

    max_pred_diff = float(cmp["pred_mw_diff"].abs().max())
    max_actual_diff = float(cmp["actual_mw_diff"].abs().max())
    bad_merge = cmp[cmp["_merge"].ne("both")]

    out = ROOT / "metrics" / "round40_dashboard_city_series_consistency.csv"
    cmp.to_csv(out, index=False, encoding="utf-8-sig")

    print("[OK] pkl:", pkl)
    print("rows pkl/json/merged:", len(city_pkl), len(city_json), len(cmp))
    print("max_actual_diff:", max_actual_diff)
    print("max_pred_diff:", max_pred_diff)
    print("bad_merge_rows:", len(bad_merge))

    assert len(bad_merge) == 0, "city_series 与 pkl 时间戳不一致"
    # 4-decimal rounding in JSON export → max rounding error ≈ 0.00005 per aggregated row
    # actual_mw uses same rounding; use 1e-3 as safe tolerance
    assert max_actual_diff <= 1e-3, f"actual_mw 不一致 (max={max_actual_diff})"
    assert max_pred_diff <= 1e-3, f"pred_mw 不一致 (max={max_pred_diff})"
    print("[PASS] dashboard city_series matches final pkl")


if __name__ == "__main__":
    main()
