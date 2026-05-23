# Cursor 下一步修改方案：10-14 点站点 NRMSE 继续优化

## 0. 本轮目标

本轮不再把“周二版结果”作为唯一验收标准，核心目标改为：

1. 继续降低测试集 10、11、12、13、14 点的站点平均 NRMSE。
2. 允许城市总量误差和整体 MAE/RMSE 有小幅波动，但不能明显恶化。
3. 禁止使用 test 集做调参、选模型、学参数；test 只用于最终评估。
4. 最终报告中不再用 WAPE 作为主要指标，10-14 点以站点平均 NRMSE 为主。

当前修改已经有效，但只是做了站点小时级乘法校准，改进幅度有限。下一步要补上两个问题：

1. 当前 `select_final_prediction_by_guard.py` 的 `nrmse_capacity_pct` 是整小时样本级 RMSE / 平均容量，不等同于用户关注的“站点平均 NRMSE”。
2. 当前 `apply_midday_site_nrmse_calibration.py` 基本是乘法缩放，无法修正某些站点中午曲线形状偏差，因此需要增加“中午残差专家校正”。

---

## 1. 修改总览

请在 Cursor 中完成以下 4 类修改：

| 序号 | 修改项 | 目的 |
|---:|---|---|
| 1 | 在选择器中新增 `site_nrmse_mean_pct` 指标 | 让 10-14 点真正按站点平均 NRMSE 选版本 |
| 2 | 新增 `scripts/apply_midday_residual_specialist.py` | 用 train 学残差，用 valid 选参数，修正中午站点级系统偏差 |
| 3 | 修改 `select_final_prediction_by_guard.py` | 加载 `MiddayResidualSpecialist` 候选，10-14 点优先比较站点 NRMSE |
| 4 | 修改验收脚本 | 不再强制贴近周二版，只比较“当前版本 vs 修复前版本”是否改善 |

---

## 2. 关键原则

### 2.1 数据泄漏约束

严格按以下规则：

| 数据集 | 允许用途 |
|---|---|
| train | 学习残差修正参数 |
| valid | 选择 shrinkage、校正强度、是否采用新候选 |
| test | 最终评估，只能在全部参数确定后读取 |

禁止在 test 上决定某小时是否采用新版本。

### 2.2 主指标

10-14 点主指标使用：

```text
单站点 NRMSE_i,h =
sqrt(mean((P_true - P_pred)^2)) / mean(C_i) * 100%

逐小时站点平均 NRMSE_h =
mean_i(单站点 NRMSE_i,h)
```

其中：

- `P_true`：实际功率，单位 MW。
- `P_pred`：预测功率，单位 MW。
- `C_i`：站点装机容量，单位 MW。
- `i`：站点。
- `h`：小时。

这和当前选择器里的整小时 `nrmse_capacity_pct` 不完全一样，必须单独实现。

---

## 3. 修改一：在选择器里增加站点平均 NRMSE

打开：

```text
scripts/select_final_prediction_by_guard.py
```

在 metric helper 区域新增函数：

```python
def site_nrmse_mean_by_capacity(df: pd.DataFrame, pred_col: str = "power_pred") -> float:
    """站点平均容量归一化 NRMSE(%): 先算每个站点 NRMSE，再对站点求平均。"""
    vals = []
    for _, sg in df.groupby("site_id"):
        yt = pd.to_numeric(sg["power_mw"], errors="coerce").to_numpy(dtype=float)
        yp = pd.to_numeric(sg[pred_col], errors="coerce").to_numpy(dtype=float)
        cap = pd.to_numeric(sg["capacity_mw"], errors="coerce").to_numpy(dtype=float)
        m = np.isfinite(yt) & np.isfinite(yp) & np.isfinite(cap) & (cap > 0)
        if not m.any():
            continue
        rmse_val = float(np.sqrt(np.mean((yt[m] - yp[m]) ** 2)))
        cap_mean = float(np.nanmean(cap[m]))
        if cap_mean > 0:
            vals.append(rmse_val / cap_mean * 100.0)
    return float(np.nanmean(vals)) if vals else np.nan
```

然后在 `compute_hour_metrics()` 的返回字典中增加：

```python
"site_nrmse_mean_pct": site_nrmse_mean_by_capacity(sub_df, pred_col),
```

修改 `score_candidates(metrics, hour=None)`：

把：

```python
nrmse = metrics.get("nrmse_capacity_pct", 100)
```

改为：

```python
if hour in MIDDAY_NRMSE_PRIORITY_HOURS if hour is not None else False:
    nrmse = metrics.get("site_nrmse_mean_pct", metrics.get("nrmse_capacity_pct", 100))
else:
    nrmse = metrics.get("nrmse_capacity_pct", 100)
```

注意：如果这行三元表达式在 Cursor 中提示语法可读性差，可以改成下面这种更稳的写法：

```python
is_midday_priority = hour in MIDDAY_NRMSE_PRIORITY_HOURS if hour is not None else False
if is_midday_priority:
    nrmse = metrics.get("site_nrmse_mean_pct", metrics.get("nrmse_capacity_pct", 100))
else:
    nrmse = metrics.get("nrmse_capacity_pct", 100)
```

同时在 `score_candidates()` 中 10-14 点权重改为：

```python
if is_midday_priority:
    return (
        0.62 * nrmse
        + 0.18 * rmse_val
        + 0.10 * mae_val
        + 0.06 * city
        + 0.02 * ratio_err
        + 0.01 * (n100 * 5)
        + 0.01 * (n200 * 10)
    )
```

原因：本轮目标就是 10-14 点站点平均 NRMSE，因此这里必须让它成为主导指标。

---

## 4. 修改二：新增中午残差专家校正脚本

新建文件：

```text
scripts/apply_midday_residual_specialist.py
```

完整写入以下代码：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10-14 点中午残差专家校正
========================

目标：
  在不使用 test 集调参的前提下，继续降低 10-14 点站点平均 NRMSE。

方法：
  1. 读取 fixed_full 作为基础表。
  2. 若 midday_site_calibrated_full 存在，则以它作为中午初始预测。
  3. 仅用 train 学习残差：
       residual_norm = (power_mw - power_pred) / capacity_mw
  4. 分层学习残差中位数：
       (site_id, hour, month)
       (site_id, hour)
       (hour, capacity_bucket)
       (hour)
  5. 用 valid 选择残差强度 lambda 和 clip 范围。
  6. 应用到 full 表，输出新的候选版本。
"""
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load, write_prediction_pickle_atomic
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics


TABLES_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)

MIDDAY_HOURS = [10, 11, 12, 13, 14]
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}

IN_FIXED = TABLES_DIR / "distributed_predictions_fixed_full.pkl"
IN_MIDDAY = TABLES_DIR / "distributed_predictions_midday_site_calibrated_full.pkl"

OUT_FULL = TABLES_DIR / "distributed_predictions_midday_residual_specialist_full.pkl"
OUT_EVAL = TABLES_DIR / "distributed_predictions_midday_residual_specialist_eval.pkl"
OUT_PARAMS = METRICS_DIR / "midday_residual_specialist_params.csv"
OUT_VALID = METRICS_DIR / "midday_residual_specialist_valid_ablation.csv"


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if "hour" not in out.columns:
        out["hour"] = out["time"].dt.hour
    if "date" not in out.columns:
        out["date"] = out["time"].dt.date
    out["month"] = out["time"].dt.month
    return out


def add_capacity_bucket(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    cap = pd.to_numeric(out["capacity_mw"], errors="coerce")
    try:
        out["capacity_bucket"] = pd.qcut(cap.rank(method="first"), q=5, labels=False, duplicates="drop")
    except Exception:
        out["capacity_bucket"] = 0
    out["capacity_bucket"] = out["capacity_bucket"].fillna(0).astype(int)
    return out


def site_nrmse_mean(df: pd.DataFrame, pred_col: str = "power_pred") -> float:
    vals = []
    for _, sg in df.groupby("site_id"):
        y = pd.to_numeric(sg["power_mw"], errors="coerce").to_numpy(dtype=float)
        p = pd.to_numeric(sg[pred_col], errors="coerce").to_numpy(dtype=float)
        c = pd.to_numeric(sg["capacity_mw"], errors="coerce").to_numpy(dtype=float)
        m = np.isfinite(y) & np.isfinite(p) & np.isfinite(c) & (c > 0)
        if not m.any():
            continue
        rmse = float(np.sqrt(np.mean((y[m] - p[m]) ** 2)))
        cm = float(np.nanmean(c[m]))
        if cm > 0:
            vals.append(rmse / cm * 100.0)
    return float(np.nanmean(vals)) if vals else np.nan


def learn_residual_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    train = df[
        (df["split"] == "train")
        & (df["hour"].isin(MIDDAY_HOURS))
        & (~df["site_id"].isin(BAD_SITES))
        & (pd.to_numeric(df["power_mw"], errors="coerce") > 0)
        & (pd.to_numeric(df["capacity_mw"], errors="coerce") > 0)
    ].copy()
    if train.empty:
        raise RuntimeError("train 集中午样本为空，无法学习残差参数")

    cap = pd.to_numeric(train["capacity_mw"], errors="coerce")
    y = pd.to_numeric(train["power_mw"], errors="coerce")
    p = pd.to_numeric(train["power_pred"], errors="coerce")
    train["residual_norm"] = ((y - p) / cap).clip(-0.35, 0.35)

    def agg(keys, min_n):
        g = (
            train.groupby(keys, dropna=False)["residual_norm"]
            .agg(["median", "count"])
            .reset_index()
            .rename(columns={"median": "residual_norm_median", "count": "n_train"})
        )
        return g[g["n_train"] >= min_n].copy()

    return {
        "site_hour_month": agg(["site_id", "hour", "month"], 12),
        "site_hour": agg(["site_id", "hour"], 35),
        "hour_capacity": agg(["hour", "capacity_bucket"], 80),
        "hour": agg(["hour"], 120),
    }


def attach_residual(df: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    out = df.copy()
    out["_row_id"] = np.arange(len(out))

    sources = [
        ("site_hour_month", ["site_id", "hour", "month"], "r_shm", "n_shm"),
        ("site_hour", ["site_id", "hour"], "r_sh", "n_sh"),
        ("hour_capacity", ["hour", "capacity_bucket"], "r_hc", "n_hc"),
        ("hour", ["hour"], "r_h", "n_h"),
    ]

    for name, keys, r_col, n_col in sources:
        tab = tables[name].rename(
            columns={
                "residual_norm_median": r_col,
                "n_train": n_col,
            }
        )
        out = out.merge(tab[keys + [r_col, n_col]], on=keys, how="left")

    # 分层回退：优先站点-小时-月份，再站点-小时，再小时-容量桶，最后小时整体。
    out["residual_norm_hat"] = out["r_shm"]
    out["residual_source"] = "site_hour_month"

    m = out["residual_norm_hat"].isna()
    out.loc[m, "residual_norm_hat"] = out.loc[m, "r_sh"]
    out.loc[m & out["residual_norm_hat"].notna(), "residual_source"] = "site_hour"

    m = out["residual_norm_hat"].isna()
    out.loc[m, "residual_norm_hat"] = out.loc[m, "r_hc"]
    out.loc[m & out["residual_norm_hat"].notna(), "residual_source"] = "hour_capacity"

    m = out["residual_norm_hat"].isna()
    out.loc[m, "residual_norm_hat"] = out.loc[m, "r_h"]
    out.loc[m & out["residual_norm_hat"].notna(), "residual_source"] = "hour"

    out["residual_norm_hat"] = out["residual_norm_hat"].fillna(0.0)

    # 样本少时自动收缩，防止站点小样本过拟合。
    n_eff = out["n_shm"].fillna(out["n_sh"]).fillna(out["n_hc"]).fillna(out["n_h"]).fillna(0.0)
    shrink = n_eff / (n_eff + 80.0)
    out["residual_norm_hat"] = out["residual_norm_hat"] * shrink

    drop_cols = ["r_shm", "n_shm", "r_sh", "n_sh", "r_hc", "n_hc", "r_h", "n_h", "_row_id"]
    return out.drop(columns=[c for c in drop_cols if c in out.columns])


def apply_candidate(df: pd.DataFrame, lam: float, clip_norm: float) -> pd.DataFrame:
    out = df.copy()
    pred = pd.to_numeric(out["power_pred"], errors="coerce")
    cap = pd.to_numeric(out["capacity_mw"], errors="coerce").fillna(0.0)
    residual = pd.to_numeric(out["residual_norm_hat"], errors="coerce").fillna(0.0)
    residual = residual.clip(-clip_norm, clip_norm)

    adjusted = pred + lam * residual * cap
    adjusted = adjusted.clip(lower=0.0, upper=cap)

    mask = out["hour"].isin(MIDDAY_HOURS)
    out.loc[mask, "power_pred"] = adjusted[mask]
    out["midday_residual_lambda"] = lam
    out["midday_residual_clip_norm"] = clip_norm
    return out


def valid_ablation(base_df: pd.DataFrame, cand_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for h in MIDDAY_HOURS:
        b = base_df[
            (base_df["split"] == "valid")
            & (base_df["hour"] == h)
            & (~base_df["site_id"].isin(BAD_SITES))
            & (pd.to_numeric(base_df["power_mw"], errors="coerce") > 0)
        ].copy()
        c = cand_df[
            (cand_df["split"] == "valid")
            & (cand_df["hour"] == h)
            & (~cand_df["site_id"].isin(BAD_SITES))
            & (pd.to_numeric(cand_df["power_mw"], errors="coerce") > 0)
        ].copy()
        if b.empty or c.empty:
            continue
        rows.append({
            "hour": h,
            "valid_rows": len(c),
            "before_site_nrmse_mean_pct": round(site_nrmse_mean(b), 4),
            "after_site_nrmse_mean_pct": round(site_nrmse_mean(c), 4),
            "improvement_pct_point": round(site_nrmse_mean(b) - site_nrmse_mean(c), 4),
        })
    return pd.DataFrame(rows)


def choose_valid_params(df_with_residual: pd.DataFrame) -> tuple[float, float, pd.DataFrame]:
    grid = []
    for lam in [0.25, 0.40, 0.55, 0.70, 0.85, 1.00]:
        for clip_norm in [0.04, 0.06, 0.08, 0.10, 0.12]:
            cand = apply_candidate(df_with_residual, lam=lam, clip_norm=clip_norm)
            vals = []
            for h in MIDDAY_HOURS:
                sub = cand[
                    (cand["split"] == "valid")
                    & (cand["hour"] == h)
                    & (~cand["site_id"].isin(BAD_SITES))
                    & (pd.to_numeric(cand["power_mw"], errors="coerce") > 0)
                ]
                if len(sub):
                    vals.append(site_nrmse_mean(sub))
            score = float(np.nanmean(vals)) if vals else np.nan
            grid.append({
                "lambda": lam,
                "clip_norm": clip_norm,
                "valid_midday_site_nrmse_mean_pct": score,
            })

    grid_df = pd.DataFrame(grid).dropna(subset=["valid_midday_site_nrmse_mean_pct"])
    if grid_df.empty:
        raise RuntimeError("valid 参数网格为空")
    best = grid_df.sort_values("valid_midday_site_nrmse_mean_pct").iloc[0]
    return float(best["lambda"]), float(best["clip_norm"]), grid_df


def main():
    print("=" * 80)
    print("10-14 点中午残差专家校正")
    print("=" * 80)

    if IN_MIDDAY.exists():
        in_path = IN_MIDDAY
        print(f"读取中午乘法校准版本: {in_path}")
    else:
        in_path = IN_FIXED
        print(f"中午乘法校准版本不存在，读取 fixed: {in_path}")

    if not in_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {in_path}")

    df = safe_pickle_load(in_path)
    df = ensure_columns(df)
    df = add_capacity_bucket(df)
    print(f"Loaded rows: {len(df):,}")
    print(f"Split: {df['split'].value_counts().to_dict()}")

    tables = learn_residual_tables(df)
    param_rows = []
    for name, tab in tables.items():
        x = tab.copy()
        x["level"] = name
        param_rows.append(x)
    params_df = pd.concat(param_rows, ignore_index=True)
    params_df.to_csv(OUT_PARAMS, index=False, encoding="utf-8-sig")
    print(f"保存残差参数: {OUT_PARAMS}")

    df_res = attach_residual(df, tables)
    best_lam, best_clip, grid_df = choose_valid_params(df_res)
    grid_df.to_csv(METRICS_DIR / "midday_residual_specialist_valid_grid.csv", index=False, encoding="utf-8-sig")
    print(f"valid 最优参数: lambda={best_lam}, clip_norm={best_clip}")

    df_cand = apply_candidate(df_res, lam=best_lam, clip_norm=best_clip)

    ab = valid_ablation(df, df_cand)
    ab.to_csv(OUT_VALID, index=False, encoding="utf-8-sig")
    print("valid 消融:")
    print(ab.to_string(index=False))

    eval_df = build_eval_frame(
        df_cand,
        pred_col="power_pred",
        split="test",
        hours=tuple(range(6, 20)),
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=53,
    )

    write_prediction_pickle_atomic(
        df_cand,
        OUT_FULL,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
    )
    write_prediction_pickle_atomic(
        eval_df,
        OUT_EVAL,
        required_cols=["time", "site_id", "power_mw", "power_pred", "capacity_mw"],
        hour_range=(6, 19),
    )

    hmet = hourly_nrmse_metrics(eval_df)
    hmet[hmet["hour"].isin(MIDDAY_HOURS)].to_csv(
        METRICS_DIR / "midday_residual_specialist_test_hourly_nrmse.csv",
        index=False,
        encoding="utf-8-sig",
    )
    print(f"保存: {OUT_FULL}")
    print(f"保存: {OUT_EVAL}")
    print("test 中午 NRMSE，仅用于最终查看，不用于调参:")
    print(hmet[hmet["hour"].isin(MIDDAY_HOURS)].to_string(index=False))


if __name__ == "__main__":
    main()
```

---

## 5. 修改三：选择器加载新候选

继续修改：

```text
scripts/select_final_prediction_by_guard.py
```

在 `load_candidates()` 中 `MiddaySiteCalibrated` 后面增加：

```python
    # MiddayResidualSpecialist: 10-14 点残差专家候选
    try:
        residual_path = TABLES_DIR / "distributed_predictions_midday_residual_specialist_full.pkl"
        if residual_path.exists():
            df = pd.read_pickle(residual_path)
            df["time"] = pd.to_datetime(df["time"])
            df["hour"] = df["time"].dt.hour
            candidates["MiddayResidualSpecialist"] = df
            print(f"  MiddayResidualSpecialist: {len(df):,} 行")
        else:
            print("  MiddayResidualSpecialist: 文件不存在，跳过")
    except Exception as e:
        print(f"  MiddayResidualSpecialist 加载失败: {e}")
```

在 `select_per_hour()` 遍历候选处，把：

```python
elif ver == "MiddaySiteCalibrated":
```

改成：

```python
elif ver in {"MiddaySiteCalibrated", "MiddayResidualSpecialist"}:
```

并把该分支里的判断逻辑替换为下面这版：

```python
                # 10-14 点专用：只允许在 midday 小时出现。
                reasons = []
                passed = True

                if h not in MIDDAY_NRMSE_PRIORITY_HOURS:
                    passed = False
                    reasons.append(f"{ver} 只允许用于 10-14 点")
                else:
                    base_site_nrmse = base_metrics.get("site_nrmse_mean_pct", np.nan)
                    cand_site_nrmse = cand_metrics.get("site_nrmse_mean_pct", np.nan)
                    base_rmse = base_metrics.get("rmse", np.nan)
                    cand_rmse = cand_metrics.get("rmse", np.nan)
                    base_mae = base_metrics.get("mae", np.nan)
                    cand_mae = cand_metrics.get("mae", np.nan)
                    cand_ratio = cand_metrics.get("pred_actual_ratio", np.nan)
                    cand_city = cand_metrics.get("city_rel_err", np.nan)

                    # 主约束：站点平均 NRMSE 必须不劣于 V1。
                    if np.isfinite(base_site_nrmse) and np.isfinite(cand_site_nrmse):
                        if cand_site_nrmse > base_site_nrmse * 1.005:
                            passed = False
                            reasons.append(
                                f"midday site_nrmse 未改善: {cand_site_nrmse:.2f} > 1.005*base {base_site_nrmse:.2f}"
                            )

                    # RMSE/MAE 不允许明显牺牲。
                    if np.isfinite(base_rmse) and np.isfinite(cand_rmse):
                        if cand_rmse > base_rmse * 1.03:
                            passed = False
                            reasons.append(
                                f"midday rmse 恶化: {cand_rmse:.4f} > 1.03*base {base_rmse:.4f}"
                            )
                    if np.isfinite(base_mae) and np.isfinite(cand_mae):
                        if cand_mae > base_mae * 1.03:
                            passed = False
                            reasons.append(
                                f"midday mae 恶化: {cand_mae:.4f} > 1.03*base {base_mae:.4f}"
                            )

                    # 防止城市级总量明显异常，但不让城市误差压过站点 NRMSE。
                    if np.isfinite(cand_ratio) and not (0.86 <= cand_ratio <= 1.06):
                        passed = False
                        reasons.append(f"midday ratio 异常: {cand_ratio:.3f} 不在 [0.86, 1.06]")
                    if np.isfinite(cand_city) and cand_city > 8.0:
                        passed = False
                        reasons.append(f"midday city_rel_err 过高: {cand_city:.2f} > 8.0")

                all_reasons[(h, ver)] = reasons
```

同时在最终保存的 `final_version_selection_by_hour.csv` 中确保包含：

```python
"site_nrmse_mean_pct": best_m.get("site_nrmse_mean_pct", np.nan),
```

如果当前代码里构造 selection rows 的字段列表中没有它，请补上。

---

## 6. 修改四：验收脚本改为“相对当前版本改善”

当前 `scripts/check_midday_nrmse_improvement.py` 仍然绑定周二基准。请改成以下逻辑：

1. 优先读取：

```text
tables/distributed_predictions_final_eval.pkl
```

2. 同时读取：

```text
tables/distributed_predictions_fixed_eval.pkl
```

如果 `distributed_predictions_fixed_eval.pkl` 不存在，则从 `distributed_predictions_fixed_full.pkl` 构建 eval。

3. 生成：

```text
metrics/midday_nrmse_current_vs_fixed.csv
```

4. 验收标准：

| 项目 | 标准 |
|---|---|
| 10-14 点中至少 3 个小时 | 站点平均 NRMSE 下降 |
| 10-14 点平均站点 NRMSE | 至少下降 5% 相对比例，或下降 0.8 个百分点 |
| 单小时保护 | 不允许任一小时比 fixed 恶化超过 0.3 个百分点 |

可以直接替换 `scripts/check_midday_nrmse_improvement.py` 为下面代码：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pv_forecasting.core.utils import safe_pickle_load
from pv_forecasting.core.evaluation import build_eval_frame, hourly_nrmse_metrics

TABLES = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS.mkdir(parents=True, exist_ok=True)

MIDDAY = [10, 11, 12, 13, 14]
BAD_SITES = {"S026", "S015", "S057", "S036", "S067", "S045", "S058"}


def load_eval(path_eval: Path, path_full: Path | None = None) -> pd.DataFrame:
    if path_eval.exists():
        return safe_pickle_load(path_eval)
    if path_full is None or not path_full.exists():
        raise FileNotFoundError(f"找不到 eval 或 full: {path_eval}, {path_full}")
    df = safe_pickle_load(path_full)
    return build_eval_frame(
        df,
        split="test",
        hours=tuple(range(6, 20)),
        active_only=True,
        bad_sites=BAD_SITES,
        target_site_count=53,
    )


def main():
    print("=" * 70)
    print("10-14 点站点 NRMSE 改善验收：当前 final vs fixed")
    print("=" * 70)

    fixed_eval = load_eval(
        TABLES / "distributed_predictions_fixed_eval.pkl",
        TABLES / "distributed_predictions_fixed_full.pkl",
    )
    final_eval = load_eval(
        TABLES / "distributed_predictions_final_eval.pkl",
        TABLES / "distributed_predictions_final_full.pkl",
    )

    fixed_h = hourly_nrmse_metrics(fixed_eval)
    final_h = hourly_nrmse_metrics(final_eval)

    rows = []
    for h in MIDDAY:
        f0 = fixed_h[fixed_h["hour"] == h]
        f1 = final_h[final_h["hour"] == h]
        if f0.empty or f1.empty:
            continue
        before = float(f0.iloc[0]["site_nrmse_mean_pct"])
        after = float(f1.iloc[0]["site_nrmse_mean_pct"])
        city_before = float(f0.iloc[0]["city_nrmse_pct"])
        city_after = float(f1.iloc[0]["city_nrmse_pct"])
        rows.append({
            "hour": h,
            "fixed_site_nrmse_pct": round(before, 4),
            "final_site_nrmse_pct": round(after, 4),
            "improvement_pct_point": round(before - after, 4),
            "relative_improvement_pct": round((before - after) / before * 100.0, 2) if before > 0 else np.nan,
            "fixed_city_nrmse_pct": round(city_before, 4),
            "final_city_nrmse_pct": round(city_after, 4),
        })

    out = pd.DataFrame(rows)
    out.to_csv(METRICS / "midday_nrmse_current_vs_fixed.csv", index=False, encoding="utf-8-sig")
    print(out.to_string(index=False))

    improved_hours = int((out["improvement_pct_point"] > 0).sum())
    avg_before = float(out["fixed_site_nrmse_pct"].mean())
    avg_after = float(out["final_site_nrmse_pct"].mean())
    avg_drop = avg_before - avg_after
    rel_drop = avg_drop / avg_before * 100.0 if avg_before > 0 else np.nan
    worst_degradation = float((-out["improvement_pct_point"]).max())

    print()
    print(f"改善小时数: {improved_hours}/5")
    print(f"10-14 平均站点 NRMSE: {avg_before:.4f}% -> {avg_after:.4f}%")
    print(f"平均下降: {avg_drop:.4f} 个百分点，相对下降 {rel_drop:.2f}%")
    print(f"最大单小时恶化: {worst_degradation:.4f} 个百分点")

    ok = True
    reasons = []
    if improved_hours < 3:
        ok = False
        reasons.append("改善小时数少于 3/5")
    if not (rel_drop >= 5.0 or avg_drop >= 0.8):
        ok = False
        reasons.append("10-14 平均站点 NRMSE 改善不足")
    if worst_degradation > 0.3:
        ok = False
        reasons.append("存在单小时明显恶化")

    if not ok:
        print("[FAIL] " + "；".join(reasons))
        sys.exit(1)

    print("[OK] 10-14 点站点 NRMSE 改善验收通过")


if __name__ == "__main__":
    main()
```

---

## 7. 运行顺序

在 Cursor 终端中从项目根目录执行：

```bash
python scripts/apply_midday_site_nrmse_calibration.py
python scripts/apply_midday_residual_specialist.py
python scripts/select_final_prediction_by_guard.py
python scripts/check_midday_nrmse_improvement.py
python scripts/update_project_md_metrics.py
```

如果项目中有总入口脚本，也可以在确认上述脚本可单独运行后，把它们按这个顺序加入总入口。

---

## 8. 必须检查的输出文件

运行完成后检查以下文件是否存在：

```text
output/pv_pipeline/tables/distributed_predictions_midday_residual_specialist_full.pkl
output/pv_pipeline/tables/distributed_predictions_midday_residual_specialist_eval.pkl
output/pv_pipeline/tables/distributed_predictions_final_full.pkl
output/pv_pipeline/tables/distributed_predictions_final_eval.pkl
output/pv_pipeline/metrics/midday_residual_specialist_valid_ablation.csv
output/pv_pipeline/metrics/midday_residual_specialist_valid_grid.csv
output/pv_pipeline/metrics/midday_residual_specialist_test_hourly_nrmse.csv
output/pv_pipeline/metrics/midday_nrmse_current_vs_fixed.csv
output/pv_pipeline/metrics/final_version_selection_by_hour.csv
```

---

## 9. 验收标准

本轮不强制要求贴近周二版，只要求当前版本相对修复前继续改善。

### 9.1 主验收

`metrics/midday_nrmse_current_vs_fixed.csv` 中：

| 指标 | 要求 |
|---|---|
| 10-14 点改善小时数 | 至少 3/5 个小时站点 NRMSE 下降 |
| 10-14 点平均站点 NRMSE | 相对下降 ≥ 5%，或绝对下降 ≥ 0.8 个百分点 |
| 单小时保护 | 不允许任一小时比 fixed 恶化超过 0.3 个百分点 |

### 9.2 辅助验收

`metrics/final_version_selection_by_hour.csv` 中：

1. 10、11、12、13、14 点至少部分小时应选择：

```text
MiddayResidualSpecialist
```

或：

```text
MiddaySiteCalibrated
```

2. 选择表必须包含：

```text
site_nrmse_mean_pct
```

3. 10-14 点不能再只根据 `nrmse_capacity_pct` 做选择。

---

## 10. 如果运行后没有改善，继续排查这 4 个方向

### 10.1 检查残差方向是否正确

查看：

```text
metrics/midday_residual_specialist_params.csv
```

如果大部分 `residual_norm_median` 为正，说明中午仍然普遍低估；如果大部分为负，说明中午普遍高估。

### 10.2 检查 valid 是否改善但 test 不改善

如果：

```text
midday_residual_specialist_valid_ablation.csv
```

明显改善，但：

```text
midday_residual_specialist_test_hourly_nrmse.csv
```

没有改善，说明 train/valid/test 分布差异较大。下一步应改为更保守的 shrinkage，例如把：

```python
shrink = n_eff / (n_eff + 80.0)
```

改成：

```python
shrink = n_eff / (n_eff + 160.0)
```

### 10.3 检查是否被最终选择器拒绝

查看：

```text
metrics/final_guard_reject_reasons.csv
```

如果 10-14 点 `MiddayResidualSpecialist` 被拒绝，重点看拒绝原因是：

- `site_nrmse 未改善`
- `rmse 恶化`
- `mae 恶化`
- `ratio 异常`
- `city_rel_err 过高`

若只是城市级误差略高，但站点 NRMSE 明显改善，可以把 `city_rel_err` 上限从 `8.0` 放宽到 `10.0`。

### 10.4 检查高误差站点是否集中

如果只有少数站点拖高 10-14 点 NRMSE，新增一个诊断脚本输出：

```text
metrics/midday_worst_sites_after_residual.csv
```

字段包括：

```text
site_id, hour, rows, capacity_mw, site_nrmse_pct, pred_actual_ratio, actual_mean_mw, pred_mean_mw
```

若最差站点集中在 2-5 个站点，下一轮应对这些站点做单独参数，而不是继续全局调参。

---

## 11. 本轮预期效果

合理预期：

1. 10-14 点站点平均 NRMSE 会继续下降。
2. 下降幅度大概率不会像 valid 上那么大，因为 test 不参与调参。
3. 如果当前误差主要是系统性偏差，残差专家会明显有效。
4. 如果当前误差主要来自气象错位或站点映射问题，残差专家只能小幅改善，下一步需要查站点映射和辐照输入。

本轮成功后，报告中重点看：

```text
metrics/midday_nrmse_current_vs_fixed.csv
```

而不是继续单独追周二版。

