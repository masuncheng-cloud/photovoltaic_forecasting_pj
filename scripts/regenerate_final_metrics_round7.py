#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round7 脚本一：统一 final metrics 重算
=========================================
从 distributed_predictions_final_eval.pkl 重算所有核心指标文件，
覆盖旧的、不一致的 metrics，输出 manifest 记录来源。
"""
from __future__ import annotations

from pathlib import Path
import sys
import json
import hashlib
from datetime import datetime
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"
METRICS.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)

FINAL_EVAL = TABLES / "distributed_predictions_final_eval.pkl"
FIXED_EVAL = TABLES / "distributed_predictions_fixed_eval.pkl"
FIXED_FULL = TABLES / "distributed_predictions_fixed_full.pkl"
MSC_EVAL = TABLES / "distributed_predictions_midday_site_calibrated_eval.pkl"
MSC_FULL = TABLES / "distributed_predictions_midday_site_calibrated_full.pkl"

MIDDAY = [10, 11, 12, 13, 14]
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def overall_metrics(df: pd.DataFrame) -> dict:
    y = pd.to_numeric(df["power_mw"], errors="coerce").to_numpy(dtype=float)
    p = pd.to_numeric(df["power_pred"], errors="coerce").to_numpy(dtype=float)
    c = pd.to_numeric(df["capacity_mw"], errors="coerce").to_numpy(dtype=float)
    m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c)
    actual = float(np.sum(y[m]))
    pred = float(np.sum(p[m]))
    mae = float(np.mean(np.abs(y[m] - p[m])))
    rmse = float(np.sqrt(np.mean((y[m] - p[m]) ** 2)))
    cap_mean = float(np.nanmean(c[m]))
    return {
        "rows": int(len(df)),
        "n_sites": int(df["site_id"].nunique()),
        "actual_mwh": round(actual, 2),
        "pred_mwh": round(pred, 2),
        "pred_actual_ratio": round(pred / actual, 6) if actual > 0 else np.nan,
        "bias_pct": round((pred / actual - 1.0) * 100.0, 3) if actual > 0 else np.nan,
        "mae_mw": round(mae, 4),
        "rmse_mw": round(rmse, 4),
        "nrmse_capacity_pct": round(rmse / cap_mean * 100.0, 3) if cap_mean > 0 else np.nan,
    }


def load_eval(eval_path: Path, full_path: Path | None = None) -> pd.DataFrame:
    if eval_path.exists():
        return safe_pickle_load(eval_path)
    if full_path is None or not full_path.exists():
        raise FileNotFoundError(f"找不到 eval/full: {eval_path}, {full_path}")
    df = safe_pickle_load(full_path)
    return build_eval_frame(
        df,
        split="test",
        hours=tuple(range(6, 20)),
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=53,
    )


def compare_hourly(base: pd.DataFrame, final: pd.DataFrame, name: str) -> pd.DataFrame:
    b = hourly_nrmse_metrics(base)
    f = hourly_nrmse_metrics(final)
    rows = []
    for h in range(6, 20):
        br = b[b["hour"] == h]
        fr = f[f["hour"] == h]
        if br.empty or fr.empty:
            continue
        br = br.iloc[0]
        fr = fr.iloc[0]
        rows.append({
            "hour": int(h),
            f"{name}_site_nrmse_pct": round(float(br["site_nrmse_mean_pct"]), 4),
            "final_site_nrmse_pct": round(float(fr["site_nrmse_mean_pct"]), 4),
            "improvement_pp": round(float(br["site_nrmse_mean_pct"] - fr["site_nrmse_mean_pct"]), 4),
            f"{name}_city_nrmse_pct": round(float(br["city_nrmse_pct"]), 4),
            "final_city_nrmse_pct": round(float(fr["city_nrmse_pct"]), 4),
            "city_improvement_pp": round(float(br["city_nrmse_pct"] - fr["city_nrmse_pct"]), 4),
        })
    return pd.DataFrame(rows)


def main():
    if not FINAL_EVAL.exists():
        raise FileNotFoundError(FINAL_EVAL)

    final = safe_pickle_load(FINAL_EVAL)
    if "hour" not in final.columns:
        final["time"] = pd.to_datetime(final["time"])
        final["hour"] = final["time"].dt.hour

    manifest = []
    source_hash = file_sha256(FINAL_EVAL)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 整体指标
    overall = overall_metrics(final)
    overall_df = pd.DataFrame([overall])
    out_overall = METRICS / "round7_final_overall_metrics.csv"
    overall_df.to_csv(out_overall, index=False, encoding="utf-8-sig")
    manifest.append({
        "file": str(out_overall.relative_to(PROJECT_ROOT)),
        "source": str(FINAL_EVAL.relative_to(PROJECT_ROOT)),
        "source_sha256": source_hash,
    })

    # 逐小时 NRMSE
    hourly = hourly_nrmse_metrics(final)
    out_hourly = METRICS / "分布式光伏预测_逐小时平均NRMSE.csv"
    hourly[["hour", "rows", "site_nrmse_mean_pct", "city_nrmse_pct"]].to_csv(out_hourly, index=False, encoding="utf-8-sig")
    manifest.append({
        "file": str(out_hourly.relative_to(PROJECT_ROOT)),
        "source": str(FINAL_EVAL.relative_to(PROJECT_ROOT)),
        "source_sha256": source_hash,
    })

    # final vs fixed
    fixed = load_eval(FIXED_EVAL, FIXED_FULL)
    cmp_fixed = compare_hourly(fixed, final, "fixed")
    cmp_fixed_midday = cmp_fixed[cmp_fixed["hour"].isin(MIDDAY)].copy()
    out_fixed = METRICS / "midday_nrmse_current_vs_fixed.csv"
    cmp_fixed_midday.to_csv(out_fixed, index=False, encoding="utf-8-sig")
    manifest.append({
        "file": str(out_fixed.relative_to(PROJECT_ROOT)),
        "source": str(FINAL_EVAL.relative_to(PROJECT_ROOT)),
        "source_sha256": source_hash,
    })

    # final vs MiddaySiteCalibrated
    if MSC_EVAL.exists() or MSC_FULL.exists():
        msc = load_eval(MSC_EVAL, MSC_FULL)
        cmp_safe = compare_hourly(msc, final, "safe")
        cmp_safe = cmp_safe[cmp_safe["hour"].isin(MIDDAY)].copy()
        out_safe = METRICS / "round6_midday_gain_vs_safe.csv"
        cmp_safe.to_csv(out_safe, index=False, encoding="utf-8-sig")
        manifest.append({
            "file": str(out_safe.relative_to(PROJECT_ROOT)),
            "source": str(FINAL_EVAL.relative_to(PROJECT_ROOT)),
            "source_sha256": source_hash,
        })

    # JSON summary
    summary = {
        "generated_at": generated_at,
        "source_final_eval": str(FINAL_EVAL.relative_to(PROJECT_ROOT)),
        "source_sha256": source_hash,
        "overall": overall,
        "midday_hourly": hourly[hourly["hour"].isin(MIDDAY)][
            ["hour", "rows", "site_nrmse_mean_pct", "city_nrmse_pct"]
        ].to_dict(orient="records"),
    }
    out_json = METRICS / "round7_final_metrics_summary.json"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest.append({
        "file": str(out_json.relative_to(PROJECT_ROOT)),
        "source": str(FINAL_EVAL.relative_to(PROJECT_ROOT)),
        "source_sha256": source_hash,
    })

    # manifest
    manifest_df = pd.DataFrame(manifest)
    manifest_df["generated_at"] = generated_at
    out_manifest = METRICS / "round7_final_metrics_manifest.csv"
    manifest_df.to_csv(out_manifest, index=False, encoding="utf-8-sig")

    print("Round7 final metrics regenerated from final_eval.")
    print(overall_df.to_string(index=False))
    print(hourly[hourly["hour"].isin(MIDDAY)][
        ["hour", "rows", "site_nrmse_mean_pct", "city_nrmse_pct"]
    ].to_string(index=False))


if __name__ == "__main__":
    main()
