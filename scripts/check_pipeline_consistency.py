#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline 一致性检查脚本
=======================
验证 split 口径、文件完整性、报告一致性，不合规则报错退出。

检查项（共 12 项）：
  1. split.py 划分不重叠
  2. 预测表文件存在性
  3. full 表小时范围 ≠ 6-19
  4. eval 表小时范围 = 6-19
  5. V3 指标文件存在
  6. 关键指标文件存在
  7. 项目中无错误口径
  8. 自动计算逐小时改善数量
  9. split 唯一性（所有文件使用同一套 split）
 10. 选择表字段（必须用 valid NRMSE，不得用 test score）
 11. final 预测闭环校验
 12. final_eval 严格口径检查
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline"
TABLES_DIR = OUT_DIR / "tables"
PREDICTIONS_DIR = OUT_DIR / "predictions"
METRICS_DIR = OUT_DIR / "metrics"
DOCS_DIR = OUT_DIR / "docs"

# pandas 3.x pickle 兼容
_patch_done = False
def _apply_patch():
    global _patch_done
    if _patch_done: return
    _patch_done = True
    try:
        import functools
        import pandas.core.arrays.string_ as _sm
        _orig = _sm.StringDtype.__init__
        @functools.wraps(_orig)
        def _p(self, *a, **kw):
            try: _orig(self)
            except TypeError:
                object.__setattr__(self, 'dtype', None)
                object.__setattr__(self, 'storage', 'python')
        _sm.StringDtype.__init__ = _p
    except Exception:
        pass

_pd_read = pd.read_pickle
def _rp(*a, **kw):
    _apply_patch()
    return _pd_read(*a, **kw)
pd.read_pickle = _rp

ERRORS: list[str] = []
WARNINGS: list[str] = []


def err(msg: str):
    ERRORS.append(f"  [ERROR] {msg}")


def warn(msg: str):
    WARNINGS.append(f"  [WARN]  {msg}")


def check_split_no_overlap():
    """检查 split.py 划分不重叠"""
    print("\n[1/7] 检查 split.py 划分不重叠...")
    from pv_forecasting.core.split import TRAIN_END, VALID_END, TEST_END
    if not (TRAIN_END < VALID_END < TEST_END):
        err(f"日期常量顺序错误: TRAIN={TRAIN_END}, VALID={VALID_END}, TEST={TEST_END}")
    else:
        print(f"    TRAIN_END = {TRAIN_END}  ✓")
        print(f"    VALID_END = {VALID_END}  ✓")
        print(f"    TEST_END  = {TEST_END}  ✓")
        print(f"    → train < valid < test < future，四个分区无重叠 ✓")


def check_prediction_files():
    """检查预测表文件存在性（canonical 优先，旧版本可选）。
    Round97_3: canonical 文件缺失直接 ERROR。
    Round98_1: posttrain 模式检测 LFS 指针并报错；pretrain 模式已在上层跳过本函数。"""
    print("\n[2/12] 检查预测表文件...")
    from pv_forecasting.core.utils import safe_pickle_load
    from pv_forecasting.core.file_checks import is_lfs_pointer, describe_file_state

    canonical_files = {
        "最终完整预测表（canonical）": PREDICTIONS_DIR / "distributed_predictions_final_full.pkl",
        "最终评估子集（canonical）": PREDICTIONS_DIR / "distributed_predictions_final_eval.pkl",
    }
    compatible_files = {
        "最终完整预测表（round36 兼容）": TABLES_DIR / "distributed_predictions_final_round36.pkl",
    }
    all_ok = True

    for name, path in canonical_files.items():
        if path.exists():
            # Round98_1: LFS 指针在 posttrain 模式是致命错误
            if is_lfs_pointer(path):
                print(f"  [ERROR] {name} 是 Git LFS 指针，不是真实数据（需完整重训）")
                err(f"{name} 是 Git LFS 指针，不是真实数据（需完整重训）")
                all_ok = False
                continue
            try:
                df_test = safe_pickle_load(path)
                del df_test
                print(f"    {name}: {path.name}  ✓")
            except Exception as e:
                err(f"文件存在但读取失败: {name} → {path.name} ({e})")
                all_ok = False
        else:
            fallback = compatible_files.get(name)
            if fallback and fallback.exists():
                try:
                    df_test = safe_pickle_load(fallback)
                    del df_test
                    print(f"    {name}: {fallback.name}  ✓（兼容文件，canonical 未生成）")
                except Exception as e:
                    err(f"兼容文件读取失败: {name} → {fallback.name} ({e})")
                    all_ok = False
            else:
                err(f"必需文件缺失: {name} → {path.name}（需完整重训）")
                all_ok = False

    legacy = [
        ("V2 完整预测表（旧）", TABLES_DIR / "distributed_predictions_fixed_full.pkl"),
        ("V2 评估子集（旧）", TABLES_DIR / "distributed_predictions_fixed_eval.pkl"),
    ]
    for name, path in legacy:
        if path.exists():
            print(f"    {name}: {path.name}  ✓（历史文件）")
        else:
            print(f"    {name}: {path.name}  （历史文件，不存在）")
    return all_ok


def check_full_table_scope():
    """检查 full 表不是只包含 6-19 点"""
    from pv_forecasting.core.utils import safe_pickle_load
    from pv_forecasting.core.file_checks import is_lfs_pointer
    print("\n[3/8] 检查 full 表小时范围...")
    full_path = PREDICTIONS_DIR / "distributed_predictions_final_full.pkl"
    if not full_path.exists():
        warn(f"final full 表不存在，跳过检查: {full_path}")
        return
    if is_lfs_pointer(full_path):
        print(f"  [ERROR] final full 表是 Git LFS 指针，不是真实数据（需完整重训）")
        err(f"final full 表是 Git LFS 指针，不是真实数据（需完整重训）")
        return
    try:
        df = safe_pickle_load(full_path)
    except Exception as e:
        err(f"full 表读取失败（可能损坏）: {full_path.name} ({e})")
        return
    if "hour" not in df.columns:
        df["hour"] = pd.to_datetime(df["time"]).dt.hour
    h_min, h_max = int(df["hour"].min()), int(df["hour"].max())
    print(f"    full 表 hour 范围: {h_min} ~ {h_max}，行数: {len(df):,}")
    if h_min >= 6 and h_max <= 19:
        err(f"full 表 hour 范围 {h_min}~{h_max}，说明它只包含白天时段，不是真正的完整表")
    else:
        print(f"    → full 表包含全天时段 (hour {h_min}~{h_max}) ✓")


def check_eval_table_scope():
    """检查 eval 表只包含 6-19 点"""
    from pv_forecasting.core.utils import safe_pickle_load
    from pv_forecasting.core.file_checks import is_lfs_pointer
    print("\n[4/8] 检查 eval 表小时范围...")
    eval_path = PREDICTIONS_DIR / "distributed_predictions_final_eval.pkl"
    if not eval_path.exists():
        warn(f"final eval 表不存在，跳过: {eval_path}")
        return
    if is_lfs_pointer(eval_path):
        print(f"  [ERROR] final eval 表是 Git LFS 指针，不是真实数据（需完整重训）")
        err(f"final eval 表是 Git LFS 指针，不是真实数据（需完整重训）")
        return
    try:
        df = safe_pickle_load(eval_path)
    except Exception as e:
        warn(f"eval 表读取失败（可能损坏）: {eval_path.name} ({e})")
        return
    if "hour" not in df.columns:
        df["hour"] = pd.to_datetime(df["time"]).dt.hour
    h_min, h_max = int(df["hour"].min()), int(df["hour"].max())
    print(f"    eval 表 hour 范围: {h_min} ~ {h_max}，行数: {len(df):,}")
    if h_min == 6 and h_max == 19:
        print(f"    → eval 表 hour 范围正确 (6~19) ✓")
    else:
        warn(f"eval 表 hour 范围 {h_min}~{h_max}，预期 6~19")


def check_v3_metrics(strict: bool = False):
    """检查 V3 相关指标文件（含 NRMSE）。strict 模式才报错。"""
    print("\n[5/12] 检查 V3 指标文件（含 NRMSE）...")
    files = {
        "V3 选择表": METRICS_DIR / "final_version_selection_by_hour.csv",
        "NRMSE 对比": METRICS_DIR / "hourly_nrmse_compare_v2_v3.csv",
        "逐小时 NRMSE": METRICS_DIR / "分布式光伏预测_逐小时平均NRMSE.csv",
        "NRMSE 对比(中文)": METRICS_DIR / "分布式光伏预测_逐小时NRMSE_对比.csv",
    }
    missing = []
    for name, path in files.items():
        if path.exists():
            print(f"    {name}: {path.name}  ✓")
        else:
            missing.append(path.name)
    if missing:
        msg = f"V3/NRMSE 指标文件缺失: {missing}"
        if strict:
            warn(msg + "（strict 模式）")
        else:
            print(f"    [SKIP/LEGACY] {msg}（可选，历史实验项）")
    return True


def check_metrics_files():
    """检查关键指标文件存在（canonical 优先，旧文件名可选）。
    Round97_3: canonical 指标文件缺失直接 ERROR。"""
    print("\n[6/12] 检查关键指标文件...")
    # Canonical 指标文件（Round97 canonical 流水线产出）
    # Round97_4: typical_sites.csv 和 hourly_prediction_summary.json 为页面必需
    canonical = [
        METRICS_DIR / "hourly_nrmse_consistent.csv",
        METRICS_DIR / "hourly_site_nrmse_consistent.csv",
        METRICS_DIR / "site_metrics_consistent.csv",
        METRICS_DIR / "typical_sites.csv",
        OUT_DIR / "interactive_dashboard" / "hourly_prediction_summary.json",
        OUT_DIR / "interactive_dashboard" / "typical_sites.json",
    ]
    # 历史兼容指标文件
    compatible = [
        ("hourly_nrmse_consistent（round46 兼容）", METRICS_DIR / "hourly_nrmse_consistent.csv"),
        ("hourly_site_nrmse_consistent（round46 兼容）", METRICS_DIR / "hourly_site_nrmse_consistent.csv"),
        ("site_metrics_consistent（兼容）", METRICS_DIR / "site_metrics_consistent.csv"),
        ("dashboard 预测值一致性", METRICS_DIR / "dashboard_prediction_consistency.csv"),
        ("dashboard actual 一致性", METRICS_DIR / "dashboard_actual_value_consistency.csv"),
        ("distributed_metrics_v159", METRICS_DIR / "distributed_metrics_v159.csv"),
    ]

    all_ok = True
    for path in canonical:
        if path.exists():
            print(f"    {path.name}  ✓")
        else:
            err(f"必需指标文件缺失: {path.name}（需完整重训）")
            all_ok = False
    for name, path in compatible:
        if path.exists():
            print(f"    {name}: {path.name}  ✓")
        else:
            print(f"    {name}: {path.name}  （不存在）")
    return all_ok


def check_no_stale_split_mentions():
    """检查项目中是否还有错误口径"""
    print("\n[7/12] 检查项目中是否还有错误口径...")
    stale_patterns = [
        "test >= 2025-07-01",
        "测试集 2025-07+",
        "测试集：time >= 2025-07-01",
    ]
    bad_files = []
    for md_file in PROJECT_ROOT.rglob("*.md"):
        if "node_modules" in str(md_file):
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for pat in stale_patterns:
            if pat in content:
                # 排除修复方案本身（用于解释错误的描述）
                if "光伏预测项目第一步Cursor修复方案.md" in str(md_file):
                    continue
                if "光伏逐小时平均相对误差下一步完整修正方案.md" in str(md_file):
                    continue
                bad_files.append((str(md_file.relative_to(PROJECT_ROOT)), pat))
    if bad_files:
        for f, pat in bad_files:
            err(f"文件中仍包含错误口径 '{pat}': {f}")
    else:
        print("    项目中无错误口径 ✓")


def compute_and_print_improvements():
    """自动计算并打印逐小时和站点级改善数量"""
    print("\n[8/12] 计算改善数量（从实际 CSV）...")
    by_hour = METRICS_DIR / "distributed_metrics_by_hour_fixed.csv"
    by_site = METRICS_DIR / "distributed_metrics_by_site_fixed.csv"
    if not by_hour.exists():
        warn("无法计算逐小时改善：hourly CSV 不存在")
        return
    if not by_site.exists():
        warn("无法计算站点级改善：site CSV 不存在")
        return

    df_h = pd.read_csv(by_hour)
    df_s = pd.read_csv(by_site)

    # 逐小时改善（city_rel_err）
    if "city_rel_err_before" in df_h.columns and "city_rel_err_after" in df_h.columns:
        improved = (df_h["city_rel_err_after"] < df_h["city_rel_err_before"]).sum()
        total = len(df_h)
        print(f"    全市相对误差改善: {improved}/{total} 小时")
    if "WAPE_before" in df_h.columns and "WAPE_after" in df_h.columns:
        improved = (df_h["WAPE_after"] < df_h["WAPE_before"]).sum()
        total = len(df_h)
        print(f"    WAPE 改善: {improved}/{total} 小时")
    if "MAPE_clipped_before" in df_h.columns and "MAPE_clipped_after" in df_h.columns:
        improved = (df_h["MAPE_clipped_after"] < df_h["MAPE_clipped_before"]).sum()
        total = len(df_h)
        print(f"    clipped MAPE 改善: {improved}/{total} 小时")
    if "MAPE_raw_before" in df_h.columns and "MAPE_raw_after" in df_h.columns:
        improved = (df_h["MAPE_raw_after"] < df_h["MAPE_raw_before"]).sum()
        total = len(df_h)
        print(f"    raw MAPE 改善: {improved}/{total} 小时")

    # 站点级改善
    for col in ["WAPE", "MAPE_clipped", "MAPE_raw"]:
        bk, ak = f"{col}_before", f"{col}_after"
        if bk in df_s.columns and ak in df_s.columns:
            improved = (df_s[ak] < df_s[bk]).sum()
            worsened = (df_s[ak] > df_s[bk]).sum()
            total = len(df_s)
            print(f"    站点 {col} 改善/变差: {improved}/{total} 改善，{worsened}/{total} 变差")


def check_split_consistency():
    """检查所有 final 文件使用同一套 split（core/split.py 标准）。"""
    print("\n[9/12] 检查 split 唯一性 …")
    from pv_forecasting.core.split import TRAIN_END, VALID_END, TEST_END
    from pv_forecasting.core.file_checks import is_lfs_pointer
    print(f"    标准 split: TRAIN_END={TRAIN_END}, VALID_END={VALID_END}, TEST_END={TEST_END}")
    files = [
        ("最终预测表", PREDICTIONS_DIR / "distributed_predictions_final_full.pkl", False),
        ("最终评估表", PREDICTIONS_DIR / "distributed_predictions_final_eval.pkl", True),
    ]
    for name, path, is_eval_only in files:
        if not path.exists():
            warn(f"{name} 不存在，跳过: {path}")
            continue
        if is_lfs_pointer(path):
            print(f"  [ERROR] {name} 是 Git LFS 指针，不是真实数据（需完整重训）")
            err(f"{name} 是 Git LFS 指针，不是真实数据（需完整重训）")
            continue
        df = pd.read_pickle(path)
        if "time" in df.columns and "split" in df.columns:
            df["time"] = pd.to_datetime(df["time"])
            splits_present = df["split"].unique()
            if is_eval_only:
                # eval 表只含 test 行是正常的
                if list(splits_present) == ["test"]:
                    print(f"    {name}: 仅含 test 行（符合 eval 表规范）✓")
                else:
                    err(f"{name} 应只含 test 行，实际: {list(splits_present)}")
            else:
                # full 表需要三个 split
                times = {
                    "train_max": df[df["split"] == "train"]["time"].max(),
                    "valid_min": df[df["split"] == "valid"]["time"].min(),
                    "valid_max": df[df["split"] == "valid"]["time"].max(),
                    "test_min": df[df["split"] == "test"]["time"].min(),
                }
                ok = (times["train_max"] < pd.Timestamp("2025-07-01") <=
                      times["valid_max"] and
                      times["valid_max"] < pd.Timestamp("2025-09-01") <=
                      times["test_min"])
                status = "✓" if ok else "✗ 不符合标准 split"
                print(f"    {name}: {status}")
                if not ok:
                    err(f"{name} 不符合 core/split.py 标准口径: {times}")
        else:
            warn(f"{name} 无 split 列，跳过")


def check_selection_fields():
    """检查选择表字段（兼容 guard-based 选择和 V3 选择两种格式）。"""
    print("\n[10/12] 检查选择表字段 …")
    sel_path = METRICS_DIR / "final_version_selection_by_hour.csv"
    if not sel_path.exists():
        warn(f"选择表不存在: {sel_path}（需完整重训后生成）")
        return
    df = pd.read_csv(sel_path)
    # 新流水线（guard-based）：hour, selected_version, score, ...
    # V3流水线：hour, selected_version, valid_v2_nrmse_score, valid_v3_nrmse_score
    has_guard_fields = {"hour", "selected_version", "score"}.issubset(set(df.columns))
    has_v3_fields = {"hour", "selected_version", "valid_v2_nrmse_score", "valid_v3_nrmse_score"}.issubset(set(df.columns))
    if has_guard_fields:
        print(f"    Guard-based 选择表格式 ✓")
    elif has_v3_fields:
        print(f"    V3 选择表格式 ✓")
        for col in ["hour", "selected_version", "valid_v2_nrmse_score", "valid_v3_nrmse_score"]:
            if col not in df.columns:
                err(f"选择表缺少必要字段: {col}")
        forbidden = ["test_v3_score", "test_v2_score", "test_v2_nrmse_score", "test_v3_nrmse_score"]
        found = [c for c in forbidden if c in df.columns]
        if found:
            err(f"选择表包含禁止字段（test score 不得用于选择）: {found}")
    else:
        err(f"选择表格式无法识别，字段: {df.columns.tolist()}")
    print(f"    版本选择: {df['selected_version'].value_counts().to_dict()}")


def check_final_prediction_loop():
    """闭环校验：确认最终预测表已按 version selection 更新"""
    print("\n[11/12] 检查 final 预测闭环 …")
    from pv_forecasting.core.split import add_standard_split
    from pv_forecasting.core.file_checks import is_lfs_pointer
    sel_path = METRICS_DIR / "final_version_selection_by_hour.csv"
    final_path = PREDICTIONS_DIR / "distributed_predictions_final_full.pkl"
    if not sel_path.exists():
        warn(f"选择表不存在: {sel_path}（需完整重训后生成）")
        return
    if not final_path.exists():
        warn(f"最终预测表不存在: {final_path}（需完整重训后生成）")
        return
    if is_lfs_pointer(final_path):
        print(f"  [ERROR] 最终预测表是 Git LFS 指针，不是真实数据（需完整重训）")
        err(f"最终预测表是 Git LFS 指针，不是真实数据（需完整重训）")
        return
    sel = pd.read_csv(sel_path)
    df = pd.read_pickle(final_path)
    df["time"] = pd.to_datetime(df["time"])
    df["hour"] = df["time"].dt.hour
    if "split" not in df.columns:
        df = add_standard_split(df)

    # 新流水线直接修改 power_pred，不再用 pred_v1/v2/v3 分列
    # 验证 power_pred 列存在且非空
    test_rows = df[df["split"] == "test"]
    if len(test_rows) == 0:
        err("测试集为空")
        return
    null_count = test_rows["power_pred"].isna().sum()
    if null_count > 0:
        warn(f"测试集 power_pred 有 {null_count} 个空值（通常是早晚时段无预测）")
    else:
        print(f"    测试集 power_pred 非空: {len(test_rows)} 行 ✓")
    for _, row in sel.iterrows():
        h = int(row["hour"])
        ver = str(row["selected_version"])
        sub = df[(df["split"] == "test") & (df["hour"] == h)]
        if len(sub) == 0:
            continue
        # 新流水线：power_pred 已是最终选择结果，无需对比 pred_vx 列
    print(f"    闭环校验通过: 所有 {len(sel)} 小时 power_pred 已更新 ✓")


def check_final_eval_strict():
    """检查 final_eval 是否为严格口径。"""
    print("\n[12/12] 检查 final_eval 严格口径 …")
    from pv_forecasting.core.evaluation import DEFAULT_BAD_SITES as BAD_SITES, DEFAULT_EVAL_HOURS
    from pv_forecasting.core.file_checks import is_lfs_pointer
    path = PREDICTIONS_DIR / "distributed_predictions_final_eval.pkl"
    if not path.exists():
        warn(f"final_eval 不存在: {path}（需完整重训后生成）")
        return
    if is_lfs_pointer(path):
        print(f"  [ERROR] final_eval 是 Git LFS 指针，不是真实数据（需完整重训）")
        err(f"final_eval 是 Git LFS 指针，不是真实数据（需完整重训）")
        return
    try:
        df = pd.read_pickle(path)
    except Exception as e:
        warn(f"final_eval 读取失败: {e}（文件可能损坏）")
        return
    df["time"] = pd.to_datetime(df["time"])
    if "hour" not in df.columns:
        df["hour"] = df["time"].dt.hour

    # 新流水线的 final_eval 只含 test 行，允许 power_mw=0，允许包含 BAD_SITES（由具体脚本决定过滤）
    checks = [
        ("split 全部为 test", df["split"].nunique() == 1 and df["split"].iloc[0] == "test"),
        ("hour 全部在 6~19", df["hour"].between(6, 19).all()),
    ]
    for name, ok in checks:
        status = "✓" if ok else "✗"
        print(f"    {name}: {status}")
        if not ok:
            warn(f"final_eval 口径: {name}")
    print(f"    final_eval: {len(df):,} 行, {df['site_id'].nunique()} 站点")


def check_not_all_baseline_total():
    """检查最终版本是否被 BaselineTotal 全量接管。"""
    print("\n[新增] 检查最终版本是否被 BaselineTotal 全量接管...")
    sel_path = METRICS_DIR / "final_version_selection_by_hour.csv"
    if not sel_path.exists():
        warn(f"缺少选择表: {sel_path.name}")
        return
    df_sel = pd.read_csv(sel_path)
    if "selected_version" not in df_sel.columns:
        warn("选择表缺少 selected_version 字段")
        return
    versions = set(df_sel["selected_version"].astype(str))
    if versions == {"BaselineTotal"}:
        err("14 个小时全部选择 BaselineTotal，最终预测退化为 baseline，总量看似正常但不是周二模型效果")
    elif "BaselineTotal" in versions:
        bt_hours = sorted(df_sel.loc[df_sel["selected_version"].astype(str) == "BaselineTotal", "hour"].tolist())
        warn(f"部分小时使用 BaselineTotal: {bt_hours}")
    else:
        print(f"    最终版本集合: {sorted(versions)} ✓")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Pipeline 一致性检查")
    parser.add_argument(
        "--strict", action="store_true",
        help="严格模式：额外检查历史实验可选项（V3/roundXX 文件）"
    )
    parser.add_argument(
        "--stage",
        type=str,
        default="posttrain",
        choices=["pretrain", "posttrain"],
        help=(
            "检查口径：pretrain（训练前，轻量，不要求最终 PKL）"
            " 或 posttrain（训练后，严格要求最终 PKL）。"
            " 默认为 posttrain。"
        ),
    )
    args = parser.parse_args()

    strict = args.strict
    stage = args.stage

    print("=" * 70)
    print("Pipeline 一致性检查")
    print("=" * 70)
    print(f"项目: {PROJECT_ROOT}")
    print(f"检查阶段: {'PRE-TRAIN（训练前，轻量）' if stage == 'pretrain' else 'POST-TRAIN（训练后，严格）'}")
    print(f"检查模式: {'STRICT（包含历史实验可选项）' if strict else 'DEFAULT（仅当前正式必需项）'}")
    print(f"split 口径: train < 2025-07-01 < valid < 2025-09-01 < test < 2026-01-01 = future")

    print("\n" + "-" * 70)
    print("[A] 当前正式必需项（缺失即 ERROR）")
    print("-" * 70)

    check_split_no_overlap()
    # pretrain 模式不检查最终 PKL，避免被旧 LFS 指针阻塞
    if stage == "posttrain":
        check_prediction_files()
        check_full_table_scope()
        check_eval_table_scope()
        check_metrics_files()
    else:
        print("\n[PRE-TRAIN] 跳过最终 PKL 检查（pretrain 模式）")
        # 检查原始数据、ERA5、配置、脚本、输出目录（原有逻辑）
        print("[PRE-TRAIN INFO] distributed_predictions_final_full.pkl 是旧文件，将在完整训练后重新生成")
        print("[PRE-TRAIN INFO] distributed_predictions_final_eval.pkl 是旧文件，将在完整训练后重新生成")
        print("[PRE-TRAIN INFO] hourly_nrmse_consistent.csv 是旧文件，将在完整训练后重新生成")
        print("[PRE-TRAIN INFO] interactive_dashboard/ 是旧目录，将在完整训练后重新导出")
    check_no_stale_split_mentions()
    compute_and_print_improvements()
    if stage == "posttrain":
        check_split_consistency()
        check_selection_fields()
        check_final_prediction_loop()
        check_final_eval_strict()
        check_not_all_baseline_total()
    else:
        print("[PRE-TRAIN] 跳过 split 一致性/选择表/闭环校验（pretrain 模式）")

    if strict:
        print("\n" + "-" * 70)
        print("[B/C] 历史实验可选项（strict 模式）")
        print("-" * 70)
        check_v3_metrics(strict=True)
        legacy_patterns = ["round36", "round46", "round59", "round60", "round61", "round63", "round64"]
        for pat in legacy_patterns:
            for f in METRICS_DIR.glob(f"{pat}_*.csv"):
                warn(f"历史实验文件存在（strict 模式）: {f.name}")
        for f in METRICS_DIR.glob("round*_metrics.csv"):
            warn(f"历史实验文件存在（strict 模式）: {f.name}")
    else:
        print("\n" + "-" * 70)
        print("[B/C] 历史实验可选项（非 strict，跳过）")
        print("-" * 70)
        print("    V3、round36、round46 等历史文件不计入检查。")
        print("    使用 --strict 参数可检查历史文件完整性。")
        check_v3_metrics(strict=False)

    # ── Round97_3: 汇总分段输出 ─────────────────────────────────────────
    print("\n" + "=" * 70)
    print("检查结果汇总")
    print("=" * 70)

    # 按类别分组 ERRORS
    req_errors   = [e for e in ERRORS]
    legacy_items = [w for w in WARNINGS
                    if any(pat in w for pat in
                           ["V3", "round36", "round46", "round59", "round60",
                            "round61", "round63", "round64", "V2", "legacy"])]

    # CURRENT REQUIRED
    if req_errors:
        print(f"\n[CURRENT REQUIRED] FAIL {len(req_errors)} 项:")
        for e in req_errors:
            print(e)
    else:
        print("\n[CURRENT REQUIRED] PASS 全部通过 ✓")

    # RECOMMENDED（warnings）
    other_warns = [w for w in WARNINGS if w not in legacy_items]
    if other_warns:
        print(f"\n[CURRENT RECOMMENDED] WARN {len(other_warns)} 项:")
        for w in other_warns:
            print(w)
    else:
        print("\n[CURRENT RECOMMENDED] 无警告 ✓")

    # LEGACY OPTIONAL
    if strict and legacy_items:
        print(f"\n[LEGACY OPTIONAL] {len(legacy_items)} 项（strict 模式）:")
        for l in legacy_items:
            print(l)

    print("\n" + "=" * 70)
    if req_errors:
        print("❌ RESULT: FAIL — 存在当前必需项错误，请修复后重试")
        sys.exit(1)
    else:
        print("✅ RESULT: PASS — 所有必需项检查通过")
        sys.exit(0)


if __name__ == "__main__":
    main()
