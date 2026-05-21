from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pv_forecasting.core.runtime import build_parser, make_paths
from pv_forecasting.tasks.irradiance_blend import infer_site_irradiance, prepare_blend_training, train_blend_model


def main():
    parser = build_parser("Train irradiance blend model")
    args = parser.parse_args()
    paths = make_paths(PROJECT_ROOT, args)

    site_master = pd.read_csv(paths.tables / "site_master.csv")
    inverse_pred = pd.read_pickle(paths.tables / "inverse_predictions.pkl")
    site_meteo = pd.read_pickle(paths.tables / "site_meteo.pkl")

    blend_train = prepare_blend_training(inverse_pred, site_master)
    blend_train.to_pickle(paths.tables / "blend_train_table.pkl")
    bundle, metrics_df, pred_df = train_blend_model(blend_train, paths.models / "irradiance_blend_model.pkl", paths.metrics / "irradiance_blend_metrics.csv")
    pred_df.to_pickle(paths.tables / "blend_validation_predictions.pkl")
    site_irr = infer_site_irradiance(inverse_pred, site_master, site_meteo, bundle)
    site_irr.to_pickle(paths.tables / "site_irradiance.pkl")
    print(metrics_df)


if __name__ == "__main__":
    main()
