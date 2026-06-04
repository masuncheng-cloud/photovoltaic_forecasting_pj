#!/usr/bin/env python3
"""
compare_pipeline_outputs.py
========================
对比两个 pipeline 输出目录的核心指标，生成对比报告。

用法：
    python scripts/compare_pipeline_outputs.py \
        --old-output output/pv_pipeline \
        --new-output output/pv_pipeline_round94_3_era5_expanded_clean_20260604_225618 \
        --report docs/Round94_3_新旧训练结果对比报告.md
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def load_hourly_consistent(root: Path) -> pd.DataFrame | None:
    p = root / "metrics" / "hourly_nrmse_consistent.csv"
    if p.exists():
        return pd.read_csv(p)
    return None


def load_site_metrics(root: Path) -> pd.DataFrame | None:
    p = root / "metrics" / "site_metrics_consistent.csv"
    if p.exists():
        return pd.read_csv(p)
    return None


def load_city_hourly(root: Path) -> pd.DataFrame | None:
    # Try round36_city_hourly_nrmse.csv first
    p = root / "metrics" / "round36_city_hourly_nrmse.csv"
    if p.exists():
        return pd.read_csv(p)
    return None


def compare_hourly(hr_old, hr_new):
    rows = []
    for label, hr in [("旧", hr_old), ("新", hr_new)]:
        if hr is None:
            continue
        for hour_range, label_h in [((6, 19), "6-19点"), ((10, 14), "10-14点")]:
            sub = hr[hr["hour"].between(*hour_range)]
            rows.append({
                "范围": label_h,
                "来源": label,
                "city_nrmse_mean": sub["city_nrmse_pct"].mean(),
                "city_nrmse_min": sub["city_nrmse_pct"].min(),
                "city_nrmse_max": sub["city_nrmse_pct"].max(),
                "site_avg_nrmse_mean": sub["site_avg_nrmse_pct"].mean(),
            })
    return pd.DataFrame(rows)


def compare_sites(sm_old, sm_new):
    rows = []
    for label, sm in [("旧", sm_old), ("新", sm_new)]:
        if sm is None:
            continue
        status_counts = sm["site_status"].value_counts()
        normal_sites = sm[sm["site_status"] == "正常评价"]
        rows.append({
            "来源": label,
            "总站点": len(sm),
            "正常评价": len(normal_sites),
            "测试期分布漂移": int(status_counts.get("测试期分布漂移", 0)),
            "系统性偏差": int(status_counts.get("系统性偏差", 0)),
            "测试期无有效发电": int(status_counts.get("测试期无有效发电", 0)),
            "无测试预测结果": int(status_counts.get("无测试预测结果", 0)),
            "站点NRMSE均值": sm["nrmse_pct"].mean(),
            "站点NRMSE最大": sm["nrmse_pct"].max(),
            "站点NRMSE最小": sm["nrmse_pct"].min(),
            "正常站点NRMSE均值": normal_sites["nrmse_pct"].mean() if len(normal_sites) else np.nan,
            "正常站点NRMSE最大": normal_sites["nrmse_pct"].max() if len(normal_sites) else np.nan,
        })
    return pd.DataFrame(rows)


def compare_specific_sites(sm_old, sm_new, site_ids):
    rows = []
    for sid in site_ids:
        for label, sm in [("旧", sm_old), ("新", sm_new)]:
            if sm is None:
                continue
            row = sm[sm["site_id"] == sid]
            if len(row):
                rows.append({
                    "站点": sid,
                    "来源": label,
                    "site_status": row["site_status"].values[0],
                    "nrmse_pct": row["nrmse_pct"].values[0],
                    "bias_MW": row["bias_MW"].values[0],
                })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="对比两个 pipeline 输出目录的核心指标")
    parser.add_argument("--old-output", required=True, help="旧输出目录")
    parser.add_argument("--new-output", required=True, help="新输出目录")
    parser.add_argument("--report", help="输出报告路径（Markdown）")
    args = parser.parse_args()

    old_root = Path(args.old_output)
    new_root = Path(args.new_output)

    print("=" * 60)
    print("新旧训练结果对比")
    print("=" * 60)
    print(f"旧输出: {old_root}")
    print(f"新输出: {new_root}")

    # Load data
    hr_old = load_hourly_consistent(old_root)
    hr_new = load_hourly_consistent(new_root)
    sm_old = load_site_metrics(old_root)
    sm_new = load_site_metrics(new_root)
    city_old = load_city_hourly(old_root)
    city_new = load_city_hourly(new_root)

    # City hourly comparison
    print("\n## 城市级 NRMSE 对比")
    print("| 范围 | 来源 | 城市NRMSE均值 | 城市NRMSE范围 |")
    print("|---|---|---|---|")
    if city_old is not None:
        for hr, label in [(city_old, "旧"), (city_new, "新")]:
            if hr is None:
                continue
            for lo, hi, label_h in [(6, 19, "6-19点"), (10, 14, "10-14点")]:
                sub = hr[hr["hour"].between(lo, hi)]
                print(f"| {label_h} | {label} | {sub['nrmse_city_pct'].mean():.4f}% | "
                      f"{sub['nrmse_city_pct'].min():.2f}% ~ {sub['nrmse_city_pct'].max():.2f}% |")

    # Site comparison
    print("\n## 站点级指标对比")
    site_comp = compare_sites(sm_old, sm_new)
    if len(site_comp):
        for _, row in site_comp.iterrows():
            print(f"\n### {row['来源']} 结果")
            print(f"- 总站点: {row['总站点']}")
            print(f"- 正常评价: {row['正常评价']}")
            print(f"- 站点NRMSE均值: {row['站点NRMSE均值']:.4f}%")
            print(f"- 站点NRMSE最大: {row['站点NRMSE最大']:.4f}%")
            print(f"- 正常站点NRMSE均值: {row['正常站点NRMSE均值']:.4f}%" if not np.isnan(row['正常站点NRMSE均值']) else "- 正常站点NRMSE均值: N/A")

    # Specific sites (S115, S116)
    print("\n## S115/S116 专项对比")
    sp = compare_specific_sites(sm_old, sm_new, ["S115", "S116"])
    if len(sp):
        for sid in ["S115", "S116"]:
            rows = sp[sp["站点"] == sid]
            if len(rows) == 2:
                old_r = rows[rows["来源"] == "旧"].iloc[0]
                new_r = rows[rows["来源"] == "新"].iloc[0]
                delta = new_r["nrmse_pct"] - old_r["nrmse_pct"]
                print(f"\n### {sid}")
                print(f"- 旧: {old_r['nrmse_pct']:.4f}% (状态: {old_r['site_status']})")
                print(f"- 新: {new_r['nrmse_pct']:.4f}% (状态: {new_r['site_status']})")
                print(f"- 变化: {delta:+.4f}%")

    # Summary
    print("\n## 总结")
    if sm_old is not None and sm_new is not None:
        old_mean = sm_old["nrmse_pct"].mean()
        new_mean = sm_new["nrmse_pct"].mean()
        delta = new_mean - old_mean
        print(f"站点NRMSE均值: 旧={old_mean:.4f}% 新={new_mean:.4f}% Δ={delta:+.4f}%")

    print("=" * 60)

    # Generate Markdown report
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# 新旧训练结果对比报告\n", f"**旧输出**: `{old_root}`\n", f"**新输出**: `{new_root}`\n", "## 指标对比\n"]
        if sm_old is not None and sm_new is not None:
            lines.append(f"| 指标 | 旧结果 | 新结果 | 变化 |\n")
            lines.append(f"|---|---|---|---|\n")
            old_mean = sm_old["nrmse_pct"].mean()
            new_mean = sm_new["nrmse_pct"].mean()
            lines.append(f"| 站点NRMSE均值 | {old_mean:.4f}% | {new_mean:.4f}% | {new_mean-old_mean:+.4f}% |\n")
            old_max = sm_old["nrmse_pct"].max()
            new_max = sm_new["nrmse_pct"].max()
            lines.append(f"| 站点NRMSE最大 | {old_max:.4f}% | {new_max:.4f}% | {new_max-old_max:+.4f}% |\n")
            old_norm = sm_old[sm_old["site_status"]=="正常评价"]["nrmse_pct"]
            new_norm = sm_new[sm_new["site_status"]=="正常评价"]["nrmse_pct"]
            lines.append(f"| 正常评价站点NRMSE均值 | {old_norm.mean():.4f}% (n={len(old_norm)}) | {new_norm.mean():.4f}% (n={len(new_norm)}) | {new_norm.mean()-old_norm.mean():+.4f}% |\n")
            lines.append(f"| 正常评价站点数 | {len(old_norm)} | {len(new_norm)} | {len(new_norm)-len(old_norm):+} |\n")
            for sid in ["S115", "S116"]:
                o = sm_old[sm_old["site_id"]==sid]["nrmse_pct"].values
                n = sm_new[sm_new["site_id"]==sid]["nrmse_pct"].values
                if len(o) and len(n):
                    lines.append(f"| {sid} NRMSE | {o[0]:.4f}% | {n[0]:.4f}% | {n[0]-o[0]:+.4f}% |\n")
        report_path.write_text("".join(lines), encoding="utf-8")
        print(f"\n报告已生成: {report_path}")


if __name__ == "__main__":
    main()
