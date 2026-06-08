#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round97: 生成阶段 2、3、4 的 PPT 训练效果图。

图 1：阶段 2 4×4 红色系热力图
  行：物理基线功率重构、反演辐照、IDW 空间扩展、融合辐照
  列：训练集、验证集、测试集、整体
  值：nRMSE（%），全部从 metrics 文件读取或推导，不允许出现"未导出"

图 2：阶段 3 融合权重 alpha 时段热力图
  行：月份
  列：小时
  值：平均 alpha_pred

图 3：阶段 4 分布式功率模型特征重要性
  优先读取模型内置 feature importance
  若模型结构不可解析，则回退为训练表数值特征与容量归一化目标的绝对相关性
"""

from __future__ import annotations

import json
import math
import pickle
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib import font_manager


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, str(SRC))

OUT_DIR = ROOT / "output" / "pv_pipeline"
METRICS_DIR = OUT_DIR / "metrics"
TABLE_DIR = OUT_DIR / "tables"
MODEL_DIR = OUT_DIR / "models"
FIG_DIR = OUT_DIR / "ppt_figures" / "model_effect"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def setup_font() -> None:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
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
    plt.rcParams["savefig.facecolor"] = "white"
    plt.rcParams["font.size"] = 12


def pct_from_fraction_or_pct(x: float) -> float:
    """项目内 nRMSE 多数为小数形式；若明显已经是百分数则保持。"""
    x = float(x)
    if not np.isfinite(x):
        return np.nan
    return x * 100.0 if abs(x) <= 1.5 else x


def weighted_mean(values: list[float], weights: list[float]) -> float:
    values_arr = np.asarray(values, dtype=float)
    weights_arr = np.asarray(weights, dtype=float)
    mask = np.isfinite(values_arr) & np.isfinite(weights_arr) & (weights_arr > 0)
    if not mask.any():
        return np.nan
    return float(np.average(values_arr[mask], weights=weights_arr[mask]))


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def read_pickle_compat(path: Path) -> Any:
    """兼容部分 pandas StringDtype pickle 读取问题。"""
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        return pd.read_pickle(path)
    except TypeError:
        import pandas.core.arrays.string_ as string_mod
        cls = string_mod.StringDtype
        old_init = cls.__init__
        def patched_init(self, storage=None, na_value=pd.NA):
            try:
                old_init(self, storage=storage, na_value=na_value)
            except TypeError:
                old_init(self, storage=storage)
        cls.__init__ = patched_init
        return pd.read_pickle(path)


def plot_stage2_heatmap() -> tuple[Path, pd.DataFrame]:
    inv = load_csv(METRICS_DIR / "inverse_metrics.csv")
    blend = load_csv(METRICS_DIR / "irradiance_blend_metrics.csv")

    required_inv = {"split", "irr_nrmse", "power_recon_nrmse", "rows"}
    required_blend = {"split", "rmse_idw", "rmse_era5", "rmse_blend", "nrmse_blend", "rows"}
    if not required_inv.issubset(inv.columns):
        raise ValueError(f"inverse_metrics.csv 缺少字段：{sorted(required_inv - set(inv.columns))}")
    if not required_blend.issubset(blend.columns):
        raise ValueError(f"irradiance_blend_metrics.csv 缺少字段：{sorted(required_blend - set(blend.columns))}")

    inv = inv.set_index("split")
    blend = blend.set_index("split")
    splits = ["train", "valid", "test"]
    col_names = ["训练集", "验证集", "测试集", "整体"]
    rows = ["物理基线功率重构", "反演辐照", "IDW空间扩展", "融合辐照"]
    mat = pd.DataFrame(index=rows, columns=col_names, dtype=float)

    for sp, cn in zip(splits, col_names[:3]):
        if sp not in inv.index or sp not in blend.index:
            raise ValueError(f"metrics 文件缺少 split={sp}")

        mat.loc["物理基线功率重构", cn] = pct_from_fraction_or_pct(inv.loc[sp, "power_recon_nrmse"])
        mat.loc["反演辐照", cn] = pct_from_fraction_or_pct(inv.loc[sp, "irr_nrmse"])

        # 由 blend nRMSE 反推同一归一化分母，再计算 IDW nRMSE。
        denom = float(blend.loc[sp, "rmse_blend"]) / max(float(blend.loc[sp, "nrmse_blend"]), 1e-12)
        mat.loc["IDW空间扩展", cn] = float(blend.loc[sp, "rmse_idw"]) / denom * 100.0
        mat.loc["融合辐照", cn] = pct_from_fraction_or_pct(blend.loc[sp, "nrmse_blend"])

    inv_rows = [float(inv.loc[sp, "rows"]) for sp in splits]
    blend_rows = [float(blend.loc[sp, "rows"]) for sp in splits]
    for row, metric in [
        ("物理基线功率重构", "power_recon_nrmse"),
        ("反演辐照", "irr_nrmse"),
    ]:
        mat.loc[row, "整体"] = weighted_mean(
            [pct_from_fraction_or_pct(inv.loc[sp, metric]) for sp in splits],
            inv_rows,
        )

    idw_vals, blend_vals = [], []
    for sp in splits:
        denom = float(blend.loc[sp, "rmse_blend"]) / max(float(blend.loc[sp, "nrmse_blend"]), 1e-12)
        idw_vals.append(float(blend.loc[sp, "rmse_idw"]) / denom * 100.0)
        blend_vals.append(pct_from_fraction_or_pct(blend.loc[sp, "nrmse_blend"]))
    mat.loc["IDW空间扩展", "整体"] = weighted_mean(idw_vals, blend_rows)
    mat.loc["融合辐照", "整体"] = weighted_mean(blend_vals, blend_rows)

    if not np.isfinite(mat.values.astype(float)).all():
        raise ValueError("阶段2 4×4 热力图存在空值，请检查 metrics 文件。")

    csv_path = FIG_DIR / "阶段2_训练效果_4x4_nrmse数据.csv"
    mat.round(4).to_csv(csv_path, encoding="utf-8-sig")

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "academic_soft_red",
        ["#fff7f3", "#fde0dd", "#fcbba1", "#fb6a4a", "#de2d26"],
    )
    values = mat.values.astype(float)
    vmax = max(float(np.nanmax(values)), 1.0)

    fig, ax = plt.subplots(figsize=(8.0, 8.0), dpi=300)
    im = ax.imshow(values, cmap=cmap, vmin=0, vmax=vmax * 1.12, aspect="equal")

    ax.set_xticks(np.arange(len(col_names)), col_names)
    ax.set_yticks(np.arange(len(rows)), rows)
    ax.tick_params(axis="x", labelsize=13)
    ax.tick_params(axis="y", labelsize=13)
    ax.set_title("阶段2  集中式反演辐照模型训练效果", fontsize=18, pad=18)

    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            v = values[i, j]
            text_color = "white" if v > vmax * 0.55 else "#263238"
            ax.text(j, i, f"{v:.2f}%", ha="center", va="center", fontsize=12, color=text_color)

    for edge in ["top", "right", "bottom", "left"]:
        ax.spines[edge].set_linewidth(1.1)
        ax.spines[edge].set_color("#333333")

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("nRMSE（%）", fontsize=12)
    cbar.ax.tick_params(labelsize=11)
    ax.set_xlabel("数据集划分", fontsize=13, labelpad=10)
    ax.set_ylabel("阶段内评价对象", fontsize=13, labelpad=10)

    fig.tight_layout()
    out = FIG_DIR / "阶段2_集中式反演辐照模型训练效果_4x4红色热力图.png"
    fig.savefig(out, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return out, mat


def plot_stage3_alpha_heatmap() -> tuple[Path, pd.DataFrame]:
    df = read_pickle_compat(TABLE_DIR / "blend_validation_predictions.pkl")
    required = {"time", "hour", "month", "alpha_pred"}
    if not required.issubset(df.columns):
        raise ValueError(f"blend_validation_predictions.pkl 缺少字段：{sorted(required - set(df.columns))}")

    d = df.copy()
    d["hour"] = pd.to_numeric(d["hour"], errors="coerce")
    d["month"] = pd.to_numeric(d["month"], errors="coerce")
    d["alpha_pred"] = pd.to_numeric(d["alpha_pred"], errors="coerce").clip(0, 1)
    d = d[d["hour"].between(6, 19)]
    d = d[d["month"].between(1, 12)]
    if d.empty:
        raise ValueError("阶段3 alpha 数据为空。")

    pivot = d.pivot_table(index="month", columns="hour", values="alpha_pred", aggfunc="mean")
    pivot = pivot.reindex(index=range(1, 13), columns=range(6, 20))
    if pivot.isna().any().any():
        pivot = pivot.interpolate(axis=1).interpolate(axis=0).fillna(pivot.stack().mean())

    csv_path = FIG_DIR / "阶段3_融合权重alpha_月小时热力图数据.csv"
    pivot.round(4).to_csv(csv_path, encoding="utf-8-sig")

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "alpha_heat",
        ["#fff7ec", "#fee8c8", "#fdbb84", "#e34a33", "#b30000"],
    )

    fig, ax = plt.subplots(figsize=(9.2, 6.6), dpi=300)
    im = ax.imshow(pivot.values, cmap=cmap, vmin=0, vmax=1, aspect="auto")

    ax.set_xticks(np.arange(len(pivot.columns)), [f"{h}时" for h in pivot.columns])
    ax.set_yticks(np.arange(len(pivot.index)), [f"{m}月" for m in pivot.index])
    ax.tick_params(axis="x", labelsize=11)
    ax.tick_params(axis="y", labelsize=11)
    ax.set_title("阶段3  辐照融合权重 alpha 的月-小时分布", fontsize=18, pad=14)
    ax.set_xlabel("小时", fontsize=13, labelpad=8)
    ax.set_ylabel("月份", fontsize=13, labelpad=8)

    # 只标注部分关键时段，避免信息过密。
    for i, month in enumerate(pivot.index):
        for j, hour in enumerate(pivot.columns):
            if hour in [8, 10, 12, 14, 16, 18] and month in [1, 3, 6, 9, 12]:
                v = pivot.loc[month, hour]
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8.5,
                        color="white" if v > 0.62 else "#263238")

    for edge in ["top", "right", "bottom", "left"]:
        ax.spines[edge].set_linewidth(1.0)
        ax.spines[edge].set_color("#333333")

    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.025)
    cbar.set_label("平均 alpha", fontsize=12)
    cbar.ax.tick_params(labelsize=10)

    fig.tight_layout()
    out = FIG_DIR / "阶段3_辐照融合权重alpha月小时热力图.png"
    fig.savefig(out, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return out, pivot


def load_model_pickle(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(path)
    with open(path, "rb") as f:
        return pickle.load(f)


def get_feature_names(model: Any) -> list[str] | None:
    for attr in ["feature_names_", "feature_name_", "feature_names_in_"]:
        if hasattr(model, attr):
            names = getattr(model, attr)
            if callable(names):
                names = names()
            if names is not None:
                return [str(x) for x in list(names)]
    if hasattr(model, "booster_") and hasattr(model.booster_, "feature_name"):
        return [str(x) for x in model.booster_.feature_name()]
    return None


def collect_model_importances(obj: Any, prefix: str = "") -> list[tuple[str, pd.Series]]:
    items: list[tuple[str, pd.Series]] = []

    if isinstance(obj, dict):
        for k, v in obj.items():
            items.extend(collect_model_importances(v, prefix=f"{prefix}{k}."))
        return items

    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            items.extend(collect_model_importances(v, prefix=f"{prefix}{i}."))
        return items

    model = obj
    if hasattr(model, "named_steps"):
        steps = list(model.named_steps.items())
        if steps:
            model = steps[-1][1]

    names = get_feature_names(model)
    importance = None
    if hasattr(model, "get_feature_importance"):
        try:
            importance = np.asarray(model.get_feature_importance(), dtype=float)
        except Exception:
            importance = None
    if importance is None and hasattr(model, "feature_importances_"):
        try:
            importance = np.asarray(model.feature_importances_, dtype=float)
        except Exception:
            importance = None

    if importance is not None and len(importance) > 0:
        if names is None or len(names) != len(importance):
            names = [f"feature_{i}" for i in range(len(importance))]
        s = pd.Series(importance, index=names, dtype=float)
        s = s.replace([np.inf, -np.inf], np.nan).dropna()
        if not s.empty and s.sum() > 0:
            s = s / s.sum() * 100.0
            items.append((prefix.rstrip(".") or type(model).__name__, s))
    return items


def fallback_feature_correlation() -> tuple[pd.Series, str]:
    df = read_pickle_compat(TABLE_DIR / "distributed_train_table_v159.pkl")
    d = df.copy()
    for c in ["power_mw", "capacity_mw"]:
        if c not in d.columns:
            raise ValueError(f"distributed_train_table_v159.pkl 缺少 {c}，无法回退计算相关性。")

    target = pd.to_numeric(d["power_mw"], errors="coerce") / pd.to_numeric(d["capacity_mw"], errors="coerce").replace(0, np.nan)
    numeric_cols = []
    banned = {
        "power_mw", "capacity_mw", "target", "split", "is_future",
        "time", "datetime", "site_id", "station_id", "station_name",
    }
    for c in d.columns:
        if c in banned:
            continue
        s = pd.to_numeric(d[c], errors="coerce")
        if s.notna().sum() > 1000 and s.std(skipna=True) > 0:
            numeric_cols.append(c)

    scores = {}
    for c in numeric_cols:
        s = pd.to_numeric(d[c], errors="coerce")
        tmp = pd.DataFrame({"x": s, "y": target}).dropna()
        if len(tmp) < 1000:
            continue
        corr = tmp["x"].corr(tmp["y"])
        if np.isfinite(corr):
            scores[c] = abs(float(corr)) * 100.0

    if not scores:
        raise ValueError("无法从训练表计算特征相关性。")
    return pd.Series(scores).sort_values(ascending=False), "fallback_abs_corr"


def pretty_feature_name(name: str) -> str:
    mapping = {
        "g_blend_pred": "融合辐照",
        "blend_ghi": "融合辐照",
        "clear_sky_ghi": "晴空辐照",
        "era5_pred": "ERA5辐照",
        "idw_pred": "IDW辐照",
        "hour": "小时",
        "month": "月份",
        "capacity_mw": "装机容量",
        "lag_power_1": "滞后功率1小时",
        "lag_power_24": "滞后功率24小时",
        "temp": "温度",
        "temperature": "温度",
        "wind_speed": "风速",
        "humidity": "湿度",
        "cloud": "云量",
    }
    return mapping.get(name, name)


def plot_stage4_feature_importance() -> tuple[Path, pd.DataFrame, str]:
    source = "model_feature_importance"
    try:
        obj = load_model_pickle(MODEL_DIR / "distributed_model_v159.pkl")
        parts = collect_model_importances(obj)
        if not parts:
            raise ValueError("模型对象未解析到 feature importance。")
        merged: dict[str, list[float]] = {}
        for _, s in parts:
            for k, v in s.items():
                merged.setdefault(k, []).append(float(v))
        scores = pd.Series({k: float(np.mean(v)) for k, v in merged.items()}).sort_values(ascending=False)
    except Exception as e:
        scores, source = fallback_feature_correlation()
        print(f"[WARN] 模型特征重要性不可解析，改用训练表目标相关性：{type(e).__name__}: {e}")

    scores = scores.replace([np.inf, -np.inf], np.nan).dropna()
    top = scores.head(15).sort_values(ascending=True)
    top.index = [pretty_feature_name(x) for x in top.index]
    df_out = top.sort_values(ascending=False).reset_index()
    df_out.columns = ["feature", "importance_score"]
    df_out["source"] = source
    csv_path = FIG_DIR / "阶段4_分布式功率模型特征重要性数据.csv"
    df_out.to_csv(csv_path, index=False, encoding="utf-8-sig")

    fig, ax = plt.subplots(figsize=(9.4, 6.5), dpi=300)
    color = "#0f766e" if source == "model_feature_importance" else "#b45309"
    ax.barh(np.arange(len(top)), top.values, color=color, alpha=0.86, edgecolor="#264653", linewidth=0.5)
    ax.set_yticks(np.arange(len(top)), top.index)
    ax.tick_params(axis="y", labelsize=11)
    ax.tick_params(axis="x", labelsize=10)
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.set_axisbelow(True)
    ax.set_xlabel("重要性得分（归一化）" if source == "model_feature_importance" else "与归一化功率目标的绝对相关性（×100）", fontsize=12)
    ax.set_title("阶段4  分布式功率模型关键特征贡献", fontsize=18, pad=14)

    xmax = max(float(top.max()), 1.0)
    for i, v in enumerate(top.values):
        ax.text(v + xmax * 0.012, i, f"{v:.2f}", va="center", ha="left", fontsize=10, color="#263238")

    for edge in ["top", "right"]:
        ax.spines[edge].set_visible(False)
    ax.spines["left"].set_color("#333333")
    ax.spines["bottom"].set_color("#333333")

    fig.tight_layout()
    out = FIG_DIR / "阶段4_分布式功率模型特征重要性图.png"
    fig.savefig(out, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return out, df_out, source


def main() -> None:
    setup_font()
    generated = {}

    p2, mat2 = plot_stage2_heatmap()
    generated["stage2"] = str(p2.relative_to(ROOT))
    print(f"[OK] stage2: {p2}")

    p3, alpha = plot_stage3_alpha_heatmap()
    generated["stage3"] = str(p3.relative_to(ROOT))
    print(f"[OK] stage3: {p3}")

    p4, fi, source = plot_stage4_feature_importance()
    generated["stage4"] = str(p4.relative_to(ROOT))
    print(f"[OK] stage4: {p4}")

    meta = {
        "round": "Round97",
        "purpose": "PPT model training effect figures",
        "figures": generated,
        "stage2_values_pct": mat2.round(4).to_dict(),
        "stage3_alpha_shape": list(alpha.shape),
        "stage4_importance_source": source,
        "stage4_top_features": fi.head(10).to_dict(orient="records"),
    }
    meta_path = FIG_DIR / "model_effect_figures_metadata.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] metadata: {meta_path}")


if __name__ == "__main__":
    main()
