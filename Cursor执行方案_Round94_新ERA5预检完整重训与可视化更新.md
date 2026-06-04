# Cursor执行方案：Round94 新 ERA5 预检、完整重训与可视化更新

## 目标

你已经下载好 2023、2024、2025 三年的新 ERA5 数据，路径为：

```text
/Users/masuncheng/Downloads/光伏预测/数据集/连云港/data/2023
/Users/masuncheng/Downloads/光伏预测/数据集/连云港/data/2024
/Users/masuncheng/Downloads/光伏预测/数据集/连云港/data/2025
```

本轮目标：

1. 检查新 ERA5 文件是否完整、变量是否和原项目一致、时间是否完整、经纬度范围是否覆盖连云港站点。
2. 将新 ERA5 替换到项目 `data/2023`、`data/2024`、`data/2025`。
3. 在新输出目录完整重训一遍，不直接覆盖当前最优正式结果。
4. 完整检查训练结果、指标口径、dashboard 数据一致性。
5. 如果新 ERA5 训练结果通过检查，再更新正式可视化页面数据。

---

## 一、进入项目根目录

在 Cursor 终端执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
```

先确认当前分支和工作区：

```bash
git status
git checkout -b run/round94-era5-expanded-retrain
```

如果分支已存在，则执行：

```bash
git checkout run/round94-era5-expanded-retrain
```

---

## 二、先备份当前正式 ERA5 与当前正式输出

不要直接覆盖旧文件。先备份：

```bash
mkdir -p archive/round94_before_era5_replace/data
mkdir -p archive/round94_before_era5_replace/output

cp -r data/2023 archive/round94_before_era5_replace/data/2023
cp -r data/2024 archive/round94_before_era5_replace/data/2024
cp -r data/2025 archive/round94_before_era5_replace/data/2025

cp -r output/pv_pipeline archive/round94_before_era5_replace/output/pv_pipeline_before_round94
```

记录当前正式结果摘要：

```bash
python scripts/audit_training_metric_contract.py --output-root output/pv_pipeline
python scripts/dashboard_regression_check.py --output-root output/pv_pipeline
python scripts/check_dashboard_prediction_values.py
python scripts/posttrain_validation.py
```

---

## 三、检查新 ERA5 文件是否齐全

新 ERA5 源目录：

```bash
NEW_ERA5_ROOT="/Users/masuncheng/Downloads/光伏预测/数据集/连云港/data"
```

检查文件：

```bash
for y in 2023 2024 2025; do
  echo "===== $y ====="
  ls -lh "$NEW_ERA5_ROOT/$y"
  test -f "$NEW_ERA5_ROOT/$y/data_stream-oper_stepType-instant.nc"
  test -f "$NEW_ERA5_ROOT/$y/data_stream-oper_stepType-accum.nc"
done
```

如果文件名不是：

```text
data_stream-oper_stepType-instant.nc
data_stream-oper_stepType-accum.nc
```

需要先改名成上述名称，否则项目读取不到。

---

## 四、临时替换 ERA5 文件并做预检

先替换项目中的 ERA5 文件：

```bash
for y in 2023 2024 2025; do
  mkdir -p "data/$y"
  cp "$NEW_ERA5_ROOT/$y/data_stream-oper_stepType-instant.nc" "data/$y/data_stream-oper_stepType-instant.nc"
  cp "$NEW_ERA5_ROOT/$y/data_stream-oper_stepType-accum.nc" "data/$y/data_stream-oper_stepType-accum.nc"
done
```

执行 ERA5 预检：

```bash
python scripts/check_era5_inputs.py --data-root data --output-root output/pv_pipeline
```

预检必须确认：

```text
instant 文件包含 t2m，单位 K
accum 文件包含 ssrd，单位 J m**-2
2023 = 8760 小时
2024 = 8784 小时
2025 = 8760 小时
经纬度范围覆盖连云港主要站点
```

期望新 ERA5 范围接近或大于：

```text
North >= 35.75
West <= 118.00
South <= 33.50
East >= 120.50
```

注意：

```text
S032 经纬度疑似异常，lat=32.49。
如果只有 S032 超出范围，不要因此判定新 ERA5 失败。
但如果 S009、S020、S021、S046、S066、S095 等北侧站点仍超出范围，则说明新 ERA5 仍不合格。
```

---

## 五、新目录完整重训

不要直接覆盖正式目录。新建本轮输出：

```bash
RUN_ID="round94_era5_expanded_$(date +%Y%m%d_%H%M%S)"
OUT="output/pv_pipeline_${RUN_ID}"
echo "$OUT"
```

完整重训：

```bash
python scripts/run_full_pipeline.py --output-root "$OUT"
```

训练时间可能较长，训练完成前不要中断。

如果运行中断，先保存完整日志，不要直接反复改代码：

```bash
mkdir -p docs
```

记录失败信息到：

```text
docs/Round94_新ERA5完整重训失败记录.md
```

---

## 六、训练完成后做完整检查

训练完成后执行：

```bash
python scripts/check_era5_inputs.py --data-root data --output-root "$OUT"
python scripts/audit_training_project_structure.py --output-root "$OUT"
python scripts/audit_training_metric_contract.py --output-root "$OUT"
python scripts/dashboard_regression_check.py --output-root "$OUT"
python scripts/check_dashboard_prediction_values.py --output-root "$OUT"
python scripts/posttrain_validation.py --output-root "$OUT"
```

如果 `check_dashboard_prediction_values.py` 不支持 `--output-root`，请先补参数支持，不能默认只检查 `output/pv_pipeline`。

必须满足：

```text
posttrain_validation.py: FAIL = 0
dashboard_regression_check.py: PASS
check_dashboard_prediction_values.py: 68/68 PASS
metric contract: PASS
project structure: PASS
dashboard 不含 future
dashboard 使用 power_pred_final
```

---

## 七、对比新旧训练结果

新增或使用已有对比脚本：

```text
scripts/compare_pipeline_outputs.py
```

如果没有该脚本，请新增。对比：

```bash
python scripts/compare_pipeline_outputs.py \
  --old-output output/pv_pipeline \
  --new-output "$OUT" \
  --report docs/Round94_新ERA5训练结果对比报告.md
```

至少对比以下指标：

```text
1. 6-19 点站点平均 NRMSE 均值
2. 10-14 点站点平均 NRMSE 均值
3. 6-19 点城市 NRMSE 均值
4. 10-14 点城市 NRMSE 均值
5. 站点级 NRMSE 均值
6. 站点级 NRMSE 最大值
7. 典型最差站点是否改善
8. dashboard 是否正常
```

判断规则建议：

```text
如果新 ERA5 使整体站点 NRMSE、10-14 点 NRMSE 或城市 NRMSE 明显变好，可以采用。
如果只改善很少，但工程检查全部通过，也可以保留为候选，不立即替换正式结果。
如果新结果比当前正式版本差，不要覆盖 output/pv_pipeline。
```

---

## 八、通过后更新正式可视化页面

如果新训练结果通过检查，并确认要采用新 ERA5 结果，再更新正式 `output/pv_pipeline`。

先二次备份：

```bash
mkdir -p archive/round94_before_promote
cp -r output/pv_pipeline "archive/round94_before_promote/pv_pipeline_$(date +%Y%m%d_%H%M%S)"
```

替换正式输出：

```bash
rm -rf output/pv_pipeline
cp -r "$OUT" output/pv_pipeline
```

重新导出正式 dashboard：

```bash
python scripts/export_interactive_dashboard_data.py --output-root output/pv_pipeline
python scripts/dashboard_regression_check.py --output-root output/pv_pipeline
python scripts/check_dashboard_prediction_values.py --output-root output/pv_pipeline
python scripts/posttrain_validation.py --output-root output/pv_pipeline
```

启动可视化页面：

```bash
python3 -m http.server 8070
```

浏览器访问：

```text
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

强制刷新：

```text
Ctrl + Shift + R
```

---

## 九、如果新训练结果不如当前正式结果

不要覆盖正式结果。

只归档新输出：

```bash
mkdir -p archive/rejected_training_runs
mv "$OUT" "archive/rejected_training_runs/${RUN_ID}"
```

写说明：

```bash
cat > "archive/rejected_training_runs/${RUN_ID}/REJECTED_REASON.md" <<'EOF'
# Round94 新 ERA5 训练结果未采用

原因：

- 新 ERA5 文件已通过预检；
- 完整训练已完成；
- 但与当前正式 output/pv_pipeline 对比后，核心指标未明显改善或出现退化；
- 因此不覆盖当前正式结果。
EOF
```

---

## 十、生成本轮报告

新增报告：

```text
docs/Round94_新ERA5预检完整重训与可视化更新报告.md
```

报告必须包含：

1. 新 ERA5 来源路径。
2. 新 ERA5 变量检查结果。
3. 新 ERA5 时间完整性检查结果。
4. 新 ERA5 经纬度范围。
5. 是否仍有站点超出 ERA5 范围。
6. 完整训练输出目录。
7. posttrain validation 结果。
8. dashboard 检查结果。
9. 新旧结果对比。
10. 是否采用新结果。
11. 是否更新正式 `output/pv_pipeline`。
12. 可视化页面是否已更新。

---

## 十一、最终验收标准

本轮结束时必须满足以下之一。

### 情况 A：新结果被采用

```text
1. 新 ERA5 预检通过。
2. 新目录完整重训成功。
3. 新结果核心指标不差于当前正式结果。
4. output/pv_pipeline 已替换为新结果。
5. dashboard 已重新导出。
6. 可视化页面显示新训练数据。
7. 所有审计脚本 PASS。
```

### 情况 B：新结果未采用

```text
1. 新 ERA5 预检通过。
2. 新目录完整重训成功。
3. 但新结果指标不如当前正式结果。
4. output/pv_pipeline 未被覆盖。
5. 新训练目录已归档到 archive/rejected_training_runs。
6. 当前正式 dashboard 仍保持可用。
```

