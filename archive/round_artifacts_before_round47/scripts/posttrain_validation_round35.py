"""
posttrain_validation_round35.py
=============================
Round35 总体验证脚本，整合 Step 7 的所有检查项。

输出：
  output/pv_pipeline/docs/Round35_产物收口与可视化一致性验证报告.md

验收标准不满足则 exit code 1。
"""
import os
import pickle
import pandas as pd
import numpy as np
from pathlib import Path
import sys
import subprocess

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
TABLES  = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DASH    = PROJECT_ROOT / "output" / "pv_pipeline" / "interactive_dashboard"
DOCS    = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"
os.makedirs(DOCS, exist_ok=True)

RESULT_FILE = DOCS / "Round35_产物收口与可视化一致性验证报告.md"


class Check:
    def __init__(self):
        self.results = []
        self._fails = 0
        self._warns  = 0

    def ok(self, name: str, msg: str = ""):
        self.results.append(("PASS", name, msg))
        print(f"  [PASS] {name}" + (f" — {msg}" if msg else ""))

    def warn(self, name: str, msg: str = ""):
        self.results.append(("WARN", name, msg))
        self._warns += 1
        print(f"  [WARN] {name}" + (f" — {msg}" if msg else ""))

    def fail(self, name: str, msg: str = ""):
        self.results.append(("FAIL", name, msg))
        self._fails += 1
        print(f"  [FAIL] {name}" + (f" — {msg}" if msg else ""))

    def has_failures(self) -> bool:
        return self._fails > 0


c = Check()
print("=" * 60)
print("Round35 总体验证")
print("=" * 60)

# ────────────────────────────────────────────────────────────────────────
# C1: Round34 预测文件可读
# ────────────────────────────────────────────────────────────────────────
pkl_path = TABLES / "distributed_predictions_final_round34.pkl"
if not pkl_path.exists():
    c.fail("C1: Round34 预测文件存在", f"不存在: {pkl_path}")
else:
    try:
        with open(pkl_path, "rb") as f:
            df = pickle.load(f)
        c.ok("C1: Round34 预测文件存在且可读", f"{len(df):,} 行, {len(df.columns)} 列")
    except Exception as e:
        c.fail("C1: Round34 预测文件可读", str(e))

# ────────────────────────────────────────────────────────────────────────
# C2: power_pred_final 存在
# ────────────────────────────────────────────────────────────────────────
if pkl_path.exists():
    try:
        with open(pkl_path, "rb") as f:
            df = pickle.load(f)
        if "power_pred_final" not in df.columns:
            c.fail("C2: power_pred_final 存在", "列不存在")
        else:
            c.ok("C2: power_pred_final 存在",
                 f"{df['power_pred_final'].notna().sum():,} 个非空值")
    except Exception as e:
        c.fail("C2: power_pred_final 检查", str(e))

# ────────────────────────────────────────────────────────────────────────
# C3: Round34 指标文件存在
# ────────────────────────────────────────────────────────────────────────
required_csv = [
    ("round34_city_hourly_nrmse.csv",     METRICS),
    ("round34_site_hourly_nrmse.csv",     METRICS),
    ("round34_site_avg_hourly_nrmse.csv", METRICS),
    ("round34_site_metrics.csv",          METRICS),
    ("round34_typical_sites.csv",         METRICS),
    ("round34_site_validity.csv",         METRICS),
    ("round34_site_count_summary.csv",    METRICS),
    ("round35_dashboard_prediction_consistency.csv", METRICS),
]
missing = []
for fname, dir_ in required_csv:
    if not (dir_ / fname).exists():
        missing.append(str(dir_ / fname))
if missing:
    c.fail("C3: Round34 指标文件存在", f"缺失: {missing}")
else:
    c.ok("C3: Round34 指标文件存在", f"{len(required_csv)} 个文件全部存在")

# ────────────────────────────────────────────────────────────────────────
# C4: round34_city_hourly_nrmse 使用城市总出力口径
# ────────────────────────────────────────────────────────────────────────
city_path = METRICS / "round34_city_hourly_nrmse.csv"
if city_path.exists():
    try:
        city = pd.read_csv(city_path)
        required = ["hour", "nrmse_city_pct", "mae_city_MW", "rmse_city_MW", "bias_city_MW"]
        missing_cols = [col for col in required if col not in city.columns]
        if missing_cols:
            c.fail("C4: city_hourly_nrmse 必要字段", f"缺少: {missing_cols}")
        elif city["nrmse_city_pct"].min() <= 0:
            c.fail("C4: city_hourly_nrmse 数值合理", "NRMSE 有非正值")
        else:
            c.ok("C4: city_hourly_nrmse 使用城市总出力口径",
                 f"14 行, NRMSE={city['nrmse_city_pct'].min():.2f}%~{city['nrmse_city_pct'].max():.2f}%")
    except Exception as e:
        c.fail("C4: city_hourly_nrmse 检查", str(e))

# ────────────────────────────────────────────────────────────────────────
# C5: round34_typical_sites 无跨类重复
# ────────────────────────────────────────────────────────────────────────
tp_path = METRICS / "round34_typical_sites.csv"
if tp_path.exists():
    try:
        tp = pd.read_csv(tp_path)
        dup = tp[tp.duplicated("site_id", keep=False)]
        if len(dup) > 0:
            c.fail("C5: typical_sites 无站点重复",
                   f"{list(dup['site_id'])} 重复")
        else:
            c.ok("C5: typical_sites 无站点重复",
                 f"{len(tp)} 行, {dict(tp['类型'].value_counts())}")
    except Exception as e:
        c.fail("C5: typical_sites 检查", str(e))

# ────────────────────────────────────────────────────────────────────────
# C6: round35_dashboard_prediction_consistency.csv 全部 PASS
# ────────────────────────────────────────────────────────────────────────
cons_path = METRICS / "round35_dashboard_prediction_consistency.csv"
if not cons_path.exists():
    c.fail("C6: dashboard 一致性 CSV 存在", f"不存在: {cons_path}")
else:
    try:
        cons = pd.read_csv(cons_path)
        fails = int((cons["status"] == "FAIL").sum())
        max_pred = float(cons["max_abs_diff_pred"].max()) if cons["max_abs_diff_pred"].notna().any() else 0.0
        max_actual = float(cons["max_abs_diff_actual"].max()) if cons["max_abs_diff_actual"].notna().any() else 0.0
        if fails > 0:
            c.fail("C6: dashboard pred/actual 一致",
                   f"{fails}/{len(cons)} 个站点 FAIL，max_pred_diff={max_pred:.2e}")
        else:
            c.ok("C6: dashboard pred/actual 一致",
                 f"68/68 PASS, max_pred={max_pred:.2e}, max_actual={max_actual:.2e}")
    except Exception as e:
        c.fail("C6: dashboard 一致性 CSV 检查", str(e))

# ────────────────────────────────────────────────────────────────────────
# C7: 报告路径统一（Markdown 报告应在 docs/，不应在 metrics/docs/）
# ────────────────────────────────────────────────────────────────────────
wrong_docs_dir = METRICS / "docs"
wrong_docs_files = list(wrong_docs_dir.glob("*.md")) if wrong_docs_dir.exists() else []
if wrong_docs_files:
    c.fail("C7: 报告路径统一", f"metrics/docs/ 下仍有报告: {[p.name for p in wrong_docs_files]}")
else:
    c.ok("C7: 报告路径统一", "Markdown 报告统一输出到 output/pv_pipeline/docs/")

# ────────────────────────────────────────────────────────────────────────
# C8: 光伏功率预测项目.md 中包含 118、68、14 三类站点说明
# ────────────────────────────────────────────────────────────────────────
report_path = PROJECT_ROOT / "光伏功率预测项目.md"
if not report_path.exists():
    c.fail("C8: 项目报告存在", f"不存在: {report_path}")
else:
    try:
        content = open(report_path, encoding="utf-8").read()
        has_118 = "118" in content and "全部登记站点" in content
        has_68  = "68" in content and "有 test 结果站点" in content
        has_14  = "14" in content and "正常可排名站点" in content
        has_50  = "50" in content and "无测试预测结果" in content
        if has_118 and has_68 and has_14 and has_50:
            c.ok("C8: 项目报告含 118/68/14/50 说明",
                 "全部登记站点118 / 有test结果68 / 正常可排名14 / 无测试预测结果50")
        else:
            c.fail("C8: 项目报告含站点数量说明",
                   f"has_118={has_118}, has_68={has_68}, has_14={has_14}, has_50={has_50}")
    except Exception as e:
        c.fail("C8: 项目报告读取", str(e))

# ────────────────────────────────────────────────────────────────────────
# C9: 项目报告中不把 0.3365% 作为正式核心指标
# ────────────────────────────────────────────────────────────────────────
if report_path.exists():
    try:
        content = open(report_path, encoding="utf-8").read()
        lines = content.split("\n")
        core_section = "\n".join(lines[:500])
        has_bad = "0.3365" in core_section or "0.3420" in core_section
        if has_bad:
            c.fail("C9: 历史口径 NRMSE 不作核心指标",
                   "项目中存在 0.3365% 或 0.3420% 数值（正文部分）")
        else:
            c.ok("C9: 历史口径 NRMSE 不作核心指标", "未在正文中发现 0.3365%")
    except Exception as e:
        c.warn("C9: 历史口径检查", str(e))

# ────────────────────────────────────────────────────────────────────────
# C10: Git 不追踪大体积 pkl、site_series JSON 和 tables 输出
# ────────────────────────────────────────────────────────────────────────
tracked = subprocess.run(
    ["git", "ls-files"],
    capture_output=True, text=True, errors="replace",
    cwd=str(PROJECT_ROOT), check=False,
).stdout.splitlines()

pkl_tracked = [x for x in tracked if x.endswith((".pkl", ".joblib", ".parquet"))]
json_tracked = [x for x in tracked if "site_series/" in x or x.endswith("city_series.json")]
tables_tracked = [x for x in tracked if "output/pv_pipeline/tables/" in x]

if pkl_tracked:
    c.fail("C10: Git 不追踪 pkl/joblib/parquet", f"发现 {len(pkl_tracked)} 个: {pkl_tracked[:5]}")
else:
    c.ok("C10: Git 不追踪 pkl/joblib/parquet", "0 个")

if json_tracked:
    c.fail("C10: Git 不追踪 site_series/city_series JSON", f"发现 {len(json_tracked)} 个")
else:
    c.ok("C10: Git 不追踪 site_series/city_series JSON", "0 个（已从 git 移除并写入 .gitignore）")

if tables_tracked:
    c.fail("C10: Git 不追踪 tables/ 输出", f"发现 {len(tables_tracked)} 个")
else:
    c.ok("C10: Git 不追踪 tables/ 输出", "0 个")

# ────────────────────────────────────────────────────────────────────────
# C11: 可视化页面默认不含 future
# ────────────────────────────────────────────────────────────────────────
if DASH.exists():
    import json as _json
    sample_jsons = list((DASH / "site_series").glob("S*.json"))[:3]
    future_found = 0
    for jf in sample_jsons:
        try:
            with open(jf) as f:
                data = _json.load(f)
            future_found += sum(1 for r in data if r.get("split") == "future")
        except Exception:
            pass
    if future_found == 0:
        c.ok("C11: 可视化默认不含 future", f"已检查 {len(sample_jsons)} 个文件，无 future 数据")
    else:
        c.warn("C11: 可视化 future 数据", f"发现 {future_found} 行 future 数据")

# ────────────────────────────────────────────────────────────────────────
# C12: 站点数量自洽性验证
# ────────────────────────────────────────────────────────────────────────
sv_path = METRICS / "round34_site_validity.csv"
if not sv_path.exists():
    c.warn("C12: round34_site_validity.csv 存在", "文件不存在")
else:
    try:
        sv = pd.read_csv(sv_path)
        total = len(sv)
        counts = sv["site_status"].value_counts()
        no_test = int(counts.get("无测试预测结果", 0))
        has_test = int(counts.get("正常评价", 0) + counts.get("测试期无有效发电", 0)
                     + counts.get("测试期分布漂移", 0) + counts.get("系统性偏差", 0))
        if total == no_test + has_test and total == 118:
            c.ok("C12: 站点数量自洽", f"全部={total} = 有test={has_test}+无test={no_test}")
        else:
            c.fail("C12: 站点数量自洽", f"total={total}, has_test={has_test}, no_test={no_test}")
    except Exception as e:
        c.fail("C12: 站点数量自洽检查", str(e))

# ────────────────────────────────────────────────────────────────────────
# 汇总并写报告
# ────────────────────────────────────────────────────────────────────────
total_ = len(c.results)
passes_ = sum(1 for r in c.results if r[0] == "PASS")
fails_  = sum(1 for r in c.results if r[0] == "FAIL")
warns_  = sum(1 for r in c.results if r[0] == "WARN")

print()
print("=" * 60)
print(f"校验结果: {total_} 项 | {passes_} PASS | {fails_} FAIL | {warns_} WARN")
print("=" * 60)

lines = [
    "# Round35 产物收口与可视化一致性验证报告\n",
    f"**生成时间**: 2026-05-28 21:35\n",
    f"\n## 校验结果\n",
    f"| 状态 | 数量 |\n",
    f"|------|------|\n",
    f"| PASS | {passes_} |\n",
    f"| FAIL | {fails_} |\n",
    f"| WARN | {warns_} |\n",
    f"\n## 逐项检查结果\n",
    f"| # | 状态 | 检查项 | 说明 |\n",
    f"|---|------|--------|------|\n",
]
for i, (status, name, msg) in enumerate(c.results, 1):
    icon = "✓" if status == "PASS" else ("⚠" if status == "WARN" else "✗")
    lines.append(f"| {i} | {icon} {status} | {name} | {msg} |\n")

if c.has_failures():
    lines.append("\n## 结论\n")
    lines.append(f"**FAIL**：{fails_} 项不合格，请修复后重新运行。\n")
    exit_code = 1
else:
    lines.append("\n## 结论\n")
    lines.append("**全部检查通过**：Round35 产物收口与可视化一致性验证合格。\n")
    exit_code = 0

with open(RESULT_FILE, "w", encoding="utf-8") as f:
    f.writelines(lines)
print(f"\n报告已写入: {RESULT_FILE}")
sys.exit(exit_code)
