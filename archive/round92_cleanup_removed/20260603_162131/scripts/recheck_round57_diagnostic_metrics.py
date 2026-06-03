#!/usr/bin/env python3
"""
recheck_round57_diagnostic_metrics.py
====================================
独立复核 Round57 诊断指标是否正确。

必须从 distributed_predictions_final_eval.pkl 从零计算，不调用 Round57 诊断函数。

输出：
  output/pv_pipeline/validation/round58_recheck_hourly_metrics.csv
  output/pv_pipeline/validation/round58_recheck_monthly_metrics.csv
  output/pv_pipeline/validation/round58_recheck_scene_metrics.csv
  output/pv_pipeline/validation/round58_recheck_site_hour_bad_hours.csv
  output/pv_pipeline/validation/round58_recheck_findings.csv
  output/pv_pipeline/validation/round58_recheck_report.md

用法：
    python scripts/recheck_round57_diagnostic_metrics.py
"""

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PRED = ROOT / "output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl"
DIAG = ROOT / "output/pv_pipeline/diagnostics"
VAL = ROOT / "output/pv_pipeline/validation"
VAL.mkdir(parents=True, exist_ok=True)

PRED_COL = "power_pred_final"


def rmse(a, p):
    a = np.asarray(a, dtype=float)
    p = np.asarray(p, dtype=float)
    if len(a) == 0:
        return np.nan
    return float(np.sqrt(np.mean((p - a) ** 2)))


def mae(a, p):
    a = np.asarray(a, dtype=float)
    p = np.asarray(p, dtype=float)
    if len(a) == 0:
        return np.nan
    return float(np.mean(np.abs(p - a)))


def nrmse(a, p, den):
    den = float(den)
    if den <= 0:
        return np.nan
    return rmse(a, p) / den * 100


def bias_pct(a, p):
    a_sum = float(np.sum(a))
    p_sum = float(np.sum(p))
    if abs(a_sum) < 1e-12:
        return np.nan
    return (p_sum - a_sum) / a_sum * 100


def pred_actual(a, p):
    a_sum = float(np.sum(a))
    if abs(a_sum) < 1e-12:
        return np.nan
    return float(np.sum(p)) / a_sum


def main():
    print("=" * 60)
    print("Round57 诊断口径独立复核")
    print("=" * 60)

    # ── Load data ───────────────────────────────────────────────────────────
    df = pd.read_pickle(PRED)
    print(f"[INFO] loaded eval: {df.shape}")

    # Normalize columns
    time_col = "time" if "time" in df.columns else "timestamp"
    id_col = "site_id" if "site_id" in df.columns else "station_id"
    df["_time"] = pd.to_datetime(df[time_col], errors="coerce")
    if "hour" not in df.columns:
        df["hour"] = df["_time"].dt.hour
    if "month" not in df.columns:
        df["month"] = df["_time"].dt.month

    # Canonical filter (already test-only but enforce)
    if "split" in df.columns:
        df = df[df["split"].eq("test")].copy()
    if "_is_future" in df.columns and df["_is_future"].any():
        df = df[~df["_is_future"].fillna(False)].copy()

    df = df[df["hour"].between(6, 19)].copy()
    df = df[df["power_mw"].notna() & df[PRED_COL].notna() & (df["capacity_mw"] > 0)].copy()

    print(f"[INFO] after filter: {len(df)} rows, {df[id_col].nunique()} sites")

    required = [id_col, time_col, "power_mw", PRED_COL, "capacity_mw", "hour", "month"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"missing required columns: {missing}")

    # ── Capacity lookups ───────────────────────────────────────────────────
    cap_by_site = (
        df[[id_col, "capacity_mw"]]
        .drop_duplicates(id_col)
        .set_index(id_col)["capacity_mw"]
    )
    city_cap = float(cap_by_site.sum())

    def site_mean_nrmse(sub_df):
        """Mean of per-site NRMSE (each site normalized by its own capacity)."""
        vals = []
        for sid, sdf in sub_df.groupby(id_col):
            cap = cap_by_site.get(sid, np.nan)
            if pd.isna(cap) or cap <= 0:
                continue
            v = nrmse(sdf["power_mw"].values, sdf[PRED_COL].values, cap)
            if np.isfinite(v):
                vals.append(v)
        return float(np.nanmean(vals)) if vals else np.nan

    # ── Hourly metrics ───────────────────────────────────────────────────
    print("\n[1] 计算小时级指标（独立复算）...")
    hour_rows = []
    for hour, hdf in df.groupby("hour"):
        agg = hdf.groupby("_time", as_index=False).agg(
            actual=("power_mw", "sum"),
            pred=(PRED_COL, "sum"),
        )
        hour_rows.append({
            "hour": int(hour),
            "rows": len(hdf),
            "site_mean_nrmse_percent_recalc": site_mean_nrmse(hdf),
            "city_nrmse_percent_recalc": nrmse(
                agg["actual"].values, agg["pred"].values, city_cap
            ),
            "city_bias_percent_recalc": bias_pct(agg["actual"].values, agg["pred"].values),
            "city_pred_actual_ratio_recalc": pred_actual(agg["actual"].values, agg["pred"].values),
            "actual_sum": float(hdf["power_mw"].sum()),
            "pred_sum": float(hdf[PRED_COL].sum()),
            "zero_ratio_actual": float((hdf["power_mw"] == 0).mean()),
            "zero_ratio_pred": float((hdf[PRED_COL].fillna(0) == 0).mean()),
        })
    hour_re = pd.DataFrame(hour_rows).sort_values("hour").reset_index(drop=True)
    hour_re.to_csv(VAL / "round58_recheck_hourly_metrics.csv", index=False, encoding="utf-8-sig")
    print(f"    → round58_recheck_hourly_metrics.csv ({len(hour_re)} rows)")

    # ── Monthly metrics ───────────────────────────────────────────────────
    print("\n[2] 计算月份指标（独立复算）...")
    month_rows = []
    for month, mdf in df.groupby("month"):
        agg = mdf.groupby("_time", as_index=False).agg(
            actual=("power_mw", "sum"),
            pred=(PRED_COL, "sum"),
        )
        month_rows.append({
            "month": int(month),
            "rows": len(mdf),
            "site_mean_nrmse_percent_recalc": site_mean_nrmse(mdf),
            "city_nrmse_percent_recalc": nrmse(
                agg["actual"].values, agg["pred"].values, city_cap
            ),
            "city_bias_percent_recalc": bias_pct(agg["actual"].values, agg["pred"].values),
            "city_pred_actual_ratio_recalc": pred_actual(agg["actual"].values, agg["pred"].values),
        })
    month_re = pd.DataFrame(month_rows).sort_values("month").reset_index(drop=True)
    month_re.to_csv(VAL / "round58_recheck_monthly_metrics.csv", index=False, encoding="utf-8-sig")
    print(f"    → round58_recheck_monthly_metrics.csv ({len(month_re)} rows)")

    # ── Scene metrics ───────────────────────────────────────────────────
    scene_col = "scene_v151" if "scene_v151" in df.columns else None
    print(f"\n[3] 计算场景指标（独立复算）...")
    scene_rows = []
    if scene_col:
        for scene, sdf in df.groupby(scene_col):
            agg = sdf.groupby("_time", as_index=False).agg(
                actual=("power_mw", "sum"),
                pred=(PRED_COL, "sum"),
            )
            scene_rows.append({
                "scene": str(scene),
                "rows": len(sdf),
                "site_mean_nrmse_percent_recalc": site_mean_nrmse(sdf),
                "city_nrmse_percent_recalc": nrmse(
                    agg["actual"].values, agg["pred"].values, city_cap
                ),
                "bias_percent_recalc": bias_pct(
                    sdf["power_mw"].values, sdf[PRED_COL].values
                ),
                "pred_actual_ratio_recalc": pred_actual(
                    sdf["power_mw"].values, sdf[PRED_COL].values
                ),
            })
    scene_re = pd.DataFrame(scene_rows) if scene_rows else pd.DataFrame()
    if not scene_re.empty:
        scene_re.to_csv(VAL / "round58_recheck_scene_metrics.csv", index=False, encoding="utf-8-sig")
        print(f"    → round58_recheck_scene_metrics.csv ({len(scene_re)} rows)")
    else:
        print("    [SKIP] scene_v151 not available")

    # ── Site-hour bad hours ─────────────────────────────────────────────
    print("\n[4] 计算站点-小时最差小时...")
    site_hour_rows = []
    for sid, sdf in df.groupby(id_col):
        cap = cap_by_site.get(sid, np.nan)
        for hour, sh in sdf.groupby("hour"):
            site_hour_rows.append({
                id_col: sid,
                "hour": int(hour),
                "rows": len(sh),
                "nrmse_percent_recalc": nrmse(
                    sh["power_mw"].values, sh[PRED_COL].values, cap
                ),
                "bias_percent_recalc": bias_pct(
                    sh["power_mw"].values, sh[PRED_COL].values
                ),
                "pred_actual_ratio_recalc": pred_actual(
                    sh["power_mw"].values, sh[PRED_COL].values
                ),
                "actual_zero_ratio": float((sh["power_mw"] == 0).mean()),
                "pred_zero_ratio": float((sh[PRED_COL].fillna(0) == 0).mean()),
            })
    site_hour_re = pd.DataFrame(site_hour_rows)
    bad_hours = (
        site_hour_re.sort_values([id_col, "nrmse_percent_recalc"], ascending=[True, False])
        .groupby(id_col)
        .head(3)
        .groupby(id_col)
        .agg(
            main_bad_hours=("hour", lambda x: "|".join(map(str, x))),
            main_bad_hour_nrmse=("nrmse_percent_recalc", "max"),
        )
        .reset_index()
    )
    bad_hours.to_csv(VAL / "round58_recheck_site_hour_bad_hours.csv", index=False, encoding="utf-8-sig")
    print(f"    → round58_recheck_site_hour_bad_hours.csv ({len(bad_hours)} sites)")

    # ── Findings ────────────────────────────────────────────────────────
    print("\n[5] 对比 Round57 诊断结果，检查问题是否真实存在...")
    findings = []

    def add_finding(code, severity, exists, evidence, recommended_fix):
        findings.append({
            "code": code,
            "severity": severity,
            "exists": bool(exists),
            "evidence": evidence,
            "recommended_fix": recommended_fix,
        })

    # F1: site_mean == city_nrmse (identical columns)
    h57_path = DIAG / "round57_error_by_hour.csv"
    if h57_path.exists():
        h57 = pd.read_csv(h57_path)
        cols57 = list(h57.columns)
        site_col57 = "site_mean_nrmse_percent"
        city_col57 = "city_nrmse_percent"
        if site_col57 in cols57 and city_col57 in cols57:
            identical = bool(
                np.allclose(h57[site_col57], h57[city_col57], equal_nan=True)
            )
            add_finding(
                "HOUR_SITE_CITY_IDENTICAL",
                "high",
                identical,
                f"Round57 hour: site_mean_nrmse == city_nrmse for all rows = {identical}",
                "Separate station-mean NRMSE and city-aggregated NRMSE calculations",
            )

    # F2: hour city NRMSE mismatch
    if h57_path.exists() and len(hour_re):
        h57 = pd.read_csv(h57_path)
        merged_h = h57.merge(hour_re, on="hour", how="inner")
        if len(merged_h):
            diffs = np.abs(merged_h["city_nrmse_percent"] - merged_h["city_nrmse_percent_recalc"])
            max_diff = float(np.nanmax(diffs)) if len(diffs) else 0.0
            add_finding(
                "HOUR_CITY_NRMSE_MISMATCH",
                "high",
                max_diff > 0.1,
                f"max abs diff Round57 city_nrmse vs independent recalc = {max_diff:.4f}%",
                "Replace hourly city NRMSE with city-aggregated formula",
            )

    # F3: hour site_mean NRMSE mismatch
    if h57_path.exists() and len(hour_re):
        merged_h = h57.merge(hour_re, on="hour", how="inner")
        if len(merged_h):
            diffs = np.abs(merged_h["site_mean_nrmse_percent"] - merged_h["site_mean_nrmse_percent_recalc"])
            max_diff = float(np.nanmax(diffs)) if len(diffs) else 0.0
            add_finding(
                "HOUR_SITE_NRMSE_MISMATCH",
                "high",
                max_diff > 0.1,
                f"max abs diff Round57 site_mean vs independent recalc = {max_diff:.4f}%",
                "Replace hourly site_mean NRMSE with per-site mean NRMSE",
            )

    # F4: month city NRMSE mismatch
    m57_path = DIAG / "round57_error_by_month.csv"
    if m57_path.exists() and len(month_re):
        m57 = pd.read_csv(m57_path)
        merged_m = m57.merge(month_re, on="month", how="inner")
        if len(merged_m):
            diffs = np.abs(merged_m["city_nrmse_percent"] - merged_m["city_nrmse_percent_recalc"])
            max_diff = float(np.nanmax(diffs)) if len(diffs) else 0.0
            add_finding(
                "MONTH_CITY_NRMSE_MISMATCH",
                "high",
                max_diff > 0.1,
                f"max abs diff Round57 monthly city vs independent recalc = {max_diff:.4f}%",
                "Replace monthly metrics with independent formula",
            )
            old_worst = int(merged_m.sort_values("city_nrmse_percent", ascending=False).iloc[0]["month"])
            new_worst = int(merged_m.sort_values("city_nrmse_percent_recalc", ascending=False).iloc[0]["month"])
            add_finding(
                "MONTH_CONCLUSION_MAY_BE_WRONG",
                "medium",
                old_worst != new_worst,
                f"Round57 worst month={old_worst}, recalculated worst month={new_worst}",
                "Update report conclusion according to recalculated monthly metrics",
            )

    # F5: main_bad_hours empty
    prio57_path = DIAG / "round57_priority_sites.csv"
    if prio57_path.exists():
        pr = pd.read_csv(prio57_path)
        has_col = "main_bad_hours" in pr.columns
        all_empty = has_col and pr["main_bad_hours"].isna().all()
        add_finding(
            "MAIN_BAD_HOURS_EMPTY",
            "medium",
            all_empty or not has_col,
            f"main_bad_hours column {'missing' if not has_col else 'all NaN'} in priority_sites",
            "Join top-3 bad hours from site-hour metrics into priority_sites",
        )

    # F7: daytime_scene_night over-trigger
    site57_path = DIAG / "round57_error_by_site.csv"
    if site57_path.exists():
        s57 = pd.read_csv(site57_path)
        if "risk_flags" in s57.columns:
            cnt = int(s57["risk_flags"].fillna("").str.contains("daytime_scene_night").sum())
            total = len(s57)
            # Also check the raw field if available
            night_ratio_col = "scene_night_ratio_10_14" if "scene_night_ratio_10_14" in s57.columns else None
            if night_ratio_col:
                mean_night_ratio = float(s57[night_ratio_col].mean())
            else:
                mean_night_ratio = None
            add_finding(
                "DAYTIME_SCENE_NIGHT_OVERTRIGGER",
                "medium",
                cnt > 10,
                f"daytime_scene_night flagged sites={cnt}/{total} ({cnt/total*100:.0f}%), "
                f"mean scene_night_ratio_10_14={mean_night_ratio}",
                "Use test 10-14 or daytime-specific night ratio instead of broad 6-19 night ratio",
            )

    # F7: NaN bias sites
    if site57_path.exists():
        s57 = pd.read_csv(site57_path)
        nan_bias = int(s57["bias_percent"].isna().sum()) if "bias_percent" in s57.columns else 0
        total = len(s57)
        if nan_bias > 0:
            nan_sites_df = s57[s57["bias_percent"].isna()][["station_id", "risk_flags"]].head(5)
            # Check if they are correctly classified as zero_actual_sum (not over/under prediction)
            all_correct = all(
                "zero_actual_sum" in str(r.get("risk_flags", ""))
                and "over_prediction" not in str(r.get("risk_flags", ""))
                and "under_prediction" not in str(r.get("risk_flags", ""))
                for _, r in nan_sites_df.iterrows()
            )
            nan_sites = nan_sites_df.to_string(index=False)
        else:
            all_correct = True
            nan_sites = "none"
        # If NaN bias exists AND they are still misclassified, that's a problem
        # If NaN bias exists but they are correctly classified (zero_actual_sum), it's NOT a problem
        add_finding(
            "NAN_BIAS_NEEDS_SEPARATE_CLASS",
            "medium",
            nan_bias > 0 and not all_correct,
            f"sites with NaN bias={nan_bias}/{total}. "
            f"Correctly classified as zero_actual_sum: {all_correct}. "
            f"Sites: {nan_sites}",
            "Classify as zero_actual_sum, not over/under prediction",
        )

    # F8: overall site_mean and city_nrmse should differ
    if h57_path.exists() and len(hour_re):
        h57 = pd.read_csv(h57_path)
        mean_site_diff = float(np.nanmean(
            np.abs(h57["site_mean_nrmse_percent"] - h57["city_nrmse_percent"])
        ))
        add_finding(
            "HOUR_METRICS_SHOULD_DIFFER",
            "low",
            mean_site_diff < 0.01,
            f"mean abs diff between site_mean and city columns = {mean_site_diff:.6f}% (should be > 1%)",
            "Ensure site_mean and city_nrmse use different denominators",
        )

    findings_df = pd.DataFrame(findings)
    findings_df.to_csv(VAL / "round58_recheck_findings.csv", index=False, encoding="utf-8-sig")

    # Print findings
    print("\n" + "=" * 60)
    print("复核结论")
    print("=" * 60)
    for _, r in findings_df.iterrows():
        icon = "[!!]" if r["exists"] and r["severity"] == "high" else ("[~]" if r["exists"] else "[  ]")
        print(f"  {icon} {r['code']} ({r['severity']}): {'存在' if r['exists'] else '未确认'}")
        print(f"       证据: {r['evidence']}")
        if r["exists"]:
            print(f"       修复: {r['recommended_fix']}")

    # Write markdown report
    md_lines = [
        "# Round58 Round57 诊断口径独立复核报告\n",
        "## 1. 复核结论\n",
    ]
    for _, r in findings_df.iterrows():
        mark = "**存在**" if r["exists"] else "未确认"
        md_lines.append(f"- **{r['code']}**（{r['severity']}）：{mark}")
        md_lines.append(f"  - 证据：{r['evidence']}")
        if r["exists"]:
            md_lines.append(f"  - 修复建议：{r['recommended_fix']}")
        md_lines.append("")

    md_lines += [
        "\n## 2. 小时级复算结果\n",
        "| hour | rows | site_mean_nrmse% | city_nrmse% | bias% | P/A |\n",
        "|-----|-----:|----------------:|------------:|------:|----:|\n",
    ]
    for _, r in hour_re.iterrows():
        md_lines.append(
            f"| {int(r['hour'])} | {int(r['rows'])} "
            f"| {r['site_mean_nrmse_percent_recalc']:.2f} "
            f"| {r['city_nrmse_percent_recalc']:.2f} "
            f"| {r['city_bias_percent_recalc']:.2f} "
            f"| {r['city_pred_actual_ratio_recalc']:.4f} |\n"
        )

    md_lines += [
        "\n## 3. 月份复算结果\n",
        "| month | rows | site_mean_nrmse% | city_nrmse% | bias% | P/A |\n",
        "|-------|-----:|----------------:|------------:|------:|----:|\n",
    ]
    for _, r in month_re.iterrows():
        md_lines.append(
            f"| {int(r['month'])} | {int(r['rows'])} "
            f"| {r['site_mean_nrmse_percent_recalc']:.2f} "
            f"| {r['city_nrmse_percent_recalc']:.2f} "
            f"| {r['city_bias_percent_recalc']:.2f} "
            f"| {r['city_pred_actual_ratio_recalc']:.4f} |\n"
        )

    if not scene_re.empty:
        md_lines += [
            "\n## 4. 场景复算结果\n",
            "| scene | rows | site_mean_nrmse% | city_nrmse% | bias% | P/A |\n",
            "|-------|-----:|----------------:|------------:|------:|----:|\n",
        ]
        for _, r in scene_re.iterrows():
            md_lines.append(
                f"| {r['scene']} | {int(r['rows'])} "
                f"| {r['site_mean_nrmse_percent_recalc']:.2f} "
                f"| {r['city_nrmse_percent_recalc']:.2f} "
                f"| {r['bias_percent_recalc']:.2f} "
                f"| {r['pred_actual_ratio_recalc']:.4f} |\n"
            )

    md_lines += [
        "\n## 5. 处理建议\n",
        "只有 exists=True 的问题才进入修复。\n",
    ]

    (VAL / "round58_recheck_report.md").write_text("".join(md_lines), encoding="utf-8")
    print(f"\n[OK] 复核报告 → {VAL / 'round58_recheck_report.md'}")

    # Summary stats
    confirmed = findings_df[findings_df["exists"]]
    high_confirmed = confirmed[confirmed["severity"] == "high"]
    print(f"\n复核统计: {len(findings_df)} 项检查，{len(confirmed)} 项确认存在，"
          f"其中 {len(high_confirmed)} 项 high severity")
    if len(confirmed):
        print("\n确认存在的问题：")
        print(confirmed[["code", "severity", "recommended_fix"]].to_string(index=False))

    return findings_df


if __name__ == "__main__":
    main()
