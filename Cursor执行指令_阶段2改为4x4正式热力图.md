# Cursor 执行指令：阶段 2 改为 4×4 正式热力图

## 修改目标

当前阶段 2 图中出现“未导出”，不适合正式 PPT。  
本轮要求：

- 阶段 2 热力图必须是 **4×4**。
- 每个单元格必须有真实计算值。
- 不允许出现“未导出”“缺失”“0.00% 代替缺失”等内容。
- 优先使用 nRMSE；如果阶段级 nRMSE 无法形成完整 4×4，则自动切换为更稳定、可完整计算的指标。
- 图形使用红色系，整体和热力图都接近正方形。

---

## 一、图形口径

### 优先方案：阶段级 nRMSE 4×4

如果项目中已经有完整阶段级指标文件，例如：

```text
output/pv_pipeline/metrics/stage2_metrics_4x4.csv
```

且能形成 4×4，则绘制 nRMSE 热力图。

推荐 4 行：

```text
物理基线
残差修正
反演辐照
功率重构
```

推荐 4 列：

```text
训练集
验证集
测试集
全量
```

### 兜底方案：阶段 2 关键变量相关性 4×4

如果阶段级 nRMSE 不完整，则改用 **Pearson 相关系数热力图**。

4 个变量为：

```text
集中式功率
ERA5 辐照
物理基线辐照
反演辐照
```

这张图仍然能支撑阶段 2 的文字部分：

- 集中式功率与辐照变量的相关性体现反演基础。
- 物理基线辐照与反演辐照的相关性体现物理约束是否被保留。
- ERA5 辐照与反演辐照的相关性体现气象背景对残差修正的作用。

相关性热力图比“未导出 nRMSE”更正式，也不会伪造不存在的阶段误差。

---

## 二、新建脚本

新建文件：

```text
scripts/generate_stage2_formal_heatmap.py
```

填入以下完整代码：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成阶段 2 正式 4×4 热力图。

优先：
1. 读取完整 stage2_metrics_4x4.csv 绘制 nRMSE 4×4。

兜底：
2. 若 nRMSE 不完整，绘制阶段 2 关键变量 Pearson 相关性 4×4。

不允许出现“未导出”或缺失格。
"""

from __future__ import annotations

from pathlib import Path
import math

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


def find_prediction_table() -> tuple[pd.DataFrame, Path]:
    candidates = [
        OUT_DIR / "distributed_predictions_final_full.pkl",
        OUT_DIR / "distributed_predictions_final_eval.pkl",
        OUT_DIR / "distributed_predictions_final.pkl",
        OUT_DIR / "predictions" / "distributed_predictions_final_full.pkl",
        OUT_DIR / "predictions" / "distributed_predictions_final_eval.pkl",
    ]
    for p in candidates:
        if p.exists():
            return pd.read_pickle(p), p

    for p in sorted(OUT_DIR.rglob("*.pkl"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            df = pd.read_pickle(p)
        except Exception:
            continue
        cols = set(df.columns)
        if "power_mw" in cols:
            return df, p

    raise FileNotFoundError("未找到可用于阶段 2 热力图的数据表。")


def pick_time_col(df: pd.DataFrame) -> str | None:
    for c in ["datetime", "time", "timestamp", "date_time"]:
        if c in df.columns:
            return c
    return None


def load_complete_nrmse_4x4() -> tuple[pd.DataFrame, str] | None:
    """
    读取正式的 4×4 nRMSE 指标文件。
    文件格式要求：
        index 或第一列为阶段名；
        列为 训练集、验证集、测试集、全量；
        所有值均可转为数值。
    """
    candidates = [
        OUT_DIR / "metrics" / "stage2_metrics_4x4.csv",
        OUT_DIR / "metrics" / "stage2_nrmse_4x4.csv",
        OUT_DIR / "ppt_figures" / "stage2_metrics_4x4.csv",
    ]

    for p in candidates:
        if not p.exists():
            continue

        raw = pd.read_csv(p)
        if raw.shape[0] < 4 or raw.shape[1] < 5:
            continue

        stage_col = raw.columns[0]
        mat = raw.set_index(stage_col)
        wanted_cols = ["训练集", "验证集", "测试集", "全量"]
        if not set(wanted_cols).issubset(mat.columns):
            continue
        mat = mat.loc[:, wanted_cols].head(4)
        mat = mat.apply(pd.to_numeric, errors="coerce")
        if mat.shape == (4, 4) and mat.notna().all().all():
            return mat, str(p)

    return None


def find_col(df: pd.DataFrame, candidates: list[str], fuzzy: list[str] | None = None) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    if fuzzy:
        lower_map = {c.lower(): c for c in df.columns}
        for key in fuzzy:
            for lc, orig in lower_map.items():
                if key.lower() in lc:
                    return orig
    return None


def build_correlation_4x4() -> tuple[pd.DataFrame, str]:
    df, src = find_prediction_table()
    df = df.copy()

    time_col = pick_time_col(df)
    if time_col:
        df["datetime"] = pd.to_datetime(df[time_col], errors="coerce")
        df["hour"] = df["datetime"].dt.hour
        df = df[df["hour"].between(6, 19)]

    if "is_future" in df.columns:
        df = df[~df["is_future"].fillna(False).astype(bool)]

    # 尽量使用测试集；如果测试集过少，则使用非 future 全量。
    if "split" in df.columns:
        test = df[df["split"].astype(str).str.lower().eq("test")].copy()
        if len(test) >= 100:
            df = test

    power_col = find_col(
        df,
        ["central_power_mw", "centralized_power_mw", "power_c_mw", "p_c", "P_c", "power_mw"],
        fuzzy=["central", "power"],
    )
    era5_col = find_col(
        df,
        ["era5_ghi", "ghi_era5", "G_era5", "era5_global_radiation", "ssrd", "ghi"],
        fuzzy=["era5", "ghi", "ssrd"],
    )
    base_col = find_col(
        df,
        ["g_base", "G_base", "ghi_base", "physical_ghi_base", "irradiance_base"],
        fuzzy=["base"],
    )
    inv_col = find_col(
        df,
        ["g_pred", "G_pred", "ghi_inverse", "inverse_ghi", "ghi_inv", "g_inv", "G_inv", "irradiance_pred"],
        fuzzy=["inverse", "inv", "pred_ghi", "irradiance"],
    )

    missing = []
    if power_col is None:
        missing.append("集中式功率")
    if era5_col is None:
        missing.append("ERA5 辐照")
    if base_col is None:
        missing.append("物理基线辐照")
    if inv_col is None:
        missing.append("反演辐照")

    if missing:
        raise KeyError(
            "无法生成 4×4 相关性热力图，缺少字段："
            + "、".join(missing)
            + "\\n请在阶段 2 中间结果导出表中保留这些列，或补充列名候选。"
        )

    use = pd.DataFrame({
        "集中式功率": pd.to_numeric(df[power_col], errors="coerce"),
        "ERA5辐照": pd.to_numeric(df[era5_col], errors="coerce"),
        "物理基线辐照": pd.to_numeric(df[base_col], errors="coerce"),
        "反演辐照": pd.to_numeric(df[inv_col], errors="coerce"),
    }).replace([np.inf, -np.inf], np.nan).dropna()

    if len(use) < 100:
        raise ValueError(f"用于相关性热力图的有效样本过少：{len(use)} 行。")

    corr = use.corr(method="pearson")
    return corr, f"{src.name}；字段：{power_col}, {era5_col}, {base_col}, {inv_col}；样本数 {len(use)}"


def plot_heatmap(mat: pd.DataFrame, title: str, value_type: str, source_note: str) -> Path:
    """
    value_type:
        nrmse: 数值越大颜色越深，标注百分比
        corr: 相关性，使用浅红到深红，标注 r
    """
    fig, ax = plt.subplots(figsize=(8.4, 8.4), dpi=280)

    values = mat.values.astype(float)

    if value_type == "nrmse":
        vmax = max(float(np.nanmax(values)), 1.0)
        norm = mcolors.Normalize(vmin=0, vmax=vmax * 1.2)
        cmap = mcolors.LinearSegmentedColormap.from_list(
            "soft_red",
            ["#fff7f3", "#fde0dd", "#fcbba1", "#fb6a4a", "#cb181d"],
        )
        labels = [[f"{v:.2f}%" for v in row] for row in values]
        cbar_label = "nRMSE（%）"
        out_name = "阶段2_集中式反演辐照_nRMSE热力图_4x4.png"
    else:
        # 相关性全部映射到 0-1，避免负值破坏红色系。
        norm = mcolors.Normalize(vmin=-1, vmax=1)
        cmap = mcolors.LinearSegmentedColormap.from_list(
            "corr_red",
            ["#fff7f3", "#fee0d2", "#fcbba1", "#fc9272", "#de2d26"],
        )
        labels = [[f"{v:.2f}" for v in row] for row in values]
        cbar_label = "Pearson r"
        out_name = "阶段2_集中式反演辐照_关键变量相关性热力图_4x4.png"

    im = ax.imshow(values, cmap=cmap, norm=norm, aspect="equal")

    ax.set_title(title, fontsize=18, pad=18)
    ax.set_xticks(range(mat.shape[1]), mat.columns, fontsize=13)
    ax.set_yticks(range(mat.shape[0]), mat.index, fontsize=13)
    ax.tick_params(length=0)

    ax.set_xticks(np.arange(-0.5, mat.shape[1], 1), minor=True)
    ax.set_yticks(np.arange(-0.5, mat.shape[0], 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=3)
    ax.tick_params(which="minor", bottom=False, left=False)

    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            ax.text(
                j,
                i,
                labels[i][j],
                ha="center",
                va="center",
                fontsize=14,
                color="#222222",
            )

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label(cbar_label, fontsize=13)
    cbar.ax.tick_params(labelsize=11)

    ax.text(
        0.5,
        -0.14,
        f"数据来源：{source_note}",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=9,
        color="#666666",
    )

    fig.tight_layout()
    out = FIG_DIR / out_name
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def main() -> None:
    setup_font()

    nrmse = load_complete_nrmse_4x4()
    if nrmse is not None:
        mat, src = nrmse
        out = plot_heatmap(
            mat,
            "阶段 2：集中式反演辐照模型 nRMSE 热力图",
            "nrmse",
            src,
        )
        mode = "nRMSE 4×4"
    else:
        mat, src_note = build_correlation_4x4()
        out = plot_heatmap(
            mat,
            "阶段 2：集中式反演辐照关键变量相关性热力图",
            "corr",
            src_note,
        )
        mode = "Pearson 相关性 4×4"

    report = FIG_DIR / "阶段2_4x4热力图_数据说明.md"
    report.write_text(
        "\\n".join([
            "# 阶段 2 4×4 热力图数据说明",
            "",
            f"- 生成模式：{mode}",
            f"- 输出文件：`{out.name}`",
            "- 优先读取完整阶段级 nRMSE 4×4 指标。",
            "- 若阶段级 nRMSE 不完整，则自动改用关键变量 Pearson 相关性 4×4。",
            "- 不使用“未导出”或 0 值填补缺失指标。",
            "- 红色越深表示 nRMSE 越高，或相关性越强。",
            "",
        ]),
        encoding="utf-8",
    )

    print(f"[OK] {mode}: {out}")
    print(f"[OK] report: {report}")


if __name__ == "__main__":
    main()
```

---

## 三、执行脚本

执行：

```bash
python scripts/generate_stage2_formal_heatmap.py
```

---

## 四、检查输出

执行：

```bash
ls -lh output/pv_pipeline/ppt_figures/*阶段2*4x4*.png
ls -lh output/pv_pipeline/ppt_figures/阶段2_4x4热力图_数据说明.md
```

可能生成两种图之一：

### 情况 A：生成 nRMSE 热力图

```text
阶段2_集中式反演辐照_nRMSE热力图_4x4.png
```

说明项目中已经有完整阶段级 nRMSE 指标。

### 情况 B：生成相关性热力图

```text
阶段2_集中式反演辐照_关键变量相关性热力图_4x4.png
```

说明阶段级 nRMSE 不完整，脚本自动切换为关键变量 Pearson 相关性。  
这比出现“未导出”正式，也比强行填 0 严谨。

---

## 五、如果脚本提示缺少字段

如果报错类似：

```text
缺少字段：物理基线辐照、反演辐照
```

说明最终预测表没有保留阶段 2 中间变量。需要在阶段 2 训练或导出脚本中保留以下列：

```text
central_power_mw      # 集中式功率
era5_ghi              # ERA5 辐照
g_base                # 物理基线辐照
g_pred / g_inv        # 反演辐照
```

然后重新运行：

```bash
python scripts/generate_stage2_formal_heatmap.py
```

---

## 六、PPT 中建议使用的文字说明

如果生成的是 nRMSE 热力图：

```text
热力图展示阶段二不同子环节在训练、验证、测试和全量口径下的 nRMSE。颜色越深表示误差越高，可用于判断误差是否集中在物理基线、残差修正或功率重构环节。
```

如果生成的是相关性热力图：

```text
热力图展示集中式功率、ERA5 辐照、物理基线辐照和反演辐照之间的 Pearson 相关性。反演辐照同时保留功率驱动和气象背景信息，说明物理基线与残差修正共同参与了辐照估计。
```

---

## 七、正式性要求

最终图必须满足：

- 4×4。
- 每个格子都有数字。
- 不出现“未导出”。
- 不出现缺失值填 0。
- 红色系。
- 正方形画布。
- 数字清晰可读。

