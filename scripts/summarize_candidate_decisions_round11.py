#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Round11：汇总所有候选晋级决策，生成排行榜"""
from __future__ import annotations

from pathlib import Path
import json
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"
METRICS.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)


def main():
    rows = []
    for path in sorted(METRICS.glob("round10_candidate_decision_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cand = data.get("candidate_metrics", {})
        best = data.get("best_metrics", {})
        rows.append({
            "candidate_name": data.get("candidate_name", path.stem.replace("round10_candidate_decision_", "")),
            "accepted": bool(data.get("accepted", False)),
            "candidate_overall_nrmse_pct": cand.get("overall_nrmse_pct"),
            "best_overall_nrmse_pct": best.get("overall_nrmse_pct"),
            "overall_improve_pp": data.get("overall_improve_pp"),
            "candidate_midday_nrmse_pct": cand.get("midday_overall_nrmse_pct"),
            "best_midday_nrmse_pct": best.get("midday_overall_nrmse_pct"),
            "midday_improve_pp": data.get("midday_improve_pp"),
            "candidate_mae_mw": cand.get("mae_mw"),
            "candidate_rmse_mw": cand.get("rmse_mw"),
            "best_mae_mw": best.get("mae_mw"),
            "best_rmse_mw": best.get("rmse_mw"),
            "candidate_score": data.get("candidate_score"),
            "best_score": data.get("best_score"),
            "reasons": "；".join(data.get("reasons", [])),
            "decision_file": str(path.relative_to(PROJECT_ROOT)),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(
            ["accepted", "overall_improve_pp"],
            ascending=[False, False],
        )

    out_csv = METRICS / "round11_candidate_leaderboard.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    lines = ["# 候选模型晋级记录 Round11", ""]
    lines.append("> 只有 `accepted=true` 的候选才允许覆盖 final/best。")
    lines.append("")
    if df.empty:
        lines.append("暂无候选决策记录。")
    else:
        lines.append(
            "| 候选 | 晋级 | 候选 NRMSE | best NRMSE | 改善 pp | "
            "候选 MAE | 候选 RMSE | 拒绝原因 |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
        for _, r in df.iterrows():
            mae_str = f"{r['candidate_mae_mw']:.4f}" if pd.notna(r.get("candidate_mae_mw")) else "—"
            rmse_str = f"{r['candidate_rmse_mw']:.4f}" if pd.notna(r.get("candidate_rmse_mw")) else "—"
            lines.append(
                f"| {r['candidate_name']} | {r['accepted']} | "
                f"{r['candidate_overall_nrmse_pct']:.4f} | {r['best_overall_nrmse_pct']:.4f} | "
                f"{r['overall_improve_pp']:.4f} | "
                f"{mae_str} | {rmse_str} | "
                f"{r['reasons']} |"
            )

    out_md = DOCS / "候选模型晋级记录_Round11.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")

    print(f"已生成: {out_csv}")
    print(f"已生成: {out_md}")
    print(df.to_string(index=False) if not df.empty else "暂无候选记录")


if __name__ == "__main__":
    main()
