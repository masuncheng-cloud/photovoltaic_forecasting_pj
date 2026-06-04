"""
生成辐照缺失/数据来源示意图。

输出路径：output/pv_pipeline/figures/irradiance_missing_data_sources.png
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "irradiance_missing_data_sources.png"

FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]

def get_font(size):
    for fp in FONT_PATHS:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()

W, H = 2200, 1200
BG = (255, 255, 255)

img = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(img)

# 配色
COL_LEFT_BG    = (227, 242, 253)   # 浅蓝
COL_LEFT_BD    = (66, 165, 245)
COL_MID_BG     = (255, 235, 238)   # 浅红
COL_MID_BD     = (229, 57, 53)
COL_RIGHT_BG   = (232, 245, 233)   # 浅绿
COL_RIGHT_BD  = (67, 160, 71)
COL_ARROW      = (100, 100, 100)
COL_CONCL_BG   = (250, 250, 250)
COL_TITLE      = (30, 30, 30)
COL_SUBTITLE   = (80, 80, 80)

# 标题
font_title  = get_font(48)
font_header = get_font(32)
font_body   = get_font(26)
font_small  = get_font(22)
font_concl  = get_font(24)

title_text = "辐照缺失与数据来源分析"
draw.text((W // 2 - 300, 40), title_text, fill=COL_TITLE, font=font_title)

# --- 布局参数 ---
panel_y_top    = 160
panel_h        = 720
gap            = 80

left_w   = 620
mid_w    = 620
right_w  = 620

left_x   = 60
mid_x    = left_x + left_w + gap
right_x  = mid_x + mid_w + gap

# ===================== 左侧面板 =====================
def get_text_size(draw, text, font):
    """Get (width, height) of text using PIL's textlength / textbbox."""
    try:
        w = draw.textlength(text, font=font)
        bb = draw.textbbox((0, 0), text, font=font)
        h = bb[3] - bb[1]
        return w, h
    except AttributeError:
        return draw.textsize(text, font=font)

def draw_panel(draw, x, y, w, h, bg, bd, header, items, header_font, body_font):
    draw.rounded_rectangle([x, y, x + w, y + h], radius=16, fill=bg, outline=bd, width=3)
    cy = y + 30
    tw, th = get_text_size(draw, header, header_font)
    draw.text((x + (w - tw) // 2, cy), header, fill=(20, 20, 20), font=header_font)
    cy += th + 40
    for item in items:
        dot_x = x + 36
        dot_y = cy + 6
        draw.ellipse([dot_x - 5, dot_y - 5, dot_x + 5, dot_y + 5], fill=bd)
        tw, th2 = get_text_size(draw, item, body_font)
        draw.text((x + 56, cy), item, fill=(40, 40, 40), font=body_font)
        cy += th2 + 30

# 左侧：已有数据来源
left_items = [
    "集中式光伏功率记录",
    "ERA5 气象再分析数据",
    "分布式站点台账信息",
    "分布式功率实测记录",
]
draw_panel(draw, left_x, panel_y_top, left_w, panel_h,
           COL_LEFT_BG, COL_LEFT_BD, "已有数据来源", left_items,
           font_header, font_body)

# 中间：关键数据缺口
mid_items = [
    "多数分布式站点缺少实测辐照",
    "单点辐照无法代表全市空间差异",
    "站点容量、位置、运行状态各异",
]
draw_panel(draw, mid_x, panel_y_top, mid_w, panel_h,
           COL_MID_BG, COL_MID_BD, "关键数据缺口", mid_items,
           font_header, font_body)

# 右侧：建模补偿路径
right_items = [
    "集中式功率反演区域辐照",
    "辐照空间扩展至分布式站点",
    "站点功率响应建模",
    "全市/站点级逐小时评价",
]
draw_panel(draw, right_x, panel_y_top, right_w, panel_h,
           COL_RIGHT_BG, COL_RIGHT_BD, "建模补偿路径", right_items,
           font_header, font_body)

# ===================== 箭头 =====================
ay = panel_y_top + panel_h // 2

# 左 -> 中
ax1 = left_x + left_w
ax2 = mid_x
draw.line([(ax1, ay), (ax2, ay)], fill=COL_ARROW, width=4)
# 箭头头部
draw.polygon([(ax2, ay), (ax2 - 16, ay - 12), (ax2 - 16, ay + 12)], fill=COL_ARROW)

# 中 -> 右
bx1 = mid_x + mid_w
bx2 = right_x
draw.line([(bx1, ay), (bx2, ay)], fill=COL_ARROW, width=4)
draw.polygon([(bx2, ay), (bx2 - 16, ay - 12), (bx2 - 16, ay + 12)], fill=COL_ARROW)

# ===================== 底部结论条 =====================
conc_y = panel_y_top + panel_h + 40
conc_h  = 90
conc_x  = 60
conc_w  = W - 120

draw.rounded_rectangle([conc_x, conc_y, conc_x + conc_w, conc_y + conc_h],
                       radius=12, fill=(245, 245, 245), outline=(180, 180, 180), width=2)

conc_text = (
    "形成「已有功率与气象数据  →  区域辐照估计  →  分布式功率预测与评价」的数据补偿路径"
)
tw, th = get_text_size(draw, conc_text, font_concl)
draw.text(((W - tw) // 2, conc_y + (conc_h - th) // 2), conc_text,
          fill=(50, 50, 50), font=font_concl)

# ===================== 图例说明 =====================
legend_y = conc_y + conc_h + 30
legend_items = [
    (COL_LEFT_BG, COL_LEFT_BD, "已有数据"),
    (COL_MID_BG,  COL_MID_BD,  "数据缺口"),
    (COL_RIGHT_BG, COL_RIGHT_BD, "建模路径"),
]

lx = 200
for bg, bd, lbl in legend_items:
    draw.rounded_rectangle([lx, legend_y, lx + 30, legend_y + 30],
                          radius=6, fill=bg, outline=bd, width=2)
    tw, th = get_text_size(draw, lbl, font_small)
    draw.text((lx + 42, legend_y + 4), lbl, fill=COL_SUBTITLE, font=font_small)
    lx += tw + 90

# ===================== 保存 =====================
img.save(OUT_PATH, "PNG", dpi=(220, 220))
print(f"已保存：{OUT_PATH}")
