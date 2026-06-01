# Cursor执行方案 Round63：基线保存复核与离线分场景残差模型实验

## 一、目标

本轮分两步执行：

1. **先复核 Round61 稳定基线是否真的可恢复**  
   确认 Git commit、Git tag、baseline manifest、关键产物 SHA256 都存在，避免后续模型结构实验效果变差时无法回退。

2. **再进入模型结构层面的离线实验**  
   不直接覆盖 `power_pred_final`，只生成候选预测列，用 valid 集选择候选，用 test 集做最终评估。若候选效果不如 Round61，自动保留 Round61。

本轮重点不是改指标公式，也不是继续堆后处理，而是验证：在 Round61 稳定结果基础上，分场景残差模型是否能真实提升预测效果。

---

## 二、执行前约束

请严格遵守：

- 不使用 test 集调参。
- 不修改 Round61 已确认的正式结果文件。
- 新模型输出只写入 candidate 列，例如 `power_pred_round63_residual`。
- 只有通过 valid 安全门控后，才允许生成 `power_pred_final_candidate_round63`。
- 如果候选在 test 上不优于 Round61，最终报告必须明确写出“保持 Round61，不采用 Round63”。
- 不提交大型 `.pkl/.joblib/.parquet/.npy` 文件到 GitHub，只提交代码、配置、报告、轻量 CSV/JSON 指标。

---

## 三、第一步：复核 Round61 稳定基线

### 3.1 检查 Git 状态

在 Cursor 终端执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
git status
git branch --show-current
git remote -v
git tag | grep round61
```

要求：

- 当前工作区不能有未解释的脏文件。
- 必须存在类似 `round61-stable-20260601` 的 tag。
- 如果 tag 不存在，先不要继续模型实验，先补 tag。

### 3.2 新增基线复核脚本

新建：

```text
scripts/verify_round61_baseline.py
```

功能：

1. 检查以下文件是否存在：

```text
output/pv_pipeline/baselines/round61/round61_baseline_manifest.json
output/pv_pipeline/baselines/round61/round61_baseline_files.csv
docs/Round61_稳定基线说明.md
```

2. 读取 manifest 中记录的关键文件路径和 SHA256。

3. 对当前文件重新计算 SHA256，与 manifest 对比。

4. 输出：

```text
output/pv_pipeline/baselines/round61/round61_baseline_verify_report.csv
docs/Round63_Round61基线复核报告.md
```

报告至少包含：

| 项目 | 内容 |
|---|---|
| 当前分支 | `git branch --show-current` |
| 当前 commit | `git rev-parse HEAD` |
| Round61 tag | tag 名称 |
| tag commit | `git rev-list -n 1 round61-stable-20260601` |
| manifest 文件数 | 数量 |
| SHA256 通过数 | 数量 |
| SHA256 失败数 | 数量 |
| 是否可恢复 | PASS / FAIL |

如果有任一关键文件缺失或 SHA256 不一致，脚本必须退出非 0。

### 3.3 执行复核

```bash
python scripts/verify_round61_baseline.py
```

必须通过后，才能进入下一步。

---

## 四、第二步：建立 Round63 离线分场景残差实验

### 4.1 新增实验配置

新建：

```text
configs/round63_residual_experiment.yaml
```

建议内容：

```yaml
baseline_prediction_col: power_pred_final
target_col: power_mw
capacity_col: capacity_mw
split_col: split

eval_hours: [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]

scenes:
  dawn:
    hours: [6, 7, 8]
  day:
    hours: [9, 10, 11, 12, 13, 14, 15, 16]
  dusk:
    hours: [17, 18, 19]

residual_target: capacity_normalized

valid_guard:
  max_site_mean_nrmse_pp_increase: 0.10
  max_city_nrmse_pp_increase: 0.10
  max_bad_site_count_gt_1pp: 0
  require_10_14_city_nrmse_not_worse: true

test_guard:
  report_only: true
```

---

## 五、残差建模逻辑

### 5.1 残差目标

不要直接预测 MW 残差，使用容量归一化残差：

```text
y_true_norm = power_mw / capacity_mw

y_base_norm = power_pred_final / capacity_mw

residual_norm = y_true_norm - y_base_norm
```

候选预测：

```text
y_candidate_norm = y_base_norm + residual_pred_norm

power_pred_round63_residual = clip(
    y_candidate_norm * capacity_mw,
    0,
    capacity_mw
)
```

这样可以避免大容量站点完全主导模型，也能让不同容量站点的残差更可比。

### 5.2 分场景训练

新增脚本：

```text
scripts/train_round63_scene_residual_models.py
```

训练方式：

1. 读取 Round61 final 结果。
2. 只使用 `split in ["train", "valid"]` 建模。
3. 按场景拆分：
   - `dawn`: 6-8 点；
   - `day`: 9-16 点；
   - `dusk`: 17-19 点。
4. 每个场景单独训练一个轻量模型。

优先使用现有依赖中已经存在的模型库。若项目已有 LightGBM/XGBoost，可使用；如果没有，先用 sklearn：

```python
HistGradientBoostingRegressor
RandomForestRegressor
Ridge
```

建议先做两个候选：

| 候选 | 说明 |
|---|---|
| `ridge_residual` | 线性、稳定、可解释，防止过拟合 |
| `hgb_residual` | 非线性，捕捉场景残差 |

不要一开始引入过复杂模型。

### 5.3 推荐特征

优先使用项目中已经存在的字段。缺失字段不要硬造。

建议特征：

```text
hour
month
dayofyear
capacity_mw
power_pred_final
power_pred_final / capacity_mw
ghi / g_blend / irradiance 相关字段
temperature 相关字段
solar_elevation / solar_altitude
clear_sky_ghi
clear_sky_index
scene_v151 或现有 scene 字段
site_zero_ratio
site_positive_ratio
site_train_valid_positive_count
site_long_term_bias
latitude
longitude
```

要求：

- 如果某个特征不存在，脚本记录 warning，但不能中断。
- 最终实际使用的特征列表写入：

```text
output/pv_pipeline/round63/round63_feature_list.json
```

---

## 六、候选选择与安全回退

新增脚本：

```text
scripts/select_round63_residual_candidate.py
```

逻辑：

1. 在 valid 集上比较：
   - Round61 `power_pred_final`
   - `ridge_residual`
   - `hgb_residual`

2. 比较指标：

```text
site_mean_nrmse_6_19
city_nrmse_6_19
city_nrmse_10_14
hourly_site_mean_nrmse
hourly_city_nrmse
bad_site_count_gt_1pp
bias_6_19
bias_10_14
```

3. valid 选择规则：

优先级：

```text
第一优先：bad_site_count_gt_1pp = 0
第二优先：site_mean_nrmse_6_19 不高于 Round61 + 0.10pp
第三优先：city_nrmse_6_19 不高于 Round61 + 0.10pp
第四优先：city_nrmse_10_14 不高于 Round61
第五优先：7点、17点 bias_abs 有改善
```

4. 如果没有候选满足安全门控：

```text
selected_candidate = round61_baseline
```

5. 输出：

```text
output/pv_pipeline/round63/round63_valid_candidate_compare.csv
output/pv_pipeline/round63/round63_selected_candidate.json
```

---

## 七、test 集最终评估

新增脚本：

```text
scripts/evaluate_round63_candidate_on_test.py
```

要求：

- test 集只评估，不参与选择。
- 同时输出 Round61 与 Round63 selected candidate 的对比。

输出：

```text
output/pv_pipeline/round63/round63_test_overall_compare.csv
output/pv_pipeline/round63/round63_test_hourly_compare.csv
output/pv_pipeline/round63/round63_test_site_compare.csv
docs/Round63_离线分场景残差模型实验报告.md
```

报告必须包含：

| 内容 | 要求 |
|---|---|
| 是否通过 Round61 基线复核 | PASS / FAIL |
| valid 选择了哪个候选 | ridge / hgb / round61 |
| test 是否优于 Round61 | 是 / 否 |
| 是否建议替换正式结果 | 是 / 否 |
| 如果不替换 | 明确说明继续保留 Round61 |

---

## 八、是否允许替换正式结果

本轮默认**不替换**正式结果。

只有同时满足以下条件，才允许生成建议替换文件：

```text
site_mean_nrmse_6_19 优于 Round61
city_nrmse_6_19 不劣于 Round61 + 0.10pp
city_nrmse_10_14 不劣于 Round61
bad_site_count_gt_1pp = 0
10-14 点站点平均 NRMSE 有下降
```

即使满足，也只输出：

```text
output/pv_pipeline/round63/distributed_predictions_final_candidate_round63.pkl
```

不要覆盖：

```text
distributed_predictions_final_full.pkl
distributed_predictions_final_eval.pkl
```

---

## 九、执行命令

按顺序执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/verify_round61_baseline.py

python scripts/train_round63_scene_residual_models.py \
  --config configs/round63_residual_experiment.yaml

python scripts/select_round63_residual_candidate.py \
  --config configs/round63_residual_experiment.yaml

python scripts/evaluate_round63_candidate_on_test.py \
  --config configs/round63_residual_experiment.yaml
```

如果项目已有统一入口，也可以增加：

```bash
python scripts/run_full_pipeline.py --mode round63-experiment
```

但不要删除上面的单步脚本，方便定位问题。

---

## 十、提交 GitHub

如果所有脚本和报告生成正常，执行：

```bash
git status
git add configs/round63_residual_experiment.yaml
git add scripts/verify_round61_baseline.py
git add scripts/train_round63_scene_residual_models.py
git add scripts/select_round63_residual_candidate.py
git add scripts/evaluate_round63_candidate_on_test.py
git add docs/Round63_离线分场景残差模型实验报告.md
git add docs/Round63_Round61基线复核报告.md
git add output/pv_pipeline/round63/*.csv
git add output/pv_pipeline/round63/*.json

git commit -m "experiment: add round63 scene residual candidate evaluation"
git push origin HEAD
```

注意：

- 不要 `git add output/pv_pipeline/round63/*.pkl`。
- 不要提交模型二进制文件。
- 如果确实需要保存模型文件，只保存到服务器本地，不进 Git。

---

## 十一、验收标准

本轮通过标准：

1. `verify_round61_baseline.py` 通过。
2. Round61 tag、commit、manifest、SHA256 可追溯。
3. Round63 至少生成 2 个候选：`ridge_residual`、`hgb_residual`。
4. valid 选择逻辑不读取 test。
5. test 报告同时给出 Round61 与候选对比。
6. 如果候选不如 Round61，最终明确保留 Round61。
7. 不覆盖当前正式预测结果。

---

## 十二、你需要回传的文件

执行完成后，把以下文件发回来：

```text
docs/Round63_Round61基线复核报告.md
docs/Round63_离线分场景残差模型实验报告.md
output/pv_pipeline/round63/round63_valid_candidate_compare.csv
output/pv_pipeline/round63/round63_test_overall_compare.csv
output/pv_pipeline/round63/round63_test_hourly_compare.csv
output/pv_pipeline/round63/round63_test_site_compare.csv
```

我会根据这些文件判断：

- Round61 是否真的已经保存稳；
- 分场景残差模型是否有真实提升；
- 是否值得进入下一步替换正式结果；
- 如果没有提升，瓶颈是在模型结构、输入特征、数据质量还是站点差异。

