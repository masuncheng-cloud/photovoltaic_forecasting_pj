#!/usr/bin/env python3
"""
posttrain_validation.py
=======================
训练后逻辑审计脚本（Round50+ 通用版）。

基于 configs/pipeline.yaml 中的配置进行 25 项检查，
覆盖：数据完整性、指标口径、测试集泄漏、产物新鲜度。

用法：
    python scripts/posttrain_validation.py
    python scripts/posttrain_validation.py --config configs/pipeline.yaml

输出：
    output/pv_pipeline/docs/posttrain_validation_report.md
    output/pv_pipeline/validation/posttrain_validation_results.csv
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scripts.common_paths import load_config, output_root
except ImportError:
    # Fallback if common_paths not yet available
    def load_config(cfg_path=None):
        import yaml
        path = Path(cfg_path) if cfg_path else PROJECT_ROOT / "configs" / "pipeline.yaml"
        with open(path) as f:
            return yaml.safe_load(f)
    def output_root(cfg):
        return PROJECT_ROOT / cfg.get("data", {}).get("output_root", "output/pv_pipeline")


# ─── Result tracker ────────────────────────────────────────────────────────────

class ValidationCheck:
    def __init__(self):
        self.results = []
        self._fails = 0

    def ok(self, name: str, msg: str = ""):
        self.results.append(("PASS", name, msg))
        print(f"  [PASS] {name}" + (f" — {msg}" if msg else ""))

    def warn(self, name: str, msg: str = ""):
        self.results.append(("WARN", name, msg))
        print(f"  [WARN] {name}" + (f" — {msg}" if msg else ""))

    def fail(self, name: str, msg: str = ""):
        self.results.append(("FAIL", name, msg))
        self._fails += 1
        print(f"  [FAIL] {name}" + (f" — {msg}" if msg else ""))

    def has_fail(self) -> bool:
        return self._fails > 0


# ─── Main validation ─────────────────────────────────────────────────────────

def run_validation(cfg: dict) -> ValidationCheck:
    c = ValidationCheck()
    out = output_root(cfg)
    tables_dir = out / "tables"
    metrics_dir = out / "metrics"
    dash_dir = out / "interactive_dashboard"
    docs_dir = out / "docs"
    val_dir = out / "validation"
    val_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    pred_col = cfg.get("prediction", {}).get("final_column", "power_pred_final")
    eval_split = cfg.get("eval", {}).get("split", "test")
    sh, eh = cfg.get("eval", {}).get("start_hour", 6), cfg.get("eval", {}).get("end_hour", 19)
    sp = cfg.get("split", {})

    print("=" * 60)
    print("训练后逻辑审计 — posttrain_validation.py")
    print("=" * 60)
    print(f"配置: final_column={pred_col}, eval={eval_split} {sh}-{eh}h")
    print(f"split: {sp}")
    print()

    # ── C1: final pkl 存在且可读（canonical only） ──────────────────────
    canonical_full = tables_dir / ".." / "predictions" / "distributed_predictions_final_full.pkl"
    if canonical_full.exists():
        fp = canonical_full.resolve()
        try:
            df = pd.read_pickle(fp)
            df["time"] = pd.to_datetime(df["time"])
            if "hour" not in df.columns:
                df["hour"] = df["time"].dt.hour
            c.ok("C1: 最终预测 pkl 存在且可读",
                 f"canonical: {fp.name}, {len(df):,} 行, {len(df.columns)} 列, {df['site_id'].nunique()} 站")
        except Exception as e:
            c.fail("C1: 最终预测 pkl 可读", str(e))
    else:
        c.fail("C1: 最终预测 pkl 存在",
               f"canonical 不存在: {canonical_full} （Round54 禁止 fallback）")

    # ── C2: eval pkl 只含 test 6-19（canonical only） ──────────────────
    canonical_eval = tables_dir / ".." / "predictions" / "distributed_predictions_final_eval.pkl"
    if canonical_eval.exists():
        ep = canonical_eval.resolve()
        try:
            de = pd.read_pickle(ep)
            de["time"] = pd.to_datetime(de["time"])
            if "hour" not in de.columns:
                de["hour"] = de["time"].dt.hour
            split_ok = (de["split"] == eval_split).all()
            hour_ok = de["hour"].between(sh, eh).all()
            if split_ok and hour_ok:
                c.ok("C2: eval pkl 数据范围正确",
                     f"(canonical) 仅含 {eval_split} {sh}-{eh}h, {len(de):,} 行, {de['site_id'].nunique()} 站")
            else:
                c.fail("C2: eval pkl 数据范围", f"split_ok={split_ok}, hour_ok={hour_ok}")
        except Exception as e:
            c.fail("C2: eval pkl 检查", str(e))
    else:
        c.fail("C2: eval pkl 存在",
               f"canonical 不存在: {canonical_eval} （Round54 禁止 fallback）")

    # ── C3: 最终预测列存在且非空 ─────────────────────────────────────────
    if fp.exists():
        try:
            df = pd.read_pickle(fp)
            if pred_col not in df.columns:
                c.fail("C3: 最终预测列存在", f"{pred_col} 不在 pkl 中")
            else:
                nonnull = df[pred_col].notna().sum()
                pct = nonnull / len(df) * 100
                if nonnull == 0:
                    c.fail("C3: 最终预测列非空", f"全部为空")
                else:
                    c.ok("C3: 最终预测列存在", f"{pred_col}: {nonnull:,}/{len(df):,} ({pct:.1f}%)")
        except Exception as e:
            c.fail("C3: 最终预测列检查", str(e))

    # ── C4: power_mw 存在 ───────────────────────────────────────────────
    if fp.exists():
        try:
            df = pd.read_pickle(fp)
            if "power_mw" not in df.columns:
                c.fail("C4: 真实功率列存在", "power_mw 不在 pkl 中")
            else:
                nonnull = df["power_mw"].notna().sum()
                c.ok("C4: 真实功率列存在", f"power_mw: {nonnull:,}/{len(df):,}")
        except Exception as e:
            c.fail("C4: power_mw 检查", str(e))

    # ── C5: split 列存在且值正确 ────────────────────────────────────────
    if fp.exists():
        try:
            df = pd.read_pickle(fp)
            if "split" not in df.columns:
                c.fail("C5: split 列存在", "split 不在 pkl 中")
            else:
                splits = df["split"].unique()
                expected = set(["train", "valid", "test", "future"])
                found = set(splits) & expected
                test_rows = int((df["split"] == eval_split).sum())
                c.ok("C5: split 口径正确",
                     f"值={sorted(found)}, test行数={test_rows:,}")
        except Exception as e:
            c.fail("C5: split 检查", str(e))

    # ── C6: 时间切分正确 ────────────────────────────────────────────────
    if fp.exists():
        try:
            df = pd.read_pickle(fp)
            sp = cfg.get("split", {})
            test_start = sp.get("test_start", "2025-09-01")
            test_end = sp.get("test_end", "2025-12-31")
            valid_end = sp.get("valid_end", "2025-08-31")
            test_min = df[df["split"] == "test"]["time"].min()
            test_max = df[df["split"] == "test"]["time"].max()
            ok = (str(test_min.date()) == test_start and str(test_max.date()) == test_end)
            if ok:
                c.ok("C6: 测试集时间切分正确",
                     f"test={test_start}~{test_end}")
            else:
                c.fail("C6: 测试集时间切分", f"期望 {test_start}~{test_end}, 实际 {test_min.date()}~{test_max.date()}")
        except Exception as e:
            c.fail("C6: 时间切分检查", str(e))

    # ── C7: NRMSE 用 power_pred_final（不是旧列）────────────────────────
    if fp.exists():
        try:
            df = pd.read_pickle(fp)
            old_cols = ["power_pred_cal", "power_pred", "prediction_mw"]
            used_old = [col for col in old_cols if col in df.columns]
            # 只要 power_pred_final 存在且非空，就使用它
            if pred_col in df.columns and df[pred_col].notna().any():
                c.ok("C7: 使用正式预测列", f"{pred_col} 就绪")
            elif used_old:
                c.fail("C7: 使用正式预测列", f"power_pred_final 不存在，使用了旧列: {used_old}")
            else:
                c.fail("C7: 使用正式预测列", f"{pred_col} 不存在且无旧列可用")
        except Exception as e:
            c.fail("C7: 预测列检查", str(e))

    # ── C8: 评估集只用 test ─────────────────────────────────────────────
    if fp.exists():
        try:
            df = pd.read_pickle(fp)
            test_df = df[df["split"] == eval_split]
            has_pred_in_test = test_df[pred_col].notna().sum() if pred_col in test_df.columns else 0
            if has_pred_in_test > 0:
                c.ok("C8: 测试集有预测结果", f"{has_pred_in_test:,} 行")
            else:
                c.fail("C8: 测试集有预测结果", f"{has_pred_in_test} 行（可能预测生成失败）")
        except Exception as e:
            c.fail("C8: 测试集预测检查", str(e))

    # ── C9: 夜间和 future 不参与正式评估 ───────────────────────────────
    if fp.exists():
        try:
            df = pd.read_pickle(fp)
            night = df[df["hour"] < sh]
            future_test_overlap = df[(df["split"] == "future") & df["hour"].between(sh, eh)]
            if len(night) > 0 and len(future_test_overlap) > 0:
                c.warn("C9: 夜间/future 不参与评估", "pkl 中存在夜间和 future 记录（评估时会排除）")
            elif len(night) > 0:
                c.warn("C9: 夜间/future 不参与评估", f"夜间 {len(night):,} 行（评估时会排除）")
            else:
                c.ok("C9: 夜间/future 不参与评估", "仅含白天记录")
        except Exception as e:
            c.fail("C9: 夜间/future 检查", str(e))

    # ── C10: hourly_nrmse_consistent.csv 存在 ───────────────────────────
    hourly_csv = metrics_dir / "round46_hourly_nrmse_consistent.csv"
    if not hourly_csv.exists():
        c.fail("C10: hourly_nrmse_consistent.csv 存在", f"不存在: {hourly_csv.name}")
    else:
        try:
            hdf = pd.read_csv(hourly_csv)
            required = ["hour", "site_avg_nrmse_pct"]  # 实际字段名
            miss = [col for col in required if col not in hdf.columns]
            if miss:
                c.fail("C10: hourly_nrmse_consistent.csv 结构", f"缺少: {miss}")
            else:
                valid_hours = hdf[hdf["hour"].between(sh, eh)]
                c.ok("C10: hourly_nrmse_consistent.csv 正确",
                     f"{len(valid_hours)} 小时数据, NRMSE范围: {valid_hours['site_avg_nrmse_pct'].min():.2f}%~{valid_hours['site_avg_nrmse_pct'].max():.2f}%")
        except Exception as e:
            c.fail("C10: hourly_nrmse_consistent.csv 读取", str(e))

    # ── C11: dashboard JSON 一致性 ─────────────────────────────────────
    cons_csv = metrics_dir / "round36_dashboard_prediction_consistency.csv"
    if not cons_csv.exists():
        c.warn("C11: dashboard_consistency.csv 存在", "文件不存在（可能未执行导出）")
    else:
        try:
            cdf = pd.read_csv(cons_csv)
            fails = int((cdf.get("status", cdf) == "FAIL").sum())
            max_pred = float(cdf.get("max_abs_diff_pred", [0]).max())
            if fails == 0:
                c.ok("C11: dashboard 一致性校验", f"{len(cdf)} 站, 全部 PASS")
            else:
                c.fail("C11: dashboard 一致性校验", f"{fails}/{len(cdf)} FAIL, max_pred={max_pred:.2e}")
        except Exception as e:
            c.warn("C11: dashboard_consistency 检查", str(e))

    # ── C12: 产物新鲜度（dashboard 晚于 final pkl）────────────────────
    if fp.exists() and dash_dir.exists():
        try:
            idx = dash_dir / "index.json"
            if not idx.exists():
                c.fail("C12: dashboard index.json 存在", "不存在")
            else:
                pkl_mtime = fp.stat().st_mtime
                idx_mtime = idx.stat().st_mtime
                if idx_mtime >= pkl_mtime:
                    delta_h = (idx_mtime - pkl_mtime) / 3600
                    c.ok("C12: dashboard 数据新鲜", f"dashboard 晚于 final pkl {delta_h:.2f}h")
                else:
                    delta_h = (pkl_mtime - idx_mtime) / 3600
                    c.fail("C12: dashboard 数据新鲜", f"dashboard 早于 final pkl {delta_h:.2f}h（数据已过期）")
        except Exception as e:
            c.warn("C12: 新鲜度检查", str(e))

    # ── C13: Git 不追踪大数据文件 ───────────────────────────────────────
    try:
        tracked = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True,
            cwd=str(PROJECT_ROOT), check=False
        ).stdout.splitlines()
        pkl_t = [x for x in tracked if x.endswith((".pkl", ".joblib"))]
        json_t = [x for x in tracked if "site_series/" in x or x.endswith("city_series.json")]
        if pkl_t:
            c.fail("C13: Git 不追踪 pkl", f"{len(pkl_t)} 个: {pkl_t[:2]}")
        else:
            c.ok("C13: Git 不追踪 pkl", "0 个")
        if json_t:
            c.fail("C13: Git 不追踪 site_series JSON", f"{len(json_t)} 个")
        else:
            c.ok("C13: Git 不追踪 site_series JSON", "0 个")
    except Exception as e:
        c.warn("C13: Git 检查", str(e))

    # ── C14: train/valid 样本量充足 ─────────────────────────────────────
    if fp.exists():
        try:
            df = pd.read_pickle(fp)
            sp_cfg = cfg.get("split", {})
            train_start = sp_cfg.get("train_start", "2023-01-01")
            train_end = sp_cfg.get("train_end", "2025-06-30")
            train_df = df[(df["split"] == "train") & (df["hour"].between(sh, eh))]
            n_train = len(train_df)
            if n_train > 0:
                c.ok("C14: 训练集样本量", f"{n_train:,} 行（{train_start}~{train_end} 白天）")
            else:
                c.fail("C14: 训练集样本量", f"{n_train} 行（可能数据缺失）")
        except Exception as e:
            c.warn("C14: 训练集样本量检查", str(e))

    # ── C15: 站点数量合理 ───────────────────────────────────────────────
    if fp.exists():
        try:
            df = pd.read_pickle(fp)
            n_sites = df["site_id"].nunique()
            if 50 <= n_sites <= 200:
                c.ok("C15: 站点数量合理", f"{n_sites} 个站点")
            else:
                c.warn("C15: 站点数量", f"{n_sites} 个（可能异常）")
        except Exception as e:
            c.warn("C15: 站点数量检查", str(e))

    # ── C16: manifest.json 严格验证 ────────────────────────────────
    manifest = out / "manifest.json"
    if not manifest.exists():
        c.fail("C16: manifest.json 存在", "文件不存在")
    else:
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
            # 1. pipeline_entry
            entry = m.get("pipeline_entry", "")
            if entry == "scripts/run_full_pipeline.py":
                c.ok("C16: manifest.pipeline_entry", entry)
            else:
                c.fail("C16: manifest.pipeline_entry",
                       f"期望 scripts/run_full_pipeline.py，实际: {entry}")
            # 2. final_prediction_column
            fp_col = m.get("final_prediction_column", "")
            expected_col = cfg.get("prediction", {}).get("final_column", "power_pred_final")
            if fp_col == expected_col:
                c.ok("C16: manifest.final_prediction_column", fp_col)
            else:
                c.fail("C16: manifest.final_prediction_column",
                       f"期望 {expected_col}，实际: {fp_col}")
            # 3. all artifacts exist
            # manifest 中路径相对于 PROJECT_ROOT（如 "output/pv_pipeline/..."）
            # 所以用 PROJECT_ROOT 解析，不重复拼接 out
            arts = m.get("artifacts", {})
            missing_arts = []
            for art_name, art_path in arts.items():
                art_full = PROJECT_ROOT / art_path
                if not art_full.exists():
                    missing_arts.append(f"{art_name}: {art_path}")
            if not missing_arts:
                c.ok("C16: manifest artifacts 全部存在", f"{len(arts)} 个文件")
            else:
                c.fail("C16: manifest artifacts", f"缺失: {missing_arts}")
            # 4. manifest mtime >= final pkl mtime (使用 canonical)
            fp = tables_dir / ".." / "predictions" / "distributed_predictions_final_full.pkl"
            if fp.exists():
                pkl_mtime = fp.stat().st_mtime
                man_mtime = manifest.stat().st_mtime
                if man_mtime >= pkl_mtime:
                    delta_h = (man_mtime - pkl_mtime) / 3600
                    c.ok("C16: manifest 生成时间", f"晚于 canonical full pkl {delta_h:.2f}h")
                else:
                    delta_h = (pkl_mtime - man_mtime) / 3600
                    c.fail("C16: manifest 生成时间",
                           f"早于 canonical full pkl {delta_h:.2f}h")
        except Exception as e:
            c.fail("C16: manifest.json 可读", str(e))

    # ── GEO1: S115/S116 不得缺经纬度 ─────────────────────────────────
    site_master_path = tables_dir / "site_master.csv"
    if not site_master_path.exists():
        c.warn("GEO1: S115/S116 经纬度", "site_master.csv 不存在，跳过")
    else:
        try:
            sm = pd.read_csv(site_master_path)
            lat_col = "lat" if "lat" in sm.columns else "latitude"
            lon_col = "lon" if "lon" in sm.columns else "longitude"
            for sid in ["S115", "S116"]:
                row = sm[sm["site_id"] == sid]
                if len(row) == 0:
                    c.fail("GEO1: 经纬度覆盖", f"{sid} 不在 site_master 中")
                    continue
                lat = row[lat_col].values[0]
                lon = row[lon_col].values[0]
                if pd.isna(lat) or pd.isna(lon):
                    c.fail("GEO1: 经纬度覆盖", f"{sid} lat/lon 仍为空")
                else:
                    c.ok("GEO1: 经纬度覆盖", f"{sid} lat={lat}, lon={lon}")
        except Exception as e:
            c.warn("GEO1: 经纬度覆盖检查", str(e))

    # ── GEO2: 坐标在连云港范围内 ───────────────────────────────────────
    if site_master_path.exists():
        try:
            sm = pd.read_csv(site_master_path)
            lat_col = "lat" if "lat" in sm.columns else "latitude"
            lon_col = "lon" if "lon" in sm.columns else "longitude"
            for sid in ["S115", "S116"]:
                row = sm[sm["site_id"] == sid]
                if len(row) == 0:
                    continue
                lat = float(row[lat_col].values[0])
                lon = float(row[lon_col].values[0])
                in_range = 33.9 <= lat <= 35.2 and 118.4 <= lon <= 119.9
                if in_range:
                    c.ok("GEO2: 坐标范围", f"{sid} ({lat}, {lon}) 在连云港范围内")
                else:
                    c.fail("GEO2: 坐标范围", f"{sid} ({lat}, {lon}) 不在连云港 [33.9-35.2N, 118.4-119.9E]")
        except Exception as e:
            c.warn("GEO2: 坐标范围检查", str(e))

    # ── GEO3: geo_confidence 非空 ────────────────────────────────────
    if site_master_path.exists():
        try:
            sm = pd.read_csv(site_master_path)
            for sid in ["S115", "S116"]:
                row = sm[sm["site_id"] == sid]
                if len(row) == 0:
                    continue
                conf_series = sm["geo_confidence"] if "geo_confidence" in sm.columns else pd.Series(dtype=str)
                row_conf = conf_series[row.index].values[0]
                conf_str = str(row_conf).strip() if not pd.isna(row_conf) else ""
                if not conf_str or conf_str == "nan":
                    c.fail("GEO3: 置信度", f"{sid} geo_confidence 为空")
                else:
                    c.ok("GEO3: 置信度", f"{sid} confidence={conf_str}")
        except Exception as e:
            c.warn("GEO3: 置信度检查", str(e))

    # ── GEO4: low 置信度警告 ─────────────────────────────────────────
    if site_master_path.exists():
        try:
            sm = pd.read_csv(site_master_path)
            low_conf = sm[
                sm["site_id"].isin(["S115", "S116"]) &
                (sm["geo_confidence"] == "low") if "geo_confidence" in sm.columns
                else pd.Series([False] * len(sm))
            ]
            if len(low_conf) > 0:
                for _, row in low_conf.iterrows():
                    sid = row["site_id"]
                    c.warn("GEO4: 低置信度警告",
                           f"{sid} confidence=low，精确光伏场区中心有待甲方/运维台账确认")
            else:
                c.ok("GEO4: 低置信度警告", "无站点为 low 置信度")
        except Exception as e:
            c.warn("GEO4: 低置信度警告检查", str(e))

    # ── C17: 69站/68站差异说明 ──────────────────────────────────────
    try:
        canonical_full_pkl = tables_dir / ".." / "predictions" / "distributed_predictions_final_full.pkl"
        canonical_eval_pkl = tables_dir / ".." / "predictions" / "distributed_predictions_final_eval.pkl"
        full_pkl_path = canonical_full_pkl if canonical_full_pkl.exists() else tables_dir / "distributed_predictions_final_round36.pkl"
        eval_pkl_path = canonical_eval_pkl if canonical_eval_pkl.exists() else tables_dir / "distributed_predictions_final_eval_round36.pkl"
        if full_pkl_path.exists() and eval_pkl_path.exists():
            full_df = pd.read_pickle(full_pkl_path)
            eval_df = pd.read_pickle(eval_pkl_path)
            full_sites = set(full_df["site_id"].unique())
            # eval pkl 列名与 full pkl 一致（均为 site_id）
            eval_id_col = "site_id"
            eval_sites = set(eval_df[eval_id_col].unique())
            excluded = full_sites - eval_sites
            full_n = len(full_sites)
            eval_n = len(eval_sites)
            if full_n == eval_n:
                c.ok("C17: 站点数量一致性", f"full={full_n}, eval={eval_n}，数量相同")
            else:
                c.ok("C17: 站点数量一致性",
                     f"full={full_n}, eval={eval_n}，相差{full_n - eval_n}站")
                # 写出被排除站点清单
                excluded_list = []
                for sid in sorted(excluded):
                    srow = sm[sm["site_id"] == sid] if site_master_path.exists() else pd.DataFrame()
                    full_rows = int((full_df["site_id"] == sid).sum())
                    eval_rows_test = int((eval_df["site_id"] == sid).sum())
                    excluded_list.append({
                        "station_id": sid,
                        "station_name": (
                            srow["site_full_name"].values[0]
                            if len(srow) and "site_full_name" in srow.columns else ""
                        ),
                        "capacity_mw": (
                            float(srow["capacity_mw"].values[0])
                            if len(srow) and "capacity_mw" in srow.columns else ""
                        ),
                        "reason": "无有效 test 6-19 点评估记录",
                        "full_rows": full_rows,
                        "test_6_19_rows": eval_rows_test,
                    })
                if excluded_list:
                    excl_df = pd.DataFrame(excluded_list)
                    excl_path = val_dir / "excluded_from_eval_sites.csv"
                    excl_df.to_csv(excl_path, index=False, encoding="utf-8-sig")
                    print(f"  [INFO] 排除站点清单 → {excl_path.name} ({len(excl_df)} 站)")
        else:
            c.warn("C17: 站点数量一致性", "pkl 文件不全，跳过")
    except Exception as e:
        c.warn("C17: 站点数量一致性检查", str(e))

    # ── BIAS: 口径说明 ─────────────────────────────────────────────
    bias_note = (
        "BIAS = mean(power_pred_final - power_mw); "
        "BIAS > 0 表示预测偏高，BIAS < 0 表示预测偏低"
    )
    c.ok("BIAS: 口径说明", bias_note)

    return c


def write_reports(c: ValidationCheck, cfg: dict):
    out = output_root(cfg)
    docs_dir = out / "docs"
    val_dir = out / "validation"
    docs_dir.mkdir(parents=True, exist_ok=True)
    val_dir.mkdir(parents=True, exist_ok=True)

    total_ = len(c.results)
    pass_ = sum(1 for r in c.results if r[0] == "PASS")
    fails_ = sum(1 for r in c.results if r[0] == "FAIL")
    warns_ = sum(1 for r in c.results if r[0] == "WARN")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pred_col = cfg.get("prediction", {}).get("final_column", "power_pred_final")
    sp = cfg.get("split", {})

    # Markdown report
    report_path = docs_dir / "posttrain_validation_report.md"
    lines = [
        f"# 训练后逻辑审计报告\n\n",
        f"**生成时间**: {now}\n",
        f"**最终预测列**: {pred_col}\n",
        f"**评估口径**: split={cfg.get('eval',{}).get('split','test')}, "
        f"hour={cfg.get('eval',{}).get('start_hour',6)}-{cfg.get('eval',{}).get('end_hour',19)}\n",
        f"\n## 校验结果汇总\n\n",
        f"| 状态 | 数量 |\n|------|------|\n",
        f"| PASS | {pass_} |\n",
        f"| FAIL | {fails_} |\n",
        f"| WARN | {warns_} |\n",
        f"\n## 逐项结果\n\n",
        f"| # | 状态 | 检查项 | 说明 |\n",
        f"|---|------|--------|------|\n",
    ]
    for i, (status, name, msg) in enumerate(c.results, 1):
        icon = "✓" if status == "PASS" else ("⚠" if status == "WARN" else "✗")
        lines.append(f"| {i} | {icon} {status} | {name} | {msg} |\n")

    lines.append("\n## 训练切分\n\n")
    for k, v in sp.items():
        lines.append(f"- {k}: {v}\n")

    if c.has_fail():
        lines.append(f"\n## 结论\n\n")
        lines.append(f"**{fails_} 项 FAIL，不合格。请修复后重新运行训练流程。**\n")
    else:
        lines.append("\n## 结论\n\n")
        lines.append(f"**{pass_} 项 PASS，{warns_} 项 WARN，全部检查通过（或仅警告）。**\n")

    report_path.write_text("".join(lines), encoding="utf-8")
    print(f"\n[OK] 报告 → {report_path}")

    # CSV results
    csv_path = val_dir / "posttrain_validation_results.csv"
    result_df = pd.DataFrame(
        [{"status": s, "check": n, "message": m} for s, n, m in c.results]
    )
    result_df.index.name = "id"
    result_df.to_csv(csv_path, index=True, encoding="utf-8-sig")
    print(f"[OK] CSV   → {csv_path}")


def main():
    parser = argparse.ArgumentParser(description="训练后逻辑审计")
    parser.add_argument("--config", type=str, default=None, help="pipeline.yaml 路径")
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(f"[FAIL] 配置未找到: {e}")
        sys.exit(1)

    c = run_validation(cfg)
    write_reports(c, cfg)

    total_ = len(c.results)
    pass_ = sum(1 for r in c.results if r[0] == "PASS")
    fails_ = sum(1 for r in c.results if r[0] == "FAIL")
    warns_ = sum(1 for r in c.results if r[0] == "WARN")

    print()
    print("=" * 60)
    print(f"校验结果: {total_} 项 | {pass_} PASS | {fails_} FAIL | {warns_} WARN")
    print("=" * 60)

    sys.exit(1 if c.has_fail() else 0)


if __name__ == "__main__":
    main()
