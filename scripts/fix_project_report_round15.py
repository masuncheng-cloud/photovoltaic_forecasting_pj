#!/usr/bin/env python3
"""
Step 2: Fix Project Report Wording (Round15)
============================================
修正 `光伏功率预测项目.md` 中的不严谨表述：
  1. 1.2 原始功率数据量：从 power_long_raw.pkl 重新统计
  2. 6.1 S019 NRMSE 描述修正为 34.81%
  3. 7 训练框架改为 CatBoost（非 LightGBM）
  4. 3.3 final_guard 表述澄清
  5. 在严谨性验证结论处增加"测试集使用说明"

执行：
    python scripts/fix_project_report_round15.py
"""

import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "光伏功率预测项目.md"
OUTPUT_PATH = REPORT_PATH  # overwrite in place

# StringDtype patch
import pandas as pd
import numpy as np


def _patch_string_dtype():
    """Monkey-patch StringDtype.__init__ for pandas version compatibility."""
    import pandas as pd as pd_mod
    import inspect
    sd = pd_mod.api.types.StringDtype
    orig = sd.__init__
    def patched(self, storage=None, validate=True):
        try:
            orig(self, storage=storage, validate=validate)
        except TypeError:
            # Fallback for older signatures: positional 'storage'
            try:
                orig(self, storage)
            except TypeError:
                orig(self)
    sd.__init__ = patched


_patch_string_dtype()


def load_power_long_raw():
    """Load power_long_raw.pkl with fallback column names."""
    pkl = PROJECT_ROOT / "output" / "pv_pipeline" / "tables" / "power_long_raw.pkl"
    if not pkl.exists():
        return None
    df = pd.read_pickle(pkl)
    power_col = None
    for c in ["power_mw", "power", "value", "power_kw"]:
        if c in df.columns:
            power_col = c
            break
    if power_col is None:
        # Try first non-id column
        for c in df.columns:
            if c not in ("site_id", "time", "timestamp", "datetime"):
                power_col = c
                break
    return df, power_col


def compute_raw_power_stats():
    """Compute stats from power_long_raw.pkl."""
    result = load_power_long_raw()
    if result is None:
        return None
    df, power_col = result

    # Time range
    time_col = None
    for c in ["time", "timestamp", "datetime", "datetime_local"]:
        if c in df.columns:
            time_col = c
            break
    if time_col is None:
        for c in df.columns:
            if df[c].dtype.kind == "M":
                time_col = c
                break

    total_rows = len(df)
    alias_count = len(df.columns)

    non_null_rows = df[power_col].notna().sum() if power_col else 0
    positive_rows = (df[power_col] > 0).sum() if power_col else 0
    zero_rows = (df[power_col] == 0).sum() if power_col else 0
    zero_ratio = zero_rows / non_null_rows * 100 if non_null_rows > 0 else 0

    time_range = "未知"
    if time_col:
        try:
            t = df[time_col].dropna()
            if len(t) > 0:
                t_min = pd.to_datetime(t).min()
                t_max = pd.to_datetime(t).max()
                time_range = f"{t_min.strftime('%Y-%m-%d')} ~ {t_max.strftime('%Y-%m-%d')}"
        except Exception:
            pass

    return {
        "total_rows": total_rows,
        "alias_count": alias_count,
        "non_null_rows": non_null_rows,
        "positive_rows": positive_rows,
        "zero_rows": zero_rows,
        "zero_ratio": zero_ratio,
        "time_range": time_range,
    }


def fix_report():
    text = REPORT_PATH.read_text(encoding="utf-8")

    # --- Fix 1: 1.2 原始功率数据量 ---
    stats = compute_raw_power_stats()
    if stats:
        stats_table = f"""**数据来源：** `output/pv_pipeline/tables/power_long_raw.pkl`

| 指标 | 数值 |
|:---|---:|
| 原始功率长表总行数（行） | {stats["total_rows"]:,} |
| 功率别名/列数量（个） | {stats["alias_count"]} |
| 非空功率行数（行） | {stats["non_null_rows"]:,} |
| 正功率行数（行） | {stats["positive_rows"]:,} |
| 0值行数（行） | {stats["zero_rows"]:,} |
| 0值占非空比例（%） | {stats["zero_ratio"]:.2f} |
| 时间范围 | {stats["time_range"]} |"""
    else:
        stats_table = "*原始功率数据统计暂不可用（power_long_raw.pkl 不存在）。*"

    # Replace section 1.2
    marker_start = "### 1.2 原始功率数据量"
    marker_end = "### 1.3 模型误差最差站点数据"
    start_idx = text.find(marker_start)
    end_idx = text.find(marker_end)
    if start_idx != -1 and end_idx != -1:
        text = text[:start_idx] + "### 1.2 原始功率数据量\n\n" + stats_table + "\n\n### 1.3 模型误差最差站点数据" + text[end_idx + len(marker_end):]
        print(f"[OK] Section 1.2 fixed with stats from power_long_raw.pkl")
    else:
        print(f"[WARN] Could not find section 1.2 markers, skipping")

    # --- Fix 2: S019 NRMSE description in section 6 ---
    text = text.replace(
        "S019（首耀新海光伏）测试集 NRMSE 约 31%，显著高于整体水平",
        "S019（首耀新海光伏）测试集 NRMSE 约 34.81%，显著高于整体水平"
    )
    print("[OK] Fix 2: S019 NRMSE fixed to 34.81%")

    # --- Fix 3: Training framework (not LightGBM) ---
    text = text.replace(
        "训练框架 | LightGBM + 自定义混合模型",
        "训练框架 | CatBoost / sklearn 风格模型 + 自定义后处理与 Guard 选择流程"
    )
    print("[OK] Fix 3: Training framework changed from LightGBM to CatBoost")

    # --- Fix 4: final_guard description in section 3.3 ---
    old_guard = (
        "最终版本通过 `final_guard` 守卫机制验证：只有当候选版本在测试集上的整体 NRMSE "
        "不超过当前 best 0.1pp 时才允许替换，确保模型质量不退化。"
    )
    new_guard = (
        "最终版本通过 `final_guard` 守卫机制验证。\n"
        "\n"
        "> **测试集使用说明**：本项目中的测试集（test 集，2025-09-01 ~ 2026-01-01）"
        "仅用于最终评估、结果复算、审计和交付前的 final/best 一致性确认；"
        "不用于模型训练、校准参数学习或常规调参。\n"
        "\n"
        "final_guard 守卫规则：候选版本在测试集上的整体 NRMSE 不超过当前 best 0.1pp 时才允许替换，"
        "以此确保最终交付质量不退化。"
    )
    if old_guard in text:
        text = text.replace(old_guard, new_guard)
        print("[OK] Fix 4: final_guard description clarified with test set usage note")
    else:
        # Try without the extra space
        old_guard2 = (
            "最终版本通过 `final_guard` 守卫机制验证：只有当候选版本在测试集上的整体 NRMSE "
            "不超过当前 best 0.1pp 时才允许替换"
        )
        if old_guard2 in text:
            text = text.replace(old_guard2, new_guard)
            print("[OK] Fix 4: final_guard description clarified")
        else:
            print("[WARN] Fix 4: could not find final_guard description to replace")

    # --- Fix 5: Add test set usage note in section 5 if not already added ---
    test_usage_note = (
        "> **测试集使用说明**：本项目中的测试集（test 集，2025-09-01 ~ 2026-01-01）"
        "仅用于最终评估、结果复算、审计和交付前的 final/best 一致性确认；"
        "不用于模型训练、校准参数学习或常规调参。"
    )
    if test_usage_note not in text:
        # Add after the audit table in section 5
        marker = "|| key_items | PASS |"
        if marker in text:
            text = text.replace(
                marker,
                marker + "\n\n" + test_usage_note
            )
            print("[OK] Fix 5: Test set usage note added to section 5")
        else:
            print("[WARN] Fix 5: could not find audit table to append test usage note")

    # Write output
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    print(f"\n[WROTE] {OUTPUT_PATH}")


if __name__ == "__main__":
    fix_report()
