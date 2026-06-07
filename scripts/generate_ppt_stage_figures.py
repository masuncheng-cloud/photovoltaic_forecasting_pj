#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 PPT 使用的阶段 2、3、4 单图效果图。

输出：
1. 阶段2_集中式反演辐照_nRMSE热力图.png
2. 阶段3_融合辐照空间分布图.png
3. 阶段4_全市真实预测功率对比曲线.png
4. 图表数据来源说明.md
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "pv_pipeline"
FIG_DIR = OUT_DIR / "ppt_figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def setup_chinese_font() -> None:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/arphic/SimSun.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for p in candidates:
        if Path(p).exists():
            font_manager.fontManager.addfont(p)
            prop = font_manager.FontProperties(fname=p)
            plt.rcParams["font.family"] = prop.get_name()
            break
    plt.rcParams["axes.unicode_minus"] = False


def find_latest_prediction_table() -> tuple[pd.DataFrame, Path]:
    candidates = [
        OUT_DIR / "predictions" / "distributed_predictions_final_full.pkl",
        OUT_DIR / "predictions" / "distributed_predictions_final_eval.pkl",
        OUT_DIR / "predictions" / "distributed_predictions_final.pkl",
        OUT_DIR / "distributed_predictions_final_full.pkl",
        OUT_DIR / "distributed_predictions_final_eval.pkl",
        OUT_DIR / "distributed_predictions_final.pkl",
    ]
    for p in candidates:
        if p.exists():
            df = pd.read_pickle(p)
            return df, p
    raise FileNotFoundError("未找到最终预测 pkl。")


def pick_pred_col(df: pd.DataFrame) -> str:
    for c in ["power_pred_final", "power_pred", "pred_mw", "power_pred_cal", "prediction_mw"]:
        if c in df.columns:
            return c
    raise KeyError("预测表中未找到预测功率列。")


def pick_time_col(df: pd.DataFrame) -> str:
    for c in ["datetime", "time", "timestamp", "date_time"]:
        if c in df.columns:
            return c
    raise KeyError("未找到时间列。")


def nrmse(y_true, y_pred, denom) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    denom = float(denom)
    if len(y_true) == 0 or not np.isfinite(denom) or denom <= 0:
        return np.nan
    return math.sqrt(np.mean((y_pred - y_true) ** 2)) / denom * 100


def generate_stage2_heatmap(sources: list[str]) -> None:
    """
    从 inverse_metrics.csv（反演辐照）和 irradiance_blend_metrics.csv（辐照融合）
    读取 nRMSE 指标。功率估计阶段从预测表推导。
    """
    inv_path = OUT_DIR / "metrics" / "inverse_metrics.csv"
    blend_path = OUT_DIR / "metrics" / "irradiance_blend_metrics.csv"

    inv_df = pd.read_csv(inv_path) if inv_path.exists() else None
    blend_df = pd.read_csv(blend_path) if blend_path.exists() else None

    stages = ["反演辐照", "辐照融合", "功率估计"]
    splits = ["训练集", "验证集", "测试集"]
    mat = pd.DataFrame(np.nan, index=stages, columns=splits)

    if inv_df is not None:
        for _, r in inv_df.iterrows():
            sp = str(r["split"]).lower()
            v = pd.to_numeric(r["irr_nrmse"], errors="coerce")
            split_name = None
            if "train" in sp:
                split_name = "训练集"
            elif "valid" in sp:
                split_name = "验证集"
            elif "test" in sp:
                split_name = "测试集"
            if split_name and pd.notna(v):
                mat.loc["反演辐照", split_name] = float(v)

    if blend_df is not None:
        for _, r in blend_df.iterrows():
            sp = str(r["split"]).lower()
            v = pd.to_numeric(r["nrmse_blend"], errors="coerce")
            split_name = None
            if "train" in sp:
                split_name = "训练集"
            elif "valid" in sp:
                split_name = "验证集"
            elif "test" in sp:
                split_name = "测试集"
            if split_name and pd.notna(v):
                mat.loc["辐照融合", split_name] = float(v)

    pred_df, pred_path = find_latest_prediction_table()
    pred_col = pick_pred_col(pred_df)
    cap = "capacity_mw"
    for sp_raw, sp_name in [("train", "训练集"), ("valid", "验证集"), ("test", "测试集")]:
        if pd.isna(mat.loc["功率估计", sp_name]):
            sub = pred_df[pred_df["split"].astype(str).str.lower().eq(sp_raw)]
            sub = sub[(sub["hour"] >= 6) & (sub["hour"] <= 19)]
            if cap in sub.columns:
                denom = pd.to_numeric(sub[cap], errors="coerce").dropna().mean()
            else:
                denom = pd.to_numeric(sub["power_mw"], errors="coerce").dropna().mean()
            mat.loc["功率估计", sp_name] = nrmse(
                pd.to_numeric(sub["power_mw"], errors="coerce"),
                pd.to_numeric(sub[pred_col], errors="coerce"),
                denom,
            )

    source_parts = []
    if inv_df is not None:
        source_parts.append(f"反演辐照阶段读取 {inv_path.name}")
    if blend_df is not None:
        source_parts.append(f"辐照融合阶段读取 {blend_path.name}")
    source_parts.append(f"功率估计从 {pred_path.name} 推导")
    sources.append("；".join(source_parts))

    fig, ax = plt.subplots(figsize=(10.5, 6), dpi=220)
    values = mat.values.astype(float)
    im = ax.imshow(values, cmap="YlGnBu", aspect="auto", vmin=0)
    ax.set_xticks(range(len(splits)), splits, fontsize=13)
    ax.set_yticks(range(len(stages)), stages, fontsize=13)
    ax.set_title("阶段 2：集中式反演辐照模型 nRMSE 热力图", fontsize=18, pad=18)

    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            v = values[i, j]
            label = "-" if np.isnan(v) else f"{v:.2f}%"
            ax.text(j, i, label, ha="center", va="center", fontsize=14, color="#1f2d3d")

    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.03)
    cbar.set_label("nRMSE（%）", fontsize=12)
    ax.tick_params(length=0)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "阶段2_集中式反演辐照_nRMSE热力图.png", bbox_inches="tight")
    plt.close(fig)


def generate_stage3_spatial_irradiance(sources: list[str]) -> None:
    site_meta = pd.read_csv(OUT_DIR / "tables" / "site_master.csv")

    pred_df, pred_path = find_latest_prediction_table()
    time_col = pick_time_col(pred_df)
    pred_df[time_col] = pd.to_datetime(pred_df[time_col])
    if "split" in pred_df.columns:
        pred_df = pred_df[pred_df["split"].astype(str).str.lower().eq("test")]

    irr_col = "g_blend_pred"

    pred_df["date"] = pred_df[time_col].dt.date
    pred_df["hour"] = pred_df[time_col].dt.hour
    mid = pred_df[pred_df["hour"].between(10, 14)].copy()
    day_score = mid.groupby("date")[irr_col].mean().sort_values(ascending=False)
    if day_score.empty:
        raise ValueError("测试集 10-14 点无可用辐照样本。")
    date_pick = day_score.index[0]

    irr_by_site = (
        mid[mid["date"].eq(date_pick)]
        .groupby("site_id", as_index=False)[irr_col]
        .mean()
    )
    irr_by_site = irr_by_site.dropna(subset=[irr_col])

    merged = irr_by_site.merge(
        site_meta[["site_id", "lon", "lat"]], on="site_id", how="inner"
    )
    merged = merged.dropna(subset=["lon", "lat"])
    if merged.empty:
        raise ValueError("融合辐照与站点经纬度合并为空，请检查 site_master.csv 中的 site_id。")

    fig, ax = plt.subplots(figsize=(10.5, 7), dpi=220)
    sc = ax.scatter(
        merged["lon"],
        merged["lat"],
        c=merged[irr_col],
        s=70,
        cmap="YlOrRd",
        edgecolors="white",
        linewidths=0.8,
    )
    ax.set_title(f"阶段 3：融合辐照空间分布图（{date_pick}，10-14 点均值）", fontsize=18, pad=18)
    ax.set_xlabel("经度", fontsize=13)
    ax.set_ylabel("纬度", fontsize=13)
    ax.grid(True, linestyle="--", alpha=0.25)
    cbar = fig.colorbar(sc, ax=ax, fraction=0.035, pad=0.03)
    cbar.set_label("融合辐照（W/m\u00b2）", fontsize=12)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "阶段3_融合辐照空间分布图.png", bbox_inches="tight")
    plt.close(fig)

    sources.append(
        f"阶段 3 空间图读取 {pred_path.name}（融合辐照列 {irr_col}）+ site_master.csv（经纬度），"
        f"选取测试集 {date_pick} 10-14 点均值，共 {len(merged)} 个站点。"
    )


def generate_stage4_city_curve(sources: list[str]) -> None:
    raw_df, pred_path = find_latest_prediction_table()
    time_col = pick_time_col(raw_df)
    pred_col = pick_pred_col(raw_df)

    df = raw_df.copy()
    df[time_col] = pd.to_datetime(df[time_col])
    df["datetime"] = df[time_col]
    df["pred_mw_use"] = pd.to_numeric(df[pred_col], errors="coerce")
    df["actual_mw_use"] = pd.to_numeric(df["power_mw"], errors="coerce")
    df["hour"] = df[time_col].dt.hour

    if "split" in df.columns:
        df = df[df["split"].astype(str).str.lower().eq("test")]
    df = df[df["hour"].between(6, 19)]
    df = df[df["actual_mw_use"].notna() & df["pred_mw_use"].notna()]

    cap = "capacity_mw"
    df["date"] = df[time_col].dt.date

    site_col = next((c for c in ["site_id", "station_id"] if c in df.columns), None)

    day_rows = []
    for date, g in df.groupby("date"):
        city = g.groupby("datetime", as_index=False).agg(
            actual=("actual_mw_use", "sum"),
            pred=("pred_mw_use", "sum"),
        )
        if len(city) < 10:
            continue
        if cap in g.columns and site_col:
            denom = g.drop_duplicates(site_col)[cap].sum()
        else:
            denom = city["actual"].max()
        val = nrmse(city["actual"], city["pred"], denom)
        day_rows.append((date, val, len(city)))

    if not day_rows:
        raise ValueError("无法选择代表日。")
    day_df = pd.DataFrame(day_rows, columns=["date", "nrmse", "n"])
    date_pick = day_df.sort_values(["nrmse", "date"]).iloc[0]["date"]

    show = (
        df[df["date"].eq(date_pick)]
        .groupby("datetime", as_index=False)
        .agg(
            actual=("actual_mw_use", "sum"),
            pred=("pred_mw_use", "sum"),
        )
        .sort_values("datetime")
    )

    fig, ax = plt.subplots(figsize=(11, 6.2), dpi=220)
    ax.plot(show["datetime"], show["actual"], color="#2f80d8", lw=2.8, marker="o", ms=3.5, label="真实功率")
    ax.plot(show["datetime"], show["pred"], color="#f2994a", lw=2.8, marker="o", ms=3.5, label="预测功率")
    ax.set_title(f"阶段 4：全市真实/预测功率对比曲线（{date_pick}）", fontsize=18, pad=18)
    ax.set_xlabel("时间", fontsize=13)
    ax.set_ylabel("全市功率（MW）", fontsize=13)
    ax.grid(True, linestyle="--", alpha=0.25)
    ax.legend(frameon=False, fontsize=12, loc="upper left")
    fig.autofmt_xdate(rotation=20)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "阶段4_全市真实预测功率对比曲线.png", bbox_inches="tight")
    plt.close(fig)

    sources.append(
        f"阶段 4 曲线读取 {pred_path.name}，使用测试集 6-19 点，"
        f"自动选择城市日级 nRMSE 最低的代表日 {date_pick}。"
    )


def write_report(sources: list[str]) -> None:
    report = FIG_DIR / "图表数据来源说明.md"
    lines = [
        "# PPT 阶段效果图数据来源说明",
        "",
        "本目录图表由 `scripts/generate_ppt_stage_figures.py` 根据当前项目最新训练产物生成。",
        "",
        "## 输出文件",
        "",
        "- `阶段2_集中式反演辐照_nRMSE热力图.png`",
        "- `阶段3_融合辐照空间分布图.png`",
        "- `阶段4_全市真实预测功率对比曲线.png`",
        "",
        "## 数据来源",
        "",
    ]
    for s in sources:
        lines.append(f"- {s}")
    lines += [
        "",
        "## 口径说明",
        "",
        "- 默认排除 future 行（预测表中无 future 列时此条不适用）。",
        "- 若存在 split 列，阶段 3 和阶段 4 默认使用 test 集。",
        "- 阶段 4 仅统计 6-19 点。",
        "- 图中数值随重新训练后的最终预测产物变化而变化。",
        "",
    ]
    report.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    setup_chinese_font()
    sources: list[str] = []
    generate_stage2_heatmap(sources)
    generate_stage3_spatial_irradiance(sources)
    generate_stage4_city_curve(sources)
    write_report(sources)
    print("[OK] PPT figures saved to:", FIG_DIR)


if __name__ == "__main__":
    main()
