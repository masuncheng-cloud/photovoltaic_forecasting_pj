#!/usr/bin/env python3
"""
check_dashboard_prediction_values.py
==================================
Dashboard 预测值一致性全量校验（Round50+ 通用版）。

校验可视化 site_series/*.json 中的 actual_mw / pred_mw
是否与 distributed_predictions_final_full.pkl 中的对应列一致。

口径：split != future, hour in 6..19

预测列选择（与 export_interactive_dashboard_data.py 完全一致）：
  train -> power_pred_cal
  valid -> power_pred_final
  test  -> power_pred_final

由于 JSON 导出精度为 4 位小数，比较时将 PKL 值 round 到 4 位小数再比对。

用法：
    python scripts/check_dashboard_prediction_values.py --output-root output/pv_pipeline
"""

import argparse
import json
import pickle
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# JSON 导出精度为 4 位小数，对齐后再比对
JSON_PRECISION = 4
TOLERANCE = 1e-4   # 4位小数精度下的预期最大差异

HISTORY_SPLITS = ["train", "valid", "test"]


def resolve_best_pred_col_for_split(df: pd.DataFrame, split: str) -> str:
    """与 export_interactive_dashboard_data.py 完全一致的列选择逻辑。"""
    candidates_by_split = {
        "test":   ["power_pred_final", "power_pred", "power_pred_cal"],
        "valid":  ["power_pred_final", "power_pred", "power_pred_cal"],
        "train":  ["power_pred_cal", "pred_mw", "power_pred_raw"],
    }
    candidates = candidates_by_split.get(split, candidates_by_split["train"])
    for col in candidates:
        if col in df.columns:
            s = df[df["split"] == split]
            if s is not None and s[col].notna().sum() > 0:
                return col
    return candidates[0]


def load_pkl(out_dir: Path) -> tuple[pd.DataFrame, dict]:
    """加载 pkl 并返回列→split 映射。"""
    canonical = out_dir / "predictions" / "distributed_predictions_final_full.pkl"
    if not canonical.exists():
        raise FileNotFoundError(
            f"[ERROR] canonical 预测文件不存在: {canonical}\n"
            f"[ERROR] 请先运行完整重训。"
        )
    print(f"  [canonical] {canonical.relative_to(PROJECT_ROOT)}")
    with open(canonical, "rb") as f:
        df = pickle.load(f)
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    df = df[df["split"].isin(HISTORY_SPLITS)].copy()
    df = df[df["hour"].between(6, 19)].copy()
    df = df.sort_values(["site_id", "time"]).reset_index(drop=True)

    pred_col_by_split = {}
    for sp in HISTORY_SPLITS:
        pred_col_by_split[sp] = resolve_best_pred_col_for_split(df, sp)

    print(f"  pkl: {len(df):,} 行 (不含future, 6-19点), {df['site_id'].nunique()} 站")
    print(f"  [pred_col_by_split] {pred_col_by_split}")
    return df, pred_col_by_split


def load_json_series(site_dir: Path) -> dict:
    """加载所有站点 JSON 文件（不含 future）。"""
    result = {}
    for f in sorted(site_dir.glob("S*.json")):
        sid = f.stem
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        result[sid] = data
    print(f"  JSON: {len(result)} 个站点文件")
    return result


def check_site(sid: str, json_rows: list, pkl_df: pd.DataFrame,
               pred_col_by_split: dict) -> dict:
    """按 split 选择正确列，校验单个站点的 JSON 与 PKL 一致性。

    JSON 导出精度为 4 位小数，将 PKL 值 round 到 4 位小数再比对。
    """
    n_json = len(json_rows)
    if n_json == 0:
        return {
            "site_id": sid, "n_json": 0, "n_pkl": 0, "n_matched": 0,
            "count_ok": False, "max_abs_diff_actual": np.nan,
            "max_abs_diff_pred": np.nan,
            "status": "WARN", "message": "JSON 为空或全为 future",
        }

    jdf = pd.DataFrame(json_rows)
    jdf["time"] = pd.to_datetime(jdf["time"], errors="coerce")
    jdf = jdf.sort_values(["time"]).reset_index(drop=True)

    n_pkl = len(pkl_df[pkl_df["site_id"] == sid])
    n_matched = 0
    max_diff_actual = np.nan
    max_diff_pred = np.nan
    count_ok = False
    all_ok = True
    msgs = []

    for split, col in pred_col_by_split.items():
        jsplit = [r for r in json_rows if r.get("split") == split]
        if not jsplit:
            continue

        jsp = pd.DataFrame(jsplit)
        jsp["time"] = pd.to_datetime(jsp["time"], errors="coerce")
        jsp = jsp.sort_values("time").reset_index(drop=True)

        pkl_site = pkl_df[
            (pkl_df["site_id"] == sid) & (pkl_df["split"] == split)
        ].sort_values("time").reset_index(drop=True)

        merged = pd.merge(
            jsp[["time", "actual_mw", "pred_mw"]].rename(
                columns={"actual_mw": "actual_json", "pred_mw": "pred_json"}
            ),
            pkl_site[["time", "power_mw", col]].rename(
                columns={"power_mw": "actual_pkl", col: "pred_pkl_raw"}
            ),
            on="time", how="inner",
        )
        if len(merged) == 0:
            continue

        n_matched += len(merged)

        merged["pred_pkl"] = merged["pred_pkl_raw"].round(JSON_PRECISION)
        merged["actual_pkl_rounded"] = merged["actual_pkl"].round(JSON_PRECISION)

        diff_actual = (merged["actual_json"] - merged["actual_pkl_rounded"]).abs()
        diff_pred = (merged["pred_json"] - merged["pred_pkl"]).abs()

        max_da = float(diff_actual.max()) if diff_actual.notna().any() else 0.0
        max_dp = float(diff_pred.max()) if diff_pred.notna().any() else 0.0

        if np.isnan(max_diff_actual) or max_da > max_diff_actual:
            max_diff_actual = max_da
        if np.isnan(max_diff_pred) or max_dp > max_diff_pred:
            max_diff_pred = max_dp

        if max_da > TOLERANCE or max_dp > TOLERANCE:
            all_ok = False
            msgs.append(f"  {split}: actual={max_da:.2e}, pred={max_dp:.2e} (col={col})")

    count_ok = (n_matched > 0)
    status = "PASS" if all_ok and count_ok else "FAIL"
    msg = "; ".join(msgs) if msgs else f"count_ok={count_ok}, n_matched={n_matched}"
    if all_ok:
        msg = f"max_actual={max_diff_actual:.2e}, max_pred={max_diff_pred:.2e}"

    return {
        "site_id": sid,
        "n_json": n_json,
        "n_pkl": n_pkl,
        "n_matched": n_matched,
        "count_ok": count_ok,
        "max_abs_diff_actual": max_diff_actual,
        "max_abs_diff_pred": max_diff_pred,
        "status": status,
        "message": msg,
    }


def check_all(pkl_df: pd.DataFrame, json_data: dict,
              pred_col_by_split: dict) -> pd.DataFrame:
    rows = []
    for sid in sorted(json_data.keys()):
        r = check_site(sid, json_data[sid], pkl_df, pred_col_by_split)
        rows.append(r)
    return pd.DataFrame(rows)


def write_outputs(result_df: pd.DataFrame, pred_col_by_split: dict, out_dir: Path):
    metrics_dir = out_dir / "metrics"
    docs_dir = out_dir / "docs"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(result_df)
    passes = int((result_df["status"] == "PASS").sum())
    fails  = int((result_df["status"] == "FAIL").sum())
    warns  = int((result_df["status"] == "WARN").sum())
    max_pred   = float(result_df["max_abs_diff_pred"].max())    if result_df["max_abs_diff_pred"].notna().any()    else 0.0
    max_actual = float(result_df["max_abs_diff_actual"].max()) if result_df["max_abs_diff_actual"].notna().any() else 0.0

    csv_path = metrics_dir / "dashboard_prediction_consistency.csv"
    result_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"  CSV -> {csv_path}")

    report_path = docs_dir / "Dashboard预测值一致性检查报告.md"
    pred_info = ", ".join(f"{s}->{c}" for s, c in sorted(pred_col_by_split.items()))
    lines = [
        f"# Dashboard 预测值一致性检查报告\n\n",
        f"**生成时间**: {now}\n\n",
        f"**检查口径**: split != 'future', hour in 6-19\n\n",
        f"**预测列选择（与 export 脚本一致）**: {pred_info}\n\n",
        f"**JSON 精度**: {JSON_PRECISION} 位小数，PKL 对齐到 {JSON_PRECISION} 位后再比对\n\n",
        f"**容差**: {TOLERANCE:.0e} MW\n\n",
        f"## 总体结果\n\n",
        f"| 指标 | 值 |\n|------|---|\n",
        f"| 总站点数 | {total} |\n",
        f"| PASS | {passes} |\n",
        f"| FAIL | {fails} |\n",
        f"| WARN | {warns} |\n",
        f"| 最大 actual 误差 | {max_actual:.2e} |\n",
        f"| 最大 pred 误差 | {max_pred:.2e} |\n\n",
        f"## 逐站点详情\n\n",
        f"| site_id | n_json | n_pkl | n_matched | count_ok | "
        f"max_diff_actual | max_diff_pred | status |\n",
        f"|----------|--------|-------|-----------|---------|"
        f"-----------------|---------------|--------|\n",
    ]
    for _, r in result_df.iterrows():
        ad = f"{r['max_abs_diff_actual']:.2e}" if not pd.isna(r['max_abs_diff_actual']) else "N/A"
        pd_ = f"{r['max_abs_diff_pred']:.2e}"   if not pd.isna(r['max_abs_diff_pred'])   else "N/A"
        icon = "PASS" if r['status'] == "PASS" else ("WARN" if r['status'] == "WARN" else "FAIL")
        lines.append(
            f"| {r['site_id']} | {r['n_json']} | {r['n_pkl']} | {r['n_matched']} | "
            f"{'Y' if r['count_ok'] else 'N'} | {ad} | {pd_} | "
            f"{icon} |\n"
        )

    if fails > 0:
        lines.append("\n## FAIL 详情\n\n")
        for _, r in result_df[result_df["status"] == "FAIL"].iterrows():
            lines.append(f"- **{r['site_id']}**: {r['message']}\n")
    else:
        lines.append("\n## 结论\n\n")
        lines.append(
            f"**全部站点 PASS**：pred_mw 与 PKL 中对应列（已对齐精度后）完全一致。\n"
        )

    report_path.write_text("".join(lines), encoding="utf-8")
    print(f"  报告 -> {report_path}")

    return passes, fails, warns, max_pred, max_actual


def main():
    parser = argparse.ArgumentParser(description="Dashboard 预测值一致性校验")
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument(
        "--output-root",
        type=str,
        default=None,
        help="输出根目录 (default: output/pv_pipeline)",
    )
    args = parser.parse_args()

    if args.output_root:
        out_dir = PROJECT_ROOT / args.output_root
    else:
        import yaml
        cfg_path = PROJECT_ROOT / "configs" / "pipeline.yaml"
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        out_dir = PROJECT_ROOT / cfg.get("data", {}).get("output_root", "output/pv_pipeline")

    print("=" * 60)
    print("Dashboard 预测值一致性全量检查")
    print(f"Output root: {out_dir}")
    print("=" * 60)
    print(f"口径: split != 'future', hour in 6-19")
    print(f"JSON 精度: {JSON_PRECISION} 位小数, 容差: {TOLERANCE:.0e}")

    try:
        pkl_df, pred_col_by_split = load_pkl(out_dir)
    except FileNotFoundError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)

    site_dir = out_dir / "interactive_dashboard" / "site_series"
    if not site_dir.exists():
        print(f"[FAIL] site_series 目录不存在: {site_dir}")
        sys.exit(1)

    json_data = load_json_series(site_dir)
    result_df = check_all(pkl_df, json_data, pred_col_by_split)
    passes, fails, warns, max_pred, max_actual = write_outputs(result_df, pred_col_by_split, out_dir)

    print()
    print("=" * 60)
    print(f"结果: {passes}/{len(result_df)} PASS, {fails} FAIL, {warns} WARN")
    print(f"最大 pred 误差:     {max_pred:.2e} (容差: {TOLERANCE:.0e})")
    print(f"最大 actual 误差:   {max_actual:.2e}")
    print("=" * 60)

    sys.exit(0 if fails == 0 else 1)


if __name__ == "__main__":
    main()
