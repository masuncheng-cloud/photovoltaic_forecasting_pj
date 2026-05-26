# Cursor 执行方案 Round15：最终交付包清理与报告修正

## 0. 本轮目标

当前 Round14 已完成：

```text
完整重训成功
final = best
审计 Grade A
FAIL = 0
WARN = 0
```

但当前完整项目包仍存在交付层面的残留问题：

1. 主 `metrics/`、`tables/` 中仍有 round6、round9、v3/v4、旧候选结果残留。
2. `round14_final_delivery_check.csv` 只有 `True/False`，缺少检查项名称，不利于追溯。
3. `光伏功率预测项目.md` 中存在少量不严谨表述：
   - 原始功率数据量写“暂不可用”；
   - S019 NRMSE 描述和表格不一致；
   - 训练框架写成 LightGBM，但依赖和代码主要是 CatBoost/自定义模型；
   - final_guard 表述容易让人误解为 test 参与模型选择。
4. zip 交付包中包含 `.git/`、`__MACOSX/`、`auto_push_test.txt`、`test_auto_push.txt`、截图等非交付杂项。

本轮目标：

```text
不重新训练，不修改 final/best 预测结果。
只做最终交付包清理、报告表述修正、交付检查脚本增强、重新打包。
```

---

## 1. 严禁修改

本轮禁止修改以下核心结果：

```text
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
output/pv_pipeline/tables/best_predictions_eval.pkl
output/pv_pipeline/tables/best_predictions_full.pkl
output/pv_pipeline/metrics/round10_overall_nrmse_summary.csv
output/pv_pipeline/metrics/分布式光伏预测_逐小时平均NRMSE.csv
```

禁止重新训练：

```text
不要运行 train_fixed.py
不要运行 run_full_retrain_round14.py
```

本轮只允许：

```text
归档旧文件
修正报告文字
增强检查脚本
重新生成交付压缩包
重新运行审计与交付检查
```

---

## 2. 新增/修改脚本

建议新增：

```text
scripts/archive_remaining_stale_artifacts_round15.py
scripts/fix_project_report_round15.py
scripts/build_clean_delivery_package_round15.py
```

修改：

```text
scripts/check_round14_final_delivery.py
```

或新增替代脚本：

```text
scripts/check_round15_final_delivery.py
```

推荐新增 `check_round15_final_delivery.py`，避免破坏 Round14 记录。

---

## 3. Step 1：归档剩余历史残留

新增：

```text
scripts/archive_remaining_stale_artifacts_round15.py
```

### 3.1 归档目录

```text
output/pv_pipeline/archive_round15/
```

### 3.2 必须保护文件

写死保护清单：

```python
KEEP_FILES = {
    "distributed_predictions_final_eval.pkl",
    "distributed_predictions_final_full.pkl",
    "best_predictions_eval.pkl",
    "best_predictions_full.pkl",
    "round10_overall_nrmse_summary.csv",
    "round10_hour_overall_nrmse.csv",
    "round10_site_hour_nrmse.csv",
    "round10_final_is_best_check.csv",
    "round10_final_vs_best_nrmse.csv",
    "round11_candidate_leaderboard.csv",
    "round14_retrain_decision.json",
    "round14_retrain_vs_verified_best.csv",
    "round14_final_delivery_check.csv",
    "分布式光伏预测_逐小时平均NRMSE.csv",
    "audit_summary.json",
    "audit_metric_recompute.csv",
    "audit_metric_overall.csv",
    "audit_data_integrity.csv",
    "audit_split_integrity.csv",
    "audit_site_mapping.csv",
    "audit_report_page_consistency.json",
    "audit_final_best_consistency.json",
    "audit_physical_range.json",
}
```

### 3.3 归档 metrics 中的残留

移动以下文件到：

```text
output/pv_pipeline/archive_round15/metrics/
```

匹配规则：

```python
STALE_METRIC_PATTERNS = [
    "round6_*",
    "round9_*",
    "v3_*",
    "v4_*",
    "*MAPE*",
    "*相对误差*",
    "hourly_relative_error*",
    "hourly_nrmse_compare_v2_v3.csv",
    "final_comparison_V0_V1_V2.csv",
    "final_comparison_V0_V1_V3.csv",
]
```

注意：

```text
如果文件名在 KEEP_FILES 中，不允许归档。
```

### 3.4 归档 tables 中的旧候选

移动以下文件到：

```text
output/pv_pipeline/archive_round15/tables/
```

匹配规则：

```python
STALE_TABLE_PATTERNS = [
    "distributed_predictions_midday_residual_specialist_*.pkl",
    "distributed_predictions_round6_stable_bias_*.pkl",
    "distributed_predictions_midday_selective_site_corrected_*.pkl",
    "distributed_predictions_metadata_overridden_full.pkl",
]
```

保留以下中间产物，因为它们属于训练闭环必要产物：

```text
distributed_predictions_v159.pkl
distributed_predictions_v159_fix.pkl
distributed_train_table_v159.pkl
distributed_predictions_midday_site_calibrated_eval.pkl
distributed_predictions_midday_site_calibrated_full.pkl
inverse_predictions.pkl
inverse_train_table.pkl
site_irradiance.pkl
site_meteo.pkl
power_clean.pkl
power_long_raw.pkl
```

### 3.5 归档 docs 中旧 Round 报告

将以下文档移动到：

```text
output/pv_pipeline/archive_round15/docs/
```

匹配规则：

```python
STALE_DOC_PATTERNS = [
    "Round6_*",
    "Round7_*",
    "Round8_*",
    "Round9_*",
    "Round10_*",
    "Round11_*",
]
```

保留：

```text
docs/训练过程与结果严谨性验证报告.md
docs/训练记录_Round14_清理残留完整重训并重填项目报告_20260526.md
光伏功率预测项目.md
CHANGELOG.md
README.md
```

### 3.6 输出归档清单

生成：

```text
output/pv_pipeline/archive_round15/archive_manifest.csv
```

字段：

```text
source_path
archive_path
file_type
reason
size_bytes
sha256
archived_at
```

---

## 4. Step 2：修正 `光伏功率预测项目.md`

新增：

```text
scripts/fix_project_report_round15.py
```

### 4.1 修正 1.2 原始功率数据量

当前：

```text
*原始功率数据统计暂不可用。*
```

改为从：

```text
output/pv_pipeline/tables/power_long_raw.pkl
```

重新统计：

```text
总行数
站点/别名数
非空功率行数
正功率行数
0值行数
0值占非空比例
时间范围
```

写入表格：

```markdown
| 指标 | 数值 |
|:---|---:|
| 原始功率长表总行数（行） | ... |
| 功率别名/列数量（个） | ... |
| 非空功率行数（行） | ... |
| 正功率行数（行） | ... |
| 0值行数（行） | ... |
| 0值占非空比例（%） | ... |
| 时间范围 | ... |
```

如果 `power_long_raw.pkl` 中字段名不是 `power_mw`，自动识别：

```python
power_col_candidates = ["power_mw", "power", "value", "功率"]
```

### 4.2 修正 S019 描述

当前问题：

```text
S019 表格为 34.81%，但问题描述写约31%
```

改为：

```text
S019（首耀新海光伏）测试集 NRMSE 约 34.81%，显著高于整体水平。
```

如果报告中没有站点中文名，则写：

```text
S019 测试集 NRMSE 约 34.81%，显著高于整体水平。
```

### 4.3 修正训练框架描述

检查实际依赖：

```text
requirements.txt 中有 catboost，没有 lightgbm
```

因此将：

```text
训练框架 | LightGBM + 自定义混合模型
```

改为：

```text
训练框架 | CatBoost / sklearn 风格模型 + 自定义后处理与 Guard 选择
```

或者更稳妥：

```text
训练框架 | CatBoost 及自定义分层后处理、Guard 选择流程
```

### 4.4 修正 final_guard 表述

当前：

```text
只有当候选版本在测试集上的整体 NRMSE 不超过当前 best 0.1pp 时才允许替换
```

容易被理解为 test 参与模型选择。

改为：

```text
final_guard 用于最终产物保护和回退检查。模型选择和校准不使用 test 集调参；test 集仅用于最终评估、审计复算和交付前的 final/best 一致性确认。
```

### 4.5 增加一段“测试集使用说明”

在严谨性验证结论附近加入：

```markdown
> **测试集使用说明**：本项目中的 test 集仅用于最终评估、结果复算、审计和交付前保护检查；不用于模型训练、校准参数学习或常规调参。
```

### 4.6 修正章节跳号

如果审计报告中存在：

```text
## 6
## 8
## 9
## 10
```

可不改审计报告历史记录，但如果重新生成 `光伏功率预测项目.md` 时有跳号，必须修正。

---

## 5. Step 3：增强最终交付检查

新增：

```text
scripts/check_round15_final_delivery.py
```

### 5.1 输出格式

生成：

```text
output/pv_pipeline/metrics/round15_final_delivery_check.csv
```

字段必须是：

```text
check_name
passed
detail
severity
```

不要再输出只有：

```text
check,passed
True,True
```

### 5.2 检查项

至少包含：

```text
final_eval_readable
final_full_readable
best_eval_readable
best_full_readable
final_equals_best
audit_grade_a
audit_fail_zero
audit_warn_zero
project_report_exists
project_report_no_wape_main_metric
project_report_no_mape_main_metric
project_report_has_raw_power_stats
project_report_no_lightgbm_claim_if_missing_dep
project_report_test_usage_clear
hourly_table_has_14_rows
interactive_dashboard_index_exists
full_history_rows_ge_20000
archive_round15_manifest_exists
backup_round14_manifest_exists
zip_exclude_git
zip_exclude_macosx
zip_exclude_test_push_files
```

### 5.3 最终判定

如果所有 `severity == "ERROR"` 的检查通过，打印：

```text
[OK] Round15 final delivery checks passed
```

如果有失败，打印失败项并返回非 0。

---

## 6. Step 4：构建干净交付包

新增：

```text
scripts/build_clean_delivery_package_round15.py
```

### 6.1 输出文件

```text
dist/photovoltaic_forecasting_pj_round15_delivery.zip
```

### 6.2 打包内容包含

保留：

```text
README.md
CHANGELOG.md
requirements.txt
configs/
config/
src/
stages/
scripts/
data/
output/pv_pipeline/tables/
output/pv_pipeline/metrics/
output/pv_pipeline/models/
output/pv_pipeline/interactive_dashboard/
output/pv_pipeline/docs/
output/pv_pipeline/archive_round14/
output/pv_pipeline/archive_round15/
output/pv_pipeline/verified_backup_round14/
docs/训练过程与结果严谨性验证报告.md
docs/训练记录_Round14_清理残留完整重训并重填项目报告_20260526.md
光伏功率预测项目.md
任务书-2026年国网江苏省电力有限公司面向生产一线的科技项目包（连云港公司）.doc
```

### 6.3 打包时必须排除

```text
.git/
__MACOSX/
.DS_Store
*.pyc
__pycache__/
catboost_info/
auto_push_test.txt
test_auto_push.txt
auto_sync.log
auto_sync.py
截屏*.png
*.tmp
*.bak
```

### 6.4 生成打包 manifest

生成：

```text
dist/photovoltaic_forecasting_pj_round15_delivery_manifest.csv
```

字段：

```text
path
size_bytes
sha256
included
reason
```

### 6.5 打包后自检

打包脚本完成后检查 zip 内部：

```python
bad_patterns = [
    ".git/",
    "__MACOSX/",
    ".DS_Store",
    "__pycache__/",
    "auto_push_test.txt",
    "test_auto_push.txt",
    "auto_sync.log",
    "截屏",
]
```

如果 zip 中存在上述内容，直接失败。

---

## 7. 执行顺序

请 Cursor 按顺序执行：

```bash
# 1. 归档剩余历史残留
python scripts/archive_remaining_stale_artifacts_round15.py

# 2. 修正项目报告
python scripts/fix_project_report_round15.py

# 3. 重新运行严谨性验证，确保仍 Grade A
python scripts/audit_training_process_and_results.py \
  --output-root output/pv_pipeline \
  --report-path docs/训练过程与结果严谨性验证报告.md

# 4. 运行 Round15 最终交付检查
python scripts/check_round15_final_delivery.py

# 5. 构建干净交付包
python scripts/build_clean_delivery_package_round15.py

# 6. 再次检查交付包
python scripts/check_round15_final_delivery.py
```

---

## 8. 验收命令

### 8.1 检查审计仍为 Grade A

```bash
python - <<'PY'
import json
from pathlib import Path

p = Path("output/pv_pipeline/metrics/audit_summary.json")
data = json.loads(p.read_text(encoding="utf-8"))
assert data["grade"] == "A"
assert data["fail_count"] == 0
assert data["warn_count"] == 0
print("[OK] audit Grade A")
PY
```

### 8.2 检查 Round15 交付检查

```bash
python - <<'PY'
import pandas as pd
from pathlib import Path

p = Path("output/pv_pipeline/metrics/round15_final_delivery_check.csv")
assert p.exists()
df = pd.read_csv(p)
assert {"check_name", "passed", "detail", "severity"}.issubset(df.columns)
failed = df[(df["severity"].eq("ERROR")) & (~df["passed"].astype(bool))]
assert failed.empty, failed.to_string(index=False)
print("[OK] round15 final delivery check passed")
PY
```

### 8.3 检查报告表述

```bash
python - <<'PY'
from pathlib import Path

p = Path("光伏功率预测项目.md")
text = p.read_text(encoding="utf-8")

assert "原始功率数据统计暂不可用" not in text
assert "LightGBM + 自定义混合模型" not in text
assert "测试集仅用于最终评估" in text or "test 集仅用于最终评估" in text
assert "34.81" in text

print("[OK] project report wording fixed")
PY
```

### 8.4 检查干净 zip

```bash
python - <<'PY'
from pathlib import Path
import zipfile

zip_path = Path("dist/photovoltaic_forecasting_pj_round15_delivery.zip")
assert zip_path.exists(), "交付 zip 不存在"

bad = []
with zipfile.ZipFile(zip_path) as z:
    names = z.namelist()
    for name in names:
        if (
            ".git/" in name
            or "__MACOSX/" in name
            or ".DS_Store" in name
            or "__pycache__/" in name
            or name.endswith("auto_push_test.txt")
            or name.endswith("test_auto_push.txt")
            or name.endswith("auto_sync.log")
            or "截屏" in name
        ):
            bad.append(name)

assert not bad, "zip 中仍包含非交付文件:\\n" + "\\n".join(bad[:50])
print("[OK] clean delivery zip")
PY
```

---

## 9. 预期最终结果

完成后应有：

```text
审计：Grade A, FAIL=0, WARN=0
Round15 final delivery check：全部 ERROR 项通过
光伏功率预测项目.md：数据完整、表述严谨
dist/photovoltaic_forecasting_pj_round15_delivery.zip：不含 .git、__MACOSX、测试文件、截图
主 metrics/tables：不再保留明显 round6/round9/v3/v4 旧候选残留
```

---

## 10. 最终提交说明建议

```text
Round15: clean final delivery package and fix report wording

- archive remaining stale round6/round9/v3/v4 artifacts
- fix project report raw data stats and wording
- clarify test set usage and final guard role
- add structured Round15 final delivery check
- build clean delivery zip excluding git/macOS/test artifacts
- keep final/best predictions unchanged
```

