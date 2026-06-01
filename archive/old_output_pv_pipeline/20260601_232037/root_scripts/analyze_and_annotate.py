#!/usr/bin/env python3
"""
对每个站点计算预测误差指标，标注：
1. 最好的5个站点
2. 最差的5个站点
3. 有问题的站点（零值过多 or 样本数过少）
"""

import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path("/root/autodl-tmp/photovoltaic_forecasting_pj/output/pv_pipeline/metrics")

files = {
    "前38座": BASE / "分布式光伏预测_前38座_真实预测对照.csv",
    "后40座": BASE / "分布式光伏预测_后40座_真实预测对照.csv",
}


def compute_station_metrics(df):
    """计算每个站点的预测指标"""
    real_cols = sorted([c for c in df.columns if c.endswith("_总出力值")])
    results = []

    for real_col in real_cols:
        station = real_col.replace("_总出力值", "")
        pred_col = station + "_预测"

        if pred_col not in df.columns:
            continue

        real = pd.to_numeric(df[real_col], errors="coerce").fillna(0)
        pred = pd.to_numeric(df[pred_col], errors="coerce").fillna(0)

        # 排除全0行用于指标计算（白天时段）
        mask = real > 0

        n_total = len(real)
        n_zero = (real == 0).sum()
        n_nonzero = mask.sum()
        zero_rate = n_zero / n_total * 100

        if n_nonzero > 0:
            mae = np.abs(real[mask] - pred[mask]).mean()
            rmse = np.sqrt(((real[mask] - pred[mask]) ** 2).mean())
            mape = (np.abs(real[mask] - pred[mask]) / real[mask]).mean() * 100
            # 相对误差（预测值/真实值），超过100%算偏离极大
            over_pred = (pred[mask] / real[mask]).mean()
        else:
            mae = rmse = mape = over_pred = np.nan

        # 真实值最大值（装机容量估算）
        max_real = real.max()

        results.append({
            "站点": station,
            "n_total": n_total,
            "n_nonzero": n_nonzero,
            "n_zero": n_zero,
            "zero_rate": zero_rate,
            "max_real": max_real,
            "MAE": mae,
            "RMSE": rmse,
            "MAPE": mape,
            "pred_real_ratio": over_pred,
        })

    return pd.DataFrame(results)


def make_annotation(row):
    """生成单个站点的标注文字"""
    flags = []

    # 0值过多
    if row["zero_rate"] > 50:
        flags.append(f"🔵 0值过多(零值率{round(row['zero_rate'])}%)")
    elif row["zero_rate"] > 40:
        flags.append(f"🔵 0值偏多(零值率{round(row['zero_rate'])}%)")

    # 样本数过少（非零样本）
    if row["n_nonzero"] < 3000:
        flags.append(f"🟠 有效样本少(n={int(row['n_nonzero'])})")

    # 预测偏离极大
    if not np.isnan(row["pred_real_ratio"]) and (row["pred_real_ratio"] < 0.3 or row["pred_real_ratio"] > 2.0):
        flags.append(f"⚠️ 预测偏离极大(预测/真实={round(row['pred_real_ratio'],2)})")

    # MAE 极高
    if not np.isnan(row["MAE"]):
        if row["MAE"] > 0.8:
            flags.append(f"🔴 MAE极高({round(row['MAE'],2)}MW)")
        elif row["MAE"] > 0.3:
            flags.append(f"🟡 MAE偏高({round(row['MAE'],2)}MW)")

    return " | ".join(flags) if flags else "✅ 正常"


for label, fpath in files.items():
    print(f"\n{'='*60}")
    print(f"▶ {label}: {fpath.name}")
    print('='*60)

    df = pd.read_csv(fpath)
    metrics = compute_station_metrics(df)

    # 过滤有效站点（非零样本>0）
    valid = metrics[metrics["n_nonzero"] > 0].copy()

    # 用 MAE / max_real 作为相对误差指标，找最好/最差
    valid["MAE_normalized"] = valid["MAE"] / valid["max_real"].replace(0, np.nan)

    best5 = valid.nsmallest(5, "MAE")
    worst5 = valid.nlargest(5, "MAE")

    print(f"\n📊 共 {len(metrics)} 个站点，非零样本>0的有 {len(valid)} 个\n")

    print("🟢 预测最好的5个站点:")
    for _, r in best5.iterrows():
        note = "✅ 最好站点(MAE<0.1MW)" if r["MAE"] < 0.1 else ""
        print(f"  {r['站点']}: MAE={round(r['MAE'],4)}, RMSE={round(r['RMSE'],4)}, MAPE={round(r['MAPE'],1)}% {note}")

    print("\n🔴 预测最差的5个站点:")
    for _, r in worst5.iterrows():
        note = "🔴 最差站点(MAE>0.8MW)" if r["MAE"] > 0.8 else ""
        print(f"  {r['站点']}: MAE={round(r['MAE'],4)}, RMSE={round(r['RMSE'],4)}, MAPE={round(r['MAPE'],1)}% {note}")

    print("\n🔵 存在问题的站点:")
    for _, r in metrics.iterrows():
        ann = make_annotation(r)
        if ann != "✅ 正常":
            print(f"  {r['站点']}: {ann}")

    # 保存指标汇总
    metrics["标注"] = metrics.apply(make_annotation, axis=1)
    out_summary = fpath.with_name(fpath.stem.replace("真实预测对照", "") + "指标汇总.csv")
    metrics.to_csv(out_summary, index=False, encoding="utf-8-sig")
    print(f"\n💾 指标汇总已保存: {out_summary}")

    # 更新原CSV的"站点问题标注"列
    annot_map = dict(zip(metrics["站点"], metrics["标注"]))
    df_out = df.copy()

    # 为每个站点生成合并标注
    all_notes = []
    for _, row in df_out.iterrows():
        notes = []
        for station, note in annot_map.items():
            if note != "✅ 正常":
                notes.append(f"{station}: {note}")
        df_out.at[_, "站点问题标注"] = " | ".join(notes) if notes else "✅ 全部正常"

    df_out.to_csv(fpath, index=False, encoding="utf-8-sig")
    print(f"💾 已更新原文件标注: {fpath}")
