"""
round45_guard_and_commit.py
==========================
Round45 Step 3: 守门检查 + 提交。

在 valid 集上对比：
- base（无校准）：power_pred_final_before_round45
- candidate（有校准）：power_pred_final_round45_candidate

五项条件全部满足才启用候选：
1. valid 站点平均 NRMSE 下降 >= 0.2pp
2. valid 全市 NRMSE 上升 <= 0.3pp
3. valid 10-14 全市 NRMSE 上升 <= 0.3pp
4. valid 全市 |bias| <= 15%
5. valid edge suspicious zero count == 0

若任一条件不满足，自动回退到 base。
"""

from pathlib import Path
import math
import shutil
import numpy as np
import pandas as pd


ROOT = Path("output/pv_pipeline")
TABLE_DIR = ROOT / "tables"
METRIC_DIR = ROOT / "metrics"
METRIC_DIR.mkdir(parents=True, exist_ok=True)


def find_final_pkl():
    candidates = sorted(TABLE_DIR.glob("distributed_predictions_final_round*.pkl"))
    if candidates:
        return candidates[-1]
    for name in ["distributed_predictions_final_full.pkl", "distributed_predictions_final.pkl"]:
        p = TABLE_DIR / name
        if p.exists():
            return p
    raise FileNotFoundError("找不到 distributed_predictions_final*.pkl")


def normalize(df):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    return df


def rmse(x):
    x = np.asarray(x, dtype=float)
    return math.sqrt(float(np.mean(x * x))) if len(x) else np.nan


def evaluate(df, pred_col, split="valid"):
    work = df[
        df["split"].eq(split)
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df[pred_col].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()

    work["actual_mw"] = pd.to_numeric(work["power_mw"], errors="coerce")
    work["pred_mw"] = pd.to_numeric(work[pred_col], errors="coerce")
    work["capacity_mw"] = pd.to_numeric(work["capacity_mw"], errors="coerce")

    city = work.groupby("time", as_index=False).agg(
        actual_mw=("actual_mw", "sum"),
        pred_mw=("pred_mw", "sum"),
        capacity_sum_mw=("capacity_mw", "sum"),
    )
    city_err = city["pred_mw"] - city["actual_mw"]
    city_nrmse = rmse(city_err) / max(float(city["capacity_sum_mw"].mean()), 1e-9) * 100
    city_bias = (city["pred_mw"].sum() - city["actual_mw"].sum()) / max(city["actual_mw"].sum(), 1e-9) * 100

    focus = work[work["hour"].isin([10, 11, 12, 13, 14])].copy()
    focus_city = focus.groupby("time", as_index=False).agg(
        actual_mw=("actual_mw", "sum"),
        pred_mw=("pred_mw", "sum"),
        capacity_sum_mw=("capacity_mw", "sum"),
    )
    focus_err = focus_city["pred_mw"] - focus_city["actual_mw"]
    focus_nrmse = rmse(focus_err) / max(float(focus_city["capacity_sum_mw"].mean()), 1e-9) * 100

    edge = work[work["hour"].isin([6, 7, 18, 19])].copy()
    edge_city = edge.groupby("time", as_index=False).agg(
        actual_mw=("actual_mw", "sum"),
        pred_mw=("pred_mw", "sum"),
    )
    suspicious_zero = int(((edge_city["actual_mw"] > 1e-9) & (edge_city["pred_mw"].abs() <= 1e-9)).sum())

    site_rows = []
    for sid, g in work.groupby("site_id"):
        err = g["pred_mw"] - g["actual_mw"]
        cap = float(g["capacity_mw"].mean())
        site_rows.append(rmse(err) / max(cap, 1e-9) * 100)

    return {
        "split": split,
        "pred_col": pred_col,
        "city_nrmse_pct": float(city_nrmse),
        "city_bias_pct": float(city_bias),
        "focus_10_14_city_nrmse_pct": float(focus_nrmse),
        "edge_suspicious_city_zero_count": suspicious_zero,
        "site_mean_nrmse_pct": float(np.mean(site_rows)),
        "site_median_nrmse_pct": float(np.median(site_rows)),
    }


def main():
    pkl = find_final_pkl()
    backup = pkl.with_suffix(".before_round45.pkl")

    df = pd.read_pickle(pkl)
    df = normalize(df)

    if "power_pred_final_round45_candidate" not in df.columns:
        raise SystemExit(
            "缺少 power_pred_final_round45_candidate，"
            "请先运行 round45_apply_site_hour_shrinkage_calibration.py"
        )

    base_col = "power_pred_final_before_round45"
    if base_col not in df.columns:
        base_col = "power_pred_final"
    cand_col = "power_pred_final_round45_candidate"

    base_valid = evaluate(df, base_col, split="valid")
    cand_valid = evaluate(df, cand_col, split="valid")

    site_improve = base_valid["site_mean_nrmse_pct"] - cand_valid["site_mean_nrmse_pct"]
    city_delta = cand_valid["city_nrmse_pct"] - base_valid["city_nrmse_pct"]
    focus_delta = cand_valid["focus_10_14_city_nrmse_pct"] - base_valid["focus_10_14_city_nrmse_pct"]

    cond1 = site_improve >= 0.2
    cond2 = city_delta <= 0.3
    cond3 = focus_delta <= 0.3
    cond4 = abs(cand_valid["city_bias_pct"]) <= 15.0
    cond5 = cand_valid["edge_suspicious_city_zero_count"] == 0

    use_candidate = cond1 and cond2 and cond3 and cond4 and cond5

    row = {
        "use_round45_candidate": use_candidate,
        "site_improve_valid_pp": round(site_improve, 6),
        "city_delta_valid_pp": round(city_delta, 6),
        "focus_delta_valid_pp": round(focus_delta, 6),
        "base_site_mean_nrmse": round(base_valid["site_mean_nrmse_pct"], 6),
        "cand_site_mean_nrmse": round(cand_valid["site_mean_nrmse_pct"], 6),
        "base_city_nrmse": round(base_valid["city_nrmse_pct"], 6),
        "cand_city_nrmse": round(cand_valid["city_nrmse_pct"], 6),
        "base_focus_nrmse": round(base_valid["focus_10_14_city_nrmse_pct"], 6),
        "cand_focus_nrmse": round(cand_valid["focus_10_14_city_nrmse_pct"], 6),
        "cand_city_bias": round(cand_valid["city_bias_pct"], 6),
        "cand_edge_suspicious_zero": cand_valid["edge_suspicious_city_zero_count"],
        "cond1_site_improve_ge_0.2": cond1,
        "cond2_city_delta_le_0.3": cond2,
        "cond3_focus_delta_le_0.3": cond3,
        "cond4_bias_le_15": cond4,
        "cond5_edge_zero_eq_0": cond5,
    }
    pd.DataFrame([row]).to_csv(METRIC_DIR / "round45_guard_decision.csv", index=False, encoding="utf-8-sig")

    print("=" * 50)
    print("Round45 Guard Decision (valid 集)")
    print("=" * 50)
    print(f"  站点平均 NRMSE 改善: {site_improve:+.4f}pp (需 >= 0.2) [{cond1}]")
    print(f"  全市 NRMSE 变化: {city_delta:+.4f}pp (需 <= 0.3) [{cond2}]")
    print(f"  10-14 全市 NRMSE 变化: {focus_delta:+.4f}pp (需 <= 0.3) [{cond3}]")
    print(f"  全市 |bias|: {abs(cand_valid['city_bias_pct']):.4f}% (需 <= 15) [{cond4}]")
    print(f"  Edge 可疑 0 值数: {cand_valid['edge_suspicious_city_zero_count']} (需 == 0) [{cond5}]")
    print(f"\n  base 站点 NRMSE: {base_valid['site_mean_nrmse_pct']:.4f}%")
    print(f"  cand 站点 NRMSE: {cand_valid['site_mean_nrmse_pct']:.4f}%")

    if use_candidate:
        df["power_pred_final"] = df[cand_col]
        print(f"\n[PASS] Round45 candidate accepted (5/5 conditions met)")
    else:
        df["power_pred_final"] = df[base_col]
        print(f"\n[RESTORE] Round45 candidate rejected, restored base prediction")

    tmp = pkl.with_suffix(".round45_guard.tmp.pkl")
    df.to_pickle(tmp)
    check = pd.read_pickle(tmp)
    assert len(check) == len(df)
    tmp.replace(pkl)
    print(f"[OK] updated: {pkl}")


if __name__ == "__main__":
    main()
