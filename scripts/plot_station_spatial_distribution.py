from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageEnhance, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = PROJECT_ROOT / "city_map.jpg"
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_AUDIT_CSV = OUT_DIR / "station_spatial_audit.csv"
OUT_OUTLIERS_CSV = OUT_DIR / "station_spatial_outliers.csv"
OUT_AUDIT_IMG = OUT_DIR / "lianyungang_station_spatial_distribution_audit.png"
OUT_PPT_IMG = OUT_DIR / "lianyungang_station_spatial_distribution_ppt.png"
OUT_FULL_IMG = OUT_DIR / "lianyungang_station_spatial_distribution.png"


# --- 经纬度到像素的线性映射范围 ---
# 整体偏左 → 增大 lon_min/lon_max（让同样经度对应更右边的像素）
# 整体偏右 → 减小 lon_min/lon_max
# 整体偏上 → 增大 lat_min/lat_max
# 整体偏下 → 减小 lat_min/lat_max
MAP_BOUNDS = {
    "lon_min": 118.25,
    "lon_max": 119.85,
    "lat_min": 33.95,
    "lat_max": 35.35,
}

# --- 地图内框（黑色边框以内的实际绘图区域）像素坐标 ---
# 底图原始尺寸 2500×1738，resize 到 2200 后等比缩放至 ≈1529×1061
# 底图 resize 系数：2200/2500 = 0.88
# 偏左 → 增大 x_min/x_max；偏右 → 减小 x_min/x_max
# 偏上 → 增大 y_min/y_max；偏下 → 减小 y_min/y_max
MAP_INNER_BOX = {
    "x_min": 90,
    "x_max": 2070,
    "y_min": 100,
    "y_max": 1420,
}

# --- 连云港市粗略 bbox（用于第一轮越界初筛）---
LIANYUNGANG_BBOX = {
    "lon_min": 118.35,
    "lon_max": 119.95,
    "lat_min": 34.05,
    "lat_max": 35.25,
}

# --- 站点台账候选文件（按优先级排序）---
STATION_FILE_CANDIDATES = [
    PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "station_metadata_canonical.csv",
    PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "site_master.csv",
    PROJECT_ROOT / "data" / "station_metadata.csv",
    PROJECT_ROOT / "data" / "stations.csv",
    PROJECT_ROOT / "output" / "pv_pipeline" / "interactive_dashboard" / "site_metrics.json",
]

# --- 名称/区域不一致关键词（疑似不在连云港市范围）---
OUTSIDE_REGION_KEYWORDS = [
    "沭阳", "宿迁", "淮安", "盐城", "徐州",
    "临沂", "日照", "莒县", "莒南", "新沂",
]

# --- 沿海关键词（这些站点即使靠近海岸也不要直接判定为错误，只标记为需人工核验）---
COASTAL_KEYWORDS = [
    "沿海", "灌云", "灌南", "徐圩", "大浦", "裕灌",
    "连云", "海滨", "海州", "赣榆", "临港",
    "板桥", "云台", "宿城", "前三岛",
]

# --- 连云港市下属区县名（用于海岸保护兜底）---
LYG_COUNTIES = {
    "灌云县", "灌南县", "赣榆区", "东海县",
    "海州区", "连云区", "开发区", "徐圩新区",
}

# --- 正式 PPT 图中只展示无争议站点 ---
PPT_ALLOWED_STATUS = {"ok"}

# --- 用户人工指定需要复核的站点（当前底图上展示有争议）---
# 这些站点不代表一定错误，只表示在截图底图上展示容易引起误解
MANUAL_REVIEW_SITE_IDS = {
    "S097",  # 沿海灌云光伏：当前落在海面，需核验坐标/底图配准/是否为海上或滩涂项目
    "S096",  # 华电曲阳光伏发电站：当前视觉上接近或越过市界，需核验
}

MANUAL_REVIEW_KEYWORDS = [
    "沿海灌云",
    "华电曲阳",
]


# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def load_font(size: int):
    for path in [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        p = Path(path)
        if p.exists():
            return ImageFont.truetype(str(p), size=size)
    return ImageFont.load_default()


FONT_TITLE = load_font(42)
FONT_LABEL = load_font(24)
FONT_SMALL = load_font(20)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    for c in list(df.columns):
        lc = str(c).strip().lower()
        if lc in {"station_id", "site_id", "id", "站点id", "站点编号"}:
            if "station_id" not in df.columns:
                df["station_id"] = df[c]
        elif lc in {
            "station_name", "site_name", "name", "站点名称", "名称",
            "site_short_name", "site_full_name",
        }:
            if "station_name" not in df.columns:
                df["station_name"] = df[c]
        elif lc in {"longitude", "lon", "lng", "经度"}:
            if "longitude" not in df.columns:
                df["longitude"] = df[c]
        elif lc in {"latitude", "lat", "纬度"}:
            if "latitude" not in df.columns:
                df["latitude"] = df[c]
        elif lc in {"capacity_mw", "capacity", "装机容量", "容量mw", "容量"}:
            if "capacity_mw" not in df.columns:
                df["capacity_mw"] = df[c]
        elif lc in {"station_type", "site_type", "type", "类型", "类别", "dev_type"}:
            if "station_type" not in df.columns:
                df["station_type"] = df[c]
        elif lc in {"county", "区县", "区域"}:
            if "county" not in df.columns:
                df["county"] = df[c]
    return df


def read_any_table(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in ["sites", "data", "records", "site_metrics"]:
                    if key in data and isinstance(data[key], list):
                        return pd.DataFrame(data[key])
                return pd.DataFrame(data)
            return pd.DataFrame(data)
        return pd.read_csv(path)
    except Exception:
        return None


def find_station_table() -> pd.DataFrame:
    frames = []
    for path in STATION_FILE_CANDIDATES:
        df = read_any_table(path)
        if df is None or df.empty:
            continue
        df = normalize_columns(df)
        if {"longitude", "latitude"}.issubset(df.columns):
            df["_source_file"] = str(path.relative_to(PROJECT_ROOT))
            frames.append(df)

    if not frames:
        raise FileNotFoundError(
            "未找到包含经纬度的站点文件。请补充 STATION_FILE_CANDIDATES。"
        )

    df = pd.concat(frames, ignore_index=True, sort=False)
    if "station_id" not in df.columns:
        df["station_id"] = [f"S{i + 1:03d}" for i in range(len(df))]
    if "station_name" not in df.columns:
        df["station_name"] = df["station_id"]
    if "capacity_mw" not in df.columns:
        df["capacity_mw"] = None
    if "station_type" not in df.columns:
        df["station_type"] = "distributed"

    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["capacity_mw"] = pd.to_numeric(df["capacity_mw"], errors="coerce")
    df = df.dropna(subset=["longitude", "latitude"]).copy()
    df = df.drop_duplicates(subset=["station_id"], keep="first")
    df["station_type"] = df["station_type"].astype(str)
    return df


# ─────────────────────────────────────────────
# 经纬度 → 像素坐标（使用内框映射）
# ─────────────────────────────────────────────

def lonlat_to_xy(lon: float, lat: float) -> tuple[float, float]:
    lon_min = MAP_BOUNDS["lon_min"]
    lon_max = MAP_BOUNDS["lon_max"]
    lat_min = MAP_BOUNDS["lat_min"]
    lat_max = MAP_BOUNDS["lat_max"]

    x0 = MAP_INNER_BOX["x_min"]
    x1 = MAP_INNER_BOX["x_max"]
    y0 = MAP_INNER_BOX["y_min"]
    y1 = MAP_INNER_BOX["y_max"]

    x = x0 + (lon - lon_min) / (lon_max - lon_min) * (x1 - x0)
    y = y0 + (lat_max - lat) / (lat_max - lat_min) * (y1 - y0)
    return x, y


# ─────────────────────────────────────────────
# 海上点判断
# ─────────────────────────────────────────────

def is_probably_water(img: Image.Image, x: float, y: float) -> bool:
    radius = 5
    pixels = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            xx = int(x + dx)
            yy = int(y + dy)
            if 0 <= xx < img.width and 0 <= yy < img.height:
                pixels.append(img.getpixel((xx, yy)))
    if not pixels:
        return False
    r = sum(p[0] for p in pixels) / len(pixels)
    g = sum(p[1] for p in pixels) / len(pixels)
    b = sum(p[2] for p in pixels) / len(pixels)
    return b > r + 18 and b > g + 8 and b > 145


# ─────────────────────────────────────────────
# 站点分类（集中式 / 分布式）
# ─────────────────────────────────────────────

def classify_type(row: pd.Series) -> str:
    text = f"{row.get('station_type', '')} {row.get('station_name', '')}".lower()
    if any(k in text for k in ["central", "集中", "集中式"]):
        return "centralized"
    return "distributed"


# ─────────────────────────────────────────────
# 站点空间核查
# ─────────────────────────────────────────────

def audit_stations(stations: pd.DataFrame, img: Image.Image) -> pd.DataFrame:
    stations = stations.copy()

    stations["plot_x"] = stations.apply(
        lambda r: lonlat_to_xy(r["longitude"], r["latitude"])[0], axis=1
    )
    stations["plot_y"] = stations.apply(
        lambda r: lonlat_to_xy(r["longitude"], r["latitude"])[1], axis=1
    )

    stations["in_map_inner_box"] = (
        stations["plot_x"].between(MAP_INNER_BOX["x_min"], MAP_INNER_BOX["x_max"])
        & stations["plot_y"].between(MAP_INNER_BOX["y_min"], MAP_INNER_BOX["y_max"])
    )

    stations["in_lianyungang_bbox"] = (
        (LIANYUNGANG_BBOX["lon_min"] <= stations["longitude"])
        & (stations["longitude"] <= LIANYUNGANG_BBOX["lon_max"])
        & (LIANYUNGANG_BBOX["lat_min"] <= stations["latitude"])
        & (stations["latitude"] <= LIANYUNGANG_BBOX["lat_max"])
    )

    stations["suspect_lonlat"] = ~(
        stations["longitude"].between(118.0, 120.5)
        & stations["latitude"].between(33.5, 35.5)
    )

    stations["suspect_outside_city"] = ~stations["in_lianyungang_bbox"]

    stations["suspect_offshore"] = stations.apply(
        lambda r: is_probably_water(img, r["plot_x"], r["plot_y"])
        if r["in_map_inner_box"] else False,
        axis=1,
    )

    def check_name_mismatch(row):
        name = str(row.get("station_name", "")).lower()
        return any(kw in name for kw in OUTSIDE_REGION_KEYWORDS)

    stations["suspect_name_region_mismatch"] = stations.apply(check_name_mismatch, axis=1)

    def coastal_keyword_match(row):
        name = str(row.get("station_name", "")).lower()
        return any(kw in name for kw in COASTAL_KEYWORDS)

    stations["_has_coastal_keyword"] = stations.apply(coastal_keyword_match, axis=1)

    def county_in_lyg(row):
        county = str(row.get("county", "")).strip()
        return county in LYG_COUNTIES

    stations["_lyg_county"] = stations.apply(county_in_lyg, axis=1)

    def resolve_audit_status(row):
        reasons = []
        if row["suspect_lonlat"]:
            reasons.append("经纬度数值明显异常；")

        # 纬度 ≥ 34.9°N 的北部海岸站点：即使像素颜色偏蓝，也不应视为越界
        is_northern_coast = row["latitude"] >= 34.9 and row["suspect_offshore"]

        if row["suspect_outside_city"]:
            reasons.append("经纬度超出连云港市粗略范围；")
        if row["suspect_name_region_mismatch"]:
            reasons.append("站点名称疑似不属于连云港市范围；")
        if row["suspect_offshore"] and not is_northern_coast and not row["_has_coastal_keyword"]:
            reasons.append("像素颜色判断疑似落入海域；")
        if row["suspect_offshore"] and (is_northern_coast or row["_has_coastal_keyword"]):
            reasons.append("像素颜色判断疑似落入海域，但位于连云港沿海区县/北部海岸带，需人工核验；")

        if not reasons:
            return "ok", ""
        # 沿海关键词 / 北部海岸 / LYG 下辖区县 → coastal_review
        if (row["_has_coastal_keyword"] or is_northern_coast or row["_lyg_county"]) and row["suspect_offshore"]:
            return "coastal_review", "".join(reasons)
        if row["suspect_name_region_mismatch"]:
            return "exclude_from_ppt", "".join(reasons)
        if row["suspect_outside_city"]:
            return "exclude_from_ppt", "".join(reasons)
        if row["suspect_offshore"]:
            return "exclude_from_ppt", "".join(reasons)
        if row["suspect_lonlat"]:
            return "exclude_from_ppt", "".join(reasons)
        return "exclude_from_ppt", "".join(reasons)

    audit = stations.apply(resolve_audit_status, axis=1, result_type="expand")
    stations["audit_status"] = audit[0]
    stations["audit_reason"] = audit[1]

    return stations


def apply_manual_review_rules(df: pd.DataFrame) -> pd.DataFrame:
    mask = (
        df["station_id"].astype(str).isin(MANUAL_REVIEW_SITE_IDS)
        | df["station_name"].astype(str).apply(
            lambda x: any(k in x for k in MANUAL_REVIEW_KEYWORDS)
        )
    )
    df = df.copy()
    df.loc[mask, "audit_status"] = "manual_review"
    df.loc[mask, "audit_reason"] = (
        df.loc[mask, "audit_reason"]
        .fillna("")
        .astype(str)
        + "人工指定复核：当前底图展示位置存在海上或市界外观争议；"
    )
    return df


# ─────────────────────────────────────────────
# 绘图工具
# ─────────────────────────────────────────────

def prepare_base(ppt_style: bool = False) -> Image.Image:
    base = Image.open(MAP_PATH).convert("RGB")
    if ppt_style:
        base = base.resize(
            (2400, int(base.height * 2400 / base.width)), Image.Resampling.LANCZOS
        )
        base = ImageEnhance.Color(base).enhance(0.78)
        base = ImageEnhance.Contrast(base).enhance(0.95)
        base = ImageEnhance.Brightness(base).enhance(1.10)
        veil = Image.new("RGB", base.size, (255, 255, 255))
        base = Image.blend(base, veil, 0.18)
    else:
        base = base.resize(
            (2200, int(base.height * 2200 / base.width)), Image.Resampling.LANCZOS
        )
        base = ImageEnhance.Sharpness(base).enhance(1.4)
    return base


def draw_legend(draw: ImageDraw.ImageDraw, x: int, y: int, box_w: int, box_h: int,
                show_all: bool = False):
    bx0, by0 = x, y
    bx1, by1 = x + box_w, y + box_h
    draw.rounded_rectangle((bx0, by0, bx1, by1), radius=14, fill=(255, 255, 255, 235), outline=(160, 180, 190), width=2)
    draw.text((x + 22, y + 18), "图例", font=FONT_LABEL, fill=(30, 55, 75))

    if show_all:
        # 核查版图例：5 项（集中式 / 分布式 / 沿海待核验 / 人工复核 / 剔除）
        row_h = 36
        items = [
            ("#E74C3C", "white",   2, "集中式光伏站点",   None),
            ("#1F77B4", "white",   2, "分布式光伏站点",   None),
            ("#1F77B4", "#FF8C00", 3, "沿海待核验站点",   None),
            ("#1F77B4", "#8E44AD", 3, "人工复核站点",     None),
            (None,      "#888888", 3, "剔除站点",         "x"),
        ]
        for i, (fill_c, outline_c, width_c, label, symbol) in enumerate(items):
            iy = y + 56 + i * row_h
            if symbol == "x":
                # X 形叉号
                draw.line([(x + 28, iy), (x + 50, iy + 22)], fill=outline_c, width=3)
                draw.line([(x + 50, iy), (x + 28, iy + 22)], fill=outline_c, width=3)
            else:
                draw.ellipse((x + 28, iy, x + 50, iy + 22), fill=fill_c, outline=outline_c, width=width_c)
            draw.text((x + 66, iy + 2), label, font=FONT_SMALL, fill=(35, 35, 35))
    else:
        # 正式 PPT 图例：2 项
        draw.ellipse((x + 28, y + 58, x + 50, y + 80), fill="#E74C3C", outline="white", width=2)
        draw.text((x + 66, y + 54), "集中式光伏站点", font=FONT_SMALL, fill=(35, 35, 35))
        draw.ellipse((x + 28, y + 99, x + 50, y + 121), fill="#1F77B4", outline="white", width=2)
        draw.text((x + 66, y + 95), "分布式光伏站点", font=FONT_SMALL, fill=(35, 35, 35))


def draw_title(draw: ImageDraw.ImageDraw, width: int):
    draw.rounded_rectangle((36, 28, 720, 105), radius=16, fill=(255, 255, 255, 230), outline=(100, 145, 170), width=2)
    draw.text((62, 45), "连云港光伏站点空间分布图", font=FONT_TITLE, fill=(20, 60, 90))


def draw_station_dot(draw: ImageDraw.ImageDraw, x: float, y: float,
                     color: str, radius: float, outline_color: str = "white",
                     outline_width: int = 3, orange_ring: bool = False):
    x1 = x - radius
    y1 = y - radius
    x2 = x + radius
    y2 = y + radius
    draw.ellipse((x1, y1, x2, y2), fill=color, outline=outline_color, width=outline_width)
    if orange_ring:
        draw.ellipse((x1 - 4, y1 - 4, x2 + 4, y2 + 4), fill=None, outline="#FF8C00", width=3)


def draw_x_mark(draw: ImageDraw.ImageDraw, x: float, y: float, size: float = 10):
    color = (120, 120, 120)
    draw.line([(x - size, y - size), (x + size, y + size)], fill=color, width=3)
    draw.line([(x - size, y + size), (x + size, y - size)], fill=color, width=3)


def label_station(draw: ImageDraw.ImageDraw, x: float, y: float, name: str,
                  fill: str = (20, 45, 65), font=None):
    if font is None:
        font = FONT_SMALL
    draw.text((x + 12, y - 12), name[:12], font=font, fill=fill, stroke_width=3, stroke_fill="white")


def get_radius(capacity_mw: float, cap_median: float, cap_p95: float) -> float:
    cap = capacity_mw if pd.notna(capacity_mw) else cap_median
    cap = cap if pd.notna(cap) else 1.0
    return 7 + 10 * (cap / max(cap_p95, 1))


# ─────────────────────────────────────────────
# 主绘图函数
# ─────────────────────────────────────────────

def draw_diamond(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float,
                 fill: str, outline: str, width: int = 3):
    points = [
        (cx, cy - size),
        (cx + size, cy),
        (cx, cy + size),
        (cx - size, cy),
    ]
    draw.polygon(points, fill=fill, outline=outline)
    draw.polygon(points, fill=None, outline=outline, width=width)


def get_inner_legend_position(inner_box: dict, legend_w: int, legend_h: int,
                               margin: int = 28, extra_y: int = 0) -> tuple[int, int]:
    """根据地图内框计算图例位置，始终落在黑框内部右下角。"""
    x = int(inner_box["x_max"] - legend_w - margin)
    y = int(inner_box["y_max"] - legend_h - margin - extra_y)
    return x, y


def draw_map(stations: pd.DataFrame, out_path: Path, ppt_style: bool = False,
             show_all: bool = False, title_suffix: str = ""):
    base = prepare_base(ppt_style)
    draw = ImageDraw.Draw(base, "RGBA")
    w, h = base.size

    cap_median = stations["capacity_mw"].median() if stations["capacity_mw"].notna().any() else 1.0
    cap_p95 = stations["capacity_mw"].quantile(0.95)
    cap_p95 = cap_p95 if pd.notna(cap_p95) and cap_p95 > 0 else 1.0

    plot_type_color = {"centralized": "#E74C3C", "distributed": "#1F77B4"}

    # ── 正式 PPT 图：只画 ok 站点 ──
    if ppt_style:
        for ptype in ["distributed", "centralized"]:
            part = stations[
                (stations["plot_type"] == ptype)
                & stations["in_map_inner_box"]
                & (stations["audit_status"] == "ok")
            ]
            for _, r in part.iterrows():
                x, y = float(r["plot_x"]), float(r["plot_y"])
                rad = get_radius(r["capacity_mw"], cap_median, cap_p95)
                draw.ellipse(
                    (x - rad, y - rad, x + rad, y + rad),
                    fill=plot_type_color[ptype], outline="white", width=3
                )

    # ── 核查图 / 完整版：区分四种状态 ──
    else:
        for ptype in ["distributed", "centralized"]:
            part = stations[
                (stations["plot_type"] == ptype)
                & stations["in_map_inner_box"]
                & stations["audit_status"].isin(PPT_ALLOWED_STATUS)
            ]
            for _, r in part.iterrows():
                x, y = float(r["plot_x"]), float(r["plot_y"])
                rad = get_radius(r["capacity_mw"], cap_median, cap_p95)
                draw.ellipse(
                    (x - rad, y - rad, x + rad, y + rad),
                    fill=plot_type_color[ptype], outline="white", width=3
                )

        for status, fill, outline_color, symbol, ring_color in [
            ("coastal_review", "#1F77B4", "#FF8C00", "dot", "#FF8C00"),
            ("manual_review",  "#1F77B4", "#8E44AD", "diamond", "#8E44AD"),
        ]:
            for ptype in ["distributed", "centralized"]:
                part = stations[
                    (stations["plot_type"] == ptype)
                    & stations["in_map_inner_box"]
                    & (stations["audit_status"] == status)
                ]
                for _, r in part.iterrows():
                    x, y = float(r["plot_x"]), float(r["plot_y"])
                    rad = get_radius(r["capacity_mw"], cap_median, cap_p95)
                    if symbol == "dot":
                        draw.ellipse(
                            (x - rad, y - rad, x + rad, y + rad),
                            fill=fill, outline=outline_color, width=3
                        )
                    elif symbol == "diamond":
                        draw_diamond(
                            draw, x, y, rad + 2,
                            fill=fill, outline=outline_color, width=3
                        )
                    name = str(r["station_name"])[:10]
                    draw.text(
                        (x + 12, y - 12), name,
                        font=FONT_SMALL, fill=ring_color, stroke_width=3, stroke_fill="white"
                    )

        # exclude_from_ppt：灰色叉号 + 名称
        excluded = stations[stations["audit_status"] == "exclude_from_ppt"]
        for _, r in excluded.iterrows():
            if r["in_map_inner_box"]:
                x, y = float(r["plot_x"]), float(r["plot_y"])
                draw.line([(x - 8, y - 8), (x + 8, y + 8)], fill="#888888", width=3)
                draw.line([(x - 8, y + 8), (x + 8, y - 8)], fill="#888888", width=3)
                draw.text(
                    (x + 12, y - 12), str(r["station_name"])[:10],
                    font=FONT_SMALL, fill=(90, 90, 90), stroke_width=3, stroke_fill="white"
                )

    # ── 标题 ──
    title_text = "连云港光伏站点空间分布图"
    if title_suffix:
        title_text += f"  [{title_suffix}]"
    draw.rounded_rectangle((36, 28, 760, 105), radius=16, fill=(255, 255, 255, 230), outline=(100, 145, 170), width=2)
    draw.text((62, 45), title_text, font=FONT_TITLE, fill=(20, 60, 90))

    # ── 图例：基于缩放后的内框坐标，放在黑框内部右下角 ──
    # 内框按图片 resize 比例缩放（底图原始 2500，PPT 2400，核查/完整版 2200）
    scale = w / 2500.0
    scaled_box = {
        k: int(v * scale) for k, v in MAP_INNER_BOX.items()
    }

    if ppt_style:
        # 正式 PPT 图例：2 项，宽 370，高 150
        legend_w, legend_h = 370, 150
        margin, extra_y = 28, 0
        lx, ly = get_inner_legend_position(scaled_box, legend_w, legend_h, margin, extra_y)
        # 断言：图例必须在黑框内（左边界、右边界、底边界均不超出）
        assert lx >= scaled_box["x_min"], f"图例左侧 x={lx} 超出内框左边界 {scaled_box['x_min']}"
        assert scaled_box["y_min"] <= ly <= scaled_box["y_max"], f"图例 y={ly} 超出内框 {scaled_box['y_min']}~{scaled_box['y_max']}"
        assert lx + legend_w <= scaled_box["x_max"], f"图例右侧 {lx+legend_w} 超出内框右边界 {scaled_box['x_max']}"
        assert ly + legend_h <= scaled_box["y_max"], f"图例底部 {ly+legend_h} 超出内框底部 {scaled_box['y_max']}"
        draw_legend(draw, lx, ly, legend_w, legend_h, show_all=False)
    else:
        # 核查图例：5 项，宽 400，高 250，略高一些避免遮挡底部标注
        legend_w, legend_h = 400, 250
        margin, extra_y = 28, 50
        lx, ly = get_inner_legend_position(scaled_box, legend_w, legend_h, margin, extra_y)
        assert scaled_box["x_min"] <= lx <= scaled_box["x_max"], f"图例 x={lx} 超出内框"
        assert scaled_box["y_min"] <= ly <= scaled_box["y_max"], f"图例 y={ly} 超出内框"
        assert lx + legend_w <= scaled_box["x_max"], "图例右侧超出内框"
        assert ly + legend_h <= scaled_box["y_max"], "图例底部超出内框"
        draw_legend(draw, lx, ly, legend_w, legend_h, show_all=True)

    base.save(out_path)
    print(f"[OK] saved: {out_path}")


# ─────────────────────────────────────────────
# 主程序
# ─────────────────────────────────────────────

def main():
    if not MAP_PATH.exists():
        raise FileNotFoundError(f"底图不存在：{MAP_PATH}")

    print("[INFO] 加载站点数据...")
    stations = find_station_table()
    stations["plot_type"] = stations.apply(classify_type, axis=1)
    print(f"[INFO] 共加载 {len(stations)} 个有效站点")

    print("[INFO] 读取底图进行海上点判断...")
    img_raw = Image.open(MAP_PATH).convert("RGB")
    img_for_check = img_raw.resize(
        (2200, int(img_raw.height * 2200 / img_raw.width)), Image.Resampling.LANCZOS
    )

    print("[INFO] 执行空间核查...")
    stations = audit_stations(stations, img_for_check)

    print("[INFO] 应用人工复核规则...")
    stations = apply_manual_review_rules(stations)

    audit_df = stations[[
        "station_id", "station_name", "plot_type", "capacity_mw", "county",
        "longitude", "latitude", "plot_x", "plot_y",
        "in_map_inner_box", "in_lianyungang_bbox",
        "suspect_lonlat", "suspect_outside_city", "suspect_offshore",
        "suspect_name_region_mismatch", "_lyg_county",
        "audit_status", "audit_reason",
        "_source_file",
    ]].copy()
    audit_df.to_csv(OUT_AUDIT_CSV, index=False, encoding="utf-8-sig")
    print(f"[OK] audit CSV: {OUT_AUDIT_CSV}")

    # 输出：所有非 ok 状态的站点都进入 outliers.csv
    non_ok = stations[stations["audit_status"] != "ok"].copy()
    if len(non_ok) > 0:
        non_ok[[
            "station_id", "station_name", "plot_type", "capacity_mw", "county",
            "longitude", "latitude", "plot_x", "plot_y",
            "audit_status", "audit_reason",
            "_source_file",
        ]].to_csv(OUT_OUTLIERS_CSV, index=False, encoding="utf-8-sig")
        print(f"[OK] outliers CSV: {OUT_OUTLIERS_CSV}  ({len(non_ok)} stations)")
    elif OUT_OUTLIERS_CSV.exists():
        OUT_OUTLIERS_CSV.unlink()

    # 统计
    total = len(stations)
    ok_count = (stations["audit_status"] == "ok").sum()
    coastal_count = (stations["audit_status"] == "coastal_review").sum()
    manual_count = (stations["audit_status"] == "manual_review").sum()
    excluded = (stations["audit_status"] == "exclude_from_ppt").sum()
    outside_bbox = stations["suspect_outside_city"].sum()
    offshore = stations["suspect_offshore"].sum()
    name_mismatch = stations["suspect_name_region_mismatch"].sum()

    print()
    print("=" * 50)
    print(f"[OK] total stations:         {total}")
    print(f"[OK] valid for ppt (ok):    {ok_count}")
    print(f"[WARN] coastal review:        {coastal_count}")
    print(f"[WARN] manual review:         {manual_count}")
    print(f"[WARN] excluded from ppt:   {excluded}")
    print(f"[WARN] outside bbox:         {outside_bbox}")
    print(f"[WARN] probable offshore:     {offshore}")
    print(f"[WARN] name-region mismatch: {name_mismatch}")
    print("=" * 50)
    print()

    if len(non_ok) > 0:
        print("非 ok 站点清单（前 20 行）：")
        print(
            non_ok[["station_id", "station_name", "longitude", "latitude", "audit_status", "audit_reason"]]
            .head(20)
            .to_string(index=False)
        )
        print()

    # 输出图
    print("[INFO] 生成正式 PPT 图...")
    draw_map(stations, OUT_PPT_IMG, ppt_style=True, show_all=False)

    print("[INFO] 生成核查图...")
    draw_map(stations, OUT_AUDIT_IMG, ppt_style=False, show_all=True, title_suffix="核查版")

    print()
    print("[DONE] 所有输出：")
    for p in [OUT_AUDIT_CSV, OUT_OUTLIERS_CSV, OUT_PPT_IMG, OUT_AUDIT_IMG, OUT_FULL_IMG]:
        print(f"  {p}")


if __name__ == "__main__":
    main()
