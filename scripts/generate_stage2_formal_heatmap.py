#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成阶段 2 正式 4×4 热力图。

策略：
  1. 若 inverse_metrics.csv + irradiance_blend_metrics.csv 存在 → 用这两份文件构建 4×4 nRMSE 表。
     行 = [Inverse Irradiace Estimation, Power Reconstruction]
     列 = [训练集, 验证集, 测试集, 全量(加权平均)]
  2. 兜底：若上述不满足，用 prediction pkl 中 power + irradiance 变量的 Pearson 相关性 4×4。
     行 = [actual_power, pred_power, clear_sky_ghi, blend_ghi]
     列 = 同上
"""

from __future__ import annotations

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


def setup_font() -> None:
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


def load_nrmse_4x4() -> tuple[pd.DataFrame, str] | None:
    """从 metrics 文件构建 4×4 nRMSE 热力图。"""
    inv_path = OUT_DIR / "metrics" / "inverse_metrics.csv"
    blend_path = OUT_DIR / "metrics" / "irradiance_blend_metrics.csv"

    if not inv_path.exists() or not blend_path.exists():
        return None

    inv = pd.read_csv(inv_path)
    blend = pd.read_csv(blend_path)

    if not {"split", "irr_nrmse", "irr_corr", "power_recon_nrmse"}.issubset(inv.columns):
        return None
    if not {"split", "nrmse_blend"}.issubset(blend.columns):
        return None

    inv_d = inv.set_index("split")
    blend_d = blend.set_index("split")

    # 4 rows: Inverse Irradiance nRMSE, Inverse Irradiance Corr,
    #         Power Reconstruction nRMSE, Blend nRMSE
    # 4 cols: 训练集, 验证集, 测试集, 全量
    row_names = [
        "Inverse Irradiance nRMSE",
        "Inverse Irradiance Corr",
        "Power Reconstruction nRMSE",
        "Blend nRMSE",
    ]
    col_names = ["训练集", "验证集", "测试集", "全量"]
    split_map = {c: s for c, s in zip(col_names, ["train", "valid", "test", "full"])}

    mat = pd.DataFrame(index=row_names, columns=col_names, dtype=float)

    for col, sp in split_map.items():
        if sp == "full":
            w = inv_d.loc["train", "rows"] + inv_d.loc["valid", "rows"] + inv_d.loc["test", "rows"]
            for row, col_key in [
                ("Inverse Irradiance nRMSE", "irr_nrmse"),
                ("Power Reconstruction nRMSE", "power_recon_nrmse"),
            ]:
                v = (inv_d.loc["train", col_key] * inv_d.loc["train", "rows"]
                     + inv_d.loc["valid", col_key] * inv_d.loc["valid", "rows"]
                     + inv_d.loc["test", col_key] * inv_d.loc["test", "rows"]) / w
                mat.loc[row, col] = v
            mat.loc["Inverse Irradiance Corr", col] = (
                inv_d.loc["train", "irr_corr"] * inv_d.loc["train", "rows"]
                + inv_d.loc["valid", "irr_corr"] * inv_d.loc["valid", "rows"]
                + inv_d.loc["test", "irr_corr"] * inv_d.loc["test", "rows"]
            ) / w
            w_blend = blend_d.loc["train", "rows"] + blend_d.loc["valid", "rows"] + blend_d.loc["test", "rows"]
            mat.loc["Blend nRMSE", col] = (
                blend_d.loc["train", "nrmse_blend"] * blend_d.loc["train", "rows"]
                + blend_d.loc["valid", "nrmse_blend"] * blend_d.loc["valid", "rows"]
                + blend_d.loc["test", "nrmse_blend"] * blend_d.loc["test", "rows"]
            ) / w_blend
        else:
            mat.loc["Inverse Irradiance nRMSE", col] = inv_d.loc[sp, "irr_nrmse"]
            mat.loc["Inverse Irradiance Corr", col] = inv_d.loc[sp, "irr_corr"]
            mat.loc["Power Reconstruction nRMSE", col] = inv_d.loc[sp, "power_recon_nrmse"]
            mat.loc["Blend nRMSE", col] = blend_d.loc[sp, "nrmse_blend"]

    mat = mat.astype(float)
    if mat.notna().all().all():
        source = ("inverse_metrics.csv + irradiance_blend_metrics.csv; "
                  "全量 = train/valid/test 加权平均; corr 用加权平均")
        return mat, source

    return None


def build_correlation_4x4() -> tuple[pd.DataFrame, str]:
    """从 prediction pkl 构建 4×4 Pearson 相关性热力图。"""
    candidates = [
        OUT_DIR / "predictions" / "distributed_predictions_final_full.pkl",
        OUT_DIR / "distributed_predictions_final_full.pkl",
        OUT_DIR / "distributed_predictions_final_eval.pkl",
    ]
    df = None
    src_path = None
    for p in candidates:
        if p.exists():
            try:
                df = pd.read_pickle(p)
                src_path = p
                break
            except Exception:
                continue

    if df is None:
        raise FileNotFoundError("未找到 prediction pkl。")

    # filter to test split for stability
    if "split" in df.columns:
        test = df[df["split"].astype(str).str.lower().eq("test")].copy()
        if len(test) >= 100:
            df = test

    # daylight filter
    if "time" in df.columns:
        df["_dt"] = pd.to_datetime(df["time"], errors="coerce")
        df["_hour"] = df["_dt"].dt.hour
        df = df[df["_hour"].between(6, 19)]
        df = df.drop(columns=["_dt", "_hour"])

    if "is_future" in df.columns:
        df = df[~df["is_future"].fillna(False).astype(bool)]

    # column mapping
    col_map = {
        "Actual Power": ["power_mw"],
        "Predicted Power": ["power_pred_final", "power_pred", "pred_baseline"],
        "Clear Sky GHI": ["clear_sky_ghi"],
        "Blend GHI": ["g_blend_pred"],
    }

    series = {}
    for name, candidates in col_map.items():
        found = None
        for c in candidates:
            if c in df.columns:
                s = pd.to_numeric(df[c], errors="coerce")
                if s.notna().sum() >= 100:
                    found = s
                    break
        if found is None:
            raise KeyError(f"缺少字段：{name}（候选：{candidates}）")
        series[name] = found

    corr_df = pd.DataFrame(series).dropna()
    if len(corr_df) < 100:
        raise ValueError(f"有效样本过少：{len(corr_df)} 行。")

    corr = corr_df.corr(method="pearson")

    source = (f"{src_path.name}；样本数 {len(corr_df)}；split=test；"
              f"daylight hours (6-19)；power_pred_final 列")
    return corr, source


def plot_heatmap(mat: pd.DataFrame, title: str, value_type: str,
                 source_note: str) -> Path:
    fig, ax = plt.subplots(figsize=(8.4, 8.4), dpi=280)
    values = mat.values.astype(float)

    if value_type == "nrmse":
        vmax = max(float(np.nanmax(np.abs(values))), 1e-9)
        norm = mcolors.Normalize(vmin=0, vmax=vmax * 1.2)
        cmap = mcolors.LinearSegmentedColormap.from_list(
            "soft_red",
            ["#fff7f3", "#fde0dd", "#fcbba1", "#fb6a4a", "#cb181d"],
        )
        labels = [[f"{v:.4f}" for v in row] for row in values]
        cbar_label = "nRMSE"
        out_name = "阶段2_集中式反演辐照_nRMSE热力图_4x4.png"
    else:
        vmax = max(float(np.nanmax(np.abs(values))), 1.0)
        norm = mcolors.Normalize(vmin=-1, vmax=1)
        cmap = mcolors.LinearSegmentedColormap.from_list(
            "corr_red",
            ["#fff7f3", "#fee0d2", "#fcbba1", "#fc9272", "#de2d26"],
        )
        labels = [[f"{v:.3f}" for v in row] for row in values]
        cbar_label = "Pearson r"
        out_name = "阶段2_集中式反演辐照_关键变量相关性热力图_4x4.png"

    im = ax.imshow(values, cmap=cmap, norm=norm, aspect="equal")

    ax.set_title(title, fontsize=18, pad=18)
    ax.set_xticks(range(mat.shape[1]))
    ax.set_xticklabels(mat.columns, fontsize=13)
    ax.set_yticks(range(mat.shape[0]))
    ax.set_yticklabels(mat.index, fontsize=13)
    ax.tick_params(length=0)

    ax.set_xticks(np.arange(-0.5, mat.shape[1], 1), minor=True)
    ax.set_yticks(np.arange(-0.5, mat.shape[0], 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=3)
    ax.tick_params(which="minor", bottom=False, left=False)

    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            ax.text(j, i, labels[i][j],
                    ha="center", va="center", fontsize=14, color="#222222")

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label(cbar_label, fontsize=13)
    cbar.ax.tick_params(labelsize=11)

    ax.text(0.5, -0.14, f"数据来源：{source_note}",
            transform=ax.transAxes, ha="center", va="top",
            fontsize=9, color="#666666")

    fig.tight_layout()
    out = FIG_DIR / out_name
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def main() -> None:
    setup_font()

    nrmse = load_nrmse_4x4()
    if nrmse is not None:
        mat, src = nrmse
        out = plot_heatmap(mat,
                           "阶段 2：集中式反演辐照模型 nRMSE 热力图",
                           "nrmse", src)
        mode = "nRMSE 4×4"
    else:
        mat, src_note = build_correlation_4x4()
        out = plot_heatmap(mat,
                           "阶段 2：集中式反演辐照关键变量相关性热力图",
                           "corr", src_note)
        mode = "Pearson 相关性 4×4"

    report = FIG_DIR / "阶段2_4x4热力图_数据说明.md"
    report.write_text(
        "\n".join([
            "# 阶段 2 4×4 热力图数据说明",
            "",
            f"- 生成模式：{mode}",
            f"- 输出文件：`{out.name}`",
            "- nRMSE 模式：inverse_metrics.csv + irradiance_blend_metrics.csv",
            "  行：Inverse Irradiance Estimation, Power Reconstruction",
            "  列：训练集、验证集、测试集、全量（加权平均）",
            "- 相关性模式：prediction pkl 中 power + irradiance 变量 Pearson 相关性",
            "- 不使用'未导出'或 0 值填补缺失指标。",
            "- 红色越深表示 nRMSE 越高，或相关性越强。",
            "",
        ]),
        encoding="utf-8",
    )

    print(f"[OK] {mode}: {out}")
    print(f"[OK] report: {report}")


if __name__ == "__main__":
    main()
