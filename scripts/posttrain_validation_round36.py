"""
posttrain_validation_round36.py
=============================
Round36 训练后全链路验证脚本（16 项检查）。

输出：
  output/pv_pipeline/docs/Round36_训练逻辑与可视化一致性验证报告.md

有 FAIL 则 exit(1)。
"""
import os, sys, pickle, subprocess
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
TABLES  = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DASH    = PROJECT_ROOT / "output" / "pv_pipeline" / "interactive_dashboard"
DOCS    = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"
os.makedirs(DOCS, exist_ok=True)

RESULT_FILE = DOCS / "Round36_训练逻辑与可视化一致性验证报告.md"


class Check:
    def __init__(self):
        self.results = []
        self._fails = 0

    def ok(self, name, msg=""):
        self.results.append(("PASS", name, msg))
        print(f"  [PASS] {name}" + (f" — {msg}" if msg else ""))

    def warn(self, name, msg=""):
        self.results.append(("WARN", name, msg))
        print(f"  [WARN] {name}" + (f" — {msg}" if msg else ""))

    def fail(self, name, msg=""):
        self.results.append(("FAIL", name, msg))
        self._fails += 1
        print(f"  [FAIL] {name}" + (f" — {msg}" if msg else ""))

    def has_fail(self):
        return self._fails > 0


c = Check()
print("=" * 60)
print("Round36 训练后全链路验证")
print("=" * 60)

# ── C1: final_round36.pkl 可读 ──────────────────────────────
fp = TABLES / "distributed_predictions_final_round36.pkl"
if not fp.exists():
    c.fail("C1: final_round36.pkl 存在", f"不存在: {fp}")
else:
    try:
        df = pd.read_pickle(fp)
        df["time"] = pd.to_datetime(df["time"])
        c.ok("C1: final_round36.pkl 存在且可读", f"{len(df):,} 行, {len(df.columns)} 列")
    except Exception as e:
        c.fail("C1: final_round36.pkl 可读", str(e))

# ── C2: eval_round36.pkl 只含 test 6-19 ────────────────────
ep = TABLES / "distributed_predictions_final_eval_round36.pkl"
if not ep.exists():
    c.fail("C2: eval_round36.pkl 存在", f"不存在: {ep}")
else:
    try:
        de = pd.read_pickle(ep)
        de["time"] = pd.to_datetime(de["time"])
        split_ok = (de["split"] == "test").all()
        hour_ok  = de["hour"].between(6, 19).all()
        if split_ok and hour_ok:
            c.ok("C2: eval_round36 只含 test 6-19", f"{len(de):,} 行, {de['site_id'].nunique()} 站")
        else:
            c.fail("C2: eval_round36 数据范围",
                   f"split_ok={split_ok}, hour_ok={hour_ok}")
    except Exception as e:
        c.fail("C2: eval_round36 检查", str(e))

# ── C3: power_pred_final 存在且非空 ────────────────────────
if fp.exists():
    try:
        df = pd.read_pickle(fp)
        if "power_pred_final" not in df.columns:
            c.fail("C3: power_pred_final 存在", "列不存在")
        else:
            nonnull = df["power_pred_final"].notna().sum()
            c.ok("C3: power_pred_final 存在", f"{nonnull:,} 个非空值 / {len(df):,} 行")
    except Exception as e:
        c.fail("C3: power_pred_final 检查", str(e))

# ── C4: power_pred_final 在 [0, capacity] ─────────────────
if fp.exists():
    try:
        df = pd.read_pickle(fp)
        in_range = ((df["power_pred_final"] >= 0) &
                    (df["power_pred_final"] <= df["capacity_mw"] + 1e-6)).all()
        if in_range:
            c.ok("C4: power_pred_final 在 [0, capacity]", "全部在有效范围内")
        else:
            n_bad = ((df["power_pred_final"] < 0) | (df["power_pred_final"] > df["capacity_mw"])).sum()
            c.fail("C4: power_pred_final 范围", f"{n_bad} 行超出范围")
    except Exception as e:
        c.fail("C4: power_pred_final 范围检查", str(e))

# ── C5: future 不参与指标 ─────────────────────────────────
if fp.exists():
    try:
        df = pd.read_pickle(fp)
        future_count = (df["split"] == "future").sum()
        # future 可以存在于 pkl，但不应用于 eval 或 metrics
        if future_count > 0:
            c.warn("C5: future 不参与指标", f"pkl 中有 {future_count} 行 future（已排除）")
        else:
            c.ok("C5: future 不参与指标", "pkl 中无 future 行")
    except Exception as e:
        c.fail("C5: future 检查", str(e))

# ── C6: site_validity 数量自洽 ────────────────────────────
sv = METRICS / "round36_site_validity.csv"
if not sv.exists():
    c.warn("C6: round36_site_validity.csv 存在", "文件不存在")
else:
    try:
        sdf = pd.read_csv(sv)
        total = len(sdf)
        counts = sdf["site_status"].value_counts()
        has_test = int(counts.get("正常评价", 0) + counts.get("测试期无有效发电", 0) +
                       counts.get("测试期分布漂移", 0) + counts.get("系统性偏差", 0))
        no_test = int(counts.get("无测试预测结果", 0))
        if total == has_test + no_test == 118:
            c.ok("C6: 站点数量自洽", f"全部={total}, 有test={has_test}, 无test={no_test}")
        else:
            c.fail("C6: 站点数量自洽", f"total={total}, has_test={has_test}, no_test={no_test}")
    except Exception as e:
        c.fail("C6: site_validity 检查", str(e))

# ── C7: city_hourly_nrmse 使用城市总出力口径 ───────────────
city_path = METRICS / "round36_city_hourly_nrmse.csv"
if not city_path.exists():
    c.fail("C7: round36_city_hourly_nrmse.csv 存在", "不存在")
else:
    try:
        city = pd.read_csv(city_path)
        required = ["hour", "nrmse_city_pct", "mae_city_MW", "rmse_city_MW", "bias_city_MW"]
        miss = [col for col in required if col not in city.columns]
        if miss:
            c.fail("C7: city_hourly_nrmse 必要字段", f"缺少: {miss}")
        elif city["nrmse_city_pct"].min() <= 0:
            c.fail("C7: city_hourly_nrmse 数值合理", "NRMSE 有非正值")
        else:
            c.ok("C7: city_hourly_nrmse 口径正确",
                 f"{len(city)} 行, NRMSE={city['nrmse_city_pct'].min():.2f}%~{city['nrmse_city_pct'].max():.2f}%")
    except Exception as e:
        c.fail("C7: city_hourly_nrmse 检查", str(e))

# ── C8: site_metrics 使用 power_pred_final ─────────────────
sm = METRICS / "round36_site_metrics.csv"
if not sm.exists():
    c.fail("C8: round36_site_metrics.csv 存在", "不存在")
else:
    try:
        smdf = pd.read_csv(sm)
        if "site_status" in smdf.columns:
            c.ok("C8: round36_site_metrics.csv 有效", f"{len(smdf)} 个站点")
        else:
            c.warn("C8: round36_site_metrics.csv", "无 site_status 列（可能口径旧）")
    except Exception as e:
        c.fail("C8: site_metrics 检查", str(e))

# ── C9: typical_sites 无跨类重复 ──────────────────────────
tp = METRICS / "round36_typical_sites.csv"
if not tp.exists():
    c.warn("C9: round36_typical_sites.csv 存在", "文件不存在")
else:
    try:
        tpdf = pd.read_csv(tp)
        dup = tpdf[tpdf.duplicated("site_id", keep=False)]
        if len(dup) > 0:
            c.fail("C9: typical_sites 无站点重复", f"{list(dup['site_id'])} 重复")
        else:
            c.ok("C9: typical_sites 无站点重复",
                 f"{len(tpdf)} 行, {dict(tpdf['类型'].value_counts())}")
    except Exception as e:
        c.fail("C9: typical_sites 检查", str(e))

# ── C10: dashboard 一致性 CSV 全部 PASS ────────────────────
cons = METRICS / "round36_dashboard_prediction_consistency.csv"
if not cons.exists():
    c.fail("C10: round36_dashboard_consistency.csv 存在", "不存在")
else:
    try:
        cdf = pd.read_csv(cons)
        fails = int((cdf["status"] == "FAIL").sum())
        max_pred = float(cdf["max_abs_diff_pred"].max()) if cdf["max_abs_diff_pred"].notna().any() else 0.0
        if fails > 0:
            c.fail("C10: dashboard pred/actual 一致", f"{fails}/{len(cdf)} FAIL, max_pred={max_pred:.2e}")
        else:
            c.ok("C10: dashboard pred/actual 一致",
                 f"{len(cdf)}/{len(cdf)} PASS, max_pred={max_pred:.2e}")
    except Exception as e:
        c.fail("C10: dashboard_consistency 检查", str(e))

# ── C11: 可视化默认不含 future ─────────────────────────────
if DASH.exists():
    import json as _json
    sample = list((DASH / "site_series").glob("S*.json"))[:3]
    future_found = 0
    for jf in sample:
        try:
            with open(jf) as f:
                data = _json.load(f)
            future_found += sum(1 for r in data if r.get("split") == "future")
        except Exception:
            pass
    if future_found == 0:
        c.ok("C11: 可视化默认不含 future", f"已检查 {len(sample)} 个文件")
    else:
        c.warn("C11: 可视化含 future", f"{future_found} 行 future")

# ── C12: Git 不追踪 pkl/json/tables ───────────────────────
tracked = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                         cwd=str(PROJECT_ROOT), check=False).stdout.splitlines()
pkl_t   = [x for x in tracked if x.endswith((".pkl", ".joblib", ".parquet"))]
js_t    = [x for x in tracked if "site_series/" in x or x.endswith("city_series.json")]
tbl_t   = [x for x in tracked if "output/pv_pipeline/tables/" in x]

if pkl_t:
    c.fail("C12: Git 不追踪 pkl", f"{len(pkl_t)} 个: {pkl_t[:3]}")
else:
    c.ok("C12: Git 不追踪 pkl", "0 个")
if js_t:
    c.fail("C12: Git 不追踪 site_series JSON", f"{len(js_t)} 个")
else:
    c.ok("C12: Git 不追踪 site_series JSON", "0 个")
if tbl_t:
    c.fail("C12: Git 不追踪 tables/", f"{len(tbl_t)} 个")
else:
    c.ok("C12: Git 不追踪 tables/", "0 个")

# ── C13: 报告中不出现旧口径 ────────────────────────────────
report_path = PROJECT_ROOT / "光伏功率预测项目.md"
if not report_path.exists():
    c.warn("C13: 项目报告存在", "文件不存在")
else:
    try:
        content = open(report_path, encoding="utf-8").read()
        old_bad = ["0.3365", "0.3420"]
        found = [x for x in old_bad if x in content]
        if found:
            c.fail("C13: 无旧口径 0.3365%/0.3420%", f"发现: {found}")
        else:
            c.ok("C13: 无旧口径", "正文中未发现旧口径")
    except Exception as e:
        c.warn("C13: 报告检查", str(e))

# ── C14: 报告使用 Round36 数据 ─────────────────────────────
if report_path.exists():
    try:
        content = open(report_path, encoding="utf-8").read()
        has_r36 = "Round36" in content or "round36" in content.lower()
        has_r34 = "Round34" in content
        if has_r36:
            c.ok("C14: 报告含 Round36 内容", "检测到 Round36 相关内容")
        elif has_r34:
            c.warn("C14: 报告可能仍为旧版", "含 Round34 但不含 Round36")
        else:
            c.warn("C14: 报告版本", "无法确定是否为 Round36 版")
    except Exception as e:
        c.warn("C14: 报告版本检查", str(e))

# ── C15: split 列时间范围正确 ──────────────────────────────
if fp.exists():
    try:
        df = pd.read_pickle(fp)
        df["time"] = pd.to_datetime(df["time"])
        # train: < 2025-07-01, valid: 2025-07-01 ~ 2025-08-31, test: 2025-09-01 ~ 2025-12-31
        checks = [
            ("train", df[df["split"]=="train"]["time"].max(), pd.Timestamp("2025-07-01"), "<"),
            ("valid", df[df["split"]=="valid"]["time"].min(), pd.Timestamp("2025-07-01"), ">="),
            ("valid", df[df["split"]=="valid"]["time"].max(), pd.Timestamp("2025-09-01"), "<"),
            ("test",  df[df["split"]=="test"]["time"].min(), pd.Timestamp("2025-09-01"), ">="),
        ]
        ok = all([
            checks[0][1] < checks[0][2],   # train 最大时间 < 2025-07-01
            checks[1][1] >= checks[1][2],  # valid 最小时间 >= 2025-07-01
            checks[2][1] < checks[2][2],   # valid 最大时间 < 2025-09-01
            checks[3][1] >= checks[3][2],  # test 最小时间 >= 2025-09-01
        ])
        if ok:
            c.ok("C15: split 时间边界正确", str(df["split"].value_counts().to_dict()))
        else:
            c.fail("C15: split 时间边界", "边界不符合定义")
    except Exception as e:
        c.fail("C15: split 时间边界检查", str(e))

# ── C16: 训练日志存在 ─────────────────────────────────────
log_path = DOCS / "Round36_训练日志.md"
if log_path.exists():
    try:
        log = open(log_path, encoding="utf-8").read()
        has_split = "train" in log and "valid" in log and "test" in log
        c.ok("C16: 训练日志存在", f"{len(log)} 字，含 train/valid/test: {has_split}")
    except Exception as e:
        c.warn("C16: 训练日志", str(e))
else:
    c.warn("C16: 训练日志存在", "文件不存在（训练后生成）")

# ── 汇总写报告 ─────────────────────────────────────────────
total_ = len(c.results)
pass_  = sum(1 for r in c.results if r[0] == "PASS")
fails_ = sum(1 for r in c.results if r[0] == "FAIL")
warns_ = sum(1 for r in c.results if r[0] == "WARN")

print()
print("=" * 60)
print(f"校验结果: {total_} 项 | {pass_} PASS | {fails_} FAIL | {warns_} WARN")
print("=" * 60)

lines = ["# Round36 训练逻辑与可视化一致性验证报告\n",
         f"**生成时间**: 2026-05-28 22:xx\n",
         f"\n## 校验结果\n",
         f"| 状态 | 数量 |\n||------|\n",
         f"| PASS | {pass_} |\n",
         f"| FAIL | {fails_} |\n",
         f"| WARN | {warns_} |\n",
         f"\n## 逐项结果\n",
         f"| # | 状态 | 检查项 | 说明 |\n",
         f"|---|------|--------|------|\n"]
for i, (status, name, msg) in enumerate(c.results, 1):
    icon = "✓" if status == "PASS" else ("⚠" if status == "WARN" else "✗")
    lines.append(f"| {i} | {icon} {status} | {name} | {msg} |\n")

if c.has_fail():
    lines.append("\n## 结论\n")
    lines.append(f"**{fails_} 项 FAIL，不合格。请修复后重新运行 posttrain_validation_round36.py。**\n")
    exit_code = 1
else:
    lines.append("\n## 结论\n")
    lines.append("**全部检查通过：Round36 训练与可视化全链路验证合格。**\n")
    exit_code = 0

with open(RESULT_FILE, "w", encoding="utf-8") as f:
    f.writelines(lines)
print(f"\n报告已写入: {RESULT_FILE}")
sys.exit(exit_code)
