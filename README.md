# 光伏功率预测项目

连云港地区光伏电站功率预测流水线，支持辐照反演、站点级功率估计和城市总量预测。

---

## 正式训练入口

```bash
# 完整训练（唯一正式入口）
python scripts/run_full_pipeline.py

# 训练后验证（自动包含在完整流程中）
python scripts/posttrain_validation.py
python scripts/check_dashboard_prediction_values.py
```

> **注意**：`run_full_pipeline.py` 是正式主入口；历史 round 脚本（如 round63-73）只作为归档和审计材料，不作为正式训练入口。

训练完成后，按以下步骤启动可视化看板：

# 1. 进入项目根目录
cd /Users/masuncheng/Downloads/photovoltaic_forecasting_pj

# 2. 启动本地 HTTP 服务
python -m http.server 8060

如果 8060 被占用，可以换一个端口，例如：

```bash
python -m http.server 8070
```

# 3. 浏览器打开
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html

如果用了 8070，就打开：

http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html

注意：不要直接双击 HTML 文件打开，因为页面需要读取 output/pv_pipeline/interactive_dashboard/ 里的 JSON 数据，直接用 file:// 打开时浏览器通常会拦截数据读取，导致图表不显示。

停止服务：

# 前台启动时
Ctrl+C

# 如果是后台残留进程
pkill -f "http.server 8060"

重新训练或重新导出可视化数据后，先执行：

python scripts/export_interactive_dashboard_data.py

然后浏览器强制刷新即可：

Ctrl + Shift + R

如果页面仍显示旧数据，可以加版本参数访问：

http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html?v=latest

---

## 数据切分口径

| 集合 | 时间范围 | 用途 |
|------|---------|------|
| train | 2023-01-01 ~ 2025-06-30 | 模型训练 |
| valid | 2025-07-01 ~ 2025-08-31 | 校准、调参 |
| test | 2025-09-01 ~ 2025-12-31 | 最终评估 |
| future | 2026-01-01 ~ 2026-03-31 | 保留，不参与训练和评估 |

---

## 指标口径

- **评估范围**：test 集，小时 6-19，不含 future
- **站点 NRMSE**：RMSE / capacity_mw × 100（%）
- **城市 NRMSE**：RMSE / 参与评估站点装机容量之和 × 100（%）
- **主要指标**：NRMSE、MAE、RMSE、BIAS（%）、pred/actual 比值
- **不使用**：MAPE、WAPE 作为主指标（仅作诊断参考）

---

## 最终预测文件

```
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl   # 完整预测（含 train/valid/test/future）
output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl   # 评估口径（test 6-19）
```

- 唯一正式预测列：`power_pred_final`（不允许回退）
- 正式评估与可视化仅使用 train、valid、test 中的有效样本，不包含 future
- test 集评估范围：2025-09-01 至 2025-12-31，小时 6-19

---

## 训练流水线阶段

```
Stage 1 — 数据准备
  stages/01_data/build_site_master.py          站点元数据
  stages/01_data/prepare_meteo_and_power.py    功率清洗 + ERA5 IDW 插值

Stage 2 — 辐照反演与融合
  stages/02_irradiance/train_inverse_model.py   集中式辐照反演
  stages/02_irradiance/train_irradiance_blend.py 辐照空间融合

Stage 3 — 分布式功率预测
  stages/03_power/train_distributed_model_v159.py  分布式双分支模型

Stage 4 — 评估与可视化
  stages/04_evaluation/evaluate_layers.py           多维度评估
  scripts/export_interactive_dashboard_data.py        可视化数据导出
```

---

## 目录结构

```
photovoltaic_forecasting_pj/
├── configs/
│   └── pipeline.yaml           统一配置（split 口径、评估参数等）
├── scripts/
│   ├── run_full_pipeline.py            唯一正式训练入口
│   ├── posttrain_validation.py         训练后逻辑审计
│   ├── check_dashboard_prediction_values.py  Dashboard 校验
│   ├── export_interactive_dashboard_data.py  可视化导出
│   ├── common_paths.py               公共路径工具
│   ├── metrics_common.py             统一指标口径
│   └── archive_legacy_round_files.py  归档历史文件
├── stages/
│   ├── 01_data/         数据准备
│   ├── 02_irradiance/   辐照反演
│   ├── 03_power/         分布式模型
│   ├── 04_evaluation/   评估
│   └── 05_visualization/ 可视化看板
├── data/                  原始输入数据
└── output/pv_pipeline/   训练输出
    ├── predictions/        正式预测 pkl（含 canonical）
    ├── tables/             中间训练表（CSV/Parquet）
    ├── models/             模型文件
    ├── metrics/            指标文件
    └── interactive_dashboard/  可视化 JSON
```

---

## 依赖

```bash
pip install -r requirements.txt
# 需要：pandas, numpy, scikit-learn, catboost
```

---

## 历史归档

旧版 round 临时脚本和过期产物已归档到 `archive/` 目录，主流程不依赖归档文件。

---

## 版本历史

详见 [CHANGELOG.md](./CHANGELOG.md)。
