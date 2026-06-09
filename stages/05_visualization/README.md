生成中文训练看板和结果诊断图。

## 交互式预测结果页面

### 启动本地服务

```bash
# 1. 进入项目根目录（自动定位）
cd "$(dirname "$(python3 -c "import pathlib; print(pathlib.Path('scripts/run_full_pipeline.py').resolve().parents[0].parent)"))"

# 2. 启动本地 HTTP 服务（端口 8070）
python3 -m http.server 8070

# 3. 浏览器打开
# http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html
```

### 停止服务

```bash
# 前台启动时
Ctrl+C

# 如果是后台残留进程
pkill -f "http.server 8070"
```

### 重新导出数据

重新训练或重新导出可视化数据后：

```bash
python3 scripts/export_interactive_dashboard_data.py
```

然后浏览器强制刷新即可：

```bash
Ctrl + Shift + R
```

或者加版本参数访问：

```bash
http://127.0.0.1:8070/stages/05_visualization/interactive_forecast_dashboard.html?v=latest
```

注意：不要直接双击 HTML 文件打开，因为页面需要读取 `output/pv_pipeline/interactive_dashboard/` 里的 JSON 数据，直接用 `file://` 打开时浏览器通常会拦截数据读取，导致图表不显示。

---

页面支持全市/单站点真实值与预测值对比、典型站点选择、10-14 点典型时段、四季代表日、逐小时预测结果（站点平均 NRMSE 与城市 NRMSE）、单站点全量历史样本数与测试集 NRMSE 关系散点图。

散点图默认使用"单站点全量历史样本数"作为横轴，测试集站点 NRMSE 作为纵轴。全量历史样本数来自 `distributed_predictions_final_full.pkl`，包含该站点所有小时、所有 split（train/valid/test/future）的全部记录；测试 NRMSE 仍固定使用 test 集 6-19 点。
