# Cursor 执行指令：站点空间分布图正式版收口与人工复核清单

## 目标

当前站点空间分布图仍存在：

- `沿海灌云光伏` 等点位落在海面上；
- `华电曲阳光伏电站` 等点位看起来超出连云港市界；
- `station_spatial_audit.csv` 已经标记了部分 `coastal_review`，但正式 PPT 图仍然把这些点画出来；
- `华电曲阳光伏电站` 在核查表中被判为 `ok`，没有进入异常清单。

本轮目标不是继续微调地图，而是把“正式汇报图”和“内部核查图”的口径彻底分开：

1. **正式 PPT 图只展示无争议站点**；
2. **疑似海上、边界外观争议、名称争议站点全部进入人工复核清单**；
3. **核查图保留所有点，并用不同符号说明为什么被排除**；
4. **正式图不能再出现明显在海里或明显越界的点**。

---

## 一、当前 CSV 诊断结论

从当前 `station_spatial_audit.csv` 看：

```text
ok                  97
coastal_review      17
exclude_from_ppt     1
```

问题在于：正式图仍绘制了 `coastal_review`。

例如：

```text
S097 沿海灌云光伏 centralized 灌云县 119.568298 34.686101 coastal_review
```

该站点已经被像素颜色判定为疑似海上点，但仍进入正式图，所以正式图上会看到红点在海里。

另一个问题：

```text
S096 华电曲阳光伏发电站 centralized 东海县 118.683060 34.425000 ok
```

该站点虽然经纬度在粗略 bbox 内，但从底图视觉上看容易被认为越过连云港市界，因此应进入人工复核名单，不应直接作为正式 PPT 图点位展示。

---

## 二、修改脚本

修改：

```bash
scripts/plot_station_spatial_distribution.py
```

如果当前脚本里已有 `audit_status`，在其基础上继续修改；不要重写整个脚本。

---

## 三、新增正式图保留规则

新增配置：

```python
# 正式 PPT 图中只展示无争议站点。
# coastal_review 不再进入正式图，只进入核查图。
PPT_ALLOWED_STATUS = {"ok"}

# 用户人工指定需要复核或不进入正式图的站点。
# 这些站点不代表一定错误，只表示当前地图底图上展示容易引起误解。
MANUAL_REVIEW_SITE_IDS = {
    "S097",  # 沿海灌云光伏：当前落在海面，需核验坐标/底图配准/是否为海上或滩涂项目
    "S096",  # 华电曲阳光伏发电站：当前视觉上接近或越过市界，需核验
}

MANUAL_REVIEW_KEYWORDS = [
    "沿海灌云",
    "华电曲阳",
]
```

---

## 四、修改 audit_status 规则

在生成 `station_spatial_audit.csv` 时，增加人工复核状态：

```python
def apply_manual_review_rules(df):
    manual_mask = (
        df["station_id"].astype(str).isin(MANUAL_REVIEW_SITE_IDS)
        | df["station_name"].astype(str).apply(
            lambda x: any(k in x for k in MANUAL_REVIEW_KEYWORDS)
        )
    )

    df.loc[manual_mask, "audit_status"] = "manual_review"
    df.loc[manual_mask, "audit_reason"] = (
        df.loc[manual_mask, "audit_reason"].fillna("").astype(str)
        + "人工指定复核：当前底图展示位置存在海上或市界外观争议；"
    )
    return df
```

调用位置必须在所有自动规则之后、写出 CSV 之前：

```python
stations = apply_manual_review_rules(stations)
```

---

## 五、正式 PPT 图只画 ok 站点

找到正式 PPT 图绘制逻辑，修改为：

```python
if ppt_style:
    plot_df = stations[stations["audit_status"].isin(PPT_ALLOWED_STATUS)].copy()
else:
    plot_df = stations.copy()
```

也就是说：

- `lianyungang_station_spatial_distribution_ppt.png`：只画 `ok`。
- `lianyungang_station_spatial_distribution.png`：可画 `ok + manual_review`，但建议用不同标记。
- `lianyungang_station_spatial_distribution_audit.png`：画全部站点。

注意：正式 PPT 图不要再画 `coastal_review` 和 `manual_review`。

---

## 六、核查图中明确标记不同状态

核查图中使用以下规则：

| 状态 | 图形 |
|---|---|
| `ok` | 原有蓝点/红点 |
| `coastal_review` | 橙色空心圆 |
| `manual_review` | 紫色空心菱形或紫色空心圆 |
| `exclude_from_ppt` | 灰色叉号 |

建议颜色：

```python
STATUS_STYLE = {
    "ok": {"outline": "white"},
    "coastal_review": {"outline": "#FF8C00"},
    "manual_review": {"outline": "#8E44AD"},
    "exclude_from_ppt": {"outline": "#666666"},
}
```

核查图中必须给 `coastal_review/manual_review/exclude_from_ppt` 标注站点名称，方便人工复核。

---

## 七、异常清单输出规则

当前 `station_spatial_outliers.csv` 只输出了 `exclude_from_ppt`，太少。

修改为输出所有非 `ok` 状态：

```python
outliers = stations[stations["audit_status"] != "ok"].copy()
outliers.to_csv(OUT_OUTLIERS, index=False, encoding="utf-8-sig")
```

输出字段至少包含：

```text
station_id
station_name
plot_type
capacity_mw
county
longitude
latitude
plot_x
plot_y
audit_status
audit_reason
source_file
```

这样 `沿海灌云光伏` 和 `华电曲阳光伏电站` 必须都出现在 `station_spatial_outliers.csv` 中。

---

## 八、正式图标题和图例同步修改

正式 PPT 图标题建议改为：

```text
连云港光伏站点空间分布图
```

图例只保留：

```text
集中式光伏站点
分布式光伏站点
```

不要在正式 PPT 图图例中出现：

```text
沿海待核验站点
人工复核站点
```

这些只出现在核查图中。

核查图标题改为：

```text
连云港光伏站点空间分布图（核查版）
```

核查图图例包含：

```text
集中式光伏站点
分布式光伏站点
沿海待核验站点
人工复核站点
剔除站点
```

---

## 九、运行命令

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
python scripts/plot_station_spatial_distribution.py
```

然后检查：

```bash
ls -lh output/pv_pipeline/figures/lianyungang_station_spatial_distribution*.png
python - <<'PY'
import pandas as pd
base = "output/pv_pipeline/figures"
audit = pd.read_csv(f"{base}/station_spatial_audit.csv")
out = pd.read_csv(f"{base}/station_spatial_outliers.csv")
print("audit_status counts:")
print(audit["audit_status"].value_counts(dropna=False))
print("\nmanual/coastal examples:")
print(out[out["station_name"].astype(str).str.contains("沿海灌云|华电曲阳", na=False)][
    ["station_id", "station_name", "plot_type", "county", "longitude", "latitude", "audit_status", "audit_reason"]
].to_string(index=False))
PY
```

必须看到：

```text
S097 沿海灌云光伏 manual_review 或 coastal_review
S096 华电曲阳光伏发电站 manual_review
```

并且二者都必须出现在：

```bash
output/pv_pipeline/figures/station_spatial_outliers.csv
```

---

## 十、验收标准

本轮完成后验收：

1. `lianyungang_station_spatial_distribution_ppt.png` 中不再出现海面上的 `沿海灌云光伏` 红点。
2. `lianyungang_station_spatial_distribution_ppt.png` 中不再出现视觉上明显超出市界的 `华电曲阳光伏电站`。
3. `station_spatial_outliers.csv` 中包含 `沿海灌云光伏` 和 `华电曲阳光伏电站`。
4. `lianyungang_station_spatial_distribution_audit.png` 中保留这些点，并用人工复核/沿海待核验符号标注。
5. 正式 PPT 图只展示通过核查的站点，不展示待核验点。

---

## 十一、重要说明

`华电曲阳光伏电站` 不一定真实不属于连云港，因为台账中区县为 `东海县`，而东海县属于连云港市。本轮把它移出正式图，是因为在当前截图底图和线性配准方式下，视觉上容易被认为越界。

正式汇报图优先保证“不出现明显争议点”。内部核查图和 CSV 保留完整信息，后续可通过标准行政区 GeoJSON 或人工核验重新决定是否恢复到正式图。

长期建议：后续不要依赖截图底图 + 经纬度线性映射，改为 `GeoJSON 行政边界 + geopandas` 的标准 GIS 绘图。
