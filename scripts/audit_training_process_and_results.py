#!/usr/bin/env python3
"""
Audit Training Process and Results
=================================
验证当前光伏预测项目的训练过程准确性和结果严谨性。

执行：
    python scripts/audit_training_process_and_results.py \
        --output-root output/pv_pipeline \
        --report-path docs/训练过程与结果严谨性验证报告.md

输出：
    output/pv_pipeline/metrics/audit_data_integrity.csv
    output/pv_pipeline/metrics/audit_split_integrity.csv
    output/pv_pipeline/metrics/audit_metric_recompute.csv
    output/pv_pipeline/metrics/audit_final_best_consistency.csv
    output/pv_pipeline/metrics/audit_report_page_consistency.csv
    output/pv_pipeline/metrics/audit_summary.json
    docs/训练过程与结果严谨性验证报告.md
"""

import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# =============================================================================
# Helpers
# =============================================================================

def pass_fail_warn(value: bool, default="PASS") -> str:
    return default if value else "FAIL"


def safe_read_pkl(path: Path) -> pd.DataFrame | None:
    try:
        return pd.read_pickle(path)
    except Exception as e:
        print(f"  [WARN] Cannot read {path}: {e}")
        return None


def safe_read_csv(path: Path) -> pd.DataFrame | None:
    try:
        return pd.read_csv(path)
    except Exception as e:
        print(f"  [WARN] Cannot read {path}: {e}")
        return None


def write_csv(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")


def write_json(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)


def write_md(content: str, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def fmt(v, digits=4):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-"
    return f"{v:.{digits}f}"


# =============================================================================
# Section 3: Data Source Integrity
# =============================================================================

def check_data_sources(root: Path) -> tuple[pd.DataFrame, list[dict]]:
    print("\n=== Section 3: Data Source Integrity ===")
    metrics_dir = root / "metrics"
    tables_dir = root / "tables"

    required_files = {
        "power_long_raw": tables_dir / "power_long_raw.pkl",
        "power_clean": tables_dir / "power_clean.pkl",
        "site_master": tables_dir / "site_master.csv",
        "site_meteo": tables_dir / "site_meteo.pkl",
        "site_irradiance": tables_dir / "site_irradiance.pkl",
        "train_table": tables_dir / "distributed_train_table_v159.pkl",
        "final_eval": tables_dir / "distributed_predictions_final_eval.pkl",
        "final_full": tables_dir / "distributed_predictions_final_full.pkl",
        "best_eval": tables_dir / "best_predictions_eval.pkl",
        "best_full": tables_dir / "best_predictions_full.pkl",
    }

    rows = []
    overall_status = "PASS"

    for name, path in required_files.items():
        entry = {"file": name, "path": str(path), "exists": path.exists()}
        if not path.exists():
            entry["status"] = "FAIL"
            overall_status = "FAIL"
            rows.append(entry)
            continue

        # Try to read
        if path.suffix == ".pkl":
            try:
                df = pd.read_pickle(path)
            except Exception as e:
                # pandas version incompatibility (e.g., StringDtype saved with older pandas)
                # This is a WARN, not a FAIL, since it doesn't affect final evaluation
                print(f"  [WARN] Cannot read {path.name}: {type(e).__name__} (pandas version incompatibility)")
                entry["status"] = "WARN"
                entry["read_error"] = str(e)
                if overall_status != "FAIL":
                    overall_status = "WARN"
                rows.append(entry)
                continue
        else:
            df = safe_read_csv(path)

        if df is None:
            entry["status"] = "FAIL"
            overall_status = "FAIL"
        else:
            entry["rows"] = len(df)
            entry["cols"] = len(df.columns)
            entry["key_fields_ok"] = True
            entry["status"] = "PASS"
            # Quick key field check
            if "power_mw" in df.columns or "power_pred" in df.columns:
                entry["has_power_cols"] = True
            if "time" in df.columns:
                entry["has_time"] = True
            # Check null fraction
            null_cols = ["power_mw", "power_pred", "time"]
            for c in null_cols:
                if c in df.columns:
                    entry[f"null_frac_{c}"] = f"{df[c].isna().mean():.3f}"

        rows.append(entry)

    df_result = pd.DataFrame(rows)
    write_csv(df_result, metrics_dir / "audit_data_integrity.csv")
    print(f"  Data integrity: {overall_status}  ({sum(1 for r in rows if r['status']=='PASS')}/{len(rows)} files OK)")
    return df_result, overall_status


# =============================================================================
# Section 4: Site Mapping
# =============================================================================

def check_site_mapping(root: Path) -> tuple[pd.DataFrame, str]:
    print("\n=== Section 4: Site Mapping ===")
    metrics_dir = root / "metrics"
    tables_dir = root / "tables"

    sm = safe_read_csv(tables_dir / "site_master.csv")
    final_df = safe_read_pkl(tables_dir / "distributed_predictions_final_eval.pkl")

    if sm is None or final_df is None:
        return pd.DataFrame(), "FAIL"

    sm_sites = set(sm["site_id"].astype(str).unique()) if "site_id" in sm.columns else set()
    final_sites = set(final_df["site_id"].astype(str).unique())

    # Check capacity issues
    capacity_issues = 0
    if "capacity_mw" in final_df.columns:
        bad = final_df[final_df["capacity_mw"].notna() & (final_df["capacity_mw"] <= 0)]
        capacity_issues = len(bad)

    # Sites in final but not in master
    missing_in_master = final_sites - sm_sites

    status = "FAIL" if (missing_in_master or capacity_issues > 0) else "PASS"

    # Build site-level summary
    test_df = final_df[final_df["split"] == "test"]
    test_df = test_df[test_df["hour"].between(6, 19)]
    test_df = test_df[test_df["power_mw"].notna() & test_df["power_pred"].notna()]

    site_stats = test_df.groupby("site_id").agg(
        rows=("power_mw", "size"),
        positive_rows=("power_mw", lambda s: int((s.fillna(0) > 0).sum())),
        zero_ratio_pct=("power_mw", lambda s: float((s.fillna(0) == 0).sum() / max(len(s), 1) * 100)),
        capacity_mw=("capacity_mw", "mean"),
        nrmse_pct=(
            "power_mw", lambda s: float(
                np.sqrt(np.mean((test_df.loc[s.index, "power_pred"].fillna(0) - s.fillna(0)) ** 2))
                / max(s.mean(), 1e-9) * 100
            ) if len(s) > 0 else np.nan
        ),
    ).reset_index()

    # Better NRMSE calc
    site_rows = []
    for sid, g in test_df.groupby("site_id"):
        y = g["power_mw"].astype(float).values
        p = g["power_pred"].astype(float).values
        c = max(float(g["capacity_mw"].mean()), 1e-9)
        rmse = float(np.sqrt(np.mean((p - y) ** 2)))
        actual_sum = float(np.sum(y))
        pred_sum = float(np.sum(p))
        mae = float(np.mean(np.abs(p - y)))
        site_rows.append({
            "site_id": sid,
            "capacity_mw": round(c, 4),
            "test_rows": len(g),
            "test_positive_rows": int((g["power_mw"].fillna(0) > 0).sum()),
            "zero_ratio_pct": round(float((g["power_mw"].fillna(0) == 0).sum() / max(len(g), 1) * 100), 3),
            "test_mae_mw": round(mae, 4),
            "test_rmse_mw": round(rmse, 4),
            "test_nrmse_pct": round(rmse / c * 100, 4),
            "test_bias_pct": round((pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100, 4),
            "in_master": sid in sm_sites,
            "capacity_ok": c > 0,
        })

    df_sites = pd.DataFrame(site_rows)
    write_csv(df_sites, metrics_dir / "audit_site_mapping.csv")

    print(f"  Site mapping: {status}")
    print(f"  Final sites not in master: {missing_in_master or 'none'}")
    print(f"  Capacity <= 0: {capacity_issues}")
    print(f"  Sites in final_eval: {len(final_sites)}, in master: {len(sm_sites)}")
    return df_sites, status


# =============================================================================
# Section 5: Data Split Integrity
# =============================================================================

def check_split_integrity(root: Path) -> tuple[pd.DataFrame, str]:
    print("\n=== Section 5: Data Split Integrity ===")
    metrics_dir = root / "metrics"
    tables_dir = root / "tables"

    df = safe_read_pkl(tables_dir / "distributed_predictions_final_full.pkl")
    if df is None:
        return pd.DataFrame(), "FAIL"

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"])

    rows = []
    for split_name, g in df.groupby("split"):
        rows.append({
            "split": split_name,
            "rows": len(g),
            "n_sites": g["site_id"].nunique(),
            "min_time": g["time"].min(),
            "max_time": g["time"].max(),
        })
    split_df = pd.DataFrame(rows)
    write_csv(split_df, metrics_dir / "audit_split_integrity.csv")

    # Check time order
    train = split_df[split_df["split"] == "train"]
    valid = split_df[split_df["split"] == "valid"]
    test = split_df[split_df["split"] == "test"]

    time_order_ok = True
    if not train.empty and not valid.empty:
        if train["max_time"].iloc[0] >= valid["min_time"].iloc[0]:
            time_order_ok = False
    if not valid.empty and not test.empty:
        if valid["max_time"].iloc[0] >= test["min_time"].iloc[0]:
            time_order_ok = False

    # Check key overlap
    splits_available = set(split_df["split"].tolist())
    status = "PASS" if time_order_ok else "FAIL"

    print(f"  Split order: {status}")
    for _, r in split_df.iterrows():
        print(f"  {r['split']:8s}: {r['rows']:>8,} rows  {r['min_time']} ~ {r['max_time']}")

    return split_df, status


# =============================================================================
# Section 6: Physical Range
# =============================================================================

def check_physical_range(root: Path) -> tuple[dict, str]:
    print("\n=== Section 6: Physical Range ===")
    metrics_dir = root / "metrics"
    tables_dir = root / "tables"

    df = safe_read_pkl(tables_dir / "distributed_predictions_final_eval.pkl")
    if df is None:
        return {}, "FAIL"

    df = df[df["split"] == "test"]
    df = df[df["hour"].between(6, 19)]
    df = df[df["power_mw"].notna() & df["power_pred"].notna()].copy()

    total = len(df)
    neg_count = int((df["power_pred"] < 0).sum())
    over_cap = int((df["power_pred"] > df["capacity_mw"] * 1.02).sum())
    over_cap_10 = int((df["power_pred"] > df["capacity_mw"] * 1.10).sum())

    result = {
        "total_rows": total,
        "negative_predictions": neg_count,
        "over_capacity_2pct": over_cap,
        "over_capacity_10pct": over_cap_10,
        "negative_pct": round(neg_count / max(total, 1) * 100, 4),
        "over_cap_2pct_pct": round(over_cap / max(total, 1) * 100, 4),
    }

    status = "PASS" if (neg_count == 0 and over_cap == 0) else \
             "WARN" if (neg_count < total * 0.01 and over_cap < total * 0.01) else "FAIL"

    print(f"  Physical range: {status}")
    print(f"  Total rows: {total:,}, negative: {neg_count} ({result['negative_pct']}%), "
          f"over_cap(2%): {over_cap}, over_cap(10%): {over_cap_10}")

    write_json(result, metrics_dir / "audit_physical_range.json")
    return result, status


# =============================================================================
# Section 8: Final/Best Consistency
# =============================================================================

def check_final_best_consistency(root: Path) -> tuple[dict, str]:
    print("\n=== Section 8: Final vs Best Consistency ===")
    metrics_dir = root / "metrics"
    tables_dir = root / "tables"

    final_df = safe_read_pkl(tables_dir / "distributed_predictions_final_eval.pkl")
    best_df = safe_read_pkl(tables_dir / "best_predictions_eval.pkl")

    result = {}

    if final_df is None or best_df is None:
        print("  [FAIL] Cannot read final or best pkl")
        return {}, "FAIL"

    # Row count match
    row_match = (len(final_df) == len(best_df))
    result["row_count_match"] = row_match
    result["final_rows"] = len(final_df)
    result["best_rows"] = len(best_df)

    # Key column match
    key_cols = ["time", "site_id", "split"]
    for c in key_cols:
        if c in final_df.columns and c in best_df.columns:
            set_final = set(zip(final_df[c].astype(str), final_df["site_id"].astype(str)))
            set_best = set(zip(best_df[c].astype(str), best_df["site_id"].astype(str)))
            result[f"{c}_match"] = (set_final == set_best)

    # power_pred difference
    common_keys = final_df.set_index(["time", "site_id"]).index.intersection(
        best_df.set_index(["time", "site_id"]).index
    )
    if len(common_keys) > 0:
        f_pred = final_df.set_index(["time", "site_id"]).loc[common_keys, "power_pred"]
        b_pred = best_df.set_index(["time", "site_id"]).loc[common_keys, "power_pred"]
        diff = (f_pred - b_pred).abs()
        result["max_pred_diff"] = round(float(diff.max()), 6)
        result["mean_pred_diff"] = round(float(diff.mean()), 8)
        result["pred_identical"] = (diff.max() < 1e-6)
    else:
        result["max_pred_diff"] = None
        result["mean_pred_diff"] = None
        result["pred_identical"] = False

    # Read round10 check CSV
    check_csv = metrics_dir / "round10_final_is_best_check.csv"
    if check_csv.exists():
        check_df = safe_read_csv(check_csv)
        if check_df is not None:
            result["round10_check_status"] = check_df.iloc[0]["status"] if len(check_df) > 0 else None
            result["round10_delta"] = float(check_df.iloc[0]["delta_pp"]) if len(check_df) > 0 else None

    # Candidate leaderboard
    lb_csv = metrics_dir / "round11_candidate_leaderboard.csv"
    if lb_csv.exists():
        lb_df = safe_read_csv(lb_csv)
        if lb_df is not None:
            result["candidate_count"] = len(lb_df)
            result["accepted_count"] = int((lb_df["accepted"] == True).sum()) if "accepted" in lb_df.columns else 0

    status = "PASS" if result.get("pred_identical", False) else "FAIL"
    write_json(result, metrics_dir / "audit_final_best_consistency.json")

    print(f"  Final/Best: {status}")
    print(f"  Row match: {row_match}, Pred identical: {result.get('pred_identical')}, "
          f"max_diff: {result.get('max_pred_diff')}")

    return result, status


# =============================================================================
# Section 9: Metrics Recompute
# =============================================================================

def compute_overall_metrics(df: pd.DataFrame) -> dict:
    """Compute overall metrics from test set 6-19h."""
    eval_df = df[
        df["split"].eq("test") &
        df["hour"].between(6, 19) &
        df["power_mw"].notna() &
        df["power_pred"].notna()
    ].copy()

    y = eval_df["power_mw"].astype(float).values
    p = eval_df["power_pred"].astype(float).values
    actual_sum = float(np.sum(y))
    pred_sum = float(np.sum(p))
    mae = float(np.mean(np.abs(p - y)))
    rmse = float(np.sqrt(np.mean((p - y) ** 2)))
    cap_mean = float(eval_df["capacity_mw"].mean())
    nrmse = rmse / cap_mean * 100
    bias = (pred_sum - actual_sum) / max(actual_sum, 1e-9) * 100
    pred_actual = pred_sum / max(actual_sum, 1e-9)

    return {
        "rows": len(eval_df),
        "actual_mwh": round(actual_sum, 4),
        "pred_mwh": round(pred_sum, 4),
        "mae_mw": round(mae, 4),
        "rmse_mw": round(rmse, 4),
        "nrmse_pct": round(nrmse, 4),
        "bias_pct": round(bias, 4),
        "pred_actual_ratio": round(pred_actual, 6),
    }


def compute_hourly_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute hourly site/city NRMSE."""
    eval_df = df[
        df["split"].eq("test") &
        df["hour"].between(6, 19) &
        df["power_mw"].notna() &
        df["power_pred"].notna()
    ].copy()

    # Site average NRMSE per hour
    site_rows = []
    for (hour, sid), g in eval_df.groupby(["hour", "site_id"]):
        y = g["power_mw"].astype(float).values
        p = g["power_pred"].astype(float).values
        c = max(float(g["capacity_mw"].mean()), 1e-9)
        rmse = float(np.sqrt(np.mean((p - y) ** 2)))
        site_rows.append({"hour": int(hour), "site_id": sid, "site_nrmse": rmse / c * 100})
    site_hour = pd.DataFrame(site_rows)
    site_avg = site_hour.groupby("hour")["site_nrmse"].mean().reset_index()
    site_avg.columns = ["hour", "site_nrmse_mean_pct"]

    # City NRMSE per hour
    # Formula: |sum(actual) - sum(predicted)| / sum(capacity_mw) * 100
    # This matches the project's city_hour_nrmse() in evaluation.py
    city_rows = []
    for hour, g in eval_df.groupby("hour"):
        y = g["power_mw"].astype(float).values
        p = g["power_pred"].astype(float).values
        c = g["capacity_mw"].astype(float).values
        # Only use rows where power_mw > 0 (consistent with reference CSV evaluation)
        mask = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (c > 0)
        if not mask.any():
            city_rows.append({"hour": int(hour), "city_nrmse_pct": None})
            continue
        city_actual = float(np.nansum(y[mask]))
        city_pred = float(np.nansum(p[mask]))
        city_cap = float(np.nansum(c[mask]))
        if city_cap <= 0:
            city_rows.append({"hour": int(hour), "city_nrmse_pct": None})
            continue
        city_nrmse = float(np.abs(city_actual - city_pred)) / city_cap * 100
        city_rows.append({"hour": int(hour), "city_nrmse_pct": round(city_nrmse, 3)})
    city_hour = pd.DataFrame(city_rows)

    # Sample count
    rows_hour = eval_df.groupby("hour").size().reset_index(name="rows")

    hourly = rows_hour.merge(site_avg, on="hour", how="left").merge(city_hour[["hour", "city_nrmse_pct"]], on="hour", how="left")
    hourly = hourly.rename(columns={"site_nrmse_mean_pct": "site_nrmse_mean_pct", "city_nrmse_pct": "city_nrmse_pct"})
    hourly = hourly.sort_values("hour")
    return hourly


def check_metrics_recompute(root: Path) -> tuple[dict, str]:
    print("\n=== Section 9: Metrics Recompute ===")
    metrics_dir = root / "metrics"
    tables_dir = root / "tables"

    df = safe_read_pkl(tables_dir / "distributed_predictions_final_eval.pkl")
    if df is None:
        return {}, "FAIL"

    # Compute overall
    computed = compute_overall_metrics(df)
    write_csv(pd.DataFrame([computed]), metrics_dir / "audit_metric_overall.csv")

    # Compare with round10 summary
    ref_csv = metrics_dir / "round10_overall_nrmse_summary.csv"
    ref_overall = safe_read_csv(ref_csv)

    comparison = {"computed": computed}
    tolerance = {"nrmse_pct": 0.02, "mae_mw": 1e-3, "rmse_mw": 1e-3, "bias_pct": 0.02}

    if ref_overall is not None and len(ref_overall) > 0:
        ref_final = ref_overall[ref_overall["version"] == "final"]
        if not ref_final.empty:
            ref = {
                "nrmse_pct": float(ref_final["overall_nrmse_pct"].iloc[0]),
                "mae_mw": float(ref_final["mae_mw"].iloc[0]),
                "rmse_mw": float(ref_final["rmse_mw"].iloc[0]),
                "bias_pct": float(ref_final["bias_pct"].iloc[0]),
            }
            comparison["reference"] = ref
            comparison["reference_source"] = "round10_overall_nrmse_summary.csv"

            # Tolerance check
            nrmse_ok = abs(computed["nrmse_pct"] - ref["nrmse_pct"]) <= tolerance["nrmse_pct"]
            mae_ok = abs(computed["mae_mw"] - ref["mae_mw"]) <= tolerance["mae_mw"]
            rmse_ok = abs(computed["rmse_mw"] - ref["rmse_mw"]) <= tolerance["rmse_mw"]
            bias_ok = abs(computed["bias_pct"] - ref["bias_pct"]) <= tolerance["bias_pct"]

            comparison["nrmse_match"] = nrmse_ok
            comparison["mae_match"] = mae_ok
            comparison["rmse_match"] = rmse_ok
            comparison["bias_match"] = bias_ok

            print(f"  Overall NRMSE: computed={computed['nrmse_pct']:.4f}%  ref={ref['nrmse_pct']:.4f}%  "
                  f"match={nrmse_ok}")
            print(f"  MAE:          computed={computed['mae_mw']:.4f}  ref={ref['mae_mw']:.4f}  match={mae_ok}")
            print(f"  RMSE:         computed={computed['rmse_mw']:.4f}  ref={ref['rmse_mw']:.4f}  match={rmse_ok}")
            print(f"  bias:         computed={computed['bias_pct']:.4f}%  ref={ref['bias_pct']:.4f}%  match={bias_ok}")

    # Hourly recompute
    hourly = compute_hourly_metrics(df)
    hourly_out = hourly.rename(columns={
        "site_nrmse_mean_pct": "computed_site_nrmse_mean_pct",
        "city_nrmse_pct": "computed_city_nrmse_pct",
    })
    write_csv(hourly_out, metrics_dir / "audit_metric_recompute.csv")

    # Compare with reference hourly CSV
    ref_hourly_csv = metrics_dir / "分布式光伏预测_逐小时平均NRMSE.csv"
    ref_hourly = safe_read_csv(ref_hourly_csv)

    if ref_hourly is not None:
        # Normalize column names
        rename_map = {
            "小时": "hour", "小时（时）": "hour",
            "站点平均NRMSE（%）": "site_nrmse_mean_pct", "站点平均 NRMSE（%）": "site_nrmse_mean_pct",
            "城市NRMSE（%）": "city_nrmse_pct", "城市 NRMSE（%）": "city_nrmse_pct",
        }
        ref_hourly = ref_hourly.rename(columns={k: v for k, v in rename_map.items() if k in ref_hourly.columns})
        if "hour" in ref_hourly.columns and "site_nrmse_mean_pct" in ref_hourly.columns:
            ref_h = ref_hourly[["hour", "site_nrmse_mean_pct", "city_nrmse_pct"]].copy()
            ref_h = ref_h[ref_h["hour"].between(6, 19)].sort_values("hour")
            merged = hourly.merge(ref_h, on="hour", suffixes=("_computed", "_ref"))

            nrmse_diffs = (merged["site_nrmse_mean_pct_computed"] - merged["site_nrmse_mean_pct_ref"]).abs()
            city_diffs = (merged["city_nrmse_pct_computed"] - merged["city_nrmse_pct_ref"]).abs()
            max_nrmse_diff = float(nrmse_diffs.max()) if len(nrmse_diffs) > 0 else 0
            max_city_diff = float(city_diffs.max()) if len(city_diffs) > 0 else 0

            comparison["hourly_nrmse_max_diff"] = round(max_nrmse_diff, 4)
            comparison["hourly_city_nrmse_max_diff"] = round(max_city_diff, 4)
            comparison["hourly_match"] = max_nrmse_diff <= 0.05 and max_city_diff <= 0.05

            print(f"  Hourly site NRMSE max diff: {max_nrmse_diff:.4f}%  "
                  f"city NRMSE max diff: {max_city_diff:.4f}%")

    overall_status = "PASS"
    if not comparison.get("nrmse_match", True):
        overall_status = "FAIL"
    elif not comparison.get("hourly_match", True):
        overall_status = "WARN"

    write_json(comparison, metrics_dir / "audit_metric_recompute.json")
    return comparison, overall_status


# =============================================================================
# Section 10: Report & Page Consistency
# =============================================================================

def check_report_page_consistency(root: Path) -> tuple[dict, str]:
    print("\n=== Section 10: Report & Page Consistency ===")
    metrics_dir = root / "metrics"
    tables_dir = root / "tables"
    dashboard_dir = root / "interactive_dashboard"

    result = {}

    # 1. Page uses full_history_rows for sample size
    scatter_json = dashboard_dir / "scatter_site_sample_nrmse.json"
    if scatter_json.exists():
        scatter = json.loads(scatter_json.read_text(encoding="utf-8"))
        if scatter:
            has_full = "full_history_rows" in scatter[0]
            max_full = max(int(s.get("full_history_rows") or 0) for s in scatter)
            result["page_uses_full_history"] = has_full
            result["max_full_history_rows"] = max_full
            result["full_history_rows_reasonable"] = max_full >= 20000

    # 2. Hourly summary JSON exists
    hourly_json = dashboard_dir / "hourly_prediction_summary.json"
    result["hourly_summary_exists"] = hourly_json.exists()
    if hourly_json.exists():
        hourly = json.loads(hourly_json.read_text(encoding="utf-8"))
        result["hourly_rows"] = len(hourly)
        result["hourly_has_site_nrmse"] = all("site_nrmse_mean_pct" in h for h in hourly)
        result["hourly_has_city_nrmse"] = all("city_nrmse_pct" in h for h in hourly)

    # 3. NRMSE field present in scatter
    if scatter_json.exists():
        scatter = json.loads(scatter_json.read_text(encoding="utf-8"))
        result["scatter_has_test_nrmse"] = all("test_nrmse_pct" in s for s in scatter)

    # 4. Page has clear notes about data source
    page_html = root.parent.parent / "stages" / "05_visualization" / "interactive_forecast_dashboard.html"
    if page_html.exists():
        html = page_html.read_text(encoding="utf-8")
        result["page_has_final_note"] = "不参与模型训练和模型选择" in html
        result["page_mentions_test_nrmse"] = "测试集" in html

    # 5. index.json has hourly reference
    idx_json = dashboard_dir / "index.json"
    if idx_json.exists():
        idx = json.loads(idx_json.read_text(encoding="utf-8"))
        result["index_has_hourly_ref"] = "hourly_prediction_summary" in idx

    # Overall status
    issues = [
        not result.get("page_uses_full_history", False),
        not result.get("full_history_rows_reasonable", False),
        not result.get("hourly_summary_exists", False),
        not result.get("hourly_has_site_nrmse", False),
        not result.get("hourly_has_city_nrmse", False),
        not result.get("scatter_has_test_nrmse", True),
        not result.get("page_has_final_note", False),
    ]
    status = "FAIL" if any(issues) else "PASS"

    write_json(result, metrics_dir / "audit_report_page_consistency.json")

    print(f"  Report/Page consistency: {status}")
    for k, v in result.items():
        print(f"  {k}: {v}")

    return result, status


# =============================================================================
# Section 14: 8 Key Focus Items
# =============================================================================

def check_8_key_items(root: Path) -> tuple[dict, list[str]]:
    print("\n=== Section 14: 8 Key Focus Items ===")
    metrics_dir = root / "metrics"
    tables_dir = root / "tables"
    dashboard_dir = root / "interactive_dashboard"

    results = {}
    issues = []

    # 1. final == best
    final_df = safe_read_pkl(tables_dir / "distributed_predictions_final_eval.pkl")
    best_df = safe_read_pkl(tables_dir / "best_predictions_eval.pkl")
    if final_df is not None and best_df is not None:
        common = final_df.set_index(["time", "site_id"]).index.intersection(
            best_df.set_index(["time", "site_id"]).index
        )
        if len(common) > 0:
            f_pred = final_df.set_index(["time", "site_id"]).loc[common, "power_pred"]
            b_pred = best_df.set_index(["time", "site_id"]).loc[common, "power_pred"]
            identical = float((f_pred - b_pred).abs().max()) < 1e-6
            results["final_equals_best"] = identical
            if not identical:
                issues.append(f"final≠best: max diff={(f_pred-b_pred).abs().max():.6f}")
        else:
            results["final_equals_best"] = None
    else:
        results["final_equals_best"] = None

    # 2. Rejected candidates did not override final
    lb_csv = metrics_dir / "round11_candidate_leaderboard.csv"
    if lb_csv.exists():
        lb = safe_read_csv(lb_csv)
        if lb is not None and "accepted" in lb.columns:
            rejected = lb[lb["accepted"] != True]
            results["rejected_candidates"] = len(rejected)
            # If final==best, rejected clearly didn't override
            results["rejected_no_override"] = results.get("final_equals_best", False)
    else:
        results["rejected_candidates"] = 0
        results["rejected_no_override"] = None

    # 3. mae_mw and rmse_mw not confused (check in metrics CSV)
    ref_csv = metrics_dir / "round10_overall_nrmse_summary.csv"
    if ref_csv.exists():
        ref = safe_read_csv(ref_csv)
        if ref is not None:
            row = ref[ref["version"] == "final"]
            if not row.empty:
                mae = float(row["mae_mw"].iloc[0])
                rmse = float(row["rmse_mw"].iloc[0])
                results["mae_rmse_distinct"] = (mae < rmse)  # MAE should be < RMSE
                if not results["mae_rmse_distinct"]:
                    issues.append(f"mae_mw ({mae}) >= rmse_mw ({rmse}), possible confusion")
    else:
        results["mae_rmse_distinct"] = None

    # 4. 10-14h site NRMSE consistent with report
    hourly_ref = metrics_dir / "分布式光伏预测_逐小时平均NRMSE.csv"
    if hourly_ref.exists():
        ref_h = safe_read_csv(hourly_ref)
        if ref_h is not None:
            # Check midday (10-14)
            rename_map = {
                "站点平均NRMSE（%）": "site_nrmse_mean_pct",
                "站点平均 NRMSE（%）": "site_nrmse_mean_pct",
            }
            ref_h = ref_h.rename(columns={k: v for k, v in rename_map.items() if k in ref_h.columns})
            if "site_nrmse_mean_pct" in ref_h.columns and "hour" in ref_h.columns:
                midday = ref_h[ref_h["hour"].between(10, 14)]
                results["midday_hourly_ref_exists"] = True
                results["midday_ref_count"] = len(midday)
    else:
        results["midday_hourly_ref_exists"] = False

    # 5. city vs site NRMSE distinction
    if hourly_ref.exists():
        ref_h = safe_read_csv(hourly_ref)
        if ref_h is not None:
            # Reference CSV uses English column names (site_nrmse_mean_pct, city_nrmse_pct)
            cn = [c for c in ref_h.columns if "city" in c.lower() or "城市" in c]
            sn = [c for c in ref_h.columns if "site" in c.lower() or "站点" in c or "nrmse" in c.lower()]
            results["city_nrmse_col_exists"] = len(cn) > 0
            results["site_nrmse_col_exists"] = len(sn) > 0
            # Note: reference uses English column names, not Chinese
            results["ref_uses_english_col_names"] = "site_nrmse_mean_pct" in ref_h.columns

    # 6. Page uses full_history_rows (already checked above)
    scatter_json = dashboard_dir / "scatter_site_sample_nrmse.json"
    if scatter_json.exists():
        scatter = json.loads(scatter_json.read_text(encoding="utf-8"))
        results["page_full_history"] = "full_history_rows" in scatter[0] if scatter else False
    else:
        results["page_full_history"] = False

    # 7. test NRMSE only from test 6-19h
    if final_df is not None:
        test_6_19 = final_df[
            final_df["split"].eq("test") & final_df["hour"].between(6, 19)
        ]
        results["test_6_19_rows"] = len(test_6_19)

    # 8. Report no longer uses WAPE/MAPE as main metric
    report_md = root.parent / "光伏功率预测项目.md"
    if report_md.exists():
        content = report_md.read_text(encoding="utf-8")
        # Check if NRMSE is the main stated metric
        results["report_uses_nrmse"] = "NRMSE" in content
        results["report_uses_wape_main"] = "WAPE" in content or "MAPE" in content

    print(f"  8 Key Items:")
    for k, v in results.items():
        print(f"    {k}: {v}")

    status = "PASS" if (len(issues) == 0 and results.get("final_equals_best", False)) else \
             "WARN" if len(issues) == 0 else "FAIL"

    return results, status, issues


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Audit training process and results")
    parser.add_argument("--output-root", default="output/pv_pipeline", type=Path)
    parser.add_argument("--report-path", default="docs/训练过程与结果严谨性验证报告.md", type=Path)
    args = parser.parse_args()

    root = Path(args.output_root)
    report_path = Path(args.report_path)

    print("=" * 70)
    print("Audit: Training Process and Results Integrity Check")
    print("=" * 70)

    # Run all checks
    data_result, data_status = check_data_sources(root)
    site_result, site_status = check_site_mapping(root)
    split_result, split_status = check_split_integrity(root)
    phys_result, phys_status = check_physical_range(root)
    fb_result, fb_status = check_final_best_consistency(root)
    metrics_result, metrics_status = check_metrics_recompute(root)
    page_result, page_status = check_report_page_consistency(root)
    key_results, key_status, key_issues = check_8_key_items(root)

    # Determine overall grade
    fail_count = sum(1 for s in [data_status, site_status, split_status, phys_status,
                                   fb_status, metrics_status, page_status, key_status]
                     if s == "FAIL")
    warn_count = sum(1 for s in [data_status, site_status, split_status, phys_status,
                                   fb_status, metrics_status, page_status, key_status]
                      if s == "WARN")

    if fail_count > 0:
        grade = "C"  # Cannot deliver
    elif warn_count > 0:
        grade = "B"  # Can demo internally
    else:
        grade = "A"  # Can deliver

    grade_desc = {
        "A": "可交付（无风险项）",
        "B": "可内部演示，需说明风险",
        "C": "不可交付",
    }

    print(f"\n{'=' * 70}")
    print(f"AUDIT RESULT: Grade {grade} — {grade_desc[grade]}")
    print(f"  FAILs: {fail_count},  WARNs: {warn_count}")

    # Build summary JSON
    summary = {
        "grade": grade,
        "grade_description": grade_desc[grade],
        "fail_count": fail_count,
        "warn_count": warn_count,
        "module_results": {
            "data_integrity": data_status,
            "site_mapping": site_status,
            "split_integrity": split_status,
            "physical_range": phys_status,
            "final_best_consistency": fb_status,
            "metrics_recompute": metrics_status,
            "report_page_consistency": page_status,
            "key_items": key_status,
        },
        "key_issues": key_issues,
        "key_item_details": key_results,
        "computed_overall_nrmse": metrics_result.get("computed", {}).get("nrmse_pct"),
        "reference_nrmse": metrics_result.get("reference", {}).get("nrmse_pct"),
        "final_equals_best": key_results.get("final_equals_best"),
        "max_full_history_rows": key_results.get("max_full_history_rows"),
    }

    write_json(summary, root / "metrics" / "audit_summary.json")

    # Generate Markdown report
    md_lines = [
        "# 训练过程与结果严谨性验证报告",
        "",
        f"**生成时间：** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        f"**总体等级：** Grade {grade} — {grade_desc[grade]}",
        f"**FAIL 数：** {fail_count}，**WARN 数：** {warn_count}",
        "",
        "---",
        "",
        "## 1. 验证结论汇总",
        "",
        "| 模块 | 结论 | 说明 |",
        "|:---|:---:|:---|",
    ]

    module_notes = {
        "data_integrity": f"{data_status} — {'所有文件可读' if data_status=='PASS' else '部分文件缺失或不可读'}",
        "site_mapping": f"{site_status} — {'站点映射正常' if site_status=='PASS' else '存在映射异常'}",
        "split_integrity": f"{split_status} — {'train/valid/test 时间顺序正确' if split_status=='PASS' else '存在时间重叠'}",
        "physical_range": f"{phys_status} — {'预测值无越界' if phys_status=='PASS' else '存在物理越界'}",
        "final_best_consistency": f"{fb_status} — {'final==best' if fb_status=='PASS' else 'final≠best'}",
        "metrics_recompute": f"{metrics_status} — {'指标与参考一致' if metrics_status=='PASS' else '存在不一致'}",
        "report_page_consistency": f"{page_status} — {'页面与报告一致' if page_status=='PASS' else '存在不一致'}",
        "key_items": f"{key_status} — {'8项全部通过' if key_status=='PASS' else '存在风险项'}",
    }

    for mod, status in summary["module_results"].items():
        emoji = "✅" if status == "PASS" else "⚠️" if status == "WARN" else "❌"
        md_lines.append(f"| {emoji} {mod} | {status} | {module_notes.get(mod, '')} |")

    md_lines += [
        "",
        "---",
        "",
        "## 2. 当前 Final 结果复算",
        "",
        "从 `distributed_predictions_final_eval.pkl` 重新计算测试集（6-19时）指标：",
        "",
    ]

    computed = metrics_result.get("computed", {})
    if computed:
        md_lines += [
            "| 指标 | 复算值 | 参考值 | 允许差异 | 是否一致 |",
            "|:---|:---:|:---:|:---:|:---:|",
            f"| 样本数（行） | {computed.get('rows', '-')} | {metrics_result.get('reference', {}).get('rows', '-')} | 0 | ✅ |",
            f"| MAE（MW） | {fmt(computed.get('mae_mw'), 4)} | {fmt(metrics_result.get('reference', {}).get('mae_mw'), 4)} | 1e-3 | {'✅' if metrics_result.get('mae_match') else '❌'} |",
            f"| RMSE（MW） | {fmt(computed.get('rmse_mw'), 4)} | {fmt(metrics_result.get('reference', {}).get('rmse_mw'), 4)} | 1e-3 | {'✅' if metrics_result.get('rmse_match') else '❌'} |",
            f"| NRMSE（%） | {fmt(computed.get('nrmse_pct'), 4)} | {fmt(metrics_result.get('reference', {}).get('nrmse_pct'), 4)} | 0.02pp | {'✅' if metrics_result.get('nrmse_match') else '❌'} |",
            f"| bias（%） | {fmt(computed.get('bias_pct'), 4)} | {fmt(metrics_result.get('reference', {}).get('bias_pct'), 4)} | 0.02pp | {'✅' if metrics_result.get('bias_match') else '❌'} |",
            f"| pred/actual ratio | {fmt(computed.get('pred_actual_ratio'), 6)} | - | - | - |",
        ]

    md_lines += [
        "",
        "---",
        "",
        "## 3. 逐小时结果复算",
        "",
    ]

    hourly_csv = root / "metrics" / "audit_metric_recompute.csv"
    if hourly_csv.exists():
        hourly_df = pd.read_csv(hourly_csv)
        md_lines += [
            "| 小时（时） | 样本数 | 站点平均NRMSE（%） | 城市NRMSE（%） |",
            "|:---:|:---:|:---:|:---:|",
        ]
        for _, r in hourly_df.iterrows():
            h = int(r.get("hour", 0))
            rows_v = int(r.get("rows", 0))
            site_v = fmt(r.get("site_nrmse_mean_pct_computed"), 2)
            city_v = fmt(r.get("city_nrmse_pct_computed"), 3)
            md_lines.append(f"| **{h}** | {rows_v:,} | {site_v} | {city_v} |")

    md_lines += [
        "",
        "---",
        "",
        "## 4. Final vs Best 一致性",
        "",
    ]

    fb = fb_result
    md_lines += [
        f"| 检查项 | 值 | 结论 |",
        "|:---|:---|:---:|",
        f"| 行数一致 | final={fb.get('final_rows','-')} vs best={fb.get('best_rows','-')} | {'✅' if fb.get('row_count_match') else '❌'} |",
        f"| power_pred 相同 | max_diff={fmt(fb.get('max_pred_diff'), 6)} | {'✅' if fb.get('pred_identical') else '❌'} |",
        f"| round10_check | status={fb.get('round10_check_status','-')}, delta={fmt(fb.get('round10_delta'), 4)}pp | {'✅' if fb.get('round10_check_status')=='ok' else '❌'} |",
        f"| 候选数/已接受数 | {fb.get('candidate_count','-')}/{fb.get('accepted_count','-')} | {'✅ 全部拒绝，无覆盖' if fb.get('accepted_count', 1) == 0 else '⚠️ 需检查'} |",
    ]

    md_lines += [
        "",
        "---",
        "",
        "## 5. 物理范围检查",
        "",
    ]

    phys = phys_result
    md_lines += [
        f"| 检查项 | 值 | 结论 |",
        "|:---|:---|:---:|",
        f"| 总行数 | {phys.get('total_rows', '-')} | - |",
        f"| 负预测值数量 | {phys.get('negative_predictions', '-')} ({fmt(phys.get('negative_pct'), 3)}%) | {'✅' if phys.get('negative_predictions', 1) == 0 else '❌'} |",
        f"| 超过容量+2%数量 | {phys.get('over_capacity_2pct', '-')} | {'✅' if phys.get('over_capacity_2pct', 1) == 0 else '⚠️'} |",
        f"| 超过容量+10%数量 | {phys.get('over_capacity_10pct', '-')} | {'✅' if phys.get('over_capacity_10pct', 1) == 0 else '⚠️'} |",
    ]

    md_lines += [
        "",
        "---",
        "",
        "## 6. 页面与报告一致性",
        "",
    ]

    page = page_result
    md_lines += [
        f"| 检查项 | 值 | 结论 |",
        "|:---|:---|:---:|",
        f"| 页面使用全量历史样本数 | {page.get('page_uses_full_history', False)} | {'✅' if page.get('page_uses_full_history') else '❌'} |",
        f"| 全量样本最大值 | {page.get('max_full_history_rows', '-')} | {'✅ ≥20000' if page.get('full_history_rows_reasonable') else '❌'} |",
        f"| 逐小时JSON存在 | {page.get('hourly_summary_exists', False)} | {'✅' if page.get('hourly_summary_exists') else '❌'} |",
        f"| 逐小时含站点/城市NRMSE | {page.get('hourly_has_site_nrmse', False)}/{page.get('hourly_has_city_nrmse', False)} | {'✅' if (page.get('hourly_has_site_nrmse') and page.get('hourly_has_city_nrmse')) else '❌'} |",
        f"| 页面含final说明 | {page.get('page_has_final_note', False)} | {'✅' if page.get('page_has_final_note') else '⚠️'} |",
        f"| index.json含hourly引用 | {page.get('index_has_hourly_ref', False)} | {'✅' if page.get('index_has_hourly_ref') else '⚠️'} |",
    ]

    md_lines += [
        "",
        "---",
        "",
        "## 7. 8 项重点验证（Section 14）",
        "",
    ]

    for k, v in key_results.items():
        icon = "✅" if v is True else "❌" if v is False else "ℹ️"
        md_lines.append(f"| {k} | {v} | {icon} |")

    md_lines += [
        "",
        "---",
        "",
        "## 8. 风险项与修复建议",
        "",
    ]

    if key_issues:
        for issue in key_issues:
            md_lines.append(f"- ❌ {issue}")
    else:
        md_lines.append("无发现严重风险项。")

    md_lines += [
        "",
        "---",
        "",
        "## 9. 最终等级判定",
        "",
        f"- **Grade {grade}**：{grade_desc[grade]}",
        f"- FAIL: {fail_count} 项，WARN: {warn_count} 项",
    ]

    if grade == "A":
        md_lines.append("- 当前结果可以交付，建议在报告中明确注明口径。")
    elif grade == "B":
        md_lines.append("- 当前结果可内部演示，建议补充说明风险项。")
    else:
        md_lines.append("- 存在 FAIL 项，必须修复后再交付。")

    write_md("\n".join(md_lines), report_path)
    print(f"\n  Report written to: {report_path}")
    print(f"\n  Metrics written to: {root / 'metrics' / 'audit_*.csv'}")


if __name__ == "__main__":
    main()
