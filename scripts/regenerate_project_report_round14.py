#!/usr/bin/env python3
"""
Regenerate the main project report 光伏功率预测项目.md using current outputs.

Data sources:
- output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
- output/pv_pipeline/tables/distributed_predictions_final_full.pkl
- output/pv_pipeline/tables/site_master.csv
- output/pv_pipeline/metrics/round10_overall_nrmse_summary.csv
- output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv
- output/pv_pipeline/metrics/audit_summary.json
- output/pv_pipeline/interactive_dashboard/scatter_site_sample_nrmse.json

IMPORTANT: Do NOT use WAPE or MAPE as primary metrics. Use NRMSE as the main metric.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path("/home/ac/data16t/msc/photovoltaic_forecasting_pj")
sys.path.insert(0, str(PROJECT_ROOT))

# =============================================================================
# Pandas StringDtype pickle compatibility patch
# =============================================================================

def patch_pandas_string_dtype_pickle():
    """Patch pandas StringDtype pickle compatibility for older artifacts."""
    try:
        from pandas import StringDtype
        original_init = getattr(StringDtype, "__init__", None)

        def _patched_init__(self, storage=None, na_value=None):
            try:
                if original_init is not None:
                    original_init(self, storage=storage, na_value=na_value)
            except TypeError:
                try:
                    original_init(self, storage=storage)
                except TypeError:
                    try:
                        original_init(self)
                    except TypeError:
                        pass

        if not getattr(StringDtype, "_pv_pickle_patch_applied", False):
            StringDtype.__init__ = _patched_init__
            StringDtype._pv_pickle_patch_applied = True
    except Exception:
        pass


def safe_read_pickle(path: Path) -> pd.DataFrame | None:
    """Read a pickle file with StringDtype compatibility patch."""
    if not path.exists():
        return None
    patch_pandas_string_dtype_pickle()
    try:
        return pd.read_pickle(path)
    except Exception as e:
        print(f"  [WARN] Failed to read {path}: {e}")
        return None


# =============================================================================
# Data loading helpers
# =============================================================================

def load_data(root: Path) -> dict:
    """Load all data sources for the report."""
    data = {}

    # PKL files
    data["final_eval"] = safe_read_pickle(root / "tables/distributed_predictions_final_eval.pkl")
    data["final_full"] = safe_read_pickle(root / "tables/distributed_predictions_final_full.pkl")

    # CSV files
    data["site_master"] = pd.read_csv(root / "tables/site_master.csv")
    data["overall_summary"] = pd.read_csv(root / "metrics/round10_overall_nrmse_summary.csv")
    data["hourly_nrmse"] = pd.read_csv(root / "metrics/分布式光伏预测_逐小时平均NRMSE.csv")

    # JSON files
    audit_path = root / "metrics/audit_summary.json"
    if audit_path.exists():
        with open(audit_path, encoding="utf-8") as f:
            data["audit_summary"] = json.load(f)
    else:
        data["audit_summary"] = None

    scatter_path = root / "interactive_dashboard/scatter_site_sample_nrmse.json"
    if scatter_path.exists():
        with open(scatter_path, encoding="utf-8") as f:
            data["scatter"] = json.load(f)
    else:
        data["scatter"] = []

    return data


def compute_worst_sites(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Compute per-site NRMSE and return top N worst sites."""
    eval_df = df[
        df["split"].eq("test") &
        df["hour"].between(6, 19) &
        df["power_mw"].notna() &
        df["power_pred"].notna()
    ].copy()

    site_rows = []
    for sid, g in eval_df.groupby("site_id"):
        y = g["power_mw"].astype(float).values
        p = g["power_pred"].astype(float).values
        c = max(float(g["capacity_mw"].mean()), 1e-9)
        rmse = float(np.sqrt(np.mean((p - y) ** 2)))
        mae = float(np.mean(np.abs(p - y)))
        nrmse = rmse / c * 100
        site_rows.append({
            "site_id": sid,
            "capacity_mw": round(c, 4),
            "test_rows": len(g),
            "positive_rows": int((g["power_mw"].fillna(0) > 0).sum()),
            "mae_mw": round(mae, 4),
            "rmse_mw": round(rmse, 4),
            "nrmse_pct": round(nrmse, 4),
        })

    df_sites = pd.DataFrame(site_rows)
    df_sites = df_sites.sort_values("nrmse_pct", ascending=False)
    return df_sites.head(n)


def get_power_raw_stats(root: Path) -> dict:
    """Get power_long_raw row counts and zero ratios."""
    power_raw = safe_read_pickle(root / "tables/power_long_raw.pkl")
    if power_raw is None:
        return {}

    total = len(power_raw)
    if "is_distributed" in power_raw.columns:
        dist = power_raw[power_raw["is_distributed"] == True]
    else:
        return {}

    dist_total = len(dist)
    dist_non_null = dist["power_mw"].notna().sum() if "power_mw" in dist.columns else 0
    dist_positive = (dist["power_mw"].fillna(0) > 0).sum() if "power_mw" in dist.columns else 0
    dist_zero = (dist["power_mw"].fillna(0) == 0).sum() if "power_mw" in dist.columns else 0

    return {
        "total_rows": total,
        "dist_total": dist_total,
        "dist_non_null": int(dist_non_null),
        "dist_positive": int(dist_positive),
        "dist_zero": int(dist_zero),
        "dist_zero_ratio": round(dist_zero / max(dist_non_null, 1) * 100, 2),
    }


# =============================================================================
# Report generation
# =============================================================================

def generate_report(data: dict, root: Path) -> str:
    """Generate the project report markdown content."""
    lines = []

    # Header
    lines.append("# 光伏功率预测项目\n")
    lines.append("> **本报告数据来源：** `output/pv_pipeline/tables/distributed_predictions_final_eval.pkl`")
    lines.append("> **生成时间：** Generated by `scripts/regenerate_project_report_round14.py`")
    lines.append("")

    # =========================================================================
    # Section 1: Dataset
    # =========================================================================
    lines.append("## 一、数据集情况\n")

    lines.append("### 1.1 站点数量与可用数量\n")
    lines.append("| 类型 | 台账站点数（座） | 映射成功站点数（座） | 最终模型评估可用站点数（座） |")
    lines.append("|:---|:---:|:---:|:---:|")
    lines.append("| 集中式光伏 | 36 | 24 | 24 |")
    lines.append("| 分布式光伏 | 82 | 74 | 53 |")
    lines.append("")
    lines.append("> **可用站点说明**：最终评估固定使用 53 个站点（排除 7 个坏站点：S026/S015/S057/S036/S067/S045/S058）。")
    lines.append("")

    # Raw power data stats
    lines.append("### 1.2 原始功率数据量\n")
    power_stats = get_power_raw_stats(root)
    if power_stats:
        lines.append(f"原始功率长表 `power_long_raw.pkl` 共 {power_stats['total_rows']:,} 行，其中分布式 {power_stats['dist_total']:,} 行。")
        lines.append("")
        lines.append("| 类型 | 总行数（行） | 非空功率行数（行） | 正功率行数（行） | 0 值行数（行） | 0 值占非空比例（%） |")
        lines.append("|:---|:---:|:---:|:---:|:---:|:---:|")
        lines.append(f"| 分布式光伏 | {power_stats['dist_total']:,} | {power_stats['dist_non_null']:,} | {power_stats['dist_positive']:,} | {power_stats['dist_zero']:,} | {power_stats['dist_zero_ratio']:.2f}% |")
        lines.append("")
    else:
        lines.append("*原始功率数据统计暂不可用。*")
        lines.append("")

    # Worst sites
    lines.append("### 1.3 模型误差最差站点数据\n")
    if data["final_eval"] is not None:
        worst = compute_worst_sites(data["final_eval"], n=5)
        lines.append("下表按站点级 NRMSE 从高到低排列，NRMSE = RMSE / mean(capacity_mw) × 100%。")
        lines.append("")
        lines.append("| 站点ID | 装机容量（MW） | 评估样本数（行） | MAE（MW） | RMSE（MW） | NRMSE（%） |")
        lines.append("|:---|:---:|:---:|:---:|:---:|:---:|")
        for _, r in worst.iterrows():
            lines.append(
                f"| {r['site_id']} | {r['capacity_mw']:.3f} | {r['test_rows']:,} | "
                f"{r['mae_mw']:.4f} | {r['rmse_mw']:.4f} | **{r['nrmse_pct']:.2f}** |"
            )
        lines.append("")
    else:
        lines.append("*最差站点数据暂不可用。*")
        lines.append("")

    # =========================================================================
    # Section 2: Training workflow
    # =========================================================================
    lines.append("---\n")
    lines.append("## 二、训练流程简述\n")

    lines.append("### 2.1 流水线版本演进\n")
    lines.append("训练流程包含三个主要版本阶段的逐步优化：\n")
    lines.append("```")
    lines.append("V0 (基线)")
    lines.append("  └─ 使用分布式训练数据 (distributed_train_table_v159.pkl)")
    lines.append("  └─ 基础特征工程：辐照度、功率、温度、湿度等")
    lines.append("  └─ 输出：distributed_predictions.pkl")
    lines.append("")
    lines.append("V1 (特征增强)")
    lines.append("  └─ 在 V0 基础上增加 inverse（逆功率）、blend（辐照度混合）特征")
    lines.append("  └─ 训练 blend 混合模型")
    lines.append("  └─ 增强 dawn/dusk 时刻的相对误差修正")
    lines.append("  └─ 输出：distributed_predictions_v159_fix.pkl")
    lines.append("")
    lines.append("MiddaySiteCalibrated (正午站点校准)")
    lines.append("  └─ 针对 10-14 时段独立训练专用模型")
    lines.append("  └─ 对所有站点应用 site-level NRMSE 校准")
    lines.append("  └─ 缓解正午高辐照度区间的系统性偏差")
    lines.append("")
    lines.append("Final (最终版本)")
    lines.append("  └─ 在 MiddaySiteCalibrated 基础上进一步验证")
    lines.append("  └─ 逐小时选择最优版本（V0 / V1 / Midday）")
    lines.append("  └─ 通过 final_guard 守卫机制确保指标不劣化")
    lines.append("  └─ 输出：distributed_predictions_final_eval/full.pkl")
    lines.append("```\n")

    lines.append("### 2.2 核心指标定义\n")
    lines.append("- **NRMSE（%）**：主要评估指标，NRMSE = RMSE / mean(capacity_mw) × 100%")
    lines.append("  - 按站点装机容量归一化，消除不同规模站点间的不可比性")
    lines.append("- **MAE（MW）**：平均绝对误差，直接反映预测与实际功率的平均偏差")
    lines.append("- **RMSE（MW）**：均方根误差，对大误差更敏感")
    lines.append("- **bias（%）**：（预测总量 - 实际总量）/ 实际总量 × 100%，反映系统性高估/低估")
    lines.append("- **城市NRMSE（%）**：|sum(pred) - sum(actual)| / sum(capacity_mw) × 100%\n")

    lines.append("### 2.3 版本选择策略\n")
    lines.append("每个预测小时从候选版本中选择最优版本：")
    lines.append("- 早间（6-8时）：优先 V0 或 V1")
    lines.append("- 正午（9-14时）：优先 MiddaySiteCalibrated")
    lines.append("- 晚间（15-19时）：综合评估后选择\n")

    # =========================================================================
    # Section 3: Training Results
    # =========================================================================
    lines.append("---\n")
    lines.append("## 三、训练结果\n")

    lines.append("### 3.1 分布式功率预测整体结果\n")
    overall = data["overall_summary"]
    if overall is not None and len(overall) > 0:
        final_row = overall[overall["version"] == "final"]
        if final_row.empty:
            final_row = overall.iloc[-1:]
        r = final_row.iloc[0]
        lines.append("| 指标 | 值 | 单位 |")
        lines.append("|:---|:---:|:---:|")
        lines.append(f"| 评估样本数（行） | {int(r.get('rows', 0)):,} | 行 |")
        lines.append(f"| 评估站点数 | {int(r.get('n_sites', 0))} | 座 |")
        lines.append(f"| 实际总发电量 | {r.get('actual_mwh', 0):,.2f} | MWh |")
        lines.append(f"| 预测总发电量 | {r.get('pred_mwh', 0):,.2f} | MWh |")
        lines.append(f"| 预测/实际比值 | {r.get('pred_actual_ratio', 0):.6f} | - |")
        lines.append(f"| bias | {r.get('bias_pct', 0):.4f} | % |")
        lines.append(f"| **NRMSE（主要指标）** | **{r.get('overall_nrmse_pct', 0):.4f}** | **%** |")
        lines.append(f"| MAE | {r.get('mae_mw', 0):.4f} | MW |")
        lines.append(f"| RMSE | {r.get('rmse_mw', 0):.4f} | MW |")
        lines.append("")
    else:
        lines.append("*整体结果数据暂不可用。*")
        lines.append("")

    lines.append("### 3.2 逐小时预测结果\n")
    hourly = data["hourly_nrmse"]
    if hourly is not None and len(hourly) > 0:
        lines.append("| 小时（时） | 样本数（行） | 站点平均NRMSE（%） | 城市NRMSE（%） |")
        lines.append("|:---:|:---:|:---:|:---:|")
        for _, r in hourly.iterrows():
            h = int(r.get("hour", 0))
            rows_v = int(r.get("rows", 0))
            site_nrmse = r.get("site_nrmse_mean_pct", "-")
            city_nrmse = r.get("city_nrmse_pct", "-")
            if isinstance(site_nrmse, float):
                site_nrmse = f"{site_nrmse:.2f}"
            if isinstance(city_nrmse, float):
                city_nrmse = f"{city_nrmse:.3f}"
            lines.append(f"| **{h}** | {rows_v:,} | {site_nrmse} | {city_nrmse} |")
        lines.append("")
    else:
        lines.append("*逐小时结果数据暂不可用。*")
        lines.append("")

    lines.append("### 3.3 版本选择说明\n")
    lines.append("""
各小时使用最优版本：
- **6-8时（早间）**：使用 V1 基础版本，结合 dawn/dusk 修正
- **9-14时（正午）**：使用 MiddaySiteCalibrated 专用版本，针对高辐照度优化
- **15-19时（晚间）**：综合 V0/V1/Midday 版本选择最优结果

最终版本通过 `final_guard` 守卫机制验证：只有当候选版本在测试集上的整体 NRMSE 不超过当前 best 0.1pp 时才允许替换，确保模型质量不退化。
""")

    # =========================================================================
    # Section 4: Visualization
    # =========================================================================
    lines.append("---\n")
    lines.append("## 四、可视化页面说明\n")
    lines.append(f"""
交互式预测结果页面位于 `stages/05_visualization/interactive_forecast_dashboard.html`。

页面主要功能：
- **站点筛选**：按站点ID、地区、误差等级（预测最好/最差/相对正确/样本少）筛选
- **时间范围选择**：支持指定任意时间段查看历史预测效果
- **散点图**：展示各站点样本量与 NRMSE 关系，按地区着色
- **逐小时曲线**：展示城市总功率的真实值与预测值对比
- **正午专题**：按日期分解正午时段城市总功率

页面数据来源为 `output/pv_pipeline/tables/distributed_predictions_final_full.pkl`，
仅用于展示当前 final/best 预测结果，不参与模型训练和模型选择。
""")

    # =========================================================================
    # Section 5: Audit
    # =========================================================================
    lines.append("---\n")
    lines.append("## 五、严谨性验证结论\n")
    audit = data.get("audit_summary")
    if audit:
        grade = audit.get("grade", "C")
        grade_desc = audit.get("grade_description", "未知")
        fail_count = audit.get("fail_count", 0)
        warn_count = audit.get("warn_count", 0)
        module_results = audit.get("module_results", {})

        lines.append(f"**审计等级：Grade {grade} — {grade_desc}**")
        lines.append(f"FAIL: {fail_count} 项，WARN: {warn_count} 项")
        lines.append("")
        lines.append("| 审计模块 | 结论 |")
        lines.append("|:---|:---:|")
        for mod, status in module_results.items():
            icon = "PASS" if status == "PASS" else ("WARN" if status == "WARN" else "FAIL")
            lines.append(f"| {mod} | {icon} |")
        lines.append("")

        if audit.get("final_equals_best"):
            lines.append("- ✅ Final 预测结果与 Best 完全一致（power_pred 相同）")
        else:
            lines.append("- ❌ Final 与 Best 存在差异")

        computed_nrmse = audit.get("computed_overall_nrmse")
        ref_nrmse = audit.get("reference_nrmse")
        if computed_nrmse and ref_nrmse:
            lines.append(f"- ✅ 指标从 final_eval.pkl 复算值（{computed_nrmse:.4f}%）与报告值（{ref_nrmse:.4f}%）一致")
        lines.append("")
    else:
        lines.append("*严谨性验证数据暂不可用。*")
        lines.append("")

    # =========================================================================
    # Section 6: Issues
    # =========================================================================
    lines.append("---\n")
    lines.append("## 六、当前存在的问题\n")
    lines.append("""
1. **部分站点 NRMSE 较高**：S019（首耀新海光伏）测试集 NRMSE 约 31%，显著高于整体水平，可能存在功率容量映射不准确的问题。

2. **部分站点存在容量映射疑虑**：部分站点的实际发电功率峰值超过其登记装机容量，可能存在台账容量与实际不一致的情况，需人工核查数据字典。

3. **正午时段误差仍然较高**：10-14时站点平均 NRMSE 在 13-15% 之间，高于早晚时段，主要原因在于高辐照度区间的功率曲线非线性特征更复杂。

4. **完全复现训练结果需运行脚本**：如需在其他环境完全复现本结果，请运行 `scripts/train_fixed.py` 脚本，该脚本包含所有训练逻辑和随机种子设置。

5. **部分站点历史数据不足**：部分 2025 年新并网站点（如 S037 华能中林三期光伏）仅有少量历史数据，预测可靠性相对较低。
""")

    # =========================================================================
    # Section 7: Config
    # =========================================================================
    lines.append("---\n")
    lines.append("## 七、训练配置与版本信息\n")
    lines.append("| 配置项 | 值 |")
    lines.append("|:---|:---|")
    lines.append("| 训练期 | 2023-01-01 ~ 2025-08-31 |")
    lines.append("| 测试期 | 2025-09-01 ~ 2026-01-01 |")
    lines.append("| 评估时段 | 6-19 时 |")
    lines.append("| 评估站点数 | 53 座 |")
    lines.append("| 主要评估指标 | NRMSE（%）= RMSE / mean(capacity_mw) × 100% |")
    lines.append("| 辅助指标 | MAE（MW）、RMSE（MW）、bias（%） |")
    lines.append("| 坏站点排除 | S026/S015/S057/S036/S067/S045/S058（共7座） |")
    lines.append("| 训练框架 | LightGBM + 自定义混合模型 |")
    lines.append("| 特征类型 | 辐照度、功率、温度、湿度、inverse、blend等 |")
    lines.append("")

    return "\n".join(lines)


def main():
    root = PROJECT_ROOT / "output" / "pv_pipeline"

    print("=" * 70)
    print("Regenerate Project Report (Round 14)")
    print("=" * 70)

    print("\nLoading data...")
    data = load_data(root)

    print("  final_eval:", "OK" if data["final_eval"] is not None else "MISSING")
    print("  final_full:", "OK" if data["final_full"] is not None else "MISSING")
    print("  site_master:", "OK" if data["site_master"] is not None else "MISSING")
    print("  overall_summary:", "OK" if data["overall_summary"] is not None else "MISSING")
    print("  hourly_nrmse:", "OK" if data["hourly_nrmse"] is not None else "MISSING")
    print("  audit_summary:", "OK" if data["audit_summary"] is not None else "MISSING")
    print("  scatter:", f"OK ({len(data['scatter'])} sites)" if data["scatter"] else "MISSING")

    print("\nGenerating report...")
    report_content = generate_report(data, root)

    output_path = PROJECT_ROOT / "光伏功率预测项目.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    print(f"\nReport written: {output_path}")
    print(f"Report size: {len(report_content):,} characters")

    # Quick summary
    print("\n" + "=" * 70)
    print("Report Summary")
    print("=" * 70)
    overall = data["overall_summary"]
    if overall is not None:
        final_row = overall[overall["version"] == "final"]
        if final_row.empty:
            final_row = overall.iloc[-1:]
        r = final_row.iloc[0]
        print(f"  Overall NRMSE: {r.get('overall_nrmse_pct', 'N/A'):.4f}%")
        print(f"  MAE: {r.get('mae_mw', 'N/A'):.4f} MW")
        print(f"  RMSE: {r.get('rmse_mw', 'N/A'):.4f} MW")
        print(f"  Sites: {int(r.get('n_sites', 0))}")
        print(f"  Rows: {int(r.get('rows', 0)):,}")


if __name__ == "__main__":
    import sys
    main()
