#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import sys
import os

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import font_manager

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pv_forecasting.core.runtime import build_parser, make_paths

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
        if os.path.exists(fp):
            selected = fp
            break
    matplotlib.rcParams["axes.unicode_minus"] = False
    if selected is None:
        matplotlib.rcParams["font.family"] = "sans-serif"
        matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]
        print('[WARN] 未找到系统中文字体文件，将退回默认字体。')
        return
    font_manager.fontManager.addfont(selected)
    prop = font_manager.FontProperties(fname=selected)
    CH_FONT = prop
    name = prop.get_name()
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = [name]
    matplotlib.rcParams["font.serif"] = [name]
    print(f'[INFO] 已强制加载中文字体: {name}')
    print(f'[INFO] 字体文件路径: {selected}')

def apply_tick_font(ax):
    if CH_FONT is None:
        return
    for tick in ax.get_xticklabels():
        tick.set_fontproperties(CH_FONT)
    for tick in ax.get_yticklabels():
        tick.set_fontproperties(CH_FONT)
    if ax.title:
        ax.title.set_fontproperties(CH_FONT)
    if ax.xaxis.label:
        ax.xaxis.label.set_fontproperties(CH_FONT)
    if ax.yaxis.label:
        ax.yaxis.label.set_fontproperties(CH_FONT)

def savefig(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches='tight')
    plt.close(fig)

def barh_plot(df: pd.DataFrame, label_col: str, value_col: str, title: str, xlabel: str, out_path: Path, top_n: int = 15):
    d = df.head(top_n).copy()
    if d.empty:
        return
    labels = d[label_col].astype(str).tolist()
    vals = pd.to_numeric(d[value_col], errors='coerce').fillna(0).to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(10, max(4.5, 0.42 * len(d) + 1.8)))
    ax.barh(range(len(d)), vals)
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.grid(True, axis='x', linestyle='--', alpha=0.35)
    apply_tick_font(ax)
    savefig(fig, out_path)

def plot_city_worst_day(pred_df: pd.DataFrame, out_path: Path):
    d = pred_df.copy()
    d['time'] = pd.to_datetime(d['time'])
    d['date'] = d['time'].dt.date
    d['hour'] = d['time'].dt.hour + d['time'].dt.minute / 60.0
    city = d.groupby(['date', 'hour'], as_index=False)[['power_mw', 'power_pred']].sum()
    city['abs_err'] = (city['power_mw'] - city['power_pred']).abs()
    daily = city.groupby('date', as_index=False)['abs_err'].mean().sort_values('abs_err', ascending=False)
    if daily.empty:
        return
    worst_date = daily.iloc[0]['date']
    g = city[city['date'] == worst_date].copy()
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(g['hour'], g['power_mw'], label='真实总出力')
    ax.plot(g['hour'], g['power_pred'], label='预测总出力')
    ax.set_title(f'全市总量误差最大日: {worst_date}')
    ax.set_xlabel('小时')
    ax.set_ylabel('MW')
    ax.grid(True, linestyle='--', alpha=0.35)
    leg = ax.legend(prop=CH_FONT) if CH_FONT is not None else ax.legend()
    apply_tick_font(ax)
    savefig(fig, out_path)

def plot_wakeup_sites(pred_df: pd.DataFrame, out_path: Path):
    if 'wakeup_applied' not in pred_df.columns:
        return
    d = pred_df[pred_df['wakeup_applied'].fillna(False)].copy()
    if d.empty:
        return
    grp = d.groupby('site_id', as_index=False).agg(
        wakeup_rows=('wakeup_applied', 'sum'),
        county=('county', 'first') if 'county' in d.columns else ('site_id', 'first')
    ).sort_values('wakeup_rows', ascending=False)
    grp['label'] = grp['site_id'].astype(str) + ' | ' + grp['county'].astype(str)
    barh_plot(grp, 'label', 'wakeup_rows', '白天唤醒后处理触发最多站点', '触发次数', out_path, top_n=20)

def main():
    setup_chinese_font()
    parser = build_parser('生成瓶颈诊断图')
    args = parser.parse_args()
    paths = make_paths(PROJECT_ROOT, args)
    diag_dir = paths.figures / 'diagnostics'
    diag_dir.mkdir(parents=True, exist_ok=True)

    pred_df = pd.read_pickle(paths.tables / 'distributed_predictions.pkl')
    by_site_path = paths.metrics / 'distributed_metrics_by_site.csv'
    by_county_path = paths.metrics / 'distributed_metrics_by_county.csv'
    by_scene_path = paths.metrics / 'distributed_metrics_by_scene.csv'
    zero_path = paths.metrics / 'top_day_zero_sites.csv'

    by_site = pd.read_csv(by_site_path) if by_site_path.exists() else pd.DataFrame()
    by_county = pd.read_csv(by_county_path) if by_county_path.exists() else pd.DataFrame()
    by_scene = pd.read_csv(by_scene_path) if by_scene_path.exists() else pd.DataFrame()
    zero_df = pd.read_csv(zero_path) if zero_path.exists() else pd.DataFrame()

    if not by_site.empty:
        by_site = by_site.copy()
        name_col = 'site_short_name' if 'site_short_name' in by_site.columns else 'site_id'
        by_site['label'] = by_site[name_col].fillna(by_site['site_id']).astype(str)
        barh_plot(by_site.sort_values('rmse', ascending=False), 'label', 'rmse', '最差站点 RMSE', 'RMSE', diag_dir / '01_top_site_rmse.png')
        if 'nrmse_cap' in by_site.columns:
            barh_plot(by_site.sort_values('nrmse_cap', ascending=False), 'label', 'nrmse_cap', '最差站点容量归一化 RMSE', 'NRMSE(cap)', diag_dir / '02_top_site_nrmse_cap.png')

    if not by_county.empty:
        barh_plot(by_county.sort_values('rmse', ascending=False), 'county', 'rmse', '县区聚合误差', 'RMSE', diag_dir / '03_county_rmse.png', top_n=20)

    if not zero_df.empty:
        name_col = 'site_short_name' if 'site_short_name' in zero_df.columns else 'site_id'
        zero_df = zero_df.copy()
        zero_df['label'] = zero_df[name_col].fillna(zero_df['site_id']).astype(str)
        barh_plot(zero_df.sort_values(['day_zero_run_rate', 'day_zero_rate'], ascending=False), 'label', 'day_zero_run_rate', '白天持续零值最严重站点', '持续零值比例', diag_dir / '04_top_dayzero_sites.png')

    if not by_scene.empty:
        barh_plot(by_scene.sort_values('rmse', ascending=False), 'scene_label', 'rmse', '场景分组误差', 'RMSE', diag_dir / '05_scene_rmse.png', top_n=20)

    plot_city_worst_day(pred_df, diag_dir / '06_city_worst_day_curve.png')
    plot_wakeup_sites(pred_df, diag_dir / '07_wakeup_sites.png')
    print(f'[OK] 诊断图已输出到: {diag_dir}')

if __name__ == '__main__':
    main()
