"""
compute_round34_metrics.py
========================
Round34 核心指标重算脚本，同时完成 Step 4、5、6：

1. 全市总出力逐小时 NRMSE（先按 time 聚合全市，再算 RMSE）
2. 站点平均逐小时 NRMSE（先按 site+hour 算 NRMSE，再对站点平均）
3. 站点级综合指标（使用 power_pred_final）
4. 典型站点表（互斥分类，无重复）

所有指标默认使用 power_pred_final。
口径：split=="test"，小时 6-19。
"""
import os
import pickle
import pandas as pd
import numpy as np
from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from pv_forecasting.core.eval_frame import resolve_prediction_column

TABLES  = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
os.makedirs(METRICS, exist_ok=True)

PRED_FULL  = TABLES / "distributed_predictions_final_round34.pkl"
VALIDITY   = METRICS / "round34_site_validity.csv"


def load_pred() -> pd.DataFrame:
    """读取 Round34 最终预测，解析 pred 列。"""
    print("读取预测文件...")
    with open(PRED_FULL, "rb") as f:
        df = pickle.load(f)
    df["time"] = pd.to_datetime(df["time"])
    df["date"] = df["time"].dt.strftime("%Y-%m-%d")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    # 选择预测列
    pred_col = resolve_prediction_column(df)
    print(f"  使用预测列: {pred_col}")
    # test 6-19
    df_eval = df[
        (df["split"] == "test") &
        (df["hour"] >= 6) & (df["hour"] < 20)
    ].copy()
    print(f"  test 6-19: {len(df_eval):,} 行, {df_eval['site_id'].nunique()} 站点")
    return df_eval, pred_col


# ── 指标计算工具 ─────────────────────────────────────────────────────────

def city_hourly_nrmse(sub_df: pd.DataFrame, pred_col: str) -> pd.DataFrame:
    """全市总出力逐小时 NRMSE：先按 time 聚合，再算 RMSE。

    公式：
      city_actual_t = sum(site_actual_t)
      city_pred_t   = sum(site_pred_t)
      city_RMSE     = sqrt(mean((city_pred_t - city_actual_t)^2))
      city_NRMSE    = city_RMSE / capacity_sum * 100
    """
    rows = []
    for h in range(6, 20):
        sub = sub_df[sub_df["hour"] == h].copy()
        if len(sub) == 0:
            continue
        # 按时间聚合
        agg = sub.groupby("time").agg(
            actual_mw=("power_mw", "sum"),
            pred_mw=(pred_col, "sum"),
        )
        actual = agg["actual_mw"].values
        pred   = agg["pred_mw"].values
        m = np.isfinite(actual) & np.isfinite(pred)
        if not m.any():
            continue
        # 全市 RMSE
        rmse = float(np.sqrt(np.mean((pred[m] - actual[m]) ** 2)))
        mae  = float(np.mean(np.abs(pred[m] - actual[m])))
        bias = float(np.mean(pred[m] - actual[m]))
        cap_sum = sub.groupby("site_id")["capacity_mw"].first().sum()
        nrmse = rmse / max(cap_sum, 1e-9) * 100
        ratio = pred.sum() / actual.sum() if actual.sum() > 0 else np.nan
        rows.append({
            "hour": h,
            "n_sites": sub["site_id"].nunique(),
            "n_timestamps": len(agg),
            "capacity_sum_MW": round(cap_sum, 2),
            "actual_sum_MWh": round(float(actual.sum()), 2),
            "pred_sum_MWh": round(float(pred.sum()), 2),
            "mae_city_MW": round(mae, 4),
            "rmse_city_MW": round(rmse, 4),
            "nrmse_city_pct": round(nrmse, 4),
            "bias_city_MW": round(bias, 4),
            "pred_actual_ratio": round(float(ratio), 4) if not np.isnan(ratio) else np.nan,
        })
    return pd.DataFrame(rows)


def site_hourly_nrmse(sub_df: pd.DataFrame, pred_col: str) -> pd.DataFrame:
    """站点逐小时 NRMSE：每个 site/hour 一个 RMSE 值。"""
    rows = []
    for (sid, h), grp in sub_df.groupby(["site_id", "hour"]):
        if len(grp) == 0:
            continue
        actual = grp["power_mw"].values
        pred   = grp[pred_col].values
        cap    = float(grp["capacity_mw"].mean())
        m = np.isfinite(actual) & np.isfinite(pred)
        if not m.any():
            continue
        rmse = float(np.sqrt(np.mean((actual[m] - pred[m]) ** 2)))
        mae  = float(np.mean(np.abs(actual[m] - pred[m])))
        bias = float(np.mean(pred[m] - actual[m]))
        nrmse = rmse / max(cap, 1e-9) * 100
        ratio = pred.sum() / actual.sum() if actual.sum() > 0 else np.nan
        rows.append({
            "site_id": sid,
            "hour": int(h),
            "n_rows": len(grp),
            "capacity_MW": round(cap, 4),
            "mae_MW": round(mae, 4),
            "rmse_MW": round(rmse, 4),
            "nrmse_pct": round(nrmse, 4),
            "bias_MW": round(bias, 4),
            "pred_actual_ratio": round(float(ratio), 4) if not np.isnan(ratio) else np.nan,
        })
    return pd.DataFrame(rows)


def site_avg_hourly_nrmse(site_hourly_df: pd.DataFrame) -> pd.DataFrame:
    """站点平均逐小时 NRMSE：对每个小时，先算每个站点 NRMSE，再对站点取平均。"""
    rows = []
    for h in range(6, 20):
        sub = site_hourly_df[site_hourly_df["hour"] == h]
        if len(sub) == 0:
            continue
        rows.append({
            "hour": h,
            "n_sites": len(sub),
            "mae_MW_avg": round(sub["mae_MW"].mean(), 4),
            "rmse_MW_avg": round(sub["rmse_MW"].mean(), 4),
            "nrmse_pct_avg": round(sub["nrmse_pct"].mean(), 4),
            "nrmse_pct_median": round(sub["nrmse_pct"].median(), 4),
            "bias_MW_avg": round(sub["bias_MW"].mean(), 4),
        })
    return pd.DataFrame(rows)


def compute_site_metrics(sub_df: pd.DataFrame, pred_col: str,
                         validity_df: pd.DataFrame) -> pd.DataFrame:
    """站点级综合指标（test 6-19）。"""
    # 转成 dict：{site_id: {col: value}}，避免 DataFrame.get() 误取列
    validity = validity_df.set_index("site_id").to_dict("index")
    rows = []
    for sid, grp in sub_df.groupby("site_id"):
        if len(grp) == 0:
            continue
        actual = grp["power_mw"].values
        pred   = grp[pred_col].values
        cap    = float(grp["capacity_mw"].mean())
        m = np.isfinite(actual) & np.isfinite(pred)
        rmse = mae = bias = np.nan
        if m.any():
            rmse = float(np.sqrt(np.mean((actual[m] - pred[m]) ** 2)))
            mae  = float(np.mean(np.abs(actual[m] - pred[m])))
            bias = float(np.mean(pred[m] - actual[m]))
        nrmse = rmse / max(cap, 1e-9) * 100
        pred_sum = float(pred.sum())
        actual_sum = float(actual.sum())
        ratio = pred_sum / actual_sum if actual_sum > 0 else np.nan
        v = validity.get(sid, {})
        rows.append({
            "site_id": sid,
            "site_name": v.get("site_name", ""),
            "county": v.get("county", ""),
            "install_group": v.get("install_group", ""),
            "capacity_MW": round(cap, 3),
            "n_rows": len(grp),
            "test_positive_rows_6_19": int((actual > 0).sum()),
            "test_zero_ratio_6_19_pct": round(
                float((actual == 0).sum() / max(len(actual), 1) * 100), 2),
            "mae_MW": round(mae, 4),
            "rmse_MW": round(rmse, 4),
            "nrmse_pct": round(nrmse, 4),
            "bias_MW": round(bias, 4),
            "pred_actual_ratio": round(float(ratio), 4) if not np.isnan(ratio) else np.nan,
            "site_status": v.get("site_status", "正常评价"),
            "exclude_from_ranking": v.get("exclude_from_ranking", "否"),
            "exclude_reason": v.get("exclude_reason", ""),
        })
    return pd.DataFrame(rows)


def build_typical_sites(site_df: pd.DataFrame) -> pd.DataFrame:
    """典型站点表（互斥分类，无重复）。优先级：最好 > 最差 > 相对正确。"""
    valid = site_df[site_df["exclude_from_ranking"] == "否"].copy()
    valid = valid[valid["nrmse_pct"].notna() & (valid["nrmse_pct"] > 0)].copy()
    valid = valid.sort_values("nrmse_pct").reset_index(drop=True)

    n_best = min(5, len(valid))
    best_sites = set(valid.iloc[:n_best]["site_id"])
    valid_remain = valid.iloc[n_best:]
    n_worst = min(5, len(valid_remain))
    worst_sites = set(valid_remain.iloc[-n_worst:]["site_id"])
    valid_remain2 = valid_remain.iloc[:-n_worst] if n_worst > 0 else valid_remain
    valid_remain2 = valid_remain2.copy()
    if len(valid_remain2) > 0:
        valid_remain2["ratio_diff"] = (valid_remain2["pred_actual_ratio"] - 1.0).abs()
        correct = valid_remain2.nsmallest(5, "ratio_diff")
        correct_sites = set(correct["site_id"])
    else:
        correct_sites = set()

    # 组装
    parts = []
    if n_best > 0:
        best_df = valid.head(n_best).copy()
        best_df["类型"] = "预测最好"
        parts.append(best_df)
    if n_worst > 0:
        worst_df = valid_remain.tail(n_worst).copy()
        worst_df["类型"] = "预测最差"
        parts.append(worst_df)
    if correct_sites:
        correct_df = valid[valid["site_id"].isin(correct_sites)].copy()
        correct_df["类型"] = "相对正确"
        parts.append(correct_df)

    if not parts:
        return pd.DataFrame()

    typical = pd.concat(parts, ignore_index=True)
    typical = typical[[
        "类型", "site_id", "site_name", "county", "capacity_MW",
        "n_rows", "test_positive_rows_6_19", "test_zero_ratio_6_19_pct",
        "mae_MW", "rmse_MW", "nrmse_pct", "pred_actual_ratio",
    ]].sort_values(["类型", "nrmse_pct"]).reset_index(drop=True)
    return typical


# ── 主流程 ──────────────────────────────────────────────────────────────
print("=" * 60)
print("Round34 指标重算")
print("=" * 60)

# 1. 加载数据
df_eval, pred_col = load_pred()
validity_df = pd.read_csv(VALIDITY)
print(f"  站点有效性表: {len(validity_df)} 个站点")

# 2. 全市逐小时 NRMSE
print("\n[2] 计算全市总出力逐小时 NRMSE...")
city_hourly = city_hourly_nrmse(df_eval, pred_col)
city_hourly.to_csv(METRICS / "round34_city_hourly_nrmse.csv", index=False, encoding="utf-8-sig")
print(f"  已保存: round34_city_hourly_nrmse.csv ({len(city_hourly)} 行)")

# 3. 站点逐小时 NRMSE
print("\n[3] 计算站点逐小时 NRMSE...")
site_hourly = site_hourly_nrmse(df_eval, pred_col)
site_hourly.to_csv(METRICS / "round34_site_hourly_nrmse.csv", index=False, encoding="utf-8-sig")
print(f"  已保存: round34_site_hourly_nrmse.csv ({len(site_hourly)} 行)")

# 4. 站点平均逐小时 NRMSE
print("\n[4] 计算站点平均逐小时 NRMSE...")
site_avg_hourly = site_avg_hourly_nrmse(site_hourly)
site_avg_hourly.to_csv(METRICS / "round34_site_avg_hourly_nrmse.csv", index=False, encoding="utf-8-sig")
print(f"  已保存: round34_site_avg_hourly_nrmse.csv ({len(site_avg_hourly)} 行)")

# 5. 站点级综合指标
print("\n[5] 计算站点级综合指标...")
site_df = compute_site_metrics(df_eval, pred_col, validity_df)
site_df = site_df.sort_values("nrmse_pct").reset_index(drop=True)
site_df.to_csv(METRICS / "round34_site_metrics.csv", index=False, encoding="utf-8-sig")
print(f"  已保存: round34_site_metrics.csv ({len(site_df)} 行)")

# 6. 典型站点
print("\n[6] 生成典型站点表...")
typical = build_typical_sites(site_df)
typical.to_csv(METRICS / "round34_typical_sites.csv", index=False, encoding="utf-8-sig")
print(f"  已保存: round34_typical_sites.csv ({len(typical)} 行)")
if len(typical) > 0:
    print("  典型站点分布:")
    for t, grp in typical.groupby("类型"):
        print(f"    {t}: {list(grp['site_id'])}")
    # 检查无重复
    dup = typical[typical.duplicated("site_id")]
    if len(dup) > 0:
        print(f"  [WARN] 站点重复: {list(dup['site_id'])}")
    else:
        print("  [OK] 无站点跨类别重复")

# 7. 异常站点分类输出
print("\n[7] 输出异常站点分类...")
invalid_sites = site_df[site_df["exclude_from_ranking"] == "是"]
for fname, subset in [
    ("round34_invalid_eval_sites.csv",
     site_df[site_df["site_status"] == "测试期无有效发电"]),
    ("round34_distribution_drift_sites.csv",
     site_df[site_df["site_status"] == "测试期分布漂移"]),
    ("round34_bias_sites.csv",
     site_df[site_df["site_status"] == "系统性偏差"]),
]:
    if len(subset) > 0:
        cols = [c for c in ["site_id","site_name","site_status","exclude_reason",
                            "nrmse_pct","mae_MW","rmse_MW","pred_actual_ratio",
                            "test_zero_ratio_6_19_pct"] if c in subset.columns]
        subset[cols].to_csv(METRICS / fname, index=False, encoding="utf-8-sig")
        print(f"  已保存: {fname} ({len(subset)} 行)")

# 8. 打印关键指标摘要
print("\n" + "=" * 60)
print("关键指标摘要")
print("=" * 60)
peak = city_hourly[city_hourly["hour"].between(10, 14)]
if len(peak) > 0:
    print(f"  全市 10-14 点 NRMSE: {peak['nrmse_city_pct'].mean():.2f}%")
print(f"  全市 6-19 点 NRMSE 范围: {city_hourly['nrmse_city_pct'].min():.2f}% ~ {city_hourly['nrmse_city_pct'].max():.2f}%")
valid_sites = site_df[site_df["exclude_from_ranking"] == "否"]
print(f"  有效站点平均 NRMSE: {valid_sites['nrmse_pct'].mean():.2f}% (中位数: {valid_sites['nrmse_pct'].median():.2f}%)")
print(f"  有效站点数: {len(valid_sites)}")
print("\nStep 4-6 完成！所有 Round34 指标文件已生成。")
