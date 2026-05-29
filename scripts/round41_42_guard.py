from pathlib import Path
import shutil
import pandas as pd


ROOT = Path("output/pv_pipeline")
TABLE_DIR = ROOT / "tables"
METRIC_DIR = ROOT / "metrics"


def find_final_pkl():
    candidates = sorted(TABLE_DIR.glob("distributed_predictions_final_round*.pkl"))
    if candidates:
        return candidates[-1]
    return TABLE_DIR / "distributed_predictions_final_full.pkl"


def main():
    pkl = find_final_pkl()
    backup = pkl.with_suffix(".before_round41_42.pkl")

    city_summary = pd.read_csv(METRIC_DIR / "round40_prediction_column_compare_summary.csv")
    final = city_summary[city_summary["pred_col"].eq("power_pred_final")].iloc[0]

    hourly = pd.read_csv(METRIC_DIR / "round40_prediction_column_compare_hourly.csv")
    final_hour = hourly[hourly["pred_col"].eq("power_pred_final")]
    edge = final_hour[final_hour["hour"].isin([6, 7, 18, 19])]
    focus = final_hour[final_hour["hour"].isin([10, 11, 12, 13, 14])]

    site_summary = pd.read_csv(METRIC_DIR / "round41_42_site_summary_after.csv").iloc[0]

    checks = []
    checks.append({
        "check": "edge_suspicious_city_zero_count",
        "value": int(edge["suspicious_city_zero_count"].sum()),
        "threshold": 0,
        "status": "PASS" if int(edge["suspicious_city_zero_count"].sum()) == 0 else "FAIL",
    })
    checks.append({
        "check": "focus_10_14_city_hourly_nrmse_under_6",
        "value": round(float(focus["city_nrmse_pct"].mean()), 6),
        "threshold": 6.0,
        "status": "PASS" if float(focus["city_nrmse_pct"].mean()) <= 6.0 else "FAIL",
    })
    checks.append({
        "check": "city_nrmse_under_10",
        "value": round(float(final["city_nrmse_pct"]), 6),
        "threshold": 10.0,
        "status": "PASS" if float(final["city_nrmse_pct"]) <= 10.0 else "FAIL",
    })
    checks.append({
        "check": "city_abs_bias_under_15",
        "value": round(abs(float(final["city_bias_pct"])), 6),
        "threshold": 15.0,
        "status": "PASS" if abs(float(final["city_bias_pct"])) <= 15.0 else "FAIL",
    })
    checks.append({
        "check": "full_site_mean_nrmse_under_35",
        "value": round(float(site_summary["full_site_mean_nrmse_pct"]), 6),
        "threshold": 35.0,
        "status": "PASS" if float(site_summary["full_site_mean_nrmse_pct"]) <= 35.0 else "FAIL",
    })
    checks.append({
        "check": "active_site_mean_nrmse_under_25",
        "value": round(float(site_summary["active_site_mean_nrmse_pct"]), 6),
        "threshold": 25.0,
        "status": "PASS" if float(site_summary["active_site_mean_nrmse_pct"]) <= 25.0 else "FAIL",
    })

    out = pd.DataFrame(checks)
    out.to_csv(METRIC_DIR / "round41_42_guard.csv", index=False, encoding="utf-8-sig")
    print(out.to_string(index=False))

    if (out["status"] == "FAIL").any():
        if backup.exists():
            shutil.copy2(backup, pkl)
            print("[RESTORE] guard failed, restored:", pkl)
        raise SystemExit("[FAIL] Round41+42 guard failed")

    print("[PASS] Round41+42 guard passed")


if __name__ == "__main__":
    main()
