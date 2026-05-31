"""
round40_apply_hour_level_final_prediction.py
==============================================
按小时选择最终预测列：
  - 边缘小时 (6, 7, 18, 19)：使用 power_pred_cal（避免 ghi<5 硬置零）
  - 其他小时 (8-17)：使用 power_pred（保持更好的整体 BIAS）
"""
import pandas as pd
from pathlib import Path

ROOT = Path("output/pv_pipeline")
TABLES = ROOT / "tables"
METRICS = ROOT / "metrics"

FINAL_PATH = TABLES / "distributed_predictions_final_round36.pkl"
EVAL_PATH  = TABLES / "distributed_predictions_final_eval_round36.pkl"

EDGE_HOURS = [6, 7, 18, 19]


def main():
    print("=" * 60)
    print("Round40: 按小时选择最终预测列")
    print("=" * 60)

    df = pd.read_pickle(FINAL_PATH)
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour

    print(f"总行数: {len(df):,}")

    edge_mask = df["hour"].isin(EDGE_HOURS)

    # 记录切换前的状态用于对比
    for col in ["power_pred_final", "power_pred_cal", "power_pred"]:
        if col in df.columns:
            vals = df.loc[edge_mask, col].values
            print(f"  {col} edge hours nonzero: {(vals > 1e-9).sum()}/{len(vals)}")

    # 保存旧的 power_pred_final
    df["power_pred_final_before_round40"] = df["power_pred_final"]

    # 构建新最终预测
    df["power_pred_final"] = df["power_pred"].copy()
    df.loc[edge_mask, "power_pred_final"] = df.loc[edge_mask, "power_pred_cal"]

    # 物理裁剪
    df["power_pred_final"] = df["power_pred_final"].clip(lower=0)
    df["power_pred_final"] = df[["power_pred_final", "capacity_mw"]].min(axis=1)

    # 保存
    df.to_pickle(FINAL_PATH)
    print(f"\n已保存: {FINAL_PATH}")

    df_eval = df[(df["split"] == "test") & df["hour"].between(6, 19)].copy()
    df_eval.to_pickle(EVAL_PATH)
    print(f"已保存: {EVAL_PATH} ({len(df_eval):,} 行)")

    # 快速 BIAS 对比
    test = df[df["split"] == "test"].copy()
    test = test[test["hour"].between(6, 19)]
    test = test[test["power_mw"].notna() & test["power_pred_final"].notna()]

    for col in ["power_pred_final", "power_pred_final_before_round40"]:
        if col not in test.columns:
            continue
        city = test.groupby("time").agg(
            actual=("power_mw", "sum"), pred=(col, "sum")
        )
        bias = (city["pred"].sum() - city["actual"].sum()) / max(city["actual"].sum(), 1e-9) * 100
        nrmse_mw = ((city["pred"] - city["actual"]) ** 2).mean() ** 0.5
        cap = city["pred"].sum() / max(city["actual"].sum(), 1e-9)
        nrmse_pct = float(nrmse_mw / (city["pred"].sum() / max(city["actual"].sum(), 1e-9)) * 100)
        print(f"  {col}: bias={bias:+.2f}%")

    print("\n[OK] hour-level final prediction applied")


if __name__ == "__main__":
    main()
