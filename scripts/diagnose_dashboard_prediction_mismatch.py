#!/usr/bin/env python3
"""
diagnose_dashboard_prediction_mismatch.py
=======================================
诊断 dashboard JSON 中的 pred_mw / actual_mw 与 pkl 中对应列的差异来源。

诊断步骤：
1. 读取 pkl，按 split 确定每个 split 对应的最优预测列（与 export_interactive_dashboard_data.py 完全一致）
2. 读取 JSON，按 split 分组
3. 对每个 split，对比 JSON.pred_mw 与 pkl[对应列]
4. 输出分 split、分站点的差异统计
5. 定位导致 max_diff_pred 最大的行

用法：
    python scripts/diagnose_dashboard_prediction_mismatch.py --output-root output/pv_pipeline
"""
import argparse
import json
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]


HISTORY_SPLITS = ["train", "valid", "test"]


def resolve_best_pred_col_for_split(df: pd.DataFrame, split: str) -> str:
    """与 export_interactive_dashboard_data.py 中的逻辑完全一致。"""
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


def load_pkl(out_dir: Path) -> pd.DataFrame:
    canonical = out_dir / "predictions" / "distributed_predictions_final_full.pkl"
    if not canonical.exists():
        raise FileNotFoundError(f"canonical pkl not found: {canonical}")
    with open(canonical, "rb") as f:
        df = pickle.load(f)
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    df = df[df["split"].isin(HISTORY_SPLITS)].copy()
    df = df[df["hour"].between(6, 19)].copy()
    df = df.sort_values(["site_id", "time"]).reset_index(drop=True)
    print(f"  [pkl] loaded: {len(df):,} rows, {df['site_id'].nunique()} sites, splits: {sorted(df['split'].unique())}")
    return df


def load_json_series(site_dir: Path) -> dict:
    result = {}
    for f in sorted(site_dir.glob("S*.json")):
        sid = f.stem
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        result[sid] = data
    print(f"  [json] loaded: {len(result)} site files")
    return result


def diagnose_by_split(pkl_df: pd.DataFrame, json_data: dict, pred_col_by_split: dict) -> pd.DataFrame:
    """分 split 诊断：找出每个 split 的最大差异"""
    rows = []
    for split in ["train", "valid", "test"]:
        col = pred_col_by_split[split]
        pkl_s = pkl_df[pkl_df["split"] == split].copy()

        diffs = []
        for sid, json_rows in json_data.items():
            jsplit = [r for r in json_rows if r.get("split") == split]
            if not jsplit:
                continue
            jdf = pd.DataFrame(jsplit)
            jdf["time"] = pd.to_datetime(jdf["time"], errors="coerce")
            jdf = jdf.sort_values("time").reset_index(drop=True)

            pkl_site = pkl_s[pkl_s["site_id"] == sid].sort_values("time").reset_index(drop=True)

            merged = pd.merge(
                jdf[["time", "pred_mw"]].rename(columns={"pred_mw": "pred_json"}),
                pkl_site[["time", col]].rename(columns={col: "pred_pkl"}),
                on="time", how="inner",
            )
            if len(merged) == 0:
                continue

            diff = (merged["pred_json"] - merged["pred_pkl"]).abs()
            max_diff = float(diff.max())
            mean_diff = float(diff.mean())
            diffs.append({
                "site_id": sid, "split": split, "pred_col": col,
                "n_rows": len(merged), "max_diff": max_diff, "mean_diff": mean_diff,
            })

        if diffs:
            df = pd.DataFrame(diffs)
            worst = df.sort_values("max_diff", ascending=False).iloc[0]
            rows.append({
                "split": split,
                "pred_col": col,
                "n_sites": len(df),
                "max_diff_site": worst["site_id"],
                "max_diff": worst["max_diff"],
                "mean_diff": df["mean_diff"].mean(),
            })
    return pd.DataFrame(rows)


def diagnose_by_site(pkl_df: pd.DataFrame, json_data: dict, pred_col_by_split: dict) -> pd.DataFrame:
    """逐站点诊断：找出每个站点的最大差异及来源 split"""
    rows = []
    for sid in sorted(json_data.keys()):
        for split in ["train", "valid", "test"]:
            col = pred_col_by_split[split]
            jsplit = [r for r in json_data[sid] if r.get("split") == split]
            if not jsplit:
                continue

            jdf = pd.DataFrame(jsplit)
            jdf["time"] = pd.to_datetime(jdf["time"], errors="coerce")
            jdf = jdf.sort_values("time").reset_index(drop=True)

            pkl_site = pkl_df[(pkl_df["site_id"] == sid) & (pkl_df["split"] == split)].sort_values("time").reset_index(drop=True)

            merged = pd.merge(
                jdf[["time", "pred_mw"]].rename(columns={"pred_mw": "pred_json"}),
                pkl_site[["time", col]].rename(columns={col: "pred_pkl"}),
                on="time", how="inner",
            )
            if len(merged) == 0:
                continue

            diff = (merged["pred_json"] - merged["pred_pkl"]).abs()
            rows.append({
                "site_id": sid,
                "split": split,
                "pred_col": col,
                "n_matched": len(merged),
                "max_diff": float(diff.max()),
                "mean_diff": float(diff.mean()),
            })

    return pd.DataFrame(rows)


def find_worst_examples(pkl_df: pd.DataFrame, json_data: dict, pred_col_by_split: dict, top_n: int = 5) -> pd.DataFrame:
    """找到差异最大的具体行"""
    all_diffs = []
    for sid in sorted(json_data.keys()):
        for split in ["train", "valid", "test"]:
            col = pred_col_by_split[split]
            jsplit = [r for r in json_data[sid] if r.get("split") == split]
            if not jsplit:
                continue

            jdf = pd.DataFrame(jsplit)
            jdf["time"] = pd.to_datetime(jdf["time"], errors="coerce")

            pkl_site = pkl_df[(pkl_df["site_id"] == sid) & (pkl_df["split"] == split)]

            merged = pd.merge(
                jdf[["time", "pred_mw"]].rename(columns={"pred_mw": "pred_json"}),
                pkl_site[["time", col]].rename(columns={col: "pred_pkl"}),
                on="time", how="inner",
            )
            if len(merged) == 0:
                continue

            merged["diff"] = (merged["pred_json"] - merged["pred_pkl"]).abs()
            merged["site_id"] = sid
            merged["split"] = split
            merged["pred_col"] = col
            top = merged.sort_values("diff", ascending=False).head(top_n)
            for _, row in top.iterrows():
                all_diffs.append({
                    "site_id": row["site_id"],
                    "split": row["split"],
                    "pred_col": row["pred_col"],
                    "time": row["time"],
                    "pred_json": row["pred_json"],
                    "pred_pkl": row["pred_pkl"],
                    "diff": row["diff"],
                })

    df = pd.DataFrame(all_diffs)
    if len(df) > 0:
        df = df.sort_values("diff", ascending=False).head(20)
    return df


def main():
    parser = argparse.ArgumentParser(description="诊断 dashboard 预测值差异")
    parser.add_argument("--output-root", type=str, default=None,
                        help="输出根目录 (default: output/pv_pipeline)")
    args = parser.parse_args()

    if args.output_root:
        out_dir = PROJECT_ROOT / args.output_root
    else:
        out_dir = PROJECT_ROOT / "output" / "pv_pipeline"

    print("=" * 60)
    print("Dashboard 预测值差异诊断")
    print(f"Output root: {out_dir}")
    print("=" * 60)

    pkl_df = load_pkl(out_dir)
    site_dir = out_dir / "interactive_dashboard" / "site_series"
    if not site_dir.exists():
        print(f"[ERROR] site_series not found: {site_dir}")
        sys.exit(1)
    json_data = load_json_series(site_dir)

    # Determine prediction column per split (same as export script)
    pred_col_by_split = {}
    for split in HISTORY_SPLITS:
        col = resolve_best_pred_col_for_split(pkl_df, split)
        pred_col_by_split[split] = col
    print(f"\n  [pred_col_by_split] {pred_col_by_split}")

    # 1. Summary by split
    print("\n" + "=" * 60)
    print("## 按 Split 诊断")
    print("=" * 60)
    by_split = diagnose_by_split(pkl_df, json_data, pred_col_by_split)
    print(by_split.to_string(index=False))

    # 2. By site
    by_site = diagnose_by_site(pkl_df, json_data, pred_col_by_split)
    worst_sites = by_site.sort_values("max_diff", ascending=False).head(20)
    print("\n" + "=" * 60)
    print("## 最差站点 (max_diff)")
    print("=" * 60)
    print(worst_sites.to_string(index=False))

    # 3. Worst examples
    worst_examples = find_worst_examples(pkl_df, json_data, pred_col_by_split, top_n=3)
    print("\n" + "=" * 60)
    print("## 差异最大的具体行 (top 20)")
    print("=" * 60)
    if len(worst_examples) > 0:
        pd.set_option('display.max_colwidth', 40)
        print(worst_examples.to_string(index=False))
    else:
        print("No mismatches found!")

    # 4. Write outputs
    diagnostics_dir = out_dir / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    by_split.to_csv(diagnostics_dir / "round94_4_dashboard_mismatch_by_split.csv", index=False)
    by_site.to_csv(diagnostics_dir / "round94_4_dashboard_mismatch_by_site.csv", index=False)
    if len(worst_examples) > 0:
        worst_examples.to_csv(diagnostics_dir / "round94_4_dashboard_mismatch_examples.csv", index=False)

    # Summary markdown
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    worst_overall = by_site["max_diff"].max()
    worst_site = by_site.sort_values("max_diff", ascending=False).iloc[0] if len(by_site) > 0 else None

    summary_lines = [
        f"# Dashboard 预测值差异诊断报告\n\n",
        f"**生成时间**: {now}\n\n",
        f"## 诊断结论\n\n",
        f"**整体最大差异**: {worst_overall:.6f} MW\n\n",
        f"**最大差异站点**: {worst_site['site_id'] if worst_site is not None else 'N/A'} "
        f"({worst_site['split'] if worst_site is not None else ''}, 列={worst_site['pred_col'] if worst_site is not None else ''})\n\n",
        f"## 预测列选择（与 export 脚本一致）\n\n",
    ]
    for split, col in sorted(pred_col_by_split.items()):
        summary_lines.append(f"- {split}: **{col}**\n")
    summary_lines.append("\n## 按 Split 统计\n\n")
    summary_lines.append(by_split.to_markdown(index=False))
    summary_lines.append("\n## 最差站点\n\n")
    summary_lines.append(worst_sites.head(10).to_markdown(index=False))

    (diagnostics_dir / "round94_4_dashboard_mismatch_summary.md").write_text(
        "".join(summary_lines), encoding="utf-8")

    print(f"\n[OK] 诊断输出:")
    print(f"  - {diagnostics_dir / 'round94_4_dashboard_mismatch_by_split.csv'}")
    print(f"  - {diagnostics_dir / 'round94_4_dashboard_mismatch_by_site.csv'}")
    print(f"  - {diagnostics_dir / 'round94_4_dashboard_mismatch_examples.csv'}")
    print(f"  - {diagnostics_dir / 'round94_4_dashboard_mismatch_summary.md'}")


if __name__ == "__main__":
    import sys
    main()
