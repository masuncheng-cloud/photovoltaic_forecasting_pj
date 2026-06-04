"""
build_site_validity_round36.py
==============================
Round36 站点有效性分层：

1. 全部登记站点（site_master.csv）：所有已登记站点
2. 有 test 结果站点（final_eval_round36）：有 test 6-19h 预测结果
3. 正常可排名站点：非异常/漂移/偏差

状态分类（优先级递减）：
  - 无测试预测结果：final_eval 中无该站点
  - 测试期无有效发电：test 6-19h 正功率样本 < 100 或 实际总电量 ≈ 0
  - 测试期分布漂移：train/valid 与 test 容量因子均值差异 ≥ 0.10 或 p95 差异 ≥ 0.20
  - 系统性偏差：pred/actual 比值 < 0.80 或 > 1.20
  - 正常评价：其余有 test 结果站点

输出：
  <output-root>/metrics/round36_site_validity.csv
  <output-root>/metrics/round36_site_count_summary.csv

用法：
  python scripts/build_site_validity_round36.py
  python scripts/build_site_validity_round36.py --output-root output/pv_pipeline
"""
import argparse
import os
import pickle
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# ── 阈值常量 ────────────────────────────────────────────────────────────────
MIN_TEST_POSITIVE_ROWS = 100
MIN_TEST_ACTUAL_MWH   = 1e-6
DRIFT_MEAN_THRESHOLD   = 0.10
DRIFT_P95_THRESHOLD   = 0.20
BIAS_RATIO_LOW        = 0.80
BIAS_RATIO_HIGH       = 1.20


def get_site_status(sid: str, eval_df: pd.DataFrame, full_df: pd.DataFrame) -> str:
    """返回站点的有效性状态。"""
    site_eval = eval_df[eval_df["site_id"] == sid]
    if len(site_eval) == 0:
        return "无测试预测结果"

    # test 6-19h 正功率行数
    positive = site_eval[site_eval["power_mw"] > 0]
    n_positive = len(positive)
    actual_sum = site_eval["power_mw"].sum()  # MWh（小时数据，1行=1MWh）

    if n_positive < MIN_TEST_POSITIVE_ROWS or actual_sum <= MIN_TEST_ACTUAL_MWH:
        return "测试期无有效发电"

    # 分布漂移：train/valid vs test 的容量因子
    site_full = full_df[full_df["site_id"] == sid].copy()
    train_valid = site_full[site_full["split"].isin(["train", "valid"])].copy()
    test_rows = site_full[site_full["split"] == "test"].copy()

    def capacity_factor(sub):
        if len(sub) == 0:
            return 0.0
        cap = sub["capacity_mw"].iloc[0]
        if cap <= 0:
            return 0.0
        return sub["power_mw"].mean() / cap

    cf_train = capacity_factor(train_valid)
    cf_test  = capacity_factor(test_rows)
    cf_p95_train = train_valid["power_mw"].quantile(0.95) / (train_valid["capacity_mw"].iloc[0] if len(train_valid) else 1)
    cf_p95_test  = test_rows["power_mw"].quantile(0.95) / (test_rows["capacity_mw"].iloc[0] if len(test_rows) else 1)

    mean_shift = abs(cf_train - cf_test)
    p95_shift  = abs(cf_p95_train - cf_p95_test)

    if mean_shift >= DRIFT_MEAN_THRESHOLD or p95_shift >= DRIFT_P95_THRESHOLD:
        return "测试期分布漂移"

    # 系统性偏差：pred/actual 比值
    if len(site_eval) > 0:
        pred_sum = site_eval["power_pred_final"].sum()
        actual_sum2 = site_eval["power_mw"].sum()
        if actual_sum2 > 0:
            ratio = pred_sum / actual_sum2
            if ratio < BIAS_RATIO_LOW or ratio > BIAS_RATIO_HIGH:
                return "系统性偏差"

    return "正常评价"


def main():
    parser = argparse.ArgumentParser(description="Round36 站点有效性分层")
    parser.add_argument(
        "--output-root",
        type=str,
        default="output/pv_pipeline",
        help="输出根目录 (default: output/pv_pipeline)",
    )
    args = parser.parse_args()
    output_root = PROJECT_ROOT / args.output_root

    TABLES = output_root / "tables"
    METRICS = output_root / "metrics"
    os.makedirs(METRICS, exist_ok=True)
    FINAL_EVAL = TABLES / "distributed_predictions_final_eval_round36.pkl"
    SITE_MASTER_PATH = TABLES / "site_master.csv"

    print("=" * 60)
    print("Round36 站点有效性分层")
    print(f"Output root: {output_root}")
    print("=" * 60)

    # ── Step 1: 全部登记站点 ─────────────────────────────
    print("\n读取 site_master.csv（全部登记站点）...")
    sm = pd.read_csv(SITE_MASTER_PATH)
    all_sites = sorted(sm["site_id"].unique())
    print(f"  全部登记站点: {len(all_sites)} 个")

    # ── Step 2: 有 test 结果站点 ─────────────────────────
    print(f"\n读取 {FINAL_EVAL}（有 test 结果站点）...")
    if not FINAL_EVAL.exists():
        print(f"[ERROR] {FINAL_EVAL} 不存在！")
        import sys; sys.exit(1)
    df_eval = pd.read_pickle(FINAL_EVAL)
    df_eval["time"] = pd.to_datetime(df_eval["time"])
    eval_sites = sorted(df_eval["site_id"].unique())
    print(f"  有 test 结果站点: {len(eval_sites)} 个")

    # ── Step 3: 读取 full pkl 用于漂移分析 ───────────────
    full_path = TABLES / "distributed_predictions_final_round36.pkl"
    if full_path.exists():
        df_full = pd.read_pickle(full_path)
        df_full["time"] = pd.to_datetime(df_full["time"])
        print(f"  full pkl 已读取: {len(df_full):,} 行")
    else:
        print(f"  [WARN] {full_path} 不存在，跳过漂移分析")
        df_full = df_eval

    # ── Step 4: 逐站点判断 ─────────────────────────────
    print("\n逐站点判断有效性状态...")
    rows = []
    for sid in all_sites:
        status = get_site_status(sid, df_eval, df_full)
        rows.append({"site_id": sid, "site_status": status})
    df_result = pd.DataFrame(rows)

    # ── Step 5: 保存 ───────────────────────────────────
    df_result.to_csv(METRICS / "round36_site_validity.csv", index=False, encoding="utf-8-sig")
    print(f"\n已保存: {METRICS}/round36_site_validity.csv")

    # ── Step 6: 统计摘要 ────────────────────────────────
    counts = df_result["site_status"].value_counts()
    print("\n站点分类统计:")
    print(f"  全部登记站点: {len(all_sites)} 个")
    print(f"  有test结果站点: {len(eval_sites)} 个")
    print(f"  无测试预测结果: {counts.get('无测试预测结果', 0)} 个")
    for status in ["正常评价", "测试期无有效发电", "测试期分布漂移", "系统性偏差"]:
        n = counts.get(status, 0)
        if n > 0:
            print(f"  {status}: {n} 个")

    # 自洽验证
    has_test = len(eval_sites)
    no_test = counts.get("无测试预测结果", 0)
    normal = counts.get("正常评价", 0)
    abnormal = sum(counts.get(s, 0) for s in
                   ["测试期无有效发电", "测试期分布漂移", "系统性偏差"])
    print(f"\n  有test={has_test}, 无test={no_test}, 正常={normal}, 异常={abnormal}")
    print(f"  自洽验证: {len(all_sites)} == {has_test} + {no_test} = {has_test + no_test}",
          "✓" if len(all_sites) == has_test + no_test else "✗")

    # ── Step 7: 保存摘要 CSV ────────────────────────────
    summary_rows = [
        {"分类": "全部登记站点", "数量": len(all_sites)},
        {"分类": "有test结果站点", "数量": has_test},
        {"分类": "正常可排名站点", "数量": normal},
        {"分类": "测试期无有效发电", "数量": counts.get("测试期无有效发电", 0)},
        {"分类": "测试期分布漂移", "数量": counts.get("测试期分布漂移", 0)},
        {"分类": "系统性偏差", "数量": counts.get("系统性偏差", 0)},
        {"分类": "无测试预测结果", "数量": no_test},
    ]
    pd.DataFrame(summary_rows).to_csv(
        METRICS / "round36_site_count_summary.csv", index=False, encoding="utf-8-sig"
    )
    print(f"\n已保存: {METRICS}/round36_site_count_summary.csv")
    print("\n[OK] build_site_validity_round36.py 完成！")


if __name__ == "__main__":
    main()
