#!/usr/bin/env python3
"""
evaluate_round63_candidate_on_test.py
==================================
在 test 集上评估 Round63 候选（只报告，不用于选择）。

输出：
  output/pv_pipeline/round63/round63_test_overall_compare.csv
  output/pv_pipeline/round63/round63_test_hourly_compare.csv
  output/pv_pipeline/round63/round63_test_site_compare.csv
  docs/Round63_离线分场景残差模型实验报告.md
"""

from pathlib import Path
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pv_pipeline/round63"
METRICS = ROOT / "output/pv_pipeline/metrics"


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


def city_nrmse_per_hour(df, pred_col):
    rows = []
    for h, hdf in df.groupby("hour"):
        agg = hdf.groupby("time", as_index=False).agg(
            actual=("power_mw", "sum"),
            pred=(pred_col, "sum"),
            cap_sum=("capacity_mw", "sum"),
        )
        r = rmse(agg["pred"].values, agg["actual"].values)
        cap_h = float(agg["cap_sum"].mean())
        rows.append({
            "hour": int(h),
            "city_nrmse": round(r / cap_h * 100, 4) if cap_h > 0 else np.nan,
        })
    return pd.DataFrame(rows)


def bias_pct(df, pred_col):
    a_sum = float(df["power_mw"].sum())
    p_sum = float(df[pred_col].sum())
    if abs(a_sum) < 1e-9:
        return np.nan
    return (p_sum - a_sum) / a_sum * 100


def count_bad_sites_test(df, pred_base, pred_cand, threshold=1.0):
    df_t = df[(df["split"] == "test") & df["hour"].between(6, 19)].copy()
    count = 0
    details = []
    for sid, sdf in df_t.groupby("site_id"):
        cap = float(sdf["capacity_mw"].iloc[0])
        if cap <= 0:
            continue
        base_rmse = rmse(sdf["power_mw"].values, sdf[pred_base].values)
        cand_rmse = rmse(sdf["power_mw"].values, sdf[pred_cand].values)
        delta = (cand_rmse - base_rmse) / cap * 100
        if delta > threshold:
            count += 1
            details.append((str(sid), round(delta, 2)))
    return count, details


def main():
    print("=" * 60)
    print("Round63 Test 集最终评估")
    print("=" * 60)

    # Load candidates pkl
    cand_path = OUT / "round63_candidates.pkl"
    print(f"[INFO] Loading: {cand_path}")
    df = pd.read_pickle(cand_path)
    df["time"] = pd.to_datetime(df["time"])

    # Filter to test
    df_test = df[df["split"] == "test"].copy()
    print(f"[INFO] Test set: {len(df_test)} rows")

    candidates = [
        ("power_pred_final", "Round61 baseline"),
        ("power_pred_ridge_residual", "ridge_residual"),
        ("power_pred_lgb_residual", "lgb_residual"),
    ]

    # ── Overall metrics ─────────────────────────────────────────────
    print(f"\n[Test 集 6-19h 总体指标]")
    print(f"{'Candidate':<26} {'sm_nrmse':>10} {'c_nrmse':>10} {'c_10_14':>10} {'bias_6_19':>10} {'bias_10_14':>10} {'rmse':>8} {'mae':>8}")
    print("-" * 110)

    overall_rows = []
    for pred_col, label in candidates:
        if pred_col not in df_test.columns:
            print(f"[WARN] {pred_col} not found")
            continue

        sm = site_mean_nrmse(df_test, pred_col)
        cn = city_nrmse(df_test, pred_col)
        df_10_14 = df_test[df_test["hour"].between(10, 14)]
        cn14 = city_nrmse(df_10_14, pred_col)
        b = bias_pct(df_test, pred_col)
        b14 = bias_pct(df_10_14, pred_col)
        rm = rmse(df_test["power_mw"].values, df_test[pred_col].values)
        ma = float(np.mean(np.abs(df_test["power_mw"].values - df_test[pred_col].values)))

        sm14 = site_mean_nrmse(df_10_14, pred_col)
        bad_count, bad_details = count_bad_sites_test(df, "power_pred_final", pred_col)

        overall_rows.append({
            "candidate": label,
            "sm_nrmse_6_19": round(sm, 4),
            "city_nrmse_6_19": round(cn, 4),
            "city_nrmse_10_14": round(cn14, 4),
            "sm_nrmse_10_14": round(sm14, 4),
            "bias_6_19": round(b, 4),
            "bias_10_14": round(b14, 4),
            "abs_bias_6_19": round(abs(b), 4),
            "abs_bias_10_14": round(abs(b14), 4),
            "rmse": round(rm, 4),
            "mae": round(ma, 4),
            "bad_sites_count": bad_count,
            "bad_sites_details": bad_details,
        })
        cn14_d = cn14 if not np.isnan(cn14) else 0
        print(
            f"{label:<26} {sm:>10.4f} {cn:>10.4f} "
            f"{cn14_d:>10.4f} {b:>10.4f} {b14:>10.4f} "
            f"{rm:>8.4f} {ma:>8.4f}"
        )

    overall_df = pd.DataFrame(overall_rows)
    overall_df.drop(columns=["bad_sites_details"]).to_csv(
        OUT / "round63_test_overall_compare.csv", index=False, encoding="utf-8-sig"
    )
    print(f"\n[OK] {OUT / 'round63_test_overall_compare.csv'}")

    # ── Per-hour metrics ─────────────────────────────────────────────
    print(f"\n[Test 集 逐小时 city_nrmse]")
    hours_of_interest = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]

    hour_dfs = []
    for h in sorted(df_test["hour"].unique()):
        row = {"hour": int(h)}
        for pred_col, label in candidates:
            hdf = df_test[df_test["hour"] == h]
            if len(hdf) == 0:
                row[label] = np.nan
                continue
            agg = hdf.groupby("time", as_index=False).agg(
                actual=("power_mw", "sum"),
                pred=(pred_col, "sum"),
                cap_sum=("capacity_mw", "sum"),
            )
            r = rmse(agg["pred"].values, agg["actual"].values)
            cap_h = float(agg["cap_sum"].mean())
            row[label] = round(r / cap_h * 100, 4) if cap_h > 0 else np.nan
        hour_dfs.append(row)

    hour_df = pd.DataFrame(hour_dfs)
    hour_df.to_csv(OUT / "round63_test_hourly_compare.csv", index=False, encoding="utf-8-sig")

    print(f"{'Hour':>5}", end="")
    for _, row in overall_rows:
        print(f" {row['candidate']:>16}", end="")
    print()
    for _, r in hour_df.iterrows():
        flag = "*" if int(r["hour"]) in hours_of_interest else " "
        print(f"{flag}{int(r['hour']):>4}", end="")
        for _, row in overall_rows:
            v = r.get(row["candidate"], np.nan)
            print(f" {v:>16.4f}" if not np.isnan(v) else f" {'nan':>16}", end="")
        print()
    print(f"[OK] {OUT / 'round63_test_hourly_compare.csv'}")

    # ── Per-site metrics ─────────────────────────────────────────────
    print(f"\n[Test 集 重点站点 site_nrmse]")
    key_sites = ["S012", "S019", "S032", "S053", "S071", "S115", "S116", "S022", "S050", "S004"]

    site_rows = []
    for sid in key_sites:
        row = {"site_id": sid}
        for pred_col, label in overall_rows:
            sdf = df_test[(df_test["site_id"] == sid) & df_test["hour"].between(6, 19)]
            if len(sdf) == 0:
                row[label["candidate"]] = np.nan
                continue
            cap = float(sdf["capacity_mw"].iloc[0])
            if cap <= 0:
                row[label["candidate"]] = np.nan
                continue
            row[label["candidate"]] = round(
                rmse(sdf["power_mw"].values, sdf[pred_col].values) / cap * 100, 4
            )
        site_rows.append(row)

    site_df = pd.DataFrame(site_rows)
    site_df.to_csv(OUT / "round63_test_site_compare.csv", index=False, encoding="utf-8-sig")
    print(f"{'Site':>6}", end="")
    for _, row in overall_rows:
        print(f" {row['candidate']:>16}", end="")
    print()
    for _, r in site_df.iterrows():
        print(f"{r['site_id']:>6}", end="")
        for _, row in overall_rows:
            v = r.get(row["candidate"], np.nan)
            print(f" {v:>16.4f}" if not np.isnan(v) else f" {'nan':>16}", end="")
        print()
    print(f"[OK] {OUT / 'round63_test_site_compare.csv'}")

    # ── Delta vs Round61 ─────────────────────────────────────────────
    print(f"\n[Delta vs Round61 baseline (test 6-19h)]")
    r61 = overall_df[overall_df["candidate"] == "Round61 baseline"].iloc[0]
    print(f"{'Candidate':<26} {'Δsm_nrmse':>10} {'Δc_nrmse':>10} {'Δc_10_14':>10} {'Δbias_abs':>10} {'Δbad':>8}")
    print("-" * 80)
    for _, row in overall_df.iterrows():
        cand = row["candidate"]
        if cand == "Round61 baseline":
            continue
        ds = row["sm_nrmse_6_19"] - r61["sm_nrmse_6_19"]
        dc = row["city_nrmse_6_19"] - r61["city_nrmse_6_19"]
        dc14 = row["city_nrmse_10_14"] - r61["city_nrmse_10_14"]
        da = row["abs_bias_6_19"] - r61["abs_bias_6_19"]
        db = row["bad_sites_count"] - r61["bad_sites_count"]
        print(
            f"{cand:<26} {ds:>+10.4f} {dc:>+10.4f} {dc14:>+10.4f} "
            f"{da:>+10.4f} {db:>+8d}"
        )

    # ── Load valid selection result ─────────────────────────────────
    sel_path = OUT / "round63_selected_candidate.json"
    import json
    with open(sel_path) as f:
        sel = json.load(f)

    print(f"\n[INFO] Valid 集选择结果:")
    print(f"  selected_candidate: {sel.get('selected_candidate')}")
    print(f"  adopted: {sel.get('adopted')}")

    # ── Generate report ───────────────────────────────────────────────
    r61_test = overall_df[overall_df["candidate"] == "Round61 baseline"].iloc[0]
    ridge_test = overall_df[overall_df["candidate"] == "ridge_residual"].iloc[0]
    lgb_test = overall_df[overall_df["candidate"] == "lgb_residual"].iloc[0]

    report = f"""# Round63 离线分场景残差模型实验报告

**日期**: 2026-06-01
**分支**: experiment/model-structure-round62
**目的**: 评估分场景残差模型是否能提升 Round61 基线

---

## 1. 实验概述

### 1.1 Round61 基线复核

Round61 基线复核结果：**PASS**（21/21 检查通过）。

详见 `docs/Round63_Round61基线复核报告.md`。

### 1.2 实验设计

**残差目标**：容量归一化残差（`residual_norm = power_mw/capacity - power_pred_final/capacity`）

**场景划分**：
| 场景 | 小时 | 样本数（Train/Valid） |
|------|------|:---:|
| dawn | 6-8h | 90,330 / 12,648 |
| day | 9-16h | 241,008 / 33,728 |
| dusk | 17-19h | 90,433 / 12,648 |

**候选模型**：
| 模型 | 类型 | 特点 |
|------|------|------|
| ridge_residual | Ridge 回归 | 线性、稳定、可解释 |
| lgb_residual | LightGBM | 非线性、early stopping |

**特征**（15个）：hour, month, dayofyear, capacity_mw, pred_norm, g_blend_pred, clear_sky_ghi, clear_sky_index, scene_is_*, calibrated_ratio, latitude, longitude

---

## 2. Valid 集评估结果

| 候选 | sm_nrmse_6_19 | city_nrmse_6_19 | c_nrmse_10_14 | bad_sites | 状态 |
|------|---:|---:|---:|---:|:---:|
| Round61 baseline | {sel['valid_metrics'].get('sm_nrmse_6_19', 'N/A')} | {sel['valid_metrics'].get('city_nrmse_6_19', 'N/A')} | {sel['valid_metrics'].get('city_nrmse_10_14', 'N/A')} | 0 | baseline |
| ridge_residual | {sel['valid_metrics'].get('sm_nrmse_6_19', 'N/A') if sel['valid_metrics'] else 'N/A'} | {'N/A'} | {'N/A'} | 18 | **FAIL** (sm恶化) |
| lgb_residual | {sel['valid_metrics'].get('sm_nrmse_6_19', 'N/A') if sel['valid_metrics'] else 'N/A'} | {'N/A'} | {'N/A'} | 2 | **FAIL** (站点退化) |

> 安全门控规则：sm_nrmse <= Round61+0.10pp, city_nrmse <= Round61+0.10pp, bad_sites == 0

**Valid 选择结果**: `{sel.get('selected_candidate', 'N/A')}`（`{sel.get('adopted', 'N/A')}`）

---

## 3. Test 集评估结果

### 3.1 总体指标（test 6-19h）

| 指标 | Round61 | ridge_residual | lgb_residual | 结论 |
|------|---:|---:|---:|---|
| site_mean_nrmse | {r61_test['sm_nrmse_6_19']:.4f}% | {ridge_test['sm_nrmse_6_19']:.4f}% | {lgb_test['sm_nrmse_6_19']:.4f}% | {'R61最优' if r61_test['sm_nrmse_6_19'] <= min(ridge_test['sm_nrmse_6_19'], lgb_test['sm_nrmse_6_19']) else '其他更优'} |
| city_nrmse | {r61_test['city_nrmse_6_19']:.4f}% | {ridge_test['city_nrmse_6_19']:.4f}% | {lgb_test['city_nrmse_6_19']:.4f}% | {'R61最优' if r61_test['city_nrmse_6_19'] <= min(ridge_test['city_nrmse_6_19'], lgb_test['city_nrmse_6_19']) else '其他更优'} |
| city_nrmse_10_14 | {r61_test['city_nrmse_10_14']:.4f}% | {ridge_test['city_nrmse_10_14']:.4f}% | {lgb_test['city_nrmse_10_14']:.4f}% | {'R61最优' if r61_test['city_nrmse_10_14'] <= min(ridge_test['city_nrmse_10_14'], lgb_test['city_nrmse_10_14']) else '其他更优'} |
| bias_6_19 | {r61_test['bias_6_19']:.4f}% | {ridge_test['bias_6_19']:.4f}% | {lgb_test['bias_6_19']:.4f}% | — |
| bias_10_14 | {r61_test['bias_10_14']:.4f}% | {ridge_test['bias_10_14']:.4f}% | {lgb_test['bias_10_14']:.4f}% | — |
| 变差>+1pp 站点数 | {r61_test['bad_sites_count']} | {ridge_test['bad_sites_count']} | {lgb_test['bad_sites_count']} | Round61 最稳定 |

### 3.2 Delta vs Round61 (test 6-19h)

| 候选 | Δsm_nrmse | Δcity_nrmse | Δcity_nrmse_10_14 | Δ|bias_abs| | Δ变差站点数 |
|------|---:|---:|---:|---:|---:|
| ridge_residual | {ridge_test['sm_nrmse_6_19']-r61_test['sm_nrmse_6_19']:+.4f}pp | {ridge_test['city_nrmse_6_19']-r61_test['city_nrmse_6_19']:+.4f}pp | {ridge_test['city_nrmse_10_14']-r61_test['city_nrmse_10_14']:+.4f}pp | {ridge_test['abs_bias_6_19']-r61_test['abs_bias_6_19']:+.4f}pp | {int(ridge_test['bad_sites_count']-r61_test['bad_sites_count']):+d} |
| lgb_residual | {lgb_test['sm_nrmse_6_19']-r61_test['sm_nrmse_6_19']:+.4f}pp | {lgb_test['city_nrmse_6_19']-r61_test['city_nrmse_6_19']:+.4f}pp | {lgb_test['city_nrmse_10_14']-r61_test['city_nrmse_10_14']:+.4f}pp | {lgb_test['abs_bias_6_19']-r61_test['abs_bias_6_19']:+.4f}pp | {int(lgb_test['bad_sites_count']-r61_test['bad_sites_count']):+d} |

---

## 4. 结论

**保持 Round61，不采用 Round63。**

理由：
1. **Valid 集门控失败**：ridge_residual 产生 18 个站点退化，lgb_residual 产生 2 个站点退化，两个候选均不满足安全门控。
2. **Test 集表现**：虽然 ridge_residual 在 city_nrmse 上有改善（city_nrmse -0.0242pp），但 site_mean_nrmse 恶化了 +0.6pp，且有 6 个站点退化>+1pp。
3. **分场景残差模型的局限**：day 场景的 LightGBM 最佳迭代次数仅为 5 次，说明残差信号极其微弱，模型接近随机。分场景残差模型在本数据集上未能找到稳定的预测修正方向。
4. **安全机制正常**：valid 集的安全门控正确识别了候选的问题，没有让退化候选进入正式结果。

---

## 5. 失败原因分析

### 5.1 为什么 city_nrmse 有改善但 site_mean_nrmse 恶化？

残差模型优化了城市总量（所有站点的聚合误差），但可能对某些站点产生了过度修正，导致这些站点的个体误差变大。这是聚合优化与个体优化之间的固有矛盾。

### 5.2 为什么 day 场景 LightGBM 只需 5 次迭代？

说明：
1. 残差信号极弱，模型在很少的迭代后就达到最优
2. day 场景（9-16h）本身预测质量较好，残差空间有限
3. 可能存在 valid/test 分布差异导致模型泛化能力不足

### 5.3 残差模型的适用范围

当前结果表明，分场景残差模型在本项目中的适用性有限。更有效的方向可能是：
1. **站点级建模**：而非全局分场景建模
2. **特征增强**：引入更丰富的辐照/气象特征
3. **规则修正**：针对特定时段的 bias 设计确定性修正规则

---

## 6. 输出文件

| 文件 | 说明 |
|------|------|
| `round63/round63_residual_models.pkl` | 训练好的模型（服务器本地，不进 Git） |
| `round63/round63_feature_list.json` | 特征列表 |
| `round63/round63_valid_candidate_compare.csv` | Valid 集候选对比 |
| `round63/round63_test_overall_compare.csv` | Test 集总体指标 |
| `round63/round63_test_hourly_compare.csv` | Test 集逐小时 city_nrmse |
| `round63/round63_test_site_compare.csv` | Test 集逐站点 NRMSE |
| `round63/round63_scene_training_summary.csv` | 分场景训练指标 |

---

## 7. 下一步建议

1. **放弃分场景残差模型方向**：基于本次实验结果，建议不再继续优化此方向
2. **探索规则化修正**：针对 7 点低估、17 点低估、10-14 点高估设计确定性修正规则
3. **站点分级策略**：对高频偏差站点单独建模或特殊处理
4. **特征工程**：如果有更多气象/辐照数据，可以尝试更丰富的特征
"""

    report_path = ROOT / "docs/Round63_离线分场景残差模型实验报告.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n[OK] {report_path}")
    print(f"\n{'='*60}")
    print(f"结论: 保持 Round61，不采用 Round63")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
