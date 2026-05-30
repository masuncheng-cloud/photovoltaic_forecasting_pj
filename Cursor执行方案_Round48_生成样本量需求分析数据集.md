# Cursor执行方案 Round48：生成“需要多少数据才能预测较准”的分析数据集

## 目标

为了判断“单站点需要多少有效数据量，预测才能相对精确”，需要先生成一个站点级分析数据集。

本轮不改模型、不重新训练，只从现有训练结果和数据集中提取统计特征，生成可用于分析的 CSV。

输出目标：

```text
output/pv_pipeline/metrics/round48_station_data_requirement_analysis.csv
output/pv_pipeline/docs/Round48_样本量需求分析数据说明.md
```

这个 CSV 后续交给 Codex 分析，用来判断：

- 样本量与 NRMSE 的关系；
- 多少训练样本量更容易达到 NRMSE ≤ 10%、15%、20%；
- 样本多但预测差的原因；
- 样本少但预测还可以的原因；
- 零值、缺失、异常、容量、气象匹配对预测精度的影响。

---

## 一、输入数据优先级

请优先从当前项目最新产物读取数据。

### 1. 最终预测结果

优先读取：

```text
output/pv_pipeline/distributed_predictions_final_full.pkl
```

如果不存在，再查找：

```text
output/pv_pipeline/**/distributed_predictions_final_full.pkl
output/pv_pipeline/**/distributed_predictions_final_eval.pkl
```

要求最终预测列必须是：

```text
power_pred_final
```

如果没有该列，直接报错，不允许回退到 `power_pred_cal`。

### 2. 清洗后功率数据

优先读取：

```text
output/pv_pipeline/power_clean.pkl
```

如果不存在，则从 final pkl 中的实际功率列统计。

### 3. 站点元数据

从 final pkl 或已有站点表中读取：

```text
site_id
site_name
capacity_mw
```

### 4. 气象/辐照数据

如果 final pkl 中已有以下字段，直接使用：

```text
ghi
GHI
irradiance
clear_sky_ghi
temperature
wind_speed
```

如果没有，则气象相关字段填空，并在说明文件中标注“当前产物未包含气象匹配质量字段”。

---

## 二、新增脚本

新建：

```text
scripts/build_station_data_requirement_dataset.py
```

---

## 三、统计口径

### 1. 时间与集合口径

按 `split` 分为：

```text
train
valid
test
```

如果没有 `split` 字段，根据项目当前切分日期补充推断；但必须在说明文件中写明推断规则。

样本量统计分为：

- 全量历史样本：`train + valid + test`，不含 `future`
- 训练+验证样本：`train + valid`，不含 `test` 和 `future`
- 测试样本：`test`
- 白天样本：小时 `6-19`
- 中午样本：小时 `10-14`

### 2. 正功率与 0 值口径

正功率样本：

```text
power_mw > 0
```

0 值样本：

```text
power_mw == 0
```

如果有负功率或缺失：

- 负功率计入异常；
- 缺失计入缺失；
- 不要把缺失当作 0。

### 3. 误差口径

测试集 6-19 点：

```text
error = power_pred_final - power_mw
MAE = mean(abs(error))
RMSE = sqrt(mean(error^2))
NRMSE = RMSE / capacity_mw * 100
BIAS = sum(error) / sum(power_mw) * 100
pred_actual = sum(power_pred_final) / sum(power_mw)
```

测试集 10-14 点同样计算：

```text
test_10_14_mae_mw
test_10_14_rmse_mw
test_10_14_nrmse_pct
test_10_14_bias_pct
```

逐小时 NRMSE：

对每个站点、每个小时 `6-19` 单独计算：

```text
hour_h_nrmse_pct = RMSE(site, hour h) / capacity_mw * 100
```

字段命名：

```text
nrmse_h06_pct
nrmse_h07_pct
...
nrmse_h19_pct
```

---

## 四、输出字段

CSV 每个站点一行，至少包含以下字段：

```text
site_id
site_name
capacity_mw

history_samples_total
history_samples_6_19
history_positive_samples_6_19
history_zero_ratio_6_19

train_samples_6_19
valid_samples_6_19
test_samples_6_19
train_valid_samples_6_19
train_valid_positive_samples_6_19
train_valid_zero_ratio_6_19

test_positive_samples_6_19
test_zero_ratio_6_19
test_missing_ratio_6_19
test_negative_ratio_6_19

train_valid_samples_10_14
train_valid_positive_samples_10_14
test_samples_10_14
test_positive_samples_10_14
test_zero_ratio_10_14

test_mae_mw
test_rmse_mw
test_nrmse_pct
test_bias_pct
test_pred_actual

test_10_14_mae_mw
test_10_14_rmse_mw
test_10_14_nrmse_pct
test_10_14_bias_pct

nrmse_h06_pct
nrmse_h07_pct
nrmse_h08_pct
nrmse_h09_pct
nrmse_h10_pct
nrmse_h11_pct
nrmse_h12_pct
nrmse_h13_pct
nrmse_h14_pct
nrmse_h15_pct
nrmse_h16_pct
nrmse_h17_pct
nrmse_h18_pct
nrmse_h19_pct

ghi_power_corr
weather_missing_ratio

capacity_changed_flag
suspected_curtailment_flag
mapping_issue_flag
all_zero_or_invalid_flag
```

如果某些字段暂时无法计算：

- 字段仍保留；
- 值填空；
- 在说明文件中写清楚原因。

---

## 五、推荐脚本实现框架

```python
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pv_pipeline"
METRICS = OUT / "metrics"
DOCS = OUT / "docs"


def find_final_pkl():
    candidates = [
        OUT / "distributed_predictions_final_full.pkl",
        OUT / "distributed_predictions_final_eval.pkl",
    ]
    candidates += list(OUT.rglob("*distributed_predictions_final_full.pkl"))
    candidates += list(OUT.rglob("*distributed_predictions_final_eval.pkl"))
    candidates = [p for p in candidates if p.exists()]
    if not candidates:
        raise FileNotFoundError("找不到 distributed_predictions_final_full/eval.pkl")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def normalize_columns(df):
    if "timestamp" not in df.columns:
        for c in ["time", "datetime", "date_time"]:
            if c in df.columns:
                df = df.rename(columns={c: "timestamp"})
                break
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["hour"] = df["timestamp"].dt.hour
    return df


def safe_ratio(num, den):
    return np.nan if den == 0 or pd.isna(den) else num / den


def rmse(x):
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return np.nan
    return float(np.sqrt(np.mean(x ** 2)))


def calc_metrics(g, capacity):
    y = g["power_mw"].astype(float)
    p = g["power_pred_final"].astype(float)
    err = p - y
    out = {}
    out["mae_mw"] = float(np.mean(np.abs(err))) if len(g) else np.nan
    out["rmse_mw"] = rmse(err) if len(g) else np.nan
    out["nrmse_pct"] = safe_ratio(out["rmse_mw"], capacity) * 100 if pd.notna(capacity) else np.nan
    out["bias_pct"] = safe_ratio(float(err.sum()), float(y.sum())) * 100 if float(y.sum()) != 0 else np.nan
    out["pred_actual"] = safe_ratio(float(p.sum()), float(y.sum())) if float(y.sum()) != 0 else np.nan
    return out


def main():
    METRICS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)

    final_pkl = find_final_pkl()
    df = pd.read_pickle(final_pkl)
    df = normalize_columns(df)

    required = {"site_id", "power_mw", "power_pred_final", "capacity_mw"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"缺少必要字段: {missing}")

    if "split" not in df.columns:
        raise ValueError("缺少 split 字段，请先补充 train/valid/test/future 切分口径")

    df = df[df["split"] != "future"].copy()
    day = df[df["hour"].between(6, 19)].copy()
    noon = df[df["hour"].between(10, 14)].copy()

    rows = []
    for site_id, g in df.groupby("site_id"):
        row = {"site_id": site_id}
        row["site_name"] = g["site_name"].dropna().iloc[0] if "site_name" in g.columns and g["site_name"].notna().any() else site_id
        capacity = float(g["capacity_mw"].dropna().median()) if g["capacity_mw"].notna().any() else np.nan
        row["capacity_mw"] = capacity

        gd = day[day["site_id"] == site_id]
        gn = noon[noon["site_id"] == site_id]

        row["history_samples_total"] = int(len(g))
        row["history_samples_6_19"] = int(len(gd))
        row["history_positive_samples_6_19"] = int((gd["power_mw"] > 0).sum())
        row["history_zero_ratio_6_19"] = safe_ratio(int((gd["power_mw"] == 0).sum()), len(gd)) * 100 if len(gd) else np.nan

        for split in ["train", "valid", "test"]:
            s = gd[gd["split"] == split]
            row[f"{split}_samples_6_19"] = int(len(s))

        tv = gd[gd["split"].isin(["train", "valid"])]
        te = gd[gd["split"] == "test"]
        row["train_valid_samples_6_19"] = int(len(tv))
        row["train_valid_positive_samples_6_19"] = int((tv["power_mw"] > 0).sum())
        row["train_valid_zero_ratio_6_19"] = safe_ratio(int((tv["power_mw"] == 0).sum()), len(tv)) * 100 if len(tv) else np.nan
        row["test_positive_samples_6_19"] = int((te["power_mw"] > 0).sum())
        row["test_zero_ratio_6_19"] = safe_ratio(int((te["power_mw"] == 0).sum()), len(te)) * 100 if len(te) else np.nan
        row["test_missing_ratio_6_19"] = safe_ratio(int(te["power_mw"].isna().sum()), len(te)) * 100 if len(te) else np.nan
        row["test_negative_ratio_6_19"] = safe_ratio(int((te["power_mw"] < 0).sum()), len(te)) * 100 if len(te) else np.nan

        tv_noon = gn[gn["split"].isin(["train", "valid"])]
        te_noon = gn[gn["split"] == "test"]
        row["train_valid_samples_10_14"] = int(len(tv_noon))
        row["train_valid_positive_samples_10_14"] = int((tv_noon["power_mw"] > 0).sum())
        row["test_samples_10_14"] = int(len(te_noon))
        row["test_positive_samples_10_14"] = int((te_noon["power_mw"] > 0).sum())
        row["test_zero_ratio_10_14"] = safe_ratio(int((te_noon["power_mw"] == 0).sum()), len(te_noon)) * 100 if len(te_noon) else np.nan

        m = calc_metrics(te, capacity)
        row["test_mae_mw"] = m["mae_mw"]
        row["test_rmse_mw"] = m["rmse_mw"]
        row["test_nrmse_pct"] = m["nrmse_pct"]
        row["test_bias_pct"] = m["bias_pct"]
        row["test_pred_actual"] = m["pred_actual"]

        mn = calc_metrics(te_noon, capacity)
        row["test_10_14_mae_mw"] = mn["mae_mw"]
        row["test_10_14_rmse_mw"] = mn["rmse_mw"]
        row["test_10_14_nrmse_pct"] = mn["nrmse_pct"]
        row["test_10_14_bias_pct"] = mn["bias_pct"]

        for h in range(6, 20):
            gh = te[te["hour"] == h]
            mh = calc_metrics(gh, capacity)
            row[f"nrmse_h{h:02d}_pct"] = mh["nrmse_pct"]

        # 气象相关性：优先找 GHI 类字段
        ghi_col = next((c for c in ["ghi", "GHI", "irradiance", "clear_sky_ghi"] if c in gd.columns), None)
        if ghi_col and gd[ghi_col].notna().sum() > 10 and gd["power_mw"].notna().sum() > 10:
            row["ghi_power_corr"] = gd[[ghi_col, "power_mw"]].corr().iloc[0, 1]
            row["weather_missing_ratio"] = safe_ratio(int(gd[ghi_col].isna().sum()), len(gd)) * 100 if len(gd) else np.nan
        else:
            row["ghi_power_corr"] = np.nan
            row["weather_missing_ratio"] = np.nan

        # 旗标：先用可直接从数据判断的规则
        row["capacity_changed_flag"] = int(g["capacity_mw"].dropna().nunique() > 1)
        row["suspected_curtailment_flag"] = np.nan
        row["mapping_issue_flag"] = np.nan
        row["all_zero_or_invalid_flag"] = int(row["history_positive_samples_6_19"] == 0)

        rows.append(row)

    out = pd.DataFrame(rows)
    out_path = METRICS / "round48_station_data_requirement_analysis.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")

    doc_path = DOCS / "Round48_样本量需求分析数据说明.md"
    doc_path.write_text(
        f"""# Round48 样本量需求分析数据说明

生成文件：`{out_path}`

数据来源：`{final_pkl}`

统计口径：

- 不包含 `future`。
- 历史样本 = train + valid + test。
- 白天样本 = 6-19 点。
- 中午样本 = 10-14 点。
- 正功率样本 = power_mw > 0。
- NRMSE = RMSE / capacity_mw * 100%。
- 测试误差只使用 test 集。

注意：

- `suspected_curtailment_flag` 和 `mapping_issue_flag` 当前需要额外规则或人工标注，若无可靠来源则保留为空。
- 如果气象字段不存在，`ghi_power_corr` 和 `weather_missing_ratio` 为空。

站点数：{len(out)}
""",
        encoding="utf-8",
    )

    print(f"[PASS] wrote {out_path}")
    print(f"[PASS] wrote {doc_path}")


if __name__ == "__main__":
    main()
```

---

## 六、执行命令

在项目根目录执行：

```bash
python scripts/build_station_data_requirement_dataset.py
```

执行完成后检查：

```bash
python - <<'PY'
import pandas as pd
p='output/pv_pipeline/metrics/round48_station_data_requirement_analysis.csv'
df=pd.read_csv(p)
print(df.shape)
print(df[['site_id','site_name','train_valid_samples_6_19','train_valid_positive_samples_6_19','test_nrmse_pct','test_10_14_nrmse_pct']].head(10))
print(df[['train_valid_samples_6_19','train_valid_positive_samples_6_19','test_nrmse_pct']].describe())
PY
```

---

## 七、验收标准

### 1. CSV 必须生成

```text
output/pv_pipeline/metrics/round48_station_data_requirement_analysis.csv
```

### 2. 每个站点一行

站点数量应接近当前有效站点规模，例如 68 左右。

### 3. 必须包含关键字段

至少确认这些字段存在：

```text
site_id
site_name
capacity_mw
train_valid_samples_6_19
train_valid_positive_samples_6_19
train_valid_zero_ratio_6_19
test_zero_ratio_6_19
test_mae_mw
test_rmse_mw
test_nrmse_pct
test_10_14_nrmse_pct
nrmse_h10_pct
nrmse_h11_pct
nrmse_h12_pct
nrmse_h13_pct
nrmse_h14_pct
```

### 4. 不允许出现旧预测列

如果 final pkl 中没有 `power_pred_final`，脚本必须失败，不允许自动改用：

```text
power_pred_cal
power_pred_raw
```

---

## 八、给 Codex 的交付文件

执行完成后，把以下文件发给 Codex：

```text
output/pv_pipeline/metrics/round48_station_data_requirement_analysis.csv
output/pv_pipeline/docs/Round48_样本量需求分析数据说明.md
```

如果气象字段无法统计，也一并说明当前 final pkl 是否包含 GHI 或辐照字段。

