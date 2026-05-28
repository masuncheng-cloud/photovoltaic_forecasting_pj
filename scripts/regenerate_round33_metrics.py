"""
regenerate_round33_metrics.py
============================
按 Round33 方案重新生成所有核心指标文件，并输出：
  - round33_city_hourly_nrmse.csv
  - round33_site_hourly_nrmse.csv
  - round33_site_metrics.csv
  - round33_typical_sites.csv
  - round33_invalid_eval_sites.csv
  - round33_distribution_drift_sites.csv
  - round33_bias_sites.csv
  - Round33_异常站点与分布漂移分析报告.md

口径：
  - NRMSE = RMSE / capacity_mw * 100%
  - 只使用 split=="test"，小时 6-19
  - 异常站点（测试期无有效发电、分布漂移、系统性偏差）不参与最好/最差排名
"""
import os
import pickle
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
V159_PATH    = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "distributed_predictions_v159.pkl"
VALIDITY_CSV = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics" / "round33_site_validity.csv"
OUT_DIR      = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS_DIR     = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)


def derive_split(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    TRAIN_END = pd.Timestamp("2025-07-01")
    VALID_END = pd.Timestamp("2025-09-01")
    TEST_END  = pd.Timestamp("2026-01-01")
    df["split"] = "future"
    df.loc[df["time"] < TRAIN_END, "split"] = "train"
    df.loc[(df["time"] >= TRAIN_END) & (df["time"] < VALID_END), "split"] = "valid"
    df.loc[(df["time"] >= VALID_END) & (df["time"] < TEST_END), "split"] = "test"
    df["hour"] = df["time"].dt.hour
    df["date"] = df["time"].dt.date
    return df


def nrmse_func(y_true, y_pred, cap):
    """NRMSE(%)。cap 可以是数组（站点级）或标量（城市级）。"""
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any(): return np.nan
    y_t = np.asarray(y_true)[m]
    y_p = np.asarray(y_pred)[m]
    cap_arr = np.asarray(cap)
    if cap_arr.ndim == 0:
        # 标量（城市总容量）
        cap_mean = float(cap_arr)
    else:
        cap_arr = cap_arr[m]
        cap_mean = float(cap_arr.mean()) if len(cap_arr) > 0 else 1.0
    return float(np.sqrt(np.mean((y_t - y_p) ** 2)) / max(cap_mean, 1e-9) * 100)


def mae_func(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any(): return np.nan
    return float(np.mean(np.abs(y_true[m] - y_pred[m])))


def rmse_func(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any(): return np.nan
    return float(np.sqrt(np.mean((y_true[m] - y_pred[m]) ** 2)))


def bias_func(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any(): return np.nan
    return float(np.mean(y_pred[m] - y_true[m]))


# ── 读取数据 ────────────────────────────────────────────────────────────────
print("读取 v159 预测...")
with open(V159_PATH, "rb") as f:
    df = pickle.load(f)
df = derive_split(df)

# 测试集 6-19 点
df_test = df[
    (df["split"] == "test") &
    (df["hour"] >= 6) & (df["hour"] < 20)
].copy()
print(f"测试集 6-19 行: {len(df_test):,} | 站点: {df_test['site_id'].nunique()}")

# 读取有效性表
validity = pd.read_csv(VALIDITY_CSV)
valid_sites = set(validity[validity["exclude_from_ranking"] == "否"]["site_id"].tolist())
invalid_sites = set(validity[validity["exclude_from_ranking"] == "是"]["site_id"].tolist())
bias_sites_df = validity[validity["site_status"] == "系统性偏差"]
drift_sites_df = validity[validity["site_status"] == "测试期分布漂移"]
no_gen_df = validity[validity["site_status"] == "测试期无有效发电"]

print(f"有效评价站点: {len(valid_sites)} | 无效站点: {len(invalid_sites)}")

# ── 1. 全市逐小时 NRMSE ───────────────────────────────────────────────────
print("\n生成全市逐小时 NRMSE...")
city_hourly = []
for h in range(6, 20):
    sub = df_test[df_test["hour"] == h]
    if len(sub) == 0:
        continue
    # 全部站点
    mae  = mae_func(sub["power_mw"].values, sub["power_pred"].values)
    rmse = rmse_func(sub["power_mw"].values, sub["power_pred"].values)
    bias = bias_func(sub["power_mw"].values, sub["power_pred"].values)
    cap_sum = sub.groupby("site_id")["capacity_mw"].first().sum()
    nrmse = nrmse_func(sub["power_mw"].values, sub["power_pred"].values, cap_sum)
    pred_sum = sub["power_pred"].sum()
    actual_sum = sub["power_mw"].sum()
    ratio = pred_sum / actual_sum if actual_sum > 0 else np.nan
    city_hourly.append({
        "hour": h,
        "n_sites": sub["site_id"].nunique(),
        "n_rows": len(sub),
        "mae_MW": round(mae, 4),
        "rmse_MW": round(rmse, 4),
        "nrmse_pct": round(nrmse, 4),
        "bias_MW": round(bias, 4),
        "capacity_sum_MW": round(cap_sum, 2),
        "actual_sum_MWh": round(actual_sum, 2),
        "pred_sum_MWh": round(pred_sum, 2),
        "pred_actual_ratio": round(ratio, 4) if not np.isnan(ratio) else np.nan,
        "scope": "全部站点",
    })
    # 有效站点（不含异常）
    sub_valid = sub[sub["site_id"].isin(valid_sites)]
    if len(sub_valid) > 0:
        mae_v  = mae_func(sub_valid["power_mw"].values, sub_valid["power_pred"].values)
        rmse_v = rmse_func(sub_valid["power_mw"].values, sub_valid["power_pred"].values)
        bias_v = bias_func(sub_valid["power_mw"].values, sub_valid["power_pred"].values)
        cap_sum_v = sub_valid.groupby("site_id")["capacity_mw"].first().sum()
        nrmse_v = nrmse_func(sub_valid["power_mw"].values, sub_valid["power_pred"].values, cap_sum_v)
        pred_sum_v = sub_valid["power_pred"].sum()
        actual_sum_v = sub_valid["power_mw"].sum()
        ratio_v = pred_sum_v / actual_sum_v if actual_sum_v > 0 else np.nan
        city_hourly.append({
            "hour": h,
            "n_sites": sub_valid["site_id"].nunique(),
            "n_rows": len(sub_valid),
            "mae_MW": round(mae_v, 4),
            "rmse_MW": round(rmse_v, 4),
            "nrmse_pct": round(nrmse_v, 4),
            "bias_MW": round(bias_v, 4),
            "capacity_sum_MW": round(cap_sum_v, 2),
            "actual_sum_MWh": round(actual_sum_v, 2),
            "pred_sum_MWh": round(pred_sum_v, 2),
            "pred_actual_ratio": round(ratio_v, 4) if not np.isnan(ratio_v) else np.nan,
            "scope": "有效站点",
        })

city_hourly_df = pd.DataFrame(city_hourly)
city_hourly_df.to_csv(OUT_DIR / "round33_city_hourly_nrmse.csv", index=False, encoding="utf-8-sig")
print(f"  全市逐小时 NRMSE: {len(city_hourly_df)} 行 → {OUT_DIR / 'round33_city_hourly_nrmse.csv'}")

# ── 2. 站点逐小时 NRMSE ───────────────────────────────────────────────────
print("\n生成站点逐小时 NRMSE...")
site_hourly_rows = []
for (site_id, hour), grp in df_test.groupby(["site_id", "hour"]):
    if len(grp) == 0:
        continue
    mae  = mae_func(grp["power_mw"].values, grp["power_pred"].values)
    rmse = rmse_func(grp["power_mw"].values, grp["power_pred"].values)
    cap = grp["capacity_mw"].iloc[0]
    nrmse = nrmse_func(grp["power_mw"].values, grp["power_pred"].values, cap)
    bias = bias_func(grp["power_mw"].values, grp["power_pred"].values)
    pred_sum = grp["power_pred"].sum()
    actual_sum = grp["power_mw"].sum()
    ratio = pred_sum / actual_sum if actual_sum > 0 else np.nan
    status_row = validity[validity["site_id"] == site_id]
    status_val = status_row["site_status"].values[0] if len(status_row) > 0 else "正常评价"
    site_hourly_rows.append({
        "site_id": site_id,
        "hour": int(hour),
        "n_rows": len(grp),
        "capacity_MW": cap,
        "mae_MW": round(mae, 4),
        "rmse_MW": round(rmse, 4),
        "nrmse_pct": round(nrmse, 4),
        "bias_MW": round(bias, 4),
        "pred_actual_ratio": round(ratio, 4) if not np.isnan(ratio) else np.nan,
        "exclude_from_ranking": "是" if site_id in invalid_sites else "否",
        "site_status": status_val,
    })
site_hourly_df = pd.DataFrame(site_hourly_rows)
site_hourly_df.to_csv(OUT_DIR / "round33_site_hourly_nrmse.csv", index=False, encoding="utf-8-sig")
print(f"  站点逐小时 NRMSE: {len(site_hourly_df)} 行")

# ── 3. 站点级综合指标 ──────────────────────────────────────────────────────
print("\n生成站点级综合指标...")
site_rows = []
for site_id, grp in df_test.groupby("site_id"):
    if len(grp) == 0:
        continue
    mae  = mae_func(grp["power_mw"].values, grp["power_pred"].values)
    rmse = rmse_func(grp["power_mw"].values, grp["power_pred"].values)
    cap = grp["capacity_mw"].iloc[0]
    nrmse = nrmse_func(grp["power_mw"].values, grp["power_pred"].values, cap)
    bias = bias_func(grp["power_mw"].values, grp["power_pred"].values)
    pred_sum = grp["power_pred"].sum()
    actual_sum = grp["power_mw"].sum()
    ratio = pred_sum / actual_sum if actual_sum > 0 else np.nan
    county = grp["county"].iloc[0] if "county" in grp.columns else ""
    install_group = grp["install_group"].iloc[0] if "install_group" in grp.columns else ""
    status_row = validity[validity["site_id"] == site_id]
    status = status_row["site_status"].values[0] if len(status_row) > 0 else "正常评价"
    exclude = status != "正常评价"
    test_zero_ratio = (grp["power_mw"] == 0).sum() / len(grp) * 100
    site_rows.append({
        "site_id": site_id,
        "county": county,
        "install_group": install_group,
        "capacity_MW": round(cap, 3),
        "n_rows": len(grp),
        "mae_MW": round(mae, 4),
        "rmse_MW": round(rmse, 4),
        "nrmse_pct": round(nrmse, 4),
        "bias_MW": round(bias, 4),
        "pred_actual_ratio": round(ratio, 4) if not np.isnan(ratio) else np.nan,
        "test_zero_ratio_pct": round(test_zero_ratio, 2),
        "site_status": status,
        "exclude_from_ranking": "是" if exclude else "否",
        "exclude_reason": status_row["exclude_reason"].values[0] if len(status_row) > 0 and "exclude_reason" in status_row.columns else "",
    })

site_df = pd.DataFrame(site_rows)
site_df = site_df.sort_values("nrmse_pct").reset_index(drop=True)
site_df.to_csv(OUT_DIR / "round33_site_metrics.csv", index=False, encoding="utf-8-sig")
print(f"  站点级指标: {len(site_df)} 行")

# ── 4. 典型站点表 ─────────────────────────────────────────────────────────
print("\n生成典型站点表...")
valid_sites_df = site_df[site_df["exclude_from_ranking"] == "否"].copy()
if len(valid_sites_df) >= 3:
    typical = pd.concat([
        valid_sites_df.head(3).assign(类型="预测最好"),
        valid_sites_df.tail(3).assign(类型="预测最差"),
    ])
    # 找一个 pred/actual 最接近 1 的
    valid_sites_df["ratio_diff"] = (valid_sites_df["pred_actual_ratio"] - 1).abs()
    most_correct = valid_sites_df.nsmallest(3, "ratio_diff").assign(类型="相对正确")
    typical = pd.concat([typical, most_correct[["site_id", "county", "capacity_MW", "nrmse_pct",
                                                  "mae_MW", "rmse_MW", "pred_actual_ratio", "类型"]]])
else:
    typical = valid_sites_df.copy()
    typical["类型"] = "正常"

typical = typical[["site_id", "county", "capacity_MW", "nrmse_pct", "mae_MW",
                    "rmse_MW", "pred_actual_ratio", "类型"]]
typical.to_csv(OUT_DIR / "round33_typical_sites.csv", index=False, encoding="utf-8-sig")
print(f"  典型站点: {len(typical)} 行")

# ── 5-7. 异常站点分类输出 ─────────────────────────────────────────────────
no_gen_df[["site_id", "site_status", "exclude_reason", "test_nrmse_pct",
           "test_rows_6_19", "test_positive_rows_6_19", "test_zero_ratio_6_19_pct"]].to_csv(
    OUT_DIR / "round33_invalid_eval_sites.csv", index=False, encoding="utf-8-sig"
)
print(f"  无效评价站点: {len(no_gen_df)} 行")

drift_sites_df[["site_id", "site_status", "exclude_reason",
                 "tv_cf_mean", "test_cf_mean", "cf_mean_shift",
                 "tv_cf_p95", "test_cf_p95", "cf_p95_shift",
                 "test_nrmse_pct", "test_pred_actual_ratio"]].to_csv(
    OUT_DIR / "round33_distribution_drift_sites.csv", index=False, encoding="utf-8-sig"
)
print(f"  分布漂移站点: {len(drift_sites_df)} 行")

bias_sites_df[["site_id", "site_status", "exclude_reason",
                "test_pred_actual_ratio", "test_nrmse_pct",
                "tv_cf_mean", "test_cf_mean"]].to_csv(
    OUT_DIR / "round33_bias_sites.csv", index=False, encoding="utf-8-sig"
)
print(f"  系统性偏差站点: {len(bias_sites_df)} 行")

# ── 8. 生成 Markdown 分析报告 ──────────────────────────────────────────────
print("\n生成异常站点分析报告...")

# 全市 10-14 点
peak = df_test[(df_test["hour"] >= 10) & (df_test["hour"] <= 14)]
city_nrmse_10_14 = nrmse_func(peak["power_mw"].values, peak["power_pred"].values,
                               peak.groupby("site_id")["capacity_mw"].first().sum())
site_avg_nrmse = valid_sites_df["nrmse_pct"].mean()
valid_test = df_test[df_test["site_id"].isin(valid_sites)]
overall_nrmse = nrmse_func(valid_test["power_mw"].values, valid_test["power_pred"].values,
                            valid_test.groupby("site_id")["capacity_mw"].first().sum())

doc = f"""# Round33 异常站点与分布漂移分析报告

生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}

## 当前模型效果

| 指标 | 值 |
|------|----|
| 全市 10-14 点 NRMSE | {city_nrmse_10_14:.2f}% |
| 有效站点平均 NRMSE | {site_avg_nrmse:.2f}% |
| 全市 6-19 点 NRMSE | {overall_nrmse:.2f}% |
| 有效评价站点数 | {len(valid_sites)} |
| 被排除站点数 | {len(invalid_sites)} |

## 站点分类

| 类别 | 数量 | 说明 |
|------|------|------|
| 正常评价站点 | {len(valid_sites)} | 纳入模型能力统计和排名 |
| 测试期无有效发电 | {len(no_gen_df)} | 测试期正功率样本不足或总电量为0 |
| 测试期分布漂移 | {len(drift_sites_df)} | 训练期与测试期容量因子分布明显差异 |
| 系统性偏差 | {len(bias_sites_df)} | pred/actual 明显偏离 [0.8, 1.2] |

## 系统性偏差站点详情

| 站点 | pred/actual | NRMSE | 可能原因 |
|------|-------------|-------|----------|
"""
for _, row in bias_sites_df.iterrows():
    ratio = row.get("test_pred_actual_ratio", 0)
    direction = "低估" if ratio < 1.0 else "高估"
    doc += f"| {row['site_id']} | {ratio:.3f} | {row.get('test_nrmse_pct', 0):.2f}% | {direction} |\n"

doc += """
## 测试期分布漂移站点（部分）

| 站点 | cf_mean漂移 | cf_p95漂移 | NRMSE | 建议 |
|------|-------------|------------|-------|------|
"""
for _, row in drift_sites_df.head(10).iterrows():
    doc += f"| {row['site_id']} | {row.get('cf_mean_shift', 0):+.3f} | {row.get('cf_p95_shift', 0):+.3f} | {row.get('test_nrmse_pct', 0):.2f}% | 保守校准 |\n"

doc += f"""
## 建议处理方式

1. **正常评价站点**（{len(valid_sites)} 个）：纳入排名和统计，指标有效。
2. **测试期无有效发电站点**（{len(no_gen_df)} 个）：不参与排名，单独在报告中标注。
3. **分布漂移站点**（{len(drift_sites_df)} 个）：在报告中标注"测试期分布漂移"，使用保守校准（ratio clip [0.80, 1.20]）。
4. **系统性偏差站点**（{len(bias_sites_df)} 个）：已在 Round33 中应用站点级偏差校准，报告中单独列出。

---
本报告由 Round33 方案自动生成，指标口径：test 6-19 点。
"""

with open(DOCS_DIR / "Round33_异常站点与分布漂移分析报告.md", "w", encoding="utf-8") as f:
    f.write(doc)
print(f"  报告已写入: {DOCS_DIR / 'Round33_异常站点与分布漂移分析报告.md'}")

print("\nStep 8-11 完成！所有 Round33 核心指标文件已生成。")
