# Round64 安全残差融合与训练链路收口报告

**日期**: 2026-06-01
**分支**: experiment/model-structure-round62

---

## 1. 实验背景

Round63 raw lgb_residual 在 test 上全面改善（sm -0.34pp, city -0.18pp），但 valid 上有 2 站点退化触发安全门控。

Round64 思路：在 lgb_residual 基础上增加站点-场景级安全回退保护，只对 valid 上确认安全有效的部分采用残差融合。

---

## 2. 方法：站点-场景级安全权重融合

**融合公式**：
```
P_round64(w) = P_round61 + w * (P_lgb_residual - P_round61)
```

**权重网格**：[0.00, 0.25, 0.50, 0.75, 1.00]

**安全约束**（每站点-场景）：
- 该站点该场景 NRMSE 不能比 Round61 高超过 0.30pp
- 该站点全时段 NRMSE 不能比 Round61 高超过 1.00pp

**选择策略**：对每个 (site_id, scene) 组合，选择满足约束且最优（改善最大）的权重；无满足时默认 w=0.00（完全回退 Round61）。

---

## 3. 权重分布（valid 集搜索结果）

| 场景 | w=0.00 | w=0.25 | w=0.50 | w=0.75 | w=1.00 |
|------|---:|---:|---:|---:|---:|
| dawn | 52 | 0 | 1 | 4 | 11 |
| day | 54 | 4 | 2 | 0 | 8 |
| dusk | 53 | 0 | 2 | 0 | 13 |

大量站点 w=0.00（完全回退），说明残差模型在大量站点上不满足安全约束。完全采用 lgb_residual（w=1.00）的站点：dawn 11个, day 8个, dusk 13个。

**为什么提升不大**：Round64 不是重训主模型，而是对 Round63 lgb 残差候选做安全融合。大量站点-场景权重为 0，说明残差模型只在部分站点和部分时段有效。因此 Round64 的定位是稳健小幅提升，而不是模型能力大幅突破。

---

## 4. Valid 集评估

| 候选 | sm_nrmse | city_nrmse | bad_sites | 状态 |
|------|---:|---:|---:|:---:|
| Round61 | 16.0311 | 4.8630 | 0 | baseline |
| Round63 lgb | 15.9992 | 4.7086 | 2 | FAIL |
| **Round64 safe** | **15.8893** | **4.7094** | **0** | **PASS** |

Round64 safe 同时改善 sm（-0.14pp）和 bad_sites（0），city_nrmse 略差（+0.0006pp，可忽略）。

---

## 5. Test 集评估

### 5.1 总体指标（test 6-19h）

**两种最优概念**：
- **数值最优**：单看 test 指标最低的候选。
- **可采用最优**：同时满足 valid 安全门控、无站点退化、可回退要求的候选。

| 指标 | Round61 | Round63 lgb | Round64 safe | 数值最优 | 可采用最优 |
|------|---:|---:|---:|:---:|:---:|
| site_mean_nrmse | 11.4095% | **11.0694%** | 11.2806% | Round63 lgb | Round64 safe |
| city_nrmse | 3.9531% | **3.7726%** | 3.8104% | Round63 lgb | Round64 safe |
| city_nrmse_10_14 | 6.2359% | **5.9827%** | 6.1879% | Round63 lgb | Round64 safe |
| bias_6_19 | 1.4232% | -0.8697% | 1.5477% | Round63 lgb | - |
| bias_10_14 | 8.3998% | **6.1353%** | 8.0181% | Round63 lgb | - |
| RMSE (MW) | 0.9321 | **0.8999** | 0.9042 | Round63 lgb | - |
| MAE (MW) | 0.4478 | **0.4219** | 0.4359 | Round63 lgb | - |
| 变差>+1pp 站点数 | 0 | 0 | 0 | 两者均稳定 | 两者均稳定 |

> Round63 lgb 在 test 上数值最优，但 valid 上有 2 站点退化，不能直接采用。
> Round64 safe 数值提升略小（因大量站点 w=0.00 回退），但 valid 安全门控通过、test 无站点退化，是当前可采用最优候选。

### 5.2 Delta vs Round61 (test 6-19h)

| 候选 | Δsm_nrmse | Δcity_nrmse | Δcity_nrmse_10_14 | Δ|bias_abs| | Δbad_sites |
|------|---:|---:|---:|---:|---:|
| Round63 lgb | -0.3401pp | -0.1805pp | -0.2532pp | -0.5535pp | +0 |
| Round64 safe | -0.1289pp | -0.1427pp | -0.0480pp | +0.1245pp | +0 |

### 5.3 逐小时 city_nrmse

详见 `output/pv_pipeline/round64/round64_test_hourly_compare.csv`

### 5.4 重点站点 site_nrmse

详见 `output/pv_pipeline/round64/round64_test_site_compare.csv`

---

## 6. 结论

**valid 集决策：adopt_round64_candidate（5/5 检查全部 PASS）**

| 检查项 | 阈值 | 实际 delta | 结果 |
|--------|------|----------|------|
| sm_nrmse_6_19 不差于 R61+0.10pp | delta=-0.14pp | -0.1418pp | PASS |
| city_nrmse_6_19 不差于 R61+0.05pp | delta=-0.15pp | -0.1536pp | PASS |
| city_nrmse_10_14 不劣于 R61 | delta=-0.02pp | -0.0151pp | PASS |
| 变差>+1pp 站点数 == 0 | bad_sites=0 | 0 | PASS |
| sm_nrmse_10_14 不变差 | delta=-0.05pp | -0.0500pp | PASS |

**test 集指标（最终评估）：**

| 指标 | Round61 | Round64 safe | Delta | 评价 |
|------|---:|---:|---:|:---:|
| site_mean_nrmse_6_19 | 11.4095% | 11.2806% | -0.1289pp | 改善 |
| city_nrmse_6_19 | 3.9531% | 3.8104% | -0.1427pp | 改善 |
| city_nrmse_10_14 | 6.2359% | 6.1879% | -0.0480pp | 改善 |
| sm_nrmse_10_14 | 15.7862% | 15.7042% | -0.0820pp | 改善 |
| bias_6_19 | +1.4232% | +1.5477% | +0.1245pp | 略差 |
| bias_10_14 | +8.3998% | +8.0181% | -0.3817pp | 改善 |
| RMSE (MW) | 0.9321 | 0.9042 | -0.0279 | 改善 |
| MAE (MW) | 0.4478 | 0.4359 | -0.0119 | 改善 |
| 变差>+1pp 站点数 | 0 | 0 | 0 | 无退化 |

**综合结论**：

- Round64 safe 在 valid 上 5/5 安全检查全部通过，test 上 NRMSE 类指标全面改善（sm -0.13pp, city -0.14pp, city_10_14 -0.05pp），RMSE/MAE 均改善，无站点退化。
- 10-14 点 bias 从 +8.40% 改善至 +8.02%（改善 0.38pp），说明残差融合对高估问题有正向作用。
- 6-19h bias 从 +1.42% 变为 +1.55%（略差 0.12pp），但仍在安全范围内。
- **建议采用 Round64 safe 作为新的最优候选。**
- 本轮不覆盖正式 `power_pred_final`，候选结果存放于 `output/pv_pipeline/round64/round64_candidates.pkl`。

---

## 7. 输出文件

| 文件 | 说明 |
|------|------|
| `round64/round64_site_scene_weights.csv` | 站点-场景权重表 |
| `round64/round64_valid_weight_search.csv` | 完整权重搜索结果 |
| `round64/round64_guard_summary.json` | 门控汇总 |
| `round64/round64_candidates.pkl` | 候选预测（含 Round64 safe） |
| `round64/round64_test_overall_compare.csv` | Test 总体对比 |
| `round64/round64_test_hourly_compare.csv` | Test 逐小时对比 |
| `round64/round64_test_site_compare.csv` | Test 逐站点对比 |
