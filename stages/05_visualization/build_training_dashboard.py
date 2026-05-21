#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib
from matplotlib import font_manager
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

CH_FONT = None
CH_FONT_NAME = None


def parse_args():
    parser = argparse.ArgumentParser(description="生成训练效果与预测效果看板（两页8图）")
    parser.add_argument("--data-root", type=str, default="data")
    parser.add_argument("--output-root", type=str, default="output/pv_pipeline")
    return parser.parse_args()


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def setup_chinese_font():
    candidate_font_files = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    selected_font_file = None
    for fp in candidate_font_files:
        if os.path.exists(fp):
            selected_font_file = fp
            break

    matplotlib.rcParams["axes.unicode_minus"] = False
    matplotlib.rcParams["figure.facecolor"] = "#f6f8fb"
    matplotlib.rcParams["axes.facecolor"] = "white"
    matplotlib.rcParams["savefig.facecolor"] = "#f6f8fb"
    matplotlib.rcParams["axes.edgecolor"] = "#dbe3ef"
    matplotlib.rcParams["axes.labelcolor"] = "#2f3b52"
    matplotlib.rcParams["xtick.color"] = "#44506a"
    matplotlib.rcParams["ytick.color"] = "#44506a"
    matplotlib.rcParams["text.color"] = "#1f2d3d"
    matplotlib.rcParams["axes.titleweight"] = "bold"
    matplotlib.rcParams["legend.frameon"] = False
    matplotlib.rcParams["grid.color"] = "#e8edf5"
    matplotlib.rcParams["grid.linestyle"] = "--"
    matplotlib.rcParams["grid.linewidth"] = 0.8

    if selected_font_file is None:
        matplotlib.rcParams["font.family"] = "sans-serif"
        matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]
        print("[WARN] 未找到系统中文字体文件，将退回默认字体。")
        return None, None

    font_manager.fontManager.addfont(selected_font_file)
    font_prop = font_manager.FontProperties(fname=selected_font_file)
    font_name = font_prop.get_name()
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = [font_name]
    matplotlib.rcParams["font.serif"] = [font_name]
    print(f"[INFO] 已强制加载中文字体: {font_name}")
    print(f"[INFO] 字体文件路径: {selected_font_file}")
    return font_name, font_manager.FontProperties(fname=selected_font_file)


def apply_tick_font(ax):
    for tick in ax.get_xticklabels():
        tick.set_fontproperties(CH_FONT)
    for tick in ax.get_yticklabels():
        tick.set_fontproperties(CH_FONT)


def zh_title(ax, text: str, pad: int = 10, fontsize: int = 14):
    ax.set_title(text, fontproperties=CH_FONT, pad=pad, fontsize=fontsize, fontweight="bold")


def zh_xlabel(ax, text: str):
    ax.set_xlabel(text, fontproperties=CH_FONT)


def zh_ylabel(ax, text: str):
    ax.set_ylabel(text, fontproperties=CH_FONT)


def zh_legend(ax, loc="best"):
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(handles, labels, prop=CH_FONT, loc=loc)


def add_card_background(ax):
    card = FancyBboxPatch(
        (0, 0), 1, 1,
        transform=ax.transAxes,
        boxstyle="round,pad=0.012,rounding_size=0.02",
        linewidth=1.0,
        edgecolor="#dfe5ef",
        facecolor="white",
        zorder=-10,
        clip_on=False,
    )
    ax.add_patch(card)


def beautify_axis(ax, rotate_x: int = 0, grid_axis: str = "y"):
    ax.grid(True, axis=grid_axis, alpha=0.9)
    for spine in ax.spines.values():
        spine.set_color("#d9dee7")
    ax.tick_params(axis="x", rotation=rotate_x)
    apply_tick_font(ax)
    if ax.xaxis.label:
        ax.xaxis.label.set_fontproperties(CH_FONT)
    if ax.yaxis.label:
        ax.yaxis.label.set_fontproperties(CH_FONT)
    if ax.title:
        ax.title.set_fontproperties(CH_FONT)


def save_figure(fig, out_path: Path):
    fig.tight_layout()
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def read_csv_if_exists(path: Path) -> Optional[pd.DataFrame]:
    if path.exists():
        try:
            return pd.read_csv(path)
        except Exception as e:
            print(f"[WARN] 读取失败 {path}: {e}")
    return None


def read_pkl_if_exists(path: Path):
    if path.exists():
        try:
            return pd.read_pickle(path)
        except Exception as e:
            print(f"[WARN] 读取失败 {path}: {e}")
    return None


def first_not_none(*values):
    for v in values:
        if v is not None:
            return v
    return None


def load_results(output_root: Path) -> Dict[str, Optional[pd.DataFrame]]:
    m = output_root / "metrics"
    t = output_root / "tables"
    data = {
        "inverse": read_csv_if_exists(m / "inverse_metrics.csv"),
        "blend": first_not_none(read_csv_if_exists(m / "irradiance_blend_metrics.csv"), read_csv_if_exists(m / "blend_metrics.csv")),
        "dist": read_csv_if_exists(m / "distributed_metrics.csv"),
        "cand": read_csv_if_exists(m / "distributed_candidate_metrics.csv"),
        "site": read_csv_if_exists(m / "distributed_metrics_by_site.csv"),
        "scene": read_csv_if_exists(m / "distributed_metrics_by_scene.csv"),
        "city": read_csv_if_exists(m / "distributed_metrics_city_total.csv"),
        "pred": first_not_none(read_pkl_if_exists(t / "distributed_predictions.pkl"), read_csv_if_exists(t / "distributed_predictions.csv")),
    }
    for key in ["inverse", "blend", "dist"]:
        df = data[key]
        if df is not None and "split" in df.columns:
            data[key] = df.copy()
            data[key]["split_cn"] = data[key]["split"].map({"train": "训练集", "valid": "验证集", "test": "测试集"}).fillna(data[key]["split"].astype(str))
    return data


def pick_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def get_test_row(df: Optional[pd.DataFrame]) -> Optional[pd.Series]:
    if df is None or df.empty:
        return None
    if "split" in df.columns:
        x = df[df["split"].astype(str) == "test"]
        if not x.empty:
            return x.iloc[0]
    return df.iloc[-1]


def ensure_scene_label(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "scene_label" in out.columns:
        return out
    time_col = pick_col(out, ["ts", "time", "datetime", "timestamp"])
    if time_col is None:
        return out
    out[time_col] = pd.to_datetime(out[time_col], errors="coerce")
    hour = out[time_col].dt.hour
    out["scene_label"] = np.where(hour < 6, "夜间", np.where(hour < 11, "上午", np.where(hour < 15, "中午峰值", np.where(hour < 19, "下午", "夜间"))))
    return out


def get_test_predictions(pred_df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if pred_df is None or pred_df.empty:
        return None
    df = pred_df.copy()
    split_col = pick_col(df, ["split"])
    if split_col and "test" in set(df[split_col].astype(str)):
        df = df[df[split_col].astype(str) == "test"].copy()
    y_true = pick_col(df, ["power_mw", "power_true", "y_true"])
    y_pred = pick_col(df, ["power_pred", "power_prediction", "y_pred"])
    time_col = pick_col(df, ["ts", "time", "datetime", "timestamp"])
    site_col = pick_col(df, ["site_id", "site_name", "site_short_name"])
    if not all([y_true, y_pred]):
        return None
    cols = [y_true, y_pred] + ([time_col] if time_col else []) + ([site_col] if site_col else [])
    if "scene_label" in df.columns:
        cols.append("scene_label")
    df = df[cols].copy()
    if time_col:
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
    df = ensure_scene_label(df)
    df = df.dropna(subset=[y_true, y_pred]).copy()
    df["abs_error"] = np.abs(df[y_true].astype(float) - df[y_pred].astype(float))
    df["residual"] = df[y_pred].astype(float) - df[y_true].astype(float)
    df.attrs["y_true_col"] = y_true
    df.attrs["y_pred_col"] = y_pred
    df.attrs["time_col"] = time_col
    df.attrs["site_col"] = site_col
    return df


def get_city_curve(pred_df: Optional[pd.DataFrame]):
    df = get_test_predictions(pred_df)
    if df is None or df.empty:
        return None
    time_col = df.attrs.get("time_col")
    y_true = df.attrs.get("y_true_col")
    y_pred = df.attrs.get("y_pred_col")
    if not time_col:
        return None
    x = df.dropna(subset=[time_col]).copy()
    x["date"] = x[time_col].dt.date
    daily = x.groupby("date")[[y_true, y_pred]].sum().reset_index()
    daily["mae"] = np.abs(daily[y_true] - daily[y_pred])
    worst_date = daily.sort_values("mae", ascending=False).iloc[0]["date"]
    curve = x[x["date"] == worst_date].groupby(time_col)[[y_true, y_pred]].sum().reset_index().sort_values(time_col)
    return curve, worst_date, y_true, y_pred, time_col


def derive_scene_error_box(pred_df: Optional[pd.DataFrame]):
    df = get_test_predictions(pred_df)
    if df is None or df.empty or "scene_label" not in df.columns:
        return None
    order = ["上午", "中午峰值", "下午", "夜间"]
    groups, labels = [], []
    for s in order:
        vals = df.loc[df["scene_label"].astype(str) == s, "abs_error"].astype(float).dropna()
        if len(vals) > 0:
            if len(vals) > 3000:
                vals = vals.sample(3000, random_state=42)
            groups.append(vals.values)
            labels.append(s)
    if not groups:
        return None
    return labels, groups


def derive_top_site_errors(pred_df: Optional[pd.DataFrame]):
    df = get_test_predictions(pred_df)
    if df is None or df.empty:
        return None
    site_col = df.attrs.get("site_col")
    y_true = df.attrs.get("y_true_col")
    y_pred = df.attrs.get("y_pred_col")
    if not site_col:
        return None
    g = df.groupby(site_col).apply(lambda x: np.sqrt(np.mean((x[y_true].astype(float) - x[y_pred].astype(float)) ** 2)), include_groups=False).reset_index(name="rmse")
    g = g.sort_values("rmse", ascending=False).head(10)
    return g


def draw_heatmap(ax, matrix: np.ndarray, row_labels: List[str], col_labels: List[str], title: str, cmap: str = "YlGnBu"):
    add_card_background(ax)
    im = ax.imshow(matrix, cmap=cmap, aspect="auto")
    ax.set_xticks(np.arange(len(col_labels)))
    ax.set_xticklabels(col_labels)
    ax.set_yticks(np.arange(len(row_labels)))
    ax.set_yticklabels(row_labels)
    zh_title(ax, title)
    apply_tick_font(ax)
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            val = matrix[i, j]
            if np.isfinite(val):
                ax.text(j, i, f"{val:.4f}", ha="center", va="center", fontproperties=CH_FONT, fontsize=10, color="#102a43")
            else:
                ax.text(j, i, "N/A", ha="center", va="center", fontproperties=CH_FONT, fontsize=10, color="#7b8794")
    cbar = plt.colorbar(im, ax=ax, shrink=0.85, fraction=0.046, pad=0.04)
    cbar.ax.set_ylabel("nRMSE", fontproperties=CH_FONT)
    apply_tick_font(cbar.ax)


def plot_training_dashboard(data, out_dir: Path):
    fig = plt.figure(figsize=(16, 11))
    gs = fig.add_gridspec(2, 2)
    fig.suptitle("训练效果看板", fontproperties=CH_FONT, fontsize=20, fontweight="bold", y=0.98)

    # 1 三阶段 nRMSE 热力图
    ax = fig.add_subplot(gs[0, 0])
    stages = ["阶段一\n反演辐照", "阶段二\n辐照融合", "阶段三\n功率估计"]
    splits = ["训练集", "验证集", "测试集"]
    mat = np.full((3, 3), np.nan)
    for i, (df, col) in enumerate([
        (data["inverse"], "irr_nrmse"),
        (data["blend"], "nrmse_blend"),
        (data["dist"], "nrmse"),
    ]):
        if df is not None and not df.empty and col in df.columns:
            for j, split in enumerate(["train", "valid", "test"]):
                g = df[df["split"].astype(str) == split]
                if not g.empty:
                    mat[i, j] = float(g.iloc[0][col])
    draw_heatmap(ax, mat, stages, splits, "① 三阶段 nRMSE 热力图")

    # 2 三阶段泛化差距哑铃图
    ax = fig.add_subplot(gs[0, 1])
    add_card_background(ax)
    labels, train_vals, valid_vals, test_vals = [], [], [], []
    for name, df, col in [
        ("反演辐照", data["inverse"], "irr_nrmse"),
        ("辐照融合", data["blend"], "nrmse_blend"),
        ("功率估计", data["dist"], "nrmse"),
    ]:
        if df is not None and not df.empty and col in df.columns:
            labels.append(name)
            train_vals.append(float(df[df["split"] == "train"].iloc[0][col]))
            valid_vals.append(float(df[df["split"] == "valid"].iloc[0][col]))
            test_vals.append(float(df[df["split"] == "test"].iloc[0][col]))
    y = np.arange(len(labels))
    for i in range(len(labels)):
        ax.plot([train_vals[i], test_vals[i]], [y[i], y[i]], color="#CBD2D9", linewidth=3)
    ax.scatter(train_vals, y, color="#5B8FF9", s=90, label="训练集", zorder=3)
    ax.scatter(valid_vals, y, color="#F6BD16", s=90, label="验证集", zorder=3)
    ax.scatter(test_vals, y, color="#F6903D", s=90, label="测试集", zorder=3)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    zh_title(ax, "② 三阶段泛化差距哑铃图")
    zh_xlabel(ax, "nRMSE（越小越好）")
    beautify_axis(ax, grid_axis="x")
    zh_legend(ax, loc="lower right")

    # 3 候选模型对比气泡图
    ax = fig.add_subplot(gs[1, 0])
    add_card_background(ax)
    cand = data["cand"]
    if cand is not None and not cand.empty:
        c = cand.copy()
        split_col = pick_col(c, ["split"])
        if split_col and "test" in set(c[split_col].astype(str)):
            c = c[c[split_col].astype(str) == "test"].copy()
        xcol = pick_col(c, ["site_nrmse", "nrmse"])
        ycol = pick_col(c, ["city_nrmse", "nrmse"])
        sizecol = pick_col(c, ["city_corr", "corr"])
        labelcol = pick_col(c, ["candidate"])
        if all([xcol, ycol, sizecol, labelcol]):
            x = c[xcol].astype(float).values
            yv = c[ycol].astype(float).values
            sizes = np.clip(c[sizecol].astype(float).values, 0, 1) * 2200 + 180
            ax.scatter(x, yv, s=sizes, color="#5B8FF9", alpha=0.45, edgecolors="white", linewidths=1.2)
            for _, row in c.iterrows():
                ax.text(float(row[xcol]), float(row[ycol]), str(row[labelcol]), ha="center", va="center", fontproperties=CH_FONT, fontsize=10)
            zh_title(ax, "③ 候选模型对比气泡图")
            zh_xlabel(ax, "站点级 nRMSE")
            zh_ylabel(ax, "全市总量 nRMSE")
            beautify_axis(ax, grid_axis="both")
            ax.text(0.98, 0.03, "气泡大小表示全市相关系数", transform=ax.transAxes, ha="right", va="bottom", fontproperties=CH_FONT, fontsize=10, color="#52606d")
        else:
            ax.text(0.5, 0.5, "候选模型指标不足", fontproperties=CH_FONT, ha="center", va="center")
            ax.set_axis_off()
    else:
        ax.text(0.5, 0.5, "未找到候选模型对比结果", fontproperties=CH_FONT, ha="center", va="center")
        ax.set_axis_off()

    # 4 最终指标横向条形图
    ax = fig.add_subplot(gs[1, 1])
    add_card_background(ax)
    dist_row = get_test_row(data["dist"])
    city_row = get_test_row(data["city"])
    labels, values = [], []
    if dist_row is not None:
        for name, col in [("站点RMSE", "rmse"), ("站点nRMSE", "nrmse"), ("站点相关", "corr")]:
            if col in dist_row.index:
                labels.append(name)
                values.append(float(dist_row[col]))
    if city_row is not None:
        for name, col in [("总量RMSE", "rmse"), ("总量nRMSE", "nrmse"), ("总量相关", "corr")]:
            if col in city_row.index:
                labels.append(name)
                values.append(float(city_row[col]))
    if labels:
        y = np.arange(len(labels))
        colors = ["#5B8FF9", "#94B5FF", "#61DDAA", "#F6903D", "#FFB26B", "#36CFC9"][:len(labels)]
        ax.barh(y, values, color=colors)
        ax.set_yticks(y)
        ax.set_yticklabels(labels)
        zh_title(ax, "④ 最终关键指标汇总")
        zh_xlabel(ax, "指标值")
        beautify_axis(ax, grid_axis="x")
        for i, v in enumerate(values):
            ax.text(v, i, f" {v:.4f}", va="center", fontproperties=CH_FONT, fontsize=10)
    else:
        ax.text(0.5, 0.5, "未找到最终关键指标", fontproperties=CH_FONT, ha="center", va="center")
        ax.set_axis_off()

    save_figure(fig, out_dir / "01_训练效果看板.png")


def plot_prediction_dashboard(data, out_dir: Path):
    fig = plt.figure(figsize=(16, 11))
    gs = fig.add_gridspec(2, 2)
    fig.suptitle("预测效果看板", fontproperties=CH_FONT, fontsize=20, fontweight="bold", y=0.98)

    pred = get_test_predictions(data["pred"])

    # 5 真实值 vs 预测值密度图
    ax = fig.add_subplot(gs[0, 0])
    add_card_background(ax)
    if pred is not None and not pred.empty:
        y_true = pred.attrs["y_true_col"]
        y_pred = pred.attrs["y_pred_col"]
        tmp = pred[[y_true, y_pred]].dropna().copy()
        hb = ax.hexbin(tmp[y_true].astype(float), tmp[y_pred].astype(float), gridsize=35, cmap="Blues", mincnt=1)
        low = float(min(tmp[y_true].min(), tmp[y_pred].min()))
        high = float(max(tmp[y_true].max(), tmp[y_pred].max()))
        ax.plot([low, high], [low, high], "--", color="#F6903D", linewidth=2, label="理想线")
        zh_title(ax, "⑤ 真实值 vs 预测值密度图")
        zh_xlabel(ax, "真实功率")
        zh_ylabel(ax, "预测功率")
        beautify_axis(ax, grid_axis="both")
        zh_legend(ax, loc="upper left")
        cbar = plt.colorbar(hb, ax=ax, shrink=0.85, fraction=0.046, pad=0.04)
        cbar.ax.set_ylabel("样本密度", fontproperties=CH_FONT)
        apply_tick_font(cbar.ax)
    else:
        ax.text(0.5, 0.5, "未找到逐站预测结果", fontproperties=CH_FONT, ha="center", va="center")
        ax.set_axis_off()

    # 6 最难测试日全市总出力面积图
    ax = fig.add_subplot(gs[0, 1])
    add_card_background(ax)
    city_curve = get_city_curve(data["pred"])
    if city_curve is not None:
        curve, worst_date, y_true, y_pred, time_col = city_curve
        x = curve[time_col]
        yt = curve[y_true].astype(float)
        yp = curve[y_pred].astype(float)
        ax.fill_between(x, yt, alpha=0.35, color="#5B8FF9", label="真实总出力")
        ax.fill_between(x, yp, alpha=0.35, color="#F6903D", label="预测总出力")
        ax.plot(x, yt, linewidth=2.0, color="#3B73E0")
        ax.plot(x, yp, linewidth=2.0, color="#D97904")
        zh_title(ax, f"⑥ 最难测试日全市总出力面积图（{worst_date}）", fontsize=13)
        zh_xlabel(ax, "时间")
        zh_ylabel(ax, "总出力")
        beautify_axis(ax)
        zh_legend(ax, loc="upper left")
    else:
        ax.text(0.5, 0.5, "无法构造全市总出力曲线", fontproperties=CH_FONT, ha="center", va="center")
        ax.set_axis_off()

    # 7 不同场景绝对误差箱线图
    ax = fig.add_subplot(gs[1, 0])
    add_card_background(ax)
    box_data = derive_scene_error_box(data["pred"])
    if box_data is not None:
        labels, groups = box_data
        bp = ax.boxplot(groups, patch_artist=True, labels=labels, showfliers=False)
        box_colors = ["#5B8FF9", "#61DDAA", "#F6BD16", "#7262FD"]
        for patch, color in zip(bp["boxes"], box_colors[:len(bp["boxes"])]):
            patch.set_facecolor(color)
            patch.set_alpha(0.6)
        for item in bp["medians"]:
            item.set_color("#1f2d3d")
            item.set_linewidth(2)
        zh_title(ax, "⑦ 不同场景绝对误差箱线图")
        zh_ylabel(ax, "|预测误差|")
        beautify_axis(ax)
    else:
        ax.text(0.5, 0.5, "无法构造场景箱线图", fontproperties=CH_FONT, ha="center", va="center")
        ax.set_axis_off()

    # 8 误差最大的站点 Top10 lollipop 图
    ax = fig.add_subplot(gs[1, 1])
    add_card_background(ax)
    top_sites = derive_top_site_errors(data["pred"])
    if top_sites is not None and not top_sites.empty:
        names = top_sites.iloc[::-1, 0].astype(str).tolist()
        vals = top_sites.iloc[::-1]["rmse"].astype(float).tolist()
        y = np.arange(len(names))
        ax.hlines(y, xmin=0, xmax=vals, color="#B8C4D6", linewidth=2)
        ax.plot(vals, y, "o", color="#5B8FF9", markersize=8)
        ax.set_yticks(y)
        ax.set_yticklabels(names)
        zh_title(ax, "⑧ 误差最大的站点 Top10")
        zh_xlabel(ax, "RMSE")
        beautify_axis(ax, grid_axis="x")
        for i, v in enumerate(vals):
            ax.text(v, i, f" {v:.3f}", va="center", fontproperties=CH_FONT, fontsize=10)
    else:
        ax.text(0.5, 0.5, "无法构造站点误差图", fontproperties=CH_FONT, ha="center", va="center")
        ax.set_axis_off()

    save_figure(fig, out_dir / "02_预测效果看板.png")


def write_index_html(out_dir: Path, font_name: Optional[str]):
    html = f"""<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
<meta charset=\"UTF-8\">
<title>训练与预测效果看板</title>
<style>
body {{font-family: \"Noto Sans CJK SC\", \"WenQuanYi Zen Hei\", \"SimHei\", \"Microsoft YaHei\", sans-serif; background:#f6f8fb; margin:0; padding:24px; color:#1f2d3d;}}
.container {{max-width:1400px; margin:0 auto;}}
.card {{background:white; border:1px solid #dfe5ef; border-radius:14px; padding:18px; margin-bottom:24px; box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);}}
img {{width:100%; display:block; border-radius:10px;}}
.caption {{margin-top:10px; color:#475569; font-size:15px;}}
</style>
</head>
<body>
<div class=\"container\">
<h1>光伏训练与预测效果看板（两页8图版）</h1>
<p>当前字体：{font_name if font_name else '未检测到中文字体，已退回默认字体'}</p>
<div class=\"card\"><img src=\"01_训练效果看板.png\"><div class=\"caption\">图1：热力图、哑铃图、气泡图和横向指标图，总共4幅图。</div></div>
<div class=\"card\"><img src=\"02_预测效果看板.png\"><div class=\"caption\">图2：六边形密度图、面积图、箱线图和站点Top10图，总共4幅图。</div></div>
</div>
</body>
</html>"""
    with open(out_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(html)


def main():
    global CH_FONT, CH_FONT_NAME
    args = parse_args()
    output_root = Path(args.output_root)
    out_dir = output_root / "figures_dashboard"
    ensure_dir(out_dir)
    CH_FONT_NAME, CH_FONT = setup_chinese_font()
    data = load_results(output_root)
    plot_training_dashboard(data, out_dir)
    plot_prediction_dashboard(data, out_dir)
    write_index_html(out_dir, CH_FONT_NAME)
    print(f"[OK] 看板已输出到: {out_dir}")


if __name__ == "__main__":
    main()
