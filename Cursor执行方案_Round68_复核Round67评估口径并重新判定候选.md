# Cursor执行方案 Round68：复核 Round67 评估口径并重新判定候选

## 一、目标

Round67 报告中出现明显矛盾：

1. `lgb` 的 valid `site_mean_nrmse` 明显低于 `round64_final`，但报告却判定 `lgb` 因 `sm` 差于门控失败。
2. Round67 的 `city_nrmse` 数量级从 Round66 的 `3.8104%` 变成 `0.2326`，疑似单位或公式口径错误。
3. valid 表缺少 `city_nrmse_10_14`、`bad_sites_gt_1pp` 等关键门控项。
4. bias 判断只看正负方向，没有看绝对偏差。

本轮目标不是继续训练新模型，而是先把 Round67 的评估和选择逻辑彻底复核清楚，再重新判断：

```text
Round67 lgb/hgb/ridge 是否真的失败？
是否存在可安全采用的 Round67 candidate？
是否需要做 Round67-lgb 的安全融合？
```

---

## 二、硬性原则

- 不改指标公式的定义，只修正实现口径。
- 不用 test 集调参。
- 不训练新模型，优先复用 Round67 已生成候选。
- 不覆盖当前正式 Round64 final。
- 所有 NRMSE 输出统一为百分比 `%`。
- 所有 valid 选择必须补齐完整门控项。

---

## 三、统一指标计算函数

### 3.1 新建公共评估模块

新建：

```text
pv_forecasting/evaluation/metrics_consistent.py
```

如果项目没有 `pv_forecasting/evaluation/`，则新建目录。

必须实现以下函数：

```python
def filter_eval_frame(
    df,
    split=None,
    hours=range(6, 20),
    exclude_future=True,
    require_positive_capacity=True,
):
    ...

def site_nrmse_percent(
    df,
    pred_col,
    actual_col="power_mw",
    capacity_col="capacity_mw",
    site_col="site_id",
):
    ...

def site_mean_nrmse_percent(...):
    ...

def city_nrmse_percent(
    df,
    pred_col,
    actual_col="power_mw",
    capacity_col="capacity_mw",
    time_col="datetime",
):
    ...

def city_bias_percent(...):
    ...

def pred_actual_ratio(...):
    ...

def evaluate_prediction_set(
    df,
    pred_col,
    split,
    hours,
    baseline_site_metrics=None,
):
    ...
```

### 3.2 统一公式

所有指标按以下公式计算。

#### 单站点 NRMSE

对每个站点：

```text
RMSE_site = sqrt(mean((P_pred - P_true)^2))

NRMSE_site(%) = RMSE_site / capacity_mw_site × 100%
```

其中 `capacity_mw_site` 使用该站点容量，不能使用 `max-min`。

#### 站点平均 NRMSE

```text
site_mean_NRMSE(%) = mean(NRMSE_site(%))
```

只对有效站点取平均。

#### 城市 NRMSE

先按同一时刻聚合全市：

```text
P_city_true(t) = sum_i P_true_i(t)
P_city_pred(t) = sum_i P_pred_i(t)
```

再计算：

```text
RMSE_city = sqrt(mean((P_city_pred(t) - P_city_true(t))^2))

city_NRMSE(%) = RMSE_city / capacity_sum_mw × 100%
```

其中：

```text
capacity_sum_mw = sum(参与评估站点 capacity_mw)
```

注意：最终输出必须是百分比。不能出现 `0.2326` 这种无单位小数，除非明确写成 `0.2326%`，但要核查是否合理。

#### BIAS

```text
BIAS(%) = (sum(P_pred) - sum(P_true)) / sum(P_true) × 100%
```

比较时应同时看：

```text
bias
abs_bias
```

不能只因为 `+8%` 变成 `-2%` 就说改善，必须看绝对偏差是否变小。

---

## 四、新增 Round67 口径复核脚本

新建：

```text
scripts/recompute_round67_metrics_consistent.py
```

### 4.1 输入

读取：

```text
output/pv_pipeline/round67/round67_candidates.pkl
```

若文件不存在，则从 Round67 报告中确认实际候选文件名，或重新生成候选但不要重新训练。

候选列至少包括：

```text
power_pred_final                  # 当前 Round64 final
power_pred_round67_ridge
power_pred_round67_hgb
power_pred_round67_lgb
```

如果列名不同，自动从 pkl 中搜索包含：

```text
ridge
hgb
lgb
round67
```

的预测列，并写入日志。

### 4.2 输出

重新计算 valid 和 test：

```text
output/pv_pipeline/round68/round67_valid_metrics_recomputed.csv
output/pv_pipeline/round68/round67_test_metrics_recomputed.csv
output/pv_pipeline/round68/round67_valid_hourly_recomputed.csv
output/pv_pipeline/round68/round67_test_hourly_recomputed.csv
output/pv_pipeline/round68/round67_valid_site_recomputed.csv
output/pv_pipeline/round68/round67_test_site_recomputed.csv
```

每个总体指标表必须包含：

```text
candidate
pred_col
site_mean_nrmse_6_19_pct
city_nrmse_6_19_pct
site_mean_nrmse_10_14_pct
city_nrmse_10_14_pct
bias_6_19_pct
abs_bias_6_19_pct
bias_10_14_pct
abs_bias_10_14_pct
mae_mw
rmse_mw
bad_site_gt_1pp_count
bad_site_gt_0_5pp_count
pred_actual_extreme_count
```

---

## 五、重新实现 Round67 valid 选择

新建：

```text
scripts/select_round67_candidate_consistent.py
```

### 5.1 比较基线

基线固定为当前正式结果：

```text
power_pred_final  # Round64 final
```

### 5.2 valid 门控规则

候选必须同时满足：

```text
bad_site_gt_1pp_count == 0
city_nrmse_6_19_pct <= baseline_city_nrmse_6_19_pct + 0.05
city_nrmse_10_14_pct <= baseline_city_nrmse_10_14_pct
site_mean_nrmse_6_19_pct <= baseline_site_mean_nrmse_6_19_pct - 0.05
pred_actual_extreme_count <= baseline_pred_actual_extreme_count
abs_bias_6_19_pct <= baseline_abs_bias_6_19_pct + 0.5
```

注意：

- `+0.05` 是百分点，不是比例。
- bias 允许小幅波动，但绝对偏差不能大幅恶化。

### 5.3 输出

```text
output/pv_pipeline/round68/round67_candidate_redecision.json
output/pv_pipeline/round68/round67_valid_gate_detail.csv
```

JSON 必须包含：

```json
{
  "baseline": "power_pred_final",
  "selected_candidate": "...",
  "decision": "keep_round64_final / adopt_round67_candidate_for_review / need_safe_blend",
  "reason": "...",
  "failed_checks": [...]
}
```

---

## 六、如果 lgb 指标好但局部风险存在，构建安全融合

如果复核后发现：

```text
lgb 的 site_mean/city 指标优于 Round64
但 bad_site 或 bias 门控未完全通过
```

则新增：

```text
scripts/build_round68_lgb_safe_blend.py
```

逻辑类似 Round64，但基线改为 Round64 final，候选改为 Round67 lgb。

融合公式：

```text
P_round68(w) = P_round64_final + w * (P_round67_lgb - P_round64_final)
```

权重：

```text
[0.00, 0.25, 0.50, 0.75, 1.00]
```

选择粒度：

```text
site_id + time_block
```

valid 上选择，test 只评估。

输出：

```text
output/pv_pipeline/round68/round68_lgb_safe_blend_candidates.pkl
output/pv_pipeline/round68/round68_lgb_safe_blend_weights.csv
output/pv_pipeline/round68/round68_lgb_safe_blend_valid_compare.csv
output/pv_pipeline/round68/round68_lgb_safe_blend_test_compare.csv
```

如果 lgb 已经完整通过 valid，则可以不做安全融合，只标记为：

```text
adopt_round67_lgb_for_review
```

但本轮仍不要覆盖正式 final。

---

## 七、修正 Round67 报告

修改：

```text
docs/Round67_工程收口与主模型结构升级报告.md
```

要求：

1. 不再使用有疑问的 `city_nrmse=0.2326` 旧表。
2. 替换为 Round68 重新计算后的百分比指标。
3. 修正“lgb 因 sm 差于门控失败”的错误判断。
4. 如果 lgb 真实失败，必须写明失败的具体检查项。
5. 如果 lgb 真实通过或需要安全融合，也必须写明。
6. 删除或弱化“主模型结构升级无效”的结论，改为基于复核结果重新判断。

---

## 八、生成 Round68 报告

新建：

```text
docs/Round68_Round67评估口径复核与候选重新判定报告.md
```

必须回答：

1. Round67 原报告哪些判断有误？
2. city NRMSE 数量级异常的原因是什么？
3. 统一口径后 valid 上各候选表现如何？
4. 统一口径后 test 上各候选表现如何？
5. lgb 是否真的优于 Round64 final？
6. lgb 是否通过 valid 安全门控？
7. 是否需要 Round68 safe blend？
8. 当前正式结果是否仍保持 Round64 final？
9. 下一步是否建议正式采用 Round67/Round68 候选？

---

## 九、统一入口

修改：

```text
scripts/run_full_pipeline.py
```

新增模式：

```bash
python scripts/run_full_pipeline.py --mode round68-recheck-round67
```

执行顺序：

```text
recompute_round67_metrics_consistent
select_round67_candidate_consistent
if needed: build_round68_lgb_safe_blend
rewrite Round67 report
write Round68 report
```

---

## 十、执行命令

优先执行：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/run_full_pipeline.py --mode round68-recheck-round67
```

如果统一入口尚未接好，则执行：

```bash
mkdir -p output/pv_pipeline/round68

python scripts/recompute_round67_metrics_consistent.py

python scripts/select_round67_candidate_consistent.py

# 仅当 select 结果为 need_safe_blend 时执行
python scripts/build_round68_lgb_safe_blend.py
```

---

## 十一、Git 提交

通过后提交：

```bash
git status

git add pv_forecasting/evaluation/metrics_consistent.py
git add scripts/recompute_round67_metrics_consistent.py
git add scripts/select_round67_candidate_consistent.py
git add scripts/build_round68_lgb_safe_blend.py
git add scripts/run_full_pipeline.py
git add docs/Round67_工程收口与主模型结构升级报告.md
git add docs/Round68_Round67评估口径复核与候选重新判定报告.md
git add output/pv_pipeline/round68/*.csv
git add output/pv_pipeline/round68/*.json

git commit -m "fix: recheck round67 metrics and candidate selection"
git push origin HEAD
```

不要提交：

```text
*.pkl
*.parquet
*.joblib
```

---

## 十二、验收标准

Round68 通过标准：

1. 所有 NRMSE 输出统一为 `%`。
2. city NRMSE 公式和 Round66/Round64 口径一致。
3. valid 表补齐所有门控项。
4. lgb 是否失败有明确、可复核原因。
5. 如果 lgb 具备潜力但局部风险存在，生成 safe blend。
6. 不覆盖当前 Round64 final。
7. Round67 报告中的错误判断已修正。
8. Round68 报告给出下一步明确建议。

---

## 十三、执行完成后发回

请发回：

```text
docs/Round68_Round67评估口径复核与候选重新判定报告.md
output/pv_pipeline/round68/round67_valid_metrics_recomputed.csv
output/pv_pipeline/round68/round67_test_metrics_recomputed.csv
output/pv_pipeline/round68/round67_valid_gate_detail.csv
output/pv_pipeline/round68/round67_candidate_redecision.json
```

如果生成了 safe blend，也请发回：

```text
output/pv_pipeline/round68/round68_lgb_safe_blend_valid_compare.csv
output/pv_pipeline/round68/round68_lgb_safe_blend_test_compare.csv
output/pv_pipeline/round68/round68_lgb_safe_blend_weights.csv
```

我会据此判断下一步是：

- 正式采用 Round67 lgb；
- 正式采用 Round68 safe blend；
- 还是继续保留 Round64 final 并转向特征工程。

