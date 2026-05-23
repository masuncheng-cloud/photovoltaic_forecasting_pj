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

OUT = PROJECT_ROOT / "output" / "pv_pipeline"
TABLES = OUT / "tables"
METRICS = OUT / "metrics"
DOCS = OUT / "docs"
DOCS.mkdir(parents=True, exist_ok=True)


def main():
    print("生成当前最终结果摘要 …")

    df = safe_pickle_load(TABLES / "distributed_predictions_final_eval.pkl")
    ev = build_eval_frame(df, target_site_count=53)

    yt = pd.to_numeric(ev["power_mw"], errors="coerce")
    yp = pd.to_numeric(ev["power_pred"], errors="coerce")
    err = yp - yt
    actual = float(yt.sum())
    pred = float(yp.sum())
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err ** 2)))
    cap_mean = float(pd.to_numeric(ev["capacity_mw"], errors="coerce").mean())
    nrmse = rmse / max(cap_mean, 1e-9) * 100
    ratio = pred / max(actual, 1e-9)
    bias = (pred - actual) / max(actual, 1e-9) * 100

    lines = []
    lines.append("# 当前最终结果摘要\n")
    lines.append("## 整体指标\n")
    lines.append(f"- 样本数：{len(ev):,}")
    lines.append(f"- 站点数：{int(ev['site_id'].nunique())}")
    lines.append(f"- 实际总出力：{actual:.2f} MWh")
    lines.append(f"- 预测总出力：{pred:.2f} MWh")
    lines.append(f"- pred_actual_ratio：{ratio:.4f}")
    lines.append(f"- bias：{bias:.3f}%")
    lines.append(f"- 全样本 NRMSE：{nrmse:.3f}%")
    lines.append(f"- MAE：{mae:.4f} MW")
    lines.append(f"- RMSE：{rmse:.4f} MW")

    hdf = hourly_nrmse_metrics(ev)
    hdf_rounded = hdf.copy()
    hdf_rounded["site_nrmse_mean_pct"] = hdf_rounded["site_nrmse_mean_pct"].round(3)
    hdf_rounded["city_nrmse_pct"] = hdf_rounded["city_nrmse_pct"].round(3)
    lines.append("\n## 逐小时 NRMSE\n")
    lines.append(hdf_rounded[["hour", "rows", "site_nrmse_mean_pct", "city_nrmse_pct"]].to_string(index=False))

    sel_path = METRICS / "final_version_selection_by_hour.csv"
    if sel_path.exists():
        sel = pd.read_csv(sel_path)
        cols = [c for c in ["hour", "selected_version", "is_midday_nrmse_priority",
                             "mae", "rmse", "pred_actual_ratio", "nrmse_capacity_pct"] if c in sel.columns]
        lines.append("\n## 版本选择\n")
        lines.append(sel[cols].to_string(index=False))

    oracle_path = METRICS / "blend_oracle_on_test_diagnostic_only.csv"
    if oracle_path.exists():
        diag = pd.read_csv(oracle_path)
        lines.append("\n## BlendTotal Oracle 诊断（test 集，仅供参考，不参与 final 选择）\n")
        lines.append(diag.to_string(index=False))

    # ── 10-14 点 NRMSE 专项 ───────────────────────────────────────────
    midday_path = METRICS / "midday_nrmse_acceptance.csv"
    if midday_path.exists():
        ab = pd.read_csv(midday_path)
        lines.append("\n## 10-14 点 NRMSE 专项验收\n")
        lines.append("说明：10-14 点为主体发电时段，本轮优先优化站点平均 NRMSE；"
                    "若城市 NRMSE 小幅波动但站点 NRMSE 下降，视为有效改善。")
        lines.append(ab.to_string(index=False))

    midday_ab_path = METRICS / "midday_site_calibration_valid_ablation.csv"
    if midday_ab_path.exists():
        ab = pd.read_csv(midday_ab_path)
        lines.append("\n## Midday 校准 Valid 消融\n")
        lines.append(ab.to_string(index=False))

    midday_params_path = METRICS / "midday_site_calibration_params.csv"
    if midday_params_path.exists():
        params = pd.read_csv(midday_params_path)
        lines.append("\n## Midday 校准参数统计\n")
        lines.append(f"- 共 {len(params)} 个 (hour, site) 校准对")
        lines.append(f"- k_final 范围: [{params['k_final'].min():.4f}, {params['k_final'].max():.4f}]")
        lines.append(f"- k_final 均值: {params['k_final'].mean():.4f}")
        lines.append(f"- best_alpha 分布: {params['best_alpha'].value_counts().to_dict()}")
        lines.append("\n逐小时参数：")
        hour_stats = params.groupby("hour")["k_final"].agg(["mean", "std", "count"]).round(4)
        lines.append(hour_stats.to_string())

    md_text = "\n".join(lines)
    (DOCS / "当前最终结果摘要.md").write_text(md_text, encoding="utf-8")
    print(f"已保存: {DOCS / '当前最终结果摘要.md'}")

    print("\n整体指标：")
    print(f"  rows={len(ev)}, sites={int(ev['site_id'].nunique())}")
    print(f"  ratio={ratio:.4f}, bias={bias:.3f}%")
    print(f"  MAE={mae:.4f} MW, RMSE={rmse:.4f} MW")
    print(f"  全样本 NRMSE={nrmse:.3f}%")


if __name__ == "__main__":
    main()
