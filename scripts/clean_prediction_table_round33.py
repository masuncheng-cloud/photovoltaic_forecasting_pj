"""
clean_prediction_table_round33.py
=================================
清理 distributed_predictions_final_full.pkl 中的重复记录：
  1. train/valid/test 不允许重复 (site_id + time + split)，发现则报错
  2. future 单独保留但不参与评估
  3. 输出 clean 版本供后续所有脚本使用
"""
import os
import sys
import pickle
import pandas as pd
from pathlib import Path

# ── 路径配置 ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
PRED_DIR     = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
SRC_FILE     = PRED_DIR / "distributed_predictions_final_full.pkl"
DEST_FILE    = PRED_DIR / "distributed_predictions_final_full_clean.pkl"
DUP_REPORT   = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics" / "round33_duplicate_detail.csv"
FUTURE_DUP   = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics" / "round33_future_duplicate_detail.csv"

os.makedirs(PRED_DIR, exist_ok=True)
os.makedirs(PROJECT_ROOT / "output" / "pv_pipeline" / "metrics", exist_ok=True)

print(f"读取: {SRC_FILE}")
with open(SRC_FILE, "rb") as f:
    df = pickle.load(f)
print(f"原始总行数: {len(df):,}")
print(f"列: {list(df.columns)}")
print(f"Splits: {df['split'].unique().tolist()}")

# ── 检查 train/valid/test 重复 ──────────────────────────────────────────────
DUP_KEY = ["site_id", "time", "split"]
for split_name in ["train", "valid", "test"]:
    df_split = df[df["split"] == split_name]
    dup_mask = df_split.duplicated(subset=DUP_KEY, keep=False)
    n_dup = dup_mask.sum()
    if n_dup > 0:
        print(f"\n[ERROR] split='{split_name}' 发现 {n_dup} 个重复行！")
        dup_detail = df_split[dup_mask].sort_values(DUP_KEY)
        dup_detail.to_csv(DUP_REPORT, index=False, encoding="utf-8-sig")
        print(f"  重复明细已写入: {DUP_REPORT}")
        # 显示每组的重复次数
        grp = df_split.groupby(DUP_KEY).size()
        multi = grp[grp > 1]
        print(f"  涉及 {len(multi)} 组 (site_id, time, split)，每组重复 {multi.values} 次")
        sys.exit(1)
    else:
        print(f"  split='{split_name}': 无重复 ✓")

# ── 检查 future 重复 ─────────────────────────────────────────────────────────
df_future = df[df["split"] == "future"]
dup_future_mask = df_future.duplicated(subset=DUP_KEY, keep=False)
n_future_dup = dup_future_mask.sum()
if n_future_dup > 0:
    print(f"\n[WARNING] future 发现 {n_future_dup} 个重复行（保留但记录）")
    future_dup = df_future[dup_future_mask].sort_values(DUP_KEY)
    future_dup.to_csv(FUTURE_DUP, index=False, encoding="utf-8-sig")
    print(f"  future 重复明细已写入: {FUTURE_DUP}")
else:
    print(f"  split='future': 无重复 ✓")
    # 写入空文件占位
    pd.DataFrame(columns=["site_id", "time", "split", "note"]).to_csv(
        FUTURE_DUP, index=False, encoding="utf-8-sig"
    )

# ── 去重（对 future 取第一条，train/valid/test 已确认无重复）──────────────────
# train/valid/test 按自然顺序保留第一条（它们本无重复）
df_hist = df[df["split"].isin(["train", "valid", "test"])]
df_hist_clean = df_hist.drop_duplicates(subset=DUP_KEY, keep="first")

# future 去重
df_future_clean = df_future.drop_duplicates(subset=DUP_KEY, keep="first")

df_clean = pd.concat([df_hist_clean, df_future_clean], ignore_index=True)
print(f"\n清理后总行数: {len(df_clean):,}")
print(f"  train/valid/test: {len(df_hist_clean):,} (原始 {len(df_hist):,})")
print(f"  future:            {len(df_future_clean):,} (原始 {len(df_future):,})")
removed = len(df) - len(df_clean)
print(f"共移除 {removed:,} 行重复记录")

# ── 验证清理后无重复 ─────────────────────────────────────────────────────────
for split_name in ["train", "valid", "test", "future"]:
    df_s = df_clean[df_clean["split"] == split_name]
    n_dup = df_s.duplicated(subset=DUP_KEY, keep=False).sum()
    print(f"  验证 split='{split_name}': {'无重复 ✓' if n_dup == 0 else f'{n_dup} 个重复 ✗'}")

# ── 保存 clean 版本 ──────────────────────────────────────────────────────────
print(f"\n保存清理后文件: {DEST_FILE}")
with open(DEST_FILE, "wb") as f:
    pickle.dump(df_clean, f, protocol=4)
size_mb = os.path.getsize(DEST_FILE) / 1024 / 1024
print(f"文件大小: {size_mb:.1f} MB")
print("\nStep 3 完成！后续可视化默认读取 clean 版本。")
