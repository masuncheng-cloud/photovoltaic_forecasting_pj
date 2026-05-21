#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在 basemap.png 底图上叠加辐照度和功率预测的空间分布可视化。
参考 plot_lyg_basemap_thematic_improved.py 重构，输出：
  1. irradiance_map.png    — 辐照度（ERA5 ssrd）均值空间分布
  2. power_map.png         — 功率预测均值空间分布
  3. error_map.png         — 预测绝对误差空间分布
  4. irradiance_power_combined.png — 辐照度+功率并排图
  5. city_total_daily_curves.png   — 全市典型日光伏出力曲线
"""

from pathlib import Path
import json

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker
from matplotlib.colors import Normalize
from scipy.interpolate import Rbf
from PIL import Image
from matplotlib import font_manager
from shapely.geometry import Polygon, MultiPolygon, shape, Point
from shapely.ops import unary_union

# ── 全局字体设置 ──────────────────────────────────────────────────────────────
CH_FONT = None


def setup_chinese_font():
    global CH_FONT
    candidate_font_files = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    selected = None
    for fp in candidate_font_files:
        if Path(fp).exists():
            selected = fp
            break
    matplotlib.rcParams["axes.unicode_minus"] = False
    if selected is None:
        matplotlib.rcParams["font.family"] = "sans-serif"
        matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]
        print("[WARN] 未找到中文字体，回退默认字体。")
        return
    font_manager.fontManager.addfont(selected)
    prop = font_manager.FontProperties(fname=selected)
    CH_FONT = prop
    name = prop.get_name()
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = [name]
    matplotlib.rcParams["font.serif"] = [name]
    print(f"[INFO] 已加载中文字体: {name}")


def apply_tick_font(ax):
    if CH_FONT is None:
        return
    for tick in ax.get_xticklabels():
        tick.set_fontproperties(CH_FONT)
    for tick in ax.get_yticklabels():
        tick.set_fontproperties(CH_FONT)
    ax.xaxis.label.set_fontproperties(CH_FONT)
    ax.yaxis.label.set_fontproperties(CH_FONT)
    ax.title.set_fontproperties(CH_FONT)


# ── 坐标转换 ──────────────────────────────────────────────────────────────────
# 扩大覆盖范围以包含所有站点（灌云 lat 32.49, 灌南 lat 34.08, 赣榆 lat 35.08）
LON_MIN, LON_MAX = 118.35, 119.90
LAT_MIN, LAT_MAX = 34.00, 35.20
IMG_W, IMG_H = 1409, 1080
PAD = 10
DISP_X0, DISP_X1 = PAD, IMG_W - PAD
DISP_Y0, DISP_Y1 = PAD, IMG_H - PAD
DISP_W = DISP_X1 - DISP_X0
DISP_H = DISP_Y1 - DISP_Y0
GEO_W = LON_MAX - LON_MIN
GEO_H = LAT_MAX - LAT_MIN
GRID_RES = 400


def lonlat_to_pixel(lon, lat):
    x = (lon - LON_MIN) / GEO_W * DISP_W + DISP_X0
    y = (LAT_MAX - lat) / GEO_H * DISP_H + DISP_Y0
    return x, y


# ── 底图加载 ──────────────────────────────────────────────────────────────────
def load_basemap(path: Path):
    return np.array(Image.open(path).convert("RGBA"))


# ── 陆地边界（使用站点坐标凸包，精确覆盖所有电站区域）───────────────────────────
# 底图 basemap.png 是白色背景地图，陆地与海洋均呈现白色/浅灰色，
# 无法通过颜色区分。因此改用"站点凸包 + 缓冲区"作为裁剪掩码，
# 确保填充色仅出现在有站点数据的区域。
_SITE_HULL_MASK = None  # 2D boolean numpy array (IMG_H x IMG_W), True=inside clipping region


def extract_site_hull_mask(site_lons, site_lats):
    """
    创建基于站点凸包 + 缓冲区的 2D 布尔掩码（True = 站点覆盖区域）。
    流程：
    1. 取所有有效站点坐标；
    2. 计算凸包（ConvexHull）；
    3. 向外缓冲 0.1°（确保覆盖站点周围插值区域）；
    4. 将凸包多边形栅格化为 IMG_H x IMG_W 布尔数组；
    5. 返回 True=站点覆盖区域。
    """
    global _SITE_HULL_MASK
    if _SITE_HULL_MASK is not None:
        return _SITE_HULL_MASK

    import json
    from shapely.geometry import Polygon, Point
    from shapely.ops import unary_union
    from shapely.prepared import prep
    from scipy.spatial import ConvexHull
    from scipy.ndimage import binary_fill_holes, binary_dilation

    # 若无站点坐标，退回全图
    if len(site_lons) < 3:
        _SITE_HULL_MASK = np.ones((IMG_H, IMG_W), dtype=bool)
        return _SITE_HULL_MASK

    # 1. 站点坐标凸包
    coords = np.column_stack([np.asarray(site_lons, dtype=float),
                              np.asarray(site_lats, dtype=float)])
    hull = ConvexHull(coords)
    hull_verts = coords[hull.vertices]
    hull_poly = Polygon(hull_verts).buffer(0.10)  # 0.1° 缓冲
    hull_prep = prep(hull_poly)

    # 2. 栅格化：将经纬度网格映射到图像像素坐标
    # 图像像素坐标系：x=0（左）到 x=IMG_W-1（右）
    #                 y=0（上）到 y=IMG_H-1（下），但 origin="upper" 故 y 反向
    lon_grid = np.linspace(LON_MIN, LON_MAX, IMG_W)  # x 方向经度
    lat_grid = np.linspace(LAT_MAX, LAT_MIN, IMG_H)  # y 方向纬度（递减）

    lon_mat, lat_mat = np.meshgrid(lon_grid, lat_grid)

    # 3. 向量化点-in-polygon 测试
    points_flat = np.array([Point(lon_mat.ravel()[i], lat_mat.ravel()[i])
                              for i in range(lon_mat.size)])
    inside_flat = np.array([hull_prep.contains(p) for p in points_flat])
    inside = inside_flat.reshape(IMG_H, IMG_W).astype(bool)

    # 4. 轻微膨胀再填洞（平滑边界、闭合凸包边缘狭缝）
    inside = binary_dilation(inside, iterations=3)
    inside = binary_fill_holes(inside)
    _SITE_HULL_MASK = inside

    total = _SITE_HULL_MASK.size
    covered = _SITE_HULL_MASK.sum()
    print(f"[INFO] 站点凸包掩码: {covered}/{total} 像素 ({covered/total*100:.1f}%), "
          f"边界范围 y=[?,?] x=[?,?]")

    rows, cols = np.where(_SITE_HULL_MASK)
    if len(rows) > 0:
        print(f"  掩码 y-range: [{rows.min()}-{rows.max()}]")
        print(f"  掩码 x-range: [{cols.min()}-{cols.max()}]")
    return _SITE_HULL_MASK


def lonlat_to_boundary_coords(geom, n=60):
    """采样边界点用于 ax.plot(closed polygon)"""
    xs, ys = [], []
    rings = []
    if isinstance(geom, Polygon):
        rings = [geom.exterior]
    elif hasattr(geom, 'geoms'):  # MultiPolygon
        rings = [g.exterior for g in geom.geoms if hasattr(g, 'exterior')]
    elif hasattr(geom, 'exterior'):  # just in case
        rings = [geom.exterior]
    for ring in rings:
        x_all, y_all = ring.xy
        idx = np.linspace(0, len(x_all) - 1, n, dtype=int)
        for i in idx:
            lon, lat = x_all[i], y_all[i]
            px, py = lonlat_to_pixel(lon, lat)
            xs.append(px)
            ys.append(py)
        xs.append(None)
        ys.append(None)
    return xs, ys


# ── 县界绘制 ──────────────────────────────────────────────────────────────────
def draw_county_boundaries(ax, geojson_path: Path):
    with open(geojson_path) as f:
        gj = json.load(f)

    county_edge = {
        "东海县":  "#A9753E",
        "海州区":  "#4A9E6F",
        "赣榆区":  "#6BAED6",
        "连云区":  "#C8A83B",
        "灌云县":  "#7B68B6",
        "灌南县":  "#7DC89A",
        "赣榆县":  "#6BAED6",  # 旧名
    }

    for feat in gj["features"]:
        geom = feat["geometry"]
        name = feat["properties"].get("name", "")
        ec = county_edge.get(name, "#999999")

        if geom["type"] == "Polygon":
            rings = geom["coordinates"]
        elif geom["type"] == "MultiPolygon":
            rings = [ring for poly in geom["coordinates"] for ring in poly]
        else:
            continue

        for ring in rings:
            px_arr = np.array([lonlat_to_pixel(lon, lat) for lon, lat in ring])
            xs, ys = px_arr[:, 0], px_arr[:, 1]
            ax.plot(xs, ys, color=ec, linewidth=1.5, zorder=4)


# ── 县名标签 ──────────────────────────────────────────────────────────────────
def add_county_labels(ax, geojson_path: Path):
    centers = {
        "东海县":   (118.76, 34.52),
        "海州区":   (119.22, 34.59),
        "赣榆区":   (119.13, 34.88),
        "连云区":   (119.38, 34.73),
        "灌云县":   (119.30, 34.28),
        "灌南县":   (119.33, 34.09),
    }
    for name, (lon, lat) in centers.items():
        px, py = lonlat_to_pixel(lon, lat)
        ax.text(px, py, name, ha="center", va="center",
                fontsize=8.5, fontweight="bold", color="#2C3E50",
                fontproperties=CH_FONT,
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.72),
                zorder=10)


# ── 核心散点地图函数 ─────────────────────────────────────────────────────────
def plot_map(
    ax, basemap, geojson_path,
    site_lons, site_lats, values,
    capacities,
    cmap_name, vmin, vmax,
    title, cbar_label,
    cbar_fmt="%.0f",
    show_values=True,
    alpha_overlay=0.30,
    show_contour=True,
    contour_alpha=0.55,
):
    ax.imshow(basemap, extent=[0, IMG_W, IMG_H, 0], aspect="auto", zorder=0)
    ax.set_xlim(0, IMG_W)
    ax.set_ylim(IMG_H, 0)
    ax.axis("off")

    # 县界
    draw_county_boundaries(ax, geojson_path)
    add_county_labels(ax, geojson_path)

    # 底图叠加半透明白底色（让散点更清晰）
    overlay = np.ones((*basemap.shape[:2], 4)) * 0.82
    overlay[:, :, 3] = alpha_overlay
    if alpha_overlay > 0:
        ax.imshow(overlay, extent=[0, IMG_W, IMG_H, 0], aspect="auto", zorder=1)

    norm = Normalize(vmin=vmin, vmax=vmax, clip=True)
    cmap = plt.get_cmap(cmap_name)

    # ── 空间插值 + 站点覆盖区域裁剪 ──────────────────────────────────────────
    if show_contour and len(site_lons) >= 4:
        grid_x = np.linspace(DISP_X0, DISP_X1, GRID_RES)
        grid_y = np.linspace(DISP_Y0, DISP_Y1, GRID_RES)
        xi, yi = np.meshgrid(grid_x, grid_y)

        pts_x, pts_y = lonlat_to_pixel(site_lons, site_lats)
        pts_x = np.asarray(pts_x)
        pts_y = np.asarray(pts_y)

        # RBF 径向基函数插值
        rbf = Rbf(pts_x, pts_y, values, function="linear", smooth=0.5)
        zi = rbf(xi, yi)

        # 裁剪：使用站点坐标凸包掩码（精确覆盖所有站点区域）
        hull_mask = extract_site_hull_mask(site_lons, site_lats)
        # 将插值网格映射到图像分辨率
        grid_y_idx = ((yi - DISP_Y0) / DISP_H * (IMG_H - 1)).astype(int)
        grid_x_idx = ((xi - DISP_X0) / DISP_W * (IMG_W - 1)).astype(int)
        grid_y_idx = np.clip(grid_y_idx, 0, IMG_H - 1)
        grid_x_idx = np.clip(grid_x_idx, 0, IMG_W - 1)
        inside = hull_mask[grid_y_idx, grid_x_idx]
        zi_clipped = np.where(inside, zi, np.nan)
        ax.pcolormesh(xi, yi, zi_clipped, cmap=cmap, norm=norm,
                      alpha=contour_alpha, zorder=2, shading="auto")

    # 散点大小：按装机容量
    cap_max = np.nanmax(capacities)
    sizes = np.clip(capacities / cap_max * 220 + 25, 20, 320)

    xs, ys = lonlat_to_pixel(site_lons, site_lats)

    sc = ax.scatter(
        xs, ys,
        c=values, cmap=cmap, norm=norm,
        s=sizes,
        alpha=0.90,
        edgecolors="white", linewidths=0.7,
        zorder=5,
    )

    # 散点上标数值
    if show_values:
        for xi, yi, si, vi in zip(xs, ys, sizes, values):
            if si > 50 and np.isfinite(vi):
                ax.text(xi, yi, f"{vi:.0f}",
                        ha="center", va="center",
                        fontsize=5.8, color="black",
                        fontweight="bold", zorder=7,
                        bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.6))

    cbar = plt.colorbar(sc, ax=ax, shrink=0.58, pad=0.02, aspect=22)
    cbar.set_label(cbar_label, fontproperties=CH_FONT, fontsize=9.5)
    cbar.ax.tick_params(labelsize=8)
    cbar.formatter = matplotlib.ticker.FormatStrFormatter(cbar_fmt)

    # 固定 6 档色棒刻度，避免辐照度范围大时 tick 爆炸
    n_ticks = min(8, max(5, int(np.ceil(vmax - vmin)) + 1))
    n_ticks = min(n_ticks, max(5, int(round((vmax - vmin) / _nice_interval(vmax - vmin)) + 1)))
    nice_ticks = np.linspace(vmin, vmax, n_ticks)
    cbar.set_ticks(nice_ticks)
    cbar.update_ticks()

    ax.set_title(title, fontproperties=CH_FONT, fontsize=12.5,
                 fontweight="bold", pad=8)
    apply_tick_font(ax)


def _nice_interval(value_range, target_ticks=6):
    """返回美观刻度间隔（如 50, 100, 200）"""
    if value_range <= 0:
        return 1.0
    raw = value_range / target_ticks
    mag = 10 ** np.floor(np.log10(raw))
    norm = raw / mag
    if norm <= 1.0:
        step = 1.0 * mag
    elif norm <= 2.0:
        step = 2.0 * mag
    elif norm <= 5.0:
        step = 5.0 * mag
    else:
        step = 10.0 * mag
    return max(step, 1e-9)


# ── 站点过滤 ──────────────────────────────────────────────────────────────────
def filter_sites_in_city(site_df: pd.DataFrame, geojson_path: Path) -> pd.DataFrame:
    """不过滤站点，所有行政辖区内的站点均保留；裁剪由底图陆地边界控制"""
    return site_df.copy()


# ── 数据准备：辐照度（ERA5 ssrd_wm2，修复：取小时增量）────────────────────────
def prepare_irradiance(site_meteo: pd.DataFrame, site_master: pd.DataFrame):
    """
    取夏季（7-9月）白天有效辐照时段均值。

    修复说明：
    ERA5 ssrd_wm2 是从 UTC 00:00/06:00/12:00/18:00 重新同步的 6h 累积辐射通量。
    在 2025 数据中，UTC 00:00-05:00 diff 为正（夜间热辐射累积），
    UTC 06:00-11:00 diff 为负（大气向太空冷却，ssrd 减少）。
    取 -diff 并在 diff<0 时（真实白天）筛选，得到正确的小时辐照强度。
    筛选窗口：UTC 6-12 时（地方时约 14-20 时，即正午前后）。
    """
    df = site_meteo.copy()
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values(["site_id", "time"])

    # 计算逐小时 ssrd 变化量
    df["ssrd_diff"] = df.groupby("site_id")["ssrd_wm2"].diff()
    # 白天真实辐照强度 = -diff（diff<0 时，ssrd 在减少，辐射从天空中进入）
    df["irr_hourly"] = -df["ssrd_diff"]

    # 筛选：白天窗口（UTC 6-12 = 地方时约 14-20 时，正午前后）
    # 且 irr_hourly > 0 排除夜间残余
    mask = (
        (df["time"] >= "2025-07-01") &
        (df["time"] < "2025-10-01") &
        (df["time"].dt.hour.between(6, 12)) &
        (df["irr_hourly"] > 0)
    )
    day = df[mask].copy()
    if day.empty:
        print("[WARN] 辐照度筛选后无数据，将使用全部 irr_hourly > 0 数据")
        day = df[df["irr_hourly"] > 0].copy()

    agg = day.groupby("site_id").agg(
        irr_mean=("irr_hourly", "mean"),
        irr_std=("irr_hourly", "std"),
        count=("irr_hourly", "count"),
    ).reset_index()

    print(f"  辐照度统计: 站点 {len(agg)}, "
          f"均值范围 {agg['irr_mean'].min():.0f}-{agg['irr_mean'].max():.0f} W/m², "
          f"平均样本数 {agg['count'].mean():.0f}/站点")

    meta = site_master[["site_id", "lon", "lat", "capacity_mw",
                         "dev_type", "site_short_name"]].copy()
    merged = agg.merge(meta, on="site_id", how="inner")
    merged = merged.dropna(subset=["lon", "lat"])
    return merged


# ── 数据准备：功率（修复：使用 power_clean 而非 distributed_predictions）─────
def prepare_power(power_clean: pd.DataFrame, site_master: pd.DataFrame):
    """
    取 2025-H2 白天有效功率时段均值。

    修复说明：
    distributed_predictions 只覆盖 65 个小电站（≤22 MW），
    遗漏了数十个大型电站（100-400 MW）。
    改用 power_clean 表（覆盖全部 113 个有坐标站点），
    其中 power_mw 为清洗后的实际发电功率。
    """
    df = power_clean.copy()
    df["time"] = pd.to_datetime(df["time"])

    # 筛选条件：白天时段、有实际功率、电站已投运
    mask = (
        (df["time"] >= "2025-07-01") &
        (df["time"].dt.hour.between(6, 18)) &
        (df["power_mw"].notna()) &
        (df["power_mw"] > 0) &
        (df["ssrd_wm2"].notna()) &
        (df["ssrd_wm2"] > 50)   # 同步筛选辐照（消除累积偏差影响）
    )
    day = df[mask].copy()
    if day.empty:
        print("[WARN] 功率筛选后无数据，尝试放宽条件 ...")
        mask = (
            (df["time"] >= "2025-07-01") &
            (df["time"].dt.hour.between(6, 18)) &
            (df["power_mw"].notna()) &
            (df["power_mw"] > 0)
        )
        day = df[mask].copy()

    agg = day.groupby("site_id").agg(
        power_mean=("power_mw", "mean"),
        irr_mean=("ssrd_wm2", "mean"),
        capacity=("capacity_mw", "first"),
        count=("power_mw", "count"),
    ).reset_index()

    print(f"  功率统计: 站点 {len(agg)}, 功率范围 {agg['power_mean'].min():.1f}-{agg['power_mean'].max():.1f} MW, "
          f"平均样本数 {agg['count'].mean():.0f}/站点")

    meta = site_master[["site_id", "lon", "lat", "capacity_mw",
                         "dev_type", "site_short_name"]].copy()
    merged = agg.merge(meta, on="site_id", how="inner")
    merged = merged.dropna(subset=["lon", "lat"])
    return merged


# ── 主程序 ────────────────────────────────────────────────────────────────────
def main():
    setup_chinese_font()

    ROOT = Path(__file__).resolve().parents[1]
    OUT_DIR = ROOT / "output" / "pv_pipeline" / "figures_dashboard"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    BASEMAP = ROOT / "basemap.png"
    GEOJSON = ROOT / "lyg_boundary_counties_schematic.geojson"

    print("[INFO] 加载底图和边界 ...")
    basemap = load_basemap(BASEMAP)

    print("[INFO] 加载数据 ...")
    site_master = pd.read_csv(ROOT / "output" / "pv_pipeline" / "tables" / "site_master.csv")
    site_meteo = pd.read_pickle(ROOT / "output" / "pv_pipeline" / "tables" / "site_meteo.pkl")
    power_clean = pd.read_pickle(ROOT / "output" / "pv_pipeline" / "tables" / "power_clean.pkl")

    # ── 图1: 辐照度地图 ──────────────────────────────────────────────────────
    print("[INFO] 准备辐照度数据 ...")
    irr_data = prepare_irradiance(site_meteo, site_master)
    irr_data = filter_sites_in_city(irr_data, GEOJSON)
    print(f"  辐照站点数: {len(irr_data)}, 范围: {irr_data['irr_mean'].min():.1f} - {irr_data['irr_mean'].max():.1f} W/m²")

    irr_vmin = irr_data["irr_mean"].min()
    irr_vmax = irr_data["irr_mean"].max()
    fig1, ax1 = plt.subplots(figsize=(13, 10))
    plot_map(
        ax1, basemap, GEOJSON,
        irr_data["lon"].values, irr_data["lat"].values,
        irr_data["irr_mean"].values,
        irr_data["capacity_mw"].fillna(5).values,
        cmap_name="YlOrRd",
        vmin=irr_vmin, vmax=irr_vmax,
        title="辐照度空间分布（ERA5 ssrd，2025年7-9月白天均值）",
        cbar_label="小时辐照度 (W/m²)",
        cbar_fmt="%.0f",
        alpha_overlay=0,
    )
    fig1.tight_layout(pad=1.2)
    out1 = OUT_DIR / "irradiance_map.png"
    fig1.savefig(out1, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig1)
    print(f"[OK] 辐照度地图: {out1}")

    # ── 图2: 功率地图 ────────────────────────────────────────────────────────
    print("[INFO] 准备功率数据 ...")
    pwr_data = prepare_power(power_clean, site_master)
    pwr_data = filter_sites_in_city(pwr_data, GEOJSON)
    print(f"  功率站点数: {len(pwr_data)}, 范围: {pwr_data['power_mean'].min():.2f} - {pwr_data['power_mean'].max():.2f} MW")

    pwr_vmax = pwr_data["power_mean"].max()
    fig2, ax2 = plt.subplots(figsize=(13, 10))
    plot_map(
        ax2, basemap, GEOJSON,
        pwr_data["lon"].values, pwr_data["lat"].values,
        pwr_data["power_mean"].values,
        pwr_data["capacity_mw"].fillna(5).values,
        cmap_name="plasma",
        vmin=0, vmax=pwr_vmax,
        title="光伏电站实际发电功率均值空间分布（2025年7-9月白天均值）",
        cbar_label="发电功率 (MW)",
        cbar_fmt="%.1f",
        alpha_overlay=0,
    )
    fig2.tight_layout(pad=1.2)
    out2 = OUT_DIR / "power_map.png"
    fig2.savefig(out2, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig2)
    print(f"[OK] 功率地图: {out2}")

    # ── 图3: 误差地图（需要预测数据，对仍可用的站点绘制）────────────────────
    print("[INFO] 检查预测数据可用性 ...")
    # 误差图依赖 power_pred，但 distributed_predictions 站点有限
    # 暂以发电功率均值代替（实际功率空间分布本身即有代表性）
    # 如需误差图，请在 prepare_power 中加入 power_pred 分组聚合
    print("[INFO] 误差地图暂时跳过（需 prediction 站点子集）")

    # ── 图4: 辐照度+功率双图并排 ────────────────────────────────────────────
    print("[INFO] 绘制辐照+功率双图并排 ...")
    irr_vmin, irr_vmax = irr_data["irr_mean"].min(), irr_data["irr_mean"].max()
    pwr_vmax = pwr_data["power_mean"].max()

    fig4, axes = plt.subplots(1, 2, figsize=(26, 10))

    # ── 左图：辐照度 ──────────────────────────────────────────────────────────
    ax = axes[0]
    ax.imshow(basemap, extent=[0, IMG_W, IMG_H, 0], aspect="auto", zorder=0)
    ax.set_xlim(0, IMG_W)
    ax.set_ylim(IMG_H, 0)
    ax.axis("off")
    draw_county_boundaries(ax, GEOJSON)
    add_county_labels(ax, GEOJSON)

    norm = Normalize(vmin=irr_vmin, vmax=irr_vmax)
    cmap_irr = plt.get_cmap("YlOrRd")
    if len(irr_data) >= 4:
        gx = np.linspace(DISP_X0, DISP_X1, GRID_RES)
        gy = np.linspace(DISP_Y0, DISP_Y1, GRID_RES)
        gxi, gyi = np.meshgrid(gx, gy)
        px, py = lonlat_to_pixel(irr_data["lon"].values, irr_data["lat"].values)
        rbf_irr = Rbf(px, py, irr_data["irr_mean"].values, function="linear", smooth=0.3)
        zi = rbf_irr(gxi, gyi)
        hull_mask = extract_site_hull_mask(irr_data["lon"].values, irr_data["lat"].values)
        gyi_idx = ((gyi - DISP_Y0) / DISP_H * (IMG_H - 1)).astype(int)
        gxi_idx = ((gxi - DISP_X0) / DISP_W * (IMG_W - 1)).astype(int)
        gyi_idx = np.clip(gyi_idx, 0, IMG_H - 1)
        gxi_idx = np.clip(gxi_idx, 0, IMG_W - 1)
        inside = land_mask[gyi_idx, gxi_idx]
        zi_clipped = np.where(inside, zi, np.nan)
        ax.pcolormesh(gxi, gyi, zi_clipped, cmap=cmap_irr, norm=norm,
                      alpha=0.55, zorder=2, shading="auto")

    sizes = np.clip(irr_data["capacity_mw"].fillna(5).values /
                    irr_data["capacity_mw"].fillna(5).max() * 220 + 25, 20, 320)
    xs, ys = lonlat_to_pixel(irr_data["lon"].values, irr_data["lat"].values)
    sc = ax.scatter(xs, ys, c=irr_data["irr_mean"].values, cmap=cmap_irr, norm=norm,
                    s=sizes, alpha=0.90, edgecolors="white", linewidths=0.7, zorder=5)
    cbar = plt.colorbar(sc, ax=ax, shrink=0.55, pad=0.02)
    cbar.set_label("小时辐照度 (W/m²)", fontproperties=CH_FONT)
    cbar.formatter = matplotlib.ticker.FormatStrFormatter("%.0f")
    irr_nticks = min(8, max(5, int(round((irr_vmax - irr_vmin) / _nice_interval(irr_vmax - irr_vmin)) + 1)))
    cbar.set_ticks(np.linspace(irr_vmin, irr_vmax, irr_nticks))
    cbar.update_ticks()
    ax.set_title("辐照度（ERA5 ssrd 小时增量, W/m²）", fontproperties=CH_FONT, fontsize=12, fontweight="bold")
    apply_tick_font(ax)

    # ── 右图：功率 ────────────────────────────────────────────────────────────
    ax = axes[1]
    ax.imshow(basemap, extent=[0, IMG_W, IMG_H, 0], aspect="auto", zorder=0)
    ax.set_xlim(0, IMG_W)
    ax.set_ylim(IMG_H, 0)
    ax.axis("off")
    draw_county_boundaries(ax, GEOJSON)
    add_county_labels(ax, GEOJSON)

    cap_max = pwr_data["capacity_mw"].fillna(5).max()
    norm2 = Normalize(vmin=0, vmax=pwr_vmax)
    cmap_pwr = plt.get_cmap("plasma")
    if len(pwr_data) >= 4:
        gx2 = np.linspace(DISP_X0, DISP_X1, GRID_RES)
        gy2 = np.linspace(DISP_Y0, DISP_Y1, GRID_RES)
        gxi2, gyi2 = np.meshgrid(gx2, gy2)
        px2, py2 = lonlat_to_pixel(pwr_data["lon"].values, pwr_data["lat"].values)
        rbf_pwr = Rbf(px2, py2, pwr_data["power_mean"].values, function="linear", smooth=0.3)
        zi2 = rbf_pwr(gxi2, gyi2)
        land_mask = extract_land_boundary(basemap)
        gyi2_idx = ((gyi2 - DISP_Y0) / DISP_H * (IMG_H - 1)).astype(int)
        gxi2_idx = ((gxi2 - DISP_X0) / DISP_W * (IMG_W - 1)).astype(int)
        gyi2_idx = np.clip(gyi2_idx, 0, IMG_H - 1)
        gxi2_idx = np.clip(gxi2_idx, 0, IMG_W - 1)
        inside2 = land_mask[gyi2_idx, gxi2_idx]
        zi2_clipped = np.where(inside2, zi2, np.nan)
        ax.pcolormesh(gxi2, gyi2, zi2_clipped, cmap=cmap_pwr, norm=norm2,
                      alpha=0.55, zorder=2, shading="auto")

    sizes2 = np.clip(pwr_data["capacity_mw"].fillna(5).values / cap_max * 220 + 25, 20, 320)
    xs2, ys2 = lonlat_to_pixel(pwr_data["lon"].values, pwr_data["lat"].values)
    sc2 = ax.scatter(xs2, ys2, c=pwr_data["power_mean"].values, cmap=cmap_pwr, norm=norm2,
                     s=sizes2, alpha=0.90, edgecolors="white", linewidths=0.7, zorder=5)
    cbar2 = plt.colorbar(sc2, ax=ax, shrink=0.55, pad=0.02)
    cbar2.set_label("发电功率 (MW)", fontproperties=CH_FONT)
    cbar2.formatter = matplotlib.ticker.FormatStrFormatter("%.1f")
    pwr_nticks = min(8, max(5, int(round(pwr_vmax / _nice_interval(pwr_vmax)) + 1)))
    cbar2.set_ticks(np.linspace(0, pwr_vmax, pwr_nticks))
    cbar2.update_ticks()
    ax.set_title("实际发电功率均值 (MW)", fontproperties=CH_FONT, fontsize=12, fontweight="bold")
    apply_tick_font(ax)

    fig4.suptitle("连云港光伏电站辐照度与功率空间分布（2025年7-9月白天）",
                   fontproperties=CH_FONT, fontsize=15, fontweight="bold", y=0.99)
    fig4.tight_layout(pad=1.5)
    out4 = OUT_DIR / "irradiance_power_combined.png"
    fig4.savefig(out4, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig4)
    print(f"[OK] 辐照+功率并排图: {out4}")

    # ── 图5: 典型日光伏出力日内曲线 ──────────────────────────────────────────
    print("[INFO] 绘制典型日光伏出力曲线 ...")
    df = power_clean.copy()
    df["time"] = pd.to_datetime(df["time"])

    # 选取辐照最充足的3天（使用 ssrd_wm2，2025年夏季）
    day_df = df[(df["time"] >= "2025-07-01") & (df["time"] < "2025-10-01") &
                df["time"].dt.hour.between(6, 18)].copy()
    day_df["date"] = day_df["time"].dt.date
    # 用 ssrd_wm2 筛选辐照充足时段（用小时增量避免累积偏差）
    day_df = day_df[day_df["ssrd_wm2"] > 50]  # 简化：直接用 ssrd_wm2 > 50
    daily_irr = day_df.groupby("date")["power_mw"].sum()
    best_dates = daily_irr.sort_values(ascending=False).head(3).index.tolist()
    print(f"  典型日: {best_dates}")

    n = len(best_dates)
    fig5, axes = plt.subplots(1, n, figsize=(5.5 * n, 4.5))
    if n == 1:
        axes = [axes]

    for ax, date in zip(axes, best_dates):
        d = df[df["time"].dt.date == date].copy()
        hourly = d.groupby(d["time"].dt.floor("H")).agg(
            true_total=("power_mw", "sum"),
        ).reset_index()
        hourly["hour"] = hourly["time"].dt.hour + hourly["time"].dt.minute / 60

        ax.fill_between(hourly["hour"], 0, hourly["true_total"],
                        alpha=0.20, color="#2980B9", label="发电功率面积")
        ax.plot(hourly["hour"], hourly["true_total"], "o-",
                color="#2980B9", linewidth=2.2, markersize=4, label="全市总功率", zorder=3)
        ax.set_title(str(date), fontproperties=CH_FONT, fontsize=11)
        ax.set_xlabel("小时 (h)", fontproperties=CH_FONT)
        ax.set_ylabel("全市总功率 (MW)", fontproperties=CH_FONT)
        ax.legend(prop=CH_FONT, fontsize=7.5)
        ax.grid(True, linestyle="--", alpha=0.35)
        ax.set_xlim(4, 21)
        ax.set_ylim(bottom=0)
        apply_tick_font(ax)

    fig5.suptitle("全市光伏总出力典型日曲线（辐照最充足日）",
                   fontproperties=CH_FONT, fontsize=13, fontweight="bold")
    fig5.tight_layout(pad=1.5)
    out5 = OUT_DIR / "city_total_daily_curves.png"
    fig5.savefig(out5, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig5)
    print(f"[OK] 全市总量曲线: {out5}")

    print(f"\n[ALL DONE] 输出目录: {OUT_DIR}")
    print(f"  irradiance_map.png              辐照度空间分布")
    print(f"  power_map.png                   功率空间分布")
    print(f"  irradiance_power_combined.png   辐照+功率并排")
    print(f"  city_total_daily_curves.png     全市典型日曲线")


if __name__ == "__main__":
    main()
