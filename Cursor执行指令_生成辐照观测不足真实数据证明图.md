# Cursor 执行指令：生成“分布式光伏站点缺少连续辐照观测”的真实数据证明图

## 目标

不要再画卡通示意图。基于当前项目真实数据，生成一张 PPT 可用的正方形图，用数据证明：

> 分布式光伏站点普遍有功率记录，但缺少连续实测辐照观测。

实际代码运行目录：

```bash
/home/ac/data16t/msc/photovoltaic_forecasting_pj
```

输出图：

```bash
output/pv_pipeline/ppt_figures/background/分布式站点辐照观测不足_真实数据证明图.png
```

输出统计表：

```bash
output/pv_pipeline/ppt_figures/background/分布式站点辐照观测不足_统计表.csv
```

---

## 一、图形设计要求

图不要卡通化，不要流程箭头，不要大标题，不要说明句。

采用 **数据证据型图表**：

- 左侧：有功率记录的分布式站点数量
- 中间：有 ERA5 / 融合辐照特征的站点数量
- 右侧：有连续实测辐照观测的站点数量

图形建议：

- 正方形画布，白底
- 使用竖向柱状图或点阵柱状图
- 颜色克制：
  - 功率记录：蓝灰色
  - ERA5 / 融合辐照：青绿色
  - 连续实测辐照：红色
- 每个柱子上方标出真实数量
- 不写长句，只保留短标签
- 图中允许出现：
  - “功率记录”
  - “ERA5 / 融合辐照”
  - “连续实测辐照”
  - “站点数”

---

## 二、统计逻辑

### 1. 有功率记录站点

优先从以下文件读取：

```text
output/pv_pipeline/predictions/distributed_predictions_final_full.pkl
output/pv_pipeline/tables/power_clean.pkl
output/pv_pipeline/tables/distributed_train_table_v159.pkl
```

统计有 `site_id` 且存在 `power_mw` 或预测/功率记录列的站点数。

### 2. 有 ERA5 / 融合辐照特征站点

优先从以下文件读取：

```text
output/pv_pipeline/tables/site_meteo.pkl
output/pv_pipeline/tables/blend_validation_predictions.pkl
output/pv_pipeline/tables/blend_train_table.pkl
output/pv_pipeline/tables/site_irradiance.pkl
```

统计包含以下字段之一的站点数：

```text
era5_pred
idw_pred
g_blend_pred
ghi
GHI
clear_sky_ghi
```

注意：这类数据只能说明“存在气象/融合辐照特征”，不能当作实测辐照。

### 3. 有连续实测辐照观测站点

扫描所有候选表，查找明确表示“实测辐照”的字段：

```text
measured_ghi
observed_ghi
obs_ghi
ghi_obs
real_ghi
measured_irradiance
observed_irradiance
irradiance_obs
实测辐照
观测辐照
辐照观测
```

如果不存在这些字段，连续实测辐照站点数记为 0。

如果存在这些字段，则按站点统计：

- 6—19 点
- 非 future
- 非空实测辐照样本
- 连续覆盖率达到 80% 以上，才认定为“有连续实测辐照观测”

---

## 三、新建脚本

新建：

```bash
scripts/plot_irradiance_observation_gap_evidence.py
```

写入以下代码：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成“分布式光伏站点缺少连续实测辐照观测”的真实数据证明图。

该脚本不画示意流程，而是扫描项目真实输出表：
1. 统计有功率记录的站点数；
2. 统计有 ERA5 / IDW / 融合辐照特征的站点数；
3. 统计有连续实测辐照观测字段且覆盖率达标的站点数。
"""

from __future__ import annotations

from pathlib import Path
import json
import re

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "pv_pipeline"
FIG_DIR = OUT_DIR / "ppt_figures" / "background"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def setup_font() -> None:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for p in candidates:
        if Path(p).exists():
            font_manager.fontManager.addfont(p)
            prop = font_manager.FontProperties(fname=p)
            plt.rcParams["font.family"] = prop.get_name()
            break
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.facecolor"] = "white"
    plt.rcParams["savefig.facecolor"] = "white"


def read_table(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path)
        if path.suffix.lower() in [".pkl", ".pickle"]:
            try:
                return pd.read_pickle(path)
            except TypeError:
                import pandas.core.arrays.string_ as string_mod
                cls = string_mod.StringDtype
                old_init = cls.__init__

                def patched_init(self, storage=None, na_value=pd.NA):
                    try:
                        old_init(self, storage=storage, na_value=na_value)
                    except TypeError:
                        old_init(self, storage=storage)

                cls.__init__ = patched_init
                return pd.read_pickle(path)
    except Exception as e:
        print(f"[WARN] 读取失败：{path} -> {type(e).__name__}: {e}")
        return None
    return None


def find_site_col(df: pd.DataFrame) -> str | None:
    for c in ["site_id", "station_id", "station_name", "站点ID", "站点名称"]:
        if c in df.columns:
            return c
    return None


def find_time_col(df: pd.DataFrame) -> str | None:
    for c in ["time", "datetime", "timestamp", "date_time"]:
        if c in df.columns:
            return c
    return None


def table_candidates() -> list[Path]:
    fixed = [
        OUT_DIR / "predictions" / "distributed_predictions_final_full.pkl",
        OUT_DIR / "predictions" / "distributed_predictions_final_eval.pkl",
        OUT_DIR / "tables" / "power_clean.pkl",
        OUT_DIR / "tables" / "distributed_train_table_v159.pkl",
        OUT_DIR / "tables" / "site_meteo.pkl",
        OUT_DIR / "tables" / "blend_validation_predictions.pkl",
        OUT_DIR / "tables" / "blend_train_table.pkl",
        OUT_DIR / "tables" / "site_irradiance.pkl",
        OUT_DIR / "tables" / "inverse_predictions.pkl",
        OUT_DIR / "tables" / "inverse_train_table.pkl",
        OUT_DIR / "tables" / "station_metadata_canonical.pkl",
        OUT_DIR / "tables" / "station_metadata_canonical.csv",
    ]
    extra = sorted((OUT_DIR / "tables").glob("*.pkl")) + sorted((OUT_DIR / "tables").glob("*.csv"))
    seen = []
    for p in fixed + extra:
        if p not in seen:
            seen.append(p)
    return seen


def count_sites_with_columns(col_patterns: list[str], require_daytime_coverage: bool = False) -> tuple[int, list[str], list[str]]:
    matched_sites: set[str] = set()
    matched_cols: list[str] = []
    matched_files: list[str] = []

    regexes = [re.compile(p, re.IGNORECASE) for p in col_patterns]

    for p in table_candidates():
        df = read_table(p)
        if df is None or df.empty:
            continue
        site_col = find_site_col(df)
        if site_col is None:
            continue

        hit_cols = []
        for c in df.columns:
            c_str = str(c)
            if any(r.search(c_str) for r in regexes):
                hit_cols.append(c)
        if not hit_cols:
            continue

        tmp = df.copy()
        if require_daytime_coverage:
            tcol = find_time_col(tmp)
            if tcol is not None:
                tmp["_dt"] = pd.to_datetime(tmp[tcol], errors="coerce")
                tmp["_hour"] = tmp["_dt"].dt.hour
                tmp = tmp[tmp["_hour"].between(6, 19)]
            if "is_future" in tmp.columns:
                tmp = tmp[~tmp["is_future"].fillna(False).astype(bool)]

        for col in hit_cols:
            val = pd.to_numeric(tmp[col], errors="coerce")
            sub = tmp[val.notna()].copy()
            if sub.empty:
                continue

            if require_daytime_coverage:
                # 连续实测辐照要求站点在可评价日间样本中覆盖率达到 80%。
                total = tmp.groupby(site_col).size()
                valid = sub.groupby(site_col).size()
                cov = (valid / total).replace([np.inf, -np.inf], np.nan).dropna()
                good_sites = cov[cov >= 0.80].index.astype(str).tolist()
                matched_sites.update(good_sites)
            else:
                matched_sites.update(sub[site_col].dropna().astype(str).unique().tolist())

            matched_cols.append(str(col))
            matched_files.append(str(p.relative_to(ROOT)))

    return len(matched_sites), sorted(set(matched_cols)), sorted(set(matched_files))


def count_power_sites() -> tuple[int, list[str]]:
    candidates = [
        OUT_DIR / "predictions" / "distributed_predictions_final_full.pkl",
        OUT_DIR / "tables" / "power_clean.pkl",
        OUT_DIR / "tables" / "distributed_train_table_v159.pkl",
    ]
    for p in candidates:
        df = read_table(p)
        if df is None or df.empty:
            continue
        site_col = find_site_col(df)
        if site_col is None:
            continue
        power_cols = [c for c in df.columns if str(c) in ["power_mw", "actual_mw", "power", "有功功率"] or "power" in str(c).lower()]
        if not power_cols:
            continue
        sites = sorted(df[site_col].dropna().astype(str).unique().tolist())
        if sites:
            return len(sites), [str(p.relative_to(ROOT))]
    return 0, []


def plot_evidence(counts: dict[str, int]) -> Path:
    labels = ["功率记录", "ERA5/融合辐照", "连续实测辐照"]
    values = [counts["power_sites"], counts["derived_irradiance_sites"], counts["measured_irradiance_sites"]]
    colors = ["#5b7794", "#4aa38f", "#d95f59"]

    fig, ax = plt.subplots(figsize=(7.2, 7.2), dpi=320)
    x = np.arange(len(labels))
    bars = ax.bar(x, values, width=0.56, color=colors, edgecolor="#2f3b4a", linewidth=0.8)

    ymax = max(max(values) * 1.28, 10)
    ax.set_ylim(0, ymax)
    ax.set_ylabel("站点数", fontsize=13, color="#2f3b4a")
    ax.set_xticks(x, labels, fontsize=12)
    ax.tick_params(axis="y", labelsize=11, colors="#4b5b6b")
    ax.grid(axis="y", linestyle="--", linewidth=0.8, alpha=0.28)
    ax.set_axisbelow(True)

    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + ymax * 0.025,
            f"{value}",
            ha="center",
            va="bottom",
            fontsize=21,
            color="#202b36",
            fontweight="bold",
        )

    # 用一个细红框强调实测辐照缺口，但不写解释长句。
    ax.annotate(
        "",
        xy=(2, values[2] + ymax * 0.01),
        xytext=(2, max(values[0], values[1]) * 0.88),
        arrowprops=dict(arrowstyle="<->", color="#d95f59", linewidth=2.0),
    )
    ax.text(2.08, max(values[0], values[1]) * 0.48, "观测缺口", rotation=90,
            ha="center", va="center", fontsize=12, color="#d95f59", fontweight="bold")

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color("#9aa9b8")
    ax.spines["bottom"].set_color("#9aa9b8")

    fig.tight_layout(pad=1.4)
    out = FIG_DIR / "分布式站点辐照观测不足_真实数据证明图.png"
    fig.savefig(out, bbox_inches="tight", pad_inches=0.10)
    plt.close(fig)
    return out


def main() -> None:
    setup_font()

    power_sites, power_files = count_power_sites()

    derived_patterns = [
        r"era5",
        r"idw",
        r"g_blend",
        r"blend_ghi",
        r"clear_sky_ghi",
        r"ghi$",
        r"irradiance",
    ]
    derived_sites, derived_cols, derived_files = count_sites_with_columns(derived_patterns, require_daytime_coverage=False)

    measured_patterns = [
        r"measured_ghi",
        r"observed_ghi",
        r"obs_ghi",
        r"ghi_obs",
        r"real_ghi",
        r"measured_irradiance",
        r"observed_irradiance",
        r"irradiance_obs",
        r"实测辐照",
        r"观测辐照",
        r"辐照观测",
    ]
    measured_sites, measured_cols, measured_files = count_sites_with_columns(measured_patterns, require_daytime_coverage=True)

    counts = {
        "power_sites": int(power_sites),
        "derived_irradiance_sites": int(derived_sites),
        "measured_irradiance_sites": int(measured_sites),
    }
    out = plot_evidence(counts)

    stat = pd.DataFrame([
        {
            "类别": "有功率记录站点",
            "站点数": counts["power_sites"],
            "判定依据": "site_id + power_mw/功率相关字段",
            "来源文件": "; ".join(power_files),
            "匹配字段": "power_mw / power*",
        },
        {
            "类别": "有ERA5或融合辐照特征站点",
            "站点数": counts["derived_irradiance_sites"],
            "判定依据": "ERA5/IDW/融合/晴空辐照等模型或气象特征字段",
            "来源文件": "; ".join(derived_files),
            "匹配字段": "; ".join(derived_cols),
        },
        {
            "类别": "有连续实测辐照观测站点",
            "站点数": counts["measured_irradiance_sites"],
            "判定依据": "明确实测辐照字段，且6-19点非future覆盖率>=80%",
            "来源文件": "; ".join(measured_files),
            "匹配字段": "; ".join(measured_cols),
        },
    ])
    csv_path = FIG_DIR / "分布式站点辐照观测不足_统计表.csv"
    stat.to_csv(csv_path, index=False, encoding="utf-8-sig")

    meta = {
        "counts": counts,
        "output_figure": str(out.relative_to(ROOT)),
        "output_table": str(csv_path.relative_to(ROOT)),
        "measured_patterns": measured_patterns,
        "derived_patterns": derived_patterns,
    }
    meta_path = FIG_DIR / "分布式站点辐照观测不足_证明图_metadata.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] figure: {out}")
    print(f"[OK] table: {csv_path}")
    print(stat.to_string(index=False))


if __name__ == "__main__":
    main()
```

---

## 四、执行

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj

python scripts/plot_irradiance_observation_gap_evidence.py
```

---

## 五、验收

执行：

```bash
python - <<'PY'
from pathlib import Path
import pandas as pd

root = Path("/home/ac/data16t/msc/photovoltaic_forecasting_pj")
fig = root / "output/pv_pipeline/ppt_figures/background/分布式站点辐照观测不足_真实数据证明图.png"
csv = root / "output/pv_pipeline/ppt_figures/background/分布式站点辐照观测不足_统计表.csv"

if not fig.exists() or fig.stat().st_size < 50_000:
    raise SystemExit("图文件不存在或过小。")
if not csv.exists():
    raise SystemExit("统计表未生成。")

df = pd.read_csv(csv)
print(df.to_string(index=False))

required = ["有功率记录站点", "有ERA5或融合辐照特征站点", "有连续实测辐照观测站点"]
if not set(required).issubset(set(df["类别"])):
    raise SystemExit("统计类别不完整。")

power = int(df.loc[df["类别"] == "有功率记录站点", "站点数"].iloc[0])
measured = int(df.loc[df["类别"] == "有连续实测辐照观测站点", "站点数"].iloc[0])

if power <= 0:
    raise SystemExit("功率站点数异常。")
if measured > power:
    raise SystemExit("实测辐照站点数不能大于功率站点数。")

print("[PASS] 真实数据证明图生成完成。")
PY
```

---

## 六、PPT 使用建议

这张图用于支撑项目背景中的第二点：

> 分布式光伏站点普遍缺少连续辐照观测。

PPT 页面文字中可以写：

```text
分布式光伏站点虽具备功率记录，但连续实测辐照观测覆盖不足，站点真实光照条件无法直接获得。
```

不要把 ERA5 或融合辐照说成“实测辐照”。图中“ERA5 / 融合辐照”只表示项目通过气象与模型方法补足了辐照特征。

