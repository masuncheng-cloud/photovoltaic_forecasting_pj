"""
regenerate_project_report_round36.py
=================================
重新生成光伏功率预测项目.md，使用 Round36 最新数据。

报告必须包含：
  1. 数据集情况（118站点，时间范围）
  2. 站点数量分层（118/68/14/50等）
  3. 训练流程
  4. 训练逻辑说明
  5. 全市总出力逐小时 NRMSE
  6. 站点平均逐小时 NRMSE
  7. 站点级指标
  8. 典型站点
  9. 异常站点说明
  10. 当前问题

禁止：
  - 旧版 0.3365% 作为正式指标
  - 混用行级 NRMSE 和城市总出力 NRMSE
  - 把 68 写成正常可排名站点
"""
import os
import pickle
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
TABLES  = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS    = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"

OUT_PATH = PROJECT_ROOT / "光伏功率预测项目.md"


def safe_load_csv(path):
    if path.exists():
        return pd.read_csv(path)
    return None


def main():
    print("=" * 60)
    print("重新生成光伏功率预测项目.md（Round36 版）")
    print("=" * 60)

    # ── 读取数据 ───────────────────────────────────────
    city_hourly = safe_load_csv(METRICS / "round36_city_hourly_nrmse.csv")
    site_avg    = safe_load_csv(METRICS / "round36_site_avg_hourly_nrmse.csv")
    site_metrics= safe_load_csv(METRICS / "round36_site_metrics.csv")
    typical     = safe_load_csv(METRICS / "round36_typical_sites.csv")
    validity    = safe_load_csv(METRICS / "round36_site_validity.csv")
    summary     = safe_load_csv(METRICS / "round36_site_count_summary.csv")

    # ── 计算关键指标 ─────────────────────────────────
    if city_hourly is not None:
        peak_nrmse  = float(city_hourly[city_hourly["hour"].between(10,14)]["nrmse_city_pct"].mean())
        overall_max = float(city_hourly["nrmse_city_pct"].max())
        overall_min = float(city_hourly["nrmse_city_pct"].min())
        peak_hour   = int(city_hourly.loc[city_hourly["nrmse_city_pct"].idxmax(), "hour"])
    else:
        peak_nrmse = overall_max = overall_min = peak_hour = None

    if site_metrics is not None and validity is not None:
        normal_sites = site_metrics[site_metrics["site_status"] == "正常评价"]
        if len(normal_sites) > 0:
            avg_nrmse = float(normal_sites["nrmse_pct"].mean())
            med_nrmse = float(normal_sites["nrmse_pct"].median())
        else:
            avg_nrmse = med_nrmse = None
    else:
        avg_nrmse = med_nrmse = None

    # ── 站点数量 ────────────────────────────────────
    if summary is not None:
        def get_count(label):
            row = summary[summary["分类"] == label]
            return int(row["数量"].iloc[0]) if len(row) > 0 else 0
        total     = get_count("全部登记站点")
        has_test  = get_count("有test结果站点")
        normal    = get_count("正常可排名站点")
        no_power  = get_count("测试期无有效发电")
        drift     = get_count("测试期分布漂移")
        bias      = get_count("系统性偏差")
        no_test   = get_count("无测试预测结果")
    else:
        total = has_test = normal = no_power = drift = bias = no_test = 0

    # ── 典型站点 ───────────────────────────────────
    if typical is not None:
        best  = list(typical[typical["类型"] == "预测最好"]["site_id"])
        worst = list(typical[typical["类型"] == "预测最差"]["site_id"])
        rel_ok= list(typical[typical["类型"] == "相对正确"]["site_id"]) if "相对正确" in typical["类型"].values else []
    else:
        best = worst = rel_ok = []

    # ── 构造 Markdown ───────────────────────────────
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# 光伏功率预测项目\n",
        f"\n",
        f"> **最后更新**: {now}（Round36 完整重训版）\n",
        f"> **数据范围**: 2023-01-01 ~ 2025-12-31\n",
        f"\n",
        f"## 一、项目概述\n",
        f"\n",
        f"本项目对某地 {total} 个分布式光伏电站进行功率预测，建模方法为 LightGBM 融合 v152 MAPE-aware 残差修正，"
        f"后处理包含偏差校准与物理裁剪。\n",
        f"\n",
        f"**训练逻辑严格隔离**：\n",
        f"- 模型训练仅使用 **train** 数据（2023-01-01 ~ 2025-06-30）\n",
        f"- 模型选择与偏差校准仅使用 **valid** 数据（2025-07-01 ~ 2025-08-31）\n",
        f"- 最终评价仅使用 **test** 数据（2025-09-01 ~ 2025-12-31）\n",
        f"- **future** 数据（2026-01-01 之后）不参与任何指标计算\n",
        f"\n",
        f"## 二、数据集情况\n",
        f"\n",
        f"| 项目 | 数值 |\n",
        f"|------|------|\n",
        f"| 全部登记站点 | {total} 个 |\n",
        f"| 有 test 结果站点 | {has_test} 个 |\n",
        f"| 正常可排名站点 | {normal} 个 |\n",
        f"| 测试期无有效发电 | {no_power} 个 |\n",
        f"| 测试期分布漂移 | {drift} 个 |\n",
        f"| 系统性偏差 | {bias} 个 |\n",
        f"| 无测试预测结果 | {no_test} 个 |\n",
        f"| 训练集时间范围 | 2023-01-01 ~ 2025-06-30 |\n",
        f"| 验证集时间范围 | 2025-07-01 ~ 2025-08-31 |\n",
        f"| 测试集时间范围 | 2025-09-01 ~ 2025-12-31 |\n",
        f"\n",
        f"> **口径说明**：全部登记站点 {total} = 有test结果 {has_test} + 无测试预测结果 {no_test}。"
        f"正常可排名 {normal} 个为「正常评价」站点，其余 {has_test - normal} 个有 test 结果但存在异常（无发电/分布漂移/系统偏差）。\n",
        f"\n",
        f"## 三、模型架构\n",
        f"\n",
        f"**Baseline**：LightGBM，容量归一化功率（y = power_mw / capacity_mw）为目标变量，"
        f"特征包括辐照度（ERA5 ghi/blh）、温度（ERA5 t2m）、云量（ERA5 tcc）、"
        f"太阳高度角、日照时长、基础功率（p_base）、月度性能比（pr_month）等。\n",
        f"\n",
        f"**v152 残差修正**：针对 Baseline 高 MAPE 时段（如晨昏/低辐照）训练专门的残差修正模型，"
        f"输出残差校正量叠加到 Baseline 预测上。\n",
        f"\n",
        f"**后处理**：\n",
        f"1. **容量归一化还原**：y_pred × capacity_mw\n",
        f"2. **物理裁剪**：max(0, min(power_pred_raw, capacity_mw))\n",
        f"3. **偏差校准**：基于 valid 集学习 site_id / hour 层级的 actual/pred 比率，"
        f"应用 shrinkage（K=200）防止过拟合，对异常站点自动回退\n",
        f"\n",
        f"## 四、最终预测字段\n",
        f"\n",
        f"所有最终指标和可视化均使用统一口径：\n",
        f"\n",
        f"```\n",
        f"power_pred_final\n",
        f"```\n",
        f"\n",
        f"原始模型输出记为 `power_pred_raw`，`power_pred_final` 在 `power_pred_raw` 基础上经过校准。\n",
        f"\n",
        f"## 五、评价指标\n",
        f"\n",
        f"### 5.1 全市总出力逐小时 NRMSE（主要指标）\n",
        f"\n",
        f"先将各时刻各站点功率聚合为全市总出力，再计算 RMSE：\n",
        f"\n",
        f"```python\n",
        f"city_actual = sum(power_mw for all sites at time t)\n",
        f"city_pred   = sum(power_pred_final for all sites at time t)\n",
        f"capacity_sum = sum(capacity_mw for all sites)\n",
        f"nrmse_city = sqrt(mean((city_pred - city_actual)^2)) / capacity_sum × 100%\n",
        f"```\n",
        f"\n",
    ]

    if city_hourly is not None:
        lines.extend([
            f"| 小时 | NRMSE（%） | MAE（MW） | 偏差（MW） |\n",
            f"|------|-----------|-----------|------------|\n",
        ])
        for _, row in city_hourly.sort_values("hour").iterrows():
            lines.append(
                f"| {int(row['hour'])}时 | {row['nrmse_city_pct']:.2f} | "
                f"{row['mae_city_MW']:.2f} | {row['bias_city_MW']:+.2f} |\n"
            )
        lines.append(f"\n")
        lines.append(
            f"> 全市 10-14 时 NRMSE 平均：**{peak_nrmse:.2f}%**\n"
            f"> 全市全天 NRMSE 范围：**{overall_min:.2f}% ~ {overall_max:.2f}%**\n"
            f"> 峰值出现在：**{peak_hour}时（{overall_max:.2f}%）**\n"
        )
    else:
        lines.append("> 暂无数据（请运行 compute_round36_metrics.py）\n")

    lines.extend([
        f"\n",
        f"### 5.2 站点平均逐小时 NRMSE\n",
        f"\n",
    ])

    if site_avg is not None:
        lines.extend([
            f"| 小时 | 平均 NRMSE（%） | 中位数 NRMSE（%） |\n",
            f"|------|----------------|-------------------|\n",
        ])
        for _, row in site_avg.sort_values("hour").iterrows():
            lines.append(
                f"| {int(row['hour'])}时 | {row['nrmse_hour_avg']:.2f} | {row['nrmse_hour_median']:.2f} |\n"
            )
        lines.append(f"\n")
    else:
        lines.append("> 暂无数据\n\n")

    lines.extend([
        f"### 5.3 站点级指标\n",
        f"\n",
    ])

    if site_metrics is not None and len(site_metrics) > 0:
        lines.extend([
            f"| 指标 | 数值 |\n",
            f"|------|------|\n",
            f"| 有效站点数 | {len(site_metrics)} |\n",
            f"| 正常评价站点数 | {normal} |\n",
        ])
        if avg_nrmse is not None:
            lines.append(f"| 正常站点平均 NRMSE | {avg_nrmse:.2f}% |\n")
            lines.append(f"| 正常站点中位 NRMSE | {med_nrmse:.2f}% |\n")
        lines.append("\n")
    else:
        lines.append("> 暂无数据\n\n")

    lines.extend([
        f"### 5.4 典型站点\n",
        f"\n",
    ])

    if typical is not None and len(typical) > 0:
        lines.extend([
            f"| 类型 | 站点 | NRMSE（%） | MAE（MW） | 偏差（MW） |\n",
            f"|------|------|-----------|-----------|------------|\n",
        ])
        for _, row in typical.iterrows():
            lines.append(
                f"| {row['类型']} | {row['site_id']} | {row['nrmse_pct']:.2f} | "
                f"{row['mae_MW']:.2f} | {row['bias_MW']:+.2f} |\n"
            )
        lines.append("\n")
    else:
        lines.append("> 暂无数据\n\n")

    lines.extend([
        f"## 六、异常站点说明\n",
        f"\n",
    ])

    if validity is not None:
        for status in ["测试期无有效发电", "测试期分布漂移", "系统性偏差", "无测试预测结果"]:
            n = int((validity["site_status"] == status).sum())
            if n > 0:
                sids = sorted(validity[validity["site_status"] == status]["site_id"].tolist())
                if len(sids) <= 20:
                    lines.append(f"- **{status}**（{n} 个）：{', '.join(sids)}\n")
                else:
                    lines.append(f"- **{status}**（{n} 个）：{', '.join(sids[:10])}...（共 {n} 个）\n")
        lines.append("\n")
    else:
        lines.append("> 暂无数据\n\n")

    lines.extend([
        f"## 七、当前仍存在的问题\n",
        f"\n",
        f"1. **分布漂移站点**：部分电站在测试期出现容量因子分布偏移（与训练/验证期显著不同），"
        f"可能因天气模式变化或设备状态改变，导致模型预测失效。\n",
        f"\n",
        f"2. **无有效发电站点**：部分电站在测试期持续零功率，可能已停机或数据采集异常，"
        f"预测结果无实际参考价值。\n",
        f"\n",
        f"3. **系统性偏差站点**：部分站点预测值持续偏离实际值，"
        f"需进一步调查是否存在数据质量问题或模型对特定场景适应性不足。\n",
        f"\n",
        f"## 八、指标口径说明\n",
        f"\n",
        f"- **全市 NRMSE**：先聚合到全市时间序列（sum of all sites），再计算 RMSE，"
        f"分母为全部站点装机容量之和。这是本项目的**主要指标**，用于横向对比不同轮次。\n",
        f"- **站点 NRMSE**：各站点独立计算（RMSE / 站点装机容量），仅用于站点间排名。\n",
        f"- **不允许**用未来（future）数据参与任何指标计算。\n",
        f"- **不允许**将行级站点 NRMSE 与城市总出力 NRMSE 混用。\n",
        f"\n",
        f"---\n",
        f"\n",
        f"*本报告由 `regenerate_project_report_round36.py` 自动生成，最后更新于 {now}。*\n",
    ])

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"\n报告已写入: {OUT_PATH}")
    print(f"字数: {sum(len(l) for l in lines):,} 字")

    # 验证
    content = open(OUT_PATH, encoding="utf-8").read()
    checks = {
        "含 Round36": "Round36" in content,
        "无旧口径 0.3365%": "0.3365" not in content,
        "含站点分层": str(total) in content and str(normal) in content,
        "含训练逻辑": "train" in content and "valid" in content and "test" in content,
        "含 power_pred_final": "power_pred_final" in content,
    }
    print("\n报告验证：")
    for name, ok in checks.items():
        print(f"  {'✓' if ok else '✗'} {name}")

    if not all(checks.values()):
        print("\n[WARN] 部分验证未通过，请检查！")

    print("\n[OK] regenerate_project_report_round36.py 完成！")


if __name__ == "__main__":
    main()
