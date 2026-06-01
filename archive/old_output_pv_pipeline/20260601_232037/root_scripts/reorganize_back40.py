#!/usr/bin/env python3
"""
将后40座CSV重新整理为：真实值列 + 预测值列（每个站点配对在一起）
"""

import pandas as pd
from pathlib import Path

BASE = Path("/root/autodl-tmp/photovoltaic_forecasting_pj/output/pv_pipeline/metrics")
IN   = BASE / "分布式光伏预测_后40座_已标注.csv"
OUT  = BASE / "分布式光伏预测_后40座_真实预测对照.csv"

df = pd.read_csv(IN)
cols = list(df.columns)

real_cols = sorted([c for c in cols if c.endswith("_总出力值")])
pred_cols = sorted([c for c in cols if c.endswith("_预测")])

def station_name(c, suffix):
    return c.replace(suffix, "")

real_dict = {station_name(c, "_总出力值"): c for c in real_cols}
pred_dict = {station_name(c, "_预测"): c for c in pred_cols}
common = sorted(real_dict.keys() & pred_dict.keys())

new_order = []
for s in common:
    new_order.append(real_dict[s])
    new_order.append(pred_dict[s])

for c in ["time", "站点问题标注"]:
    if c in cols:
        new_order.append(c)

df_out = df[new_order].copy()
df_out.to_csv(OUT, index=False, encoding="utf-8-sig")

print(f"站点数: {len(common)}")
print(f"站点列表: {common}")
print(f"输出列数: {len(new_order)}")
print(f"输出行数: {len(df_out)}")
print(f"已保存至: {OUT}")
