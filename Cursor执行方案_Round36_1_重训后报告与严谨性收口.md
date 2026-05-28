# Round36.1 重训后报告与严谨性收口方案

## 一、是否需要重新训练？

**不需要。**

Round36 已经完成完整重训，并且核心链路通过：

```text
完整训练成功
final_round36 / final_eval_round36 已生成
eval 只含 test 6-19
power_pred_final 已落地
可视化 actual/pred 全量一致
全市 NRMSE 使用城市总出力聚合口径
Git 不追踪大体积结果文件
```

当前剩余问题是：

1. 报告中 `0 WARN` 与实际 `2 WARN` 矛盾。
2. Round34 对比基准数值疑似不一致。
3. 正式项目报告中仍出现 MAPE。
4. 训练日志标记为“手动生成”，严谨性不够。
5. S115、S116 经纬度缺失需要保留说明。

因此 Round36.1 只做报告、校验和日志自动化收口，不重新训练模型。

## 二、需要修复的问题

### 2.1 修正 posttrain_validation 的 WARN 表述

Round36 执行反馈中存在矛盾：

```text
验收标准核对：posttrain_validation 0 FAIL、0 WARN
全链路验证结果：16 PASS / 0 FAIL / 2 WARN
```

正确表述应为：

```text
posttrain_validation：0 FAIL，2 WARN
```

并说明两个 WARN：

1. `future` 在 pkl 中存在，但已排除指标和默认可视化。
2. 训练日志为手动生成或非训练脚本自动生成。

### 2.2 核对 Round34 对比基准

Round36 报告中写：

```text
Round34 全市 10-14 时 NRMSE = 6.31%
Round36 全市 10-14 时 NRMSE = 4.25%
下降 2.06pp
```

但之前 Round34 反馈中曾出现：

```text
Round34 全市 10-14 点 NRMSE = 5.78%
```

必须重新从真实 CSV 核对，而不是手写。

核对文件优先级：

```text
output/pv_pipeline/metrics/round34_city_hourly_nrmse.csv
output/pv_pipeline/archive_before_round36/round34_city_hourly_nrmse.csv
```

如果只有一个存在，就用存在的那个。

计算方式：

```python
df = pd.read_csv("round34_city_hourly_nrmse.csv")
sub = df[df["hour"].between(10, 14)]

如果存在 nrmse_city_pct:
    round34_10_14 = sub["nrmse_city_pct"].mean()
elif 存在 nrmse_pct:
    round34_10_14 = sub["nrmse_pct"].mean()
else:
    报错
```

同理计算 Round36：

```text
output/pv_pipeline/metrics/round36_city_hourly_nrmse.csv
```

输出：

```text
output/pv_pipeline/metrics/round36_vs_round34_metric_check.csv
```

字段：

```text
metric
round34_value_pct
round36_value_pct
delta_pp
source_round34
source_round36
status
```

### 2.3 正式报告中删除 MAPE

用户前面已经要求：

```text
训练结果里不再使用 MAPE
```

因此正式 `光伏功率预测项目.md` 中：

1. 不得在核心训练结果表中展示 MAPE。
2. 如确需保留，只能放到附录，并明确“不作为核心评价指标”。
3. 主指标只使用：

```text
MAE（MW）
RMSE（MW）
NRMSE（%）
BIAS（% 或 MW）
pred/actual
Corr
```

建议直接从正式报告中删除 MAPE。

### 2.4 训练日志自动化

当前 WARN：

```text
C16 训练日志存在：WARN（手动生成）
```

需要修改：

```text
scripts/run_round36_full_retrain.py
```

让训练脚本自动写出：

```text
output/pv_pipeline/docs/Round36_训练日志.md
```

日志内容至少包含：

```text
训练开始时间
训练结束时间
训练耗时
训练入口脚本
训练样本数
验证样本数
测试样本数
future 样本数
站点数
特征列数量
特征列清单
目标列
模型参数
随机种子
输出文件路径
```

如果完整重训已经完成，本轮不重新训练，可以新增一个日志补全脚本：

```text
scripts/generate_round36_training_log.py
```

读取现有产物和模型配置，自动生成训练日志，并在日志中注明：

```text
本日志由 Round36.1 根据 Round36 已完成训练产物自动补全生成，未重新训练。
```

然后修改 `posttrain_validation_round36.py`：

```python
如果 Round36_训练日志.md 存在，且包含训练入口、样本数、split 边界、输出文件，则 PASS。
```

不要再因为“手动生成”给 WARN。

### 2.5 S115/S116 经纬度缺失保留说明

训练前审计中：

```text
S115, S116 经纬度缺失
```

目前解释为：

```text
模型使用 ERA5，不依赖站点经纬度
```

正式报告中应保留一句：

```text
S115、S116 存在经纬度缺失，但当前 Round36 分布式模型使用统一气象/ERA5 特征和站点统计特征，未直接依赖单站经纬度；若后续启用太阳高度角、clear-sky 等站点物理特征，应先补齐这两个站点经纬度。
```

## 三、Cursor 修改步骤

### Step 1：新增 Round34/Round36 指标核对脚本

新建：

```text
scripts/check_round36_vs_round34_metrics.py
```

实现：

```python
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "output" / "pv_pipeline" / "metrics"
ARCHIVE = ROOT / "output" / "pv_pipeline" / "archive_before_round36"
OUT = METRICS / "round36_vs_round34_metric_check.csv"

def find_round34_city_file():
    candidates = [
        METRICS / "round34_city_hourly_nrmse.csv",
        ARCHIVE / "round34_city_hourly_nrmse.csv",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError("找不到 round34_city_hourly_nrmse.csv")

def calc_10_14(path):
    df = pd.read_csv(path)
    sub = df[df["hour"].between(10, 14)].copy()
    if "nrmse_city_pct" in sub.columns:
        col = "nrmse_city_pct"
    elif "nrmse_pct" in sub.columns:
        col = "nrmse_pct"
    else:
        raise KeyError(f"{path} 中没有 nrmse_city_pct/nrmse_pct")
    return float(sub[col].mean())

round34_path = find_round34_city_file()
round36_path = METRICS / "round36_city_hourly_nrmse.csv"

round34_val = calc_10_14(round34_path)
round36_val = calc_10_14(round36_path)

df = pd.DataFrame([{
    "metric": "city_10_14_nrmse_pct",
    "round34_value_pct": round(round34_val, 4),
    "round36_value_pct": round(round36_val, 4),
    "delta_pp": round(round36_val - round34_val, 4),
    "source_round34": str(round34_path),
    "source_round36": str(round36_path),
    "status": "PASS",
}])
df.to_csv(OUT, index=False, encoding="utf-8-sig")
print(df.to_string(index=False))
print(f"saved: {OUT}")
```

### Step 2：新增训练日志自动补全脚本

新建：

```text
scripts/generate_round36_training_log.py
```

要求：

1. 读取：

```text
output/pv_pipeline/tables/distributed_predictions_final_round36.pkl
output/pv_pipeline/tables/distributed_predictions_final_eval_round36.pkl
output/pv_pipeline/metrics/round36_pretrain_audit.csv
```

2. 统计：

```text
train 行数
valid 行数
test 行数
future 行数
站点数
test 6-19 行数
test 6-19 站点数
```

3. 尝试读取训练脚本中的特征列，如果无法自动读取，则写：

```text
特征列清单见 train_distributed_model_v159.py 中 FEATURE_COLS 或训练表字段；本日志未重新训练。
```

4. 输出：

```text
output/pv_pipeline/docs/Round36_训练日志.md
```

日志中必须明确：

```text
本日志由 Round36.1 根据 Round36 已完成训练产物自动补全生成，未重新训练。
```

### Step 3：修改 posttrain_validation_round36.py

修改：

```text
scripts/posttrain_validation_round36.py
```

#### 3.1 C16 训练日志检查改为严格内容检查

检查：

```python
log_path = DOCS / "Round36_训练日志.md"
content = log_path.read_text(encoding="utf-8")
required_terms = [
    "训练入口",
    "train",
    "valid",
    "test",
    "future",
    "distributed_predictions_final_round36.pkl",
    "distributed_predictions_final_eval_round36.pkl",
]
```

如果存在并包含所有关键词：

```text
PASS
```

否则：

```text
FAIL
```

不要再输出“手动生成” WARN。

#### 3.2 C5 future 检查改为 PASS

如果：

1. final pkl 中包含 future；
2. metrics 文件均不包含 future；
3. 可视化默认不含 future；

则 C5 应为：

```text
PASS：future 保留在 final_full 中，但已排除指标和默认可视化
```

不要再给 WARN。

### Step 4：修改项目报告生成脚本

修改：

```text
scripts/regenerate_project_report_round36.py
```

要求：

1. 删除核心结果中的 MAPE。
2. 项目报告核心指标只保留：

```text
MAE
RMSE
NRMSE
BIAS
pred/actual
Corr
```

3. 加入 Round34/Round36 对比时，必须读取：

```text
output/pv_pipeline/metrics/round36_vs_round34_metric_check.csv
```

不要手写 Round34 基准。

4. 报告中加入 S115/S116 经纬度说明。

5. 报告中 `posttrain_validation` 表述改为：

```text
0 FAIL，0 WARN
```

只有在重新运行 validation 真正 0 WARN 后才能这样写。

### Step 5：重新运行收口脚本

依次执行：

```bash
python scripts/check_round36_vs_round34_metrics.py
python scripts/generate_round36_training_log.py
python scripts/regenerate_project_report_round36.py
python scripts/posttrain_validation_round36.py
```

如果 `posttrain_validation_round36.py` 仍有 WARN 或 FAIL，先修复，不要提交。

### Step 6：检查正式报告中是否仍有 MAPE

执行：

```bash
grep -n "MAPE" 光伏功率预测项目.md || true
grep -n "0.3365\\|0.3420" 光伏功率预测项目.md || true
```

要求：

1. `MAPE` 不应出现在正式核心结果中。
2. `0.3365`、`0.3420` 不应出现。

### Step 7：Git 检查

执行：

```bash
git status --short
git ls-files | grep -E '\.pkl$|\.joblib$|\.parquet$|site_series/|city_series\.json|output/pv_pipeline/tables/' || true
```

要求：

```text
不能出现 pkl/joblib/parquet/site_series/city_series/tables 输出文件
```

### Step 8：提交

如果全部通过，提交：

```bash
git add scripts/check_round36_vs_round34_metrics.py \
        scripts/generate_round36_training_log.py \
        scripts/posttrain_validation_round36.py \
        scripts/regenerate_project_report_round36.py \
        output/pv_pipeline/metrics/round36_vs_round34_metric_check.csv \
        output/pv_pipeline/docs/Round36_训练日志.md \
        output/pv_pipeline/docs/Round36_训练逻辑与可视化一致性验证报告.md \
        光伏功率预测项目.md

git commit -m "docs: finalize round36 training validation report"
git push
```

## 四、验收标准

Round36.1 完成后必须满足：

1. 不重新训练。
2. `posttrain_validation_round36.py` 输出：

```text
0 FAIL
0 WARN
```

3. `光伏功率预测项目.md` 核心结果中不出现 MAPE。
4. `光伏功率预测项目.md` 不出现 `0.3365`、`0.3420`。
5. Round34/Round36 对比来自 CSV 自动核对结果。
6. `Round36_训练日志.md` 自动补全生成，并包含 split 行数、训练入口、输出文件。
7. S115/S116 经纬度缺失说明保留。
8. Git 不追踪大体积结果文件。

## 五、完成后回传文件

请回传：

```text
output/pv_pipeline/metrics/round36_vs_round34_metric_check.csv
output/pv_pipeline/docs/Round36_训练日志.md
output/pv_pipeline/docs/Round36_训练逻辑与可视化一致性验证报告.md
光伏功率预测项目.md
git status --short 输出
grep -n "MAPE" 光伏功率预测项目.md || true 输出
```
