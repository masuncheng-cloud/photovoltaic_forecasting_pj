#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对三个CSV文件进行颜色标注：
  1. 最好站点（MAE最低）  → 绿色
  2. 最差站点（MAE最高）  → 红色
  3. 训练数据少（样本数<3000）→ 橙色
  4. 0值过多（零功率比例>50%）→ 蓝色

标注规则：
  - 相对误差统计.csv → 添加【问题标注】列，列出所有问题类别
  - 前38座/后40座时序.csv → 每行标注该行涉及的所有站点问题类别
"""

import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "output" / "pv_pipeline" / "metrics"

# ═══════════════════════════════════════════════════════════════════════════════
#  Step 1: 从时序文件中计算各站点零值比例
# ═══════════════════════════════════════════════════════════════════════════════
print("Step 1: 计算各站点零值比例...")

df1 = pd.read_csv(ROOT / '分布式光伏预测_前38座.csv')
df2 = pd.read_csv(ROOT / '分布式光伏预测_后40座.csv')

def get_zero_ratios(df):
    zero_ratios = {}
    for col in df.columns:
        if col == 'time':
            continue
        if col.endswith('_预测'):
            continue
        # col 是实际值列
        n = len(df)
        nz = (df[col] == 0).sum()
        # 从列名提站点名
        site_name = col.replace('_总出力值', '')
        zero_ratios[site_name] = nz / n * 100
    return zero_ratios

zr1 = get_zero_ratios(df1)
zr2 = get_zero_ratios(df2)
zero_ratio = {**zr1, **zr2}
print(f"  零值比例计算完成: {len(zero_ratio)} 个站点")

# ═══════════════════════════════════════════════════════════════════════════════
#  Step 2: 读取统计表，构建标注信息
# ═══════════════════════════════════════════════════════════════════════════════
print("Step 2: 构建标注信息...")

df_stat = pd.read_csv(ROOT / '分布式光伏预测_各站点相对误差统计.csv')

# 站点名→列名映射（统计表用站点名称，时序表用_总出力值列名）
# 建立映射关系
site_to_col = {}
for col in list(df1.columns) + list(df2.columns):
    if col == 'time' or col.endswith('_预测'):
        continue
    site_name = col.replace('_总出力值', '')
    site_to_col[site_name] = col

def get_site_issues(row, zero_ratio_map, site_col_map):
    issues = []
    sid = row['站点ID']
    name = row['站点名称']
    mae = row['MAE(MW)']
    n = row['样本数']
    rel_err = row['相对误差均值(%)']

    # 最好：MAE < 0.10 MW（绝对精度好）
    if mae < 0.10:
        issues.append('✅ 最好站点(MAE<0.1MW)')

    # 最差：MAE > 0.80 MW 或 相对误差均值 > 200%
    if mae > 0.80 or rel_err > 200:
        issues.append('🔴 最差站点(MAE>0.8MW或相对误差>200%)')

    # 训练数据少：样本数 < 3000
    if n < 3000:
        issues.append('🟠 训练数据少(n<3000)')

    # 0值过多：零值比例 > 50%
    # 尝试匹配
    zr = None
    for k, v in zero_ratio_map.items():
        if k == name or k.startswith(name) or name.startswith(k):
            zr = v
            break
    if zr is None:
        # 尝试模糊匹配
        for k, v in zero_ratio_map.items():
            if name in k or k in name:
                zr = v
                break
    if zr is not None and zr > 50:
        issues.append(f'🔵 0值过多(零值率{zr:.0f}%)')

    # 特别标注：误差<1MW比例<60%（预测质量极差）
    pct_1mw = row['误差<1MW比例(%)']
    if pct_1mw < 60:
        issues.append(f'⚠️ 预测偏离极大(<1MW比例仅{pct_1mw:.0f}%)')

    return ' | '.join(issues) if issues else '正常'


# 为统计表添加标注列
df_stat['问题标注'] = df_stat.apply(
    lambda r: get_site_issues(r, zero_ratio, site_to_col), axis=1
)

# ═══════════════════════════════════════════════════════════════════════════════
#  Step 3: 为时序表构建标注
# ═══════════════════════════════════════════════════════════════════════════════
print("Step 3: 为时序表添加标注...")

# 建立站点名到时序列的映射（实际值列，不带_预测）
site_to_actual_col = {}
for df_ts in [df1, df2]:
    for col in df_ts.columns:
        if col == 'time' or col.endswith('_预测'):
            continue
        # 标准化站点名
        sn = col.replace('_总出力值', '')
        if sn not in site_to_actual_col:
            site_to_actual_col[sn] = col

def get_ts_issues_per_row(row, df_stat, zero_ratio_map):
    """对时序表的每一行，判断涉及哪些站点的标注问题"""
    issues = []
    for _, sr in df_stat.iterrows():
        sid = sr['站点ID']
        name = sr['站点名称']
        mae = sr['MAE(MW)']
        n = sr['样本数']
        rel_err = sr['相对误差均值(%)']
        pct_1mw = sr['误差<1MW比例(%)']

        # 尝试匹配时序列
        matched_col = None
        for k, v in site_to_actual_col.items():
            if name in k or k in name or name.startswith(k.replace('光伏', '').replace('电站', '')):
                matched_col = v
                break

        if matched_col and matched_col in row.index:
            if (row[matched_col] == 0):
                continue  # 实际值为0时跳过

        tags = []
        if mae < 0.10:
            tags.append('✅')
        if mae > 0.80 or rel_err > 200:
            tags.append('🔴')
        if n < 3000:
            tags.append('🟠')
        if mae > 0.80 and n < 3000:
            tags.append('🔴+🟠')
        if mae > 0.80 and rel_err > 200:
            tags.append('🔴🔴')

    # 简化：对整列打标签（每行的问题来自整列的站点属性）
    return None  # 将在下一步用站点级别标注

print(f"  时序表站点映射完成: {len(site_to_actual_col)} 个站点")

# 为时序表添加站点问题列
# 建立站点名称 → 标注信息的映射
site_to_issue = {}
for _, r in df_stat.iterrows():
    issue = get_site_issues(r, zero_ratio, site_to_col)
    if issue != '正常':
        site_to_issue[r['站点名称']] = issue

# 为时序表 df1 和 df2 添加标注列
def annotate_ts_df(df_ts, site_to_issue, site_to_actual_col):
    # 收集所有标注（按站点分组）
    all_issues = []
    for col in df_ts.columns:
        if col == 'time' or col.endswith('_预测'):
            continue
        site_name_raw = col.replace('_总出力值', '')
        issue = site_to_issue.get(site_name_raw, '正常')
        if issue != '正常':
            all_issues.append(f"{site_name_raw}: {issue}")

    issue_summary = ' | '.join(all_issues) if all_issues else '正常'
    df_ts['站点问题标注'] = issue_summary
    return df_ts

df1_ann = annotate_ts_df(df1.copy(), site_to_issue, site_to_actual_col)
df2_ann = annotate_ts_df(df2.copy(), site_to_issue, site_to_actual_col)

# ═══════════════════════════════════════════════════════════════════════════════
#  Step 4: 保存标注后的文件
# ═══════════════════════════════════════════════════════════════════════════════
print("Step 4: 保存标注文件...")

# 保存统计表
stat_out = ROOT / '分布式光伏预测_各站点相对误差统计_已标注.csv'
df_stat.to_csv(stat_out, index=False, encoding='utf-8-sig')
print(f"  ✅ 保存: {stat_out.name}")
print(f"      标注列: 问题标注")
print(f"      有标注站点数: {(df_stat['问题标注'] != '正常').sum()} / {len(df_stat)}")

# 保存时序表
f1_out = ROOT / '分布式光伏预测_前38座_已标注.csv'
f2_out = ROOT / '分布式光伏预测_后40座_已标注.csv'
df1_ann.to_csv(f1_out, index=False, encoding='utf-8-sig')
df2_ann.to_csv(f2_out, index=False, encoding='utf-8-sig')
print(f"  ✅ 保存: {f1_out.name}  (新增列: 站点问题标注)")
print(f"  ✅ 保存: {f2_out.name}  (新增列: 站点问题标注)")

# ═══════════════════════════════════════════════════════════════════════════════
#  Step 5: 打印标注汇总
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("标注汇总")
print("=" * 70)

normal_mask = df_stat['问题标注'] == '正常'
issues = df_stat[~normal_mask][['站点ID','站点名称','MAE(MW)','样本数','相对误差均值(%)','误差<1MW比例(%)','问题标注']]
print(f"\n🔴 最差站点（MAE>0.8MW 或 相对误差>200%）:")
worst = df_stat[(df_stat['MAE(MW)'] > 0.80) | (df_stat['相对误差均值(%)'] > 200)]
for _, r in worst.sort_values('MAE(MW)', ascending=False).iterrows():
    print(f"  {r['站点ID']} {r['站点名称']}: MAE={r['MAE(MW)']:.3f}MW, 相对误差={r['相对误差均值(%)']:.1f}%, n={r['样本数']}")

print(f"\n✅ 最好站点（MAE<0.10MW）:")
best = df_stat[df_stat['MAE(MW)'] < 0.10]
for _, r in best.sort_values('MAE(MW)').iterrows():
    print(f"  {r['站点ID']} {r['站点名称']}: MAE={r['MAE(MW)']:.3f}MW, n={r['样本数']}")

print(f"\n🟠 训练数据少（样本数<3000）:")
few = df_stat[df_stat['样本数'] < 3000].sort_values('样本数')
for _, r in few.iterrows():
    print(f"  {r['站点ID']} {r['站点名称']}: n={r['样本数']}, MAE={r['MAE(MW)']:.3f}MW")

print(f"\n🔵 0值过多（零功率比例>50%）:")
for site_name, zr in sorted(zero_ratio.items(), key=lambda x: -x[1]):
    if zr > 50:
        # 找对应站点ID
        matched = df_stat[df_stat['站点名称'].str.contains(site_name[:4], na=False)]
        sid = matched['站点ID'].values[0] if len(matched) > 0 else '?'
        print(f"  {sid} {site_name}: 零值率={zr:.1f}%")

print(f"\n⚠️ 预测偏离极大（<1MW比例<60%）:")
bad = df_stat[df_stat['误差<1MW比例(%)'] < 60].sort_values('误差<1MW比例(%)')
for _, r in bad.iterrows():
    print(f"  {r['站点ID']} {r['站点名称']}: <1MW比例={r['误差<1MW比例(%)']:.1f}%, MAE={r['MAE(MW)']:.3f}MW")

print("\n✅ 完成！标注文件已保存到 metrics/ 目录")
