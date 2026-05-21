#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
regenerate_chinese_metrics.py
=============================
基于当前 fixed pipeline 预测结果 (distributed_predictions_fixed_eval.pkl)，
重新生成所有中文命名的指标 CSV 文件。

用法：
    /home/mjj/anaconda3/bin/python regenerate_chinese_metrics.py
"""

import numpy as np
import pandas as pd
from pathlib import Path
import sys
import functools

# pandas 3.x 兼容 patch
_pd_patch_done = False
def _ensure_patch():
    global _pd_patch_done
    if _pd_patch_done:
        return
    _pd_patch_done = True
    try:
        import pandas.core.arrays.string_ as _sm
        _orig = _sm.StringDtype.__init__
        @functools.wraps(_orig)
        def _p(self, *a, **kw):
            try: _orig(self)
            except TypeError:
                object.__setattr__(self, 'dtype', None)
                object.__setattr__(self, 'storage', 'python')
        _sm.StringDtype.__init__ = _p
    except Exception:
        pass

_pd_read_pickle = pd.read_pickle
def _patched_read_pickle(*a, **kw):
    _ensure_patch()
    return _pd_read_pickle(*a, **kw)
pd.read_pickle = _patched_read_pickle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 优先读取最终预测，否则回退
PRED_PKL = TABLES_DIR / "distributed_predictions_final_eval.pkl"
if not PRED_PKL.exists():
    raise FileNotFoundError(
        f"缺少最终预测文件: {PRED_PKL}，请先运行 select_final_prediction_by_guard.py"
    )
SITE_MASTER = TABLES_DIR / "site_master.csv"

# 排除的差质量站点
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
print("Loading prediction table …")
df = pd.read_pickle(PRED_PKL)
df["time"] = pd.to_datetime(df["time"])
df["year"]  = df["time"].dt.year
df["month"] = df["time"].dt.month
df["date"]  = df["time"].dt.date
df["hour"]  = df["time"].dt.hour

# 过滤：test set（split=="test"），去除坏站点（eval pkl 已做，这里双重保险）
# eval 表：2025-09-01+，hours 6-19，53 sites，67094 rows
mask = (df["split"] == "test") & (~df["site_id"].isin(BAD_SITES))
df = df[mask].copy()
print(f"Test set: {len(df):,} rows, {df['site_id'].nunique()} sites, "
      f"{df['date'].min()} – {df['date'].max()}")

# ---------------------------------------------------------------------------
# Load site master for real names
# ---------------------------------------------------------------------------
print("Loading site master …")
sm = pd.read_csv(SITE_MASTER)
# site_id → site_short_name
sid_to_name = dict(zip(sm["site_id"], sm["site_short_name"]))
print(f"  {len(sid_to_name)} site names loaded")

# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------
def mape(y_true, y_pred):
    mask = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / y_true[mask]) * 100)

def mape_clipped(y_true, y_pred, capacity):
    mask = (y_true > 0) & np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    yt = np.asarray(y_true)[mask]
    denom = np.maximum.reduce([
        yt,
        0.05 * np.asarray(capacity)[mask],
        np.full(yt.shape, 0.01)
    ])
    return float(np.mean(np.abs(yt - np.asarray(y_pred)[mask]) / denom) * 100)

def wape(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any() or np.sum(np.abs(y_true[mask])) == 0:
        return np.nan
    return float(np.sum(np.abs(y_true[mask] - y_pred[mask])) / np.sum(np.abs(y_true[mask])) * 100)

def mae(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask])))

def rmse(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.sqrt(np.mean((y_true[mask] - y_pred[mask]) ** 2)))

def nrmse(y_true, y_pred):
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return np.nan
    return float(np.sqrt(np.mean((y_true[mask] - y_pred[mask]) ** 2)))

def city_rel_err(y_true_sum, y_pred_sum):
    if not np.isfinite(y_true_sum) or y_true_sum <= 0:
        return np.nan
    return float(np.abs(y_pred_sum - y_true_sum) / y_true_sum * 100)

# ---------------------------------------------------------------------------
# Scene labels (same as v151)
# ---------------------------------------------------------------------------
def _scene_v151(g_df):
    elev = pd.to_numeric(g_df.get("solar_elevation_deg", pd.Series(-90, index=g_df.index)),
                         errors="coerce").fillna(-90)
    g_val = pd.to_numeric(g_df.get("g_blend_pred", pd.Series(0, index=g_df.index)),
                           errors="coerce").fillna(0)
    ramp = pd.to_numeric(g_df.get("g_blend_pred_diff1", pd.Series(0, index=g_df.index)),
                          errors="coerce").abs().fillna(0)
    k = pd.to_numeric(g_df.get("g_blend_pred_kt", pd.Series(0, index=g_df.index)),
                      errors="coerce").fillna(0)
    scene = np.where(elev <= 0, "night",
              np.where((g_val < 120) | (k < 0.18), "low",
              np.where(ramp > 140, "ramp",
              np.where((g_val > 520) & (elev > 18), "clear_peak",
              "mid"))))
    return pd.Series(scene, index=g_df.index, dtype="string")

df["scene_label"] = _scene_v151(df)

# ---------------------------------------------------------------------------
# 0. 各站点零值比例 (用于标注)
# ---------------------------------------------------------------------------
print("\nComputing zero-value ratios …")
# 从 full 表（0-23h）计算零值比例
full_path = TABLES_DIR / "distributed_predictions_final_full.pkl"
if not full_path.exists():
    full_path = TABLES_DIR / "distributed_predictions_fixed_full.pkl"
    print(f"  final_full 不存在，回退到: {full_path.name}")
try:
    df_full = pd.read_pickle(full_path)
    df_full["time"] = pd.to_datetime(df_full["time"])
    df_full["hour"]  = df_full["time"].dt.hour
    # 0值比例：hour in 0-23 的 actual=0 行
    zero_ratios = {}
    for sid, grp in df_full[~df_full["site_id"].isin(BAD_SITES)].groupby("site_id"):
        n = len(grp)
        nz = (grp["power_mw"] == 0).sum()
        zero_ratios[sid] = nz / n * 100
    print(f"  Zero ratios computed from full table: {len(zero_ratios)} sites")
except Exception as e:
    print(f"  Full table not available ({e}), zero ratios = empty")
    zero_ratios = {}

# ---------------------------------------------------------------------------
# Load full table for time-series (test set, 0-23h, all sites)
# ---------------------------------------------------------------------------
print("\nLoading full prediction table for time-series …")
df_full_ts = pd.read_pickle(full_path)
df_full_ts["time"] = pd.to_datetime(df_full_ts["time"])
df_full_ts["year"]  = df_full_ts["time"].dt.year
df_full_ts["month"] = df_full_ts["time"].dt.month
df_full_ts["date"]  = df_full_ts["time"].dt.date
df_full_ts["hour"]  = df_full_ts["time"].dt.hour
# Test set, exclude bad sites
df_ts = df_full_ts[(df_full_ts["split"] == "test") & (~df_full_ts["site_id"].isin(BAD_SITES))].copy()
print(f"  Full test set: {len(df_ts):,} rows, {df_ts['site_id'].nunique()} sites, "
      f"{df_ts['date'].min()} – {df_ts['date'].max()}, hours {df_ts['hour'].min()}-{df_ts['hour'].max()}")

# ---------------------------------------------------------------------------
# 1. 城市总出力逐日平均相对误差
#    格式：日期, 实际总出力(MWh), 预测总出力(MWh), 平均相对误差(%), 最大相对误差(%), 最小相对误差(%)
# ---------------------------------------------------------------------------
print("\n[1/11] 城市总出力逐日平均相对误差 …")
rows = []
for date, g in df.groupby("date"):
    yt_sum = g["power_mw"].sum()
    yp_sum = g["power_pred"].sum()
    rel_err = city_rel_err(yt_sum, yp_sum)

    # 每小时 city_rel_err
    hourly_rels = []
    for _, hg in g.groupby("hour"):
        yt_h = hg["power_mw"].sum()
        yp_h = hg["power_pred"].sum()
        hourly_rels.append(city_rel_err(yt_h, yp_h))
    hourly_rels = [r for r in hourly_rels if np.isfinite(r)]

    rows.append({
        "日期": str(date),
        "实际总出力(MWh)": round(float(yt_sum), 2),
        "预测总出力(MWh)": round(float(yp_sum), 2),
        "平均相对误差(%)": round(rel_err, 3) if np.isfinite(rel_err) else np.nan,
        "最大相对误差(%)": round(float(max(hourly_rels)), 3) if hourly_rels else np.nan,
        "最小相对误差(%)": round(float(min(hourly_rels)), 3) if hourly_rels else np.nan,
    })

pd.DataFrame(rows).to_csv(
    OUT_DIR / "分布式光伏预测_城市总出力逐日平均相对误差.csv",
    index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / '分布式光伏预测_城市总出力逐日平均相对误差.csv'}")

# ---------------------------------------------------------------------------
# 2. 城市总出力逐日逐时相对误差
#    格式：level, site_id, date, hour, n_samples, MAPE(%), NRMSE(%), MAE, RMSE
# ---------------------------------------------------------------------------
print("[2/11] 城市总出力逐日逐时相对误差 …")
rows = []
rows.append({
    "level": "city",
    "site_id": "",
    "date": "",
    "hour": "",
    "n_samples": "",
    "MAPE(%)": "",
    "NRMSE(%)": "",
    "MAE": "",
    "RMSE": ""
})
for (date, hour), g in df.groupby(["date", "hour"]):
    yt = g["power_mw"].values.astype(float)
    yp = g["power_pred"].values.astype(float)
    rows.append({
        "level": "city",
        "site_id": "全市",
        "date": str(date),
        "hour": int(hour),
        "n_samples": len(g),
        "MAPE(%)": round(mape(yt, yp), 2),
        "NRMSE(%)": round(nrmse(yt, yp), 3),
        "MAE": round(mae(yt, yp), 4),
        "RMSE": round(rmse(yt, yp), 4),
    })
for (date, hour), g in df.groupby(["date", "hour"]):
    yt = g["power_mw"].values.astype(float)
    yp = g["power_pred"].values.astype(float)
    for sid in sorted(g["site_id"].unique()):
        sg = g[g["site_id"] == sid]
        syt = sg["power_mw"].values.astype(float)
        syp = sg["power_pred"].values.astype(float)
        rows.append({
            "level": "site",
            "site_id": sid,
            "date": str(date),
            "hour": int(hour),
            "n_samples": len(sg),
            "MAPE(%)": round(mape(syt, syp), 2),
            "NRMSE(%)": round(nrmse(syt, syp), 3),
            "MAE": round(mae(syt, syp), 4),
            "RMSE": round(rmse(syt, syp), 4),
        })

pd.DataFrame(rows).to_csv(
    OUT_DIR / "分布式光伏预测_城市总出力逐日逐时相对误差.csv",
    index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / '分布式光伏预测_城市总出力逐日逐时相对误差.csv'}")

# ---------------------------------------------------------------------------
# 3. 城市总出力逐小时统计
#    格式：hour, 实际总出力_MW_sum, 预测总出力_MW_sum, 平均相对误差_pct, 中位相对误差_pct, 样本数, 相对误差_pct
# ---------------------------------------------------------------------------
print("[3/11] 城市总出力逐小时统计 …")
rows = []
for h in range(6, 20):
    sub = df[df["hour"] == h]
    if len(sub) == 0:
        continue
    yt = sub["power_mw"].values.astype(float)
    yp = sub["power_pred"].values.astype(float)

    # 日级别 city_rel_err 的均值和中位数
    daily_rels = []
    for _, dg in sub.groupby("date"):
        yt_d = dg["power_mw"].sum()
        yp_d = dg["power_pred"].sum()
        daily_rels.append(city_rel_err(yt_d, yp_d))
    daily_rels = [r for r in daily_rels if np.isfinite(r)]

    rows.append({
        "hour": int(h),
        "实际总出力_MW_sum": round(float(np.nansum(yt)), 2),
        "预测总出力_MW_sum": round(float(np.nansum(yp)), 2),
        "平均相对误差_pct": round(np.mean(daily_rels), 3) if daily_rels else np.nan,
        "中位相对误差_pct": round(np.median(daily_rels), 3) if daily_rels else np.nan,
        "样本数": len(sub),
        "相对误差_pct": round(mape(yt, yp), 3),
    })

pd.DataFrame(rows).to_csv(
    OUT_DIR / "分布式光伏预测_城市总出力逐小时统计.csv",
    index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / '分布式光伏预测_城市总出力逐小时统计.csv'}")

# ---------------------------------------------------------------------------
# 3b. 逐小时平均相对误差_对比（V0/V1/V2 三版对比）
# ---------------------------------------------------------------------------
print("\n[3b/11] 逐小时平均相对误差_对比（V0/V1/V2）…")

# 加载 V0 和 V1
df_v0 = pd.read_pickle(TABLES_DIR / "distributed_predictions_v159.pkl")
df_v0["time"] = pd.to_datetime(df_v0["time"])
df_v0["hour"] = df_v0["time"].dt.hour
from pv_forecasting.core.evaluation import site_hour_nrmse, city_hour_nrmse
from pv_forecasting.core.split import add_standard_split
df_v0 = add_standard_split(df_v0)

df_v1_raw = pd.read_pickle(TABLES_DIR / "distributed_predictions_fixed_full.pkl")
df_v1_raw["time"] = pd.to_datetime(df_v1_raw["time"])
df_v1_raw["hour"] = df_v1_raw["time"].dt.hour

# V0: test set, eval hours
v0_test = df_v0[(df_v0["split"] == "test") & (~df_v0["site_id"].isin(BAD_SITES)) & df_v0["hour"].between(6, 19) & (df_v0["power_mw"] > 0)].copy()
# V2: distributed_predictions_fixed_full.pkl（V2 版本预测）
v2_pred_map = df_v1_raw[(df_v1_raw["split"] == "test") & df_v1_raw["hour"].between(6, 19)][["time", "site_id", "power_pred"]].rename(columns={"power_pred": "v2_pred"})
v0_test = v0_test.merge(v2_pred_map, on=["time", "site_id"], how="left")
v0_test["v2_pred"] = v0_test["v2_pred"].fillna(v0_test["power_pred"])
# Final: already in df (power_pred column from distributed_predictions_final_eval.pkl)
v2_test = df[(df["split"] == "test") & df["hour"].between(6, 19)].copy()

def city_rel_err_series(yt_sum, yp_sum):
    if not np.isfinite(yt_sum) or yt_sum <= 0:
        return np.nan
    return float(np.abs(yp_sum - yt_sum) / yt_sum * 100)

compare_rows = []
for h in range(6, 20):
    sub_v0 = v0_test[v0_test["hour"] == h]
    sub_v1 = v0_test[v0_test["hour"] == h]  # same mask
    sub_v2 = v2_test[v2_test["hour"] == h]
    if len(sub_v0) == 0:
        continue

    yt_v0 = float(sub_v0["power_mw"].sum())
    yp_v0 = float(sub_v0["power_pred"].sum())
    yp_v1 = float(sub_v0["v2_pred"].sum())
    yp_v2 = float(sub_v2["power_pred"].sum())

    compare_rows.append({
        "hour": int(h),
        "V0_city_avg_rel_err": round(city_rel_err_series(yt_v0, yp_v0), 2),
        "V2_city_avg_rel_err": round(city_rel_err_series(yt_v0, yp_v1), 2),
        "Final_city_avg_rel_err": round(city_rel_err_series(yt_v0, yp_v2), 2),
        "delta_Final_vs_V0": round(city_rel_err_series(yt_v0, yp_v2) - city_rel_err_series(yt_v0, yp_v0), 2),
        "delta_Final_vs_V2": round(city_rel_err_series(yt_v0, yp_v2) - city_rel_err_series(yt_v0, yp_v1), 2),
    })

pd.DataFrame(compare_rows).to_csv(
    OUT_DIR / "分布式光伏预测_逐小时平均相对误差_对比.csv",
    index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / '分布式光伏预测_逐小时平均相对误差_对比.csv'}")

pd.DataFrame(compare_rows).to_csv(
    OUT_DIR / "分布式光伏预测_逐小时平均相对误差_对比.csv",
    index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / '分布式光伏预测_逐小时平均相对误差_对比.csv'}")

# ---------------------------------------------------------------------------
# 4. 各站点平均相对误差统计
#    格式：站点ID, 站点名称, 平均相对误差(%), 中位相对误差(%), 样本数
# ---------------------------------------------------------------------------
print("[4/11] 各站点平均相对误差统计 …")
rows = []
for sid in sorted(df["site_id"].unique()):
    sg = df[df["site_id"] == sid]
    yt = sg["power_mw"].values.astype(float)
    yp = sg["power_pred"].values.astype(float)

    # 中位相对误差：对每一天算 city_rel_err，再取中位数
    daily_rels = []
    for _, dg in sg.groupby("date"):
        yt_d = dg["power_mw"].sum()
        yp_d = dg["power_pred"].sum()
        daily_rels.append(city_rel_err(yt_d, yp_d))
    daily_rels = [r for r in daily_rels if np.isfinite(r)]

    site_name = sid_to_name.get(sid, sid)  # 真实中文站点名
    rows.append({
        "站点ID": sid,
        "站点名称": site_name,
        "平均相对误差(%)": round(np.mean(daily_rels), 3) if daily_rels else np.nan,
        "中位相对误差(%)": round(np.median(daily_rels), 3) if daily_rels else np.nan,
        "样本数": len(sg),
    })

pd.DataFrame(rows).to_csv(
    OUT_DIR / "分布式光伏预测_各站点平均相对误差统计.csv",
    index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / '分布式光伏预测_各站点平均相对误差统计.csv'}")

# ---------------------------------------------------------------------------
# 5. 各站点相对误差统计_已标注
#    格式：站点ID, 站点名称, MAE(MW), RMSE(MW), 相对误差均值(%), 误差<1MW比例(%), 样本数, 问题标注
# ---------------------------------------------------------------------------
print("[5/11] 各站点相对误差统计_已标注 …")

# 逐站点统计
rows_stat = []
for sid in sorted(df["site_id"].unique()):
    sg = df[df["site_id"] == sid]
    yt = sg["power_mw"].values.astype(float)
    yp = sg["power_pred"].values.astype(float)
    cap = sg["capacity_mw"].iloc[0]

    mae_val = mae(yt, yp)
    rmse_val = rmse(yt, yp)
    mape_val = mape(yt, yp)

    # 误差<1MW比例
    mask = (yt > 0) & np.isfinite(yt) & np.isfinite(yp)
    lt1mw = np.sum(np.abs(yt[mask] - yp[mask]) < 1.0) / len(yt[mask]) * 100 if mask.any() else np.nan

    # 日级相对误差均值
    daily_rels = []
    for _, dg in sg.groupby("date"):
        yt_d = dg["power_mw"].sum()
        yp_d = dg["power_pred"].sum()
        daily_rels.append(city_rel_err(yt_d, yp_d))
    daily_rels = [r for r in daily_rels if np.isfinite(r)]
    rel_err_mean = np.mean(daily_rels) if daily_rels else np.nan

    rows_stat.append({
        "站点ID": sid,
        "站点名称": sid_to_name.get(sid, sid),
        "MAE(MW)": round(mae_val, 4),
        "RMSE(MW)": round(rmse_val, 4),
        "相对误差均值(%)": round(rel_err_mean, 2),
        "误差<1MW比例(%)": round(lt1mw, 1),
        "样本数": len(sg),
        "问题标注": "",  # 先填空，后面补充标注
    })

df_stat = pd.DataFrame(rows_stat)

# 标注逻辑已内联在下方循环中（避免闭包变量问题）

# 重新遍历标注
annotated_rows = []
for _, row in df_stat.iterrows():
    sid = row["站点ID"]
    mae_val = row["MAE(MW)"]
    rel_err = row["相对误差均值(%)"]
    n = row["样本数"]
    lt1mw = row["误差<1MW比例(%)"]

    issues = []
    if mae_val < 0.10:
        issues.append("✅ 最好站点(MAE<0.1MW)")
    if mae_val > 0.80 or (np.isfinite(rel_err) and rel_err > 200):
        issues.append("🔴 最差站点(MAE>0.8MW或相对误差>200%)")
    if n < 3000:
        issues.append("🟠 训练数据少(n<3000)")
    if sid in zero_ratios and zero_ratios[sid] > 50:
        issues.append(f"🔵 0值过多(零值率{zero_ratios[sid]:.0f}%)")
    if lt1mw < 60:
        issues.append(f"⚠️ 预测偏离极大(<1MW比例仅{lt1mw:.0f}%)")

    row = row.copy()
    row["问题标注"] = " | ".join(issues) if issues else "正常"
    annotated_rows.append(row)

df_stat_ann = pd.DataFrame(annotated_rows)
df_stat_ann.to_csv(
    OUT_DIR / "分布式光伏预测_各站点相对误差统计_已标注.csv",
    index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / '分布式光伏预测_各站点相对误差统计_已标注.csv'}")
print(f"  标注统计: {(df_stat_ann['问题标注'] != '正常').sum()} / {len(df_stat_ann)} 个站点有标注")

# ---------------------------------------------------------------------------
# 6. 各站点逐日逐时相对误差 (宽表格式)
# ---------------------------------------------------------------------------
print("[6/11] 各站点逐日逐时相对误差 …")

# 逐 (date, hour) × site 计算相对误差
pivot_rel = df.groupby(["date", "hour", "site_id"]).apply(
    lambda g: city_rel_err(g["power_mw"].sum(), g["power_pred"].sum()),
    include_groups=False
).unstack("site_id")
pivot_rel.columns = [f"{c}_相对误差(%)" for c in pivot_rel.columns]
pivot_rel = pivot_rel.reset_index()
pivot_rel["time"] = pd.to_datetime(pivot_rel["date"].astype(str)) + \
                    pd.to_timedelta(pivot_rel["hour"].astype(int), unit="h")
pivot_rel = pivot_rel.sort_values("time").drop(columns=["date", "hour"])
pivot_rel.to_csv(
    OUT_DIR / "分布式光伏预测_各站点逐日逐时相对误差.csv",
    index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / '分布式光伏预测_各站点逐日逐时相对误差.csv'}")
print(f"  Shape: {pivot_rel.shape}")

# ---------------------------------------------------------------------------
# 7. 各站点逐小时统计
#    格式：site_id, 站点名称, hour, 平均相对误差_pct, 中位相对误差_pct, 样本数
# ---------------------------------------------------------------------------
print("[7/11] 各站点逐小时统计 …")
rows = []
for sid in sorted(df["site_id"].unique()):
    site_name = sid_to_name.get(sid, sid)  # 真实中文站点名
    for h in range(6, 20):
        sg = df[(df["site_id"] == sid) & (df["hour"] == h)]
        if len(sg) == 0:
            continue
        yt = sg["power_mw"].values.astype(float)
        yp = sg["power_pred"].values.astype(float)

        # 日级相对误差
        daily_rels = []
        for _, dg in sg.groupby("date"):
            yt_d = dg["power_mw"].sum()
            yp_d = dg["power_pred"].sum()
            daily_rels.append(city_rel_err(yt_d, yp_d))
        daily_rels = [r for r in daily_rels if np.isfinite(r)]

        rows.append({
            "site_id": sid,
            "站点名称": site_name,
            "hour": int(h),
            "平均相对误差_pct": round(np.mean(daily_rels), 3) if daily_rels else np.nan,
            "中位相对误差_pct": round(np.median(daily_rels), 3) if daily_rels else np.nan,
            "样本数": len(sg),
        })

pd.DataFrame(rows).to_csv(
    OUT_DIR / "分布式光伏预测_各站点逐小时统计.csv",
    index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / '分布式光伏预测_各站点逐小时统计.csv'}")

# ---------------------------------------------------------------------------
# 8. 去异常站点后_逐小时NRMSE_MAPE
#    格式：level, site_id, site_short_name, county, date, hour, n_samples, NRMSE, MAPE(%)
# ---------------------------------------------------------------------------
print("[8/11] 去异常站点后_逐小时NRMSE_MAPE …")
rows = []
# 全局逐小时
for h in range(6, 20):
    sub = df[df["hour"] == h]
    if len(sub) == 0:
        continue
    yt = sub["power_mw"].values.astype(float)
    yp = sub["power_pred"].values.astype(float)
    cap = sub["capacity_mw"].iloc[0]
    rows.append({
        "level": "city_hourly",
        "site_id": "全市",
        "site_short_name": "全市",
        "county": "",
        "date": "",
        "hour": int(h),
        "n_samples": len(sub),
        "NRMSE": round(nrmse(yt, yp), 4),
        "MAPE(%)": round(mape(yt, yp), 2),
    })

# 逐站点逐小时
for sid in sorted(df["site_id"].unique()):
    sg_site = df[df["site_id"] == sid]
    county = sg_site["county"].iloc[0] if "county" in sg_site.columns else ""
    site_short_name = sid_to_name.get(sid, sid)
    for h in range(6, 20):
        sg = sg_site[sg_site["hour"] == h]
        if len(sg) == 0:
            continue
        yt = sg["power_mw"].values.astype(float)
        yp = sg["power_pred"].values.astype(float)
        rows.append({
            "level": "site_hourly",
            "site_id": sid,
            "site_short_name": site_short_name,
            "county": county,
            "date": "",
            "hour": int(h),
            "n_samples": len(sg),
            "NRMSE": round(nrmse(yt, yp), 4),
            "MAPE(%)": round(mape(yt, yp), 2),
        })

pd.DataFrame(rows).to_csv(
    OUT_DIR / "分布式光伏预测_去异常天后_逐小时NRMSE_MAPE.csv",
    index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / '分布式光伏预测_去异常天后_逐小时NRMSE_MAPE.csv'}")

# ---------------------------------------------------------------------------
# 9. 前38座_已标注（时序宽表）
# ---------------------------------------------------------------------------
print("[9/11] 分布式光伏预测_前38座_已标注 …")
# 按 site_id 排序，前38个
sites = sorted(df["site_id"].unique())
first_38 = sites[:38]
last_40  = sites[38:40] if len(sites) > 38 else []

def build_time_series_csv(site_list, out_name, df_source):
    """
    Build time-series wide CSV using df_source (test set, full 0-23h).
    Uses pivot_table for vectorized speed.
    - Rows: all (date, hour) in df_source (includes 6/18/19 with zero-power rows)
    - Columns: site_short_name_总出力值 / site_short_name_预测
    - Missing (date, hour, site) → NaN
    """
    if not site_list:
        print(f"  Skip (no sites): {out_name}")
        return

    # 站点标注映射
    site_to_issue = {}
    for _, row in df_stat_ann.iterrows():
        if row["问题标注"] != "正常":
            site_to_issue[row["站点ID"]] = row["问题标注"]

    # 只取目标站点
    df_sub = df_source[df_source["site_id"].isin(site_list)].copy()

    # 向量化 pivot：actual & pred 宽表
    pivot_actual = df_sub.pivot_table(
        index=["date", "hour"], columns="site_id", values="power_mw", aggfunc="first")
    pivot_pred = df_sub.pivot_table(
        index=["date", "hour"], columns="site_id", values="power_pred", aggfunc="first")

    # 重命名列为中文站点名
    actual_renamed = pivot_actual.rename(columns=sid_to_name).add_suffix("_总出力值")
    pred_renamed   = pivot_pred.rename(columns=sid_to_name).add_suffix("_预测")

    # 按 time 排序列
    actual_renamed = actual_renamed.reset_index().sort_values(["date", "hour"]).reset_index(drop=True)
    pred_renamed   = pred_renamed.reset_index().sort_values(["date", "hour"]).reset_index(drop=True)

    # 合并 actual + pred
    wide_df = pd.concat([actual_renamed, pred_renamed.drop(columns=["date", "hour"])], axis=1)

    # 重建 time 列（字符串格式）
    wide_df["time"] = (
        wide_df["date"].astype(str) + " " +
        wide_df["hour"].astype(int).astype(str).str.zfill(2) + ":00:00"
    )
    wide_df = wide_df.drop(columns=["date", "hour"])

    # 按 time 排序
    wide_df = wide_df.sort_values("time").reset_index(drop=True)

    # 添加问题标注列（用真实中文站点名）
    all_issues = []
    for sid in site_list:
        site_name = sid_to_name.get(sid, sid)
        iss = site_to_issue.get(sid, "正常")
        if iss != "正常":
            all_issues.append(f"{site_name}: {iss}")
    issue_summary = " | ".join(all_issues) if all_issues else "正常"
    wide_df["站点问题标注"] = issue_summary

    wide_df.to_csv(
        OUT_DIR / out_name,
        index=False, encoding="utf-8-sig")
    print(f"  Done → {OUT_DIR / out_name}")
    print(f"  Shape: {wide_df.shape}, sites: {len(site_list)}, rows: {len(wide_df)}")
    # 快速验证
    h6 = wide_df[wide_df["time"].str.contains(" 06:", na=False)]
    h18 = wide_df[wide_df["time"].str.contains(" 18:", na=False)]
    h19 = wide_df[wide_df["time"].str.contains(" 19:", na=False)]
    print(f"  验证：hour=06 行数={len(h6)}, hour=18 行数={len(h18)}, hour=19 行数={len(h19)}")

build_time_series_csv(first_38, "分布式光伏预测_前38座_已标注.csv", df_ts)
build_time_series_csv(last_40,  "分布式光伏预测_后40座_已标注.csv", df_ts)

# ---------------------------------------------------------------------------
# 10. 周报_逐小时NRMSE对比
# ---------------------------------------------------------------------------
print("[10/11] 周报_逐小时NRMSE对比 …")
df["week"] = df["time"].dt.isocalendar().week.astype(int)
df["year"] = df["time"].dt.isocalendar().year.astype(int)
df["week_label"] = df["year"].astype(str) + "-W" + df["week"].astype(str).str.zfill(2)

rows = []
for (date, hour), g in df.groupby(["date", "hour"]):
    yt = g["power_mw"].values.astype(float)
    yp = g["power_pred"].values.astype(float)
    week_lbl = g["week_label"].iloc[0]
    year_num = g["year"].iloc[0]
    week_num = g["week"].iloc[0]

    nrmse_all = nrmse(yt, yp)
    mape_all  = mape(yt, yp)

    # 去除最差3站点后
    site_maes = df[df["date"] == date].groupby("site_id").apply(
        lambda s: mae(s["power_mw"].values, s["power_pred"].values), include_groups=False
    )
    worst_3 = set(site_maes.nlargest(3).index)
    g_clean = g[~g["site_id"].isin(worst_3)]
    if len(g_clean) > 0:
        yt_c = g_clean["power_mw"].values.astype(float)
        yp_c = g_clean["power_pred"].values.astype(float)
        nrmse_clean = nrmse(yt_c, yp_c)
        mape_clean = mape(yt_c, yp_c)
    else:
        nrmse_clean = np.nan
        mape_clean = np.nan

    n_sites_all = g["site_id"].nunique()
    n_sites_clean = g_clean["site_id"].nunique() if len(g_clean) > 0 else 0
    nrmse_drop_pct = (1 - nrmse_clean / nrmse_all) * 100 if nrmse_all > 0 and np.isfinite(nrmse_clean) else np.nan

    rows.append({
        "datetime": f"{date} {int(hour):02d}:00",
        "date": str(date),
        "hour": int(hour),
        "year": int(year_num),
        "week": int(week_num),
        "week_label": week_lbl,
        "NRMSE_全部站点": round(nrmse_all, 4),
        "NRMSE_去除最差站点后": round(nrmse_clean, 4) if np.isfinite(nrmse_clean) else np.nan,
        "NRMSE_降幅(%)": round(nrmse_drop_pct, 3) if np.isfinite(nrmse_drop_pct) else np.nan,
        "MAPE(%)_全部站点": round(mape_all, 3),
        "MAPE(%)_去除最差站点后": round(mape_clean, 3) if np.isfinite(mape_clean) else np.nan,
        "n_sites_全部站点": int(n_sites_all),
        "n_sites_去除最差站点后": int(n_sites_clean),
    })

pd.DataFrame(rows).sort_values(["datetime"]).to_csv(
    OUT_DIR / "分布式光伏预测_周报_逐小时NRMSE对比.csv",
    index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / '分布式光伏预测_周报_逐小时NRMSE对比.csv'}")

# ---------------------------------------------------------------------------
# 11. 周报_按周汇总 + 周报_整体统计
# ---------------------------------------------------------------------------
print("[11/11] 周报_按周汇总 & 周报_整体统计 …")

# 周报_整体统计
yt_all = df["power_mw"].values.astype(float)
yp_all = df["power_pred"].values.astype(float)
city_actual = float(df["power_mw"].sum())
city_pred   = float(df["power_pred"].sum())
overall_rows = [{
    "统计周期": f"{df['date'].min()} 至 {df['date'].max()}",
    "样本数": len(df),
    "站点数": df["site_id"].nunique(),
    "实际总出力(MWh)": round(city_actual, 2),
    "预测总出力(MWh)": round(city_pred, 2),
    "平均相对误差(%)": round(city_rel_err(city_actual, city_pred), 3),
    "WAPE(%)": round(wape(yt_all, yp_all), 3),
    "MAPE(%)": round(mape(yt_all, yp_all), 3),
    "MAE(MW)": round(mae(yt_all, yp_all), 4),
    "RMSE(MW)": round(rmse(yt_all, yp_all), 4),
}]
pd.DataFrame(overall_rows).to_csv(
    OUT_DIR / "分布式光伏预测_周报_整体统计.csv",
    index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / '分布式光伏预测_周报_整体统计.csv'}")

# 周报_按周汇总
weekly_rows = []
for (year, week), g in df.groupby(["year", "week"]):
    yt = g["power_mw"].values.astype(float)
    yp = g["power_pred"].values.astype(float)
    yt_sum = g["power_mw"].sum()
    yp_sum = g["power_pred"].sum()
    week_lbl = g["week_label"].iloc[0]
    weekly_rows.append({
        "year": int(year),
        "week": int(week),
        "week_label": week_lbl,
        "start_date": str(g["date"].min()),
        "end_date": str(g["date"].max()),
        "n_days": g["date"].nunique(),
        "n_samples": len(g),
        "n_sites": g["site_id"].nunique(),
        "实际总出力(MWh)": round(float(yt_sum), 2),
        "预测总出力(MWh)": round(float(yp_sum), 2),
        "平均相对误差(%)": round(city_rel_err(yt_sum, yp_sum), 3),
        "WAPE(%)": round(wape(yt, yp), 3),
        "MAPE(%)": round(mape(yt, yp), 3),
        "MAE(MW)": round(mae(yt, yp), 4),
        "RMSE(MW)": round(rmse(yt, yp), 4),
    })

pd.DataFrame(weekly_rows).sort_values(["year", "week"]).to_csv(
    OUT_DIR / "分布式光伏预测_周报_按周汇总.csv",
    index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / '分布式光伏预测_周报_按周汇总.csv'}")

# ---------------------------------------------------------------------------
# 12. hourly_nrmse_compare_v2_v3.csv（统一由本脚本生成）
# ---------------------------------------------------------------------------
print("\n[12/12] hourly_nrmse_compare_v2_v3.csv（V2 vs Final）…")
from pv_forecasting.core.split import add_standard_split

# Load V2 predictions
v2_raw = pd.read_pickle(TABLES_DIR / "distributed_predictions_fixed_full.pkl")
v2_raw["time"] = pd.to_datetime(v2_raw["time"])
v2_raw["hour"] = v2_raw["time"].dt.hour
if "split" not in v2_raw.columns:
    v2_raw = add_standard_split(v2_raw)

# V2 eval subset
v2_eval = v2_raw[(v2_raw["split"] == "test") &
                  (~v2_raw["site_id"].isin(BAD_SITES)) &
                  v2_raw["hour"].between(6, 19)].copy()

# Final eval (already loaded and filtered as 'df' above)
final_eval = df.copy()

# Build V2 map for merge (drop duplicates: keep first)
v2_map = v2_eval[["time", "site_id", "power_pred"]].rename(columns={"power_pred": "pred_v2"}).drop_duplicates(subset=["time", "site_id"])
final_eval = final_eval.drop(columns=["pred_v2"], errors="ignore")
final_eval = final_eval.merge(v2_map, on=["time", "site_id"], how="left")
final_eval["pred_v2"] = final_eval["pred_v2"].fillna(final_eval["power_pred"])

cmp_rows = []
for h in range(6, 20):
    sub_v2 = v2_eval[v2_eval["hour"] == h]
    sub_fin = final_eval[final_eval["hour"] == h]

    yt_v2 = sub_v2["power_mw"].values.astype(float)
    yp_v2 = sub_v2["power_pred"].values.astype(float)
    site_vals_v2 = []
    for _, sg in sub_v2.groupby("site_id"):
        nr = site_hour_nrmse(sg["power_mw"].values, sg["power_pred"].values, sg["capacity_mw"].values)
        if np.isfinite(nr): site_vals_v2.append(nr)
    cn_v2 = city_hour_nrmse(sub_v2, "power_pred")
    v2_site_mean = float(np.nanmean(site_vals_v2)) if site_vals_v2 else 100.0
    v2_city = float(cn_v2) if np.isfinite(cn_v2) else 100.0
    v2_score = 0.7 * v2_site_mean + 0.3 * v2_city

    yt_fin = sub_fin["power_mw"].values.astype(float)
    yp_fin = sub_fin["power_pred"].values.astype(float)
    site_vals_fin = []
    for _, sg in sub_fin.groupby("site_id"):
        nr = site_hour_nrmse(sg["power_mw"].values, sg["power_pred"].values, sg["capacity_mw"].values)
        if np.isfinite(nr): site_vals_fin.append(nr)
    cn_fin = city_hour_nrmse(sub_fin, "power_pred")
    fin_site_mean = float(np.nanmean(site_vals_fin)) if site_vals_fin else 100.0
    fin_city = float(cn_fin) if np.isfinite(cn_fin) else 100.0
    fin_score = 0.7 * fin_site_mean + 0.3 * fin_city

    cmp_rows.append({
        "hour": int(h),
        "rows": len(sub_fin),
        "V2_site_nrmse_mean_pct": round(v2_site_mean, 2),
        "final_site_nrmse_mean_pct": round(fin_site_mean, 2),
        "V2_city_nrmse_pct": round(v2_city, 3),
        "final_city_nrmse_pct": round(fin_city, 3),
        "V2_nrmse_score": round(v2_score, 4),
        "final_nrmse_score": round(fin_score, 4),
        "V3_nrmse_score": round(fin_score, 4),
    })

cmp_df = pd.DataFrame(cmp_rows).sort_values("hour").reset_index(drop=True)
cmp_df.to_csv(OUT_DIR / "hourly_nrmse_compare_v2_v3.csv", index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / 'hourly_nrmse_compare_v2_v3.csv'}")

cmp_df[["hour", "rows",
        "final_site_nrmse_mean_pct",
        "final_city_nrmse_pct"]].to_csv(
    OUT_DIR / "分布式光伏预测_逐小时NRMSE_对比.csv", index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / '分布式光伏预测_逐小时NRMSE_对比.csv'}")

cmp_df[["hour", "rows",
        "final_site_nrmse_mean_pct",
        "final_city_nrmse_pct"]].rename(columns={
        "final_site_nrmse_mean_pct": "site_nrmse_mean_pct",
        "final_city_nrmse_pct": "city_nrmse_pct",
    }).to_csv(OUT_DIR / "分布式光伏预测_逐小时平均NRMSE.csv", index=False, encoding="utf-8-sig")
print(f"  Done → {OUT_DIR / '分布式光伏预测_逐小时平均NRMSE.csv'}")

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("All files regenerated successfully!")
print("=" * 60)
print(f"Output directory: {OUT_DIR}")
for f in sorted(OUT_DIR.glob("分布式光伏预测_*.csv")):
    size = f.stat().st_size
    print(f"  {f.name}  ({size/1024:.1f} KB)")
