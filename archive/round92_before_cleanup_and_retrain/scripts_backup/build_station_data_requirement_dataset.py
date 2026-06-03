"""
build_station_data_requirement_dataset.py
========================================
生成站点级样本量需求分析数据集。

每个站点输出一行，包含：
  - 样本量统计（train/valid/test 各集合的 6-19 点和 10-14 点样本数）
  - 测试误差指标（MAE/RMSE/NRMSE/BIAS）
  - 逐小时 NRMSE（nrmse_h06_pct ~ nrmse_h19_pct）
  - 数据质量旗标

输出：
  output/pv_pipeline/metrics/round48_station_data_requirement_analysis.csv
  output/pv_pipeline/docs/Round48_样本量需求分析数据说明.md

数据来源：
  output/pv_pipeline/tables/distributed_predictions_final_round36.pkl

注意：
  - 必须使用 power_pred_final 列，不允许回退
  - 不包含 future split
"""

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pv_pipeline"
METRICS = OUT / "metrics"
DOCS = OUT / "docs"


def find_final_pkl():
    """找到最新的 distributed_predictions_final_*.pkl。"""
    candidates = list(OUT.rglob("distributed_predictions_final_round*.pkl"))
    candidates += list(OUT.rglob("distributed_predictions_final_full.pkl"))
    candidates += list(OUT.rglob("distributed_predictions_final_eval.pkl"))
    candidates = sorted({p for p in candidates if p.exists()}, key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(
            "找不到 distributed_predictions_final*.pkl。"
            "请先运行完整训练流程。"
        )
    pkl = candidates[0]
    print(f"  Using: {pkl.relative_to(ROOT)}")
    return pkl


def safe_ratio(num, den):
    """安全除法，零或 NaN 时返回 NaN。"""
    if den == 0 or pd.isna(den):
        return np.nan
    return float(num) / float(den)


def rmse_vector(err):
    """计算 RMSE（输入为误差数组）。"""
    arr = np.asarray(err, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) == 0:
        return np.nan
    return float(np.sqrt(np.mean(arr ** 2)))


def calc_metrics(g, capacity):
    """
    计算单个站点的测试误差指标（6-19点）。
    g: 站点+测试集子集 DataFrame
    返回 dict
    """
    if len(g) == 0:
        return {k: np.nan for k in ["mae_mw", "rmse_mw", "nrmse_pct", "bias_pct", "pred_actual"]}

    y = pd.to_numeric(g["power_mw"], errors="coerce")
    p = pd.to_numeric(g["power_pred_final"], errors="coerce")
    valid = y.notna() & p.notna()
    y, p = y[valid], p[valid]
    err = p - y

    mae = float(np.abs(err).mean()) if len(err) else np.nan
    rmse = rmse_vector(err.values)
    nrmse = safe_ratio(rmse, capacity) * 100 if pd.notna(capacity) else np.nan

    y_sum = float(y.sum())
    p_sum = float(p.sum())
    bias = safe_ratio(float(err.sum()), y_sum) * 100 if y_sum != 0 else np.nan
    pred_actual = safe_ratio(p_sum, y_sum) if y_sum != 0 else np.nan

    return {
        "mae_mw": mae,
        "rmse_mw": rmse,
        "nrmse_pct": nrmse,
        "bias_pct": bias,
        "pred_actual": pred_actual,
    }


def safe_corr(x, y):
    """计算两列的 Pearson 相关系数，容忍缺失。"""
    df = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(df) < 10:
        return np.nan
    return float(df["x"].corr(df["y"]))


def main():
    print("=" * 60)
    print("build_station_data_requirement_dataset.py")
    print("=" * 60)
    print(f"Project root: {ROOT}")

    METRICS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    # ── Load data ──────────────────────────────────────────────────────────────
    final_pkl = find_final_pkl()
    print(f"\nLoading {final_pkl.relative_to(ROOT)} ...")
    df = pd.read_pickle(final_pkl)
    print(f"  Shape: {df.shape}")
    print(f"  Columns: {list(df.columns)}")
    print(f"  Sites: {df['site_id'].nunique()}")
    print(f"  Splits: {df['split'].value_counts().to_dict()}")

    # ── Validate required columns ──────────────────────────────────────────────
    required = {"site_id", "power_mw", "power_pred_final", "capacity_mw", "split"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"缺少必要字段: {missing}")

    if "power_pred_final" not in df.columns:
        raise ValueError(
            "pkl 中没有 power_pred_final 列。"
            "不允许回退到 power_pred_cal 或其他旧列。"
        )

    # ── Enforce type ───────────────────────────────────────────────────────────
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour
    df["power_mw"] = pd.to_numeric(df["power_mw"], errors="coerce")
    df["power_pred_final"] = pd.to_numeric(df["power_pred_final"], errors="coerce")
    df["capacity_mw"] = pd.to_numeric(df["capacity_mw"], errors="coerce")

    # ── Filter: exclude future ────────────────────────────────────────────────
    df_hist = df[df["split"] != "future"].copy()
    print(f"\nAfter excluding future: {len(df_hist):,} rows")

    # Subsets
    day = df_hist[df_hist["hour"].between(6, 19)].copy()      # 6-19点
    noon = df_hist[df_hist["hour"].between(10, 14)].copy()     # 10-14点
    test_day = day[day["split"] == "test"].copy()             # test 6-19点
    test_noon = noon[noon["split"] == "test"].copy()          # test 10-14点

    # ── Per-site statistics ────────────────────────────────────────────────────
    rows = []
    site_ids = sorted(df_hist["site_id"].unique())
    print(f"\nProcessing {len(site_ids)} sites ...")

    for i, sid in enumerate(site_ids):
        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(site_ids)}]")

        g = df_hist[df_hist["site_id"] == sid]
        gd = day[day["site_id"] == sid]
        gn = noon[noon["site_id"] == sid]
        g_test = test_day[test_day["site_id"] == sid]
        g_noon_test = test_noon[test_noon["site_id"] == sid]

        row = {"site_id": sid}

        # site_name: derive from site_id if not present
        if "site_name" in g.columns and g["site_name"].notna().any():
            row["site_name"] = str(g["site_name"].dropna().iloc[0])
        else:
            row["site_name"] = str(sid)

        # capacity: use median of non-null values
        cap_vals = g["capacity_mw"].dropna()
        capacity = float(cap_vals.median()) if len(cap_vals) > 0 else np.nan
        row["capacity_mw"] = capacity

        # ── History sample counts ──────────────────────────────────────────
        row["history_samples_total"] = int(len(g))
        row["history_samples_6_19"] = int(len(gd))
        row["history_positive_samples_6_19"] = int((gd["power_mw"] > 0).sum())
        row["history_zero_ratio_6_19"] = (
            safe_ratio(int((gd["power_mw"] == 0).sum()), len(gd)) * 100
            if len(gd) > 0 else np.nan
        )

        # ── Train/valid/test counts (6-19) ──────────────────────────────────
        for split_name in ["train", "valid", "test"]:
            s = gd[gd["split"] == split_name]
            row[f"{split_name}_samples_6_19"] = int(len(s))

        # train+valid
        tv = gd[gd["split"].isin(["train", "valid"])]
        row["train_valid_samples_6_19"] = int(len(tv))
        row["train_valid_positive_samples_6_19"] = int((tv["power_mw"] > 0).sum())
        row["train_valid_zero_ratio_6_19"] = (
            safe_ratio(int((tv["power_mw"] == 0).sum()), len(tv)) * 100
            if len(tv) > 0 else np.nan
        )

        # ── Test quality ratios (6-19) ─────────────────────────────────────
        row["test_positive_samples_6_19"] = int((g_test["power_mw"] > 0).sum())
        row["test_zero_ratio_6_19"] = (
            safe_ratio(int((g_test["power_mw"] == 0).sum()), len(g_test)) * 100
            if len(g_test) > 0 else np.nan
        )
        row["test_missing_ratio_6_19"] = (
            safe_ratio(int(g_test["power_mw"].isna().sum()), len(g_test)) * 100
            if len(g_test) > 0 else np.nan
        )
        row["test_negative_ratio_6_19"] = (
            safe_ratio(int((g_test["power_mw"] < 0).sum()), len(g_test)) * 100
            if len(g_test) > 0 else np.nan
        )

        # ── 10-14 sample counts ────────────────────────────────────────────
        tv_noon = gn[gn["split"].isin(["train", "valid"])]
        row["train_valid_samples_10_14"] = int(len(tv_noon))
        row["train_valid_positive_samples_10_14"] = int((tv_noon["power_mw"] > 0).sum())
        row["test_samples_10_14"] = int(len(g_noon_test))
        row["test_positive_samples_10_14"] = int((g_noon_test["power_mw"] > 0).sum())
        row["test_zero_ratio_10_14"] = (
            safe_ratio(int((g_noon_test["power_mw"] == 0).sum()), len(g_noon_test)) * 100
            if len(g_noon_test) > 0 else np.nan
        )

        # ── Test error metrics (6-19) ───────────────────────────────────────
        m = calc_metrics(g_test, capacity)
        row["test_mae_mw"] = m["mae_mw"]
        row["test_rmse_mw"] = m["rmse_mw"]
        row["test_nrmse_pct"] = m["nrmse_pct"]
        row["test_bias_pct"] = m["bias_pct"]
        row["test_pred_actual"] = m["pred_actual"]

        # ── Test error metrics (10-14) ─────────────────────────────────────
        mn = calc_metrics(g_noon_test, capacity)
        row["test_10_14_mae_mw"] = mn["mae_mw"]
        row["test_10_14_rmse_mw"] = mn["rmse_mw"]
        row["test_10_14_nrmse_pct"] = mn["nrmse_pct"]
        row["test_10_14_bias_pct"] = mn["bias_pct"]

        # ── Per-hour NRMSE (6-19) ──────────────────────────────────────────
        for h in range(6, 20):
            gh = g_test[g_test["hour"] == h]
            mh = calc_metrics(gh, capacity)
            row[f"nrmse_h{h:02d}_pct"] = mh["nrmse_pct"]

        # ── Weather correlation (clear_sky_ghi) ──────────────────────────────
        # Only clear_sky_ghi is available; it is theoretical GHI, not measured.
        # Correlation with power_mw is meaningful (clear sky -> more power), so compute it.
        # But we note it is not a weather quality indicator per se.
        if "clear_sky_ghi" in df.columns:
            ghi_valid = gd["clear_sky_ghi"].notna()
            if ghi_valid.sum() > 10 and gd["power_mw"].notna().sum() > 10:
                row["ghi_power_corr"] = safe_corr(
                    gd.loc[ghi_valid, "clear_sky_ghi"],
                    gd.loc[ghi_valid, "power_mw"],
                )
                row["weather_missing_ratio"] = (
                    safe_ratio(int(gd["clear_sky_ghi"].isna().sum()), len(gd)) * 100
                    if len(gd) > 0 else np.nan
                )
            else:
                row["ghi_power_corr"] = np.nan
                row["weather_missing_ratio"] = np.nan
        else:
            row["ghi_power_corr"] = np.nan
            row["weather_missing_ratio"] = np.nan

        # ── Quality flags ──────────────────────────────────────────────────
        # capacity_changed_flag: 容量在历史中是否变化
        cap_unique = g["capacity_mw"].dropna().nunique()
        row["capacity_changed_flag"] = int(cap_unique > 1)

        # suspected_curtailment_flag: 需要人工判断，当前置 NaN
        row["suspected_curtailment_flag"] = np.nan

        # mapping_issue_flag: 需要人工判断，当前置 NaN
        row["mapping_issue_flag"] = np.nan

        # all_zero_or_invalid_flag: 历史中完全没有正功率样本
        row["all_zero_or_invalid_flag"] = int(row["history_positive_samples_6_19"] == 0)

        rows.append(row)

    # ── Build DataFrame ──────────────────────────────────────────────────────
    out = pd.DataFrame(rows)

    # Sort by site_id
    out = out.sort_values("site_id").reset_index(drop=True)

    # ── Write CSV ────────────────────────────────────────────────────────────
    out_path = METRICS / "round48_station_data_requirement_analysis.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] Wrote: {out_path}")
    print(f"     Shape: {out.shape}")
    print(f"     Columns: {len(out.columns)}")

    # ── Quick sanity print ───────────────────────────────────────────────────
    key_cols = [
        "site_id", "capacity_mw",
        "train_valid_samples_6_19", "test_nrmse_pct", "test_10_14_nrmse_pct",
        "all_zero_or_invalid_flag",
    ]
    print(f"\n[Preview] Key columns:")
    print(out[key_cols].to_string(index=False))

    # ── Write documentation ─────────────────────────────────────────────────
    weather_note = (
        "气象字段：仅含 clear_sky_ghi（理论晴空辐照），"
        "已计算其与 power_mw 的相关系数（ghi_power_corr）。"
        "注意：clear_sky_ghi 是理论值，不代表实际气象匹配质量。"
        "原始 GHI、辐照、温度、风速等字段均不可用。"
    ) if "clear_sky_ghi" not in df.columns else (
        "气象字段：仅含 clear_sky_ghi（理论晴空辐照）。"
        "ghi_power_corr 已计算，反映理论辐照与功率的相关性。"
        "原始 GHI、辐照、温度、风速等字段均不可用。"
    )

    doc_path = DOCS / "Round48_样本量需求分析数据说明.md"
    doc_path.write_text(
        f"""# Round48 样本量需求分析数据说明

## 生成文件

- `output/pv_pipeline/metrics/round48_station_data_requirement_analysis.csv`
- `output/pv_pipeline/docs/Round48_样本量需求分析数据说明.md`

## 数据来源

`{final_pkl.relative_to(ROOT)}`
- 行数：{len(df):,}
- 站点数：{df["site_id"].nunique()}
- split 分布：{df["split"].value_counts().to_dict()}

## 统计口径

- **不包含** `future` split
- **历史样本** = train + valid + test
- **白天样本** = 小时 6-19
- **中午样本** = 小时 10-14
- **正功率样本** = power_mw > 0
- **NRMSE** = RMSE / capacity_mw × 100%
- **测试误差** 仅使用 test 集计算

## 字段说明

| 字段 | 说明 |
|------|------|
| `site_id` | 站点编号 |
| `site_name` | 站点名称（无 site_name 列时等于 site_id）|
| `capacity_mw` | 额定装机容量（中位数）|
| `history_samples_total` | 历史总样本数（不含 future）|
| `history_samples_6_19` | 历史白天样本数（6-19点）|
| `history_positive_samples_6_19` | 历史白天正功率样本数 |
| `history_zero_ratio_6_19` | 历史白天零值比例（%）|
| `*_samples_6_19` | train/valid/test 白天样本数 |
| `train_valid_*` | train + valid 合计 |
| `test_zero_ratio_6_19` | 测试集白天零值比例 |
| `test_missing_ratio_6_19` | 测试集白天缺失比例 |
| `test_negative_ratio_6_19` | 测试集白天负功率比例 |
| `test_mae_mw` | 测试集 MAE（MW）|
| `test_rmse_mw` | 测试集 RMSE（MW）|
| `test_nrmse_pct` | 测试集 NRMSE（%）|
| `test_bias_pct` | 测试集 BIAS（%）|
| `test_pred_actual` | 测试集 预测总量/实际总量 |
| `test_10_14_*` | 测试集 10-14点 同类指标 |
| `nrmse_h{h:02d}_pct` | 测试集第 h 小时 NRMSE（%）|
| `ghi_power_corr` | clear_sky_ghi 与功率的 Pearson 相关系数 |
| `weather_missing_ratio` | clear_sky_ghi 缺失比例（%）|
| `capacity_changed_flag` | 容量是否变化（0/1）|
| `suspected_curtailment_flag` | 疑似限电旗标（需人工标注，当前为空）|
| `mapping_issue_flag` | 映射问题旗标（需人工标注，当前为空）|
| `all_zero_or_invalid_flag` | 全历史无正功率样本（0/1）|

## 注意事项

- `suspected_curtailment_flag` 和 `mapping_issue_flag` 当前需要人工判断，值均为空。
- {weather_note}

## 统计摘要

站点数：{len(out)}

训练+验证样本（6-19点）：
  - 均值：{out["train_valid_samples_6_19"].mean():.0f}
  - 中位数：{out["train_valid_samples_6_19"].median():.0f}
  - 最小：{out["train_valid_samples_6_19"].min():.0f}
  - 最大：{out["train_valid_samples_6_19"].max():.0f}

测试集 NRMSE（6-19点）：
  - 均值：{out["test_nrmse_pct"].mean():.2f}%
  - 中位数：{out["test_nrmse_pct"].median():.2f}%

测试集 NRMSE（10-14点）：
  - 均值：{out["test_10_14_nrmse_pct"].mean():.2f}%
  - 中位数：{out["test_10_14_nrmse_pct"].median():.2f}%
""",
        encoding="utf-8",
    )
    print(f"\n[OK] Wrote: {doc_path}")
    print("\n[PASS] build_station_data_requirement_dataset.py completed")


if __name__ == "__main__":
    main()
