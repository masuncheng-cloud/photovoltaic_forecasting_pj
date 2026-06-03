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

页面支持全市/单站点真实值与预测值对比、典型站点选择、10-14 点典型时段、四季代表日、逐小时预测结果（站点平均 NRMSE 与城市 NRMSE）、单站点全量历史样本数与测试集 NRMSE 关系散点图。

散点图默认使用"单站点全量历史样本数"作为横轴，测试集站点 NRMSE 作为纵轴。全量历史样本数来自 `distributed_predictions_final_full.pkl`，包含该站点所有小时、所有 split（train/valid/test/future）的全部记录；测试 NRMSE 仍固定使用 test 集 6-19 点。
