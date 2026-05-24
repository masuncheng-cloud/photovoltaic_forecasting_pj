生成中文训练看板和结果诊断图。

## 交互式预测结果页面

生成数据：

```bash
cd /home/ac/data16t/msc/photovoltaic_forecasting_pj
/home/mjj/anaconda3/bin/python3 scripts/export_interactive_dashboard_data.py \
  --output-root output/pv_pipeline \
  --dashboard-root output/pv_pipeline/interactive_dashboard
```

启动本地服务：

```bash
python -m http.server 8060
```

浏览器打开：

```
http://127.0.0.1:8060/stages/05_visualization/interactive_forecast_dashboard.html
```

页面支持全市/单站点真实值与预测值对比、典型站点选择、10-14 点典型时段、四季代表日、误差-样本量散点图。
