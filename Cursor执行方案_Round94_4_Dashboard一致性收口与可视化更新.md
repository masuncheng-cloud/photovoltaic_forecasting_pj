# Cursor执行方案：Round94_4 Dashboard 一致性收口与可视化页面更新

## 目标

Round94_3 新 ERA5 干净重训已经带来明显提升，并已提升为正式 `output/pv_pipeline`。  
但报告中仍有两个验证链路问题：

```text
1. check_dashboard_prediction_values.py 显示 2/68 PASS, 66 FAIL。
2. posttrain_validation.py 仍有 C11 dashboard 一致性 FAIL。
```

本轮目标：

1. 不重训。
2. 查清 dashboard 与 pkl 预测值不一致的根因。
3. 修正 dashboard 导出或检查脚本的口径。
4. 重新导出正式可视化页面数据。
5. 让 `posttrain_validation.py` 达到 `FAIL=0`。
6. 确认可视化页面显示的是 Round94_3 最新正式结果。

---

## 一、本轮不做内容

```text
不重新训练模型
不替换 ERA5
不修改 NRMSE 公式
不修改模型结构
不覆盖 output/pv_pipeline 之外的训练结果
```

---

## 二、进入项目目录并创建分支

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
git status
git checkout -b fix/round94-4-dashboard-consistency
```

如果分支已存在：

```bash
git checkout fix/round94-4-dashboard-consistency
```

先备份当前正式 dashboard：

```bash
STAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p archive/round94_4_before_dashboard_fix
cp -r output/pv_pipeline/interactive_dashboard "archive/round94_4_before_dashboard_fix/interactive_dashboard_${STAMP}"
cp -r output/pv_pipeline/metrics "archive/round94_4_before_dashboard_fix/metrics_${STAMP}"
```

---

## 三、先定位 dashboard 差异来源

新增诊断脚本：

```text
scripts/diagnose_dashboard_prediction_mismatch.py
```

### 诊断脚本要求

读取：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
output/pv_pipeline/interactive_dashboard/site_series/*.json
output/pv_pipeline/interactive_dashboard/city_series.json
output/pv_pipeline/interactive_dashboard/metadata.json
```

检查：

1. `metadata.json` 中的：

```text
prediction_column
include_future
exclude_future
dashboard_data_scope
```

2. 对每个站点 JSON，与 pkl 按：

```text
site_id
time
```

merge。

3. 对比以下列：

```text
actual_mw vs power_mw
pred_mw vs dashboard 应使用的预测列
```

4. 分 split 统计差异：

```text
train
valid
test
future
```

5. 分小时统计差异：

```text
6-19
其他小时
```

6. 输出每个站点最大差异和差异样例。

输出：

```text
output/pv_pipeline/diagnostics/round94_4_dashboard_mismatch_by_site.csv
output/pv_pipeline/diagnostics/round94_4_dashboard_mismatch_examples.csv
output/pv_pipeline/diagnostics/round94_4_dashboard_mismatch_summary.md
```

### 预测列选择必须和导出脚本一致

先检查：

```text
scripts/export_interactive_dashboard_data.py
```

确认 dashboard 对不同 split 到底使用哪一列：

```text
test  -> power_pred_final
valid -> ?
train -> ?
```

如果导出脚本逻辑是：

```text
test/valid 使用 power_pred_final
train 使用 power_pred_cal 或 power_pred
```

那么 `check_dashboard_prediction_values.py` 必须完全采用同一逻辑，而不是统一拿 `power_pred_final` 对比。

运行诊断：

```bash
python scripts/diagnose_dashboard_prediction_mismatch.py --output-root output/pv_pipeline
```

---

## 四、修正 check_dashboard_prediction_values.py

修改：

```text
scripts/check_dashboard_prediction_values.py
```

要求：

1. 支持：

```bash
--output-root output/pv_pipeline
```

2. 不绑定 Round36/Round68。
3. 预测列选择必须和 `export_interactive_dashboard_data.py` 一致。
4. 单位必须统一为 MW。
5. 容差建议：

```text
actual_mw 容差：1e-6 MW
pred_mw 容差：1e-4 MW 或按 JSON 小数位确定
```

不要直接把容差放大到 `1e-2 MW` 来掩盖真实差异。  
如果差异达到 `6.02 MW`，必须视为真实问题，不能用容差吞掉。

输出结果必须包含：

```text
站点数
PASS 站点数
FAIL 站点数
最大 actual 差异
最大 pred 差异
最大差异样例
```

目标：

```text
68/68 PASS
最大 pred 差异 <= JSON 导出精度允许范围
```

---

## 五、修正 export_interactive_dashboard_data.py

如果诊断发现 dashboard 导出的 `pred_mw` 不是当前正式预测列，应修改：

```text
scripts/export_interactive_dashboard_data.py
```

建议统一为：

```text
所有 split 的 dashboard pred_mw 都优先使用 power_pred_final。
如果某些历史 train/valid 行没有 power_pred_final，才 fallback 到 power_pred_cal / power_pred / power_pred_raw。
```

但正式 dashboard 默认不含 future。

导出 metadata 必须包含：

```json
{
  "prediction_column": "power_pred_final",
  "include_future": false,
  "exclude_future": true,
  "dashboard_data_scope": "non_future_full_history",
  "training_round": "Round94_3",
  "era5_scope": "expanded_lianyungang"
}
```

如果不想在页面上展示版本号，也可以只写 metadata，不在 HTML 中显示。

---

## 六、重新导出可视化页面数据

执行：

```bash
python scripts/export_interactive_dashboard_data.py --output-root output/pv_pipeline
```

检查：

```bash
python scripts/dashboard_regression_check.py --output-root output/pv_pipeline
python scripts/check_dashboard_prediction_values.py --output-root output/pv_pipeline
```

目标：

```text
dashboard_regression_check.py PASS
check_dashboard_prediction_values.py 68/68 PASS
```

---

## 七、修正 posttrain_validation.py 的 C11

修改：

```text
scripts/posttrain_validation.py
```

C11 不要使用旧的硬编码检查逻辑。  
建议 C11 直接调用或复用：

```text
scripts/check_dashboard_prediction_values.py
```

如果 dashboard prediction values 通过，则 C11 PASS。

如果存在 dashboard JSON 小数精度差异，C11 应使用同一个合理容差，不要一个脚本 PASS、另一个脚本 FAIL。

执行：

```bash
python scripts/posttrain_validation.py --output-root output/pv_pipeline
```

目标：

```text
FAIL = 0
```

---

## 八、检查“典型最差5站点”指标命名问题

Round94_3 报告中出现：

```text
典型最差5站点NRMSE均值：6.14%
```

这个名称明显不合理。  
本轮需要查一下这个字段来自哪里：

```bash
grep -R "典型最差5站点" -n docs scripts output/pv_pipeline/docs output/pv_pipeline/metrics || true
grep -R "worst.*5\\|typical.*worst\\|最差5" -n scripts output/pv_pipeline/docs output/pv_pipeline/metrics || true
```

处理规则：

```text
如果实际是“预测最好5站点”，改名为“预测最好5站点”。
如果实际是“典型站点中的最差组”，改名为“典型最差组站点”。
如果计算逻辑错了，修正为真正的 NRMSE 最大 5 个站点。
```

不要保留“最差5站点 NRMSE 只有 6%”这种容易误导的表述。

---

## 九、启动并检查可视化页面

启动服务：

```bash
python3 -m http.server 8070
```

访问：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

浏览器强制刷新：

```text
Ctrl + Shift + R
```

页面检查：

```text
1. 页面能正常打开。
2. 全市总出力曲线有数据。
3. 单站点曲线有数据。
4. 逐小时预测结果表正常。
5. 样本量与 NRMSE 散点图正常。
6. 页面不显示旧 Round36/Round68 警告。
7. 页面不包含 future 数据。
8. S115/S116 不再表现为整段预测为 0。
```

---

## 十、生成本轮报告

新增：

```text
docs/Round94_4_Dashboard一致性收口与可视化更新报告.md
```

报告必须包含：

1. dashboard mismatch 诊断结论。
2. 最大差异来源。
3. 修复了 `check_dashboard_prediction_values.py` 还是 `export_interactive_dashboard_data.py`，或两者都修。
4. 修复后 `check_dashboard_prediction_values.py` 结果。
5. 修复后 `posttrain_validation.py` 结果。
6. 是否重新导出 dashboard。
7. 可视化页面是否已更新。
8. 是否还有 C11 FAIL。
9. 是否修正“典型最差5站点”命名或计算。

---

## 十一、验收标准

本轮完成后必须满足：

```text
1. check_dashboard_prediction_values.py 68/68 PASS。
2. posttrain_validation.py FAIL=0。
3. dashboard_regression_check.py PASS。
4. output/pv_pipeline/interactive_dashboard 已重新导出。
5. 可视化页面能打开且显示 Round94_3 正式结果。
6. 页面不含 future 数据。
7. 不再用大容差掩盖 MW 级差异。
8. “典型最差5站点”指标命名或计算已修正。
```

