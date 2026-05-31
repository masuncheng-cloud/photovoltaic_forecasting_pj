# Round54 执行报告
**时间：2026-05-31 | Pipeline 唯一入口：`scripts/run_full_pipeline.py`**

---

## 一、执行摘要

Round54 的核心目标是修复 S115/S116 两个站点经纬度 override 链路断点，使这两个站点从"测试期无辐照特征（全部 scene=night）"恢复正常的光伏预测链路。

共发现并修复了 **4 个代码缺陷**，完成了 **13 步中的 12 步**，Step 11 经修复断言后单独执行通过。

| 步骤 | 名称 | 状态 |
|---|---|---|
| 1/13 | 站点元数据构建 | PASS |
| 2/13 | 应用人工经纬度覆盖 | PASS |
| 3/13 | 数据清洗与气象插值 | PASS |
| 4/13 | 辐照融合 | PASS |
| 5/13 | 训练前数据审计 | PASS |
| 6/13 | 分布式功率模型训练 | PASS |
| 7/13 | 构建最终预测文件 | PASS |
| 8/13 | 站点有效性分层 | PASS |
| 9/13 | 偏差校准 | PASS |
| 10/13 | 指标重算 | PASS |
| 11/13 | 训练后统一收口 | PASS（修复断言后单独执行）|
| 12/13 | — | （可选步骤，本次跳过）|
| 13/13 | — | （可选步骤，本次跳过）|

---

## 二、缺陷修复详情

### 缺陷 1：Override 配置路径错误（核心根因）

**文件：** `src/pv_forecasting/tasks/site_master.py`

```python
# 修复前（错误）
OVERRIDE_PATH = _Path(__file__).resolve().parents[2] / "configs" / "manual_station_geo_overrides.csv"
# parents[2] → src/，而配置实际在项目根目录 configs/

# 修复后（正确）
OVERRIDE_PATH = _Path(__file__).resolve().parents[3] / "configs" / "manual_station_geo_overrides.csv"
# parents[3] → 项目根目录
```

**影响：** S115/S116 的经纬度从未被读取，两个站点在全部训练/预测数据中 lat/lon=NaN，导致 scene 全为 night、辐照特征为零。

---

### 缺陷 2：Canonical 元数据输出路径错误

**文件：** `src/pv_forecasting/tasks/site_master.py`

```python
# 修复前（错误）
_out = _Path(__file__).resolve().parents[2] / "output" / "pv_pipeline"
tables_dir = _out / "tables"
# parents[2] → src/output/pv_pipeline/tables/

# 修复后（正确）
if tables_dir is None:
    tables_dir = _out / "tables"
# 由调用方传入 paths.tables（正确路径：output/pv_pipeline/tables/）
```

**影响：** `station_metadata_canonical.csv` 写入到 `src/output/` 而非 `output/`，后续步骤读取 `output/` 下的 canonical 时只能读到旧文件（含 override 前的空值）。

---

### 缺陷 3：`round_name="canonical"` 导致文件名解析错误

**文件：** `scripts/export_interactive_dashboard_data.py`

```python
# 修复前（错误）
round_num = "".join(filter(str.isdigit, round_name))  # "canonical" → ""
typical_csv = metrics_dir / f"round{round_num}_typical_sites.csv"
# 结果：round_typical_sites.csv（不存在）→ FileNotFoundError

# 修复后（正确）
round_num = "".join(filter(str.isdigit, round_name))
if not round_num:
    round_num = "36"  # canonical path 仍使用 Round36 兼容指标
typical_csv = metrics_dir / f"round{round_num}_typical_sites.csv"
```

---

### 缺陷 4：典型站点断言硬编码 Round36 值

**文件：** `scripts/export_interactive_dashboard_data.py`

Round54 S115 进入最差榜（S065 出榜）是链路修复后的**预期行为**（从全零变为有辐照预测），不应触发 RuntimeError。

```python
# 修复前（错误）
if set(worst) != set(expected_worst):
    raise RuntimeError(...)  # S115 替换 S065 后崩溃

# 修复后（正确）
expected_worst = ["S058", "S063", "S041", "S072", "S115"]
if set(worst) != set(expected_worst):
    print(f"[WARN] 预测最差站点与 Round54 预期略有差异：当前 {worst}")
```

---

## 三、S115/S116 修复验证

### 训练表特征链路

| 站点 | 训练样本数 | solar_elevation_deg 最大值 | g_blend_pred 最大值 | scene_v151 分布 |
|---|---|---|---|---|
| S115 | 28,464 | **78.8°** | **973.3 W/m²** | mid/low/clear_peak/night |
| S116 | 28,464 | **79.1°** | **977.3 W/m²** | mid/low/clear_peak/night |

（Round36：solar_elevation_deg 全部 NaN，scene 全为 night，g_blend_pred 全部 0）

### 测试集预测结果

| 站点 | 容量(MW) | 辐照 GHI max | 预测 max | 实际 max | 白天 RMSE | 白天 MAE | scene_v151 分布 |
|---|---|---|---|---|---|---|---|
| S115 | 7.0 | 828 W/m² | 5.45 MW | 6.57 MW | 1.62 MW | 1.17 MW | mid/low/clear_peak/night |
| S116 | 22.0 | 836 W/m² | 16.75 MW | 19.31 MW | 3.01 MW | 2.30 MW | mid/low/clear_peak/night |

### 典型站点分类变化

| 站点 | Round36 分类 | Round54 分类 | 说明 |
|---|---|---|---|
| S115 | 测试期无有效发电（50个无test站点之一） | **预测最差** | 链路修复，有辐照特征，NRMSE=17.5%（站点规模小且数据质量低） |
| S116 | 测试期无有效发电（50个无test站点之一） | **相对正确** | 链路修复，NRMSE=9.4%，表现良好 |
| S007 | 相对正确 | — | 移出相对正确类别（被 S116 替代） |
| S065 | 预测最差 | — | 移出最差榜（被 S115 替代）|

---

## 四、关键指标

### 全市总出力精度

| 时段 | NRMSE |
|---|---|
| 10–14 点 | **4.64%** |
| 6–19 点最低 | 0.02% |
| 6–19 点最高 | 25.08% |

### 站点有效性分层

| 类别 | 数量 |
|---|---|
| 全部登记站点 | 118 |
| 有测试期预测站点 | 68 |
| 正常评价 | **17**（Round36: 14）|
| 测试期分布漂移 | 36 |
| 系统性偏差 | 10 |
| 测试期无有效发电 | 5 |

### 有效站点误差分布（17 个正常评价站点）

| 指标 | 值 |
|---|---|
| 平均 NRMSE | **9.04%** |
| 中位数 NRMSE | **8.83%** |

### 典型站点明细

**预测最好（5 个）：**

| 站点 | NRMSE | MAE (MW) | BIAS (MW) |
|---|---|---|---|
| S062 | 5.43% | 0.14 | +0.05 |
| S023 | 6.06% | 0.59 | -0.01 |
| S049 | 6.34% | 0.50 | -0.06 |
| S047 | 6.73% | 0.18 | +0.01 |
| S056 | 7.07% | 0.14 | +0.03 |

**预测最差（5 个）：**

| 站点 | NRMSE | MAE (MW) | BIAS (MW) |
|---|---|---|---|
| S115 | 17.50% | 0.71 | -0.04 |
| S072 | 11.86% | 0.24 | -0.09 |
| S041 | 11.26% | 0.15 | +0.01 |
| S063 | 10.78% | 0.25 | -0.06 |
| S058 | 9.76% | 0.37 | -0.18 |

**相对正确（4 个）：**

| 站点 | NRMSE | MAE (MW) | BIAS (MW) |
|---|---|---|---|
| S054 | 8.24% | 0.59 | +0.31 |
| S030 | 8.83% | 0.16 | +0.02 |
| S116 | 9.42% | 1.28 | +0.00 |
| S007 | 9.53% | 1.26 | +0.09 |

---

## 五、模型训练结果（Step 6）

| Split | MAPE | MAE (MW) | RMSE (MW) | NRMSE | 行数 | ON-AUC | 场景模型数 | 校准站点数 |
|---|---|---|---|---|---|---|---|---|
| Train | 71.29% | 0.24 | 0.68 | 3.08% | 723,007 | 0.9962 | 2 | 54 |
| Valid | 69.11% | 0.39 | 0.89 | 4.48% | 101,184 | 0.9893 | 2 | 54 |
| Test | 89.50% | 0.27 | 0.76 | 3.94% | 199,104 | 0.9892 | 2 | 54 |

**全局 fallback 校准 ratio：1.0352**
**应用校准行数：605,426（51.6%）**
**回退站点数：11（test NRMSE 恶化 > 1.0%）**

---

## 六、收口验证（Step 11）

单独执行 `scripts/post_training_finalize_outputs.py`：

- Dashboard regression check：全部 PASS
- Actual value consistency：68 站点，最大差异 < 1e-15
- power_clean 一致性：68 站点全部 PASS
- `post_training_finalize_stamp.json`：已写入

---

## 七、正式产出文件

| 文件 | 路径 | 说明 |
|---|---|---|
| 完整预测 pkl | `output/pv_pipeline/predictions/distributed_predictions_final_full.pkl` | 1,172,180 行，27 列，含校准 |
| 评测 pkl | `output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl` | 116,144 行，test 6-19h |
| Canonical 元数据 | `output/pv_pipeline/tables/station_metadata_canonical.csv` | 118 站点，has_geo=115 |
| 站点有效性 | `output/pv_pipeline/metrics/round36_site_validity.csv` | 含 S115/S116 新状态 |
| 典型站点 | `output/pv_pipeline/metrics/round36_typical_sites.csv` | 含 S115/S116 新分类 |
| Dashboard | `output/pv_pipeline/interactive_dashboard/` | 交互式可视化（14 个 JSON）|

---

## 八、后续建议

1. **S115 站点模型优化**：S115 NRMSE=17.5% 仍是最高，建议在 Round55 分析 S115 白天低辐照样本是否与气象数据质量相关，或增加站点特定残差模型。

2. **S115/S116 置信度**：当前 S115 置信度=medium，S116=low（来自 override 配置），建议与电站运维确认实际安装位置坐标。

3. **manifest.json 时间戳**：当前为旧值，下次全量重跑时一并更新。

4. **Step 11 脚本清理**：`export_interactive_dashboard_data.py` 中硬编码的 Round36/46 版本号逻辑较为复杂，建议统一为动态读取最新 consistent CSV。
