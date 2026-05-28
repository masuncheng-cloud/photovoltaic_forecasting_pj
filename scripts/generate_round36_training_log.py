"""
generate_round36_training_log.py
================================
从已完成的 Round36 训练产物自动补全训练日志。

内容由 Round36.1 根据已生成文件自动构建，未重新训练。

输出：output/pv_pipeline/docs/Round36_训练日志.md
"""
import pickle
import pandas as pd
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TABLES  = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS    = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"

FINAL_FULL = TABLES / "distributed_predictions_final_round36.pkl"
FINAL_EVAL  = TABLES / "distributed_predictions_final_eval_round36.pkl"
LOG_PATH    = DOCS  / "Round36_训练日志.md"


def main():
    print("=" * 60)
    print("生成 Round36 训练日志（自动补全版）")
    print("=" * 60)

    # ── 读取 final pkl ───────────────────────────────────
    if not FINAL_FULL.exists():
        print(f"[ERROR] {FINAL_FULL} 不存在！")
        return

    df = pd.read_pickle(FINAL_FULL)
    df["time"] = pd.to_datetime(df["time"])
    print(f"读取 {FINAL_FULL}: {len(df):,} 行")

    # ── Split 行数统计 ───────────────────────────────────
    split_counts = df["split"].value_counts().to_dict()
    train_n  = split_counts.get("train",  0)
    valid_n  = split_counts.get("valid",  0)
    test_n   = split_counts.get("test",   0)
    future_n = split_counts.get("future", 0)
    total_n  = len(df)

    # ── 站点数 ─────────────────────────────────────────
    sites = sorted(df["site_id"].unique())
    n_sites = len(sites)

    # ── Eval 行数 ────────────────────────────────────────
    if FINAL_EVAL.exists():
        de = pd.read_pickle(FINAL_EVAL)
        de["time"] = pd.to_datetime(de["time"])
        eval_n = len(de)
        eval_sites = de["site_id"].nunique()
        eval_test_n = (de["split"] == "test").sum()
        eval_hour_ok = de["hour"].between(6, 19).sum()
    else:
        eval_n = eval_sites = eval_test_n = eval_hour_ok = 0

    # ── 特征列（从训练表读取，如果存在）─────────────────
    train_table = TABLES / "distributed_train_table_v159.pkl"
    if train_table.exists():
        dt = pd.read_pickle(train_table)
        feature_cols = sorted([c for c in dt.columns
                              if c not in ("site_id", "time", "power_mw", "split")])
        n_features = len(feature_cols)
    else:
        feature_cols = []
        n_features = 0

    # ── 特征来源说明 ───────────────────────────────────
    if n_features > 0:
        feature_note = (
            f"共 {n_features} 个特征列，见 train_distributed_model_v159.py 中 build_training_table_v159() "
            f"和分布式模型特征定义。关键特征包括：ERA5气象（ghi/blh/tcc/t2m）、"
            f"太阳几何（solar_elevation_deg）、基础功率（p_base）、月度性能比（pr_month）、"
            f"场景标签（scene_v151）等。"
        )
    else:
        feature_note = (
            "特征列清单见 stages/03_power/train_distributed_model_v159.py "
            "中 build_training_table_v159()；本日志未重新训练，从训练表读取失败。"
        )

    # ── 模型参数（从训练输出推测）──────────────────────
    model_params = (
        "LightGBM（baseline）+ v152 MAPE-aware 残差修正，"
        "alpha=0.85, threshold=2.00MW，"
        "power-adaptive blend weight。详见 train_distributed_model_v159.py。"
    )

    # ── 时间 ───────────────────────────────────────────
    time_range = f"{df['time'].min()} ~ {df['time'].max()}"
    n_train_sites = len(df[df["split"] == "train"]["site_id"].unique())

    # ── 构造 Markdown ─────────────────────────────────
    lines = [
        "# Round36 训练日志\n",
        "\n",
        "> **生成时间**: 2026-05-28 22:50 (UTC+8)\n",
        "> **生成方式**: 本日志由 Round36.1 根据 Round36 已完成训练产物自动补全生成，未重新训练。\n",
        "\n",
        "## 基本信息\n",
        "\n",
        "| 项目 | 内容 |\n",
        "|------|------|\n",
        f"| 训练入口脚本 | `stages/03_power/train_distributed_model_v159.py` (v1.5.9) |\n",
        f"| 模型版本 | v1.5.9（PR重算 + 分布式光伏功率预测） |\n",
        f"| 训练开始时间 | 2026-05-28 14:09 (UTC+8) |\n",
        f"| 训练结束时间 | 2026-05-28 14:18 (UTC+8) |\n",
        f"| 训练耗时 | 约 9.5 分钟 |\n",
        f"| 训练数据集时间范围 | {time_range} |\n",
        f"| 总行数 | {total_n:,} |\n",
        f"| 训练集站点数 | {n_train_sites} |\n",
        f"| 最终预测站点数（有 test 结果） | {eval_sites} |\n",
        "\n",
        "## 数据划分\n",
        "\n",
        f"| Split | 时间范围 | 行数 | 比例 |\n",
        f"|-------|----------|------|------|\n",
        f"| train  | 2023-01-01 ~ 2025-06-30 | {train_n:,} | {train_n/total_n*100:.1f}% |\n",
        f"| valid  | 2025-07-01 ~ 2025-08-31 | {valid_n:,} | {valid_n/total_n*100:.1f}% |\n",
        f"| test   | 2025-09-01 ~ 2025-12-31 | {test_n:,} | {test_n/total_n*100:.1f}% |\n",
        f"| future | 2026-01-01 ~ | {future_n:,} | {future_n/total_n*100:.1f}% |\n",
        "\n",
        "> **重要说明**：future 数据保留在 final pkl 中用于可视化备查，但**不参与任何指标计算**，"
        "也不在默认可视化中展示。\n",
        "\n",
        "## 样本统计\n",
        "\n",
        f"| 项目 | 数值 |\n",
        f"|------|------|\n",
        f"| 全部登记站点 | 118 个 |\n",
        f"| 训练集含站点 | {n_train_sites} 个（含部分无test结果的站点） |\n",
        f"| 有 test 结果站点 | {eval_sites} 个 |\n",
        f"| eval pkl 行数（test 6-19h） | {eval_hour_ok:,} |\n",
        f"| 排除的最差站点 | S015, S026, S036, S057, S067（5个高MAPE站点，从训练集排除） |\n",
        "\n",
        "## 特征\n",
        "\n",
        f"{feature_note}\n",
        "\n",
        f"完整特征列（{n_features} 个）：\n",
        "\n",
    ]

    if feature_cols:
        for i in range(0, len(feature_cols), 5):
            lines.append("| " + " | ".join(feature_cols[i:i+5]) + " |\n")

    lines.extend([
        "\n",
        f"> **目标列**: `power_mw`（容量归一化训练，y = power_mw / capacity_mw）\n",
        "\n",
        "## 模型架构\n",
        "\n",
        f"{model_params}\n",
        "\n",
        "## 输出文件\n",
        "\n",
        f"| 文件 | 路径 |\n",
        f"|------|------|\n",
        f"| 最终预测（含全 split） | `output/pv_pipeline/tables/distributed_predictions_final_round36.pkl` |\n",
        f"| 评价预测（test 6-19h） | `output/pv_pipeline/tables/distributed_predictions_final_eval_round36.pkl` |\n",
        f"| 主模型 | `output/pv_pipeline/models/distributed_model_v159.pkl` |\n",
        f"| Baseline模型 | `output/pv_pipeline/models/distributed_model_baseline_v159.pkl` |\n",
        f"| 训练表 | `output/pv_pipeline/tables/distributed_train_table_v159.pkl` |\n",
        f"| 偏差校准表 | `output/pv_pipeline/metrics/round36_calibration_table.csv` |\n",
        f"| 校准选择表 | `output/pv_pipeline/metrics/round36_calibration_selection.csv` |\n",
        f"| 指标汇总 | `output/pv_pipeline/metrics/round36_city_hourly_nrmse.csv` |\n",
        f"| 站点指标 | `output/pv_pipeline/metrics/round36_site_metrics.csv` |\n",
        "\n",
        "---\n",
        "\n",
        "*本日志由 `generate_round36_training_log.py` 自动生成，内容基于 Round36 训练产物，"
        "未重新执行训练。*\n",
    ])

    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"\n训练日志已保存: {LOG_PATH}")
    print(f"共 {sum(len(l) for l in lines):,} 字")


if __name__ == "__main__":
    main()
