#!/usr/bin/env python3
"""将 time 列移到第一列位置"""

import pandas as pd
from pathlib import Path

BASE = Path("/root/autodl-tmp/photovoltaic_forecasting_pj/output/pv_pipeline/metrics")

for fname in ["分布式光伏预测_前38座_真实预测对照.csv",
              "分布式光伏预测_后40座_真实预测对照.csv"]:
    path = BASE / fname
    df = pd.read_csv(path)
    cols = list(df.columns)
    cols.remove("time")
    cols.insert(0, "time")
    df = df[cols]
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"{fname}  → time 已移至第1列，当前列数: {len(cols)}")
