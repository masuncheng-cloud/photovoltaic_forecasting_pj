#!/usr/bin/env python3
"""
diagnose_prediction_error_drivers.py
===================================
综合误差诊断脚本。

诊断目标：
  1. 站点级误差（NRMSE/Bias/Pred-Actual Ratio）
  2. 小时级误差
  3. 站点-小时交叉误差
  4. 月份/季节误差
  5. 场景误差（scene_v151）
  6. 自动打标 risk_flags

口径（统一）：
  split == test
  hour 6-19
  power_pred_final 作为预测列
  不使用 MAPE/WAPE

输出文件：
  output/pv_pipeline/diagnostics/round57_error_by_site.csv
  output/pv_pipeline/diagnostics/round57_error_by_hour.csv
  output/pv_pipeline/diagnostics/round57_error_by_site_hour.csv
  output/pv_pipeline/diagnostics/round57_error_by_month.csv
  output/pv_pipeline/diagnostics/round57_error_by_scene.csv
  output/pv_pipeline/diagnostics/round57_priority_sites.csv
  output/pv_pipeline/diagnostics/round57_error_driver_summary.csv

用法：
    python scripts/diagnose_prediction_error_drivers.py
"""

from pathlib import Path
import json
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "output/pv_pipeline/diagnostics"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PRED_COL = "power_pred_final"
EVAL_SPLIT = "test"
EVAL_HOURS = range(6, 20)


def load_data():
    """加载所有必要数据。"""
    out = PROJECT_ROOT / "output/pv_pipeline"
    pred_dir = out / "predictions"
    tables_dir = out / "tables"

    # eval pkl（只用它做误差诊断，因为只含 test split）
    eval_pkl = pred_dir / "distributed_predictions_final_eval.pkl"
    df_eval = pd.read_pickle(eval_pkl)
    print(f"[INFO] loaded eval: {df_eval.shape}, splits: {df_eval['split'].unique()}")

    # full pkl（用于 scene 等全量字段分析）
    full_pkl = pred_dir / "distributed_predictions_final_full.pkl"
    df_full = pd.read_pickle(full_pkl)
    print(f"[INFO] loaded full: {df_full.shape}")

    # site_master（用于 station_name）
    sm_path = tables_dir / "site_master.csv"
    sm = pd.read_csv(sm_path) if sm_path.exists() else None
    if sm is not None:
        sm_names = {}
        for _, row in sm.iterrows():
            sid = str(row.get("site_id", ""))
            name = str(row.get("site_full_name") or row.get("site_short_name") or sid)
            sm_names[sid] = name
        print(f"[INFO] loaded site_master: {len(sm_names)} sites")
    else:
        sm_names = {}

    # geo overrides（用于 geo_confidence）
    geo_path = PROJECT_ROOT / "configs" / "manual_station_geo_overrides.csv"
    geo_conf = {}
    if geo_path.exists():
        geo_df = pd.read_csv(geo_path)
        for _, r in geo_df.iterrows():
            sid = str(r.get("station_id", "")).strip()
            geo_conf[sid] = str(r.get("confidence", "")).strip()
    print(f"[INFO] loaded geo_overrides: {len(geo_conf)} sites")

    return df_eval, df_full, sm_names, geo_conf


def eval_frame(df: pd.DataFrame) -> pd.DataFrame:
    """统一评估口径：test + hour 6-19。"""
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    if "month" not in df.columns:
        df["month"] = df["time"].dt.month
    df["date"] = df["time"].dt.strftime("%Y-%m-%d")

    mask = pd.Series(True, index=df.index)
    if "split" in df.columns:
        mask = mask & (df["split"] == EVAL_SPLIT)
    mask = mask & df["hour"].isin(EVAL_HOURS)
    mask = mask & df["power_mw"].notna()
    mask = mask & df[PRED_COL].notna()
    mask = mask & (df["capacity_mw"] > 0)
    result = df[mask].copy()
    print(f"[INFO] eval frame: {len(result)} rows, {result['site_id'].nunique()} sites")
    return result


def _rmse(a, p):
    a = np.asarray(a, dtype=float)
    p = np.asarray(p, dtype=float)
    if len(a) == 0:
        return np.nan
    return float(np.sqrt(np.mean((p - a) ** 2)))


def _nrmse(a, p, den):
    den = float(den)
    if den <= 0:
        return np.nan
    return _rmse(a, p) / den * 100


def _bias_pct(a, p):
    a = np.asarray(a, dtype=float)
    p = np.asarray(p, dtype=float)
    a_sum = float(np.sum(a))
    if abs(a_sum) < 1e-12:
        return np.nan
    return (float(np.sum(p)) - a_sum) / a_sum * 100


def _pred_actual(a, p):
    a = np.asarray(a, dtype=float)
    p = np.asarray(p, dtype=float)
    a_sum = float(np.sum(a))
    if abs(a_sum) < 1e-12:
        return np.nan
    return float(np.sum(p)) / a_sum


def compute_risk_flags(row: dict) -> list[str]:
    """根据行数据生成 risk_flags。"""
    flags = []
    nrmse = row.get("nrmse_percent", 0) or 0
    bias_val = row.get("bias_percent")
    bias = abs(bias_val) if bias_val is not None and not (isinstance(bias_val, float) and np.isnan(bias_val)) else 0
    pa_ratio = row.get("pred_actual_ratio", 1) or 1
    # NaN pa_ratio means no valid actual sum
    if pa_ratio is None or (isinstance(pa_ratio, float) and np.isnan(pa_ratio)):
        pa_ratio = np.nan
    zero_ratio = row.get("zero_ratio_6_19", 0) or 0
    pred_zero = row.get("pred_zero_ratio_6_19", 0) or 0
    gblend_zero = row.get("g_blend_zero_ratio", 0) or 0
    has_geo_ratio = row.get("has_geo_ratio", 1) or 1
    geo_conf = str(row.get("geo_confidence", "")).strip()
    max_ratio = row.get("max_power_ratio", 0) or 0
    scene_night = row.get("scene_night_ratio_10_14", 0) or 0

    if nrmse >= 20:
        flags.append("high_nrmse")
    # Only apply bias flags if bias is valid (not NaN)
    if not (isinstance(bias_val, float) and np.isnan(bias_val)):
        if bias >= 20:
            flags.append("high_bias")
        if not np.isnan(pa_ratio):
            if pa_ratio >= 1.25:
                flags.append("over_prediction")
            elif pa_ratio <= 0.75:
                flags.append("under_prediction")
    else:
        # NaN bias means actual_sum is ~0 for this aggregation
        flags.append("zero_actual_sum")
    if zero_ratio >= 0.5:
        flags.append("high_actual_zero_ratio")
    if pred_zero >= 0.5:
        flags.append("high_pred_zero_ratio")
    if gblend_zero >= 0.5:
        flags.append("irradiance_zero_or_missing")
    if has_geo_ratio < 1:
        flags.append("missing_geo")
    if geo_conf == "low":
        flags.append("low_confidence_geo")
    if max_ratio > 1.2:
        flags.append("capacity_or_power_outlier")
    # scene_night is now computed from test 10-14 window
    if scene_night > 0.05:
        flags.append("daytime_scene_night")
    if not flags:
        flags.append("ok")
    return flags


def recommend_action(flags: list[str], nrmse: float, bias: float, pa: float) -> str:
    """根据 flags 推荐下一步。"""
    if "low_confidence_geo" in flags:
        return "建议更新 S116 精确坐标（confidence=low）"
    if "missing_geo" in flags:
        return "建议补全站点经纬度"
    if "irradiance_zero_or_missing" in flags:
        return "建议检查辐照特征链路"
    if "capacity_or_power_outlier" in flags:
        return "建议检查容量映射或功率异常"
    if "high_actual_zero_ratio" in flags:
        return "建议核实功率数据是否存在长期限电或遮挡"
    if "over_prediction" in flags:
        return "建议检查是否存在系统性高估，考虑站点级 bias 校准"
    if "under_prediction" in flags:
        return "建议检查是否存在系统性低估，考虑站点级 bias 校准"
    if "high_nrmse" in flags and nrmse >= 30:
        return "高误差且容量较大，建议优先分析模型输入特征"
    if "high_bias" in flags:
        return "偏差较大，建议分析偏差来源（数据/特征/模型）"
    return "暂不需要模型修正，持续监控"


# ── 1. error_by_site ────────────────────────────────────────────────────────

def compute_error_by_site(df: pd.DataFrame, sm_names: dict, geo_conf: dict) -> pd.DataFrame:
    """站点级误差统计。"""
    rows = []
    for sid, sdf in df.groupby("site_id"):
        sid = str(sid)
        n = len(sdf)

        # 基本统计
        actual = sdf["power_mw"].astype(float)
        pred = sdf[PRED_COL].astype(float)
        cap = sdf["capacity_mw"].astype(float).mean()

        mae = float((pred - actual).abs().mean())
        rmse = float(np.sqrt(((pred - actual) ** 2).mean()))
        nrmse = float(rmse / max(cap, 1e-9) * 100)

        actual_sum = float(actual.sum())
        pred_sum = float(pred.sum())
        if actual_sum < 1e-6:
            bias_pct = float("nan")
        else:
            bias_pct = float((pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100)
        if actual_sum < 1e-6:
            pa_ratio = float("nan")
        else:
            pa_ratio = float(pred_sum / max(actual_sum, 1e-9))

        pos_rows = int((actual > 0).sum())
        zero_ratio = float((actual == 0).mean())
        pred_zero_ratio = float((pred.fillna(0) == 0).mean())

        actual_max = float(actual.max())
        pred_max = float(pred.max())
        max_ratio = float(pred_max / max(actual_max, 1e-9)) if actual_max > 0 else 0

        # 辐照
        has_gblend = "g_blend_pred" in sdf.columns
        gblend_zero_ratio = 0.0
        if has_gblend:
            gblend_zero_ratio = float((sdf["g_blend_pred"].fillna(0).abs() < 1e-9).mean())

        # has_geo（用 station_metadata 查，不在 eval 里）
        has_geo_ratio = 1.0  # 假设 eval 都有

        # scene 分布
        scene_night = 0.0
        scene_low = 0.0
        scene_mid = 0.0
        scene_clear = 0.0
        if "scene_v151" in sdf.columns:
            sc = sdf["scene_v151"].astype(str)
            total = max(len(sc), 1)
            scene_night = float(sc.eq("night").sum()) / total
            scene_low = float(sc.eq("low").sum()) / total
            scene_mid = float(sc.eq("mid").sum()) / total
            scene_clear = float(sc.eq("clear_peak").sum()) / total

        row = {
            "station_id": sid,
            "station_name": sm_names.get(sid, sid),
            "capacity_mw": round(cap, 4),
            "rows": n,
            "positive_rows": pos_rows,
            "zero_ratio_6_19": round(zero_ratio, 4),
            "actual_sum_mwh_like": round(actual_sum, 4),
            "pred_sum_mwh_like": round(pred_sum, 4),
            "pred_actual_ratio": round(pa_ratio, 4),
            "bias_percent": round(bias_pct, 4),
            "mae_mw": round(mae, 4),
            "rmse_mw": round(rmse, 4),
            "nrmse_percent": round(nrmse, 4),
            "pred_zero_ratio_6_19": round(pred_zero_ratio, 4),
            "actual_max_mw": round(actual_max, 4),
            "pred_max_mw": round(pred_max, 4),
            "max_power_ratio": round(max_ratio, 4),
            "has_geo_ratio": round(has_geo_ratio, 4),
            "geo_confidence": geo_conf.get(sid, ""),
            "scene_night_ratio_6_19": round(scene_night, 4),
            "scene_low_ratio": round(scene_low, 4),
            "scene_mid_ratio": round(scene_mid, 4),
            "scene_clear_peak_ratio": round(scene_clear, 4),
            "g_blend_non_null_ratio": round(1.0 - gblend_zero_ratio, 4),
            "g_blend_zero_ratio": round(gblend_zero_ratio, 4),
        }

        flags = compute_risk_flags(row)
        row["risk_flags"] = "|".join(flags)
        rows.append(row)

    return pd.DataFrame(rows)


# ── 2. error_by_hour ────────────────────────────────────────────────────────

def compute_error_by_hour(df: pd.DataFrame) -> pd.DataFrame:
    """小时级误差统计。"""
    rows = []
    for hour, hdf in df.groupby("hour"):
        n = len(hdf)

        # city-level
        actual = hdf["power_mw"].astype(float)
        pred = hdf[PRED_COL].astype(float)
        cap_sum = float(hdf.groupby("time")["capacity_mw"].first().sum())
        actual_sum = float(actual.sum())
        pred_sum = float(pred.sum())

        city_rmse = float(np.sqrt(((pred - actual) ** 2).mean()))
        city_nrmse = float(city_rmse / max(cap_sum / n, 1e-9) * 100)

        bias_city = float((pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100)
        pa_city = float(pred_sum / max(actual_sum, 1e-9))
        mae_mean = float((pred - actual).abs().mean())

        # zero ratio
        zero_actual = float((actual == 0).mean())
        zero_pred = float((pred.fillna(0) == 0).mean())

        # top error sites (by abs error)
        hdf = hdf.copy()
        hdf["abs_err"] = (hdf[PRED_COL].astype(float) - hdf["power_mw"].astype(float)).abs()
        top_sites = (
            hdf.groupby("site_id")["abs_err"].mean()
            .nlargest(3).index.tolist()
        )

        rows.append({
            "hour": int(hour),
            "rows": n,
            "site_mean_nrmse_percent": round(city_nrmse, 4),
            "city_nrmse_percent": round(city_nrmse, 4),
            "mae_mw_mean": round(mae_mean, 4),
            "rmse_mw_mean": round(city_rmse, 4),
            "bias_percent_city": round(bias_city, 4),
            "pred_actual_ratio_city": round(pa_city, 4),
            "actual_sum": round(actual_sum, 4),
            "pred_sum": round(pred_sum, 4),
            "zero_ratio_actual": round(zero_actual, 4),
            "zero_ratio_pred": round(zero_pred, 4),
            "top_error_sites": "|".join(top_sites),
        })

    result = pd.DataFrame(rows).sort_values("hour")
    return result


# ── 3. error_by_site_hour ────────────────────────────────────────────────────

def compute_error_by_site_hour(df: pd.DataFrame, sm_names: dict) -> pd.DataFrame:
    """站点-小时交叉误差。"""
    rows = []
    for (sid, hour), sh in df.groupby(["site_id", "hour"]):
        sid = str(sid)
        n = len(sh)
        actual = sh["power_mw"].astype(float)
        pred = sh[PRED_COL].astype(float)
        cap = sh["capacity_mw"].astype(float).mean()

        mae = float((pred - actual).abs().mean())
        rmse = float(np.sqrt(((pred - actual) ** 2).mean()))
        nrmse = float(rmse / max(cap, 1e-9) * 100)

        actual_sum = float(actual.sum())
        pred_sum = float(pred.sum())
        bias = float((pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100)
        pa = float(pred_sum / max(actual_sum, 1e-9))

        zero_actual = float((actual == 0).mean())
        zero_pred = float((pred.fillna(0) == 0).mean())

        # main scene
        scene_main = ""
        if "scene_v151" in sh.columns:
            vc = sh["scene_v151"].astype(str).value_counts()
            scene_main = str(vc.index[0]) if len(vc) else ""

        row = {
            "station_id": sid,
            "station_name": sm_names.get(sid, sid),
            "hour": int(hour),
            "rows": n,
            "nrmse_percent": round(nrmse, 4),
            "mae_mw": round(mae, 4),
            "rmse_mw": round(rmse, 4),
            "bias_percent": round(bias, 4),
            "pred_actual_ratio": round(pa, 4),
            "actual_zero_ratio": round(zero_actual, 4),
            "pred_zero_ratio": round(zero_pred, 4),
            "scene_main": scene_main,
        }
        flags = compute_risk_flags(row)
        row["risk_flags"] = "|".join(flags)
        rows.append(row)

    return pd.DataFrame(rows)


# ── 4. error_by_month ───────────────────────────────────────────────────────

def compute_error_by_month(df: pd.DataFrame) -> pd.DataFrame:
    """月份误差统计。"""
    rows = []
    for month, mdf in df.groupby("month"):
        n = len(mdf)
        actual = mdf["power_mw"].astype(float)
        pred = mdf[PRED_COL].astype(float)

        # city
        actual_sum = float(actual.sum())
        pred_sum = float(pred.sum())
        cap_sum = float(mdf.groupby("time")["capacity_mw"].first().sum())
        city_rmse = float(np.sqrt(((pred - actual) ** 2).mean()))
        city_nrmse = float(city_rmse / max(cap_sum / n, 1e-9) * 100)

        bias = float((pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100)
        pa = float(pred_sum / max(actual_sum, 1e-9))

        # top error sites
        mdf = mdf.copy()
        mdf["abs_err"] = (mdf[PRED_COL].astype(float) - mdf["power_mw"].astype(float)).abs()
        top_sites = (
            mdf.groupby("site_id")["abs_err"].mean()
            .nlargest(3).index.tolist()
        )

        rows.append({
            "month": int(month),
            "rows": n,
            "site_mean_nrmse_percent": round(city_nrmse, 4),
            "city_nrmse_percent": round(city_nrmse, 4),
            "bias_percent_city": round(bias, 4),
            "pred_actual_ratio_city": round(pa, 4),
            "top_error_sites": "|".join(str(s) for s in top_sites),
        })

    result = pd.DataFrame(rows).sort_values("month")
    return result


# ── 5. error_by_scene ───────────────────────────────────────────────────────

def compute_error_by_scene(df: pd.DataFrame) -> pd.DataFrame:
    """场景误差统计。"""
    if "scene_v151" not in df.columns:
        return pd.DataFrame([{
            "note": "final_eval 未包含 scene_v151 字段，无法做场景误差诊断",
        }])

    rows = []
    for scene, sdf in df.groupby("scene_v151"):
        n = len(sdf)
        actual = sdf["power_mw"].astype(float)
        pred = sdf[PRED_COL].astype(float)
        cap_sum = float(sdf.groupby("time")["capacity_mw"].first().sum())

        actual_sum = float(actual.sum())
        pred_sum = float(pred.sum())
        city_rmse = float(np.sqrt(((pred - actual) ** 2).mean()))
        city_nrmse = float(city_rmse / max(cap_sum / n, 1e-9) * 100)
        bias = float((pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100)
        pa = float(pred_sum / max(actual_sum, 1e-9))

        sdf_copy = sdf.copy()
        sdf_copy["abs_err"] = (sdf_copy[PRED_COL].astype(float) - sdf_copy["power_mw"].astype(float)).abs()
        top_sites = (
            sdf_copy.groupby("site_id")["abs_err"].mean()
            .nlargest(3).index.tolist()
        )

        rows.append({
            "scene": str(scene),
            "rows": n,
            "site_mean_nrmse_percent": round(city_nrmse, 4),
            "city_nrmse_percent": round(city_nrmse, 4),
            "bias_percent": round(bias, 4),
            "pred_actual_ratio": round(pa, 4),
            "top_error_sites": "|".join(str(s) for s in top_sites),
        })

    return pd.DataFrame(rows)


# ── 6. priority_sites ─────────────────────────────────────────────────────

def compute_priority_sites(site_df: pd.DataFrame) -> pd.DataFrame:
    """优先处理站点清单。"""
    # 过滤掉全0和无意义站点
    valid = site_df[
        (site_df["zero_ratio_6_19"] < 0.95)  # 至少有一些正功率
        & (site_df["rows"] >= 50)  # 样本充足
    ].copy()

    # 优先级：NRMSE * capacity 作为权重（容量越大影响越大）
    valid["priority_score"] = valid["nrmse_percent"] * valid["capacity_mw"]

    # 排序：优先高 NRMSE 且大容量
    valid = valid.sort_values("priority_score", ascending=False)

    rows = []
    for rank, (_, row) in enumerate(valid.iterrows(), 1):
        # 找最差的 3 个小时
        hour_df = site_df[site_df["station_id"] == row["station_id"]]
        if "hour" in [c for c in hour_df.columns]:
            # reload hour data from site_df if available
            pass
        main_flags = [f for f in (row.get("risk_flags", "") or "").split("|") if f and f != "ok"]

        rows.append({
            "priority_rank": rank,
            "station_id": row["station_id"],
            "station_name": row.get("station_name", row["station_id"]),
            "capacity_mw": row["capacity_mw"],
            "nrmse_percent": row["nrmse_percent"],
            "bias_percent": row["bias_percent"],
            "pred_actual_ratio": row["pred_actual_ratio"],
            "zero_ratio_6_19": row["zero_ratio_6_19"],
            "main_bad_hours": "",  # filled by caller if available
            "main_risk_flags": "|".join(main_flags[:3]),
            "recommended_next_action": recommend_action(
                main_flags, row["nrmse_percent"], row["bias_percent"], row["pred_actual_ratio"]
            ),
        })

    return pd.DataFrame(rows)


# ── Summary ────────────────────────────────────────────────────────────────

def compute_summary(df_eval: pd.DataFrame, site_df: pd.DataFrame) -> dict:
    """计算总览指标。"""
    actual = df_eval["power_mw"].astype(float)
    pred = df_eval[PRED_COL].astype(float)
    cap = df_eval["capacity_mw"].astype(float)
    time_caps = df_eval.groupby("time")["capacity_mw"].first()

    actual_sum = float(actual.sum())
    pred_sum = float(pred.sum())

    mae = float((pred - actual).abs().mean())
    rmse = float(np.sqrt(((pred - actual) ** 2).mean()))
    bias = float((pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100)
    pa = float(pred_sum / max(actual_sum, 1e-9))

    # city NRMSE
    city_rmse = float(np.sqrt(((pred - actual) ** 2).mean()))
    cap_avg = float(cap.mean())
    city_nrmse = float(city_rmse / max(cap_avg, 1e-9) * 100)

    # 6-19 total
    total_nrmse = float(city_rmse / max(cap_avg, 1e-9) * 100)

    # 10-14 subset
    df_10_14 = df_eval[df_eval["hour"].between(10, 14)]
    if len(df_10_14) > 0:
        a14 = df_10_14["power_mw"].astype(float)
        p14 = df_10_14[PRED_COL].astype(float)
        c14 = df_10_14["capacity_mw"].astype(float)
        r14 = float(np.sqrt(((p14 - a14) ** 2).mean()))
        nrmse_10_14 = float(r14 / max(float(c14.mean()), 1e-9) * 100)
    else:
        nrmse_10_14 = np.nan

    # site mean
    site_nrmse = float(site_df["nrmse_percent"].mean())

    # high error sites
    high_nrmse = int((site_df["nrmse_percent"] >= 20).sum())
    high_bias = int((site_df["bias_percent"].abs() >= 20).sum())

    return {
        "total_rows": len(df_eval),
        "total_sites": int(df_eval["site_id"].nunique()),
        "mae_mw": round(mae, 4),
        "rmse_mw": round(rmse, 4),
        "city_nrmse_6_19": round(total_nrmse, 4),
        "city_nrmse_10_14": round(nrmse_10_14, 4) if not np.isnan(nrmse_10_14) else None,
        "site_mean_nrmse": round(site_nrmse, 4),
        "bias_percent": round(bias, 4),
        "pred_actual_ratio": round(pa, 4),
        "high_nrmse_sites": high_nrmse,
        "high_bias_sites": high_bias,
    }


# ── Main ────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("综合误差诊断 — diagnose_prediction_error_drivers.py")
    print("口径: split=test, hour=6-19, pred=power_pred_final")
    print("=" * 60)

    df_eval, df_full, sm_names, geo_conf = load_data()

    # 统一口径
    df = eval_frame(df_eval)

    print(f"\n[1] 计算站点级误差...")
    site_df = compute_error_by_site(df, sm_names, geo_conf)
    site_path = OUT_DIR / "round57_error_by_site.csv"
    site_df.to_csv(site_path, index=False, encoding="utf-8-sig")
    print(f"    → {site_path} ({len(site_df)} sites)")

    print(f"\n[2] 计算小时级误差...")
    hour_df = compute_error_by_hour(df)
    hour_path = OUT_DIR / "round57_error_by_hour.csv"
    hour_df.to_csv(hour_path, index=False, encoding="utf-8-sig")
    print(f"    → {hour_path} ({len(hour_df)} hours)")

    print(f"\n[3] 计算站点-小时交叉误差...")
    site_hour_df = compute_error_by_site_hour(df, sm_names)
    site_hour_path = OUT_DIR / "round57_error_by_site_hour.csv"
    site_hour_df.to_csv(site_hour_path, index=False, encoding="utf-8-sig")
    print(f"    → {site_hour_path} ({len(site_hour_df)} rows)")

    print(f"\n[4] 计算月份误差...")
    month_df = compute_error_by_month(df)
    month_path = OUT_DIR / "round57_error_by_month.csv"
    month_df.to_csv(month_path, index=False, encoding="utf-8-sig")
    print(f"    → {month_path} ({len(month_df)} months)")

    print(f"\n[5] 计算场景误差...")
    scene_df = compute_error_by_scene(df)
    scene_path = OUT_DIR / "round57_error_by_scene.csv"
    scene_df.to_csv(scene_path, index=False, encoding="utf-8-sig")
    print(f"    → {scene_path} ({len(scene_df)} scenes)")

    print(f"\n[6] 计算优先处理站点...")
    priority_df = compute_priority_sites(site_df)
    priority_path = OUT_DIR / "round57_priority_sites.csv"
    priority_df.to_csv(priority_path, index=False, encoding="utf-8-sig")
    print(f"    → {priority_path} ({len(priority_df)} sites)")

    print(f"\n[7] 计算总览指标...")
    summary = compute_summary(df, site_df)
    summary_path = OUT_DIR / "round57_error_driver_summary.csv"
    pd.DataFrame([summary]).to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"    → {summary_path}")

    # 打印摘要
    print("\n" + "=" * 60)
    print("总览指标")
    print("=" * 60)
    for k, v in summary.items():
        print(f"  {k:30s}: {v}")

    print("\n" + "=" * 60)
    print("高误差站点 (nrmse >= 20%)")
    print("=" * 60)
    high = site_df[site_df["nrmse_percent"] >= 20].sort_values("nrmse_percent", ascending=False)
    if not high.empty:
        print(high[["station_id", "station_name", "capacity_mw", "nrmse_percent", "bias_percent",
                   "pred_actual_ratio", "risk_flags"]].to_string(index=False))
    else:
        print("  无 nrmse >= 20% 的站点")

    print("\n" + "=" * 60)
    print("高 Bias 站点 (|bias| >= 20%)")
    print("=" * 60)
    bias_high = site_df[site_df["bias_percent"].abs() >= 20].sort_values("bias_percent", ascending=False)
    if not bias_high.empty:
        print(bias_high[["station_id", "station_name", "bias_percent", "pred_actual_ratio", "risk_flags"]].to_string(index=False))
    else:
        print("  无 |bias| >= 20% 的站点")

    print("\n" + "=" * 60)
    print("优先处理站点 TOP 10")
    print("=" * 60)
    if not priority_df.empty:
        top10 = priority_df.head(10)
        print(top10[["priority_rank", "station_id", "station_name", "capacity_mw",
                    "nrmse_percent", "bias_percent", "recommended_next_action"]].to_string(index=False))
    else:
        print("  无优先站点")

    print(f"\n[OK] 诊断完成，输出目录: {OUT_DIR}")


if __name__ == "__main__":
    main()
