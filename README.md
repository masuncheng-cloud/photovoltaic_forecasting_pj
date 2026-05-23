# 光伏功率预测项目

连云港地区光伏电站功率预测流水线，支持辐照反演、站点级功率估计和城市总量预测。

## 快速开始

```bash
# 训练 + 评估 + 看板（完整流程）
python scripts/all.py --mode all --data-root data --output-root output/pv_pipeline

# 仅训练
python scripts/train.py --data-root data --output-root output/pv_pipeline

# 仅生成看板
python scripts/dashboard.py --data-root data --output-root output/pv_pipeline

# 仅诊断瓶颈
python scripts/diagnose.py --data-root data --output-root output/pv_pipeline
```

## 目录结构

```
photovoltaic_forecasting_pj/
├── data/                     # 原始输入数据
│   ├── 2023/, 2024/, 2025/   # ERA5 气象数据
│   ├── tcc_strd/             # 云量和向下热辐射数据
│   └── power_data/           # 电站功率 Excel 台账
│
├── scripts/                  # 统一运行入口
│   ├── train.py              # 训练 + 评估流水线
│   ├── dashboard.py          # 可视化看板
│   ├── diagnose.py            # 误差诊断分析
│   └── all.py               # 一键全流程
│
├── stages/                   # 流水线各阶段脚本
│   ├── 01_data/             # 数据准备
│   ├── 02_irradiance/       # 辐照反演与融合
│   ├── 03_power/             # 分布式功率预测
│   ├── 04_evaluation/        # 多维度评估
│   └── 05_visualization/     # 中文化看板
│
├── src/pv_forecasting/      # 核心算法模块
│   ├── core/                 # 通用基础模块
│   │   ├── config.py          # 路径配置
│   │   ├── runtime.py         # 命令行参数与路径构造
│   │   ├── utils.py           # 通用工具与指标函数
│   │   ├── data_io.py         # 原始数据读取与 ERA5 插值
│   │   ├── features.py        # 特征工程
│   │   └── models.py          # 表格模型（CatBoost/sklearn）训练封装
│   │
│   └── tasks/                # 核心业务逻辑
│       ├── site_master.py      # 站点主表构建
│       ├── power_processing.py # 功率清洗与质量评估
│       ├── inverse_model.py    # 集中式辐照反演
│       ├── irradiance_blend.py # 全站点辐照融合
│       ├── distributed_power_v152.py  # 分布式功率预测（修复版）
│
└── output/pv_pipeline/       # 训练输出
    ├── tables/               # 中间数据表
    ├── models/              # 模型文件
    ├── metrics/            # 评估指标
    ├── figures/             # 诊断图
    └── figures_dashboard/   # 看板图
```

## 训练流水线

```
原始数据
├── ERA5 气象数据 (2023–2025)        data/2023, 2024, 2025/
├── TCC/STRD 云量数据               data/tcc_strd/2023, 2024, 2025/
└── 电站功率 Excel                  data/power_data/

Stage 1 — 数据准备
├── build_site_master.py
│     构建站点元数据（site_id, 坐标, 装机, 县域）
└── prepare_meteo_and_power.py
      ERA5 IDW 插值到站点 + 功率清洗

Stage 2 — 辐照反演与融合
├── train_inverse_model.py
│     集中式站点功率 → 月度PR反演 → 辐照 g_pred
│     仅用集中式（23个，精度高、无弃光）
└── train_irradiance_blend.py
      g_pred（集中式）→ IDW空间插值
      + ERA5 ssrd → 加权融合 → 全站点 g_blend

Stage 3 — 分布式功率预测
└── train_distributed_model_v159.py
      g_blend + 气象特征 → 双分支
      ├── Branch A: p_on 分类器（是否开机）
      ├── Branch B: 场景分组建模（night/low/mid/ramp/clear_peak）
      └── MAPE感知残差修正 + 逐站标定

Stage 4 — 评估
├── evaluate_layers.py
│     分阶段指标汇总
└── evaluate_pipeline.py
      多维度评估（县域/场景/质量/governance）
```

## 当前指标（Test）

| 维度 | MAE | RMSE | NRMSE | Corr |
|---|---|---|---|---|
| 站点级 | 0.3132 | 0.7146 | 0.0360 | 0.8751 |
| 城市级 | 9.046 | 15.19 | 0.0669 | 0.9626 |

## 输出文件

训练完成后重点查看：

```
output/pv_pipeline/
├── tables/
│   ├── site_master.csv               # 站点元数据
│   ├── distributed_predictions.pkl    # 最终预测结果
│   └── power_clean.pkl              # 清洗后功率数据
├── metrics/
│   ├── layer_metrics_summary.csv           # 分阶段 RMSE
│   ├── distributed_metrics.csv             # 分布式功率指标
│   ├── distributed_metrics_city_total.csv  # 城市总量指标
│   ├── distributed_metrics_by_scene.csv    # 分场景指标
│   ├── distributed_metrics_by_county.csv   # 分县域指标
│   ├── data_quality_metrics.csv           # 数据质量
│   └── distributed_governance_summary.csv # 弃光检测
└── figures/
    └── city_total_typical_day.png   # 典型日曲线
```

## 依赖

- Python 3.10+
- CatBoost（推荐，自动回退到 sklearn 随机森林）
- pandas, numpy, scikit-learn, matplotlib

```bash
pip install -r requirements.txt
```

## 版本历史

详见 [CHANGELOG.md](./CHANGELOG.md)。
test change 2026年 05月 23日 星期六 11:36:05 CST
### Auto-sync test 2026年 05月 23日 星期六 11:37:06 CST
