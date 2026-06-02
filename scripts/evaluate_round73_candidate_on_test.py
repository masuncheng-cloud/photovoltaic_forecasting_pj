#!/usr/bin/env python3
"""
evaluate_round73_candidate_on_test.py
"""

import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round73"


def _rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def _city_nrmse(df, pred_col):
    cap = float(df.drop_duplicates("site_id")["capacity_mw"].sum())
    agg = df.groupby("time", as_index=False).agg(
        a=("power_mw", "sum"), p=(pred_col, "sum"))
    return _rmse(agg["a"].values, agg["p"].values) / cap * 100 if cap > 0 else float("nan")


def _city_nrmse_hours(df, pred_col, hours):
    vals = []
    d = df[df["hour"].isin(hours)]
    for _, g in d.groupby("hour"):
        cap = float(g.drop_duplicates("site_id")["capacity_mw"].sum())
        agg = g.groupby("time", as_index=False).agg(
            a=("power_mw", "sum"), p=(pred_col, "sum"))
        if cap > 0:
            vals.append(_rmse(agg["a"].values, agg["p"].values) / cap * 100)
    return float(np.mean(vals)) if vals else float("nan")


def _bias(df, pred_col):
    a = float(df["power_mw"].sum())
    p = float(df[pred_col].sum())
    return (p - a) / a * 100 if abs(a) > 1e-9 else float("nan")


def _bias_hours(df, pred_col, hours):
    d = df[df["hour"].isin(hours)]
    return _bias(d, pred_col)


def _site_mean_nrmse(df, pred_col):
    vals = []
    for _, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        vals.append(_rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100)
    return float(np.mean(vals)) if vals else float("nan")


def _bad_sites(df, base_col, cand_col, threshold=1.0):
    n = 0
    details = []
    for _, sdf in df[df["hour"].between(6, 19)].groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        b = _rmse(sdf["power_mw"].values, sdf[base_col].values)
        c = _rmse(sdf["power_mw"].values, sdf[cand_col].values)
        delta = (c - b) / cap * 100
        if delta > threshold:
            n += 1
            details.append((str(sdf["site_id"].iloc[0]), round(delta, 2)))
    return n, details


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    pkl = OUT / "round73_candidates.pkl"
    print(f"[INFO] 读取: {pkl}")
    df = pd.read_pickle(pkl)
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour

    bl_col = "power_pred_final"
    focus = [10, 11, 12, 13, 14]
    df = df[df["hour"].between(6, 19)]
    test_df = df[df["split"] == "test"].copy()
    print(f"  test: {len(test_df):,}")

    with open(OUT / "round73_candidate_decision.json") as f:
        decision = json.load(f)

    cand_cols = [c for c in test_df.columns if c.startswith("power_pred_round73_")]
    print(f"  候选: {cand_cols}")

    # Overall
    rows = []
    for col in [bl_col] + cand_cols:
        if col not in test_df.columns:
            continue
        rows.append({
            "candidate": col,
            "city_nrmse_6_19": round(_city_nrmse(test_df, col), 4),
            "city_nrmse_10_14": round(_city_nrmse_hours(test_df, col, focus), 4),
            "site_mean_nrmse": round(_site_mean_nrmse(test_df, col), 4),
            "bias_6_19": round(_bias(test_df, col), 4),
            "bias_10_14": round(_bias_hours(test_df, col, focus), 4),
        })
    overall = pd.DataFrame(rows)
    overall.to_csv(OUT / "round73_test_overall_compare.csv", index=False, encoding="utf-8-sig")
    print(overall.to_string(index=False))

    # Hourly
    hrows = []
    for h in range(6, 20):
        d = test_df[test_df["hour"] == h]
        if len(d) == 0:
            continue
        row = {"hour": h}
        for col in [bl_col] + cand_cols:
            if col not in d.columns:
                continue
            cap = float(d.drop_duplicates("site_id")["capacity_mw"].sum())
            agg = d.groupby("time", as_index=False).agg(
                a=("power_mw", "sum"), p=(col, "sum"))
            row[col] = round(_rmse(agg["a"].values, agg["p"].values) / cap * 100, 4) if cap > 0 else float("nan")
        hrows.append(row)
    pd.DataFrame(hrows).to_csv(OUT / "round73_test_hourly_compare.csv", index=False, encoding="utf-8-sig")

    # Site
    srows = []
    site_base = {}
    for sid, sdf in test_df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        site_base[sid] = _rmse(sdf["power_mw"].values, sdf[bl_col].values) / cap * 100
    for col in [bl_col] + cand_cols:
        if col not in test_df.columns:
            continue
        for sid, sdf in test_df.groupby("site_id"):
            cap = float(sdf["capacity_mw"].iloc[0])
            if cap <= 0:
                continue
            srows.append({
                "site_id": sid, "candidate": col,
                "base_nrmse": round(site_base[sid], 4),
                "cand_nrmse": round(_rmse(sdf["power_mw"].values, sdf[col].values) / cap * 100, 4),
                "delta": round(_rmse(sdf["power_mw"].values, sdf[col].values) / cap * 100 - site_base[sid], 4),
            })
    pd.DataFrame(srows).to_csv(OUT / "round73_test_site_compare.csv", index=False, encoding="utf-8-sig")

    # Bad sites
    print("\nBad sites (>1pp):")
    for col in cand_cols:
        n, det = _bad_sites(test_df, bl_col, col)
        print(f"  {col}: {n} sites")
        for sid, delta in det[:5]:
            print(f"    {sid}: {delta:+.2f}pp")

    # Report
    bl_row = overall[overall["candidate"] == bl_col].iloc[0]
    report = f"""# Round73 回退最优版本并重构训练框架提升报告

## 一、验收标准检查

| 标准 | 状态 |
|------|------|
| 确认当前为 Round68 final | {"✓" if decision.get("baseline_col") == "power_pred_final" else "需要回退"} |
| Round70-72 已隔离 | 待执行 |
| 训练框架已重建 | ✓ |
| 秋冬回测窗口已建立 | 待执行 |
| 候选在非test回测窗口验证 | 待执行 |
| test只做最终评估 | ✓ |

## 二、Test 集对比

| 候选 | city_nrmse | Δ | site_nrmse | Δ | bias_6_19 | bias_10_14 |
|------|-----------|---|-----------|---|-----------|------------|
"""
    for _, row in overall.iterrows():
        delta = row["city_nrmse_6_19"] - bl_row["city_nrmse_6_19"]
        report += f"| {row['candidate']} | {row['city_nrmse_6_19']}% | {delta:+.3f}pp | {row['site_mean_nrmse']}% | {row['bias_6_19']}% | {row['bias_10_14']}% |\n"

    report += f"""
## 三、最终建议

**建议采用: {decision.get("adopted_col", bl_col)}**
**决策理由: {decision.get("reason", "N/A")}**
"""
    (PROJECT_ROOT / "docs" / "Round73_回退最优版本并重构训练框架提升报告.md").write_text(report, encoding="utf-8")
    print(f"\n[OK] 报告已生成")
    print("\n[OK] evaluate 完成!")


if __name__ == "__main__":
    main()
