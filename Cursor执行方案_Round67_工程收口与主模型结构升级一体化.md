# Cursor执行方案 Round67：工程收口与主模型结构升级一体化

## 一、目标

Round66 已经把 Round64 safe 正式升级为当前 final，并确认正式产物不含 future。本轮不要继续围绕可视化或单个报告做小修，而是一次性完成两类工作：

1. **工程收口**  
   修复 Round66 报告与 posttrain validation 中的遗留矛盾，更新 manifest SHA256，建立当前正式版本的可复现基线。

2. **主模型结构升级**  
   不再只依赖后处理残差修正，而是训练新的主模型候选。重点解决：
   - 10-14 点高估；
   - 单站点 NRMSE 偏高；
   - 早晚启动/衰减时段误差；
   - 高零值、低样本、异常站点对模型的影响。

本轮的原则是：**先把当前 Round64 final 固定为可回退基线，再训练新模型候选；候选如果不如当前 final，自动保留当前 final。**

---

## 二、硬性约束

必须遵守：

- 不使用 test 集调参。
- 不修改现有指标公式。
- 不包含 future 数据。
- 不直接覆盖当前 Round64 final，除非候选通过完整 valid 门控和最终审计。
- 新模型先输出 candidate pkl。
- 当前正式基线是 Round64 final，不再用 Round61 作为主比较对象。
- 若新模型不优于 Round64 final，最终决策必须是 `keep_round64_final`。

---

## 三、第一部分：Round66 工程收口

### 3.1 修正 Round66 报告矛盾

文件：

```text
docs/Round66_正式升级Round64并排除future数据报告.md
```

修正两处矛盾：

1. 报告前文写：

```text
SHA256 manifest 更新：未执行
```

但输出文件清单写：

```text
manifest.json（已更新）
```

必须统一。若当前确实未更新 SHA256，则改为：

```text
manifest.json 已更新基础字段，但 SHA256 完整性字段尚未重算。
```

2. posttrain validation 的 3 个 FAIL 要分成：

```text
可接受口径差异：C2、C13
需要修复：C16 manifest SHA256 未更新
```

不要再写“3 个 FAIL 均非阻塞性”。C16 要在本轮修复。

---

### 3.2 新增 manifest 重算脚本

新建：

```text
scripts/update_final_manifest_hashes.py
```

功能：

1. 读取：

```text
output/pv_pipeline/manifest.json
```

2. 对正式关键产物重算 SHA256：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl
output/pv_pipeline/interactive_dashboard/metadata.json
output/pv_pipeline/metrics/hourly_relative_error_consistent.csv
output/pv_pipeline/metrics/site_metrics_consistent.csv
```

如果某些 metrics 文件名不同，请自动搜索：

```text
output/pv_pipeline/metrics/*hour*.csv
output/pv_pipeline/metrics/*site*.csv
```

但最终报告中必须写清楚实际纳入 manifest 的文件。

3. 写入 manifest：

```json
{
  "final_round": "Round64",
  "prediction_column": "power_pred_final",
  "exclude_future": true,
  "hashes_updated_at": "...",
  "artifacts": [
    {
      "path": "...",
      "sha256": "...",
      "bytes": 123,
      "exists": true
    }
  ]
}
```

4. 输出：

```text
output/pv_pipeline/round67/round67_manifest_hash_update.csv
output/pv_pipeline/round67/round67_manifest_hash_update.json
```

---

### 3.3 修正 posttrain validation 口径

修改：

```text
scripts/posttrain_validation.py
```

或当前实际使用的：

```text
scripts/posttrain_validation_round36.py
```

要求：

1. C2：允许 eval pkl 只包含 valid/test，不再作为 FAIL。改为 WARN 或 PASS_WITH_NOTE。
2. C13：site_series JSON 不进 Git，若 `.gitignore` 明确忽略，则改为 PASS_WITH_NOTE。
3. C16：manifest SHA256 必须真实校验。若未更新或不一致，仍为 FAIL。

执行后期望：

```text
FAIL = 0
WARN 可以存在，但要有解释。
```

---

### 3.4 工程收口执行命令

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

mkdir -p output/pv_pipeline/round67

python scripts/update_final_manifest_hashes.py

python scripts/posttrain_validation.py
```

如果实际入口仍是：

```bash
python scripts/posttrain_validation_round36.py
```

则同步执行，并在报告里说明当前正式使用哪个 validation 脚本。

---

## 四、第二部分：主模型结构升级

### 4.1 本轮不再只做后处理

Round64 的提升来自残差融合，属于后处理层收益。本轮要新增主模型候选：

```text
Round67 scene-group main model
```

核心变化：

1. 训练目标仍为容量归一化功率：

```text
y = power_mw / capacity_mw
```

2. 按“时段 + 站点类型 + 天气场景”建模，而不是一个统一模型吃所有样本。

3. 对 10-14 点高估问题，在训练层面处理，而不是事后校准。

4. 输出候选列：

```text
power_pred_round67_scene_main
power_pred_round67_scene_blend
```

不直接覆盖 `power_pred_final`。

---

### 4.2 新建配置文件

新建：

```text
configs/round67_scene_main_model.yaml
```

建议内容：

```yaml
baseline_col: power_pred_final
target_col: power_mw
capacity_col: capacity_mw
split_col: split
site_col: site_id
time_col: datetime

exclude_future: true
eval_hours: [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]

time_blocks:
  dawn: [6, 7, 8]
  morning: [9, 10]
  noon: [11, 12, 13, 14]
  afternoon: [15, 16]
  dusk: [17, 18, 19]

site_groups:
  low_capacity:
    max_capacity_mw: 3
  mid_capacity:
    min_capacity_mw: 3
    max_capacity_mw: 10
  high_capacity:
    min_capacity_mw: 10
  high_zero:
    test_6_19_zero_ratio_min: 0.3
  stable:
    test_6_19_zero_ratio_max: 0.2

sample_weight:
  base: 1.0
  noon_hours_weight: 1.8
  dawn_dusk_weight: 1.4
  high_error_site_weight: 1.5
  high_zero_site_weight: 0.7

models:
  hgb:
    enabled: true
  lgb:
    enabled: true
  ridge:
    enabled: true

valid_guard:
  site_mean_nrmse_improve_min_pp: 0.05
  city_nrmse_max_worse_pp: 0.05
  city_10_14_must_not_worse: true
  bad_site_gt_1pp_max: 0
  pred_actual_extreme_max_count_increase: 0
```

---

## 五、新增主模型训练数据构造

新建：

```text
scripts/build_round67_training_table.py
```

功能：

1. 读取当前正式 final：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
```

2. 排除 future：

```python
df = df[df["split"] != "future"].copy()
```

3. 保留 6-19 点用于建模和评估。

4. 构造目标：

```text
y_norm = power_mw / capacity_mw
```

5. 构造特征，不存在则跳过并记录：

基础特征：

```text
hour
month
dayofyear
capacity_mw
latitude
longitude
power_pred_final
power_pred_final / capacity_mw
```

辐照/气象特征：

```text
g_blend_pred
ghi
clear_sky_ghi
clear_sky_index
temperature
wind_speed
humidity
solar_elevation
solar_azimuth
```

站点历史特征：

```text
site_train_positive_count
site_valid_positive_count
site_6_19_zero_ratio
site_pr_median
site_long_term_bias
site_capacity_bucket
site_quality_score
```

场景特征：

```text
time_block
site_group
is_noon
is_dawn
is_dusk
is_high_zero_site
```

6. 输出：

```text
output/pv_pipeline/round67/round67_training_table.parquet
output/pv_pipeline/round67/round67_feature_inventory.csv
output/pv_pipeline/round67/round67_training_data_summary.csv
```

注意：parquet 不提交 Git。

---

## 六、训练 Round67 主模型候选

新建：

```text
scripts/train_round67_scene_main_models.py
```

### 6.1 候选模型

至少训练以下候选：

| 候选 | 说明 |
|---|---|
| `round64_final` | 当前正式基线 |
| `ridge_scene_main` | 线性稳健模型 |
| `hgb_scene_main` | sklearn 非线性模型 |
| `lgb_scene_main` | LightGBM 非线性模型，如果依赖可用 |
| `scene_blend` | valid 上按场景融合 baseline 与最佳主模型 |

### 6.2 分块建模方式

不要只训练一个全局模型。按以下粒度训练：

```text
time_block: dawn / morning / noon / afternoon / dusk
```

每个 time_block 单独训练模型。

如果某个 time_block 样本不足，则回退到全局模型。

### 6.3 样本权重

构造 sample_weight：

```text
基础权重 = 1
10-14 点 = 1.8
6-8、17-19 点 = 1.4
高误差站点 = 1.5
高 0 值站点 = 0.7
```

权重上限建议：

```text
max_weight = 3.0
```

权重下限：

```text
min_weight = 0.3
```

### 6.4 预测物理裁剪

所有候选输出必须裁剪：

```text
power_pred = clip(y_pred_norm * capacity_mw, 0, capacity_mw)
```

并在低太阳高度或夜间不强行置零，因为目前只评估 6-19 点，且早晚有真实发电。

### 6.5 输出

```text
output/pv_pipeline/round67/round67_model_training_summary.csv
output/pv_pipeline/round67/round67_candidates.pkl
output/pv_pipeline/round67/round67_model_feature_importance.csv
output/pv_pipeline/round67/round67_model_files/
```

模型文件不提交 Git。

---

## 七、valid 选择与安全回退

新建：

```text
scripts/select_round67_scene_main_candidate.py
```

### 7.1 valid 指标

对每个候选计算：

```text
site_mean_nrmse_6_19
city_nrmse_6_19
site_mean_nrmse_10_14
city_nrmse_10_14
bias_6_19
bias_10_14
bad_site_gt_1pp
hourly_site_mean_nrmse
hourly_city_nrmse
pred_actual_extreme_count
```

### 7.2 选择规则

候选必须同时满足：

```text
bad_site_gt_1pp == 0
city_nrmse_6_19 <= Round64_final + 0.05pp
city_nrmse_10_14 <= Round64_final
site_mean_nrmse_6_19 <= Round64_final - 0.05pp
pred_actual_extreme_count 不增加
```

如果没有候选满足：

```text
selected = power_pred_final
decision = keep_round64_final
```

如果有候选满足：

```text
selected = valid 最优候选
decision = adopt_round67_candidate_for_test_review
```

输出：

```text
output/pv_pipeline/round67/round67_valid_candidate_compare.csv
output/pv_pipeline/round67/round67_selected_candidate.json
```

---

## 八、test 最终评估

新建：

```text
scripts/evaluate_round67_candidate_on_test.py
```

输出：

```text
output/pv_pipeline/round67/round67_test_overall_compare.csv
output/pv_pipeline/round67/round67_test_hourly_compare.csv
output/pv_pipeline/round67/round67_test_site_compare.csv
output/pv_pipeline/round67/round67_high_error_site_compare.csv
docs/Round67_工程收口与主模型结构升级报告.md
```

报告必须回答：

1. Round66 工程收口是否完成？
2. manifest SHA256 是否已更新？
3. posttrain validation 是否还有 FAIL？
4. Round67 新主模型是否优于 Round64 final？
5. 10-14 点是否改善？
6. 单站点 NRMSE 是否改善？
7. 是否建议采用 Round67？
8. 如果不采用，瓶颈是什么？

---

## 九、统一入口

修改：

```text
scripts/run_full_pipeline.py
```

新增模式：

```bash
python scripts/run_full_pipeline.py --mode round67-model-upgrade
```

该模式按顺序执行：

```text
update_final_manifest_hashes
posttrain_validation
build_round67_training_table
train_round67_scene_main_models
select_round67_scene_main_candidate
evaluate_round67_candidate_on_test
```

默认不 promote，不覆盖正式 final。

---

## 十、执行命令

优先执行统一入口：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/run_full_pipeline.py --mode round67-model-upgrade
```

如果统一入口尚未接好，则按单步执行：

```bash
python scripts/update_final_manifest_hashes.py

python scripts/posttrain_validation.py

python scripts/build_round67_training_table.py \
  --config configs/round67_scene_main_model.yaml

python scripts/train_round67_scene_main_models.py \
  --config configs/round67_scene_main_model.yaml

python scripts/select_round67_scene_main_candidate.py \
  --config configs/round67_scene_main_model.yaml

python scripts/evaluate_round67_candidate_on_test.py \
  --config configs/round67_scene_main_model.yaml
```

---

## 十一、Git 提交

如果执行正常，提交代码、配置、轻量报告：

```bash
git status

git add configs/round67_scene_main_model.yaml
git add scripts/update_final_manifest_hashes.py
git add scripts/build_round67_training_table.py
git add scripts/train_round67_scene_main_models.py
git add scripts/select_round67_scene_main_candidate.py
git add scripts/evaluate_round67_candidate_on_test.py
git add scripts/run_full_pipeline.py
git add scripts/posttrain_validation.py
git add docs/Round66_正式升级Round64并排除future数据报告.md
git add docs/Round67_工程收口与主模型结构升级报告.md
git add output/pv_pipeline/round67/*.csv
git add output/pv_pipeline/round67/*.json

git commit -m "experiment: add round67 scene main model upgrade"
git push origin HEAD
```

不要提交：

```text
*.pkl
*.parquet
*.joblib
output/pv_pipeline/round67/round67_model_files/
```

---

## 十二、验收标准

Round67 通过标准：

1. Round66 报告矛盾已修复。
2. manifest SHA256 已重算。
3. posttrain validation 无真实 FAIL。
4. Round67 至少训练 3 类候选：ridge、hgb、lgb 或可用替代模型。
5. valid 选择不读取 test。
6. test 只做最终评估。
7. 若 Round67 不如 Round64，自动保留 Round64 final。
8. 若 Round67 优于 Round64，只输出采用建议，不直接覆盖正式 final。
9. 报告必须说明模型结构升级是否真的带来提升，而不是只列数据。

---

## 十三、执行完成后发回

请打包发回：

```text
docs/Round67_工程收口与主模型结构升级报告.md
output/pv_pipeline/round67/round67_manifest_hash_update.csv
output/pv_pipeline/round67/round67_training_data_summary.csv
output/pv_pipeline/round67/round67_feature_inventory.csv
output/pv_pipeline/round67/round67_model_training_summary.csv
output/pv_pipeline/round67/round67_valid_candidate_compare.csv
output/pv_pipeline/round67/round67_selected_candidate.json
output/pv_pipeline/round67/round67_test_overall_compare.csv
output/pv_pipeline/round67/round67_test_hourly_compare.csv
output/pv_pipeline/round67/round67_test_site_compare.csv
output/pv_pipeline/round67/round67_high_error_site_compare.csv
```

我会重点判断：

- 主模型结构升级是否真正优于 Round64 final；
- 10-14 点高估是否缓解；
- 单站点 NRMSE 是否下降；
- 是否值得进入 Round68 正式采用；
- 如果仍无明显提升，是否已经接近现有数据条件下的模型瓶颈。

