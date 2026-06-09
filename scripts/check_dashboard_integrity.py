#!/usr/bin/env python3
"""
Round97_4 严格 Dashboard 完整性检查。
在 Round97_3 基础上新增：
  - typical_sites.json / typical_sites CSV 必须存在
  - hourly_prediction_summary.json 必须存在且覆盖 6-19h
  - metadata.optional_blocks 不得包含页面必需数据缺失标记

Round98_1 新增：
  - LFS 指针快速识别（避免 pd.read_pickle() 超时）
  - --allow-structure-only 模式：只做静态结构检查，不读取 PKL
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

_SRC = Path(__file__).resolve().parents[1] / "src"
if (_SRC / "pv_forecasting").exists():
    sys.path.insert(0, str(_SRC))


# ── pandas 3.x pickle 兼容 ─────────────────────────────────────────────────
_patch_done = False
def _apply_patch():
    global _patch_done
    if _patch_done:
        return
    _patch_done = True
    try:
        import functools
        import pandas.core.arrays.string_ as _sm
        _orig = _sm.StringDtype.__init__
        @functools.wraps(_orig)
        def _p(self, *a, **kw):
            try:
                _orig(self)
            except TypeError:
                object.__setattr__(self, 'dtype', None)
                object.__setattr__(self, 'storage', 'python')
        _sm.StringDtype.__init__ = _p
    except Exception:
        pass

_orig_read = pd.read_pickle
def _rp(*a, **kw):
    _apply_patch()
    return _orig_read(*a, **kw)


def _load_json(p: Path) -> dict | list:
    return json.loads(p.read_text(encoding="utf-8"))


# ── dashboard pred column resolution（与 export 脚本一致）────────────────────
def _build_full_history_frame(df: pd.DataFrame, pred_col_policy: str = "single_column") -> pd.DataFrame:
    """重建 dashboard 用的全历史 frame。

    policy=single_column: 全部使用 power_pred_final（Round97_4 确认 100% 覆盖）。
    policy=per_split: 按 split 优先级选择最优列。
    """
    HISTORY_SPLITS = ["train", "valid", "test"]
    out = df[df["split"].isin(HISTORY_SPLITS)].copy()

    for ts_col in ["datetime", "time", "timestamp", "date_time"]:
        if ts_col in out.columns:
            out = out.rename(columns={ts_col: "datetime"})
            break
    if "datetime" in out.columns:
        out["datetime"] = pd.to_datetime(out["datetime"], errors="coerce")
        if "hour" not in out.columns:
            out["hour"] = out["datetime"].dt.hour
        if "date" not in out.columns:
            out["date"] = out["datetime"].dt.strftime("%Y-%m-%d")

    if pred_col_policy == "single_column":
        out["pred_mw"] = out["power_pred_final"]
    else:
        _CANDIDATES = {
            "test":   ["power_pred_final", "power_pred", "power_pred_cal"],
            "valid":  ["power_pred_final", "power_pred", "power_pred_cal"],
            "train":  ["power_pred_cal", "pred_mw", "power_pred_raw"],
        }
        pred_col_by_split = {}
        for sp in set(out["split"].unique()):
            for col in _CANDIDATES.get(sp, _CANDIDATES["train"]):
                if col in out.columns and out[out["split"] == sp][col].notna().sum() > 0:
                    pred_col_by_split[sp] = col
                    break

        def pick_pred(row):
            col = pred_col_by_split.get(row["split"])
            return row.get(col) if col else None

        out["pred_mw"] = out.apply(pick_pred, axis=1)

    if "power_mw" in out.columns:
        out["actual_mw"] = out["power_mw"]

    return out


# ── 主检查函数 ──────────────────────────────────────────────────────────────
def check_dashboard_integrity(dashboard_root: str | Path, allow_structure_only: bool = False) -> None:
    root = Path(dashboard_root).resolve()
    errors: list[str] = []
    meta = None
    pred_col_policy = "single_column"   # 缺省

    if allow_structure_only:
        print("[STRUCTURE ONLY] 未核对 pkl，不代表预测值一致性通过")

    # ── 1. metadata.json ─────────────────────────────────────────────────
    meta_path = root / "metadata.json"
    if not meta_path.exists():
        errors.append(f"[ERROR] metadata.json 不存在: {meta_path}")
    else:
        try:
            meta = _load_json(meta_path)
            pred_col = meta.get("prediction_column", "")
            if pred_col != "power_pred_final":
                errors.append(f"[ERROR] prediction_column={pred_col}，期望 power_pred_final")
            if meta.get("contains_future") is True:
                errors.append("[ERROR] metadata contains_future=true，不允许")

            # Round97_4: 读取 policy
            raw_policy = meta.get("prediction_column_policy")
            if isinstance(raw_policy, dict):
                pred_col_policy = raw_policy.get("mode", "single_column")
                policy_col = raw_policy.get("column", "power_pred_final")
            else:
                pred_col_policy = str(raw_policy) if raw_policy else "single_column"
                policy_col = None
            print(f"[PASS] metadata.json ok  (prediction_column={pred_col}, policy={pred_col_policy})")

            # Round97_4: optional_blocks 不得包含页面必需数据缺失
            opt = meta.get("optional_blocks", {})
            page_required = ["typical_sites", "hourly_prediction_summary"]
            missing_req = [k for k in page_required if opt.get(k) == "missing"]
            if missing_req:
                errors.append(f"[ERROR] metadata optional_blocks 标记页面必需数据缺失（禁止）: {missing_req}")
            else:
                print(f"[PASS] metadata optional_blocks 无页面必需数据缺失")
        except Exception as e:
            errors.append(f"[ERROR] metadata.json 解析失败: {e}")

    # ── 2. index.json ────────────────────────────────────────────────────
    idx_path = root / "index.json"
    if not idx_path.exists():
        errors.append(f"[ERROR] index.json 不存在: {idx_path}")
    else:
        try:
            idx = _load_json(idx_path)
            total_rows = idx.get("total_rows", 0)
            if total_rows <= 0:
                errors.append(f"[ERROR] index.json total_rows={total_rows}，无数据")
            else:
                print(f"[PASS] index.json ok  (total_rows={total_rows})")
        except Exception as e:
            errors.append(f"[ERROR] index.json 解析失败: {e}")

    # ── 3. site_series/ 数量 ────────────────────────────────────────────
    site_dir = root / "site_series"
    if not site_dir.exists():
        errors.append(f"[ERROR] site_series/ 目录不存在: {site_dir}")
    else:
        site_jsons = sorted(site_dir.glob("*.json"))
        site_count = len(site_jsons)
        if site_count < 60:
            errors.append(f"[ERROR] site_series/ 仅 {site_count} 个文件，期望至少 60 个")
        else:
            print(f"[PASS] site_series/ count={site_count}  (>= 60)")

    # ── 4. 禁止占位数据 ─────────────────────────────────────────────────
    if site_dir.exists():
        bad_files = []
        for p in site_dir.glob("*.json"):
            text = p.read_text(encoding="utf-8")
            if any(kw in text for kw in ['"stale": true', '"placeholder": true', '"pending"']):
                bad_files.append(p.name)
        if bad_files:
            errors.append(f"[ERROR] 发现占位 site_series JSON，不允许发布：{bad_files[:10]}")
        else:
            print(f"[PASS] 无占位数据（stale/placeholder/pending 0 个）")

    # ── 5. typical_sites.json 必须存在（Round97_4 新增）──────────────────
    ts_path = root / "typical_sites.json"
    if not ts_path.exists():
        errors.append(f"[ERROR] typical_sites.json 不存在（页面必需数据）")
    else:
        try:
            ts_data = _load_json(ts_path)
            if isinstance(ts_data, list) and len(ts_data) >= 10:
                print(f"[PASS] typical_sites.json ok  rows={len(ts_data)}")
            elif isinstance(ts_data, dict) and ts_data:
                print(f"[PASS] typical_sites.json ok  keys={list(ts_data.keys())}")
            else:
                errors.append(f"[ERROR] typical_sites.json 内容异常（rows={len(ts_data) if isinstance(ts_data, list) else 'dict'}")
        except Exception as e:
            errors.append(f"[ERROR] typical_sites.json 解析失败: {e}")

    # ── 6. hourly_prediction_summary.json 必须存在且覆盖 6-19h（Round97_4 新增）─
    hp_path = root / "hourly_prediction_summary.json"
    if not hp_path.exists():
        errors.append(f"[ERROR] hourly_prediction_summary.json 不存在（页面必需数据）")
    else:
        try:
            hp_data = _load_json(hp_path)
            if not hp_data:
                errors.append("[ERROR] hourly_prediction_summary.json 内容为空")
            else:
                hours = {int(r["hour"]) for r in hp_data if "hour" in r}
                expected = set(range(6, 20))
                if expected.issubset(hours):
                    print(f"[PASS] hourly_prediction_summary.json ok  hours={min(hours)}-{max(hours)} rows={len(hp_data)}")
                else:
                    missing_hours = expected - hours
                    errors.append(f"[ERROR] hourly_prediction_summary.json 缺少小时: {sorted(missing_hours)}")
        except Exception as e:
            errors.append(f"[ERROR] hourly_prediction_summary.json 解析失败: {e}")

    # ── 7. 抽样检查站点 JSON 结构 ──────────────────────────────────────
    if site_dir.exists():
        for p in sorted(site_dir.glob("*.json"))[:3]:
            try:
                data = _load_json(p)
                if isinstance(data, dict):
                    errors.append(f"[ERROR] {p.name} 是 dict 而非 list（占位数据）")
                    continue
                records = data
                if not isinstance(records, list) or len(records) == 0:
                    errors.append(f"[ERROR] {p.name} 为空或格式错误")
                    continue
                first = records[0]
                for field in ("actual_mw", "pred_mw"):
                    if field not in first:
                        errors.append(f"[ERROR] {p.name} 缺少字段 {field}")
                print(f"[PASS] {p.name} 结构正常（{len(records)} 条记录）")
            except Exception as e:
                errors.append(f"[ERROR] {p.name} 解析失败: {e}")

    # ── 8. 加载 PKL ────────────────────────────────────────────────────
    output_root = root.parent
    pred_dir = output_root / "predictions"
    tables_dir = output_root / "tables"
    pkl_path = None
    if (pred_dir / "distributed_predictions_final_full.pkl").exists():
        pkl_path = pred_dir / "distributed_predictions_final_full.pkl"
    elif (tables_dir / "distributed_predictions_final_full.pkl").exists():
        pkl_path = tables_dir / "distributed_predictions_final_full.pkl"
    else:
        import glob
        candidates = sorted(
            Path(pp) for pp in
            glob.glob(str(pred_dir / "distributed_predictions_final_round*.pkl")) +
            glob.glob(str(tables_dir / "distributed_predictions_final_round*.pkl"))
        )
        if candidates:
            pkl_path = max(candidates, key=lambda p: p.stat().st_mtime)

    df_pkl = None
    # Round98_1: structure-only 模式跳过 PKL 读取
    if allow_structure_only:
        print("[STRUCTURE ONLY] 跳过 PKL 读取（--allow-structure-only 模式）")
    elif pkl_path:
        # Round98_1: LFS 指针必须快速失败，不执行 pd.read_pickle()
        from pv_forecasting.core.file_checks import is_lfs_pointer
        if is_lfs_pointer(pkl_path):
            errors.append(
                f"[ERROR] {pkl_path.name} 是 Git LFS 指针，不是真实 PKL。"
                "如果这是训练前检查，请用 --allow-structure-only；"
                "如果这是训练后检查，说明训练结果未生成。"
            )
        else:
            try:
                df_pkl = _rp(str(pkl_path))
                ts_col = "datetime" if "datetime" in df_pkl.columns else "time"
                df_pkl["datetime"] = pd.to_datetime(df_pkl[ts_col], errors="coerce")
                print(f"[INFO] PKL: {pkl_path.name}  {len(df_pkl):,} 行, "
                      f"站点 {df_pkl['site_id'].nunique()}, splits={sorted(df_pkl['split'].unique().tolist())}")
            except Exception as e:
                errors.append(f"[ERROR] PKL 读取失败: {pkl_path.name} → {e}")
                df_pkl = None
    else:
        print("[INFO] 未找到预测 PKL，跳过 actual/pred 核对")

    # ── 8a. actual_mw 抽样核对 ──────────────────────────────────────────
    if df_pkl is not None and site_dir.exists():
        print("\n  [actual_mw 抽样核对] 抽样 3 站点 × 20 条 ...")
        for p in sorted(site_dir.glob("*.json"))[:3]:
            site_id = p.stem
            if site_id not in df_pkl["site_id"].values:
                print(f"  [WARN] {site_id} 不在 PKL，跳过")
                continue
            try:
                records = _load_json(p)
            except Exception:
                continue
            if not records:
                continue
            sample_recs = [r for r in records
                           if r.get("hour", 0) in range(6, 20) and r.get("actual_mw", 0) > 0][:20]
            max_diff = 0.0
            for rec in sample_recs:
                ts = pd.to_datetime(rec.get("time", ""), errors="coerce")
                if pd.isna(ts):
                    continue
                row = df_pkl[(df_pkl["site_id"] == site_id) & (df_pkl["datetime"] == ts)]
                if len(row) == 0:
                    continue
                diff = abs(float(row.iloc[0]["power_mw"]) - float(rec["actual_mw"]))
                if diff > max_diff:
                    max_diff = diff
            if max_diff > 1e-6:
                errors.append(f"[ERROR] {site_id} actual_mw 最大差值 {max_diff:.6f} > 1e-6")
            else:
                print(f"  [PASS] {site_id} actual_mw 一致  max_diff={max_diff:.2e}")

    # ── 8b. pred_mw 抽样核对 ───────────────────────────────────────────
    if df_pkl is not None and site_dir.exists():
        print("\n  [pred_mw 抽样核对] 抽样 3 站点 × 20 条 ...")
        df_full = _build_full_history_frame(df_pkl, pred_col_policy=pred_col_policy)
        for p in sorted(site_dir.glob("*.json"))[:3]:
            site_id = p.stem
            if site_id not in df_full["site_id"].values:
                print(f"  [WARN] {site_id} 不在 PKL，跳过")
                continue
            try:
                records = _load_json(p)
            except Exception:
                continue
            if not records:
                continue
            max_diff = 0.0
            splits_seen = set()
            for rec in [r for r in records if r.get("hour", 0) in range(6, 20)][:20]:
                split = str(rec.get("split", "")).lower()
                if split in ("train", "valid", "test"):
                    splits_seen.add(split)
                ts = pd.to_datetime(rec.get("time", ""), errors="coerce")
                if pd.isna(ts):
                    continue
                row = df_full[(df_full["site_id"] == site_id) & (df_full["datetime"] == ts)]
                if len(row) == 0:
                    continue
                pkl_val = row.iloc[0]["pred_mw"]
                json_val = rec.get("pred_mw")
                if pd.isna(pkl_val) or json_val is None:
                    continue
                diff = abs(float(pkl_val) - float(json_val))
                if diff > max_diff:
                    max_diff = diff
            splits_str = ",".join(sorted(splits_seen)) or "?"
            if max_diff > 1e-4:
                errors.append(f"[ERROR] {site_id} pred_mw 不一致  splits=[{splits_str}]  "
                             f"max_diff={max_diff:.6e} > 1e-4")
            else:
                print(f"  [PASS] {site_id} pred_mw 一致  splits=[{splits_str}]  max_diff={max_diff:.2e}")

    # ── 8c. city_series 聚合核对 ────────────────────────────────────────
    city_path = root / "city_series.json"
    if city_path.exists() and df_pkl is not None:
        print("\n  [city_series 聚合核对] 抽样 50 个时间点 ...")
        try:
            city_json = _load_json(city_path)
        except Exception as e:
            errors.append(f"[ERROR] city_series.json 读取失败: {e}")
            city_json = None

        if city_json and isinstance(city_json, list) and len(city_json) > 0:
            df_full = _build_full_history_frame(df_pkl, pred_col_policy=pred_col_policy)
            df_city_pkl = df_full[
                df_full["split"].isin(["train", "valid", "test"]) &
                df_full["pred_mw"].notna() & df_full["actual_mw"].notna()
            ].groupby("datetime").agg(
                pkl_actual=("actual_mw", "sum"),
                pkl_pred=("pred_mw", "sum"),
            ).reset_index()

            sample_times = (
                df_city_pkl.sample(n=50, random_state=42)["datetime"].tolist()
                if len(df_city_pkl) >= 50
                else df_city_pkl["datetime"].tolist()
            )

            max_da, max_dp = 0.0, 0.0
            for ts in sample_times:
                pkl_row = df_city_pkl[df_city_pkl["datetime"] == ts]
                if len(pkl_row) == 0:
                    continue
                ts_str = str(ts)
                json_row = next(
                    (r for r in city_json if r.get("datetime") == ts_str or r.get("time") == ts_str),
                    None
                )
                if json_row is None:
                    hour = pd.to_datetime(ts).hour
                    date = pd.to_datetime(ts).strftime("%Y-%m-%d")
                    json_row = next(
                        (r for r in city_json if r.get("date") == date and r.get("hour") == hour),
                        None
                    )
                if json_row is None:
                    continue
                da = abs(float(pkl_row.iloc[0]["pkl_actual"]) - float(json_row.get("actual_mw", 0)))
                dp = abs(float(pkl_row.iloc[0]["pkl_pred"]) - float(json_row.get("pred_mw", 0)))
                if da > max_da: max_da = da
                if dp > max_dp: max_dp = dp

            if max_da > 1e-8:
                errors.append(f"[ERROR] city_series actual_mw 最大差值 {max_da:.6e} > 1e-8")
            else:
                print(f"  [PASS] city_series actual_mw 一致  max_diff={max_da:.2e}")
            if max_dp > 1e-4:
                errors.append(f"[ERROR] city_series pred_mw 最大差值 {max_dp:.6e} > 1e-4")
            else:
                print(f"  [PASS] city_series pred_mw 一致  max_diff={max_dp:.2e}")
        else:
            print("  [INFO] city_series.json 格式异常，跳过 city 聚合核对")
    elif not city_path.exists():
        print("  [INFO] city_series.json 不存在，跳过 city 聚合核对")

    # ── 9. 汇总 ─────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    if errors:
        print(f"❌ Dashboard 完整性检查失败，共 {len(errors)} 个错误:")
        for e in errors:
            print(f"   {e}")
        raise SystemExit(1)
    else:
        print("✅ Dashboard 完整性检查全部通过！")
        print("=" * 60)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Round97_4 Dashboard 完整性检查")
    parser.add_argument(
        "--dashboard-root",
        type=str,
        default="output/pv_pipeline/interactive_dashboard",
        help="Dashboard 根目录",
    )
    parser.add_argument(
        "--allow-structure-only",
        action="store_true",
        help=(
            "只做静态结构检查，不读取 PKL。"
            "只能用于训练前快速确认页面文件存在，不能作为训练后通过依据。"
        ),
    )
    args = parser.parse_args()
    print("=" * 60)
    print("Round97_4 Dashboard 完整性检查（含 typical_sites + hourly_prediction_summary）")
    print("=" * 60)
    print(f"Dashboard: {args.dashboard_root}")
    if args.allow_structure_only:
        print("[STRUCTURE ONLY] 模式：不读取 PKL，不代表预测值一致性通过")
    print()
    check_dashboard_integrity(args.dashboard_root, allow_structure_only=args.allow_structure_only)


if __name__ == "__main__":
    main()
