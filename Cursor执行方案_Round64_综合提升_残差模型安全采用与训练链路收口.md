# Cursor执行方案 Round64：综合提升-残差模型安全采用与训练链路收口

## 一、目标

本轮不要只做单点修复，而是一次性完成以下 6 件事：

1. 修正 Round63 报告中的单位和表述错误。
2. 在 Round63 `lgb_residual` 基础上增加“站点级 + 小时级 + 场景级安全回退”。
3. 只用 valid 集决定哪些站点/小时/场景允许采用残差模型，test 只做最终评估。
4. 如果候选有效，则生成 Round64 candidate；如果无效，自动保留 Round61。
5. 将评估、可视化数据导出、报告生成接入统一流程，避免后续页面仍显示旧数据。
6. 清理本轮生成的临时残留，形成可复现、可回退、可审计的结果。

本轮的核心思路是：

```text
Round61 稳定预测结果
  -> Round63 lgb_residual 候选
  -> valid 集判断哪些部分真的变好
  -> 对变差部分自动回退 Round61
  -> 形成 Round64 安全融合候选
  -> test 集最终评估
```

---

## 二、执行前原则

必须遵守：

- 不改指标公式。
- 不用 test 集调参。
- 不覆盖 Round61 稳定基线。
- 不直接覆盖正式 `power_pred_final`，先输出候选列。
- 如果 Round64 不如 Round61，最终仍保留 Round61。
- 如果 Round64 只在城市指标变好但站点明显变差，也不能采用。

---

## 三、先修正 Round63 报告问题

### 3.1 修正单位错误

文件：

```text
docs/Round63_离线分场景残差模型实验报告.md
```

需要修正：

```text
RMSE (MW) 表中不能写成百分号。
MAE (MW) 表中不能写成百分号。
```

例如：

```text
RMSE (MW): 0.9321
MAE (MW): 0.4478
```

不要写：

```text
0.9321%
0.4478%
```

### 3.2 修正退化站点数量描述

报告里如果写了：

```text
ridge_residual 6站点退化
```

需要核对并改成真实值：

```text
valid 集 ridge_residual 18 个站点退化；
test 集 ridge_residual 12 个站点退化。
```

### 3.3 结论表述改为更准确

不要写“放弃分场景残差模型方向”。

改为：

```text
Round63 不能直接采用，但 lgb_residual 在 test 集上显示出一定提升潜力。
下一步应增加 valid 驱动的站点级、小时级、场景级回退保护，验证能否保留整体提升，同时避免局部站点退化。
```

---

## 四、实现 Round64 安全融合候选

### 4.1 新建配置文件

新建：

```text
configs/round64_safe_residual_blend.yaml
```

建议内容：

```yaml
baseline_col: power_pred_final
candidate_col: power_pred_lgb_residual
output_col: power_pred_round64_safe

split_col: split
target_col: power_mw
capacity_col: capacity_mw
site_col: site_id
time_col: datetime

eval_hours: [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]

scene_groups:
  dawn: [6, 7, 8]
  day: [9, 10, 11, 12, 13, 14, 15, 16]
  dusk: [17, 18, 19]
  noon_focus: [10, 11, 12, 13, 14]

guards:
  site_max_nrmse_increase_pp: 0.30
  site_hard_nrmse_increase_pp: 1.00
  hour_city_max_nrmse_increase_pp: 0.05
  hour_site_mean_max_nrmse_increase_pp: 0.10
  scene_site_mean_max_nrmse_increase_pp: 0.10
  scene_city_max_nrmse_increase_pp: 0.05
  require_bad_site_count_gt_1pp_zero: true

blend:
  allowed_weights: [0.25, 0.50, 0.75, 1.00]
  default_weight: 1.00
  fallback_weight: 0.00
```

---

## 五、新增核心脚本：valid 驱动安全融合

新建：

```text
scripts/build_round64_safe_residual_blend.py
```

### 5.1 输入

读取 Round63 候选结果，必须包含：

```text
power_mw
capacity_mw
power_pred_final
power_pred_lgb_residual
split
site_id
datetime/hour
```

如果 `power_pred_lgb_residual` 不存在，先自动调用：

```text
scripts/train_round63_scene_residual_models.py
```

但必须在日志里写清楚。

### 5.2 候选融合公式

不要简单二选一，要支持权重融合：

```text
P_round64(w) = P_round61 + w * (P_lgb_residual - P_round61)
```

其中：

```text
w = 0.00 表示完全回退 Round61
w = 1.00 表示完全采用 lgb_residual
```

对每个站点、每个场景，在 valid 集上从：

```text
[0.00, 0.25, 0.50, 0.75, 1.00]
```

选择最安全的权重。

### 5.3 valid 选择逻辑

按优先级选择：

1. 该站点该场景 NRMSE 不能比 Round61 高超过 `0.30pp`。
2. 该站点全时段 NRMSE 不能比 Round61 高超过 `1.00pp`。
3. 该小时城市 NRMSE 不能比 Round61 高超过 `0.05pp`。
4. 优先选择能降低 `site_mean_nrmse_6_19` 的权重。
5. 如果多个权重都满足，选择更保守的较小权重。

### 5.4 输出

输出：

```text
output/pv_pipeline/round64/round64_site_scene_weights.csv
output/pv_pipeline/round64/round64_valid_weight_search.csv
output/pv_pipeline/round64/round64_candidates.pkl
```

其中 `round64_site_scene_weights.csv` 至少包含：

| site_id | scene | selected_weight | valid_nrmse_round61 | valid_nrmse_lgb | valid_nrmse_round64 | reason |
|---|---:|---:|---:|---:|---:|---|

---

## 六、Round64 test 评估脚本

新建：

```text
scripts/evaluate_round64_safe_blend.py
```

输出：

```text
output/pv_pipeline/round64/round64_test_overall_compare.csv
output/pv_pipeline/round64/round64_test_hourly_compare.csv
output/pv_pipeline/round64/round64_test_site_compare.csv
output/pv_pipeline/round64/round64_guard_summary.json
docs/Round64_安全残差融合与训练链路收口报告.md
```

### 6.1 总体评估必须包含

| 指标 | Round61 | Round63 lgb | Round64 safe | 结论 |
|---|---:|---:|---:|---|
| site_mean_nrmse_6_19 (%) |  |  |  |  |
| city_nrmse_6_19 (%) |  |  |  |  |
| city_nrmse_10_14 (%) |  |  |  |  |
| sm_nrmse_10_14 (%) |  |  |  |  |
| bias_6_19 (%) |  |  |  |  |
| bias_10_14 (%) |  |  |  |  |
| MAE (MW) |  |  |  |  |
| RMSE (MW) |  |  |  |  |
| 变差 > +1pp 站点数 |  |  |  |  |

### 6.2 逐小时评估必须包含

```text
hour
sample_count
round61_site_mean_nrmse
round64_site_mean_nrmse
delta_site_mean_nrmse
round61_city_nrmse
round64_city_nrmse
delta_city_nrmse
```

重点关注：

```text
7点、10-14点、17点
```

### 6.3 站点评估必须包含

```text
site_id
site_name
capacity_mw
round61_nrmse
round64_nrmse
delta_nrmse
round61_pred_actual
round64_pred_actual
selected_weight_summary
```

---

## 七、是否采用 Round64 的自动判定

新增：

```text
scripts/select_round64_final_decision.py
```

判定规则：

只有同时满足以下条件，才建议采用 Round64：

```text
site_mean_nrmse_6_19 <= Round61 - 0.05pp
city_nrmse_6_19 <= Round61 + 0.05pp
city_nrmse_10_14 <= Round61
bad_site_count_gt_1pp == 0
10-14 点站点平均 NRMSE 不高于 Round61
```

如果不满足：

```text
decision = keep_round61
```

如果满足：

```text
decision = adopt_round64_candidate
```

输出：

```text
output/pv_pipeline/round64/round64_final_decision.json
```

注意：即使 decision 是 `adopt_round64_candidate`，本轮也先不要覆盖正式 pkl，只写建议。

---

## 八、接入训练主流程和可视化刷新

### 8.1 更新统一入口

如果项目已有：

```text
scripts/run_full_pipeline.py
```

加入可选模式：

```bash
python scripts/run_full_pipeline.py --mode round64-experiment
```

该模式执行：

```text
verify_round61_baseline
train_round63_scene_residual_models（如果候选不存在）
build_round64_safe_residual_blend
evaluate_round64_safe_blend
select_round64_final_decision
export_interactive_dashboard_data（只在采用候选时导出候选页面，否则继续导出 Round61）
posttrain_validation
```

### 8.2 可视化刷新策略

如果 `round64_final_decision.json` 为：

```text
keep_round61
```

则可视化继续使用 Round61 当前正式数据。

如果为：

```text
adopt_round64_candidate
```

则导出：

```text
output/pv_pipeline/interactive_dashboard_round64_candidate/
```

不要直接覆盖当前正式可视化目录，防止展示结果被误认为已经正式采用。

---

## 九、清理过期和临时文件

新增：

```text
scripts/cleanup_round_experiment_artifacts.py
```

只清理明确的临时文件，不清理正式报告和 baseline。

建议移动到：

```text
archive/round_experiments/
```

清理对象：

```text
output/pv_pipeline/round59/tmp*
output/pv_pipeline/round60/tmp*
output/pv_pipeline/round63/*.tmp
docs/*草稿*
docs/*临时*
```

严禁删除：

```text
output/pv_pipeline/baselines/round61/
docs/Round61_稳定基线说明.md
docs/Round63_离线分场景残差模型实验报告.md
docs/Round64_安全残差融合与训练链路收口报告.md
```

清理前必须输出 dry-run 清单：

```bash
python scripts/cleanup_round_experiment_artifacts.py --dry-run
```

确认无误后再执行：

```bash
python scripts/cleanup_round_experiment_artifacts.py --apply
```

---

## 十、执行命令

按顺序执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/verify_round61_baseline.py

python scripts/build_round64_safe_residual_blend.py \
  --config configs/round64_safe_residual_blend.yaml

python scripts/evaluate_round64_safe_blend.py \
  --config configs/round64_safe_residual_blend.yaml

python scripts/select_round64_final_decision.py \
  --config configs/round64_safe_residual_blend.yaml

python scripts/posttrain_validation_round36.py

python scripts/cleanup_round_experiment_artifacts.py --dry-run
```

如果统一入口已接好，再执行：

```bash
python scripts/run_full_pipeline.py --mode round64-experiment
```

---

## 十一、Git 提交

如果执行正常，提交代码和轻量结果：

```bash
git status

git add configs/round64_safe_residual_blend.yaml
git add scripts/build_round64_safe_residual_blend.py
git add scripts/evaluate_round64_safe_blend.py
git add scripts/select_round64_final_decision.py
git add scripts/cleanup_round_experiment_artifacts.py
git add scripts/run_full_pipeline.py
git add docs/Round63_离线分场景残差模型实验报告.md
git add docs/Round64_安全残差融合与训练链路收口报告.md
git add output/pv_pipeline/round64/*.csv
git add output/pv_pipeline/round64/*.json

git commit -m "experiment: add round64 safe residual blend and guards"
git push origin HEAD
```

不要提交：

```text
*.pkl
*.joblib
*.parquet
*.npy
*.npz
```

---

## 十二、验收标准

本轮不是只看有没有跑通，而是看是否完成完整闭环：

1. Round63 报告单位和退化站点数量已修正。
2. Round64 生成站点-场景权重表。
3. Round64 同时输出 valid 权重搜索、test 总体、逐小时、逐站点对比。
4. 有自动采用/不采用决策。
5. 如果不采用，当前正式结果仍是 Round61。
6. 如果建议采用，必须有候选可视化目录，不能直接覆盖正式目录。
7. 清理脚本先 dry-run，不能误删基线产物。
8. GitHub 提交不包含大型模型和预测 pkl。

---

## 十三、执行完成后发回

请把以下文件打包发回：

```text
docs/Round64_安全残差融合与训练链路收口报告.md
output/pv_pipeline/round64/round64_site_scene_weights.csv
output/pv_pipeline/round64/round64_valid_weight_search.csv
output/pv_pipeline/round64/round64_test_overall_compare.csv
output/pv_pipeline/round64/round64_test_hourly_compare.csv
output/pv_pipeline/round64/round64_test_site_compare.csv
output/pv_pipeline/round64/round64_final_decision.json
output/pv_pipeline/round64/round64_guard_summary.json
```

我会根据这些文件判断：

- Round64 是否值得正式采用；
- lgb_residual 的提升是否能被安全保留下来；
- 站点退化是否被有效控制；
- 下一步是否需要真的调整主模型结构，而不是继续做残差融合。

