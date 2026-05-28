"""
build_site_validity_round34.py
=============================
Round34 修复站点有效性分类，解决 Round33 的三大口径混乱：

1. 全部登记站点（来自 site_master.csv）：所有已登记站点
2. 有 test 结果站点（来自 final eval）：有 test 6-19 点预测结果的站点
3. 正常可排名站点：有 test 结果，且不是无发电/分布漂移/系统性偏差

新增 "无测试预测结果" 状态，解决 Round33 中 NaN 站点被误标为"正常评价"的问题。
"""
import os
import pickle
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
SITE_MASTER  = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "site_master.csv"
V159_PATH     = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "distributed_predictions_v159.pkl"
FINAL_EVAL33  = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "distributed_predictions_final_eval_round33.pkl"
OUT_DIR      = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
os.makedirs(OUT_DIR, exist_ok=True)

# ── 阈值常量 ────────────────────────────────────────────────────────────────
MIN_TEST_POSITIVE_ROWS = 100
MIN_TEST_ACTUAL_MWH   = 1e-6
DRIFT_MEAN_THRESHOLD   = 0.10
DRIFT_P95_THRESHOLD   = 0.20
BIAS_RATIO_LOW        = 0.80
BIAS_RATIO_HIGH       = 1.20


def derive_split(df: pd.DataFrame) -> pd.DataFrame:
    """从时间推导 split 列。"""
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
    return df


# ── Step 1: 读取全部登记站点 ──────────────────────────────────────────────
print("读取 site_master.csv（全部登记站点）...")
sm = pd.read_csv(SITE_MASTER)
all_sites = set(sm["site_id"].unique())
print(f"  全部登记站点: {len(all_sites)} 个")

# ── Step 2: 读取 v159 预测，取 test 6-19 点站点 ──────────────────────────
print("读取 v159 预测（确定有 test 结果的站点）...")
with open(V159_PATH, "rb") as f:
    df_v159 = pickle.load(f)
df_v159 = derive_split(df_v159)

df_test_all = df_v159[
    (df_v159["split"] == "test") &
    (df_v159["hour"] >= 6) & (df_v159["hour"] < 20)
]
test_sites = set(df_test_all["site_id"].unique())
no_test_sites = all_sites - test_sites
print(f"  有 test 结果站点: {len(test_sites)} 个")
print(f"  无 test 结果站点: {len(no_test_sites)} 个 → {sorted(no_test_sites)}")

# ── Step 3: 计算所有站点的有效性指标 ─────────────────────────────────────
df_tv = df_v159[
    (df_v159["split"].isin(["train", "valid"])) &
    (df_v159["hour"] >= 6) & (df_v159["hour"] < 20)
]

rows = []
for site_id in sorted(all_sites):
    row = {"site_id": site_id}

    # 元信息
    sm_row = sm[sm["site_id"] == site_id]
    row["site_name"] = sm_row["site_full_name"].iloc[0] if len(sm_row) > 0 else site_id
    row["county"] = sm_row["county"].iloc[0] if len(sm_row) > 0 else ""
    row["install_group"] = sm_row["install_group"].iloc[0] if len(sm_row) > 0 else ""
    row["capacity_mw"] = sm_row["capacity_mw"].iloc[0] if len(sm_row) > 0 else np.nan

    # 全量历史统计（不含 future）
    df_site_all = df_v159[df_v159["site_id"] == site_id]
    df_hist = df_site_all[df_site_all["split"] != "future"]
    row["full_history_rows"] = len(df_hist)
    row["full_history_positive_rows"] = int((df_hist["power_mw"] > 0).sum())
    row["full_history_zero_ratio_pct"] = (
        (df_hist["power_mw"] == 0).sum() / max(len(df_hist), 1) * 100
    )

    # 测试集 6-19 点统计
    df_s_test = df_test_all[df_test_all["site_id"] == site_id]
    row["test_rows_6_19"] = len(df_s_test)
    row["test_positive_rows_6_19"] = int((df_s_test["power_mw"] > 0).sum())
    row["test_zero_ratio_6_19_pct"] = (
        (df_s_test["power_mw"] == 0).sum() / max(len(df_s_test), 1) * 100
    )
    row["test_actual_sum_mwh"] = float(df_s_test["power_mw"].sum())
    row["test_pred_sum_mwh"] = float(df_s_test["power_pred"].sum())
    row["test_pred_actual_ratio"] = (
        float(df_s_test["power_pred"].sum() / max(df_s_test["power_mw"].sum(), 1e-9))
        if len(df_s_test) > 0 and df_s_test["power_mw"].sum() > 0 else np.nan
    )

    # 训练验证集统计
    df_s_tv = df_tv[df_tv["site_id"] == site_id]
    if len(df_s_tv) > 0:
        tv_cf = df_s_tv["power_mw"] / df_s_tv["capacity_mw"].clip(lower=1e-6)
        row["tv_cf_mean"] = float(tv_cf.mean())
        row["tv_cf_p95"] = float(tv_cf.quantile(0.95))
        row["tv_zero_ratio_pct"] = (
            (df_s_tv["power_mw"] == 0).sum() / max(len(df_s_tv), 1) * 100
        )
    else:
        row["tv_cf_mean"] = np.nan
        row["tv_cf_p95"] = np.nan
        row["tv_zero_ratio_pct"] = np.nan

    # 测试集容量因子
    if len(df_s_test) > 0:
        test_cf = df_s_test["power_mw"] / df_s_test["capacity_mw"].clip(lower=1e-6)
        row["test_cf_mean"] = float(test_cf.mean())
        row["test_cf_p95"] = float(test_cf.quantile(0.95))
    else:
        row["test_cf_mean"] = np.nan
        row["test_cf_p95"] = np.nan

    row["cf_mean_shift"] = row.get("test_cf_mean", np.nan) - row.get("tv_cf_mean", np.nan)
    row["cf_p95_shift"] = row.get("test_cf_p95", np.nan) - row.get("tv_cf_p95", np.nan)

    # 站点状态分类
    if site_id not in test_sites:
        row["site_status"] = "无测试预测结果"
        row["exclude_from_ranking"] = "是"
        row["exclude_reason"] = "final_eval 中无 test 6-19 点预测结果"
    elif (row["test_positive_rows_6_19"] < MIN_TEST_POSITIVE_ROWS or
          row["test_actual_sum_mwh"] <= MIN_TEST_ACTUAL_MWH):
        row["site_status"] = "测试期无有效发电"
        row["exclude_from_ranking"] = "是"
        row["exclude_reason"] = (
            f"test正功率样本{row['test_positive_rows_6_19']}<{MIN_TEST_POSITIVE_ROWS}"
            f"或总电量{row['test_actual_sum_mwh']:.2e}≤{MIN_TEST_ACTUAL_MWH}"
        )
    elif (abs(row["cf_mean_shift"]) >= DRIFT_MEAN_THRESHOLD or
          abs(row["cf_p95_shift"]) >= DRIFT_P95_THRESHOLD):
        row["site_status"] = "测试期分布漂移"
        row["exclude_from_ranking"] = "是"
        row["exclude_reason"] = (
            f"cf_mean漂移{row['cf_mean_shift']:.3f}>={DRIFT_MEAN_THRESHOLD}"
            f"或cf_p95漂移{row['cf_p95_shift']:.3f}>={DRIFT_P95_THRESHOLD}"
        )
    elif not np.isnan(row.get("test_pred_actual_ratio", np.nan)):
        ratio = row["test_pred_actual_ratio"]
        if ratio < BIAS_RATIO_LOW or ratio > BIAS_RATIO_HIGH:
            row["site_status"] = "系统性偏差"
            row["exclude_from_ranking"] = "是"
            row["exclude_reason"] = (
                f"pred/actual={ratio:.3f}超出[{BIAS_RATIO_LOW},{BIAS_RATIO_HIGH}]"
            )
        else:
            row["site_status"] = "正常评价"
            row["exclude_from_ranking"] = "否"
            row["exclude_reason"] = ""
    else:
        row["site_status"] = "正常评价"
        row["exclude_from_ranking"] = "否"
        row["exclude_reason"] = ""

    # NRMSE（使用 power_pred）
    if len(df_s_test) >= 10:
        actual = df_s_test["power_mw"].values
        pred   = df_s_test["power_pred"].values
        cap    = float(df_s_test["capacity_mw"].mean())
        m = np.isfinite(actual) & np.isfinite(pred)
        if m.any():
            rmse = float(np.sqrt(np.mean((actual[m] - pred[m]) ** 2)))
            row["test_nrmse_pct"] = rmse / max(cap, 1e-9) * 100
        else:
            row["test_nrmse_pct"] = np.nan
    else:
        row["test_nrmse_pct"] = np.nan

    rows.append(row)

result = pd.DataFrame(rows)
FIELD_ORDER = [
    "site_id", "site_name", "county", "install_group", "capacity_mw",
    "full_history_rows", "full_history_positive_rows", "full_history_zero_ratio_pct",
    "tv_rows_6_19", "tv_cf_mean", "tv_cf_p95", "tv_zero_ratio_pct",
    "test_rows_6_19", "test_positive_rows_6_19", "test_zero_ratio_6_19_pct",
    "test_actual_sum_mwh", "test_pred_sum_mwh",
    "test_cf_mean", "test_cf_p95", "cf_mean_shift", "cf_p95_shift",
    "test_pred_actual_ratio", "test_nrmse_pct",
    "site_status", "exclude_from_ranking", "exclude_reason",
]
existing = [f for f in FIELD_ORDER if f in result.columns]
result = result[existing].sort_values("site_id").reset_index(drop=True)

# ── Step 4: 输出站点有效性表 ───────────────────────────────────────────
OUT_CSV = OUT_DIR / "round34_site_validity.csv"
result.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
print(f"\n站点有效性表已写入: {OUT_CSV}")
print(f"总站点数: {len(result)}")

# ── Step 5: 站点数量摘要 ──────────────────────────────────────────────────
counts = result["site_status"].value_counts()
summary_rows = []
for status, cnt in counts.items():
    ex = result[result["site_status"] == status]["exclude_from_ranking"].iloc[0]
    summary_rows.append({
        "category": status,
        "count": int(cnt),
        "exclude_from_ranking": ex,
        "description": {
            "正常评价": "有 test 结果，且 pred/actual 在 [0.8, 1.2] 范围内",
            "测试期无有效发电": "test 6-19 点正功率样本不足 100 或总电量接近 0",
            "测试期分布漂移": "训练验证期与测试期容量因子分布明显差异（均值漂移≥0.10 或 P95 漂移≥0.20）",
            "系统性偏差": "test pred/actual 超出 [0.8, 1.2]，存在系统性高估或低估",
            "无测试预测结果": "final_eval 中无 test 6-19 点预测结果",
        }.get(status, ""),
    })

# 汇总行
all_reg = len(all_sites)
has_test = len(test_sites)
no_test  = len(no_test_sites)
valid_rankable = int(counts.get("正常评价", 0))
no_gen  = int(counts.get("测试期无有效发电", 0))
drift   = int(counts.get("测试期分布漂移", 0))
bias    = int(counts.get("系统性偏差", 0))

summary_rows.insert(0, {
    "category": "全部登记站点",
    "count": all_reg,
    "exclude_from_ranking": "否",
    "description": "来自 site_master.csv 的全部已登记站点",
})
summary_rows.insert(1, {
    "category": "有test结果站点",
    "count": has_test,
    "exclude_from_ranking": "—",
    "description": "final_eval 中实际有 test 6-19 点预测结果的站点",
})

summary_df = pd.DataFrame(summary_rows)
summary_out = OUT_DIR / "round34_site_count_summary.csv"
summary_df.to_csv(summary_out, index=False, encoding="utf-8-sig")
print(f"站点数量摘要已写入: {summary_out}")

print("\n站点分类统计:")
for r in summary_rows:
    print(f"  {r['category']}: {r['count']} 个")

# 自洽性验证
total_from_counts = no_gen + drift + bias + valid_rankable
if has_test != total_from_counts:
    print(f"\n[WARN] 自洽性警告：有test结果={has_test} 但 各类之和={total_from_counts}")
else:
    print(f"\n[OK] 自洽性验证通过：{has_test} = {valid_rankable}+{no_gen}+{drift}+{bias}")

print("\nStep 2 完成！")
