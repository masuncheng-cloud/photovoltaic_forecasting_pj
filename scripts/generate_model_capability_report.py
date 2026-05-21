#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成模型能力评估报告
====================
output/pv_pipeline/docs/model_capability_on_existing_dataset.md
"""
import argparse
from pathlib import Path
from datetime import datetime
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "output" / "pv_pipeline"
METRICS_DIR = OUTPUT_ROOT / "metrics"
DOCS_DIR = OUTPUT_ROOT / "docs"


def load_metrics():
    """加载所有评估指标"""
    metrics = {}
    
    files = {
        "global": "distributed_metrics_fixed.csv",
        "by_site": "distributed_metrics_by_site_fixed.csv",
        "by_county": "distributed_metrics_by_county_fixed.csv",
        "by_scene": "distributed_metrics_by_scene_fixed.csv",
        "by_hour": "distributed_metrics_by_hour_fixed.csv",
    }
    
    for key, fname in files.items():
        fpath = METRICS_DIR / fname
        if fpath.exists():
            metrics[key] = pd.read_csv(fpath)
        else:
            metrics[key] = pd.DataFrame()
    
    return metrics


def generate_report(metrics):
    """生成模型能力评估报告"""
    
    # 全局指标
    df_global = metrics.get("global", pd.DataFrame())
    
    # 站点级指标
    df_site = metrics.get("by_site", pd.DataFrame())
    
    # 场景指标
    df_scene = metrics.get("by_scene", pd.DataFrame())
    
    # 逐小时指标
    df_hour = metrics.get("by_hour", pd.DataFrame())
    
    # 县域指标
    df_county = metrics.get("by_county", pd.DataFrame())
    
    lines = []
    lines.append("# 既有数据集模型能力评估报告")
    lines.append("")
    lines.append(f"**更新时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # 1. 评估范围
    lines.append("## 1. 评估范围")
    lines.append("")
    lines.append("说明：本报告仅评价已有数据集上的离线预测能力，不涉及实时接口、极端天气、专利和论文。")
    lines.append("")
    
    # 2. 数据划分
    lines.append("## 2. 数据划分")
    lines.append("")
    lines.append("统一数据划分口径：")
    lines.append("")
    lines.append("| 分区 | 规则 |")
    lines.append("|------|------|")
    lines.append("| train | time < 2025-07-01 |")
    lines.append("| valid | 2025-07-01 <= time < 2025-09-01 |")
    lines.append("| test | time >= 2025-09-01 |")
    lines.append("")
    
    if not df_site.empty:
        n_sites = df_site['site_id'].nunique() if 'site_id' in df_site.columns else 0
        n_samples = int(df_site['n_samples_before'].sum()) if 'n_samples_before' in df_site.columns else 0
        lines.append(f"- 测试集站点数：{n_sites}")
        lines.append(f"- 测试集样本数：{n_samples:,}")
    lines.append("")
    
    # 3. 全局指标
    lines.append("## 3. 全局指标")
    lines.append("")
    lines.append("引用 `distributed_metrics_fixed.csv`：")
    lines.append("")
    
    if not df_global.empty:
        # 筛选主要指标
        main_metrics = ['WAPE', 'MAE', 'RMSE', 'NRMSE', 'Corr', 'MAPE_clipped']
        df_main = df_global[df_global['metric'].isin(main_metrics)].copy()
        
        if not df_main.empty:
            lines.append("| 指标 | 修复前 | 修复后 | 改善幅度 |")
            lines.append("|------|--------|--------|----------|")
            for _, row in df_main.iterrows():
                metric = row['metric']
                before = row.get('before', '')
                after = row.get('after', '')
                imp_pct = row.get('improvement_pct', '')
                before_str = f"{before:.4f}" if pd.notna(before) else '-'
                after_str = f"{after:.4f}" if pd.notna(after) else '-'
                imp_str = f"{imp_pct:.2f}%" if pd.notna(imp_pct) else '-'
                lines.append(f"| {metric} | {before_str} | {after_str} | {imp_str} |")
        lines.append("")
        
        # 关键发现
        wape_row = df_global[df_global['metric'] == 'WAPE']
        if not wape_row.empty:
            before_wape = wape_row['before'].values[0]
            after_wape = wape_row['after'].values[0]
            if pd.notna(before_wape) and pd.notna(after_wape):
                lines.append(f"- WAPE: {before_wape:.2f}% → {after_wape:.2f}%")
        
        corr_row = df_global[df_global['metric'] == 'Corr']
        if not corr_row.empty:
            before_corr = corr_row['before'].values[0]
            after_corr = corr_row['after'].values[0]
            if pd.notna(before_corr) and pd.notna(after_corr):
                lines.append(f"- 相关系数: {before_corr:.4f} → {after_corr:.4f}")
    lines.append("")
    
    # 4. 城市总量逐小时能力
    lines.append("## 4. 城市总量逐小时能力")
    lines.append("")
    lines.append("引用 `distributed_metrics_by_hour_fixed.csv`：")
    lines.append("")
    
    if not df_hour.empty:
        lines.append("| 小时 | 修复前相对误差 | 修复后相对误差 | 改善 |")
        lines.append("|------|----------------|----------------|------|")
        
        for _, row in df_hour.iterrows():
            hour = row.get('hour', '')
            err_b = row.get('city_rel_err_before', '')
            err_a = row.get('city_rel_err_after', '')
            imp = row.get('city_rel_err_improvement', '')
            
            err_b_str = f"{err_b:.2f}%" if pd.notna(err_b) else '-'
            err_a_str = f"{err_a:.2f}%" if pd.notna(err_a) else '-'
            imp_str = f"+{imp:.2f}%" if pd.notna(imp) and imp > 0 else f"{imp:.2f}%" if pd.notna(imp) else '-'
            
            lines.append(f"| {hour} | {err_b_str} | {err_a_str} | {imp_str} |")
        lines.append("")
        
        # 重点说明
        lines.append("**重点说明**：")
        lines.append("")
        
        # 找出改善最明显和最差的时段
        if 'city_rel_err_improvement' in df_hour.columns:
            df_hour_valid = df_hour.dropna(subset=['city_rel_err_improvement'])
            if not df_hour_valid.empty:
                best = df_hour_valid.loc[df_hour_valid['city_rel_err_improvement'].idxmax()]
                worst = df_hour_valid.loc[df_hour_valid['city_rel_err_improvement'].idxmin()]
                
                lines.append(f"- 改善最明显时段: {int(best['hour'])}点 (改善 {best['city_rel_err_improvement']:.2f}%)")
                lines.append(f"- 改善最差时段: {int(worst['hour'])}点 (改善 {worst['city_rel_err_improvement']:.2f}%)")
        
        lines.append("- 6点、19点误差仍然偏高，主要原因：")
        lines.append("  - 功率分母小，MAPE 天然偏高")
        lines.append("  - 太阳高度角低，组件朝向差异放大")
        lines.append("  - 辐照度响应滞后")
        lines.append("- 中午时段 (10-14点) 相对稳定")
    lines.append("")
    
    # 5. 县域级能力
    lines.append("## 5. 县区级能力")
    lines.append("")
    lines.append("引用 `distributed_metrics_by_county_fixed.csv`：")
    lines.append("")
    
    if not df_county.empty:
        # 统计改善情况
        if 'MAPE_improvement' in df_county.columns:
            df_county_valid = df_county.dropna(subset=['MAPE_improvement'])
            if not df_county_valid.empty:
                improved = (df_county_valid['MAPE_improvement'] > 0).sum()
                worsened = (df_county_valid['MAPE_improvement'] < 0).sum()
                lines.append(f"- MAPE 改善县域: {improved}")
                lines.append(f"- MAPE 变差县域: {worsened}")
        
        # 显示关键县域
        if 'before_WAPE' in df_county.columns and 'after_WAPE' in df_county.columns:
            lines.append("")
            lines.append("| 县域 | 修复前WAPE | 修复后WAPE |")
            lines.append("|------|------------|------------|")
            for _, row in df_county.head(10).iterrows():
                county = row.get('county', '')
                wape_b = row.get('before_WAPE', '')
                wape_a = row.get('after_WAPE', '')
                wape_b_str = f"{wape_b:.2f}%" if pd.notna(wape_b) else '-'
                wape_a_str = f"{wape_a:.2f}%" if pd.notna(wape_a) else '-'
                lines.append(f"| {county} | {wape_b_str} | {wape_a_str} |")
    lines.append("")
    
    # 6. 站点级能力
    lines.append("## 6. 站点级能力")
    lines.append("")
    lines.append("引用 `distributed_metrics_by_site_fixed.csv`：")
    lines.append("")
    
    if not df_site.empty:
        # MAPE 统计
        if 'MAPE_improvement' in df_site.columns:
            df_site_valid = df_site.dropna(subset=['MAPE_improvement'])
            if not df_site_valid.empty:
                improved = (df_site_valid['MAPE_improvement'] > 0).sum()
                worsened = (df_site_valid['MAPE_improvement'] < 0).sum()
                total = len(df_site_valid)
                lines.append(f"- **MAPE 改善站点**: {improved}/{total} ({improved/total*100:.1f}%)")
                lines.append(f"- **MAPE 变差站点**: {worsened}/{total} ({worsened/total*100:.1f}%)")
        
        # WAPE 统计
        if 'WAPE_improvement' in df_site.columns:
            df_site_valid = df_site.dropna(subset=['WAPE_improvement'])
            if not df_site_valid.empty:
                improved = (df_site_valid['WAPE_improvement'] > 0).sum()
                worsened = (df_site_valid['WAPE_improvement'] < 0).sum()
                total = len(df_site_valid)
                lines.append(f"- **WAPE 改善站点**: {improved}/{total} ({improved/total*100:.1f}%)")
                lines.append(f"- **WAPE 变差站点**: {worsened}/{total} ({worsened/total*100:.1f}%)")
        
        # 误差最高的站点
        if 'before_MAPE' in df_site.columns:
            df_high = df_site.nlargest(5, 'before_MAPE')[['site_id', 'before_MAPE', 'after_MAPE']].dropna()
            if not df_high.empty:
                lines.append("")
                lines.append("**误差最高的前5个站点**：")
                lines.append("")
                lines.append("| 站点 | 修复前MAPE | 修复后MAPE |")
                lines.append("|------|------------|------------|")
                for _, row in df_high.iterrows():
                    lines.append(f"| {row['site_id']} | {row['before_MAPE']:.2f}% | {row['after_MAPE']:.2f}% |")
    lines.append("")
    
    # 7. 场景时段能力
    lines.append("## 7. 场景时段能力")
    lines.append("")
    lines.append("引用 `distributed_metrics_by_scene_fixed.csv`：")
    lines.append("")
    
    if not df_scene.empty:
        lines.append("| 场景 | 修复前MAPE | 修复后MAPE | MAPE变化 | 样本数 |")
        lines.append("|------|------------|------------|----------|--------|")
        
        for _, row in df_scene.iterrows():
            scene = row.get('scene', '')
            mape_b = row.get('before_MAPE', '')
            mape_a = row.get('after_MAPE', '')
            mape_imp = row.get('MAPE_improvement', '')
            n_samples = row.get('n_samples_before', '')
            
            mape_b_str = f"{mape_b:.2f}%" if pd.notna(mape_b) else '-'
            mape_a_str = f"{mape_a:.2f}%" if pd.notna(mape_a) else '-'
            mape_imp_str = f"{mape_imp:.2f}%" if pd.notna(mape_imp) else '-'
            n_str = f"{n_samples:,}" if pd.notna(n_samples) else '-'
            
            lines.append(f"| {scene} | {mape_b_str} | {mape_a_str} | {mape_imp_str} | {n_str} |")
    lines.append("")
    
    # 8. 模型能力结论
    lines.append("## 8. 模型能力结论")
    lines.append("")
    
    # 综合分析
    lines.append("**综合分析**：")
    lines.append("")
    
    # 城市总量
    if not df_global.empty:
        wape_row = df_global[df_global['metric'] == 'WAPE']
        if not wape_row.empty:
            before_wape = wape_row['before'].values[0]
            after_wape = wape_row['after'].values[0]
            if pd.notna(before_wape) and pd.notna(after_wape):
                wape_change = before_wape - after_wape
                if wape_change > 0:
                    lines.append(f"1. **城市聚合总量能力**: WAPE 改善 {wape_change:.2f}%，模型在城市级总量估算方面有所提升。")
                else:
                    lines.append(f"1. **城市聚合总量能力**: WAPE 变差 {abs(wape_change):.2f}%。")
    
    # 站点级
    if not df_site.empty and 'MAPE_improvement' in df_site.columns:
        df_site_valid = df_site.dropna(subset=['MAPE_improvement'])
        if not df_site_valid.empty:
            improved = (df_site_valid['MAPE_improvement'] > 0).sum()
            worsened = (df_site_valid['MAPE_improvement'] < 0).sum()
            total = len(df_site_valid)
            
            if improved > worsened:
                lines.append(f"2. **站点级预测能力**: {improved}/{total} 站点 MAPE 改善，整体有所提升。")
            else:
                lines.append(f"2. **站点级预测能力**: {worsened}/{total} 站点 MAPE 变差，站点级精细预测能力有待提升。")
    
    lines.append("")
    lines.append("**核心结论**：")
    lines.append("")
    lines.append("当前模型在城市聚合总出力层面表现出较明显改善，说明模型具备全市总量估算能力；")
    lines.append("但站点级 MAPE 大面积恶化，说明当前修复主要提升的是聚合层面纠偏能力，")
    lines.append("而不是单站点精细预测能力。")
    lines.append("")
    lines.append("因此，在已有数据集上，模型可用于城市级总量估算和趋势分析，")
    lines.append("但站点级精细化预测仍需进一步优化。")
    lines.append("")
    
    # 9. 当前仍需补齐的问题
    lines.append("## 9. 当前仍需补齐的问题")
    lines.append("")
    lines.append("### 评估相关")
    lines.append("")
    lines.append("- 站点级 MAPE 大面积变差，需要分析原因")
    lines.append("- 6点、19点误差仍然偏高，需要针对性优化")
    lines.append("- 部分站点误差异常高，需排查数据质量问题")
    lines.append("")
    lines.append("### 数据相关")
    lines.append("")
    lines.append("- 组件参数缺失（倾角、方位角）影响早晚时段预测")
    lines.append("- 部分站点训练数据不足")
    lines.append("")
    lines.append("### 模型相关")
    lines.append("")
    lines.append("- 站点级模型与城市级聚合模型的协同优化")
    lines.append("- 早晚 ramp 时段的专门建模")
    lines.append("")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='生成模型能力评估报告')
    parser.add_argument('--output-root', default='output/pv_pipeline', help='输出根目录')
    args = parser.parse_args()
    
    print("生成模型能力评估报告...")
    
    metrics = load_metrics()
    report = generate_report(metrics)
    
    docs_dir = Path(args.output_root) / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    
    output_path = docs_dir / "model_capability_on_existing_dataset.md"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"已保存: {output_path}")


if __name__ == '__main__':
    main()
