# Round63 离线分场景残差模型实验报告

**日期**: 2026-06-01
**分支**: experiment/model-structure-round62
**目的**: 评估分场景残差模型是否能提升 Round61 基线

---

## 1. 实验概述

### 1.1 Round61 基线复核

Round61 基线复核结果：**PASS**（21/21 检查通过）。

详见 `docs/Round63_Round61基线复核报告.md`。

### 1.2 实验设计

**残差目标**：容量归一化残差（`residual_norm = power_mw/capacity - power_pred_final/capacity`）

**场景划分**：
| 场景 | 小时 | 样本数（Train/Valid） |
|------|------|:---:|
| dawn | 6-8h | 90,330 / 12,648 |
| day | 9-16h | 241,008 / 33,728 |
| dusk | 17-19h | 90,433 / 12,648 |

**候选模型**：
| 模型 | 类型 | 特点 |
|------|------|------|
| ridge_residual | Ridge 回归 | 线性、稳定、可解释 |
| lgb_residual | LightGBM | 非线性、early stopping |

**特征**（15个）：hour, month, dayofyear, capacity_mw, pred_norm, g_blend_pred, clear_sky_ghi, clear_sky_index, scene_is_*, calibrated_ratio, latitude, longitude

**LightGBM 最佳迭代次数**：
| 场景 | best_iteration | 含义 |
|------|:---:|------|
| dawn | 65 | 残差信号适中 |
| day | **5** | **残差信号极弱，接近随机** |
| dusk | 61 | 残差信号适中 |

---

## 2. Valid 集评估结果

| 候选 | sm_nrmse_6_19 | city_nrmse_6_19 | bad_sites | 状态 |
|------|---:|---:|---:|:---:|
| Round61 baseline | 16.0311 | 4.8630 | 0 | baseline |
| ridge_residual | 16.6625 | 4.6204 | **18** | **FAIL** (18站点退化) |
| lgb_residual | 15.9992 | 4.7086 | **2** | **FAIL** (2站点退化) |

> 安全门控规则：sm_nrmse <= Round61+0.10pp, city_nrmse <= Round61+0.10pp, bad_sites == 0

**Valid 选择结果**: `power_pred_final`（adopted=False）

---

## 3. Test 集评估结果

### 3.1 总体指标（test 6-19h）

| 指标 | Round61 | ridge_residual | lgb_residual | 最优 |
|------|---:|---:|---:|:---:|
| site_mean_nrmse | 11.4095% | 11.6672% | 11.0694% | lgb_residual |
| city_nrmse | 3.9531% | 3.8791% | 3.7726% | lgb_residual |
| city_nrmse_10_14 | 6.2359% | 6.0225% | 5.9827% | lgb_residual |
| bias_6_19 | 1.4232% | 0.3667% | -0.8697% | — |
| bias_10_14 | 8.3998% | 6.7782% | 6.1353% | — |
| RMSE (MW) | 0.9321 | 0.9617 | 0.8999 | — |
| MAE (MW) | 0.4478 | 0.4627 | 0.4219 | — |
| 变差>+1pp 站点数 | 0 | 12 | 0 | Round61 最稳定 |

### 3.2 Delta vs Round61 (test 6-19h)

| 候选 | Δsm_nrmse | Δcity_nrmse | Δcity_nrmse_10_14 | Δ|bias_abs| | Δ变差站点数 |
|------|---:|---:|---:|---:|---:|
| ridge_residual | +0.2577pp | -0.0740pp | -0.2134pp | -1.0565pp | +12 |
| lgb_residual | -0.3401pp | -0.1805pp | -0.2532pp | -0.5535pp | +0 |

### 3.3 逐小时 city_nrmse（test）

详见 `output/pv_pipeline/round63/round63_test_hourly_compare.csv`

### 3.4 重点站点 site_nrmse（test）

详见 `output/pv_pipeline/round63/round63_test_site_compare.csv`

---

## 4. 结论

**保持 Round61，不直接采用 Round63 raw 候选。**

但 lgb_residual 在 test 集上显示出一定提升潜力（sm -0.34pp, city -0.18pp），其问题在于 valid 上有 2 站点退化。下一步应增加 valid 驱动的站点级、小时级、场景级回退保护，验证能否保留整体提升，同时避免局部站点退化。

---

## 5. 下一步建议

1. **实施站点-场景级安全融合**（Round64）：在 lgb_residual 基础上增加 valid 驱动的站点级/小时级/场景级回退保护
2. **继续分场景残差模型方向**：lgb_residual 的 test 全面改善说明方向可行，只是需要更细粒度的保护机制
3. **探索规则化修正**：针对 7 点低估、17 点低估、10-14 点高估设计确定性修正规则
4. **站点分级策略**：对高频偏差站点单独建模或特殊处理

---

## 6. 输出文件

| 文件 | 说明 |
|------|------|
| `round63/round63_residual_models.pkl` | 训练好的模型（服务器本地，不进 Git） |
| `round63/round63_feature_list.json` | 特征列表 |
| `round63/round63_valid_candidate_compare.csv` | Valid 集候选对比 |
| `round63/round63_test_overall_compare.csv` | Test 集总体指标 |
| `round63/round63_test_hourly_compare.csv` | Test 集逐小时 city_nrmse |
| `round63/round63_test_site_compare.csv` | Test 集逐站点 NRMSE |
| `round63/round63_scene_training_summary.csv` | 分场景训练指标 |
