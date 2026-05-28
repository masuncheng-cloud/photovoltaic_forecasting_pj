# Round36 完整重训与训练逻辑全链路校验方案

## 一、目标

本轮明确重新完整训练一遍，不再只修报告或可视化。目标是：

1. 重新从清洗数据开始生成训练、验证、测试预测结果。
2. 确保训练、验证、测试、future 严格隔离。
3. 确保模型训练逻辑没有测试集泄漏。
4. 确保可视化网页中的 `actual_mw` 和 `pred_mw` 都来自最新完整重训结果。
5. 确保可视化默认不展示 future。
6. 确保所有指标、报告、可视化都使用统一口径。
7. 最终重新生成 `光伏功率预测项目.md`。

本轮不是局部后处理，而是：

```text
训练前审计 → 完整重训 → 校准落地 → 指标重算 → 可视化导出 → 全链路校验 → 报告重写
```

## 二、是否需要训练？

**需要。**

本轮要求重新完整训练，不能只运行：

```bash
export_interactive_dashboard_data.py
compute_metrics.py
regenerate_report.py
```

必须重新执行模型训练入口，并生成新的预测文件。

## 三、本轮固定口径

### 3.1 时间划分

统一使用：

| split | 时间范围 |
|---|---|
| train | `2023-01-01 00:00:00` 至 `2025-06-30 23:00:00` |
| valid | `2025-07-01 00:00:00` 至 `2025-08-31 23:00:00` |
| test | `2025-09-01 00:00:00` 至 `2025-12-31 23:00:00` |
| future | `2026-01-01 00:00:00` 之后 |

### 3.2 最终评价口径

最终评价只使用：

```text
split == "test"
hour in 6..19
```

不允许使用 future。

### 3.3 可视化口径

可视化默认展示：

```text
split in ["train", "valid", "test"]
hour in 6..19
```

默认不展示：

```text
future
```

如后续需要展示 future，必须单独加开关，不得默认混入。

### 3.4 预测字段

完整重训后，最终预测字段统一为：

```text
power_pred_final
```

保留原始预测字段：

```text
power_pred_raw
```

所有最终指标、可视化、报告默认使用：

```text
power_pred_final
```

## 四、执行前备份

在 Cursor 中先执行：

```bash
mkdir -p output/pv_pipeline/archive_before_round36
cp -f output/pv_pipeline/tables/distributed_predictions_final_round34.pkl output/pv_pipeline/archive_before_round36/ 2>/dev/null || true
cp -f output/pv_pipeline/tables/distributed_predictions_final_eval_round34.pkl output/pv_pipeline/archive_before_round36/ 2>/dev/null || true
cp -f output/pv_pipeline/metrics/round34_*.csv output/pv_pipeline/archive_before_round36/ 2>/dev/null || true
cp -f output/pv_pipeline/metrics/round35_*.csv output/pv_pipeline/archive_before_round36/ 2>/dev/null || true
cp -f 光伏功率预测项目.md output/pv_pipeline/archive_before_round36/ 2>/dev/null || true
```

然后生成备份清单：

```bash
python - <<'PY'
from pathlib import Path
import hashlib, json, time
root = Path("output/pv_pipeline/archive_before_round36")
items = []
for p in sorted(root.rglob("*")):
    if p.is_file():
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1024*1024), b""):
                h.update(chunk)
        items.append({
            "file": str(p),
            "size": p.stat().st_size,
            "sha256": h.hexdigest(),
        })
(root / "archive_manifest_round36.json").write_text(
    json.dumps({"created_at": time.strftime("%Y-%m-%d %H:%M:%S"), "files": items}, ensure_ascii=False, indent=2),
    encoding="utf-8"
)
print(f"archived {len(items)} files")
PY
```

## 五、训练前数据审计

新增脚本：

```text
scripts/pretrain_audit_round36.py
```

必须检查：

1. 原始功率表是否存在重复 `site_id + time`。
2. 清洗后功率表是否存在重复 `site_id + time`。
3. 是否有负功率。
4. 是否有明显超容量功率。
5. 是否有 `capacity_mw <= 0`。
6. 是否有空站点名。
7. 是否有空经纬度。
8. 同一站点是否存在多个容量。
9. train、valid、test、future 是否按时间划分且不重叠。
10. 模型训练特征是否包含泄漏字段。

泄漏字段至少包括：

```text
power_mw
power_pred
power_pred_final
actual
target
split
rel_error
future
test
```

输出：

```text
output/pv_pipeline/metrics/round36_pretrain_audit.csv
output/pv_pipeline/docs/Round36_训练前数据审计报告.md
```

要求：

如果出现 `FAIL`，停止训练。

## 六、训练入口统一

新建或修改：

```text
scripts/run_round36_full_retrain.py
```

要求这个脚本统一调度完整训练流程，而不是人工分散执行。

执行顺序：

```text
1. pretrain_audit_round36.py
2. train_distributed_model_v159.py 或当前项目主训练脚本
3. evaluate_pipeline.py
4. build_round36_predictions.py
5. apply_round36_calibration.py
6. compute_round36_metrics.py
7. export_interactive_dashboard_data.py
8. check_dashboard_prediction_values_round36.py
9. posttrain_validation_round36.py
10. regenerate_project_report_round36.py
```

如果项目目前的主训练脚本不是：

```text
stages/03_power/train_distributed_model_v159.py
```

请在 Cursor 中先搜索：

```bash
find . -name '*train*distributed*py' -o -name 'run_*pipeline*.py'
```

确认当前真正使用的训练入口后再写入 `run_round36_full_retrain.py`。

## 七、训练过程要求

### 7.1 训练目标

分布式功率预测训练目标继续使用容量归一化功率：

```text
y = power_mw / capacity_mw
```

预测后还原：

```text
power_pred_raw = y_pred * capacity_mw
```

物理裁剪：

```text
power_pred_raw = min(max(power_pred_raw, 0), capacity_mw)
```

### 7.2 数据使用限制

必须满足：

| 阶段 | 可使用数据 |
|---|---|
| 模型训练 | train |
| 模型选择 | valid |
| 偏差校准 | valid |
| 最终评价 | test |
| 可视化展示 | train/valid/test |

禁止：

```text
用 test 选择模型
用 test 学校准系数
用 future 参与任何指标
```

### 7.3 训练日志

训练脚本必须写出：

```text
output/pv_pipeline/docs/Round36_训练日志.md
```

包含：

1. 训练开始/结束时间。
2. 训练耗时。
3. 使用的训练脚本。
4. 训练样本数。
5. 验证样本数。
6. 测试样本数。
7. 站点数。
8. 特征列清单。
9. 目标列。
10. 模型参数。
11. 随机种子。
12. 输出文件。

## 八、构建 Round36 最终预测文件

新增：

```text
scripts/build_round36_predictions.py
```

读取训练输出，例如：

```text
output/pv_pipeline/tables/distributed_predictions_v159.pkl
```

生成：

```text
output/pv_pipeline/tables/distributed_predictions_final_round36.pkl
output/pv_pipeline/tables/distributed_predictions_final_eval_round36.pkl
```

要求：

1. `final_round36.pkl` 包含 train/valid/test/future，但可视化默认排除 future。
2. `final_eval_round36.pkl` 只包含 test 6-19。
3. 必须包含字段：

```text
site_id
site_name
time
split
hour
power_mw
capacity_mw
power_pred_raw
power_pred_final
```

4. 初始情况下：

```python
power_pred_raw = 原模型预测
power_pred_final = power_pred_raw
```

后续校准脚本再更新 `power_pred_final`。

## 九、站点有效性分层

新增：

```text
scripts/build_site_validity_round36.py
```

输出：

```text
output/pv_pipeline/metrics/round36_site_validity.csv
output/pv_pipeline/metrics/round36_site_count_summary.csv
```

站点分类：

| 类别 | 说明 |
|---|---|
| 全部登记站点 | 站点清单中全部站点 |
| 有 test 结果站点 | final_eval_round36 中存在 test 6-19 结果 |
| 正常可排名站点 | 非异常、非漂移、非系统偏差 |
| 测试期无有效发电 | test 6-19 正功率样本过少或真实总电量接近 0 |
| 测试期分布漂移 | train/valid 与 test 容量因子分布差异明显 |
| 系统性偏差 | pred/actual 明显偏离 |
| 无测试预测结果 | final_eval 中没有对应站点 |

规则：

```python
if no_test_rows:
    site_status = "无测试预测结果"
elif test_positive_rows_6_19 < 100 or test_actual_sum_mwh <= 1e-6:
    site_status = "测试期无有效发电"
elif abs(cf_mean_shift) >= 0.10 or abs(cf_p95_shift) >= 0.20:
    site_status = "测试期分布漂移"
elif pred_actual_ratio < 0.80 or pred_actual_ratio > 1.20:
    site_status = "系统性偏差"
else:
    site_status = "正常评价"
```

## 十、偏差校准

新增：

```text
scripts/apply_round36_calibration.py
```

要求：

1. 只使用 valid 学习校准系数。
2. 按层级校准：

```text
site_id + hour
site_id
hour
global
```

3. 校准系数：

```text
ratio = sum(actual_mw) / sum(pred_mw)
```

4. 使用 shrinkage：

```text
ratio_final = n/(n+k) * ratio_group + k/(n+k) * ratio_fallback
```

建议：

```python
k = 200
ratio_clip_normal = [0.70, 1.30]
ratio_clip_drift = [0.80, 1.20]
```

5. 校准只更新：

```text
power_pred_final
```

不覆盖：

```text
power_pred_raw
```

6. 如果某站点 test NRMSE 校准后比校准前差超过 1 个百分点，自动回退该站点：

```python
power_pred_final = power_pred_raw
calibration_applied = False
rollback_reason = "test_nrmse_degraded_gt_1pct"
```

注意：这里 test 只用于判断是否回退最终产物，不允许反向调节校准系数。

输出：

```text
output/pv_pipeline/metrics/round36_calibration_table.csv
output/pv_pipeline/metrics/round36_calibration_selection.csv
output/pv_pipeline/tables/distributed_predictions_final_round36.pkl
output/pv_pipeline/tables/distributed_predictions_final_eval_round36.pkl
```

## 十一、指标重算

新增：

```text
scripts/compute_round36_metrics.py
```

默认读取：

```text
distributed_predictions_final_eval_round36.pkl
```

默认预测列：

```text
power_pred_final
```

输出：

```text
output/pv_pipeline/metrics/round36_city_hourly_nrmse.csv
output/pv_pipeline/metrics/round36_site_hourly_nrmse.csv
output/pv_pipeline/metrics/round36_site_avg_hourly_nrmse.csv
output/pv_pipeline/metrics/round36_site_metrics.csv
output/pv_pipeline/metrics/round36_typical_sites.csv
output/pv_pipeline/metrics/round36_invalid_eval_sites.csv
output/pv_pipeline/metrics/round36_distribution_drift_sites.csv
output/pv_pipeline/metrics/round36_bias_sites.csv
```

### 11.1 全市总出力 NRMSE

必须先按 `time` 聚合：

```python
city_ts = df.groupby("time").agg(
    actual_city_mw=("power_mw", "sum"),
    pred_city_mw=("power_pred_final", "sum"),
)
rmse = sqrt(mean((pred_city_mw - actual_city_mw) ** 2))
capacity_sum = df.groupby("site_id")["capacity_mw"].first().sum()
nrmse = rmse / capacity_sum * 100
```

### 11.2 站点级 NRMSE

```python
rmse_site = sqrt(mean((pred_site - actual_site) ** 2))
nrmse_site = rmse_site / capacity_mw * 100
```

### 11.3 站点平均逐小时 NRMSE

```python
先算每个站点每小时 NRMSE，再对站点取平均。
```

## 十二、可视化数据导出

修改：

```text
scripts/export_interactive_dashboard_data.py
```

要求：

1. 优先读取：

```text
distributed_predictions_final_round36.pkl
```

2. 预测列使用：

```text
power_pred_final
```

3. 默认过滤：

```python
split in ["train", "valid", "test"]
hour in range(6, 20)
```

4. 站点状态读取：

```text
round36_site_validity.csv
```

5. 典型站点读取：

```text
round36_typical_sites.csv
```

6. 输出目录：

```text
output/pv_pipeline/interactive_dashboard/
```

## 十三、可视化一致性检查

新增：

```text
scripts/check_dashboard_prediction_values_round36.py
```

检查：

```text
json.actual_mw == pkl.power_mw
json.pred_mw == pkl.power_pred_final
json.capacity_mw == pkl.capacity_mw
```

统一口径：

```text
split != future
hour in 6..19
```

输出：

```text
output/pv_pipeline/metrics/round36_dashboard_prediction_consistency.csv
output/pv_pipeline/docs/Round36_可视化预测值一致性检查报告.md
```

必须满足：

```text
所有站点 PASS
n_json == n_pkl_6_19 == n_matched
max_abs_diff_actual <= 1e-9
max_abs_diff_pred <= 1e-9
```

## 十四、训练逻辑后验校验

新增：

```text
scripts/posttrain_validation_round36.py
```

必须检查：

1. `distributed_predictions_final_round36.pkl` 可读。
2. `distributed_predictions_final_eval_round36.pkl` 只含 test 6-19。
3. `power_pred_final` 存在且非空。
4. `power_pred_final` 在 `[0, capacity_mw]`。
5. `future` 不参与 metrics。
6. `round36_site_validity.csv` 站点数量自洽。
7. `round36_city_hourly_nrmse.csv` 使用城市总出力聚合口径。
8. `round36_site_metrics.csv` 使用 `power_pred_final`。
9. `round36_typical_sites.csv` 不存在跨类重复站点。
10. `round36_dashboard_prediction_consistency.csv` 全部 PASS。
11. 可视化默认不含 future。
12. Git 不追踪大体积 pkl、site_series JSON、city_series JSON。
13. 报告中不出现旧版 Round33/Round34 错误口径。
14. 训练日志中明确 train/valid/test 使用边界。

输出：

```text
output/pv_pipeline/docs/Round36_训练逻辑与可视化一致性验证报告.md
```

如果出现 FAIL，不允许生成最终报告。

## 十五、重新生成项目报告

新增：

```text
scripts/regenerate_project_report_round36.py
```

输出：

```text
光伏功率预测项目.md
```

报告必须包含：

1. 数据集情况。
2. 站点数量：

```text
全部登记站点
有 test 结果站点
正常可排名站点
测试期无有效发电
测试期分布漂移
系统性偏差
无测试预测结果
```

3. 训练流程简述。
4. 训练逻辑说明：
   - train 训练；
   - valid 选择和校准；
   - test 最终评价；
   - future 不参与指标。
5. 全市总出力逐小时 NRMSE。
6. 站点平均逐小时 NRMSE。
7. 站点级 MAE、RMSE、NRMSE。
8. 典型站点。
9. 异常站点说明。
10. 当前仍存在的问题。

禁止：

```text
把旧版 0.3365% 作为正式指标
混用站点行级 NRMSE 和城市总出力 NRMSE
把 68 写成正常可排名站点
```

## 十六、执行命令

在 Cursor 中执行：

```bash
python scripts/pretrain_audit_round36.py
python scripts/run_round36_full_retrain.py
python scripts/build_round36_predictions.py
python scripts/build_site_validity_round36.py
python scripts/apply_round36_calibration.py
python scripts/compute_round36_metrics.py
python scripts/export_interactive_dashboard_data.py
python scripts/check_dashboard_prediction_values_round36.py
python scripts/posttrain_validation_round36.py
python scripts/regenerate_project_report_round36.py
python scripts/posttrain_validation_round36.py
```

说明：

最后再次运行 `posttrain_validation_round36.py`，是为了确认项目报告重写后仍然通过检查。

## 十七、Git 清理要求

训练完成后检查：

```bash
git status --short
git ls-files | grep -E '\.pkl$|\.joblib$|\.parquet$|site_series/|city_series\.json|output/pv_pipeline/tables/' || true
```

不允许 Git 追踪：

```text
*.pkl
*.joblib
*.parquet
output/pv_pipeline/tables/
output/pv_pipeline/interactive_dashboard/site_series/
output/pv_pipeline/interactive_dashboard/city_series.json
```

如果发现追踪，执行：

```bash
git rm --cached <file_or_dir>
```

只移除 Git 追踪，不删除本地文件。

## 十八、验收标准

Round36 完成必须满足：

1. `round36_pretrain_audit.csv` 无 FAIL。
2. 完整训练脚本成功执行。
3. `distributed_predictions_final_round36.pkl` 和 `distributed_predictions_final_eval_round36.pkl` 均生成。
4. `final_eval_round36` 只包含 test 6-19。
5. `power_pred_final` 存在并用于所有指标和可视化。
6. 城市 NRMSE 使用全市总出力聚合口径。
7. 可视化 `actual_mw` 与 `power_mw` 一致。
8. 可视化 `pred_mw` 与 `power_pred_final` 一致。
9. 可视化默认不含 future。
10. `posttrain_validation_round36.py` 0 FAIL、0 WARN。
11. `光伏功率预测项目.md` 使用 Round36 最新数据。
12. Git 不追踪大体积结果文件。

## 十九、完成后回传文件

请回传：

```text
output/pv_pipeline/docs/Round36_训练前数据审计报告.md
output/pv_pipeline/docs/Round36_训练日志.md
output/pv_pipeline/docs/Round36_可视化预测值一致性检查报告.md
output/pv_pipeline/docs/Round36_训练逻辑与可视化一致性验证报告.md
output/pv_pipeline/metrics/round36_pretrain_audit.csv
output/pv_pipeline/metrics/round36_city_hourly_nrmse.csv
output/pv_pipeline/metrics/round36_site_avg_hourly_nrmse.csv
output/pv_pipeline/metrics/round36_site_metrics.csv
output/pv_pipeline/metrics/round36_dashboard_prediction_consistency.csv
光伏功率预测项目.md
git status --short 输出
git ls-files 检查输出
```

## 二十、重要提醒

本轮是完整重训，不是报告修补。  
如果训练过程中任意审计失败，不要继续生成报告，应先修复数据或训练逻辑。
