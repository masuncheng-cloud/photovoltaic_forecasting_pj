# Cursor 执行方案 Round50：训练逻辑工程收口、去冗余与可复现提升

## 目标

本轮不再继续叠加新的临时 round 修补脚本，而是把现有项目整理成一条清晰、可复现、可审计的正式训练链路。

核心目标：

1. 保留当前有效训练逻辑：数据治理、集中式辐照估计、空间融合、分布式功率预测、校准、评估、可视化导出。
2. 建立唯一正式训练入口，避免 `roundXX` 脚本互相覆盖最终结果。
3. 统一 NRMSE、MAE、RMSE、BIAS、PRED/ACTUAL 等指标口径。
4. 自动保证可视化页面使用最新训练结果。
5. 清理或归档历史残留脚本、旧结果文件和过期报告。
6. 补充训练逻辑审计，避免测试集泄漏、预测列混用、指标口径混用。

本轮完成后，项目应能回答三个问题：

- 用哪个命令完整训练？
- 最终结果文件是哪一个？
- 可视化页面的数据是否来自最新训练结果？

---

## 一、执行前检查

请先在 Cursor 服务器项目根目录执行：

```bash
pwd
find . -maxdepth 2 -type f | sort | head -200
find scripts -maxdepth 1 -type f | sort
find output/pv_pipeline -maxdepth 2 -type f | sort | head -200
```

确认项目根目录中至少存在：

```text
scripts/
data/ 或 input/
output/pv_pipeline/
stages/05_visualization/interactive_forecast_dashboard.html
```

如果项目有内外两层目录，先确认真正用于训练的是哪一层。后续所有修改只在正式训练目录中进行。

---

## 二、建立统一配置文件

新增文件：

```text
configs/pipeline.yaml
```

内容参考：

```yaml
data:
  data_root: data
  output_root: output/pv_pipeline

split:
  train_start: "2023-01-01"
  valid_start: "2025-04-01"
  test_start: "2025-09-01"
  test_end: "2025-12-31"

eval:
  start_hour: 6
  end_hour: 19
  exclude_future: true
  exclude_zero_actual_for_site_nrmse: false
  nrmse_denominator: capacity_mw
  city_nrmse_denominator: capacity_sum_mw

quality:
  min_positive_train_valid_6_19: 300
  invalid_zero_ratio_6_19_threshold: 0.98
  max_power_over_capacity_ratio: 1.2

prediction:
  final_prediction_column: power_pred_final
  fallback_prediction_columns:
    - power_pred_cal
    - power_pred
    - prediction_mw

dashboard:
  enabled: true
  output_dir: output/pv_pipeline/interactive_dashboard
  html_path: stages/05_visualization/interactive_forecast_dashboard.html
  exclude_future: true

archive:
  archive_round_scripts: true
  keep_round_docs: true
```

要求：

- 后续所有训练、评估、导出脚本都优先读取 `configs/pipeline.yaml`。
- 不允许在多个脚本里散落 `2025-09-01`、`6-19`、`power_pred_final` 等硬编码。
- 如果暂时无法完全配置化，至少将最终入口、评估脚本、可视化导出脚本接入该配置。

---

## 三、建立公共路径与配置工具

新增文件：

```text
scripts/common_paths.py
```

实现：

```python
from pathlib import Path
import yaml


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_pipeline_config(config_path: str | None = None) -> dict:
    root = project_root()
    path = Path(config_path) if config_path else root / "configs" / "pipeline.yaml"
    if not path.exists():
        raise FileNotFoundError(f"pipeline config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def output_root(cfg: dict) -> Path:
    return project_root() / cfg["data"]["output_root"]


def dashboard_dir(cfg: dict) -> Path:
    return project_root() / cfg["dashboard"]["output_dir"]
```

要求：

- 不要在训练脚本里重复拼接 `output/pv_pipeline`。
- 旧脚本如果已经有路径类，可以保留，但最终入口必须统一走一个路径来源。

---

## 四、统一指标口径

新增文件：

```text
scripts/metrics_common.py
```

实现以下函数，并让报告、可视化、逐小时 CSV 全部调用它：

```python
import numpy as np
import pandas as pd


def build_eval_frame(
    df: pd.DataFrame,
    *,
    pred_col: str = "power_pred_final",
    split: str = "test",
    start_hour: int = 6,
    end_hour: int = 19,
    exclude_future: bool = True,
) -> pd.DataFrame:
    out = df.copy()
    if "split" in out.columns:
        out = out[out["split"].eq(split)]
    if exclude_future and "is_future" in out.columns:
        out = out[~out["is_future"].fillna(False)]
    out["timestamp"] = pd.to_datetime(out["timestamp"])
    out["hour"] = out["timestamp"].dt.hour
    out = out[out["hour"].between(start_hour, end_hour)]
    need = ["timestamp", "station_id", "power_mw", pred_col, "capacity_mw"]
    missing = [c for c in need if c not in out.columns]
    if missing:
        raise KeyError(f"missing eval columns: {missing}")
    return out.dropna(subset=["power_mw", pred_col, "capacity_mw"])


def mae(actual, pred) -> float:
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    return float(np.mean(np.abs(pred - actual))) if len(actual) else np.nan


def rmse(actual, pred) -> float:
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    return float(np.sqrt(np.mean((pred - actual) ** 2))) if len(actual) else np.nan


def nrmse_by_capacity(actual, pred, capacity_mw) -> float:
    den = float(capacity_mw)
    if den <= 0:
        return np.nan
    return rmse(actual, pred) / den * 100


def bias_percent(actual, pred) -> float:
    actual_sum = float(np.sum(actual))
    pred_sum = float(np.sum(pred))
    if abs(actual_sum) < 1e-12:
        return np.nan
    return (pred_sum - actual_sum) / actual_sum * 100


def pred_actual_ratio(actual, pred) -> float:
    actual_sum = float(np.sum(actual))
    if abs(actual_sum) < 1e-12:
        return np.nan
    return float(np.sum(pred)) / actual_sum
```

逐小时站点平均 NRMSE：

```python
def hourly_site_mean_nrmse(eval_df: pd.DataFrame, pred_col: str) -> pd.DataFrame:
    rows = []
    for hour, hdf in eval_df.groupby("hour"):
        vals = []
        for sid, sdf in hdf.groupby("station_id"):
            cap = sdf["capacity_mw"].dropna()
            if cap.empty:
                continue
            vals.append(nrmse_by_capacity(sdf["power_mw"], sdf[pred_col], cap.iloc[0]))
        rows.append({
            "hour": hour,
            "sample_count": len(hdf),
            "site_mean_nrmse_percent": np.nanmean(vals) if vals else np.nan,
        })
    return pd.DataFrame(rows).sort_values("hour")
```

逐小时城市 NRMSE：

```python
def hourly_city_nrmse(eval_df: pd.DataFrame, pred_col: str) -> pd.DataFrame:
    rows = []
    capacity_sum = (
        eval_df[["station_id", "capacity_mw"]]
        .drop_duplicates("station_id")["capacity_mw"]
        .sum()
    )
    for hour, hdf in eval_df.groupby("hour"):
        agg = hdf.groupby("timestamp", as_index=False).agg(
            actual=("power_mw", "sum"),
            pred=(pred_col, "sum"),
        )
        rows.append({
            "hour": hour,
            "city_nrmse_percent": nrmse_by_capacity(
                agg["actual"], agg["pred"], capacity_sum
            ),
        })
    return pd.DataFrame(rows).sort_values("hour")
```

要求：

- `NRMSE` 在所有报告和页面中统一展示为 `%`。
- 全市 NRMSE 分母统一为参与评估站点装机容量之和 `capacity_sum_mw`。
- 站点 NRMSE 分母统一为该站点装机容量 `capacity_mw`。
- 不再同时混用 `WAPE`、`MAPE` 作为主要指标。
- 如果仍保留 `WAPE/MAPE`，只能放在补充诊断中，不作为主结果。

---

## 五、建立唯一正式训练入口

新增或改造：

```text
scripts/run_full_pipeline.py
```

该脚本作为唯一正式入口，按顺序调用已有稳定模块：

```text
1. 数据清洗与站点映射
2. 数据质量审计
3. 集中式功率到辐照估计
4. 辐照空间扩展与 ERA5 融合
5. 分布式功率训练与预测
6. 校准与最终预测列生成
7. 最终评估指标生成
8. 可视化数据导出
9. 训练后审计
10. manifest 写出
```

入口命令固定为：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml
```

实现要求：

- 每一步必须打印输入文件、输出文件、行数、关键列名。
- 每一步失败必须直接 `raise`，不允许静默回退到旧文件。
- 最终必须生成：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
output/pv_pipeline/predictions/distributed_predictions_final_eval.pkl
output/pv_pipeline/metrics/hourly_nrmse_consistent.csv
output/pv_pipeline/metrics/site_metrics_consistent.csv
output/pv_pipeline/interactive_dashboard/index.json
output/pv_pipeline/manifest.json
```

如果现有代码中最终文件路径不同，可以保留兼容复制，但 `manifest.json` 中必须明确哪一个是正式结果。

---

## 六、最终预测列强约束

在最终评估和可视化导出前新增断言：

```python
def assert_final_prediction_ready(df, pred_col="power_pred_final"):
    if pred_col not in df.columns:
        raise KeyError(f"final prediction column missing: {pred_col}")
    if df[pred_col].isna().all():
        raise ValueError(f"{pred_col} is all NaN")
    if "power_mw" not in df.columns:
        raise KeyError("power_mw missing")
    if "split" not in df.columns:
        raise KeyError("split missing")
```

要求：

- 不允许可视化脚本自动从 `power_pred_final` 回退到 `power_pred_cal`。
- 如果 `power_pred_final` 不存在，直接报错。
- 避免再次出现“页面显示旧预测列”的问题。

---

## 七、训练后自动刷新可视化数据

在 `scripts/run_full_pipeline.py` 的最后强制调用：

```bash
python scripts/export_interactive_dashboard_data.py --config configs/pipeline.yaml
python scripts/check_dashboard_prediction_values_round36.py
```

如果文件名已经不适合 Round36，请改名为：

```text
scripts/check_dashboard_prediction_values.py
```

并修改为通用逻辑：

- 校验 `interactive_dashboard/site_series/*.json` 中的 `actual_mw` 与 `distributed_predictions_final_full.pkl` 的 `power_mw` 一致。
- 校验 `pred_mw` 与 `power_pred_final` 一致。
- 校验 `city_series.json` 等于各站点同时间求和。
- 校验 `index.json` 中的 `generated_at` 晚于最终预测文件修改时间。

验收标准：

```text
actual max_abs_diff <= 1e-9
prediction max_abs_diff <= 1e-9
city aggregation max_abs_diff <= 1e-6
dashboard generated_at >= final prediction mtime
```

---

## 八、清理历史残留与过期文件

新增脚本：

```text
scripts/archive_legacy_round_files.py
```

功能：

1. 新建目录：

```text
archive/round_scripts/
archive/round_docs/
archive/old_outputs/
```

2. 将以下文件移动到归档目录，不直接删除：

```text
scripts/*round*.py
scripts/*Round*.py
scripts/*v15*.py
scripts/*backup*.py
docs/Round*.md
output/pv_pipeline/**/*round*.csv
output/pv_pipeline/**/*before*.pkl
output/pv_pipeline/**/*backup*.pkl
```

3. 但不要移动这些正式文件：

```text
scripts/run_full_pipeline.py
scripts/export_interactive_dashboard_data.py
scripts/metrics_common.py
scripts/common_paths.py
scripts/posttrain_validation.py
scripts/check_dashboard_prediction_values.py
```

4. 移动前输出 dry-run 清单：

```bash
python scripts/archive_legacy_round_files.py --dry-run
```

确认无误后再执行：

```bash
python scripts/archive_legacy_round_files.py --apply
```

要求：

- 不要删除历史文件，只归档。
- 归档后 README 不应再引用 `roundXX` 脚本。
- 主流程不能依赖 archive 内文件。

---

## 九、README 与交付说明修正

修改 `README.md` 或项目说明文档，只保留正式运行方式：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml
python -m http.server 8060
```

访问：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

README 中必须说明：

- 训练入口。
- 最终预测文件。
- 最终指标文件。
- 可视化数据目录。
- NRMSE 计算口径。
- train/valid/test 时间范围。
- 测试集不参与训练、调参和校准。

清理以下不准确内容：

- 不存在的 `scripts/all.py`。
- 不存在的 `scripts/train.py`。
- 旧版本 `fixed/v2/v3/roundXX` 作为正式入口的描述。
- `MAPE/WAPE` 作为主指标的描述。

---

## 十、训练逻辑审计补强

新增或改造：

```text
scripts/posttrain_validation.py
```

必须检查：

1. 时间切分是否正确：

```text
train < valid < test
test_start == 2025-09-01
test_end == 2025-12-31
```

2. 测试集泄漏：

- PR、校准系数、候选选择不得使用 test。
- 如果某个脚本读取 test 指标参与选择，直接 FAIL。

3. 最终预测列：

- `power_pred_final` 存在。
- 非空。
- 不超容量严重异常。
- 夜间/future 不参与正式评估。

4. 指标一致性：

- `hourly_nrmse_consistent.csv` 与 `distributed_predictions_final_eval.pkl` 重算一致。
- `site_metrics_consistent.csv` 与重算一致。
- 可视化页面 JSON 与最终 pkl 一致。

5. 产物新鲜度：

- 最终 pkl 修改时间早于 dashboard JSON，则 PASS。
- dashboard JSON 旧于最终 pkl，则 FAIL。

输出：

```text
output/pv_pipeline/validation/posttrain_validation_report.md
output/pv_pipeline/validation/posttrain_validation_results.csv
```

---

## 十一、针对当前训练逻辑的可提升点

本轮可以先做工程收口；模型提升不建议继续散落到临时 round 脚本中。若要继续提升，应按以下方式正规接入主流程。

### 1. 高误差站点诊断常态化

新增：

```text
scripts/diagnose_site_error_drivers.py
```

输出：

```text
output/pv_pipeline/diagnostics/site_error_drivers.csv
```

字段至少包含：

```text
station_id
station_name
capacity_mw
train_valid_sample_count
train_valid_positive_6_19_count
test_sample_count
test_zero_ratio_6_19
actual_pred_ratio
bias_percent
site_nrmse_percent
capacity_mapping_flag
season_shift_flag
high_zero_flag
possible_curtailment_flag
```

作用：

- 不再只看“数据量多不多”。
- 同时判断容量映射、0 值、季节漂移、偏差方向、限电/遮挡嫌疑。

### 2. 站点偏差校准只用 valid

保留站点级 bias 校准，但必须满足：

- 只用 train/valid。
- test 只评估。
- 校准系数有上下限，例如 `0.8-1.2`。
- 小样本站点向全局系数收缩，避免过拟合。

建议输出：

```text
output/pv_pipeline/calibration/site_bias_calibrator.csv
```

字段：

```text
station_id
valid_actual_sum
valid_pred_sum
raw_factor
shrink_factor
final_factor
sample_count
```

### 3. 中午 10-14 点不再混用多来源

如果继续优化 10-14 点，必须遵守：

- 10-14 点最终预测来源统一，不要 10 点来自 A、11 点来自 B、12 点来自 C。
- 可用 valid 集选择一套“日间模型/校准策略”，然后整段 10-14 统一应用。
- test 不能参与选择。

这样比逐小时拼接更容易解释。

---

## 十二、验收命令

Cursor 修改完成后，依次执行：

```bash
python scripts/run_full_pipeline.py --config configs/pipeline.yaml
python scripts/posttrain_validation.py --config configs/pipeline.yaml
python scripts/check_dashboard_prediction_values.py --config configs/pipeline.yaml
```

如果尚未完成统一入口，临时验收命令为：

```bash
python scripts/export_interactive_dashboard_data.py --config configs/pipeline.yaml
python scripts/posttrain_validation.py --config configs/pipeline.yaml
python scripts/check_dashboard_prediction_values.py --config configs/pipeline.yaml
```

启动可视化：

```bash
python -m http.server 8060
```

浏览器访问：

```text
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

强制刷新：

```text
Ctrl + Shift + R
```

---

## 十三、验收标准

必须全部满足：

1. `run_full_pipeline.py` 能从头跑通。
2. `posttrain_validation.py` 全部 PASS。
3. `check_dashboard_prediction_values.py` 全部 PASS。
4. 可视化页面中：
   - 全市曲线有数据。
   - 单站点曲线有数据。
   - 典型站点按钮可切换。
   - 四季最佳日可切换。
   - 逐小时 NRMSE 表来自最新结果。
   - 样本量与 NRMSE 散点图来自最新结果。
5. `README.md` 只保留正式入口，不再引用过时 round 脚本。
6. 历史 round 文件已移动到 `archive/`，主流程不依赖归档文件。
7. `manifest.json` 中明确记录：
   - 训练时间。
   - 数据时间范围。
   - train/valid/test 范围。
   - 最终预测列。
   - 最终预测文件。
   - 指标文件。
   - 可视化数据目录。

---

## 十四、不要做的事

本轮不要做以下操作：

1. 不要为了单个小时指标继续堆新的 `roundXX` 临时脚本。
2. 不要用 test 集选择模型、校准参数或候选列。
3. 不要让可视化脚本静默回退旧结果。
4. 不要删除历史文件，只归档。
5. 不要同时维护多套 README 入口。
6. 不要在报告里把“辐照估计”写成“实测辐照真值”。

---

## 十五、最终交付说明模板

执行完成后，请生成：

```text
docs/Round50_工程收口与训练逻辑审计执行报告.md
```

内容包括：

```markdown
# Round50 工程收口与训练逻辑审计执行报告

## 1. 本轮修改内容

## 2. 正式训练入口

## 3. 最终产物清单

## 4. 指标口径

## 5. 可视化数据自动更新机制

## 6. 清理归档情况

## 7. 训练后验证结果

## 8. 当前仍需注意的问题
```

其中“当前仍需注意的问题”建议如实写：

- 辐照估计仍缺少独立实测辐照验证。
- 部分站点存在容量映射、异常 0 值、遮挡/限电或数据漂移风险。
- 站点平均 NRMSE 与城市 NRMSE 表示不同层面的误差，不能互相替代。
- 数据量不是唯一决定因素，有效正功率样本、站点质量、容量准确性和分布漂移共同影响精度。

