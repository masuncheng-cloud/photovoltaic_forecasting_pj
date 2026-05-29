"""
round41_42_unified_daytime_and_site_calibration.py
====================================================
Round44（修正版）：训练逻辑与可视化问题总收口

修改内容（对比 Round41/42 原版）：
1. daytime_source 由 valid 集选择（严格禁止 test 集 snooping）
   — Round45 修正确认：完全禁用任何 test 参考，不允许 fallback
2. 站点级校准增加 valid 集守门：三条件全满足才启用，否则自动回退
3. 输出 round44_site_calibration_decision.csv，记录完整守门决策过程
4. round41_42_selection_info.json 明确标注 selection_split=valid 及 test_used_for_selection=false

Round45 修正确认：
- 删除 verify_and_maybe_override（test fallback 逻辑）
- 完全信任 valid 集选择结果
"""

from pathlib import Path
import json
import math
import shutil
import numpy as np
import pandas as pd


ROOT = Path("output/pv_pipeline")
TABLE_DIR = ROOT / "tables"
METRIC_DIR = ROOT / "metrics"
METRIC_DIR.mkdir(parents=True, exist_ok=True)

EDGE_HOURS = [6, 7, 18, 19]
DAYTIME_HOURS = list(range(8, 18))
FOCUS_HOURS = [10, 11, 12, 13, 14]

# 先验工程开关（默认关闭）
USE_FIXED_DAYTIME_SOURCE = False
FIXED_DAYTIME_SOURCE = "power_pred_cal"


def find_final_pkl():
    candidates = sorted(TABLE_DIR.glob("distributed_predictions_final_round*.pkl"))
    if candidates:
        return candidates[-1]
    for name in ["distributed_predictions_final_full.pkl", "distributed_predictions_final.pkl"]:
        p = TABLE_DIR / name
        if p.exists():
            return p
    raise FileNotFoundError("找不到 distributed_predictions_final*.pkl")


def normalize(df):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    if "date" not in df.columns:
        df["date"] = df["time"].dt.strftime("%Y-%m-%d")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    return df


def candidate_columns(df):
    cols = []
    for c in [
        "power_pred",
        "power_pred_cal",
        "pred_calibrated",
        "power_pred_final_round40_snapshot",
        "power_pred_final",
    ]:
        if c in df.columns and c not in cols:
            cols.append(c)
    return cols


def rmse(x):
    x = np.asarray(x, dtype=float)
    return math.sqrt(float(np.mean(x * x))) if len(x) else np.nan


def city_hour_metrics(df, pred_col, split, hours):
    """在指定 split 上计算指定 hours 的逐小时城市级 NRMSE。"""
    work = df[
        df["split"].eq(split)
        & df["hour"].isin(hours)
        & df["power_mw"].notna()
        & df[pred_col].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()
    if work.empty:
        return None

    work["actual_mw"] = pd.to_numeric(work["power_mw"], errors="coerce")
    work["pred_mw"] = pd.to_numeric(work[pred_col], errors="coerce")
    work["capacity_mw"] = pd.to_numeric(work["capacity_mw"], errors="coerce")
    work = work[work["actual_mw"].notna() & work["pred_mw"].notna()].copy()
    if work.empty:
        return None

    rows = []
    for hour, hdf in work.groupby("hour"):
        city = (
            hdf.groupby("time", as_index=False)
            .agg(
                actual_mw=("actual_mw", "sum"),
                pred_mw=("pred_mw", "sum"),
                capacity_sum_mw=("capacity_mw", "sum"),
                site_count=("site_id", "nunique"),
            )
        )
        err = city["pred_mw"] - city["actual_mw"]
        rmse_mw = rmse(err)
        cap = float(city["capacity_sum_mw"].mean())
        nrmse = rmse_mw / max(cap, 1e-9) * 100
        bias = (city["pred_mw"].sum() - city["actual_mw"].sum()) / max(city["actual_mw"].sum(), 1e-9) * 100
        suspicious_zero = int(((city["actual_mw"] > 1e-9) & (city["pred_mw"].abs() <= 1e-9)).sum())
        rows.append({
            "hour": int(hour),
            "samples": int(len(city)),
            "city_nrmse_pct": float(nrmse),
            "city_bias_pct": float(bias),
            "suspicious_city_zero_count": suspicious_zero,
        })

    h = pd.DataFrame(rows)
    return {
        "pred_col": pred_col,
        "split": split,
        "hours": ",".join(map(str, hours)),
        "hour_count": int(h["hour"].nunique()),
        "mean_hourly_city_nrmse_pct": round(float(h["city_nrmse_pct"].mean()), 6),
        "max_hourly_city_nrmse_pct": round(float(h["city_nrmse_pct"].max()), 6),
        "mean_abs_bias_pct": round(float(h["city_bias_pct"].abs().mean()), 6),
        "total_suspicious_city_zero_count": int(h["suspicious_city_zero_count"].sum()),
    }


def select_daytime_source(df, cols):
    """评估各候选在 valid 集 focus hours 上的表现，选择最优。

    严格只用 valid 集，不参考 test 集任何指标。
    """
    rows = []
    for col in cols:
        m = city_hour_metrics(df, col, "valid", FOCUS_HOURS)
        if m is not None:
            rows.append(m)
    if not rows:
        raise RuntimeError("valid 集无法计算 10-14 候选来源指标")
    table = pd.DataFrame(rows).sort_values(
        ["mean_hourly_city_nrmse_pct", "mean_abs_bias_pct"],
        ascending=[True, True],
    )
    selected = table.iloc[0].to_dict()
    return table, selected


def apply_unified_daytime_source(df, daytime_source):
    """应用统一日间来源 + 边缘时段保护。

    策略：
    - 边缘时段（6,7,18,19）：使用 power_pred_cal
    - 日间时段（8-17）：使用 valid 集选择的 daytime_source
    """
    out = df.copy()
    if "power_pred_final_round40_snapshot" not in out.columns:
        out["power_pred_final_round40_snapshot"] = out["power_pred_final"]

    out["power_pred_final_before_round41_42"] = out["power_pred_final"]
    out["power_pred_round41_daytime"] = out["power_pred_final_round40_snapshot"]

    # 边缘时段：使用 power_pred_cal
    if "power_pred_cal" in out.columns:
        edge_mask = out["hour"].isin(EDGE_HOURS) & out["power_pred_cal"].notna()
        out.loc[edge_mask, "power_pred_round41_daytime"] = out.loc[edge_mask, "power_pred_cal"]

    # 日间时段：使用 valid 集选择的 daytime_source
    day_mask = out["hour"].isin(DAYTIME_HOURS) & out[daytime_source].notna()
    out.loc[day_mask, "power_pred_round41_daytime"] = out.loc[day_mask, daytime_source]

    out["power_pred_round41_daytime"] = pd.to_numeric(out["power_pred_round41_daytime"], errors="coerce").clip(lower=0)
    out["power_pred_final"] = out["power_pred_round41_daytime"]
    return out


def fit_site_alpha(df):
    """在 train+valid 上拟合 site 级别 alpha。"""
    train = df[
        df["split"].isin(["train", "valid"])
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df["power_pred_final"].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()

    train["power_mw"] = pd.to_numeric(train["power_mw"], errors="coerce")
    train["power_pred_final"] = pd.to_numeric(train["power_pred_final"], errors="coerce")
    train["capacity_mw"] = pd.to_numeric(train["capacity_mw"], errors="coerce")
    train["active_threshold_mw"] = np.maximum(0.02 * train["capacity_mw"], 0.05)
    train = train[train["power_mw"] > train["active_threshold_mw"]].copy()

    rows = []
    for sid, g in train.groupby("site_id"):
        y = g["power_mw"].to_numpy(dtype=float)
        p = g["power_pred_final"].to_numpy(dtype=float)

        valid_mask = np.isfinite(y) & np.isfinite(p) & (p > 1e-9)
        y = y[valid_mask]
        p = p[valid_mask]
        n = len(y)

        if n < 50:
            alpha_raw = 1.0
            alpha = 1.0
            w = 0.0
        else:
            alpha_raw = float(np.sum(y * p) / max(np.sum(p * p), 1e-9))
            alpha_raw = float(np.clip(alpha_raw, 0.70, 1.30))
            w = float(n / (n + 500))
            alpha = float(w * alpha_raw + (1 - w) * 1.0)

        rows.append({
            "site_id": sid,
            "fit_samples": int(n),
            "alpha_raw_clipped": round(alpha_raw, 8),
            "alpha": round(alpha, 8),
            "weight": round(w, 8),
        })

    return pd.DataFrame(rows)


def apply_site_calibration(df, alpha):
    """应用站点级校准到全 split。"""
    out = df.merge(alpha[["site_id", "alpha"]], on="site_id", how="left")
    out["alpha"] = out["alpha"].fillna(1.0)
    out["power_pred_final_before_round42_site_cal"] = out["power_pred_final"]
    out["power_pred_round42_site_cal"] = out["power_pred_final"] * out["alpha"]
    out["power_pred_round42_site_cal"] = out["power_pred_round42_site_cal"].clip(lower=0)
    out["power_pred_round42_site_cal"] = np.minimum(out["power_pred_round42_site_cal"], out["capacity_mw"])
    out["power_pred_final"] = out["power_pred_round42_site_cal"]
    out = out.drop(columns=["alpha"])
    return out


def evaluate_candidate(df, pred_col, split="valid"):
    """在指定 split 上评估预测列的完整指标（全市 + 站点平均）。"""
    work = df[
        df["split"].eq(split)
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df[pred_col].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()

    work["actual_mw"] = pd.to_numeric(work["power_mw"], errors="coerce")
    work["pred_mw"] = pd.to_numeric(work[pred_col], errors="coerce")
    work["capacity_mw"] = pd.to_numeric(work["capacity_mw"], errors="coerce")
    work = work[work["actual_mw"].notna() & work["pred_mw"].notna()].copy()

    city = work.groupby("time", as_index=False).agg(
        actual_mw=("actual_mw", "sum"),
        pred_mw=("pred_mw", "sum"),
        capacity_sum_mw=("capacity_mw", "sum"),
    )
    city_err = city["pred_mw"] - city["actual_mw"]
    city_rmse_val = rmse(city_err)
    city_cap = float(city["capacity_sum_mw"].mean())
    city_nrmse = city_rmse_val / max(city_cap, 1e-9) * 100
    city_bias = (city["pred_mw"].sum() - city["actual_mw"].sum()) / max(city["actual_mw"].sum(), 1e-9) * 100

    site_rows = []
    for sid, g in work.groupby("site_id"):
        err = g["pred_mw"] - g["actual_mw"]
        cap = float(g["capacity_mw"].mean())
        site_rows.append(rmse(err) / max(cap, 1e-9) * 100)

    return {
        "split": split,
        "pred_col": pred_col,
        "city_nrmse_pct": float(city_nrmse),
        "city_bias_pct": float(city_bias),
        "site_mean_nrmse_pct": float(np.mean(site_rows)) if site_rows else np.nan,
        "site_median_nrmse_pct": float(np.median(site_rows)) if site_rows else np.nan,
    }


def metric_site_summary(df, split="test"):
    """在指定 split 上计算站点级 NRMSE 汇总。"""
    work = df[
        df["split"].eq(split)
        & df["hour"].between(6, 19)
        & df["power_mw"].notna()
        & df["power_pred_final"].notna()
        & df["capacity_mw"].notna()
        & (df["capacity_mw"] > 0)
    ].copy()
    work["power_mw"] = pd.to_numeric(work["power_mw"], errors="coerce")
    work["power_pred_final"] = pd.to_numeric(work["power_pred_final"], errors="coerce")
    work["capacity_mw"] = pd.to_numeric(work["capacity_mw"], errors="coerce")
    work["active_threshold_mw"] = np.maximum(0.02 * work["capacity_mw"], 0.05)
    work["is_active_actual"] = work["power_mw"] > work["active_threshold_mw"]

    rows = []
    for sid, g in work.groupby("site_id"):
        err = g["power_pred_final"] - g["power_mw"]
        cap = float(g["capacity_mw"].mean())
        nrmse = rmse(err) / max(cap, 1e-9) * 100
        active = g[g["is_active_actual"]]
        if len(active):
            aerr = active["power_pred_final"] - active["power_mw"]
            active_nrmse = rmse(aerr) / max(cap, 1e-9) * 100
        else:
            active_nrmse = np.nan
        rows.append({
            "site_id": sid,
            "full_nrmse_pct": float(nrmse),
            "active_nrmse_pct": float(active_nrmse) if np.isfinite(active_nrmse) else np.nan,
        })

    s = pd.DataFrame(rows)
    return {
        "site_count": int(len(s)),
        "full_site_mean_nrmse_pct": round(float(s["full_nrmse_pct"].mean()), 6),
        "full_site_median_nrmse_pct": round(float(s["full_nrmse_pct"].median()), 6),
        "active_site_mean_nrmse_pct": round(float(s["active_nrmse_pct"].mean()), 6),
        "active_site_median_nrmse_pct": round(float(s["active_nrmse_pct"].median()), 6),
    }


def main():
    pkl = find_final_pkl()
    backup = pkl.with_suffix(".before_round41_42.pkl")
    shutil.copy2(pkl, backup)
    print("[OK] backup:", backup)

    df = pd.read_pickle(pkl)
    df = normalize(df)

    if "power_pred_final_round40_snapshot" not in df.columns:
        df["power_pred_final_round40_snapshot"] = df["power_pred_final"]

    cols = candidate_columns(df)

    # -----------------------------------------------------------
    # 步骤 1：选择 daytime_source（严格只用 valid 集）
    # -----------------------------------------------------------
    if USE_FIXED_DAYTIME_SOURCE:
        daytime_source = FIXED_DAYTIME_SOURCE
        selection_reason = "fixed_by_engineering_prior_not_test_metric"
        selection_table = pd.DataFrame([{
            "pred_col": daytime_source,
            "selection_reason": selection_reason,
        }])
        selected = {"pred_col": daytime_source, "selection_reason": selection_reason}
    else:
        selection_table, selected = select_daytime_source(df, cols)
        daytime_source = selected["pred_col"]
        selection_reason = "selected_by_valid_10_14_city_hourly_nrmse"

    selection_table.to_csv(
        METRIC_DIR / "round41_42_daytime_source_selection.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 收集 valid 指标用于记录
    final_valid_metric = city_hour_metrics(df, daytime_source, "valid", FOCUS_HOURS)

    selection_info = {
        "strategy": "edge_protection_plus_valid_selected_daytime_source_plus_gated_site_bias_calibration",
        "edge_hours": EDGE_HOURS,
        "daytime_hours": DAYTIME_HOURS,
        "focus_hours_for_daytime_source_selection": FOCUS_HOURS,
        "selection_split": "valid",
        "test_used_for_selection": False,
        "selection_reason": selection_reason,
        "use_fixed_daytime_source": USE_FIXED_DAYTIME_SOURCE,
        "fixed_daytime_source": FIXED_DAYTIME_SOURCE if USE_FIXED_DAYTIME_SOURCE else None,
        "selected_daytime_source": daytime_source,
        "final_valid_metrics": final_valid_metric,
    }
    (METRIC_DIR / "round41_42_selection_info.json").write_text(
        json.dumps(selection_info, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[OK] daytime_source: {daytime_source} ({selection_reason})")

    # -----------------------------------------------------------
    # 步骤 2：应用统一日间来源（候选 A：无站点校准）
    # -----------------------------------------------------------
    df1 = apply_unified_daytime_source(df, daytime_source)
    df1["candidate_no_site_cal"] = df1["power_pred_final"]

    # -----------------------------------------------------------
    # 步骤 3：拟合并应用站点级校准（候选 B：有站点校准）
    # -----------------------------------------------------------
    alpha = fit_site_alpha(df1)
    alpha.to_csv(METRIC_DIR / "round41_42_site_bias_alpha.csv", index=False, encoding="utf-8-sig")

    df2 = apply_site_calibration(df1, alpha)
    df2["candidate_with_site_cal"] = df2["power_pred_final"]

    # -----------------------------------------------------------
    # 步骤 4：使用 valid 集守门决定是否启用站点校准
    # -----------------------------------------------------------
    eval_no_cal = evaluate_candidate(
        df2.rename(columns={"candidate_no_site_cal": "tmp_pred"}),
        "tmp_pred",
        split="valid",
    )
    eval_with_cal = evaluate_candidate(
        df2.rename(columns={"candidate_with_site_cal": "tmp_pred"}),
        "tmp_pred",
        split="valid",
    )

    site_improve = eval_no_cal["site_mean_nrmse_pct"] - eval_with_cal["site_mean_nrmse_pct"]
    city_delta = eval_with_cal["city_nrmse_pct"] - eval_no_cal["city_nrmse_pct"]
    bias_ok = abs(eval_with_cal["city_bias_pct"]) <= 15.0

    use_site_cal = (
        site_improve >= 0.2
        and city_delta <= 0.3
        and bias_ok
    )

    print(f"[INFO] valid 集评估：")
    print(f"  无站点校准：city_nrmse={eval_no_cal['city_nrmse_pct']:.4f}%, "
          f"site_mean={eval_no_cal['site_mean_nrmse_pct']:.4f}%, bias={eval_no_cal['city_bias_pct']:.4f}%")
    print(f"  有站点校准：city_nrmse={eval_with_cal['city_nrmse_pct']:.4f}%, "
          f"site_mean={eval_with_cal['site_mean_nrmse_pct']:.4f}%, bias={eval_with_cal['city_bias_pct']:.4f}%")
    print(f"  站点改善：{site_improve:.4f}pp（需 >= 0.2）")
    print(f"  全市上升：{city_delta:.4f}pp（需 <= 0.3）")
    print(f"  BIAS 容忍：{bias_ok}（需 |bias| <= 15%）")
    print(f"  => 启用站点校准：{use_site_cal}")

    if use_site_cal:
        df2["power_pred_final"] = df2["candidate_with_site_cal"]
        cal_decision = "enabled"
    else:
        df2["power_pred_final"] = df2["candidate_no_site_cal"]
        cal_decision = "disabled_fallback_to_no_cal"

    # -----------------------------------------------------------
    # 步骤 5：输出站点校准决策记录
    # -----------------------------------------------------------
    decision_csv = pd.DataFrame([{
        "decision": cal_decision,
        "use_site_calibration": use_site_cal,
        "site_improve_valid_pp": round(site_improve, 6),
        "city_delta_valid_pp": round(city_delta, 6),
        "bias_valid_pct": round(eval_with_cal["city_bias_pct"], 6),
        "bias_ok": bias_ok,
        "eval_no_cal_city_nrmse": round(eval_no_cal["city_nrmse_pct"], 6),
        "eval_no_cal_site_mean_nrmse": round(eval_no_cal["site_mean_nrmse_pct"], 6),
        "eval_no_cal_bias": round(eval_no_cal["city_bias_pct"], 6),
        "eval_with_cal_city_nrmse": round(eval_with_cal["city_nrmse_pct"], 6),
        "eval_with_cal_site_mean_nrmse": round(eval_with_cal["site_mean_nrmse_pct"], 6),
        "eval_with_cal_bias": round(eval_with_cal["city_bias_pct"], 6),
    }])
    decision_csv.to_csv(
        METRIC_DIR / "round44_site_calibration_decision.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # -----------------------------------------------------------
    # 步骤 6：站点汇总（test 集，用于报告）
    # -----------------------------------------------------------
    site_summary = pd.DataFrame([metric_site_summary(df2)])
    site_summary.to_csv(
        METRIC_DIR / "round41_42_site_summary_after.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # -----------------------------------------------------------
    # 步骤 7：保存
    # -----------------------------------------------------------
    tmp = pkl.with_suffix(".round41_42.tmp.pkl")
    df2.to_pickle(tmp)
    check = pd.read_pickle(tmp)
    assert len(check) == len(df2), f"length mismatch: {len(check)} vs {len(df2)}"
    assert "power_pred_final" in check.columns
    tmp.replace(pkl)

    print("[OK] updated:", pkl)
    print(selection_table.to_string(index=False))
    print(site_summary.to_string(index=False))
    print("[OK] wrote round41_42/round44 metrics")


if __name__ == "__main__":
    main()
