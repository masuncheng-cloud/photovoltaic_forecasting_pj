# Round35.1 收口修复方案：无需重新训练

## 一、是否需要重新训练？

**不需要。**

当前 Round35 的问题不是模型训练问题，也不是预测结果本身的问题。  
`round35_dashboard_prediction_consistency.csv` 已经显示：

```text
68 个站点全部 PASS
max_abs_diff_actual = 0
max_abs_diff_pred = 0
max_abs_diff_capacity = 0
```

说明可视化中已导出的真实值、预测值与最终预测文件是一致的。

本轮只需要修复三个收口问题：

1. Git 仍追踪了部分 `site_series/*.json`。
2. 一致性检查报告路径仍写到了 `metrics/docs/`。
3. 一致性检查中 `n_json` 与 `n_pkl` 的口径未说明清楚，容易误解。

因此 Round35.1 只做脚本和产物修复，不重新训练。

## 二、当前遗留问题

### 2.1 Git 仍追踪 site_series JSON

`Round35_产物收口与可视化一致性验证报告.md` 中仍显示：

```text
C10: Git 不追踪 site_series JSON -> FAIL，发现 68 个
```

这说明之前虽然移除了部分 JSON，但还有 68 个 `site_series/*.json` 被 Git 追踪。

### 2.2 一致性报告路径仍不统一

`check_dashboard_prediction_values_round35.py` 中仍有：

```python
os.makedirs(METRICS / "docs", exist_ok=True)
OUT_REPORT = METRICS / "docs" / "Round35_可视化预测值一致性检查报告.md"
```

应改为：

```python
DOCS = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"
os.makedirs(DOCS, exist_ok=True)
OUT_REPORT = DOCS / "Round35_可视化预测值一致性检查报告.md"
```

### 2.3 一致性检查行数口径不清楚

当前 CSV 中：

```text
n_json < n_pkl
```

这并不一定是错误。原因是：

- JSON 可视化数据通常只导出 `6-19` 点；
- pkl 中包含 `0-23` 点全量历史记录；
- 因此如果不统一过滤条件，`n_json` 和 `n_pkl` 本来就不会相等。

Round35.1 要求把 pkl 也过滤到与 JSON 一致的口径：

```python
split != "future"
hour in 6..19
```

然后输出字段改为：

```text
n_json
n_pkl_6_19
n_matched
```

验收时要求：

```text
n_json == n_pkl_6_19 == n_matched
```

## 三、Cursor 修改步骤

### Step 1：修复 `check_dashboard_prediction_values_round35.py`

修改文件：

```text
scripts/check_dashboard_prediction_values_round35.py
```

#### 1.1 修复报告输出路径

将：

```python
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DASH    = PROJECT_ROOT / "output" / "pv_pipeline" / "interactive_dashboard"
os.makedirs(METRICS / "docs", exist_ok=True)

OUT_CSV   = METRICS / "round35_dashboard_prediction_consistency.csv"
OUT_REPORT = METRICS / "docs" / "Round35_可视化预测值一致性检查报告.md"
```

改为：

```python
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
DOCS    = PROJECT_ROOT / "output" / "pv_pipeline" / "docs"
DASH    = PROJECT_ROOT / "output" / "pv_pipeline" / "interactive_dashboard"
os.makedirs(METRICS, exist_ok=True)
os.makedirs(DOCS, exist_ok=True)

OUT_CSV    = METRICS / "round35_dashboard_prediction_consistency.csv"
OUT_REPORT = DOCS / "Round35_可视化预测值一致性检查报告.md"
```

#### 1.2 修复 pkl 过滤口径

在 `load_pkl()` 中，将：

```python
df = df[df["split"] != "future"].copy()
```

改为：

```python
df["hour"] = df["time"].dt.hour
df = df[
    (df["split"] != "future") &
    (df["hour"] >= 6) &
    (df["hour"] <= 19)
].copy()
```

并修改打印说明：

```python
print(f"  pkl: {len(df):,} 行 (不含future, 6-19点), {df['site_id'].nunique()} 站")
```

#### 1.3 修改字段名

把输出字段：

```text
n_pkl
```

改为：

```text
n_pkl_6_19
```

所有代码中的 `n_pkl` 同步改名。

#### 1.4 增加行数一致性判断

在每个站点判断 PASS/FAIL 时，增加：

```python
count_ok = (n_json == n_pkl_6_19 == n_matched)
```

最终 PASS 条件改为：

```python
if actual_ok and pred_ok and cap_ok and count_ok:
    status = "PASS"
else:
    status = "FAIL"
```

`message` 中加入：

```python
count_ok={count_ok}
```

#### 1.5 更新报告说明

报告中加入：

```text
本检查口径：split != future，hour in 6..19，与可视化导出站点曲线口径一致。
```

并将表头里的 `n_pkl` 改为 `n_pkl_6_19`。

### Step 2：修复 `posttrain_validation_round35.py`

修改文件：

```text
scripts/posttrain_validation_round35.py
```

#### 2.1 修复 Git 检查逻辑

替换当前 C10 的 Git 检查代码为：

```python
import subprocess

tracked = subprocess.run(
    ["git", "ls-files"],
    capture_output=True,
    text=True,
    cwd=str(PROJECT_ROOT),
    check=False,
).stdout.splitlines()

pkl_tracked = [
    x for x in tracked
    if x.endswith((".pkl", ".joblib", ".parquet"))
]

json_tracked = [
    x for x in tracked
    if "site_series/" in x or x.endswith("city_series.json")
]

if pkl_tracked:
    c.fail("C10: Git 不追踪 pkl/joblib/parquet", f"发现 {len(pkl_tracked)} 个: {pkl_tracked[:5]}")
else:
    c.ok("C10: Git 不追踪 pkl/joblib/parquet", "0 个")

if json_tracked:
    c.fail("C10: Git 不追踪 site_series/city_series JSON", f"发现 {len(json_tracked)} 个: {json_tracked[:5]}")
else:
    c.ok("C10: Git 不追踪 site_series/city_series JSON", "0 个")
```

#### 2.2 修复 C7 报告路径检查

因为 Round35 报告是在脚本末尾生成的，所以 C7 不应在生成前检查自身是否存在。

将 C7 改为检查：

```python
docs_dir_ok = DOCS.exists()
wrong_docs_dir = METRICS / "docs"
wrong_docs_files = list(wrong_docs_dir.glob("*.md")) if wrong_docs_dir.exists() else []
```

逻辑：

```python
if wrong_docs_files:
    c.fail("C7: 报告路径统一", f"metrics/docs 下仍有报告: {[p.name for p in wrong_docs_files]}")
else:
    c.ok("C7: 报告路径统一", "Markdown 报告统一输出到 output/pv_pipeline/docs/")
```

### Step 3：清理 Git 追踪中的 dashboard JSON

在 Cursor 终端执行：

```bash
git ls-files | grep 'site_series/'
git ls-files | grep 'city_series.json'
```

如果仍有输出，执行：

```bash
git rm --cached -r output/pv_pipeline/interactive_dashboard/site_series
git rm --cached output/pv_pipeline/interactive_dashboard/city_series.json
```

如果实际路径不是 `output/pv_pipeline/interactive_dashboard/`，用 `git ls-files` 输出中的真实路径替换。

然后确认：

```bash
git ls-files | grep 'site_series/' || true
git ls-files | grep 'city_series.json' || true
```

两条命令都应无输出。

### Step 4：检查 `.gitignore`

确认 `.gitignore` 包含：

```gitignore
*.pkl
*.joblib
*.parquet
output/pv_pipeline/tables/
output/pv_pipeline/interactive_dashboard/site_series/
output/pv_pipeline/interactive_dashboard/city_series.json
stages/05_visualization/data/site_series/
stages/05_visualization/data/city_series.json
__pycache__/
.DS_Store
```

如果缺少，补上。

### Step 5：重新执行验证

依次执行：

```bash
python scripts/export_interactive_dashboard_data.py
python scripts/check_dashboard_prediction_values_round35.py
python scripts/posttrain_validation_round35.py
```

预期结果：

```text
round35_dashboard_prediction_consistency.csv:
68/68 PASS
n_json == n_pkl_6_19 == n_matched
max_abs_diff_actual = 0
max_abs_diff_pred = 0
max_abs_diff_capacity = 0

Round35_产物收口与可视化一致性验证报告.md:
全部 PASS
0 FAIL
0 WARN
```

### Step 6：Git 检查

执行：

```bash
git status --short
git ls-files | grep -E '\.pkl$|\.joblib$|\.parquet$|site_series/|city_series\.json|output/pv_pipeline/tables/' || true
```

要求：

```text
不能出现 pkl/joblib/parquet/site_series/city_series/tables 输出文件
```

### Step 7：提交

如果所有检查通过，提交：

```bash
git add scripts/check_dashboard_prediction_values_round35.py \
        scripts/posttrain_validation_round35.py \
        .gitignore \
        output/pv_pipeline/metrics/round35_dashboard_prediction_consistency.csv \
        output/pv_pipeline/docs/Round35_可视化预测值一致性检查报告.md \
        output/pv_pipeline/docs/Round35_产物收口与可视化一致性验证报告.md

git commit -m "fix: finalize round35 dashboard consistency validation"
git push
```

注意：

不要 `git add` 大体积 pkl、site_series JSON、city_series JSON。

## 四、完成后回传文件

请回传：

```text
output/pv_pipeline/docs/Round35_产物收口与可视化一致性验证报告.md
output/pv_pipeline/docs/Round35_可视化预测值一致性检查报告.md
output/pv_pipeline/metrics/round35_dashboard_prediction_consistency.csv
git status --short 输出
git ls-files | grep -E '\.pkl$|\.joblib$|\.parquet$|site_series/|city_series\.json|output/pv_pipeline/tables/' || true 的输出
```

## 五、验收标准

Round35.1 通过标准：

1. 不重新训练。
2. `round35_dashboard_prediction_consistency.csv` 全部 PASS。
3. `n_json == n_pkl_6_19 == n_matched`。
4. `max_abs_diff_pred <= 1e-9`。
5. `max_abs_diff_actual <= 1e-9`。
6. `posttrain_validation_round35.py` 输出 0 FAIL、0 WARN。
7. Git 不追踪大体积结果文件。
8. 所有报告在 `output/pv_pipeline/docs/` 下。
