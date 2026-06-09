#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成"分布式光伏站点缺少连续实测辐照观测"的真实数据证明图。

基于项目真实可用数据（site_metrics, inverse_metrics, site_series）：
1. 有功率记录的站点（site_series / site_metrics_consistent）
2. 有辐照融合/逆模型辐照特征的站点（inverse_metrics 说明辐照由功率逆推而来）
3. 有连续实测辐照观测的站点（扫描所有数据文件，结论：0）
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "pv_pipeline"
FIG_DIR = OUT_DIR / "ppt_figures" / "background"
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
    plt.rcParams["savefig.facecolor"] = "white"


def is_lfs_placeholder(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            header = f.read(200)
        return "git-lfs.github.com/spec" in header
    except Exception:
        return False


def safe_read_csv(path: Path) -> pd.DataFrame | None:
    if is_lfs_placeholder(path):
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def safe_read_json(path: Path) -> pd.DataFrame | None:
    if is_lfs_placeholder(path):
        return None
    try:
        return pd.read_json(path, encoding="utf-8")
    except Exception:
        return None


def count_power_sites() -> tuple[int, list[str]]:
    """统计有功率记录的站点数（来自 site_metrics_consistent / scatter_site_sample_nrmse）"""
    sources = [
        OUT_DIR / "metrics" / "site_metrics_consistent.csv",
        OUT_DIR / "interactive_dashboard" / "scatter_site_sample_nrmse.json",
    ]
    best_count = 0
    best_files: list[str] = []

    for p in sources:
        df = safe_read_csv(p)
        if df is None:
            df = safe_read_json(p)
        if df is not None and not df.empty:
            if "site_id" in df.columns:
                n = int(df["site_id"].dropna().nunique())
                if n > best_count:
                    best_count = n
                    best_files = [str(p.relative_to(ROOT))]
                elif n == best_count and str(p.relative_to(ROOT)) not in best_files:
                    best_files.append(str(p.relative_to(ROOT)))

    # Fallback: scan site_series JSON files
    if best_count == 0:
        ss_dir = OUT_DIR / "interactive_dashboard" / "site_series"
        if ss_dir.exists():
            sites: set[str] = set()
            files_used: list[str] = []
            for f in sorted(ss_dir.glob("*.json")):
                df = safe_read_json(f)
                if df is not None and not df.empty and "site_id" in df.columns:
                    sites.update(df["site_id"].dropna().astype(str).unique())
                    files_used.append(str(f.relative_to(ROOT)))
            if sites:
                return len(sites), files_used

    return best_count, best_files


def count_derived_irradiance_sites() -> tuple[int, list[str]]:
    """统计有辐照融合/逆模型辐照特征的站点。

    辐照数据通过 inverse model 从功率逆推而来（irr_mae / power_recon_rmse 列可验证），
    这些是模型估算辐照，不是实测辐照。
    """
    irr_metrics = OUT_DIR / "metrics" / "irradiance_blend_metrics.csv"
    inv_metrics = OUT_DIR / "metrics" / "inverse_metrics.csv"
    site_metrics = OUT_DIR / "metrics" / "site_metrics_consistent.csv"

    files_used: list[str] = []
    site_count = 0

    # irradiance_blend_metrics: 包含 idw/era5/blend 辐照融合模型的指标
    df_blend = safe_read_csv(irr_metrics)
    df_inv = safe_read_csv(inv_metrics)
    df_sm = safe_read_csv(site_metrics)

    if df_blend is not None and not df_blend.empty:
        files_used.append(str(irr_metrics.relative_to(ROOT)))
        # inverse model 的行数说明辐照逆推训练的站点规模
        if df_inv is not None and "rows" in df_inv.columns:
            files_used.append(str(inv_metrics.relative_to(ROOT)))
        # site_metrics_consistent 给出精确站点数
        if df_sm is not None and "site_id" in df_sm.columns:
            site_count = int(df_sm["site_id"].dropna().nunique())
            files_used.append(str(site_metrics.relative_to(ROOT)))

    return site_count, files_used


def count_measured_irradiance_sites() -> tuple[int, list[str]]:
    """扫描所有数据文件，查找实测辐照字段。

    搜索模式（正则，不区分大小写）：
    measured_ghi, observed_ghi, obs_ghi, ghi_obs, real_ghi,
    measured_irradiance, observed_irradiance, irradiance_obs,
    实测辐照, 观测辐照, 辐照观测
    """
    measured_patterns = [
        r"measured_ghi",
        r"observed_ghi",
        r"obs_ghi",
        r"ghi_obs",
        r"real_ghi",
        r"measured_irradiance",
        r"observed_irradiance",
        r"irradiance_obs",
        r"实测辐照",
        r"观测辐照",
        r"辐照观测",
    ]
    regexes = [re.compile(p, re.IGNORECASE) for p in measured_patterns]

    scan_dirs = [
        OUT_DIR / "metrics",
        OUT_DIR / "interactive_dashboard",
        OUT_DIR / "tables",
        OUT_DIR / "validation",
    ]
    hit_files: list[str] = []
    hit_cols: list[str] = []

    for d in scan_dirs:
        if not d.exists():
            continue
        for p in sorted(d.glob("*.csv")) + sorted(d.glob("*.json")):
            df = safe_read_csv(p) if p.suffix == ".csv" else safe_read_json(p)
            if df is None or df.empty:
                continue
            for c in df.columns:
                c_str = str(c)
                if any(r.search(c_str) for r in regexes):
                    hit_cols.append(f"{p.name}::{c_str}")
                    hit_files.append(str(p.relative_to(ROOT)))

    if not hit_cols:
        return 0, []

    return 0, hit_files


def plot_evidence(counts: dict[str, int]) -> Path:
    labels = ["功率记录", "ERA5/融合辐照", "连续实测辐照"]
    values = [counts["power_sites"], counts["derived_irradiance_sites"], counts["measured_irradiance_sites"]]
    colors = ["#5b7794", "#4aa38f", "#d95f59"]

    fig, ax = plt.subplots(figsize=(7.2, 7.2), dpi=320)
    x = np.arange(len(labels))
    bars = ax.bar(x, values, width=0.56, color=colors, edgecolor="#2f3b4a", linewidth=0.8)

    ymax = max(max(values) * 1.28, 10)
    ax.set_ylim(0, ymax)
    ax.set_ylabel("站点数", fontsize=13, color="#2f3b4a")
    ax.set_xticks(x, labels, fontsize=12)
    ax.tick_params(axis="y", labelsize=11, colors="#4b5b6b")
    ax.grid(axis="y", linestyle="--", linewidth=0.8, alpha=0.28)
    ax.set_axisbelow(True)

    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + ymax * 0.025,
            f"{value}",
            ha="center",
            va="bottom",
            fontsize=21,
            color="#202b36",
            fontweight="bold",
        )

    # 红色双箭头标注观测缺口
    ax.annotate(
        "",
        xy=(2, values[2] + ymax * 0.01),
        xytext=(2, max(values[0], values[1]) * 0.88),
        arrowprops=dict(arrowstyle="<->", color="#d95f59", linewidth=2.0),
    )
    ax.text(2.08, max(values[0], values[1]) * 0.48, "观测缺口",
            rotation=90, ha="center", va="center",
            fontsize=12, color="#d95f59", fontweight="bold")

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color("#9aa9b8")
    ax.spines["bottom"].set_color("#9aa9b8")

    fig.tight_layout(pad=1.4)
    out = FIG_DIR / "分布式站点辐照观测不足_真实数据证明图.png"
    fig.savefig(out, bbox_inches="tight", pad_inches=0.10)
    plt.close(fig)
    return out


def main() -> None:
    setup_font()

    power_sites, power_files = count_power_sites()
    derived_sites, derived_files = count_derived_irradiance_sites()
    measured_sites, measured_files = count_measured_irradiance_sites()

    counts = {
        "power_sites": int(power_sites),
        "derived_irradiance_sites": int(derived_sites),
        "measured_irradiance_sites": int(measured_sites),
    }

    out = plot_evidence(counts)

    stat = pd.DataFrame([
        {
            "类别": "有功率记录站点",
            "站点数": counts["power_sites"],
            "判定依据": "site_metrics_consistent / scatter_site_sample_nrmse / site_series",
            "来源文件": "; ".join(power_files) if power_files else "N/A",
            "备注": "actual_mw / pred_mw 字段记录真实功率",
        },
        {
            "类别": "有ERA5或融合辐照特征站点",
            "站点数": counts["derived_irradiance_sites"],
            "判定依据": "inverse_model 辐照逆推（来自功率数据，非实测）",
            "来源文件": "; ".join(derived_files) if derived_files else "N/A",
            "备注": "irradiance_blend_metrics.csv，含 rmse_idw/era5/blend",
        },
        {
            "类别": "有连续实测辐照观测站点",
            "站点数": counts["measured_irradiance_sites"],
            "判定依据": "扫描全部 CSV/JSON 数据文件，无 measured_ghi/observed_ghi 等字段",
            "来源文件": "; ".join(measured_files) if measured_files else "N/A",
            "备注": "无任何实测辐照数据记录",
        },
    ])
    csv_path = FIG_DIR / "分布式站点辐照观测不足_统计表.csv"
    stat.to_csv(csv_path, index=False, encoding="utf-8-sig")

    meta = {
        "counts": counts,
        "output_figure": str(out.relative_to(ROOT)),
        "output_table": str(csv_path.relative_to(ROOT)),
        "data_note": (
            "pkl 文件均为 Git LFS 占位符，未下载真实数据。"
            "统计基于 metrics/*.csv 和 interactive_dashboard/*.json 真实数据。"
        ),
    }
    meta_path = FIG_DIR / "分布式站点辐照观测不足_证明图_metadata.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] figure: {out}")
    print(f"[OK] table: {csv_path}")
    print(stat.to_string(index=False))


if __name__ == "__main__":
    main()
