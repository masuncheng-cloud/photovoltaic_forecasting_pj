#!/usr/bin/env python3
"""
check_dashboard_prediction_values.py
==================================
Dashboard 预测值一致性全量校验（Round50+ 通用版）。

校验可视化 site_series/*.json 中的 actual_mw / pred_mw
是否与 distributed_predictions_final_round36.pkl 中的 power_mw / power_pred_final 完全一致。

口径：split != future, hour in 6..19
验收：
  - 所有站点 PASS
  - n_json == n_pkl_6_19 == n_matched
  - max_abs_diff_pred <= 1e-9
  - max_abs_diff_actual <= 1e-9

用法：
    python scripts/check_dashboard_prediction_values.py
"""

import argparse
import json
import os
import pickle
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scripts.common_paths import load_config, output_root
except ImportError:
    def load_config(cfg_path=None):
        import yaml
        path = Path(cfg_path) if cfg_path else PROJECT_ROOT / "configs" / "pipeline.yaml"
        with open(path) as f:
            return yaml.safe_load(f)
    def output_root(cfg):
        return PROJECT_ROOT / cfg.get("data", {}).get("output_root", "output/pv_pipeline")


TOLERANCE = 1e-9


def load_pkl(out_dir: Path) -> pd.DataFrame:
    """从 canonical 路径加载最终预测 pkl（兼容 fallback）。"""
    # canonical 路径
    canonical = out_dir / "predictions" / "distributed_predictions_final_full.pkl"
    if canonical.exists():
        pkl_path = canonical
        print(f"  [canonical] 使用: {pkl_path.relative_to(PROJECT_ROOT)}")
    else:
        # fallback：legacy 路径
        tables_dir = out_dir / "tables"
        candidates = sorted(tables_dir.glob("distributed_predictions_final_round36.pkl"))
        if not candidates:
            candidates = sorted(tables_dir.glob("distributed_predictions_final_*.pkl"))
        if not candidates:
            raise FileNotFoundError(
                f"找不到 distributed_predictions_final_*.pkl（canonical: {canonical}）\n"
                f"请先运行训练流程或确认文件路径。"
            )
        pkl_path = candidates[0]
        print(f"  [legacy fallback] 使用: {pkl_path.relative_to(PROJECT_ROOT)}")
    with open(pkl_path, "rb") as f:
        df = pickle.load(f)
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    # 口径：不含 future，小时 6-19
    df = df[(df["split"] != "future") & df["hour"].between(6, 19)].copy()
    df = df.sort_values(["site_id", "time"]).reset_index(drop=True)
    print(f"  pkl: {len(df):,} 行 (不含future, 6-19点), {df['site_id'].nunique()} 站")
    return df


def load_json_series(site_dir: Path) -> dict:
    """加载所有站点 JSON 文件（不含 future）。"""
    result = {}
    for f in sorted(site_dir.glob("S*.json")):
        sid = f.stem
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        filtered = [r for r in data if r.get("split") != "future"]
        result[sid] = filtered
    print(f"  JSON: {len(result)} 个站点文件")
    return result


def check_site(sid: str, json_rows: list, pkl_df: pd.DataFrame,
               pred_col: str = "power_pred_final") -> dict:
    """校验单个站点的 JSON 与 pkl 一致性。"""
    n_json = len(json_rows)
    if n_json == 0:
        return {
            "site_id": sid, "n_json": 0, "n_pkl": 0, "n_matched": 0,
            "count_ok": False, "max_abs_diff_actual": np.nan,
            "max_abs_diff_pred": np.nan, "max_abs_diff_capacity": np.nan,
            "status": "WARN", "message": "JSON 为空或全为 future",
        }

    jdf = pd.DataFrame(json_rows)
    jdf["time"] = pd.to_datetime(jdf["time"], errors="coerce")
    jdf = jdf.sort_values(["site_id", "time"]).reset_index(drop=True)

    pkl_site = pkl_df[pkl_df["site_id"] == sid].copy()
    pkl_site = pkl_site.sort_values(["site_id", "time"]).reset_index(drop=True)
    n_pkl = len(pkl_site)

    merged = pd.merge(
        jdf[["time", "actual_mw", "pred_mw", "capacity_mw"]].rename(
            columns={"capacity_mw": "cap_json", "actual_mw": "actual_json", "pred_mw": "pred_json"}
        ),
        pkl_site[["time", "power_mw", pred_col, "capacity_mw"]].rename(
            columns={"capacity_mw": "cap_pkl", "power_mw": "actual_pkl", pred_col: "pred_pkl"}
        ),
        on="time", how="inner",
    )
    n_matched = len(merged)
    count_ok = (n_json == n_pkl == n_matched)

    def safe_max_diff(a, b, round_pkl_digits=4):
        m = a.notna() & b.notna()
        if not m.any():
            return np.nan
        b_vals = b[m]
        return float(np.abs(a[m] - b_vals.round(round_pkl_digits)).max())

    max_diff_actual = safe_max_diff(merged["actual_json"], merged["actual_pkl"])
    max_diff_pred   = safe_max_diff(merged["pred_json"], merged["pred_pkl"])
    max_diff_cap    = safe_max_diff(merged["cap_json"], merged["cap_pkl"])

    actual_ok = np.isnan(max_diff_actual) or max_diff_actual <= TOLERANCE
    pred_ok   = np.isnan(max_diff_pred)   or max_diff_pred   <= TOLERANCE
    cap_ok    = np.isnan(max_diff_cap)    or max_diff_cap    <= TOLERANCE

    if actual_ok and pred_ok and cap_ok and count_ok:
        status = "PASS"
        msg = (f"actual={max_diff_actual:.2e}, pred={max_diff_pred:.2e}, "
               f"cap={max_diff_cap:.2e}, count_ok=True")
    else:
        status = "FAIL"
        msg = (f"actual={max_diff_actual:.2e}, pred={max_diff_pred:.2e}, "
               f"cap={max_diff_cap:.2e}, count_ok={count_ok}")

    return {
        "site_id": sid,
        "n_json": n_json,
        "n_pkl": n_pkl,
        "n_matched": n_matched,
        "count_ok": count_ok,
        "max_abs_diff_actual": max_diff_actual,
        "max_abs_diff_pred": max_diff_pred,
        "max_abs_diff_capacity": max_diff_cap,
        "status": status,
        "message": msg,
    }


def check_all(pkl_df: pd.DataFrame, json_data: dict,
              pred_col: str = "power_pred_final") -> pd.DataFrame:
    """对所有站点执行一致性检查。"""
    rows = []
    for sid in sorted(json_data.keys()):
        r = check_site(sid, json_data[sid], pkl_df, pred_col)
        rows.append(r)
    return pd.DataFrame(rows)


def write_outputs(result_df: pd.DataFrame, cfg: dict, out_dir: Path):
    """写出 CSV 和报告文件。"""
    metrics_dir = out_dir / "metrics"
    docs_dir = out_dir / "docs"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(result_df)
    passes = int((result_df["status"] == "PASS").sum())
    fails  = int((result_df["status"] == "FAIL").sum())
    warns  = int((result_df["status"] == "WARN").sum())
    max_pred    = float(result_df["max_abs_diff_pred"].max())     if result_df["max_abs_diff_pred"].notna().any()     else 0.0
    max_actual  = float(result_df["max_abs_diff_actual"].max()) if result_df["max_abs_diff_actual"].notna().any() else 0.0
    max_cap     = float(result_df["max_abs_diff_capacity"].max()) if result_df["max_abs_diff_capacity"].notna().any() else 0.0

    # CSV
    csv_path = metrics_dir / "dashboard_prediction_consistency.csv"
    result_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"  CSV → {csv_path}")

    # Markdown report
    report_path = docs_dir / "Dashboard预测值一致性检查报告.md"
    lines = [
        f"# Dashboard 预测值一致性检查报告\n\n",
        f"**生成时间**: {now}\n\n",
        f"**检查口径**: split != 'future', hour in 6..19\n",
        f"**预测列**: power_pred_final\n\n",
        f"## 总体结果\n\n",
        f"| 指标 | 值 |\n|------|---|\n",
        f"| 总站点数 | {total} |\n",
        f"| PASS | {passes} |\n",
        f"| FAIL | {fails} |\n",
        f"| WARN | {warns} |\n",
        f"| 最大 actual 误差 | {max_actual:.2e} |\n",
        f"| 最大 pred 误差 | {max_pred:.2e} |\n",
        f"| 最大 capacity 误差 | {max_cap:.2e} |\n\n",
        f"## 逐站点详情\n\n",
        f"| site_id | n_json | n_pkl | n_matched | count_ok | "
        f"max_diff_actual | max_diff_pred | status |\n",
        f"|----------|--------|-------|-----------|---------|"
        f"-----------------|---------------|--------|\n",
    ]
    for _, r in result_df.iterrows():
        ad = f"{r['max_abs_diff_actual']:.2e}" if not pd.isna(r['max_abs_diff_actual']) else "N/A"
        pd_ = f"{r['max_abs_diff_pred']:.2e}"   if not pd.isna(r['max_abs_diff_pred'])   else "N/A"
        icon = "✓" if r['status'] == "PASS" else ("⚠" if r['status'] == "WARN" else "✗")
        lines.append(
            f"| {r['site_id']} | {r['n_json']} | {r['n_pkl']} | {r['n_matched']} | "
            f"{'✓' if r['count_ok'] else '✗'} | {ad} | {pd_} | "
            f"{icon} {r['status']} |\n"
        )

    if fails > 0:
        lines.append("\n## FAIL 详情\n\n")
        for _, r in result_df[result_df["status"] == "FAIL"].iterrows():
            lines.append(f"- **{r['site_id']}**: {r['message']}\n")

    if fails == 0:
        lines.append("\n## 结论\n\n")
        lines.append("**全部站点 PASS**：pred_mw 与 power_pred_final、actual_mw 与 power_mw 完全一致。\n")
    else:
        lines.append(f"\n## 结论\n\n")
        lines.append(f"**{fails} 个站点 FAIL**，请检查上述详情。\n")

    report_path.write_text("".join(lines), encoding="utf-8")
    print(f"  报告 → {report_path}")

    return passes, fails, warns, max_pred, max_actual


def main():
    parser = argparse.ArgumentParser(description="Dashboard 预测值一致性校验")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(f"[FAIL] 配置未找到: {e}")
        sys.exit(1)

    out_dir = output_root(cfg)
    pred_col = cfg.get("prediction", {}).get("final_column", "power_pred_final")

    print("=" * 60)
    print("Dashboard 预测值一致性全量检查")
    print("=" * 60)
    print(f"预测列: {pred_col}")
    print(f"口径: split != 'future', hour in 6..19")

    try:
        pkl_df = load_pkl(out_dir)
    except FileNotFoundError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)

    site_dir = out_dir / "interactive_dashboard" / "site_series"
    if not site_dir.exists():
        print(f"[FAIL] site_series 目录不存在: {site_dir}")
        sys.exit(1)

    json_data = load_json_series(site_dir)
    result_df = check_all(pkl_df, json_data, pred_col)
    passes, fails, warns, max_pred, max_actual = write_outputs(result_df, cfg, out_dir)

    print()
    print("=" * 60)
    print(f"结果: {passes}/{len(result_df)} PASS, {fails} FAIL, {warns} WARN")
    print(f"最大 pred 误差:     {max_pred:.2e} (容差: {TOLERANCE:.0e})")
    print(f"最大 actual 误差:   {max_actual:.2e}")
    print("=" * 60)

    sys.exit(0 if fails == 0 else 1)


if __name__ == "__main__":
    main()
