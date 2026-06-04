# Cursor 执行指令：将站点空间分布图图例移入地图黑色边框内部

## 目标

当前正式图：

```bash
output/pv_pipeline/figures/lianyungang_station_spatial_distribution_ppt.png
```

图例位于地图黑色边框外侧右下角，容易破坏版面完整性。请将图例移动到地图黑色边框内部，放在右下角空白区域内。

本轮只修改图例位置和图例样式，不修改站点筛选、点位坐标、异常站点规则、地图配准参数。

---

## 一、修改文件

修改：

```bash
scripts/plot_station_spatial_distribution.py
```

---

## 二、确认地图内框参数

脚本中应已有类似配置：

```python
MAP_INNER_BOX = {
    "x_min": 110,
    "x_max": 2110,
    "y_min": 130,
    "y_max": 1460,
}
```

如果字段名不同，请使用当前脚本中的地图黑框内边界变量。

图例位置必须基于 `MAP_INNER_BOX` 计算，不要写死到整张图片右下角。

---

## 三、修改正式图图例位置

找到正式图绘制图例的函数，例如：

```python
draw_legend(draw, x, y)
```

或：

```python
draw_legend(draw, width - 410, height - 185)
```

将正式图图例位置改为地图黑框内部右下角。

建议新增函数：

```python
def get_inner_legend_position(legend_w: int, legend_h: int, margin: int = 28):
    x = MAP_INNER_BOX["x_max"] - legend_w - margin
    y = MAP_INNER_BOX["y_max"] - legend_h - margin
    return int(x), int(y)
```

正式 PPT 图调用：

```python
legend_w = 330
legend_h = 120
legend_x, legend_y = get_inner_legend_position(legend_w, legend_h, margin=32)
draw_legend(draw, legend_x, legend_y, legend_w=legend_w, legend_h=legend_h, mode="ppt")
```

如果当前 `draw_legend()` 不支持宽高参数，请改造为：

```python
def draw_legend(draw, x, y, legend_w=330, legend_h=120, mode="ppt"):
    draw.rounded_rectangle(
        (x, y, x + legend_w, y + legend_h),
        radius=12,
        fill=(255, 255, 255, 225),
        outline=(120, 150, 170, 210),
        width=2,
    )
    draw.text((x + 22, y + 14), "图例", font=FONT_LABEL, fill=(30, 55, 75))

    draw.ellipse((x + 26, y + 58, x + 44, y + 76), fill="#E74C3C", outline="white", width=2)
    draw.text((x + 58, y + 54), "集中式光伏站点", font=FONT_SMALL, fill=(35, 35, 35))

    draw.ellipse((x + 26, y + 88, x + 44, y + 106), fill="#1F77B4", outline="white", width=2)
    draw.text((x + 58, y + 84), "分布式光伏站点", font=FONT_SMALL, fill=(35, 35, 35))
```

---

## 四、核查图图例也放入黑框内部

如果脚本同时输出：

```bash
output/pv_pipeline/figures/lianyungang_station_spatial_distribution_audit.png
```

核查图图例也放入黑框内部右下角，但可以稍微更高一些，避免遮挡核查标注。

建议：

```python
legend_w = 380
legend_h = 180
legend_x, legend_y = get_inner_legend_position(legend_w, legend_h, margin=32)
draw_audit_legend(draw, legend_x, legend_y)
```

正式图和核查图不要使用图片外部坐标：

```python
width - 410
height - 185
```

这种写法必须删除或只用于没有 `MAP_INNER_BOX` 的兜底情况。

---

## 五、避免遮挡地图自带图例

当前底图左下角已有原始地图图例，因此不要把自定义图例放到左下角。

推荐位置：

```text
地图黑框内部右下角，略高于底部黑框 30 px，略左于右侧黑框 30 px
```

如果右下角遮挡站点较多，可以改为：

```python
legend_x = MAP_INNER_BOX["x_max"] - legend_w - 36
legend_y = MAP_INNER_BOX["y_max"] - legend_h - 80
```

---

## 六、运行命令

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
python scripts/plot_station_spatial_distribution.py
```

检查输出：

```bash
ls -lh output/pv_pipeline/figures/lianyungang_station_spatial_distribution_ppt.png
ls -lh output/pv_pipeline/figures/lianyungang_station_spatial_distribution_audit.png
```

---

## 七、验收标准

必须满足：

1. `lianyungang_station_spatial_distribution_ppt.png` 中图例位于黑色地图边框内部。
2. 图例不再超出黑色边框。
3. 图例不遮挡左下角原始地图图例。
4. 图例不遮挡主要站点密集区。
5. 正式图中图例只包含：

```text
集中式光伏站点
分布式光伏站点
```

6. 本轮不改变站点数量、不改变点位坐标、不改变异常站点剔除规则。

---

## 八、建议额外加一个位置断言

在绘制图例后增加断言，防止以后图例又跑到黑框外：

```python
assert MAP_INNER_BOX["x_min"] <= legend_x <= MAP_INNER_BOX["x_max"]
assert MAP_INNER_BOX["y_min"] <= legend_y <= MAP_INNER_BOX["y_max"]
assert legend_x + legend_w <= MAP_INNER_BOX["x_max"]
assert legend_y + legend_h <= MAP_INNER_BOX["y_max"]
```

如果断言失败，说明图例位置仍在地图黑框外，必须调整 `legend_w/legend_h/margin`。
