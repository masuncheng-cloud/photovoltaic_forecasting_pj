#!/usr/bin/env python3
"""
compare_round58_59_60_61_metrics.py
==================================
四轮次（Round58/59/60/61）预测指标对比。

使用 Round61 plan 定义的统一公式：
  - city_nrmse: per-timestamp aggregation, per-hour average
  - site_mean_nrmse: mean of per-site NRMSE (normalized by own capacity)
  - bias%: (sum(pred) - sum(actual)) / sum(actual) * 100

在 test 集（6-19h）上评估。
在 valid 集（6-19h）上评估。
"""

from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline"
METRICS = OUT / "metrics"


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean((p - a) ** 2)))


def mae(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(np.mean(np.abs(p - a)))


def site_mean_nrmse(df, pred_col):
    vals = []
    for sid, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        vals.append(rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100)
    return float(np.mean(vals)) if vals else np.nan


def city_nrmse(df, pred_col):
    vals = []
    for h, hdf in df.groupby("hour"):
        agg = hdf.groupby("time", as_index=False).agg(
            actual=("power_mw", "sum"),
            pred=(pred_col, "sum"),
            cap_sum=("capacity_mw", "sum"),
        )
        r = rmse(agg["pred"].values, agg["actual"].values)
        cap_h = float(agg["cap_sum"].mean())
        if cap_h <= 0:
            continue
        vals.append(r / cap_h * 100)
    return float(np.mean(vals)) if vals else np.nan


def bias_pct(df, pred_col):
    a_sum = float(df["power_mw"].sum())
    p_sum = float(df[pred_col].sum())
    if abs(a_sum) < 1e-9:
        return np.nan
    return (p_sum - a_sum) / a_sum * 100


def rmse_mw(df, pred_col):
    return rmse(df["power_mw"].values, df[pred_col].values)


def mae_mw(df, pred_col):
    return mae(df["power_mw"].values, df[pred_col].values)


def eval_metrics(df, pred_col, hour_range=(6, 19), label=""):
    df_h = df[df["hour"].between(hour_range[0], hour_range[1])].copy()
    if len(df_h) == 0:
        return None

    sm_nrmse = site_mean_nrmse(df_h, pred_col)
    c_nrmse = city_nrmse(df_h, pred_col)
    b = bias_pct(df_h, pred_col)
    rm = rmse_mw(df_h, pred_col)
    ma = mae_mw(df_h, pred_col)

    df_10_14 = df_h[df_h["hour"].between(10, 14)]
    c_nrmse_1014 = city_nrmse(df_10_14, pred_col) if len(df_10_14) > 0 else np.nan
    sm_nrmse_1014 = site_mean_nrmse(df_10_14, pred_col) if len(df_10_14) > 0 else np.nan
    b_1014 = bias_pct(df_10_14, pred_col) if len(df_10_14) > 0 else np.nan

    return {
        "pred_col": pred_col,
        "label": label,
        "site_mean_nrmse_6_19": round(sm_nrmse, 4),
        "city_nrmse_6_19": round(c_nrmse, 4),
        "site_mean_nrmse_10_14": round(sm_nrmse_1014, 4),
        "city_nrmse_10_14": round(c_nrmse_1014, 4),
        "bias_6_19": round(b, 4),
        "bias_10_14": round(b_1014, 4),
        "abs_bias_6_19": round(abs(b), 4),
        "abs_bias_10_14": round(abs(b_1014), 4),
        "rmse_6_19": round(rm, 4),
        "mae_6_19": round(ma, 4),
    }


def count_bad_sites(df, pred_base, pred_cand, threshold=1.0):
    df_v = df[(df["split"] == "valid") & df["hour"].between(6, 19)].copy()
    bad = []
    for sid, sdf in df_v.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        base_rmse = rmse(sdf["power_mw"].values, sdf[pred_base].values)
        cand_rmse = rmse(sdf["power_mw"].values, sdf[pred_cand].values)
        delta = (cand_rmse - base_rmse) / cap * 100
        if delta > threshold:
            bad.append((str(sid), round(delta, 2)))
    return bad


def main():
    print("=" * 70)
    print("Round58 / Round59 / Round60 / Round61 四轮对比")
    print("=" * 70)

    # ── Load all datasets ──────────────────────────────────────────────
    r58 = pd.read_pickle(OUT / "baselines/round58/distributed_predictions_final_full.pkl")
    r59 = pd.read_pickle(OUT / "baselines/round59/distributed_predictions_final_full.pkl")
    r60 = pd.read_pickle(OUT / "baselines/round60/distributed_predictions_final_full.pkl")
    r61 = pd.read_pickle(OUT / "predictions/distributed_predictions_final_full.pkl")

    for df in [r58, r59, r60, r61]:
        df["time"] = pd.to_datetime(df["time"])
        if "hour" not in df.columns:
            df["hour"] = df["time"].dt.hour

    # Column mapping
    col_map = {
        "Round58": (r58, "power_pred_final"),
        "Round59": (r59, "power_pred_final_round59"),
        "Round60": (r60, "power_pred_final_round60"),
        "Round61": (r61, "power_pred_final"),
    }

    # ── Test set metrics ───────────────────────────────────────────────
    print("\n[Test 集 6-19h]")
    print(f"{'Round':<10} {'sm_nrmse':>10} {'c_nrmse':>10} {'sm_10_14':>10} {'c_10_14':>10} {'bias_6_19':>10} {'bias_10_14':>10} {'rmse':>8} {'mae':>8}")
    print("-" * 100)

    test_results = {}
    for name, (df, col) in col_map.items():
        r = eval_metrics(df[df["split"] == "test"], col, label=name)
        if r:
            test_results[name] = r
            print(
                f"{name:<10} "
                f"{r['site_mean_nrmse_6_19']:>10.4f} "
                f"{r['city_nrmse_6_19']:>10.4f} "
                f"{r['site_mean_nrmse_10_14']:>10.4f} "
                f"{r['city_nrmse_10_14']:>10.4f} "
                f"{r['bias_6_19']:>10.4f} "
                f"{r['bias_10_14']:>10.4f} "
                f"{r['rmse_6_19']:>8.4f} "
                f"{r['mae_6_19']:>8.4f}"
            )

    # ── Valid set metrics ──────────────────────────────────────────────
    print("\n[Valid 集 6-19h]")
    print(f"{'Round':<10} {'sm_nrmse':>10} {'c_nrmse':>10} {'sm_10_14':>10} {'c_10_14':>10} {'bias_6_19':>10} {'bias_10_14':>10}")
    print("-" * 80)

    valid_results = {}
    for name, (df, col) in col_map.items():
        r = eval_metrics(df[df["split"] == "valid"], col, label=name)
        if r:
            valid_results[name] = r
            print(
                f"{name:<10} "
                f"{r['site_mean_nrmse_6_19']:>10.4f} "
                f"{r['city_nrmse_6_19']:>10.4f} "
                f"{r['site_mean_nrmse_10_14']:>10.4f} "
                f"{r['city_nrmse_10_14']:>10.4f} "
                f"{r['bias_6_19']:>10.4f} "
                f"{r['bias_10_14']:>10.4f}"
            )

    # ── Per-hour comparison on test set ────────────────────────────────
    print("\n[Test 集 逐小时 city_nrmse]")
    hours_of_interest = [7, 10, 11, 12, 13, 14, 17, 18, 19]

    hour_rows = []
    for h in sorted(range(6, 20)):
        row = {"hour": h}
        for name, (df, col) in col_map.items():
            hdf = df[(df["split"] == "test") & (df["hour"] == h)]
            if len(hdf) == 0:
                row[name] = np.nan
                continue
            agg = hdf.groupby("time", as_index=False).agg(
                actual=("power_mw", "sum"),
                pred=(col, "sum"),
                cap_sum=("capacity_mw", "sum"),
            )
            r = rmse(agg["pred"].values, agg["actual"].values)
            cap_h = float(agg["cap_sum"].mean())
            row[name] = round(r / cap_h * 100, 4) if cap_h > 0 else np.nan
        hour_rows.append(row)

    hour_df = pd.DataFrame(hour_rows)
    print(f"{'Hour':>5}", end="")
    for name in col_map:
        print(f" {name:>10}", end="")
    print()
    for _, r in hour_df.iterrows():
        flag = "*" if int(r["hour"]) in hours_of_interest else " "
        print(f"{flag}{int(r['hour']):>4}", end="")
        for name in col_map:
            v = r.get(name, np.nan)
            print(f" {v:>10.4f}" if not np.isnan(v) else f" {'nan':>10}", end="")
        print()

    # ── Per-site comparison (key sites) ────────────────────────────────
    print("\n[Test 集 重点站点 site_nrmse]")
    key_sites = ["S012", "S019", "S032", "S053", "S071", "S115", "S116", "S022", "S050", "S004"]

    site_rows = []
    for sid in key_sites:
        row = {"site_id": sid}
        for name, (df, col) in col_map.items():
            sdf = df[(df["split"] == "test") & (df["site_id"] == sid) & df["hour"].between(6, 19)]
            if len(sdf) == 0:
                row[name] = np.nan
                continue
            cap = float(sdf["capacity_mw"].iloc[0])
            if cap <= 0:
                row[name] = np.nan
                continue
            row[name] = round(rmse(sdf["power_mw"].values, sdf[col].values) / cap * 100, 4)
        site_rows.append(row)

    site_df = pd.DataFrame(site_rows)
    print(f"{'Site':>6}", end="")
    for name in col_map:
        print(f" {name:>10}", end="")
    print()
    for _, r in site_df.iterrows():
        print(f"{r['site_id']:>6}", end="")
        for name in col_map:
            v = r.get(name, np.nan)
            print(f" {v:>10.4f}" if not np.isnan(v) else f" {'nan':>10}", end="")
        print()

    # ── Bad site count (valid set) ─────────────────────────────────────
    print("\n[Valid 集 变差>+1pp 的站点数量]")
    baseline_pairs = [
        ("Round58", "power_pred_final", "power_pred_final"),
        ("Round59", "power_pred_final", "power_pred_final_round59"),
        ("Round60", "power_pred_final", "power_pred_final_round60"),
        ("Round61", "power_pred_final", "power_pred_final"),
    ]
    for name, base_col, cand_col in baseline_pairs:
        if name == "Round61":
            base_df = r60
            cand_df = r61
        else:
            base_df = col_map[name][0]
            cand_df = col_map[name][0]
        bad = count_bad_sites(cand_df, base_col, cand_col, threshold=1.0)
        print(f"  {name}: {len(bad)} sites > +1pp")
        for sid, delta in bad[:5]:
            print(f"    {sid}: {delta:+.2f}pp")

    # ── Save CSVs ───────────────────────────────────────────────────────
    test_summary = pd.DataFrame(list(test_results.values()))
    test_summary.to_csv(METRICS / "round61_compare_summary.csv", index=False, encoding="utf-8-sig")

    hour_df.to_csv(METRICS / "round61_compare_hourly.csv", index=False, encoding="utf-8-sig")

    site_df.to_csv(METRICS / "round61_compare_site.csv", index=False, encoding="utf-8-sig")

    print(f"\n[OK] Saved:")
    print(f"  {METRICS / 'round61_compare_summary.csv'}")
    print(f"  {METRICS / 'round61_compare_hourly.csv'}")
    print(f"  {METRICS / 'round61_compare_site.csv'}")

    # ── Delta table vs Round58 ─────────────────────────────────────────
    print("\n[Delta vs Round58 (test 6-19h)]")
    r58_test = test_results.get("Round58", {})
    print(f"{'Round':<10} {'Δsm_nrmse':>10} {'Δc_nrmse':>10} {'Δbias_abs':>10} {'Δc_nrmse_10_14':>15}")
    print("-" * 60)
    for name in ["Round59", "Round60", "Round61"]:
        if name not in test_results:
            continue
        r = test_results[name]
        ds = r['site_mean_nrmse_6_19'] - r58_test['site_mean_nrmse_6_19']
        dc = r['city_nrmse_6_19'] - r58_test['city_nrmse_6_19']
        da = r['abs_bias_6_19'] - r58_test['abs_bias_6_19']
        dc14 = r['city_nrmse_10_14'] - r58_test['city_nrmse_10_14']
        print(f"{name:<10} {ds:>+10.4f} {dc:>+10.4f} {da:>+10.4f} {dc14:>+15.4f}")


if __name__ == "__main__":
    main()
