"""
生成全市光伏出力波动曲线（完整版 + PPT 代表窗口版）。

输出路径：
  output/pv_pipeline/figures/city_pv_power_fluctuation_curve.png
  output/pv_pipeline/figures/city_pv_power_fluctuation_curve_ppt.png
"""
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CANDIDATE_FILES = [
    PROJECT_ROOT / "output/pv_pipeline/tables/distributed_predictions_final_eval.pkl",
    PROJECT_ROOT / "output/pv_pipeline/tables/distributed_predictions_final_full.pkl",
    PROJECT_ROOT / "output/pv_pipeline/tables/best_predictions_eval.pkl",
    PROJECT_ROOT / "output/pv_pipeline/distributed_predictions_final_eval.pkl",
]

TIME_COLS  = ["time", "timestamp", "datetime", "date_time", "ds"]
STATION_COLS = ["site_id", "station_id", "id"]
ACTUAL_COLS  = ["power_mw", "actual_mw", "y_true", "actual_power_mw"]
PRED_COLS    = ["power_pred", "power_pred_final", "pred_mw", "y_pred"]
SPLIT_COLS   = ["split", "dataset"]

def load_data():
    for fp in CANDIDATE_FILES:
        if not fp.exists():
            continue
        try:
            df = pd.read_pickle(fp)
            print(f"读取成功：{fp}  shape={df.shape}")
            return df
        except Exception as e:
            print(f"读取失败 {fp}: {e}")
    raise FileNotFoundError("未找到任何候选数据文件")

def detect_col(df, candidates, name):
    for c in candidates:
        if c in df.columns:
            print(f"  {name} 列: {c}")
            return c
    raise ValueError(f"未找到 {name} 列，候选：{candidates}")

print("=== 加载数据 ===")
df = load_data()

time_col    = detect_col(df, TIME_COLS, "时间")
station_col = detect_col(df, STATION_COLS, "站点")
actual_col  = detect_col(df, ACTUAL_COLS, "实际功率")
pred_col    = detect_col(df, PRED_COLS, "预测功率")
split_col   = detect_col(df, SPLIT_COLS, "数据集划分")

has_pred = pred_col in df.columns and df[pred_col].notna().any()

# 转换时间
df[time_col] = pd.to_datetime(df[time_col])

# 只保留 6-19 点
df = df[df[time_col].dt.hour.between(6, 19)].copy()

# 只保留测试集
if split_col in df.columns:
    test_df = df[df[split_col].astype(str).str.lower().eq("test")].copy()
else:
    test_df = df.copy()

print(f"测试集行数: {len(test_df)}")

# 全市聚合
city = (
    test_df
    .groupby(time_col, as_index=False)
    .agg(
        actual_mw=(actual_col, "sum"),
        pred_mw=(pred_col, "sum") if has_pred else (actual_col, "sum"),
        station_count=(station_col, "nunique"),
    )
)
city = city.sort_values(time_col).reset_index(drop=True)
city["date"] = city[time_col].dt.date

print(f"聚合后全市记录: {len(city)}")
print(f"时间范围: {city[time_col].min()} ~ {city[time_col].max()}")

# ============================================================
# 图 1：完整测试期曲线
# ============================================================
print("\n=== 绘制完整版 ===")
plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei", "Noto Sans CJK SC", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

fig, ax = plt.subplots(figsize=(16, 6), facecolor="white")
ax.set_facecolor("#fafafa")

ax.plot(city[time_col], city["actual_mw"],
        color="#1565C0", linewidth=0.9, label="真实功率", alpha=0.9)
if has_pred:
    ax.plot(city[time_col], city["pred_mw"],
            color="#E65100", linewidth=0.9, label="预测功率", alpha=0.8)

ax.set_xlabel("时间", fontsize=13)
ax.set_ylabel("全市功率 (MW)", fontsize=13)
ax.set_title("连云港全市光伏出力波动曲线", fontsize=16, fontweight="bold", pad=12)
ax.legend(fontsize=12, loc="upper right")
ax.grid(True, color="#e0e0e0", linestyle="--", linewidth=0.6)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
plt.xticks(rotation=30, fontsize=9)
ax.tick_params(axis="y", labelsize=10)

plt.tight_layout()
out_full = OUT_DIR / "city_pv_power_fluctuation_curve.png"
fig.savefig(out_full, dpi=220, bbox_inches="tight")
plt.close(fig)
print(f"已保存：{out_full}")

# ============================================================
# 图 2：PPT 代表窗口（选接近中位日总电量的一周）
# ============================================================
print("\n=== 绘制 PPT 版 ===")

daily = city.groupby("date")["actual_mw"].sum().reset_index(name="daily_energy")
median_energy = daily["daily_energy"].median()
daily["dist"] = (daily["daily_energy"] - median_energy).abs()
# 取最接近中位数的那一天作为窗口中心，取前后 7 天
best_date = pd.to_datetime(daily.sort_values("dist").iloc[0]["date"])
start_dt = best_date - pd.Timedelta(days=7)
end_dt   = best_date + pd.Timedelta(days=7)

ppt_city = city[(city[time_col] >= start_dt) & (city[time_col] < end_dt)].copy()
print(f"PPT 窗口：{start_dt.date()} ~ {end_dt.date()}  共 {len(ppt_city)} 条记录")

fig2, ax2 = plt.subplots(figsize=(14, 6.5), facecolor="white")
ax2.set_facecolor("#fafafa")

ax2.plot(ppt_city[time_col], ppt_city["actual_mw"],
         color="#1565C0", linewidth=2.2, label="真实功率", alpha=0.95)
if has_pred:
    ax2.plot(ppt_city[time_col], ppt_city["pred_mw"],
             color="#E65100", linewidth=2.0, label="预测功率", alpha=0.85)

ax2.set_xlabel("时间", fontsize=14)
ax2.set_ylabel("全市功率 (MW)", fontsize=14)
ax2.set_title("连云港全市光伏出力波动曲线（代表性时段）", fontsize=17, fontweight="bold", pad=14)
ax2.legend(fontsize=13, loc="upper right")
ax2.grid(True, color="#e0e0e0", linestyle="--", linewidth=0.7)
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
ax2.xaxis.set_major_locator(mdates.DayLocator())
plt.xticks(rotation=30, fontsize=11)
ax2.tick_params(axis="y", labelsize=11)

# 标注文字
ann_texts = [
    (0.02, 0.90, "日内峰谷明显", "black"),
    (0.02, 0.78, "天气扰动导致峰值波动", "black"),
    (0.02, 0.66, "逐小时预测需刻画时间规律与气象变化", "black"),
]
for x_frac, y_frac, txt, clr in ann_texts:
    ax2.annotate(txt, xy=(x_frac, y_frac), xycoords="axes fraction",
                 fontsize=12, color=clr,
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow",
                           edgecolor="#ccc", alpha=0.8))

plt.tight_layout()
out_ppt = OUT_DIR / "city_pv_power_fluctuation_curve_ppt.png"
fig2.savefig(out_ppt, dpi=220, bbox_inches="tight")
plt.close(fig2)
print(f"已保存：{out_ppt}")

print("\n全部完成。")
