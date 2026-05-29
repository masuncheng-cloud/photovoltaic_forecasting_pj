from pathlib import Path
import pandas as pd


ROOT = Path("output/pv_pipeline")
METRIC_DIR = ROOT / "metrics"


def main():
    summary_path = METRIC_DIR / "round40_prediction_column_compare_summary.csv"
    hourly_path = METRIC_DIR / "round40_prediction_column_compare_hourly.csv"

    summary = pd.read_csv(summary_path)
    hourly = pd.read_csv(hourly_path)

    required = {"power_pred_final", "power_pred_cal"}
    present = set(summary["pred_col"])
    missing = required - present
    if missing:
        raise AssertionError(f"缺少对比预测列: {missing}")

    final = summary[summary["pred_col"].eq("power_pred_final")].iloc[0]
    cal = summary[summary["pred_col"].eq("power_pred_cal")].iloc[0]

    checks = []

    # 1. 早晚临界小时不允许整城预测为 0
    final_hour = hourly[hourly["pred_col"].eq("power_pred_final")]
    edge = final_hour[final_hour["hour"].isin([6, 7, 18, 19])]
    suspicious_total = int(edge["suspicious_city_zero_count"].sum())
    checks.append({
        "check": "edge_suspicious_city_zero",
        "status": "PASS" if suspicious_total == 0 else "FAIL",
        "value": suspicious_total,
        "threshold": 0,
    })

    # 2. 10-14 不得明显劣化：相对 power_pred_cal 不高于 3 个百分点
    midday_delta = float(final["midday_city_nrmse_pct"] - cal["midday_city_nrmse_pct"])
    checks.append({
        "check": "midday_city_nrmse_not_worse_than_cal_by_3pp",
        "status": "PASS" if midday_delta <= 3.0 else "FAIL",
        "value": round(midday_delta, 6),
        "threshold": 3.0,
    })

    # 3. 整体不应离谱：全市整体 NRMSE 不超过 10%
    city_nrmse = float(final["city_nrmse_pct"])
    checks.append({
        "check": "overall_city_nrmse_under_10pct",
        "status": "PASS" if city_nrmse <= 10.0 else "FAIL",
        "value": round(city_nrmse, 6),
        "threshold": 10.0,
    })

    # 4. BIAS 不应明显偏置：绝对值不超过 15%
    bias = abs(float(final["city_bias_pct"]))
    checks.append({
        "check": "overall_city_abs_bias_under_15pct",
        "status": "PASS" if bias <= 15.0 else "FAIL",
        "value": round(bias, 6),
        "threshold": 15.0,
    })

    out = pd.DataFrame(checks)
    out_path = METRIC_DIR / "round40_final_prediction_guard.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(out.to_string(index=False))
    if (out["status"] == "FAIL").any():
      raise SystemExit("[FAIL] Round40 guard failed, do not publish dashboard as final")
    print("[PASS] Round40 guard passed")


if __name__ == "__main__":
    main()
