"""
build_site_validity_round33.py
===============================
按 Round33 方案，对所有站点进行有效性分层诊断：

- 正常评价站点
- 测试期无有效发电站点
- 测试期分布漂移站点
- 系统性偏差站点

阈值参照 Round33 方案定义。
"""
import os
import pickle
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
PRED_CLEAN  = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "distributed_predictions_final_full_clean.pkl"
OUT_CSV     = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics" / "round33_site_validity.csv"

os.makedirs(PROJECT_ROOT / "output" / "pv_pipeline" / "metrics", exist_ok=True)

# ── 阈值常量 ────────────────────────────────────────────────────────────────
MIN_TEST_ROWS             = 1000
MIN_TEST_POSITIVE_ROWS    = 100
MAX_TEST_DAYTIME_ZERO_RATIO = 95.0
MIN_TEST_ACTUAL_MWH       = 1e-6
DRIFT_MEAN_THRESHOLD      = 0.10
DRIFT_P95_THRESHOLD       = 0.20
BIAS_RATIO_LOW            = 0.80
BIAS_RATIO_HIGH           = 1.20

print(f"读取 clean 预测文件: {PRED_CLEAN}")
with open(PRED_CLEAN, "rb") as f:
    df = pickle.load(f)

df["time"] = pd.to_datetime(df["time"])

# ── 测试集 6-19 点 ─────────────────────────────────────────────────────────
df_test = df[
    (df["split"] == "test") &
    (df["hour"] >= 6) & (df["hour"] < 20)
].copy()

# ── 训练验证集（不含 future）6-19 点 ───────────────────────────────────────
df_tv = df[
    (df["split"].isin(["train", "valid"])) &
    (df["hour"] >= 6) & (df["hour"] < 20)
].copy()

print(f"测试集样本: {len(df_test):,} | 训练验证集样本: {len(df_tv):,}")

# ── 站点元信息（从 site_master.csv 读取）─────────────────────────────────────
site_master_path = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "site_master.csv"
site_meta = pd.read_csv(site_master_path)
# 选取有用字段并重命名
site_meta = site_meta[["site_id", "site_full_name", "site_short_name", "county",
                         "install_group", "capacity_bucket", "capacity_mw"]].copy()
site_meta.columns = ["site_id", "site_full_name", "site_name", "county",
                      "install_group", "capacity_bucket", "capacity_mw"]

# ── 按站点聚合测试集统计 ────────────────────────────────────────────────────
def agg_test_stats(g: pd.DataFrame) -> dict:
    total     = len(g)
    pos       = (g["power_mw"] > 0).sum()
    zero_cnt  = (g["power_mw"] == 0).sum()
    zero_ratio = zero_cnt / total * 100 if total > 0 else 0
    actual_sum = g["power_mw"].sum()
    pred_sum   = g["power_pred"].sum()
    ratio      = pred_sum / actual_sum if actual_sum > MIN_TEST_ACTUAL_MWH else np.nan
    cf_vals    = g["power_mw"] / g["capacity_mw"].clip(lower=1e-6)
    cf_mean    = cf_vals.mean()
    cf_p95     = cf_vals.quantile(0.95)
    return pd.Series({
        "test_rows_6_19": total,
        "test_positive_rows_6_19": pos,
        "test_zero_ratio_6_19_pct": zero_ratio,
        "test_actual_sum_mwh": actual_sum,
        "test_pred_sum_mwh": pred_sum,
        "test_pred_actual_ratio": ratio,
        "test_cf_mean": cf_mean,
        "test_cf_p95": cf_p95,
    })

test_stats = df_test.groupby("site_id").apply(agg_test_stats).reset_index()

# ── 按站点聚合训练验证集统计 ───────────────────────────────────────────────
def agg_tv_stats(g: pd.DataFrame) -> dict:
    cf_vals = g["power_mw"] / g["capacity_mw"].clip(lower=1e-6)
    return pd.Series({
        "tv_rows_6_19": len(g),
        "tv_positive_rows_6_19": (g["power_mw"] > 0).sum(),
        "tv_cf_mean": cf_vals.mean(),
        "tv_cf_p95": cf_vals.quantile(0.95),
        "tv_zero_ratio_pct": (g["power_mw"] == 0).sum() / len(g) * 100 if len(g) > 0 else 0,
    })

tv_stats = df_tv.groupby("site_id").apply(agg_tv_stats).reset_index()

# ── 全量历史统计 ────────────────────────────────────────────────────────────
df_full_no_future = df[df["split"] != "future"].copy()
def agg_full_stats(g: pd.DataFrame) -> dict:
    pos = (g["power_mw"] > 0).sum()
    zero_ratio = (g["power_mw"] == 0).sum() / len(g) * 100 if len(g) > 0 else 0
    return pd.Series({
        "full_history_rows": len(g),
        "full_history_positive_rows": pos,
        "full_history_zero_ratio_pct": zero_ratio,
    })

full_stats = df_full_no_future.groupby("site_id").apply(agg_full_stats).reset_index()

# ── NRMSE（测试集，站点级）──────────────────────────────────────────────────
def calc_nrmse(g: pd.DataFrame) -> float:
    actual = g["power_mw"].values
    pred   = g["power_pred"].values
    cap    = g["capacity_mw"].values
    m = np.isfinite(actual) & np.isfinite(pred)
    if not m.any():
        return np.nan
    rmse = np.sqrt(np.mean((actual[m] - pred[m]) ** 2))
    return float(rmse / cap[m].mean() * 100)

nrmse_stats = df_test.groupby("site_id").apply(calc_nrmse).reset_index()
nrmse_stats.columns = ["site_id", "test_nrmse_pct"]

# ── 合并全部统计 ────────────────────────────────────────────────────────────
result = (
    site_meta
    .merge(test_stats,  on="site_id", how="left")
    .merge(tv_stats,    on="site_id", how="left")
    .merge(full_stats,  on="site_id", how="left")
    .merge(nrmse_stats, on="site_id", how="left")
)

# ── 计算漂移量 ─────────────────────────────────────────────────────────────
result["cf_mean_shift"] = result["test_cf_mean"] - result["tv_cf_mean"]
result["cf_p95_shift"]  = result["test_cf_p95"]  - result["tv_cf_p95"]

# ── 站点有效性分类 ─────────────────────────────────────────────────────────
def classify_site(row) -> tuple[str, bool, str]:
    pos_rows  = row.get("test_positive_rows_6_19", 0)
    actual_sum = row.get("test_actual_sum_mwh", 0)
    cf_shift  = abs(row.get("cf_mean_shift", 0))
    p95_shift = abs(row.get("cf_p95_shift", 0))
    ratio     = row.get("test_pred_actual_ratio", np.nan)

    if pos_rows < MIN_TEST_POSITIVE_ROWS or actual_sum <= MIN_TEST_ACTUAL_MWH:
        reason = f"test正功率样本{pos_rows}<{MIN_TEST_POSITIVE_ROWS}或总电量不足"
        return "测试期无有效发电", True, reason
    if cf_shift >= DRIFT_MEAN_THRESHOLD or p95_shift >= DRIFT_P95_THRESHOLD:
        reason = f"cf_mean漂移{cf_shift:.3f}>={DRIFT_MEAN_THRESHOLD}或cf_p95漂移{p95_shift:.3f}>={DRIFT_P95_THRESHOLD}"
        return "测试期分布漂移", True, reason
    if not np.isnan(ratio) and (ratio < BIAS_RATIO_LOW or ratio > BIAS_RATIO_HIGH):
        reason = f"pred/actual={ratio:.3f}超出[{BIAS_RATIO_LOW},{BIAS_RATIO_HIGH}]"
        return "系统性偏差", True, reason
    return "正常评价", False, ""

result[["site_status", "exclude_from_ranking", "exclude_reason"]] = (
    result.apply(classify_site, axis=1, result_type="expand")
)
result["exclude_from_ranking"] = result["exclude_from_ranking"].map({True: "是", False: "否"})

# ── 字段排序 ───────────────────────────────────────────────────────────────
FIELD_ORDER = [
    "site_id",
    "site_name", "county", "install_group", "capacity_bucket", "capacity_mw",
    "full_history_rows", "full_history_positive_rows", "full_history_zero_ratio_pct",
    "tv_rows_6_19", "tv_positive_rows_6_19", "tv_zero_ratio_pct",
    "tv_cf_mean", "tv_cf_p95",
    "test_rows_6_19", "test_positive_rows_6_19", "test_zero_ratio_6_19_pct",
    "test_actual_sum_mwh", "test_pred_sum_mwh",
    "test_cf_mean", "test_cf_p95", "cf_mean_shift", "cf_p95_shift",
    "test_pred_actual_ratio", "test_nrmse_pct",
    "site_status", "exclude_from_ranking", "exclude_reason",
]
existing_fields = [f for f in FIELD_ORDER if f in result.columns]
result = result[existing_fields].sort_values("site_id").reset_index(drop=True)

# ── 输出 ────────────────────────────────────────────────────────────────────
result.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
print(f"\n站点有效性表已写入: {OUT_CSV}")
print(f"总站点数: {len(result)}")

# 统计各类别
print("\n站点分类统计:")
for status, cnt in result["site_status"].value_counts().items():
    print(f"  {status}: {cnt} 个站点")

# 列出被排除的站点
excluded = result[result["exclude_from_ranking"] == "是"]
print(f"\n被排除站点数: {len(excluded)}")
if len(excluded) > 0:
    print(excluded[["site_id", "site_status", "exclude_reason", "test_nrmse_pct"]].to_string())
print("\nStep 4 完成！")
