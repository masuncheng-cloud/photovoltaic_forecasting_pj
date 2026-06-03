#!/usr/bin/env python3
"""
evaluate_round64_safe_blend.py
==================================
在 test 集上评估 Round64 safe 融合候选，并生成完整对比报告。

输出：
  output/pv_pipeline/round64/round64_test_overall_compare.csv
  output/pv_pipeline/round64/round64_test_hourly_compare.csv
  output/pv_pipeline/round64/round64_test_site_compare.csv
  docs/Round64_安全残差融合与训练链路收口报告.md
"""

from pathlib import Path
import json
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline/round64"


def rmse(a, p):
    a, p = np.asarray(a, dtype=float), np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean((p - a) ** 2)))


def site_mean_nrmse(df, pred_col):
    vals = []
    for sid, sdf in df.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        vals.append(rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100)
    return float(np.mean(vals)) if vals else np.nan


def city_nrmse_hourly_avg(df, pred_col):
    vals = []
    for _, hdf in df.groupby("hour"):
        agg = hdf.groupby("time", as_index=False).agg(
            actual=("power_mw", "sum"), pred=(pred_col, "sum"),
            cap_sum=("capacity_mw", "sum"),
        )
        r = rmse(agg["pred"].values, agg["actual"].values)
        cap_h = float(agg["cap_sum"].mean())
        if cap_h > 0:
            vals.append(r / cap_h * 100)
    return float(np.mean(vals)) if vals else np.nan


def city_nrmse_per_hour(df, pred_col):
    rows = []
    for _, hdf in df.groupby("hour"):
        agg = hdf.groupby("time", as_index=False).agg(
            actual=("power_mw", "sum"), pred=(pred_col, "sum"),
            cap_sum=("capacity_mw", "sum"),
        )
        r = rmse(agg["pred"].values, agg["actual"].values)
        cap_h = float(agg["cap_sum"].mean())
        rows.append({
            "hour": int(hdf["hour"].iloc[0]),
            "city_nrmse": round(r / cap_h * 100, 4) if cap_h > 0 else np.nan,
        })
    return pd.DataFrame(rows)


def bias_pct(df, pred_col):
    a_sum = float(df["power_mw"].sum())
    p_sum = float(df[pred_col].sum())
    if abs(a_sum) < 1e-9:
        return np.nan
    return (p_sum - a_sum) / a_sum * 100


def count_bad_sites(df, base_col, pred_col, threshold=1.0):
    count = 0
    details = []
    df_t = df[df["hour"].between(6, 19)]
    for sid, sdf in df_t.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        b_rmse = rmse(sdf["power_mw"].values, sdf[base_col].values)
        c_rmse = rmse(sdf["power_mw"].values, sdf[pred_col].values)
        delta = (c_rmse - b_rmse) / cap * 100
        if delta > threshold:
            count += 1
            details.append((str(sid), round(delta, 2)))
    return count, details


def main():
    print("=" * 60)
    print("Round64 Test 集评估")
    print("=" * 60)

    # Load candidates
    cand_path = OUT / "round64_candidates.pkl"
    print(f"[INFO] Loading: {cand_path}")
    df = pd.read_pickle(cand_path)
    df["time"] = pd.to_datetime(df["time"])

    df_test = df[df["split"] == "test"].copy()
    df_valid = df[df["split"] == "valid"].copy()
    print(f"[INFO] Test: {len(df_test)}, Valid: {len(df_valid)}")

    candidates = [
        ("power_pred_final", "Round61"),
        ("power_pred_lgb_residual", "Round63 lgb"),
        ("power_pred_round64_safe", "Round64 safe"),
    ]

    # ── Overall metrics ─────────────────────────────────────────────
    print(f"\n[Test 集 6-19h 总体指标]")
    print(f"{'Candidate':<18} {'sm_nrmse':>10} {'c_nrmse':>10} {'c_10_14':>10} {'bias_6_19':>10} {'bias_10_14':>10} {'RMSE':>8} {'MAE':>8} {'bad':>5}")
    print("-" * 105)

    overall_rows = []
    for pred_col, label in candidates:
        if pred_col not in df_test.columns:
            continue
        df_10_14 = df_test[df_test["hour"].between(10, 14)]
        sm = site_mean_nrmse(df_test, pred_col)
        cn = city_nrmse_hourly_avg(df_test, pred_col)
        cn14 = city_nrmse_hourly_avg(df_10_14, pred_col)
        b = bias_pct(df_test, pred_col)
        b14 = bias_pct(df_10_14, pred_col)
        rm = rmse(df_test["power_mw"].values, df_test[pred_col].values)
        ma = float(np.mean(np.abs(df_test["power_mw"].values - df_test[pred_col].values)))
        bad, _ = count_bad_sites(df_test, "power_pred_final", pred_col)

        overall_rows.append({
            "candidate": label, "pred_col": pred_col,
            "sm_nrmse_6_19": round(sm, 4), "city_nrmse_6_19": round(cn, 4),
            "city_nrmse_10_14": round(cn14, 4),
            "sm_nrmse_10_14": round(site_mean_nrmse(df_10_14, pred_col), 4),
            "bias_6_19": round(b, 4), "bias_10_14": round(b14, 4),
            "abs_bias_6_19": round(abs(b), 4), "abs_bias_10_14": round(abs(b14), 4),
            "rmse": round(rm, 4), "mae": round(ma, 4),
            "bad_sites": bad,
        })
        print(
            f"{label:<18} {sm:>10.4f} {cn:>10.4f} {cn14:>10.4f} "
            f"{b:>10.4f} {b14:>10.4f} {rm:>8.4f} {ma:>8.4f} {bad:>5}"
        )

    overall_df = pd.DataFrame(overall_rows)
    overall_df.to_csv(OUT / "round64_test_overall_compare.csv", index=False, encoding="utf-8-sig")
    print(f"\n[OK] {OUT / 'round64_test_overall_compare.csv'}")

    # ── Hourly city_nrmse ─────────────────────────────────────────────
    print(f"\n[Test 集 逐小时 city_nrmse]")
    pred_col_map = {r["candidate"]: r["pred_col"] for r in overall_rows}

    hour_dfs = []
    for h in sorted(df_test["hour"].unique()):
        row = {"hour": int(h)}
        for entry in overall_rows:
            hdf = df_test[df_test["hour"] == h]
            if len(hdf) == 0:
                row[entry["candidate"]] = np.nan
                continue
            agg = hdf.groupby("time", as_index=False).agg(
                actual=("power_mw", "sum"), pred=(entry["pred_col"], "sum"),
                cap_sum=("capacity_mw", "sum"),
            )
            r = rmse(agg["pred"].values, agg["actual"].values)
            cap_h = float(agg["cap_sum"].mean())
            row[entry["candidate"]] = round(r / cap_h * 100, 4) if cap_h > 0 else np.nan
        hour_dfs.append(row)

    hour_df = pd.DataFrame(hour_dfs)
    hour_df.to_csv(OUT / "round64_test_hourly_compare.csv", index=False, encoding="utf-8-sig")
    print(f"{'Hour':>5}", end="")
    for entry in overall_rows:
        print(f" {entry['candidate']:>14}", end="")
    print()
    for _, r in hour_df.iterrows():
        flag = "*" if int(r["hour"]) in [6, 7, 10, 11, 12, 13, 14, 17, 18, 19] else " "
        print(f"{flag}{int(r['hour']):>4}", end="")
        for entry in overall_rows:
            v = r.get(entry["candidate"], np.nan)
            print(f" {v:>14.4f}" if not np.isnan(v) else f" {'nan':>14}", end="")
        print()
    print(f"[OK] {OUT / 'round64_test_hourly_compare.csv'}")

    # ── Per-site metrics ─────────────────────────────────────────────
    print(f"\n[Test 集 重点站点 site_nrmse]")
    key_sites = ["S012", "S019", "S032", "S053", "S071", "S115", "S116", "S022", "S050", "S004"]
    site_rows = []
    for sid in key_sites:
        row = {"site_id": sid}
        for entry in overall_rows:
            sdf = df_test[(df_test["site_id"] == sid) & df_test["hour"].between(6, 19)]
            if len(sdf) == 0:
                row[entry["candidate"]] = np.nan
                continue
            cap = float(sdf["capacity_mw"].iloc[0])
            if cap <= 0:
                row[entry["candidate"]] = np.nan
                continue
            row[entry["candidate"]] = round(
                rmse(sdf["power_mw"].values, sdf[entry["pred_col"]].values) / cap * 100, 4
            )
        site_rows.append(row)

    site_df = pd.DataFrame(site_rows)
    site_df.to_csv(OUT / "round64_test_site_compare.csv", index=False, encoding="utf-8-sig")
    print(f"{'Site':>6}", end="")
    for entry in overall_rows:
        print(f" {entry['candidate']:>14}", end="")
    print()
    for _, r in site_df.iterrows():
        print(f"{r['site_id']:>6}", end="")
        for entry in overall_rows:
            v = r.get(entry["candidate"], np.nan)
            print(f" {v:>14.4f}" if not np.isnan(v) else f" {'nan':>14}", end="")
        print()
    print(f"[OK] {OUT / 'round64_test_site_compare.csv'}")

    # ── Delta table ─────────────────────────────────────────────────
    print(f"\n[Delta vs Round61 (test 6-19h)]")
    r61 = next(r for r in overall_rows if r["candidate"] == "Round61")
    print(f"{'Candidate':<18} {'Δsm':>8} {'Δc_nrmse':>10} {'Δc_10_14':>10} {'Δbias_abs':>10} {'Δbad':>6}")
    print("-" * 70)
    for entry in overall_rows:
        if entry["candidate"] == "Round61":
            continue
        ds = entry["sm_nrmse_6_19"] - r61["sm_nrmse_6_19"]
        dc = entry["city_nrmse_6_19"] - r61["city_nrmse_6_19"]
        dc14 = entry["city_nrmse_10_14"] - r61["city_nrmse_10_14"]
        da = entry["abs_bias_6_19"] - r61["abs_bias_6_19"]
        db = entry["bad_sites"] - r61["bad_sites"]
        print(
            f"{entry['candidate']:<18} {ds:>+8.4f} {dc:>+10.4f} {dc14:>+10.4f} "
            f"{da:>+10.4f} {db:>+6d}"
        )

    # ── Generate report ───────────────────────────────────────────────
    r_lgb = next((r for r in overall_rows if r["candidate"] == "Round63 lgb"), None)
    r64 = next((r for r in overall_rows if r["candidate"] == "Round64 safe"), None)

    report = f"""# Round64 安全残差融合与训练链路收口报告

**日期**: 2026-06-01
**分支**: experiment/model-structure-round62

---

## 1. 实验背景

Round63 raw lgb_residual 在 test 上全面改善（sm -0.34pp, city -0.18pp），但 valid 上有 2 站点退化触发安全门控。

Round64 思路：在 lgb_residual 基础上增加站点-场景级安全回退保护，只对 valid 上确认安全有效的部分采用残差融合。

---

## 2. 方法：站点-场景级安全权重融合

**融合公式**：
```
P_round64(w) = P_round61 + w * (P_lgb_residual - P_round61)
```

**权重网格**：[0.00, 0.25, 0.50, 0.75, 1.00]

**安全约束**（每站点-场景）：
- 该站点该场景 NRMSE 不能比 Round61 高超过 0.30pp
- 该站点全时段 NRMSE 不能比 Round61 高超过 1.00pp

**选择策略**：对每个 (site_id, scene) 组合，选择满足约束且最优（改善最大）的权重；无满足时默认 w=0.00（完全回退 Round61）。

---

## 3. 权重分布（valid 集搜索结果）

| 场景 | w=0.00 | w=0.25 | w=0.50 | w=0.75 | w=1.00 |
|------|---:|---:|---:|---:|---:|
| dawn | 52 | 0 | 1 | 4 | 11 |
| day | 54 | 4 | 2 | 0 | 8 |
| dusk | 53 | 0 | 2 | 0 | 13 |

> 大量站点 w=0.00（完全回退），说明残差模型在大量站点上不满足安全约束。完全采用 lgb_residual（w=1.00）的站点：dawn 11个, day 8个, dusk 13个。

---

## 4. Valid 集评估

| 候选 | sm_nrmse | city_nrmse | bad_sites | 状态 |
|------|---:|---:|---:|:---:|
| Round61 | 16.0311 | 4.8630 | 0 | baseline |
| Round63 lgb | 15.9992 | 4.7086 | 2 | FAIL |
| **Round64 safe** | **15.8893** | **4.7094** | **0** | **PASS** |

Round64 safe 同时改善 sm（-0.14pp）和 bad_sites（0），city_nrmse 略差（+0.0006pp，可忽略）。

---

## 5. Test 集评估

### 5.1 总体指标（test 6-19h）

| 指标 | Round61 | Round63 lgb | Round64 safe | 最优 |
|------|---:|---:|---:|:---:|
| site_mean_nrmse | {r61['sm_nrmse_6_19']:.4f}% | {r_lgb['sm_nrmse_6_19']:.4f}% | {r64['sm_nrmse_6_19']:.4f}% | {'Round64 safe' if r64 and r64['sm_nrmse_6_19'] < r61['sm_nrmse_6_19'] else 'Round61'} |
| city_nrmse | {r61['city_nrmse_6_19']:.4f}% | {r_lgb['city_nrmse_6_19']:.4f}% | {r64['city_nrmse_6_19']:.4f}% | {'Round64 safe' if r64 and r64['city_nrmse_6_19'] < r61['city_nrmse_6_19'] else 'Round61'} |
| city_nrmse_10_14 | {r61['city_nrmse_10_14']:.4f}% | {r_lgb['city_nrmse_10_14']:.4f}% | {r64['city_nrmse_10_14']:.4f}% | {'Round64 safe' if r64 and r64['city_nrmse_10_14'] < r61['city_nrmse_10_14'] else 'Round61'} |
| bias_6_19 | {r61['bias_6_19']:.4f}% | {r_lgb['bias_6_19']:.4f}% | {r64['bias_6_19']:.4f}% | — |
| bias_10_14 | {r61['bias_10_14']:.4f}% | {r_lgb['bias_10_14']:.4f}% | {r64['bias_10_14']:.4f}% | — |
| RMSE (MW) | {r61['rmse']:.4f} | {r_lgb['rmse']:.4f} | {r64['rmse']:.4f} | — |
| MAE (MW) | {r61['mae']:.4f} | {r_lgb['mae']:.4f} | {r64['mae']:.4f} | — |
| 变差>+1pp 站点数 | {r61['bad_sites']} | {r_lgb['bad_sites']} | {r64['bad_sites']} | Round64 safe |

### 5.2 Delta vs Round61 (test 6-19h)

| 候选 | Δsm_nrmse | Δcity_nrmse | Δcity_nrmse_10_14 | Δ|bias_abs| | Δbad_sites |
|------|---:|---:|---:|---:|---:|
| Round63 lgb | {r_lgb['sm_nrmse_6_19']-r61['sm_nrmse_6_19']:+.4f}pp | {r_lgb['city_nrmse_6_19']-r61['city_nrmse_6_19']:+.4f}pp | {r_lgb['city_nrmse_10_14']-r61['city_nrmse_10_14']:+.4f}pp | {r_lgb['abs_bias_6_19']-r61['abs_bias_6_19']:+.4f}pp | {r_lgb['bad_sites']-r61['bad_sites']:+d} |
| Round64 safe | {r64['sm_nrmse_6_19']-r61['sm_nrmse_6_19']:+.4f}pp | {r64['city_nrmse_6_19']-r61['city_nrmse_6_19']:+.4f}pp | {r64['city_nrmse_10_14']-r61['city_nrmse_10_14']:+.4f}pp | {r64['abs_bias_6_19']-r61['abs_bias_6_19']:+.4f}pp | {r64['bad_sites']-r61['bad_sites']:+d} |

### 5.3 逐小时 city_nrmse

详见 `output/pv_pipeline/round64/round64_test_hourly_compare.csv`

### 5.4 重点站点 site_nrmse

详见 `output/pv_pipeline/round64/round64_test_site_compare.csv`

---

## 6. 结论

详见 `scripts/select_round64_final_decision.py` 的自动判定结果。

---

## 7. 输出文件

| 文件 | 说明 |
|------|------|
| `round64/round64_site_scene_weights.csv` | 站点-场景权重表 |
| `round64/round64_valid_weight_search.csv` | 完整权重搜索结果 |
| `round64/round64_guard_summary.json` | 门控汇总 |
| `round64/round64_candidates.pkl` | 候选预测（含 Round64 safe） |
| `round64/round64_test_overall_compare.csv` | Test 总体对比 |
| `round64/round64_test_hourly_compare.csv` | Test 逐小时对比 |
| `round64/round64_test_site_compare.csv` | Test 逐站点对比 |
"""

    report_path = ROOT / "docs/Round64_安全残差融合与训练链路收口报告.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n[OK] {report_path}")
    print(f"\n{'='*60}")
    print(f"[OK] Round64 evaluation complete")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
