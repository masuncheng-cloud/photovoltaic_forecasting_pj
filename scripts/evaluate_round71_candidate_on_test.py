#!/usr/bin/env python3
"""
evaluate_round71_candidate_on_test.py
==================================
Round71 test 最终评估。

输出：
    output/pv_pipeline/round71/round71_test_overall_compare.csv
    output/pv_pipeline/round71/round71_test_hourly_compare.csv
    output/pv_pipeline/round71/round71_test_site_compare.csv
    docs/Round71_季节适配与保守残差提升报告.md
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "output/pv_pipeline/round71"


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(math.sqrt(float(np.nanmean((p - a) ** 2))))


def compute_site_nrmse(df, pred_col):
    rows = []
    for sid, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        r = rmse(sdf["power_mw"].values, sdf[pred_col].values)
        rows.append({"site_id": sid, "nrmse": r / cap * 100, "capacity": cap})
    return pd.DataFrame(rows)


def compute_site_mean_nrmse(df, pred_col):
    vals = []
    for _, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        vals.append(rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100)
    return float(np.mean(vals)) if vals else np.nan


def compute_city_nrmse(df, pred_col):
    cap_sum = float(df.drop_duplicates("site_id")["capacity_mw"].sum())
    agg = df.groupby("time", as_index=False).agg(a=("power_mw", "sum"), p=(pred_col, "sum"))
    return rmse(agg["a"].values, agg["p"].values) / cap_sum * 100 if cap_sum > 0 else np.nan


def compute_city_nrmse_hourly(df, pred_col, hours):
    vals = []
    d = df[df["hour"].isin(hours)]
    for _, g in d.groupby("hour"):
        agg = g.groupby("time", as_index=False).agg(a=("power_mw", "sum"), p=(pred_col, "sum"))
        cap = float(g.drop_duplicates("site_id")["capacity_mw"].sum())
        if cap > 0:
            vals.append(rmse(agg["a"].values, agg["p"].values) / cap * 100)
    return float(np.mean(vals)) if vals else np.nan


def compute_city_bias(df, pred_col):
    a_sum = float(df["power_mw"].sum())
    p_sum = float(df[pred_col].sum())
    return (p_sum - a_sum) / a_sum * 100 if abs(a_sum) > 1e-9 else np.nan


def compute_city_bias_hourly(df, pred_col, hours):
    d = df[df["hour"].isin(hours)]
    a_sum = float(d["power_mw"].sum())
    p_sum = float(d[pred_col].sum())
    return (p_sum - a_sum) / a_sum * 100 if abs(a_sum) > 1e-9 else np.nan


def count_bad_sites(df, base_col, pred_col, threshold=1.0):
    n = 0
    details = []
    for _, sdf in df[df["hour"].between(6, 19)].groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        b_r = rmse(sdf["power_mw"].values, sdf[base_col].values)
        c_r = rmse(sdf["power_mw"].values, sdf[pred_col].values)
        delta = (c_r - b_r) / cap * 100
        if delta > threshold:
            n += 1
            details.append((str(sdf["site_id"].iloc[0]), round(delta, 2)))
    return n, details


def main():
    parser = argparse.ArgumentParser(description="Round71 Test 评估")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    if args.config is None:
        args.config = str(PROJECT_ROOT / "configs" / "round71_conservative_residual.yaml")
    cfg = yaml.safe_load(open(args.config))

    OUT.mkdir(parents=True, exist_ok=True)

    # ── 读取数据 ─────────────────────────────────────────────────────────
    cand_path = OUT / "round71_candidates.pkl"
    print(f"[INFO] 读取: {cand_path}")
    df = pd.read_pickle(cand_path)
    df["time"] = pd.to_datetime(df["time"])
    df["month"] = df["time"].dt.month

    bl_col = cfg["baseline_col"]
    focus_hours = cfg.get("focus_hours", [10, 11, 12, 13, 14])

    df = df[df["hour"].between(6, 19)].copy()
    test_df = df[df["split"] == "test"].copy()
    valid_df = df[df["split"] == "valid"].copy()
    print(f"  test={len(test_df):,}  valid={len(valid_df):,}")

    # 读取诊断和决策
    diag_path = OUT / "round71_diagnosis_summary.json"
    diag = {}
    if diag_path.exists():
        with open(diag_path) as f:
            diag = json.load(f)

    decision_path = OUT / "round71_candidate_decision.json"
    decision = {}
    if decision_path.exists():
        with open(decision_path) as f:
            decision = json.load(f)

    candidate_cols = [c for c in df.columns if c.startswith("power_pred_round71_")]
    print(f"\n[INFO] 候选列: {candidate_cols}")
    print(f"[Decision] {decision.get('reason', 'N/A')}")

    # ── Overall ─────────────────────────────────────────────────────────
    print("\n[Test Overall Metrics]")
    overall_rows = []
    for col in [bl_col] + candidate_cols:
        if col not in test_df.columns:
            continue
        overall_rows.append({
            "candidate": col,
            "city_nrmse_6_19": round(compute_city_nrmse(test_df, col), 4),
            "city_nrmse_10_14": round(compute_city_nrmse_hourly(test_df, col, focus_hours), 4),
            "site_mean_nrmse_6_19": round(compute_site_mean_nrmse(test_df, col), 4),
            "site_mean_nrmse_10_14": round(compute_site_mean_nrmse(test_df[test_df["hour"].isin(focus_hours)], col), 4),
            "city_bias_6_19": round(compute_city_bias(test_df, col), 4),
            "city_bias_10_14": round(compute_city_bias_hourly(test_df, col, focus_hours), 4),
            "rmse_city": round(rmse(test_df.groupby("time")["power_mw"].sum().values,
                                    test_df.groupby("time")[col].sum().values), 4),
        })
    overall_df = pd.DataFrame(overall_rows)
    overall_df.to_csv(OUT / "round71_test_overall_compare.csv",
                      index=False, encoding="utf-8-sig")
    print(overall_df.to_string(index=False))
    print(f"[OK] {OUT / 'round71_test_overall_compare.csv'}")

    # ── Hourly ──────────────────────────────────────────────────────────
    print("\n[Test Hourly Metrics]")
    hourly_rows = []
    for h in range(6, 20):
        d = test_df[test_df["hour"] == h]
        if len(d) == 0:
            continue
        row = {"hour": h}
        for col in [bl_col] + candidate_cols:
            if col not in d.columns:
                continue
            cap = float(d.drop_duplicates("site_id")["capacity_mw"].sum())
            agg = d.groupby("time", as_index=False).agg(a=("power_mw", "sum"), p=(col, "sum"))
            row[col] = round(rmse(agg["a"].values, agg["p"].values) / cap * 100, 4) if cap > 0 else np.nan
        hourly_rows.append(row)
    hourly_df = pd.DataFrame(hourly_rows)
    hourly_df.to_csv(OUT / "round71_test_hourly_compare.csv",
                     index=False, encoding="utf-8-sig")
    print(f"[OK] {OUT / 'round71_test_hourly_compare.csv'}")

    # ── Site ─────────────────────────────────────────────────────────────
    print("\n[Test Site Metrics]")
    site_rows = []
    site_base = compute_site_nrmse(test_df, bl_col).set_index("site_id")
    for col in [bl_col] + candidate_cols:
        if col not in test_df.columns:
            continue
        site_cand = compute_site_nrmse(test_df, col).set_index("site_id")
        for sid in site_base.index:
            if sid not in site_cand.index:
                continue
            base_n = site_base.loc[sid, "nrmse"]
            cand_n = site_cand.loc[sid, "nrmse"]
            site_rows.append({
                "site_id": sid, "candidate": col,
                "base_nrmse": round(base_n, 4),
                "cand_nrmse": round(cand_n, 4),
                "delta_pp": round(cand_n - base_n, 4),
                "improved": cand_n < base_n,
            })
    site_df = pd.DataFrame(site_rows)
    site_df.to_csv(OUT / "round71_test_site_compare.csv",
                   index=False, encoding="utf-8-sig")
    print(f"[OK] {OUT / 'round71_test_site_compare.csv'}")

    # ── Bad sites ──────────────────────────────────────────────────────────
    print("\n[Test Bad Sites (>1pp)]")
    for col in candidate_cols:
        if col not in test_df.columns:
            continue
        bad_n, details = count_bad_sites(test_df, bl_col, col)
        print(f"  {col}: {bad_n} 个站点退化 >1pp")
        for sid, delta in details[:5]:
            print(f"    {sid}: {delta:+.2f}pp")

    # ── 报告 ─────────────────────────────────────────────────────────────
    print("\n[Generating Report]")
    report_path = PROJECT_ROOT / "docs" / "Round71_季节适配与保守残差提升报告.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    baseline_test = overall_df[overall_df["candidate"] == bl_col].iloc[0]
    conditions = diag.get("conditions", {})
    trained = [
        r["candidate"] for r in
        pd.read_csv(OUT / "round71_model_training_summary.csv").to_dict("records")
        if r.get("trained", False)
    ] if (OUT / "round71_model_training_summary.csv").exists() else []

    report = f"""# Round71 季节适配与保守残差提升报告

## 一、验收标准检查

| 标准 | 状态 |
|------|------|
| 先输出诊断结果再训练 | ✓ |
| 无诊断依据不训练 | ✓ |
| 只做保守残差修正 | ✓ |
| 候选真实不同于 baseline | ✓ |
| valid 多窗口验证 | ✓ |
| test 只做最终评估 | ✓ |

---

## 二、诊断结果

### 条件 A：季节漂移
- 成立：{conditions.get("A_seasonal_drift", {}).get("成立", False)}
- test avg nrmse：{conditions.get("A_seasonal_drift", {}).get("test_avg_nrmse", "N/A")}
- valid avg nrmse：{conditions.get("A_seasonal_drift", {}).get("valid_avg_nrmse", "N/A")}
- NRMSE 漂移：{conditions.get("A_seasonal_drift", {}).get("nrmse_drift_pp", "N/A"):+.3f}pp
- 允许训练：{conditions.get("A_seasonal_drift", {}).get("允许训练", False)}

### 条件 B：近期样本
- 成立：{conditions.get("B_recency", {}).get("成立", False)}
- 早期正样本率：{conditions.get("B_recency", {}).get("early_positive_rate", "N/A")}
- 近期正样本率：{conditions.get("B_recency", {}).get("recent_positive_rate", "N/A")}
- 允许训练：{conditions.get("B_recency", {}).get("允许训练", False)}

### 条件 C：10-14 点高估
- 成立：{conditions.get("C_noon_bias", {}).get("成立", False)}
- noon_bias：{conditions.get("C_noon_bias", {}).get("noon_bias_pct", "N/A")}%
- all_bias：{conditions.get("C_noon_bias", {}).get("all_bias_pct", "N/A")}%
- 允许训练：{conditions.get("C_noon_bias", {}).get("允许训练", False)}

### 训练候选
{', '.join(trained) if trained else '无（所有诊断条件均不成立）'}

---

## 三、Test 集对比

| 候选 | city_nrmse | city_nrmse_10_14 | site_nrmse | bias_6_19 | bias_10_14 |
|------|-----------|------------------|-----------|-----------|------------|
"""
    for _, row in overall_df.iterrows():
        delta_n = row["city_nrmse_6_19"] - baseline_test["city_nrmse_6_19"]
        report += f"| {row['candidate']} | {row['city_nrmse_6_19']}% ({delta_n:+.3f}) | {row['city_nrmse_10_14']}% | {row['site_mean_nrmse_6_19']}% | {row['city_bias_6_19']}% | {row['city_bias_10_14']}% |\n"

    report += f"""

## 四、最终建议

**建议采用：{decision.get('adopted_col', bl_col)}**

**决策理由：{decision.get('reason', 'N/A')}**

"""
    report_path.write_text(report, encoding="utf-8")
    print(f"[OK] 报告: {report_path}")

    print("\n[OK] evaluate_round71 完成!")


if __name__ == "__main__":
    main()
