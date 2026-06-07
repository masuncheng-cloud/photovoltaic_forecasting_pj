#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重生成阶段 2、3、4 PPT 学术风单图效果图。

适配说明（基于 /root/autodl-tmp/photovoltaic_forecasting_pj 项目当前数据）：
- 阶段2：无阶段级汇总文件，前两行显示"未导出"，仅功率估计行从预测表推导
- 阶段3：预测表不含经纬度，需合并 site_master.csv 获取站点 lon/lat
- 阶段4：预测表含 site_id + capacity_mw，可直接使用
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib import font_manager


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "pv_pipeline"
FIG_DIR = OUT_DIR / "ppt_figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def setup_chinese_font() -> None:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
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
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.facecolor"] = "white"


def find_prediction_table() -> tuple[pd.DataFrame, Path]:
    candidates = [
        OUT_DIR / "predictions" / "distributed_predictions_final_full.pkl",
        OUT_DIR / "predictions" / "distributed_predictions_final_eval.pkl",
        OUT_DIR / "distributed_predictions_final_full.pkl",
        OUT_DIR / "distributed_predictions_final_eval.pkl",
        OUT_DIR / "distributed_predictions_final.pkl",
    ]
    for p in candidates:
        if p.exists():
            return pd.read_pickle(p), p

    all_pkl = sorted(OUT_DIR.rglob("*.pkl"), key=lambda x: x.stat().st_mtime, reverse=True)
    for p in all_pkl:
        try:
            df = pd.read_pickle(p)
        except Exception:
            continue
        cols = set(df.columns)
        if {"power_mw"}.issubset(cols) and any(
            c in cols for c in ["power_pred_final", "power_pred", "pred_mw", "power_pred_cal"]
        ):
            return df, p
    raise FileNotFoundError("未找到最终预测表，请先完成训练。")


def pick_time_col(df: pd.DataFrame) -> str:
    for c in ["datetime", "time", "timestamp", "date_time"]:
        if c in df.columns:
            return c
    raise KeyError("未找到时间列。")


def pick_pred_col(df: pd.DataFrame) -> str:
    for c in ["power_pred_final", "power_pred", "pred_mw", "power_pred_cal", "prediction_mw"]:
        if c in df.columns:
            return c
    raise KeyError("未找到预测功率列。")


def pick_capacity_col(df: pd.DataFrame) -> str | None:
    for c in ["capacity_mw", "capacity", "installed_capacity_mw", "cap_mw"]:
        if c in df.columns:
            return c
    return None


def pick_site_col(df: pd.DataFrame) -> str:
    for c in ["site_id", "station_id", "station_name", "站点ID", "站点名称"]:
        if c in df.columns:
            return c
    raise KeyError("未找到站点列。")


def to_eval_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    time_col = pick_time_col(df)
    pred_col = pick_pred_col(df)
    df["datetime"] = pd.to_datetime(df[time_col])
    df["hour"] = df["datetime"].dt.hour
    df["actual_mw"] = pd.to_numeric(df["power_mw"], errors="coerce")
    df["pred_mw"] = pd.to_numeric(df[pred_col], errors="coerce")
    if "split" in df.columns:
        df = df[df["split"].astype(str).str.lower().eq("test")]
    if "is_future" in df.columns:
        df = df[~df["is_future"].fillna(False).astype(bool)]
    df = df[df["hour"].between(6, 19)]
    df = df[df["actual_mw"].notna() & df["pred_mw"].notna()]
    return df


def nrmse(y_true, y_pred, denom) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    denom = float(denom)
    if len(y_true) == 0 or not np.isfinite(denom) or denom <= 0:
        return np.nan
    return math.sqrt(np.mean((y_pred - y_true) ** 2)) / denom * 100


def read_stage_metrics() -> pd.DataFrame | None:
    candidates = [
        OUT_DIR / "metrics" / "stage_nrmse_summary.csv",
        OUT_DIR / "metrics" / "three_stage_nrmse.csv",
        OUT_DIR / "metrics" / "stage_metrics.csv",
        OUT_DIR / "docs" / "stage_nrmse_summary.csv",
        OUT_DIR / "ppt_figures" / "stage_nrmse_summary.csv",
    ]
    for p in candidates:
        if p.exists():
            return pd.read_csv(p)
    return None


# ---------------------------------------------------------------------------
# Stage 2: 正方形红色系 nRMSE 热力图
# ---------------------------------------------------------------------------

def generate_stage2_heatmap(notes: list[str]) -> None:
    stages = ["反演辐照", "辐照融合", "功率估计"]
    splits = ["训练集", "验证集", "测试集"]
    mat = pd.DataFrame(np.nan, index=stages, columns=splits)

    # 优先尝试从阶段级汇总文件读取
    metric_df = read_stage_metrics()
    if metric_df is not None:
        cols = {c.lower(): c for c in metric_df.columns}
        stage_col = cols.get("stage") or cols.get("阶段")
        split_col = cols.get("split") or cols.get("数据集")
        val_col = (
            cols.get("nrmse")
            or cols.get("nrmse_pct")
            or cols.get("nrmse_%")
            or cols.get("nrmse（%）")
        )
        if stage_col and split_col and val_col:
            for _, r in metric_df.iterrows():
                stage_raw = str(r[stage_col])
                split_raw = str(r[split_col]).lower()
                value = pd.to_numeric(r[val_col], errors="coerce")

                if "反演" in stage_raw or "inverse" in stage_raw:
                    stage = "反演辐照"
                elif "融合" in stage_raw or "blend" in stage_raw or "fused" in stage_raw:
                    stage = "辐照融合"
                elif "功率" in stage_raw or "power" in stage_raw:
                    stage = "功率估计"
                else:
                    continue

                if "train" in split_raw or "训练" in split_raw:
                    split = "训练集"
                elif "valid" in split_raw or "验证" in split_raw:
                    split = "验证集"
                elif "test" in split_raw or "测试" in split_raw:
                    split = "测试集"
                else:
                    continue

                if pd.notna(value):
                    mat.loc[stage, split] = float(value)
            notes.append("阶段2热力图从阶段级 nRMSE 汇总文件读取。")

    # 无阶段级汇总时：前两行保留 NaN（显示"未导出"），只计算功率估计行
    if mat.loc["功率估计"].isna().all():
        df, src = find_prediction_table()
        cap = pick_capacity_col(df)
        pred_col = pick_pred_col(df)
        time_col = pick_time_col(df)
        if cap is None or "split" not in df.columns:
            notes.append("阶段2未找到阶段级指标，也无法从预测表推导——三行均标记为未导出。")
        else:
            df = df.copy()
            df["datetime"] = pd.to_datetime(df[time_col])
            df["hour"] = df["datetime"].dt.hour
            if "is_future" in df.columns:
                df = df[~df["is_future"].fillna(False).astype(bool)]
            df = df[df["hour"].between(6, 19)]
            for split_raw, split_name in [
                ("train", "训练集"),
                ("valid", "验证集"),
                ("test", "测试集"),
            ]:
                sub = df[df["split"].astype(str).str.lower().eq(split_raw)]
                denom = pd.to_numeric(sub[cap], errors="coerce").mean()
                mat.loc["功率估计", split_name] = nrmse(
                    pd.to_numeric(sub["power_mw"], errors="coerce"),
                    pd.to_numeric(sub[pred_col], errors="coerce"),
                    denom,
                )
            notes.append(
                f"阶段2未找到阶段级汇总，功率估计行从 {src.name} 推导；"
                "反演辐照/辐照融合行标记为未导出。"
            )

    values = mat.values.astype(float)
    masked = np.ma.masked_invalid(values)
    cmap = plt.cm.Reds.copy()
    cmap.set_bad(color="#f2f2f2")

    vmax = np.nanmax(values) if np.isfinite(values).any() else 1
    vmax = max(vmax, 1)
    norm = mcolors.Normalize(vmin=0, vmax=vmax * 1.15)

    fig, ax = plt.subplots(figsize=(8, 8), dpi=260)
    im = ax.imshow(masked, cmap=cmap, norm=norm, aspect="equal")

    ax.set_title("阶段 2：集中式反演辐照模型 nRMSE", fontsize=19, pad=20)
    ax.set_xticks(range(len(splits)), splits, fontsize=14)
    ax.set_yticks(range(len(stages)), stages, fontsize=14)
    ax.tick_params(length=0)

    # 白色单元格边框
    ax.set_xticks(np.arange(-0.5, len(splits), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(stages), 1), minor=True)
    ax.grid(which="minor", color="white", linestyle="-", linewidth=3)
    ax.tick_params(which="minor", bottom=False, left=False)

    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            v = values[i, j]
            if np.isnan(v):
                label = "未导出"
                color = "#777777"
            else:
                label = f"{v:.2f}%"
                color = "#222222"
            ax.text(j, i, label, ha="center", va="center", fontsize=15, color=color)

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("nRMSE（%）", fontsize=13)
    cbar.ax.tick_params(labelsize=11)

    fig.tight_layout()
    fig.savefig(
        FIG_DIR / "阶段2_集中式反演辐照_nRMSE热力图_v2.png",
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)


# ---------------------------------------------------------------------------
# Stage 3: 融合辐照空间分布图（分位数拉伸颜色）
# ---------------------------------------------------------------------------

def generate_stage3_spatial(notes: list[str]) -> None:
    pred_df, src = find_prediction_table()
    site_meta = pd.read_csv(OUT_DIR / "tables" / "site_master.csv")

    # 准备时间列
    time_col = pick_time_col(pred_df)
    pred_df = pred_df.copy()
    pred_df["datetime"] = pd.to_datetime(pred_df[time_col])
    pred_df["hour"] = pred_df["datetime"].dt.hour
    pred_df["date"] = pred_df["datetime"].dt.date

    if "split" in pred_df.columns:
        pred_df = pred_df[pred_df["split"].astype(str).str.lower().eq("test")]
    if "is_future" in pred_df.columns:
        pred_df = pred_df[~pred_df["is_future"].fillna(False).astype(bool)]

    # 融合辐照列（项目使用 g_blend_pred）
    irr_col = "g_blend_pred"

    # 选取 10-14 点空间离散度最大的日期（避免所有点同色）
    mid = pred_df[pred_df["hour"].between(10, 14)].copy()
    day_spread = mid.groupby("date")[irr_col].agg(
        lambda x: np.nanpercentile(x, 90) - np.nanpercentile(x, 10)
    )
    day_spread = day_spread.replace([np.inf, -np.inf], np.nan).dropna().sort_values(
        ascending=False
    )
    if day_spread.empty:
        raise ValueError("阶段3没有可用 10-14 点辐照数据。")
    date_pick = day_spread.index[0]

    # 站点级辐照均值
    site_irr = (
        mid[mid["date"].eq(date_pick)]
        .groupby("site_id", as_index=False)[irr_col]
        .mean()
    )
    site_irr = site_irr.dropna(subset=[irr_col])

    # 合并站点经纬度（site_master.csv 有 lon/lat）
    merged = site_irr.merge(
        site_meta[["site_id", "lon", "lat"]], on="site_id", how="inner"
    )
    merged = merged.dropna(subset=["lon", "lat", irr_col])
    if merged.empty:
        raise ValueError("融合辐照与站点经纬度合并为空。")

    # 分位数拉伸颜色，突出空间差异
    vmin = np.nanpercentile(merged[irr_col], 5)
    vmax = np.nanpercentile(merged[irr_col], 95)
    if not np.isfinite(vmin) or not np.isfinite(vmax) or abs(vmax - vmin) < 1e-9:
        vmin = float(merged[irr_col].min())
        vmax = float(merged[irr_col].max())
    if abs(vmax - vmin) < 1e-9:
        vmax = vmin + 1

    fig, ax = plt.subplots(figsize=(8.6, 8.0), dpi=260)
    sc = ax.scatter(
        merged["lon"],
        merged["lat"],
        c=merged[irr_col],
        cmap="YlOrRd",
        vmin=vmin,
        vmax=vmax,
        s=90,
        edgecolors="white",
        linewidths=0.9,
    )
    ax.set_title(
        f"阶段 3：融合辐照空间分布（{date_pick}，10-14 点）",
        fontsize=18,
        pad=18,
    )
    ax.set_xlabel("经度", fontsize=13)
    ax.set_ylabel("纬度", fontsize=13)
    ax.grid(True, linestyle="--", linewidth=0.8, alpha=0.25)

    # 收紧坐标范围，减少底部留白
    lon_pad = max((merged["lon"].max() - merged["lon"].min()) * 0.08, 0.03)
    lat_pad = max((merged["lat"].max() - merged["lat"].min()) * 0.08, 0.03)
    ax.set_xlim(merged["lon"].min() - lon_pad, merged["lon"].max() + lon_pad)
    ax.set_ylim(merged["lat"].min() - lat_pad, merged["lat"].max() + lat_pad)

    cbar = fig.colorbar(sc, ax=ax, fraction=0.046, pad=0.035)
    cbar.set_label("融合辐照（W/m\u00b2）", fontsize=13)
    cbar.ax.tick_params(labelsize=11)

    ax.text(
        0.02,
        0.03,
        "颜色按当日站点辐照分位数拉伸，突出空间差异",
        transform=ax.transAxes,
        fontsize=11,
        color="#444444",
        bbox=dict(
            facecolor="white",
            edgecolor="#cccccc",
            boxstyle="round,pad=0.35",
            alpha=0.9,
        ),
    )

    fig.tight_layout()
    fig.savefig(
        FIG_DIR / "阶段3_融合辐照空间分布图_v2.png",
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)

    notes.append(
        f"阶段3空间图：融合辐照列 {irr_col}，站点经纬度来自 site_master.csv，"
        f"代表日 {date_pick}（空间离散度最大），共 {len(merged)} 个站点。"
    )


# ---------------------------------------------------------------------------
# Stage 4: 单站点 NRMSE 分布直方图
# ---------------------------------------------------------------------------

def generate_stage4_station_error_distribution(notes: list[str]) -> None:
    raw, src = find_prediction_table()
    df = to_eval_frame(raw)
    site_col = pick_site_col(df)
    cap_col = pick_capacity_col(df)
    if cap_col is None:
        raise KeyError("阶段4站点误差分布图需要 capacity_mw 列。")

    rows = []
    for sid, g in df.groupby(site_col):
        cap = pd.to_numeric(g[cap_col], errors="coerce").dropna()
        if cap.empty:
            continue
        denom = cap.iloc[0]
        val = nrmse(g["actual_mw"], g["pred_mw"], denom)
        actual_sum = g["actual_mw"].sum()
        pred_sum = g["pred_mw"].sum()
        ratio = pred_sum / actual_sum if actual_sum > 0 else np.nan
        positive_rate = (g["actual_mw"] > 0).mean()
        if pd.notna(val):
            rows.append({
                "site": sid,
                "nrmse": val,
                "pred_actual": ratio,
                "positive_rate": positive_rate,
                "n": len(g),
            })

    sm = pd.DataFrame(rows).dropna(subset=["nrmse"])
    if sm.empty:
        raise ValueError("无法计算站点 NRMSE。")

    vals = sm["nrmse"].to_numpy()
    p50 = np.percentile(vals, 50)
    p75 = np.percentile(vals, 75)
    mean = np.mean(vals)

    fig, ax = plt.subplots(figsize=(8.8, 8.0), dpi=260)
    bins = np.linspace(0, max(35, np.nanpercentile(vals, 98) + 2), 15)
    ax.hist(
        vals,
        bins=bins,
        color="#f4a6a6",
        edgecolor="#8c2d2d",
        linewidth=1.2,
        alpha=0.88,
    )

    ax.axvline(10, color="#d73027", linestyle="--", linewidth=2.0, label="10% 阈值")
    ax.axvline(15, color="#f46d43", linestyle="--", linewidth=2.0, label="15% 阈值")
    ax.axvline(p50, color="#555555", linestyle="-", linewidth=2.2, label=f"中位数 {p50:.2f}%")
    ax.axvline(mean, color="#222222", linestyle=":", linewidth=2.2, label=f"均值 {mean:.2f}%")

    ax.set_title("阶段 4：单站点测试集 NRMSE 分布", fontsize=18, pad=18)
    ax.set_xlabel("单站点 NRMSE（%）", fontsize=13)
    ax.set_ylabel("站点数量", fontsize=13)
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    ax.legend(frameon=False, fontsize=11, loc="upper right")

    text = (
        f"有效站点：{len(sm)} 个\n"
        f"NRMSE ≤ 10%：{(vals <= 10).sum()} 个\n"
        f"NRMSE ≤ 15%：{(vals <= 15).sum()} 个\n"
        f"75 分位：{p75:.2f}%"
    )
    ax.text(
        0.67,
        0.63,
        text,
        transform=ax.transAxes,
        fontsize=12,
        bbox=dict(
            facecolor="white",
            edgecolor="#cccccc",
            boxstyle="round,pad=0.45",
            alpha=0.92,
        ),
    )

    fig.tight_layout()
    fig.savefig(
        FIG_DIR / "阶段4_站点预测误差分布图_v2.png",
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)

    notes.append(
        f"阶段4分布图从 {src.name} 读取，按测试集 6-19 点逐站计算容量归一化 NRMSE。"
    )


# ---------------------------------------------------------------------------
# 数据说明文件
# ---------------------------------------------------------------------------

def write_report(notes: list[str]) -> None:
    p = FIG_DIR / "阶段2_3_4学术风单图_数据说明_v2.md"
    lines = [
        "# 阶段 2、3、4 学术风单图数据说明",
        "",
        "## 输出文件",
        "",
        "- `阶段2_集中式反演辐照_nRMSE热力图_v2.png`",
        "- `阶段3_融合辐照空间分布图_v2.png`",
        "- `阶段4_站点预测误差分布图_v2.png`",
        "",
        "## 口径说明",
        "",
        "- 不使用 future 数据。",
        "- 若存在 split 列，默认使用 test 集进行阶段 3 和阶段 4 展示。",
        "- 阶段 2 没有真实阶段级指标时，显示“未导出”，不显示 0.00%。",
        "- 阶段 3 使用分位数拉伸颜色，增强站点间融合辐照差异可视性。",
        "- 阶段 4 使用单站点 NRMSE 分布直方图，避免与后续真实/预测曲线重复。",
        "",
        "## 数据来源",
        "",
    ]
    lines.extend([f"- {x}" for x in notes])
    p.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    setup_chinese_font()
    notes: list[str] = []
    generate_stage2_heatmap(notes)
    generate_stage3_spatial(notes)
    generate_stage4_station_error_distribution(notes)
    write_report(notes)
    print(f"[OK] figures saved to {FIG_DIR}")


if __name__ == "__main__":
    main()
