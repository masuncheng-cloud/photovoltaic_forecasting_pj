"""
compute_round36_metrics.py
=======================
计算 Round36 所有评价指标，使用 power_pred_final。

指标说明：
  - 全市 NRMSE：先聚合到全市时间序列，再算 RMSE/容量
  - 站点 NRMSE：每个站点独立计算
  - 典型站点：从正常可排名站点中选最好、最差、相对正确各若干

输出（全部在 output/pv_pipeline/metrics/）：
  round36_city_hourly_nrmse.csv
  round36_site_hourly_nrmse.csv
  round36_site_avg_hourly_nrmse.csv
  round36_site_metrics.csv
  round36_typical_sites.csv
  round36_invalid_eval_sites.csv
  round36_distribution_drift_sites.csv
  round36_bias_sites.csv
"""
import os
import sys
import pickle
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

TABLES  = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
os.makedirs(METRICS, exist_ok=True)

EVAL_PATH = TABLES / "distributed_predictions_final_eval_round36.pkl"
SITE_VALIDITY_PATH = METRICS / "round36_site_validity.csv"


def nrmse(y_true, y_pred, cap):
    """容量归一化 RMSE（%）。"""
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    mse = np.mean((y_true[m] - y_pred[m]) ** 2)
    return float(np.sqrt(mse) / max(float(cap), 1e-9) * 100)


def rmse(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.sqrt(np.mean((y_true[m] - y_pred[m]) ** 2)))


def mae(y_true, y_pred):
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if not m.any():
        return np.nan
    return float(np.mean(np.abs(y_true[m] - y_pred[m])))


def main():
    print("=" * 60)
    print("Round36 指标重算")
    print("=" * 60)

    if not EVAL_PATH.exists():
        print(f"[ERROR] {EVAL_PATH} 不存在！")
        import sys; sys.exit(1)

    print(f"\n读取预测文件: {EVAL_PATH}...")
    df = pd.read_pickle(EVAL_PATH)
    df["time"] = pd.to_datetime(df["time"])
    print(f"  行数: {len(df):,}, 列: {len(df.columns)}")

    # 站点有效性
    site_validity = {}
    if SITE_VALIDITY_PATH.exists():
        sv = pd.read_csv(SITE_VALIDITY_PATH)
        site_validity = dict(zip(sv["site_id"], sv["site_status"]))
        print(f"  站点有效性表已加载: {len(sv)} 个站点")

    # 只用有效站点（有 test 结果）计算指标
    normal_sites = [s for s, st in site_validity.items()
                   if st not in ["无测试预测结果", "测试期无有效发电"]]
    df_normal = df[df["site_id"].isin(normal_sites)].copy()

    # ── [1] 全市总出力逐小时 NRMSE ──────────────────────────
    print("\n[1] 计算全市总出力逐小时 NRMSE...")
    city_hourly = []
    for (time, hour), grp in df.groupby(["time", "hour"]):
        actual_sum = grp["power_mw"].sum()
        pred_sum   = grp["power_pred_final"].sum()
        city_hourly.append({
            "time": time, "hour": hour,
            "actual_city_mw": actual_sum,
            "pred_city_mw": pred_sum,
        })
    city_df = pd.DataFrame(city_hourly)
    cap_sum = df.groupby("site_id")["capacity_mw"].first().sum()
    city_df["diff_mw"] = city_df["pred_city_mw"] - city_df["actual_city_mw"]
    city_df["rmse_city_MW"] = np.sqrt(city_df["diff_mw"] ** 2)  # 每行只有1个值，rmse=abs(diff)
    city_df["nrmse_city_pct"] = city_df["rmse_city_MW"] / cap_sum * 100
    city_df["mae_city_MW"] = np.abs(city_df["diff_mw"])
    city_df["bias_city_MW"] = city_df["diff_mw"]
    city_hourly_out = city_df[["time", "hour", "actual_city_mw", "pred_city_mw",
                                "rmse_city_MW", "mae_city_MW", "nrmse_city_pct", "bias_city_MW"]]
    city_hourly_out.to_csv(METRICS / "round36_city_hourly_nrmse.csv", index=False, encoding="utf-8-sig")
    print(f"  已保存: round36_city_hourly_nrmse.csv ({len(city_df)} 行)")

    # ── [2] 站点逐小时 NRMSE ────────────────────────────────
    print("\n[2] 计算站点逐小时 NRMSE...")
    site_hourly = []
    for (sid, hour), grp in df.groupby(["site_id", "hour"]):
        if len(grp) == 0:
            continue
        cap = grp["capacity_mw"].iloc[0]
        nr = nrmse(grp["power_mw"].values, grp["power_pred_final"].values, cap)
        rm = rmse(grp["power_mw"].values, grp["power_pred_final"].values)
        ma = mae(grp["power_mw"].values, grp["power_pred_final"].values)
        bias = (grp["power_pred_final"] - grp["power_mw"]).mean()
        site_hourly.append({
            "site_id": sid, "hour": hour,
            "nrmse_site_pct": nr, "rmse_MW": rm,
            "mae_MW": ma, "bias_MW": bias,
        })
    pd.DataFrame(site_hourly).to_csv(
        METRICS / "round36_site_hourly_nrmse.csv", index=False, encoding="utf-8-sig")
    print(f"  已保存: round36_site_hourly_nrmse.csv ({len(site_hourly)} 行)")

    # ── [5] 站点平均逐小时 NRMSE ────────────────────────────
    print("\n[3] 计算站点平均逐小时 NRMSE...")
    site_hourly_all = []
    for (sid, hour), grp in df.groupby(["site_id", "hour"]):
        if len(grp) == 0:
            continue
        cap = grp["capacity_mw"].iloc[0]
        nr = nrmse(grp["power_mw"].values, grp["power_pred_final"].values, cap)
        site_hourly_all.append({"site_id": sid, "hour": int(hour), "nrmse": nr})
    sha = pd.DataFrame(site_hourly_all)
    avg_hourly = sha.groupby("hour")["nrmse"].agg(
        nrmse_hour_avg="mean", nrmse_hour_median="median").reset_index()
    avg_hourly.to_csv(METRICS / "round36_site_avg_hourly_nrmse.csv", index=False, encoding="utf-8-sig")
    print(f"  已保存: round36_site_avg_hourly_nrmse.csv ({len(avg_hourly)} 行)")

    # ── [4] 站点级综合指标 ──────────────────────────────────
    print("\n[4] 计算站点级综合指标...")
    site_metrics = []
    for sid, grp in df.groupby("site_id"):
        cap = grp["capacity_mw"].iloc[0]
        nr = nrmse(grp["power_mw"].values, grp["power_pred_final"].values, cap)
        rm = rmse(grp["power_mw"].values, grp["power_pred_final"].values)
        ma = mae(grp["power_mw"].values, grp["power_pred_final"].values)
        bias = (grp["power_pred_final"] - grp["power_mw"]).mean()
        n = len(grp)
        status = site_validity.get(sid, "无测试预测结果")
        site_metrics.append({
            "site_id": sid, "site_status": status,
            "nrmse_pct": nr, "rmse_MW": rm,
            "mae_MW": ma, "bias_MW": bias,
            "n_samples": n, "capacity_mw": cap,
        })
    site_metrics_df = pd.DataFrame(site_metrics).sort_values("nrmse_pct")
    site_metrics_df.to_csv(METRICS / "round36_site_metrics.csv", index=False, encoding="utf-8-sig")
    print(f"  已保存: round36_site_metrics.csv ({len(site_metrics_df)} 行)")

    # ── [5] 典型站点 ────────────────────────────────────────
    print("\n[5] 生成典型站点表...")
    normal_df = site_metrics_df[site_metrics_df["site_status"] == "正常评价"]
    n_normal = len(normal_df)

    typical = []
    if n_normal >= 14:
        best5  = normal_df.head(5).assign(类型="预测最好")
        worst5 = normal_df.tail(5).assign(类型="预测最差")
        # 相对正确：选择 NRMSE 最接近中位数的正常站点
        median_nrmse = normal_df["nrmse_pct"].median()
        normal_df = normal_df.copy()
        normal_df["dist_to_median"] = abs(normal_df["nrmse_pct"] - median_nrmse)
        correct4 = normal_df.sort_values("dist_to_median").head(4).assign(类型="相对正确")
        typical = pd.concat([best5, worst5, correct4])
    elif n_normal > 0:
        # 样本不足：只用已有数据
        n_each = max(1, n_normal // 3)
        best = normal_df.head(n_each).assign(类型="预测最好")
        worst = normal_df.tail(n_each).assign(类型="预测最差")
        typical = pd.concat([best, worst])

    if len(typical) > 0:
        typical_out = typical[["site_id", "类型", "nrmse_pct", "mae_MW", "bias_MW"]]
        typical_out.to_csv(METRICS / "round36_typical_sites.csv", index=False, encoding="utf-8-sig")
        print(f"  已保存: round36_typical_sites.csv ({len(typical_out)} 行)")
        print(f"  预测最好: {list(typical_out[typical_out['类型']=='预测最好']['site_id'])}")
        print(f"  预测最差: {list(typical_out[typical_out['类型']=='预测最差']['site_id'])}")
        if "相对正确" in typical_out["类型"].values:
            print(f"  相对正确: {list(typical_out[typical_out['类型']=='相对正确']['site_id'])}")

    # ── [6] 异常站点 ────────────────────────────────────────
    print("\n[6] 输出异常站点分类...")
    invalid = site_metrics_df[site_metrics_df["site_status"] == "测试期无有效发电"]
    drift   = site_metrics_df[site_metrics_df["site_status"] == "测试期分布漂移"]
    bias    = site_metrics_df[site_metrics_df["site_status"] == "系统性偏差"]

    if len(invalid) > 0:
        invalid.to_csv(METRICS / "round36_invalid_eval_sites.csv", index=False, encoding="utf-8-sig")
        print(f"  已保存: round36_invalid_eval_sites.csv ({len(invalid)} 行)")
    if len(drift) > 0:
        drift.to_csv(METRICS / "round36_distribution_drift_sites.csv", index=False, encoding="utf-8-sig")
        print(f"  已保存: round36_distribution_drift_sites.csv ({len(drift)} 行)")
    if len(bias) > 0:
        bias.to_csv(METRICS / "round36_bias_sites.csv", index=False, encoding="utf-8-sig")
        print(f"  已保存: round36_bias_sites.csv ({len(bias)} 行)")

    # ── 关键指标摘要 ───────────────────────────────────────
    print("\n" + "=" * 60)
    print("关键指标摘要")
    print("=" * 60)
    valid_normal = site_metrics_df[site_metrics_df["site_status"] == "正常评价"]
    if len(valid_normal) > 0:
        print(f"  全市 10-14 点 NRMSE: {city_df[city_df['hour'].between(10,14)]['nrmse_city_pct'].mean():.2f}%")
        print(f"  全市 6-19 点 NRMSE 范围: {city_df['nrmse_city_pct'].min():.2f}% ~ {city_df['nrmse_city_pct'].max():.2f}%")
        print(f"  有效站点平均 NRMSE: {valid_normal['nrmse_pct'].mean():.2f}% (中位数: {valid_normal['nrmse_pct'].median():.2f}%)")
        print(f"  有效站点数: {len(valid_normal)}")

    print("\n[OK] compute_round36_metrics.py 完成！")


if __name__ == "__main__":
    main()
