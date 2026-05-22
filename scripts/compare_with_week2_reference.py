#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics
from pv_forecasting.core.week2_reference import WEEK2_REFERENCE, WEEK2_HOURLY_NRMSE

OUT = PROJECT_ROOT / "output" / "pv_pipeline"
TABLES = OUT / "tables"
METRICS = OUT / "metrics"
DOCS = OUT / "docs"
METRICS.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)


def overall_metrics(df):
    yt = pd.to_numeric(df["power_mw"], errors="coerce")
    yp = pd.to_numeric(df["power_pred"], errors="coerce")
    m = yt.notna() & yp.notna()
    actual = float(yt[m].sum())
    pred = float(yp[m].sum())
    err = yp[m].values - yt[m].values
    return {
        "rows": int(len(df)),
        "sites": int(df["site_id"].nunique()),
        "actual_mwh": round(actual, 2),
        "pred_mwh": round(pred, 2),
        "pred_actual_ratio": round(pred / max(actual, 1e-9), 4),
        "bias_pct": round((pred - actual) / max(actual, 1e-9) * 100, 3),
        "mae_mw": round(float(np.mean(np.abs(err))), 4),
        "rmse_mw": round(float(np.sqrt(np.mean(err ** 2))), 4),
    }


def main():
    print("当前结果 vs 周二基准对比")
    print("=" * 50)

    final_path = TABLES / "distributed_predictions_final_eval.pkl"
    df = safe_pickle_load(final_path)
    eval_df = build_eval_frame(df, target_site_count=53)

    current = overall_metrics(eval_df)
    ref = WEEK2_REFERENCE

    # 整体对比
    rows = []
    for key, label in [
        ("rows",               "样本数"),
        ("sites",              "站点数"),
        ("actual_mwh",         "实际总出力(MWh)"),
        ("pred_mwh",           "预测总出力(MWh)"),
        ("pred_actual_ratio",  "pred_actual_ratio"),
        ("bias_pct",           "bias(%)"),
        ("mae_mw",             "MAE(MW)"),
        ("rmse_mw",           "RMSE(MW)"),
    ]:
        cur = current[key]
        old = ref[key]
        if isinstance(cur, (int, float)) and isinstance(old, (int, float)):
            diff = round(cur - old, 4)
        else:
            diff = ""
        if key in {"mae_mw", "rmse_mw"}:
            verdict = "是" if cur <= old else "否"
        elif key == "pred_actual_ratio":
            verdict = "是" if abs(cur - 0.9488) <= abs(old - 0.9488) else "否"
        elif key == "bias_pct":
            verdict = "是" if abs(cur) <= abs(old) else "否"
        else:
            verdict = "参考"
        rows.append({
            "指标": label,
            "周二基准": old,
            "当前结果": cur,
            "差值_当前减周二": diff,
            "是否优于周二": verdict,
        })

    overall_df = pd.DataFrame(rows)
    overall_df.to_csv(
        METRICS / "当前结果_vs_周二基准_整体对比.csv",
        index=False, encoding="utf-8-sig")
    print(f"已保存: {METRICS / '当前结果_vs_周二基准_整体对比.csv'}")

    # 逐小时 NRMSE 对比
    hdf = hourly_nrmse_metrics(eval_df)
    h_rows = []
    for _, r in hdf.iterrows():
        h = int(r["hour"])
        old = WEEK2_HOURLY_NRMSE.get(h, {})
        old_site = old.get("site_nrmse_mean_pct")
        old_city = old.get("city_nrmse_pct")
        site_diff = round(r["site_nrmse_mean_pct"] - old_site, 3) \
            if old_site is not None and np.isfinite(old_site) else np.nan
        city_diff = round(r["city_nrmse_pct"] - old_city, 3) \
            if old_city is not None and np.isfinite(old_city) else np.nan
        h_rows.append({
            "hour": h,
            "周二_rows": old.get("rows"),
            "当前_rows": int(r["rows"]),
            "周二_站点平均NRMSE(%)": old_site,
            "当前_站点平均NRMSE(%)": round(float(r["site_nrmse_mean_pct"]), 3),
            "站点NRMSE变化": site_diff,
            "周二_城市NRMSE(%)": old_city,
            "当前_城市NRMSE(%)": round(float(r["city_nrmse_pct"]), 3),
            "城市NRMSE变化": city_diff,
        })

    hourly_df = pd.DataFrame(h_rows)
    hourly_df.to_csv(
        METRICS / "当前结果_vs_周二基准_逐小时NRMSE对比.csv",
        index=False, encoding="utf-8-sig")
    print(f"已保存: {METRICS / '当前结果_vs_周二基准_逐小时NRMSE对比.csv'}")

    # Markdown 报告
    mae_cur = current["mae_mw"]
    rmse_cur = current["rmse_mw"]
    mae_ref = ref["mae_mw"]
    rmse_ref = ref["rmse_mw"]

    if mae_cur <= mae_ref and rmse_cur <= rmse_ref:
        verdict_text = "当前 MAE/RMSE 已达到或优于周二基准。"
    elif mae_cur <= mae_ref * 1.2 and rmse_cur <= rmse_ref * 1.2:
        verdict_text = (
            f"当前 MAE({mae_cur:.4f}) 接近周二({mae_ref:.4f})，"
            f"RMSE({rmse_cur:.4f}) 距周二({rmse_ref:.4f}) 在 20% 以内。"
        )
    else:
        verdict_text = (
            f"当前 MAE({mae_cur:.4f}) 和 RMSE({rmse_cur:.4f}) 仍未达到周二基准"
            f"(MAE={mae_ref:.4f}, RMSE={rmse_ref:.4f})，应继续优先降低站点级误差。"
        )

    lines = [
        "# 当前结果 vs 周二基准对比\n\n",
        "## 整体指标\n\n",
        overall_df.to_string(index=False), "\n\n",
        "## 逐小时 NRMSE\n\n",
        hourly_df.to_string(index=False), "\n\n",
        "## 判断\n\n",
        verdict_text,
    ]

    (DOCS / "当前结果_vs_周二基准对比.md").write_text("".join(lines), encoding="utf-8")
    print(f"已保存: {DOCS / '当前结果_vs_周二基准对比.md'}")

    print("\n整体指标：")
    print(overall_df.to_string(index=False))
    print(f"\nMAE: {mae_cur:.4f} (周二={mae_ref:.4f})")
    print(f"RMSE: {rmse_cur:.4f} (周二={rmse_ref:.4f})")


if __name__ == "__main__":
    main()
