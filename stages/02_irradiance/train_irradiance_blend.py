from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pv_forecasting.core.runtime import build_parser, make_paths
from pv_forecasting.tasks.irradiance_blend import infer_site_irradiance, prepare_blend_training, train_blend_model
from pv_forecasting.core.progress import stage_log


def main():
    parser = build_parser("Train irradiance blend model")
    args = parser.parse_args()
    paths = make_paths(PROJECT_ROOT, args)

    stage_log("[4.1] 加载数据并构建辐照融合训练样本")
    site_master = pd.read_csv(paths.tables / "site_master.csv")
    inverse_pred = pd.read_pickle(paths.tables / "inverse_predictions.pkl")
    site_meteo = pd.read_pickle(paths.tables / "site_meteo.pkl")

    stage_log("[4.1] 构建辐照融合训练样本")
    blend_train = prepare_blend_training(inverse_pred, site_master)
    blend_train.to_pickle(paths.tables / "blend_train_table.pkl")

    stage_log("[4.2] 训练辐照融合模型")
    bundle, metrics_df, pred_df = train_blend_model(blend_train, paths.models / "irradiance_blend_model.pkl", paths.metrics / "irradiance_blend_metrics.csv")
    pred_df.to_pickle(paths.tables / "blend_validation_predictions.pkl")

    stage_log("[4.3] 推断分布式站点辐照")
    site_irr = infer_site_irradiance(inverse_pred, site_master, site_meteo, bundle)
    site_irr.to_pickle(paths.tables / "site_irradiance.pkl")

    stage_log("[4.4] 保存辐照融合结果")
    print(metrics_df.to_string(index=False))


if __name__ == "__main__":
    main()
