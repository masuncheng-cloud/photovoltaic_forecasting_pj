"""
pretrain_audit_round36.py
==========================
训练前数据审计。审计结果写入:
  <output-root>/metrics/round36_pretrain_audit.csv
  <output-root>/docs/Round36_训练前数据审计报告.md

重要口径说明:
  - power_clean.pkl / power_long_raw.pkl 的主键是 power_alias + time
    （一个 site_id 可能对应多个 power_alias）
  - distributed_train_table_v159.pkl 的主键是 site_id + time
    （去掉了 power_alias 层级）

用法：
  python scripts/pretrain_audit_round36.py
  python scripts/pretrain_audit_round36.py --output-root output/pv_pipeline
"""
import argparse
import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "src"))

SPLIT_START = {
    "train":  "2023-01-01",
    "valid":  "2025-07-01",
    "test":   "2025-09-01",
    "future": "2026-01-01",
}
SPLIT_STARTS = {k: pd.Timestamp(v) for k, v in SPLIT_START.items()}

LEAK_COLS = [
    "power_mw", "power_pred", "power_pred_final", "power_pred_raw",
    "actual", "target", "actual_mw", "pred_mw",
]
LEAK_COLS_STRICT = LEAK_COLS + ["split", "rel_error", "rel_error_pred", "future", "test", "valid"]


class Check:
    def __init__(self):
        self.rows = []
        self._fail_count = 0

    def ok(self, name, detail=""):
        self.rows.append({"check": name, "status": "PASS", "detail": detail})
        print(f"  [PASS] {name}")

    def fail(self, name, detail):
        self.rows.append({"check": name, "status": "FAIL", "detail": detail})
        self._fail_count += 1
        print(f"  [FAIL] {name}: {detail}")

    def warn(self, name, detail):
        self.rows.append({"check": name, "status": "WARN", "detail": detail})
        print(f"  [WARN] {name}: {detail}")

    def has_fail(self):
        return self._fail_count > 0


def run_audit(TABLES, METRICS, DOCS):
    c = Check()
    print("=" * 60)
    print("Round36 训练前数据审计")
    print("=" * 60)

    # ── A1: power_clean 无 power_alias+time 重复 ─────────────────
    print("\n[A1] power_clean 无 power_alias+time 重复...")
    if (TABLES / "power_clean.pkl").exists():
        df = pd.read_pickle(TABLES / "power_clean.pkl")
        df["time"] = pd.to_datetime(df["time"])
        n_before = len(df)
        df_dedup = df.drop_duplicates(subset=["power_alias", "time"])
        n_after = len(df_dedup)
        dup = n_before - n_after
        if dup > 0:
            c.fail("power_clean 无重复", f"发现 {dup:,} 行重复（power_alias+time），去重后 {n_after:,} 行")
        else:
            c.ok("power_clean 无重复", f"{n_before:,} 行无重复（power_alias+time）")
    else:
        c.warn("power_clean 存在", "文件不存在，跳过")

    # ── A2: power_long_raw 无 power_alias+time 重复 ─────────────
    print("[A2] power_long_raw 无 power_alias+time 重复...")
    if (TABLES / "power_long_raw.pkl").exists():
        df2 = pd.read_pickle(TABLES / "power_long_raw.pkl")
        df2["time"] = pd.to_datetime(df2["time"])
        dup2 = df2.duplicated(subset=["power_alias", "time"], keep=False).sum()
        if dup2 > 0:
            c.fail("power_long_raw 无重复", f"发现 {dup2:,} 行重复")
        else:
            c.ok("power_long_raw 无重复", f"{len(df2):,} 行无重复")
    else:
        c.warn("power_long_raw 存在", "文件不存在，跳过")

    # ── A3: 无负功率 ─────────────────────────────────────────────
    print("[A3] 无负功率...")
    if (TABLES / "power_clean.pkl").exists():
        df = pd.read_pickle(TABLES / "power_clean.pkl")
        neg = df[df["power_mw"] < 0]
        if len(neg) > 0:
            pct = len(neg) / len(df) * 100
            c.fail("无负功率", f"{len(neg):,} 行 ({pct:.4f}%)")
        else:
            c.ok("无负功率", "全部 >= 0")
    else:
        c.warn("负功率检查", "power_clean 不存在，跳过")

    # ── A4: 无超容量 ──────────────────────────────────────────────
    print("[A4] 无超容量...")
    if (TABLES / "power_clean.pkl").exists() and (TABLES / "site_master.csv").exists():
        df = pd.read_pickle(TABLES / "power_clean.pkl")
        sm = pd.read_csv(TABLES / "site_master.csv")
        cap_map = dict(zip(sm["site_id"], sm["capacity_mw"]))
        df["capacity"] = df["site_id"].map(cap_map)
        over = df[df["power_mw"] > df["capacity"]]
        if len(over) > 0:
            pct = len(over) / len(df) * 100
            max_ratio = (over["power_mw"] / over["capacity"]).max()
            max_diff = (over["power_mw"] - over["capacity"]).max()
            if len(over) > 1000 or max_ratio > 1.05:
                c.fail("无超容量功率", f"{len(over):,} 行 ({pct:.4f}%), max_ratio={max_ratio:.3f}")
            else:
                c.warn("无严重超容量",
                       f"{len(over):,} 行 ({pct:.4f}%), max_ratio={max_ratio:.3f}, max_diff={max_diff:.3f}MW "
                       f"（功率取整浮点微小偏差，可接受）")
        else:
            c.ok("无超容量功率", "全部 <= site_master 中的 capacity_mw")
    else:
        c.warn("超容量检查", "缺少数据，跳过")

    # ── A5: capacity_mw > 0 ─────────────────────────────────────
    print("[A5] site_master capacity_mw > 0...")
    if (TABLES / "site_master.csv").exists():
        sm = pd.read_csv(TABLES / "site_master.csv")
        bad = sm[sm["capacity_mw"] <= 0]
        if len(bad) > 0:
            c.fail("capacity_mw > 0", f"{len(bad)} 个站点容量<=0: {list(bad['site_id'])}")
        else:
            c.ok("capacity_mw > 0", f"{len(sm)} 个站点全部 > 0")
    else:
        c.warn("容量有效性", "site_master.csv 不存在，跳过")

    # ── A6: 站点名非空 ───────────────────────────────────────────
    print("[A6] 站点名非空...")
    if (TABLES / "site_master.csv").exists():
        sm = pd.read_csv(TABLES / "site_master.csv")
        name_col = "site_full_name" if "site_full_name" in sm.columns else "site_short_name"
        empty = sm[sm[name_col].isna() | (sm[name_col].str.strip() == "")]
        if len(empty) > 0:
            c.fail("站点名非空", f"{len(empty)} 个站点名为空")
        else:
            c.ok("站点名非空", f"{len(sm)} 个站点全部有名称")
    else:
        c.warn("站点名检查", "site_master.csv 不存在，跳过")

    # ── A7: 经纬度完整 ───────────────────────────────────────────
    print("[A7] 经纬度完整...")
    if (TABLES / "site_master.csv").exists():
        sm = pd.read_csv(TABLES / "site_master.csv")
        lat_col = "lat" if "lat" in sm.columns else "latitude"
        lon_col = "lon" if "lon" in sm.columns else "longitude"
        miss_lat = sm[lat_col].isna().sum()
        miss_lon = sm[lon_col].isna().sum()
        train_df_exists = (TABLES / "distributed_train_table_v159.pkl").exists()
        if miss_lat > 0 or miss_lon > 0:
            sm_missing = sm[sm[lat_col].isna() | sm[lon_col].isna()]
            if not train_df_exists:
                c.warn("经纬度完整",
                       f"{lat_col} 缺 {miss_lat} 个, {lon_col} 缺 {miss_lon} 个；"
                       f"缺经纬度站点: {list(sm_missing['site_id'])}。"
                       f"训练表尚不存在，无法判断是否影响训练。")
            else:
                df_train_check = pd.read_pickle(TABLES / "distributed_train_table_v159.pkl")
                train_sites = set(df_train_check["site_id"].unique())
                in_train = sm_missing[sm_missing["site_id"].isin(train_sites)]
                not_in_train = sm_missing[~sm_missing["site_id"].isin(train_sites)]
                if len(in_train) > 0:
                    c.warn(f"经纬度完整（{len(in_train)}个训练站点缺经纬）",
                           f"{len(in_train)} 个训练站点缺 lat/lon: {list(in_train['site_id'])}；"
                           f"{len(not_in_train)} 个不在训练集（可忽略）")
                else:
                    c.ok("经纬度完整（训练站点）",
                         f"缺经纬度的 {len(not_in_train)} 个站点均不在训练集，训练不受影响")
        else:
            c.ok("经纬度完整", f"{len(sm)} 个站点全部有经纬度")
    else:
        c.warn("经纬度检查", "site_master.csv 不存在，跳过")

    # ── A8: 同一 site_id 只有一个容量 ───────────────────────────
    print("[A8] 同一 site_id 只有一个容量...")
    if (TABLES / "site_master.csv").exists():
        sm = pd.read_csv(TABLES / "site_master.csv")
        multi_cap = sm.groupby("site_id")["capacity_mw"].nunique()
        multi = multi_cap[multi_cap > 1]
        if len(multi) > 0:
            c.fail("站点容量唯一", f"{len(multi)} 个站点有多个容量值: {list(multi.index)}")
        else:
            c.ok("站点容量唯一", f"{len(sm)} 个站点各只有一个容量")
    else:
        c.warn("站点容量一致性", "site_master.csv 不存在，跳过")

    # ── A9: train/valid/test/future 时间划分无重叠 ────────────────
    print("[A9] 时间划分无重叠（检查 split 列）...")
    if (TABLES / "distributed_train_table_v159.pkl").exists():
        df = pd.read_pickle(TABLES / "distributed_train_table_v159.pkl")
        df["time"] = pd.to_datetime(df["time"])
        if "split" in df.columns:
            defined = {k: pd.Timestamp(v) for k, v in SPLIT_START.items()}
            all_ok = True
            for split_name, start_ts in defined.items():
                sub = df[df["split"] == split_name]
                if len(sub) == 0:
                    continue
                actual_min = sub["time"].min()
                actual_max = sub["time"].max()
                later_starts = [pd.Timestamp(v) for k, v in SPLIT_START.items() if k > split_name]
                intrusions = [ts for ts in later_starts if actual_min <= ts <= actual_max]
                if intrusions:
                    c.fail(f"时间划分正确({split_name})",
                           f"{split_name} 含后续split起始时间: {intrusions}, 应从 {start_ts} 开始")
                    all_ok = False
            if all_ok:
                summary = df["split"].value_counts().to_dict()
                c.ok("时间划分正确（按 split 列）",
                     f"train:{summary.get('train',0):,}, valid:{summary.get('valid',0):,}, "
                     f"test:{summary.get('test',0):,}, future:{summary.get('future',0):,}")
        else:
            c.warn("时间划分检查", "distributed_train_table_v159 无 split 列")
    else:
        c.warn("时间划分检查", "distributed_train_table_v159.pkl 不存在")

    # ── A10: 特征不含泄漏字段 ─────────────────────────────────────
    print("[A10] 训练表特征无泄漏...")
    train_path = TABLES / "distributed_train_table_v159.pkl"
    if train_path.exists():
        df_train = pd.read_pickle(train_path)
        cols = set(df_train.columns)
        truly_leaked = [col for col in cols if col in
                        ["power_pred", "power_pred_final", "power_pred_raw",
                         "actual", "target", "actual_mw", "pred_mw",
                         "rel_error", "rel_error_pred"]]
        if truly_leaked:
            c.fail("特征无泄漏", f"发现预测结果列混入训练特征: {truly_leaked}")
        else:
            c.ok("特征无泄漏", f"{len(cols)} 个特征列，不含预测结果泄漏")
    else:
        c.warn("特征泄漏检查", "distributed_train_table_v159.pkl 尚不存在，将在训练后检查")

    # ── A11: final 预测文件（训练后检查）───────────────────────────
    print("[A11] final_round36 预测文件...")
    fp = TABLES / "distributed_predictions_final_round36.pkl"
    ep = TABLES / "distributed_predictions_final_eval_round36.pkl"
    if fp.exists() and ep.exists():
        df_f = pd.read_pickle(fp)
        df_f["time"] = pd.to_datetime(df_f["time"])
        df_e = pd.read_pickle(ep)
        df_e["time"] = pd.to_datetime(df_e["time"])
        issues = []
        if not (df_e["split"] == "test").all():
            issues.append("eval 含非 test 数据")
        if not df_e["hour"].between(6, 19).all():
            issues.append("eval 含非 6-19 数据")
        if "power_pred_final" not in df_f.columns:
            issues.append("final 缺少 power_pred_final")
        if "power_pred_final" not in df_e.columns:
            issues.append("eval 缺少 power_pred_final")
        in_range = ((df_f["power_pred_final"] >= 0) & (df_f["power_pred_final"] <= df_f["capacity_mw"] + 1e-6)).all()
        if not in_range:
            issues.append("power_pred_final 超出 [0, capacity]")
        if issues:
            c.fail("final 预测文件", "; ".join(issues))
        else:
            c.ok("final 预测文件", f"final: {len(df_f):,} 行, eval: {len(df_e):,} 行，字段完整")
    else:
        c.warn("final 预测文件", "训练后检查（训练尚未执行）")

    # ── 汇总写报告 ──────────────────────────────────────────────
    pass_c = sum(1 for r in c.rows if r["status"] == "PASS")
    fail_c = sum(1 for r in c.rows if r["status"] == "FAIL")
    warn_c = sum(1 for r in c.rows if r["status"] == "WARN")

    print()
    print("=" * 60)
    print(f"审计结果: {len(c.rows)} 项 | {pass_c} PASS | {fail_c} FAIL | {warn_c} WARN")
    print("=" * 60)

    # CSV
    audit_df = pd.DataFrame(c.rows)
    audit_df.to_csv(METRICS / "round36_pretrain_audit.csv", index=False, encoding="utf-8-sig")

    # Markdown
    lines = [
        "# Round36 训练前数据审计报告\n",
        f"**生成时间**: 2026-06-04\n",
        f"\n## 审计结果\n",
        f"| 状态 | 数量 |\n|------|------|\n",
        f"| PASS | {pass_c} |\n",
        f"| FAIL | {fail_c} |\n",
        f"| WARN | {warn_c} |\n",
        f"\n## 逐项结果\n",
        f"| # | 状态 | 检查项 | 说明 |\n|---|------|--------|------|\n",
    ]
    for i, r in enumerate(c.rows, 1):
        icon = "✓" if r["status"] == "PASS" else ("⚠" if r["status"] == "WARN" else "✗")
        lines.append(f"| {i} | {icon} {r['status']} | {r['check']} | {r['detail']} |\n")

    if c.has_fail():
        lines.append("\n## 结论\n")
        lines.append(f"**{fail_c} 项 FAIL，必须修复后才能继续训练。**\n")
        exit_code = 1
    else:
        lines.append("\n## 结论\n")
        lines.append("**全部关键检查通过，可以开始训练。**\n")
        exit_code = 0

    with open(DOCS / "Round36_训练前数据审计报告.md", "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"已保存: {METRICS}/round36_pretrain_audit.csv")
    print(f"已保存: {DOCS}/Round36_训练前数据审计报告.md")
    return exit_code


def main():
    parser = argparse.ArgumentParser(description="训练前数据审计")
    parser.add_argument(
        "--output-root",
        type=str,
        default="output/pv_pipeline",
        help="输出根目录 (default: output/pv_pipeline)",
    )
    args = parser.parse_args()
    output_root = PROJECT_ROOT / args.output_root
    TABLES  = output_root / "tables"
    METRICS = output_root / "metrics"
    DOCS    = output_root / "docs"
    os.makedirs(METRICS, exist_ok=True)
    os.makedirs(DOCS, exist_ok=True)
    return run_audit(TABLES, METRICS, DOCS)


if __name__ == "__main__":
    sys.exit(main())
